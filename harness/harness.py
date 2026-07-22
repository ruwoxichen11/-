"""The harness: enforces context isolation, binds each round's real results,
runs mechanical checks, limits repair scope, retests and rolls back, and keeps a
full audit trail. The AI does understanding & judgement; the harness does what can
be repeated and checked.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import checks, retrieval_engine
from .llm_client import LLMClient
from .schema import (
    Action, Candidate, CheckReport, DraftResult, Edit, Idea, Problem,
    QueryPlan, RepairProposal, RoundRecord, RubricItem, Spec,
)

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


class Harness:
    def __init__(self, backend: str | None = None, threshold: float = 0.6,
                 max_rounds: int = 4):
        self.llm = LLMClient(backend=backend)
        self.threshold = threshold
        self.max_rounds = max_rounds
        self.records: list[RoundRecord] = []
        self.run_dir = RUNS_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    # === 1. context isolation ============================================
    def prepare_spec_input(self, idea: Idea) -> dict:
        """Spec stage sees ONLY the verified idea -- no history, no drafts."""
        return {"idea": idea.text, "verified_facts": []}

    def prepare_writer_plan_input(self, idea: Idea, spec: Spec) -> dict:
        """Writer sees the idea + proposition, but NEVER the rubric (blind test)."""
        return {"idea": idea.text, "proposition": spec.proposition}

    def prepare_writer_draft_input(self, idea: Idea, spec: Spec,
                                   plan: QueryPlan, candidates: list[Candidate]) -> dict:
        """Stage two: same writer, given this round's candidates only. Still no rubric."""
        return {
            "idea": idea.text,
            "proposition": spec.proposition,
            "outline": plan.outline,
            "candidates": [{"cid": c.cid, "kind": c.kind, "content": c.content}
                           for c in candidates],  # note: no engine scores handed to writer
        }

    # === 2. two-stage retrieval, bound to this round =====================
    def verify_binding(self, plan: QueryPlan, candidates: list[Candidate]) -> None:
        """Guard query format / info-leak; results must be engine-produced."""
        if not plan.queries:
            raise ValueError("binding: writer submitted no queries")
        if len(plan.queries) > 6:
            raise ValueError("binding: too many queries (possible field-copying)")
        # the model must not have invented candidates/scores
        for c in candidates:
            if c.score < 0:
                raise ValueError("binding: negative score is impossible from engine")

    def verify_assessment(self, result: DraftResult, candidates: list[Candidate]) -> list[str]:
        return checks.verify_evidence_grounded(result, candidates)

    # === 3. mechanical checks & routing ==================================
    def run_check(self, result: DraftResult, spec: Spec,
                  candidates: list[Candidate]) -> CheckReport:
        return checks.run_full_check(result, spec, candidates, self.threshold)

    def verify_evidence_and_route(self, decision: dict, check: CheckReport) -> None:
        """Refuse continuation if the model's conclusion contradicts checkable facts,
        and block wrong repair routing (idea/spec/material issues must not go semantic)."""
        problem = decision.get("problem")
        action = decision.get("next_action")

        # consistency between problem and action
        allowed = {
            Problem.SEMANTIC.value: {Action.REPAIR.value},
            Problem.DRAFT.value: {Action.REWRITE.value},
            Problem.SPEC.value: {Action.RESPEC.value, Action.ESCALATE.value},
            Problem.IDEA.value: {Action.RESPEC.value, Action.ESCALATE.value},
            Problem.MATERIAL.value: {Action.ADD_MATERIAL.value},
            Problem.NONE.value: {Action.FINISH.value},
        }
        if problem in allowed and action not in allowed[problem]:
            raise ValueError(f"routing: problem='{problem}' inconsistent with action='{action}'")

        # model claims 'none/finish' but checks failed -> contradiction, refuse
        if action == Action.FINISH.value and not check.passed:
            raise ValueError("routing: model wants to finish but mechanical checks failed")

    # === 4. scope-limited repair, retest & rollback ======================
    ALLOWED_REPAIR = {"register", "wording", "term", "transition", "hedging", "structure_link"}

    def apply_allowed_semantics(self, proposal: RepairProposal, draft: str,
                                spec: Spec, candidates: list[Candidate]) -> tuple[str, list[str]]:
        """Apply only edits that pass scope + anti-cheat checks. Return new draft + rejected."""
        rejected: list[str] = []
        new_draft = draft
        for e in proposal.edits:
            revised = e.revised
            # reject copying rubric verbatim
            if any(len(r.requirement) >= 12 and r.requirement in revised for r in spec.rubric):
                rejected.append("edit copies rubric text -> rejected")
                continue
            # reject writing internal identifiers
            ids = [c.cid for c in candidates] + [r.id for r in spec.rubric]
            if any(cid in revised for cid in ids):
                rejected.append("edit writes internal identifier -> rejected")
                continue
            # reject keyword stacking
            if any(revised.count(w) >= 3 for w in checks.STACK_WATCH):
                rejected.append("edit stacks filler keywords -> rejected")
                continue
            if e.locate and e.locate in new_draft:
                new_draft = new_draft.replace(e.locate, revised, 1)
            else:
                # if we cannot locate safely, do not blindly append
                rejected.append(f"edit locator not found, skipped: {e.locate[:20]}")
        return new_draft, rejected

    def verify_retest(self, check: CheckReport) -> bool:
        return check.passed

    # === run one full round ==============================================
    def run_round(self, idea: Idea, round_id: int) -> RoundRecord:
        # --- spec (isolated) ---
        spec_raw = self.llm.complete_json("spec", self.prepare_spec_input(idea))
        spec = Spec(
            proposition=spec_raw.get("proposition", ""),
            needs_clarification=spec_raw.get("needs_clarification", False),
            clarification=spec_raw.get("clarification", ""),
            rubric=[RubricItem(**r) for r in spec_raw.get("rubric", [])],
        )

        # --- writer stage 1: plan + queries (blind, no rubric) ---
        plan_raw = self.llm.complete_json("writer", self.prepare_writer_plan_input(idea, spec))
        plan = QueryPlan(outline=plan_raw.get("outline", []),
                         queries=plan_raw.get("queries", []))

        # --- engine executes the shortlist ---
        candidates = retrieval_engine.search("current_index", plan.queries)
        self.verify_binding(plan, candidates)

        # --- writer stage 2: draft from this round's candidates ---
        draft_raw = self.llm.complete_json(
            "writer", self.prepare_writer_draft_input(idea, spec, plan, candidates))
        result = DraftResult(
            mode=draft_raw.get("mode", "draft"),
            draft=draft_raw.get("draft", ""),
            clarification=draft_raw.get("clarification", ""),
            evidence=draft_raw.get("evidence", []),
        )
        self.verify_assessment(result, candidates)

        # --- mechanical checks ---
        check = self.run_check(result, spec, candidates)

        # --- blind test ends: orchestrator now sees rubric + actual draft ---
        decision = self.llm.complete_json("orchestrator", {
            "idea": idea.text,
            "proposition": spec.proposition,
            "rubric": [asdict(r) for r in spec.rubric],
            "draft": result.draft,
            "check": check.as_dict(),
        })
        self.verify_evidence_and_route(decision, check)

        record = RoundRecord(
            round_id=round_id, idea=idea.text,
            spec={"proposition": spec.proposition,
                  "rubric": [asdict(r) for r in spec.rubric]},
            query_plan=asdict(plan),
            candidates=[asdict(c) for c in candidates],
            draft=asdict(result), check=check.as_dict(), decision=decision,
        )

        # --- semantic repair branch ---
        if decision.get("problem") == Problem.SEMANTIC.value:
            rep_raw = self.llm.complete_json("repair", {
                "confirmed_problem": decision.get("reasoning", ""),
                "draft": result.draft,
                "verified_facts": [asdict(r) for r in spec.rubric],
            })
            proposal = RepairProposal(
                can_repair=rep_raw.get("can_repair", False),
                edits=[Edit(**e) for e in rep_raw.get("edits", [])],
                note=rep_raw.get("note", ""),
            )
            if proposal.can_repair:
                # work on a branch (copy); rollback = discard the copy
                branch = copy.deepcopy(result.draft)
                new_draft, rejected = self.apply_allowed_semantics(
                    proposal, branch, spec, candidates)
                retest_result = DraftResult(mode="draft", draft=new_draft,
                                            evidence=result.evidence)
                retest_check = self.run_check(retest_result, spec, candidates)
                if self.verify_retest(retest_check):
                    result = retest_result
                    check = retest_check
                    record.retest_passed = True
                else:
                    record.retest_passed = False  # rollback: keep pre-edit draft
                record.repair = {"proposal": rep_raw, "rejected": rejected,
                                 "retest": retest_check.as_dict()}
            else:
                record.repair = {"proposal": rep_raw, "note": proposal.note}

        self.records.append(record)
        self._persist(record)
        return record

    def run(self, idea_text: str) -> RoundRecord:
        idea = Idea(text=idea_text)
        last = None
        for r in range(1, self.max_rounds + 1):
            last = self.run_round(idea, r)
            action = last.decision.get("next_action")
            if action == Action.FINISH.value:
                break
            if action == Action.ESCALATE.value:
                break
            # repair round already produced a retest inside run_round;
            # if it passed we can finish next check, else loop again.
            if action == Action.REPAIR.value and last.retest_passed:
                break
        return last

    # === audit trail =====================================================
    def _persist(self, record: RoundRecord) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / f"round_{record.round_id}.json"
        path.write_text(json.dumps(asdict(record), ensure_ascii=False, indent=2),
                        encoding="utf-8")

    def final_text(self) -> str:
        for rec in reversed(self.records):
            d = rec.draft.get("draft", "")
            if d:
                return d
        return ""
