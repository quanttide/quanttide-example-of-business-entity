#!/usr/bin/env python3
"""
Experiment: 验证 "代码→文档→重写代码" 交叉审查机制是否能量化代码混乱度。

使用生产代码（qtrecurit 仓库的真实 Rust 模块）作为实验样本。
每个模块独立经过交叉审查管道，产出 Token Diff 作为可复现性度量。
"""

import difflib
import json
import os
import re
import sys
import tokenize
import urllib.request
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

SAMPLES_DIR = Path(__file__).parent / "samples"


# ── LLM 客户端 ────────────────────────────────────────────────────────


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    mock: bool = False


def llm_complete(prompt: str, config: LLMConfig) -> str:
    """Call LLM or return mock response."""
    if config.mock:
        return "# Mock response\n\nImplemented as described in the prompt.\n"

    body = json.dumps({
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }).encode()

    req = urllib.request.Request(
        f"{config.base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=180)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [LLM 调用失败] {e}", file=sys.stderr)
        return ""


# ── Diff 度量 ──────────────────────────────────────────────────────────


def strip_rust_comments(source: str) -> str:
    """Remove Rust comments (// and /* */) and doc comments (///, //!, /** */)."""
    s = source
    # Remove doc comments //! and ///
    s = re.sub(r"///.*", "", s)
    s = re.sub(r"//!.*", "", s)
    # Remove block doc/comments /** */  /* */
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)
    # Remove single-line comments (must be after doc comments)
    s = re.sub(r"//[^\n]*", "", s)
    # Remove blank lines
    lines = [l.strip() for l in s.splitlines() if l.strip()]
    return "\n".join(lines)


def tokenize_rust(code: str) -> list[str]:
    """Simple Rust tokenizer: identifiers, keywords, literals, operators."""
    # Remove string literals (replace with a placeholder token)
    s = re.sub(r'"[^"]*"', '"STR"', code)
    s = re.sub(r"'[^']*'", "'CHR'", s)
    # Extract tokens
    tokens = re.findall(r"[A-Za-z_]\w*|[0-9]+(?:\.[0-9]+)?|[{}()\[\];,:!?<>+*/%=&|^~.-]", s)
    return tokens


@dataclass
class DiffReport:
    name: str
    original: str
    regenerated: str
    diff_ratio: float = 0.0
    tokens_changed: int = 0
    total_tokens: int = 0

    def compute(self) -> "DiffReport":
        """Compute token-aware diff ratio (0 = identical, 1 = completely different)."""
        stripped_orig = strip_rust_comments(self.original)
        stripped_rege = strip_rust_comments(self.regenerated)

        orig_tokens = tokenize_rust(stripped_orig)
        rege_tokens = tokenize_rust(stripped_rege)

        sm = difflib.SequenceMatcher(None, orig_tokens, rege_tokens)
        matching = sum(b - a for tag, a, b, c, d in sm.get_opcodes() if tag == "equal")
        total = max(len(orig_tokens), len(rege_tokens))
        self.total_tokens = total
        self.tokens_changed = total - matching
        self.diff_ratio = 1.0 - (matching / total if total > 0 else 1.0)
        return self


# ── 实验管道 ──────────────────────────────────────────────────────────


def cross_review(source_code: str, language: str, config: LLMConfig) -> str:
    """
    交叉审查的一轮:
      1. AI-A: 代码 → 文档
      2. AI-B: 文档 → 代码
      返回 AI-B 生成的代码。
    """
    # Step 1: code → doc
    doc_prompt = (
        "You are a senior architect. Read the following code and write a concise design note "
        "describing its purpose, inputs, outputs, and key logic. Be accurate and complete.\n\n"
        f"```{language}\n{source_code}\n```"
    )
    doc = llm_complete(doc_prompt, config)
    if not doc:
        return ""

    # Step 2: doc → code
    code_prompt = (
        "You are a senior engineer. Implement the module described in this design note. "
        "Follow the specification precisely. Output ONLY the code in a single codeblock.\n\n"
        f"{doc}"
    )
    code = llm_complete(code_prompt, config)
    if not code:
        return ""

    # Extract code from markdown code block
    for marker in [f"```{language}", "```rust", "```python", "```"]:
        if marker in code:
            code = code.split(marker)[1].split("```")[0].strip()
            break
    return code


def run_experiment(config: LLMConfig) -> list[DiffReport]:
    """Run cross-review on all sample files and return reports."""
    sample_files = sorted(SAMPLES_DIR.glob("*"))
    if not sample_files:
        print("⚠  没有找到样本文件，请确认 samples/ 目录下有代码文件")
        return []

    results: list[DiffReport] = []
    for fpath in sample_files:
        label = fpath.stem  # filename without extension
        ext = fpath.suffix.lstrip(".")

        source = fpath.read_text()
        print(f"\n{'=' * 60}")
        print(f"  样本: {fpath.name}  ({len(source.splitlines())} 行)")
        print(f"{'=' * 60}")

        regenerated = cross_review(source, ext, config)
        if not regenerated:
            print(f"  ⚠  LLM 返回空，跳过")
            continue

        report = DiffReport(
            name=label,
            original=source,
            regenerated=regenerated,
        ).compute()

        results.append(report)
        bar = "█" * int(report.diff_ratio * 40) + "░" * (40 - int(report.diff_ratio * 40))
        print(f"  Token diff: {report.diff_ratio:.2%}  [{bar}]")
        print(f"  Tokens changed: {report.tokens_changed}/{report.total_tokens}")

    return results


def print_summary(results: list[DiffReport]):
    """Print summary table."""
    print(f"\n\n{'=' * 60}")
    print("  实验结果摘要")
    print(f"{'=' * 60}")
    print(f"{'样本':<35} {'Token Diff':<12} {'变更/总量':<12}")
    print(f"{'-' * 35} {'-' * 12} {'-' * 12}")

    results_sorted = sorted(results, key=lambda r: r.diff_ratio, reverse=True)
    for r in results_sorted:
        bar = "█" * int(r.diff_ratio * 30) + "░" * (30 - int(r.diff_ratio * 30))
        print(f"{r.name:<35} {r.diff_ratio:>10.2%}  {r.tokens_changed:>4}/{r.total_tokens:<4}  {bar}")


# ── 入口 ──────────────────────────────────────────────────────────────


def main():
    config = LLMConfig(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        mock=not os.getenv("OPENAI_API_KEY"),
    )

    if config.mock:
        print("⚠  未设置 LLM API KEY，使用 mock 模式")
        print()

    results = run_experiment(config)
    if not results:
        return

    print_summary(results)

    # 保存报告
    out_dir = Path(__file__).parent / "reports"
    out_dir.mkdir(exist_ok=True)
    report_path = out_dir / "cross_review_result.json"
    report_data = [
        {
            "name": r.name,
            "diff_ratio": r.diff_ratio,
            "tokens_changed": r.tokens_changed,
            "total_tokens": r.total_tokens,
            "original": r.original,
            "regenerated": r.regenerated,
        }
        for r in results
    ]
    report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2))
    print(f"\n📄 详细报告已保存: {report_path}")


if __name__ == "__main__":
    main()
