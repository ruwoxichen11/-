"""LLM client. Two backends:

  - "openai": any OpenAI-compatible chat endpoint (set OPENAI_API_KEY / OPENAI_BASE_URL).
  - "mock":  deterministic offline stub so the repo runs end-to-end with no key.

Each sub-agent is invoked in a FRESH context: we send only the isolated input the
harness prepared for that stage, plus that stage's system prompt. There is no shared
running history between sub-agents -- that is the whole point of context isolation.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

PROMPT_FILES = {
    "orchestrator": "01_orchestrator.md",
    "spec": "02_spec_agent.md",
    "writer": "03_writer_agent.md",
    "repair": "04_repair_agent.md",
}


def load_system_prompt(role: str) -> str:
    return (AGENTS_DIR / PROMPT_FILES[role]).read_text(encoding="utf-8")


class LLMClient:
    def __init__(self, backend: str | None = None, model: str | None = None):
        self.backend = backend or os.getenv("ARA_BACKEND", "mock")
        self.model = model or os.getenv("ARA_MODEL", "gpt-4o-mini")

    def complete_json(self, role: str, user_payload: dict) -> dict:
        """Run one sub-agent in a fresh context and parse its JSON reply."""
        system = load_system_prompt(role)
        user = json.dumps(user_payload, ensure_ascii=False, indent=2)
        if self.backend == "openai":
            raw = self._openai(system, user)
        else:
            raw = self._mock(role, user_payload)
        return _extract_json(raw)

    # ---- backends --------------------------------------------------------
    def _openai(self, system: str, user: str) -> str:
        from openai import OpenAI  # lazy import
        client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user
                 + "\n\n只输出一个 JSON 对象，不要额外文字。"},
            ],
            temperature=0.3,
        )
        return resp.choices[0].message.content or "{}"

    def _mock(self, role: str, payload: dict) -> str:
        """Deterministic stub demonstrating the intended contract."""
        if role == "spec":
            idea = payload.get("idea", "")
            return json.dumps({
                "proposition": f"围绕「{idea}」提出一个可论证的研究命题，"
                               f"聚焦其机制与适用边界，采用论证性综述取向。",
                "needs_clarification": False,
                "clarification": "",
                "rubric": [
                    {"id": "R1", "requirement": "使用书面学术语体，避免口语化与第一人称随感",
                     "basis": "学术写作规范"},
                    {"id": "R2", "requirement": "包含问题背景与既有工作定位两类结构要素",
                     "basis": "论文结构规范"},
                    {"id": "R3", "requirement": "主张须有依据支撑，区分事实与作者推断",
                     "basis": "论证规范"},
                ],
            }, ensure_ascii=False)

        if role == "writer" and "candidates" not in payload:
            # stage one: plan + queries
            return json.dumps({
                "outline": ["问题背景", "既有工作定位", "论证路径", "局限与展望"],
                "queries": ["学术句式 规范", "领域 术语 规范"],
            }, ensure_ascii=False)

        if role == "writer":
            # stage two: turn the idea into academic register prose
            idea = payload.get("idea", "该主题")
            cands = payload.get("candidates", [])
            cited = cands[0]["cid"] if cands else "C1"
            draft = (
                f"本文以{idea}为对象，尝试厘清其内在机制与适用边界。"
                "问题背景方面，既有研究多聚焦于表层现象，尚未系统性地考察其生成条件；"
                "在既有工作定位上，本文将相关论述置于更宽的理论脉络中加以比较。"
                "据此，本文提出一条以机制为中心的论证路径，并区分经验证据与作者推断。"
                "研究表明，该取向有助于揭示被忽略的约束条件；"
                "在局限与展望方面，本文的结论受限于所依据材料的范围，"
                "未来工作可在更广的样本上加以检验。"
            )
            return json.dumps({
                "mode": "draft",
                "draft": draft,
                "clarification": "",
                "evidence": [{"span": "被动化与客观陈述", "candidate": cited}],
            }, ensure_ascii=False)

        if role == "orchestrator":
            check = payload.get("check", {})
            if check.get("passed"):
                return json.dumps({
                    "problem": "none", "reasoning": "成稿通过机械检查且契合命题",
                    "next_action": "finish", "evidence": ["check.passed=true"],
                }, ensure_ascii=False)
            return json.dumps({
                "problem": "semantic",
                "reasoning": "命题与资料无误，成稿语域未达阈值，定位为语义/语域问题",
                "next_action": "repair",
                "evidence": [f"register_score={check.get('register_score')}"],
            }, ensure_ascii=False)

        if role == "repair":
            return json.dumps({
                "can_repair": True,
                "edits": [{
                    "locate": "口语化处",
                    "revised": "（已改为书面学术语体的等义表述）",
                    "basis": "学术写作规范",
                    "affected_scope": "仅该句，不影响其余段落",
                }],
                "note": "",
            }, ensure_ascii=False)

        return "{}"


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"model did not return JSON: {raw[:200]}")
    return json.loads(m.group(0))
