"""Keyword retrieval engine over a small material corpus.

Mirrors the original architecture: the ENGINE (not the model) executes queries and
assigns scores/ranking. The writer sub-agent may only submit query terms; it can
never fill in results, ranks or scores itself.

Swap this for a real BM25 / vector index in production; the contract is the same:
    search(index, queries) -> list[Candidate] with engine-assigned scores.
"""
from __future__ import annotations

from pathlib import Path

from .schema import Candidate

CORPUS_FILE = Path(__file__).resolve().parent.parent / "examples" / "material_corpus.md"


def _load_corpus() -> list[Candidate]:
    """Parse the material corpus into candidate units."""
    if not CORPUS_FILE.exists():
        return _builtin_corpus()
    items: list[Candidate] = []
    text = CORPUS_FILE.read_text(encoding="utf-8")
    for block in text.split("\n---\n"):
        block = block.strip()
        if not block:
            continue
        # first line: "[kind] cid: content"
        first, _, rest = block.partition("\n")
        head = first.strip().lstrip("#").strip()
        if ":" in head:
            meta, _, inline = head.partition(":")
            kind = meta.strip("[] ").split()[0] if meta.strip() else "background"
            cid = meta.strip("[] ").split()[-1] if meta.strip() else "C?"
            content = (inline + "\n" + rest).strip()
            items.append(Candidate(cid=cid, kind=kind, content=content))
    return items or _builtin_corpus()


def _builtin_corpus() -> list[Candidate]:
    return [
        Candidate("C1", "sentence", "学术句式规范：优先使用被动与客观陈述，避免第一人称随感。"),
        Candidate("C2", "norm", "论文结构规范：至少包含问题背景与既有工作定位。"),
        Candidate("C3", "term", "术语规范：区分'机制'与'现象'，区分'事实'与'推断'。"),
        Candidate("C4", "background", "论证规范：主张须有依据支撑，结论须标明局限。"),
    ]


def search(index: str, queries: list[str], top_k: int = 4) -> list[Candidate]:
    """Keyword shortlist. Engine assigns the scores, not the model."""
    corpus = _load_corpus()
    scored: list[Candidate] = []
    for c in corpus:
        hits = 0
        hay = (c.content + " " + c.kind).lower()
        for q in queries:
            for tok in q.lower().split():
                if tok and tok in hay:
                    hits += 1
        if hits:
            scored.append(Candidate(c.cid, c.kind, c.content, score=float(hits)))
    scored.sort(key=lambda x: x.score, reverse=True)
    # Always return at least the base norms so a first round can proceed.
    if not scored:
        scored = corpus[:top_k]
        for i, c in enumerate(scored):
            c.score = float(len(scored) - i)
    return scored[:top_k]
