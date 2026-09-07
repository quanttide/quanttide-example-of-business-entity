#!/usr/bin/env python3
"""发现希望 —— 摘取最近一周的更新素材，让 LLM 分析亮点。

用法: ./discover-hope.py [--since=<date>]
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from quanttide_agent import LLM
from quanttide_agent.config import settings

MAIN_REPO = Path(__file__).resolve().parents[4]
SINCE = datetime.now() - timedelta(days=7)
LLM = LLM(
    model=settings.llm_model or "deepseek-chat",
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
)


def main():
    global SINCE
    for arg in sys.argv[1:]:
        if arg.startswith("--since="):
            SINCE = datetime.strptime(arg[8:], "%Y-%m-%d")

    # 摘取所有子模块最近一周的提交消息 + 变更文件列表
    entries = []
    for pattern in ["apps/*", "data/*", "docs/*", "examples/*"]:
        for repo_path in sorted(MAIN_REPO.glob(pattern)):
            if not (repo_path / ".git").exists():
                continue
            repo = str(repo_path.relative_to(MAIN_REPO))
            since_str = SINCE.strftime("%Y-%m-%d")

            msgs = subprocess.run(
                ["git", "log", "--after", since_str, "--oneline", "--format=%h %s"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=10,
            ).stdout.strip()

            files = subprocess.run(
                ["git", "diff", "--name-only", f"@{{${{after:{since_str}}}}}", "HEAD"],
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=10,
            ).stdout.strip()

            if msgs:
                entries.append(f"## {repo}\n提交:\n{msgs}\n文件:\n{files}")

    material = "\n\n".join(entries)
    print(f"素材: {len(entries)} 个仓库, {len(material)} 字符", file=sys.stderr)

    prompt = f"""以下是团队最近一周的提交更新摘要。请从这些素材中找出最值得关注的积极进展信号（亮点）。

要求：
1. 找出 3-6 个亮点
2. 每个亮点说明：信号是什么、为什么值得关注
3. 输出 JSON 格式，不要多余文字

素材：
{material[:8000]}
"""

    resp = LLM.complete(prompt, temperature=0.3, max_tokens=2000)
    content = resp.content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    result = (
        json.loads(content)
        if content.startswith("{") or content.startswith("[")
        else {"raw": content}
    )

    output = {
        "title": "本周进展发现",
        "method": "摘取更新素材 → LLM 分析亮点",
        "since": since_str,
        "source_count": len(entries),
        "discoveries": result
        if isinstance(result, list)
        else [result]
        if isinstance(result, dict)
        else [],
    }

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
