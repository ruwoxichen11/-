#!/usr/bin/env python3
"""CLI entrypoint.

Usage:
    python run.py "把大模型幻觉这个想法写成论文味的一段"
    ARA_BACKEND=openai OPENAI_API_KEY=... python run.py "..."

Backend defaults to the offline 'mock' so the repo runs with no API key.
"""
from __future__ import annotations

import sys

from harness import Harness


def main() -> int:
    if len(sys.argv) < 2:
        print('用法: python run.py "你的想法"')
        return 2
    idea = sys.argv[1]
    h = Harness()
    final = h.run(idea)

    print("\n" + "=" * 60)
    print("研究命题:", final.spec["proposition"])
    print("-" * 60)
    print("最终成稿（学术论文语域）:\n")
    print(h.final_text())
    print("-" * 60)
    print("机械检查:", final.check)
    print("主 Agent 判定:", final.decision.get("problem"),
          "->", final.decision.get("next_action"))
    if final.retest_passed is not None:
        print("修复后重测:", "通过" if final.retest_passed else "未通过（已回滚）")
    print(f"\n完整留痕已保存到: {h.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
