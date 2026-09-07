#!/usr/bin/env python3
"""Generate readable markdown report from experiment JSON results."""

import json
from pathlib import Path

data = json.load(open("reports/cross_review_result.json"))

lines = ["# 交叉审查实验报告\n"]
lines.append("LLM: DeepSeek Chat\n")
lines.append("度量方式: Token 级 Diff（去注释/去 docstring 后）\n")
lines.append("日期: 2026-07-03\n")

for d in data:
    name = d["name"]
    diff = d["diff_ratio"]
    changed = d["tokens_changed"]
    total = d["total_tokens"]
    lines.append(f"\n## {name}\n")
    lines.append(f"- Token Diff: {diff:.2%}（{changed}/{total} token 变更）\n")
    lines.append("### 原始代码\n")
    lines.append("```python")
    lines.append(d["original"].rstrip())
    lines.append("```")
    lines.append("\n### 重写代码\n")
    lines.append("```python")
    lines.append(d["regenerated"].rstrip())
    lines.append("```")

Path("cross_review_report.md").write_text("\n".join(lines))
print(f"OK → cross_review_report.md")
