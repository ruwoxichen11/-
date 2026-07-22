"""Data structures passed between the orchestrator, sub-agents and the harness.

Every artifact is bound to the round it was produced in. If the idea, spec or
material changes, older artifacts must not be reused for a new round's judgement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Problem(str, Enum):
    IDEA = "idea"          # the user's idea itself is too vague
    SPEC = "spec"          # the research proposition drifted from the idea
    MATERIAL = "material"  # missing terminology / style / corpus
    DRAFT = "draft"        # structural problem, needs a rewrite
    SEMANTIC = "semantic"  # register/semantic deviation -> repair
    NONE = "none"          # passed everything


class Action(str, Enum):
    RESPEC = "respec"
    REWRITE = "rewrite"
    ADD_MATERIAL = "add_material"
    REPAIR = "repair"
    FINISH = "finish"
    ESCALATE = "escalate_to_human"


@dataclass
class Idea:
    """The user's raw, unprocessed idea."""
    text: str


@dataclass
class RubricItem:
    id: str
    requirement: str
    basis: str


@dataclass
class Spec:
    """Produced by the spec agent (the hidden 'expected answer' of the blind test)."""
    proposition: str
    rubric: list[RubricItem]
    needs_clarification: bool = False
    clarification: str = ""


@dataclass
class Candidate:
    """A retrieved writing-material candidate (term rule / academic sentence / norm)."""
    cid: str
    kind: str          # "term" | "sentence" | "norm" | "background"
    content: str
    score: float = 0.0  # filled ONLY by the retrieval engine, never by the model


@dataclass
class QueryPlan:
    outline: list[str]
    queries: list[str]


@dataclass
class DraftResult:
    mode: str                        # "draft" | "clarify"
    draft: str = ""
    clarification: str = ""
    evidence: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Edit:
    locate: str
    revised: str
    basis: str
    affected_scope: str


@dataclass
class RepairProposal:
    can_repair: bool
    edits: list[Edit] = field(default_factory=list)
    note: str = ""


@dataclass
class CheckReport:
    """Mechanical, directly-verifiable results produced by the harness."""
    register_score: float
    structure_ok: bool
    passed: bool
    findings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "register_score": self.register_score,
            "structure_ok": self.structure_ok,
            "passed": self.passed,
            "findings": self.findings,
        }


@dataclass
class RoundRecord:
    """Everything about one round, kept for full post-hoc replay."""
    round_id: int
    idea: str
    spec: dict[str, Any]
    query_plan: dict[str, Any]
    candidates: list[dict[str, Any]]
    draft: dict[str, Any]
    check: dict[str, Any]
    decision: dict[str, Any]
    repair: dict[str, Any] | None = None
    retest_passed: bool | None = None
