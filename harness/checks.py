"""Mechanical, repeatable checks the harness performs WITHOUT asking the model.

The AI does the semantic judgement (is the register right, is the argument sound);
the harness only does what can be re-run and verified deterministically:
  - is the text register academic enough (heuristic score, thresholded)?
  - does the text carry recognisable academic structure?
  - did the writer leak forbidden info / copy the rubric / stack keywords?
  - is a recommendation grounded in this round's candidates?

These are heuristics on purpose: they are guardrails, not the grader. The model
remains the grader; the harness only refuses continuation when the model's claim
contradicts something directly checkable here.
"""
from __future__ import annotations

import re

from .schema import Candidate, CheckReport, DraftResult, RubricItem, Spec

# --- lexicons -------------------------------------------------------------

# Colloquial / non-academic markers (Chinese + English), penalised.
COLLOQUIAL = [
    "其实", "说白了", "反正", "搞定", "牛逼", "特别", "超级", "很多很多",
    "一大堆", "咱们", "大家好", "点赞", "关注", "宝子", "yyds", "绝绝子",
    "gonna", "wanna", "kinda", "a lot of", "stuff", "cool", "awesome",
    "!", "！", "?!", "😀", "😂",
]

# Academic register markers (positive signal), rewarded.
ACADEMIC = [
    "本研究", "本文", "研究表明", "结果显示", "综上", "据此", "在此基础上",
    "既有研究", "相关工作", "局限", "框架", "机制", "假设", "论证", "范式",
    "we propose", "this paper", "prior work", "we argue", "framework",
    "hypothesis", "in contrast", "furthermore", "the results indicate",
]

# Structural cues that suggest a paper-like organisation.
STRUCTURE_CUES = [
    ("background", ["背景", "问题", "动机", "background", "motivation", "problem"]),
    ("related", ["既有", "相关工作", "文献", "prior", "related work", "literature"]),
    ("method", ["方法", "论证", "路径", "框架", "method", "approach", "we argue"]),
    ("limitation", ["局限", "不足", "展望", "未来", "limitation", "future work"]),
]

# Keyword-stacking: same academic filler repeated to fake register.
STACK_WATCH = ["综上所述", "研究表明", "众所周知", "毋庸置疑", "显而易见"]


def register_score(text: str) -> float:
    """Return a 0..1 heuristic academic-register score."""
    if not text.strip():
        return 0.0
    low = text.lower()
    academic_hits = sum(low.count(w.lower()) for w in ACADEMIC)
    colloq_hits = sum(low.count(w.lower()) for w in COLLOQUIAL)
    # first-person casual voice penalty
    casual_voice = len(re.findall(r"我觉得|我认为|我想说|i think|i feel", low))
    n_chars = max(len(text), 1)

    raw = 0.55
    raw += min(academic_hits, 8) * 0.05
    raw -= min(colloq_hits, 10) * 0.06
    raw -= min(casual_voice, 5) * 0.05
    # length sanity: too short can't be a paragraph of a paper
    if n_chars < 120:
        raw -= 0.2
    return max(0.0, min(1.0, raw))


def structure_ok(text: str) -> tuple[bool, list[str]]:
    low = text.lower()
    present, missing = [], []
    for name, cues in STRUCTURE_CUES:
        if any(c.lower() in low for c in cues):
            present.append(name)
        else:
            missing.append(name)
    # A single paragraph needn't contain all four; require at least 2 recognisable cues.
    ok = len(present) >= 2
    findings = [] if ok else [f"structure: only {present or 'none'} cues found"]
    return ok, findings


def detect_leaks(draft: str, spec: Spec, candidates: list[Candidate]) -> list[str]:
    """Detect copied rubric text, written-in internal identifiers, keyword stacking."""
    findings: list[str] = []

    # 1. copying rubric requirement sentences verbatim (>= 12-char overlap span)
    for item in spec.rubric:
        req = item.requirement.strip()
        if len(req) >= 12 and req in draft:
            findings.append(f"leak: rubric requirement '{item.id}' copied verbatim into draft")

    # 2. writing internal identifiers into the prose (candidate ids, rubric ids)
    for cid in [c.cid for c in candidates] + [r.id for r in spec.rubric]:
        if re.search(rf"\b{re.escape(cid)}\b", draft):
            findings.append(f"leak: internal identifier '{cid}' written into draft")

    # 3. keyword stacking to fake register
    for w in STACK_WATCH:
        if draft.count(w) >= 3:
            findings.append(f"stacking: filler '{w}' repeated {draft.count(w)} times")

    return findings


def verify_evidence_grounded(result: DraftResult, candidates: list[Candidate]) -> list[str]:
    """A cited candidate must exist in THIS round's candidate set."""
    valid = {c.cid for c in candidates}
    findings = []
    for ev in result.evidence:
        cid = ev.get("candidate", "")
        if cid and cid not in valid:
            findings.append(f"evidence: cited candidate '{cid}' is not in this round's results")
    return findings


def run_full_check(
    result: DraftResult,
    spec: Spec,
    candidates: list[Candidate],
    threshold: float = 0.6,
) -> CheckReport:
    if result.mode == "clarify":
        # A clarify is legitimate; it is not a failing draft, just not finishable.
        return CheckReport(register_score=0.0, structure_ok=False, passed=False,
                           findings=["writer requested clarification/material"])

    text = result.draft
    score = register_score(text)
    s_ok, s_find = structure_ok(text)
    findings = list(s_find)
    findings += detect_leaks(text, spec, candidates)
    findings += verify_evidence_grounded(result, candidates)

    passed = score >= threshold and s_ok and not any(
        f.startswith(("leak:", "stacking:", "evidence:")) for f in findings
    )
    return CheckReport(register_score=round(score, 3), structure_ok=s_ok,
                       passed=passed, findings=findings)
