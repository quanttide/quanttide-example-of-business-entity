#!/usr/bin/env python3
"""
Experiment: 稳态模块的交叉审查收敛性验证。

在 "src + test + docs" 三位一体的编码规范下，稳态模块的
"代码→文档→重写代码" 交叉审查理论上应该收敛。
"""

import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

SAMPLES_DIR = Path(__file__).parent / "samples"
MAX_ITERATIONS = 5


# ── LLM 客户端 ────────────────────────────────────────────────────────


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    mock: bool = False


def llm(prompt: str, config: LLMConfig) -> str:
    if config.mock:
        return "# Mock\n"
    body = json.dumps(
        {
            "model": config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
    ).encode()
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
        print(f"  [LLM 错误] {e}", file=sys.stderr)
        return ""


# ── Diff 度量 ──────────────────────────────────────────────────────────


def token_diff(a: str, b: str) -> float:
    """Token-level diff ratio between two code strings."""

    def strip(s: str) -> str:
        s = re.sub(r"///.*", "", s)
        s = re.sub(r"//!.*", "", s)
        s = re.sub(r"/\*[\s\S]*?\*/", "", s)
        s = re.sub(r"//[^\n]*", "", s)
        lines = [l.strip() for l in s.splitlines() if l.strip()]
        return "\n".join(lines)

    def tokens(s: str) -> list[str]:
        s = re.sub(r'"[^"]*"', '"S"', s)
        s = re.sub(r"'[^']*'", "'C'", s)
        return re.findall(r"[A-Za-z_]\w*|[0-9.]+|[{}()\[\];,:!?<>+*/%=&|^~.-]", s)

    o = tokens(strip(a))
    r = tokens(strip(b))
    sm = SequenceMatcher(None, o, r)
    matching = sum(b - a for tag, a, b, c, d in sm.get_opcodes() if tag == "equal")
    total = max(len(o), len(r))
    return 1.0 - (matching / total if total > 0 else 1.0)


def extract_code(text: str) -> str:
    for marker in ["```rust", "```python", "```"]:
        if marker in text:
            text = text.split(marker)[1].split("```")[0].strip()
            break
    return text


# ── 从样本文件读取三位一体 ──────────────────────────────────────────────


@dataclass
class ModuleTriplet:
    """稳态模块的三位一体。"""

    name: str
    src: str  # 代码
    tests: str  # 测试（从代码中提取的 #[cfg(test)] 部分）
    doc_intent: str  # 文档意图（模块级 doc comment, 函数签名等）

    @property
    def full(self) -> str:
        """完整上下文 = 文档意图 + 代码 + 测试"""
        return f"## Module Documentation\n\n{self.doc_intent}\n\n## Implementation\n\n```rust\n{self.src}\n```\n\n## Tests\n\n```rust\n{self.tests}\n```"

    @property
    def src_only(self) -> str:
        """仅代码"""
        return self.src


def extract_triplet(filepath: Path) -> ModuleTriplet:
    """从 Rust 源文件提取三位一体。"""
    text = filepath.read_text()
    name = filepath.stem

    # 提取模块级 doc comment (//! ...)
    doc_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//!"):
            doc_lines.append(stripped.lstrip("//!").strip())
        elif stripped.startswith("/*!") or stripped.startswith("/**"):
            # block doc - skip for now, just use what's before
            pass

    doc_intent = "\n".join(doc_lines) if doc_lines else f"Module: {name}"

    # 提取测试部分
    tests = ""
    if "#[cfg(test)]" in text:
        tests_part = text.split("#[cfg(test)]", 1)[1]
        # 找到最近的 mod tests { ... } 或 fn ... 结束
        tests = "#[cfg(test)]" + tests_part

    # 代码 = 全文
    src = text

    return ModuleTriplet(name=name, src=src, tests=tests, doc_intent=doc_intent)


# ── 验证管道 ───────────────────────────────────────────────────────────


def verify_test_passage(
    regenerated_code: str, original_tests: str, config: LLMConfig
) -> tuple[bool, str]:
    """用 LLM 验证重写代码是否能通过原始测试。"""
    prompt = (
        "You are a Rust compiler and test runner. The following code was regenerated from a design document. "
        "The original tests are provided below. Determine if the regenerated code will pass ALL tests.\n\n"
        f"## Regenerated Code\n```rust\n{regenerated_code}\n```\n\n"
        f"## Original Tests\n```rust\n{original_tests}\n```\n\n"
        "Respond with a JSON object:\n"
        '{"passes": true/false, "failures": ["test_name: reason", ...]}'
    )
    resp = llm(prompt, config)
    try:
        result = json.loads(extract_code(resp) or resp)
        passes = result.get("passes", False)
        failures = result.get("failures", [])
        return passes, "\n".join(failures) if failures else ""
    except Exception:
        return False, "test verification failed"


def cross_review(
    triplet: ModuleTriplet, mode: str, config: LLMConfig
) -> tuple[str, float, str]:
    """
    根据模式运行交叉审查。
    mode="src_only": 只看代码
    mode="full": 看三位一体
    """
    if mode == "src_only":
        context = triplet.src_only
    else:
        context = triplet.full

    # Step 1: 代码 → 文档
    doc = llm(
        "You are a senior architect. Read the following module and write a precise design note. "
        "Cover: purpose, public API, types, error handling. Be accurate.\n\n"
        f"```\n{context}\n```",
        config,
    )
    if not doc:
        return "", 0.0, ""

    # Step 2: 文档 → 代码
    code = llm(
        "You are a senior engineer. Implement the module described in this design note. "
        "Output ONLY the code in a single codeblock.\n\n"
        f"{doc}",
        config,
    )
    if not code:
        return "", 0.0, ""
    code = extract_code(code)

    # Diff
    ratio = token_diff(triplet.src, code)

    # 测试验证
    test_pass, failures = False, "no tests"
    if triplet.tests:
        test_pass, failures = verify_test_passage(code, triplet.tests, config)

    return code, ratio, f"{'✅' if test_pass else '❌'} {failures}"


# ── 主流程 ─────────────────────────────────────────────────────────────


def main():
    config = LLMConfig(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        mock=not os.getenv("OPENAI_API_KEY"),
    )

    if config.mock:
        print("⚠  Mock 模式\n")

    # 加载样本
    target = SAMPLES_DIR / "qtrecurit_funnel.rs"
    triplet = extract_triplet(target)

    print(f"样本: {target.name}  ({len(triplet.src.splitlines())} 行)")
    print(f"  代码: {len(triplet.src.splitlines())} 行")
    print(
        f"  测试: {len(triplet.tests.splitlines())} 行"
        if triplet.tests
        else "  测试: 无"
    )
    print(f"  文档: {len(triplet.doc_intent.splitlines())} 行")
    print()

    # 实验 A: 仅代码 → 交叉审查
    print(f"{'=' * 60}")
    print(f"  实验 A: 仅代码 → 交叉审查")
    print(f"{'=' * 60}")
    code_a, diff_a, verify_a = cross_review(triplet, "src_only", config)
    print(f"  Token Diff: {diff_a:.2%}")
    print(f"  测试验证: {verify_a}")
    print()

    # 实验 B: 三位一体 → 交叉审查
    print(f"{'=' * 60}")
    print(f"  实验 B: 三位一体（代码+测试+文档） → 交叉审查")
    print(f"{'=' * 60}")
    code_b, diff_b, verify_b = cross_review(triplet, "full", config)
    print(f"  Token Diff: {diff_b:.2%}")
    print(f"  测试验证: {verify_b}")
    print()

    # 如果实验 B 未收敛，迭代修正
    if diff_b > 0.30:
        print(f"{'=' * 60}")
        print(f"  实验 C: 三位一体 + 迭代修正")
        print(f"{'=' * 60}")
        # 把 Diff 偏差和测试失败喂回 LLM，让 AI-B 修正代码
        code_current = code_b
        for i in range(MAX_ITERATIONS):
            fix_prompt = (
                "You are a senior engineer. Your implementation needs to be revised to match the original module. "
                "Compare your code with the design intent and fix ALL differences. Maintain the exact same "
                "public API, type signatures, and behavior. Output ONLY the corrected code.\n\n"
                f"## Original Design Intent\n\n{triplet.doc_intent}\n\n"
                f"## Your Previous Implementation\n```rust\n{code_current}\n```\n\n"
                f"## Original Tests (your code must pass these)\n```rust\n{triplet.tests}\n```\n\n"
                "Revise your implementation."
            )
            revised = llm(fix_prompt, config)
            if not revised:
                break
            revised = extract_code(revised)
            diff_new = token_diff(triplet.src, revised)
            test_pass, failures = verify_test_passage(revised, triplet.tests, config)

            bar = "█" * int(diff_new * 40) + "░" * (40 - int(diff_new * 40))
            status = "✅" if test_pass else "❌"
            print(f"  迭代 {i + 1}: Diff={diff_new:.2%}  [{bar}]  测试:{status}")

            if diff_new <= diff_b * 0.5:
                print(f"  → 已收敛")
                break
            code_current = revised
            diff_b = diff_new

    print(f"\n{'=' * 60}")
    print(f"  总结")
    print(f"{'=' * 60}")
    print(f"  仅代码:   Diff={diff_a:.2%}")
    print(f"  三位一体: Diff={diff_b:.2%}")
    print(f"  改进:     {(diff_a - diff_b):+.2%}")


if __name__ == "__main__":
    main()
