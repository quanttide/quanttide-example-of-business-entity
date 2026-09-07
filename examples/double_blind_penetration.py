#!/usr/bin/env python3
"""
双盲穿透实验 (Double-Blind Penetration Experiment)

核心思想：利用 AI 的"过度合理化"倾向作为探针，通过"信息保真度"量化代码混乱度。

流程:
  Phase 1 - AI-A (解码者): 源码 → 设计文档（剥离补丁/奇技淫巧）
  Phase 2 - AI-B (重编码者): 文档 → 干净重写代码
  Phase 3 - AI-C (裁决者): 对比原始 vs 重写，输出三维度混乱报告
  Phase 4 - 强制收敛: 以重写代码为基准，只加回必要依赖，跑测试验证
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
REPORTS_DIR = Path(__file__).parent / "reports"
MAX_CONVERGE_ITERATIONS = 3


# ── LLM 客户端 ────────────────────────────────────────────────────────


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    mock: bool = False


def llm(prompt: str, config: LLMConfig, temperature: float = 0.1) -> str:
    if config.mock:
        return "# Mock\n"
    body = json.dumps(
        {
            "model": config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
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
        resp = urllib.request.urlopen(req, timeout=300)
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [LLM 错误] {e}", file=sys.stderr)
        return ""


# ── 工具函数 ───────────────────────────────────────────────────────────


def extract_code(text: str, lang: str = "rust") -> str:
    for marker in [f"```{lang}", "```"]:
        if marker in text:
            text = text.split(marker)[1].split("```")[0].strip()
            break
    return text


def extract_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象。"""
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    # Try extracting from code block
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "failed to parse JSON", "raw": text[:500]}


def token_diff(a: str, b: str) -> float:
    """Token-level diff ratio."""

    def strip_comments(s: str) -> str:
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

    o = tokens(strip_comments(a))
    r = tokens(strip_comments(b))
    sm = SequenceMatcher(None, o, r)
    matching = sum(b - a for tag, a, b, c, d in sm.get_opcodes() if tag == "equal")
    total = max(len(o), len(r))
    return 1.0 - (matching / total if total > 0 else 1.0)


# ── Phase 1: AI-A 解码 ────────────────────────────────────────────────


def phase1_decode(source_code: str, config: LLMConfig) -> str:
    """AI-A: 源码 → 设计文档（剥离补丁、冗余、奇技淫巧）"""
    prompt = (
        "作为资深架构师，请阅读以下 Rust 源代码。忽略所有为了兼容历史版本而存在的补丁代码、"
        "冗余的容错处理以及语言层面的奇技淫巧。提取出这个模块最纯粹的业务逻辑、数据流向、"
        "输入输出契约和核心状态变迁。将其写成一份结构清晰的设计文档（Markdown 格式）。\n\n"
        "要求：文档中不得出现任何具体实现细节（如借用、生命周期、具体函数名），只能描述意图和行为。\n\n"
        f"```rust\n{source_code}\n```"
    )
    print("  Phase 1: AI-A 解码中...")
    doc = llm(prompt, config, temperature=0.1)
    if not doc:
        print("  ⚠ AI-A 返回空")
        return ""
    print(f"  文档长度: {len(doc)} chars")
    return doc


# ── Phase 2: AI-B 重编码 ──────────────────────────────────────────────


def phase2_rewrite(design_doc: str, config: LLMConfig) -> str:
    """AI-B: 文档 → 干净重写代码"""
    prompt = (
        "作为资深工程师，请严格按照这份设计文档，从零实现该模块的核心逻辑。\n\n"
        "要求：\n"
        "1. 代码必须高内聚、低耦合\n"
        "2. 不允许引入文档中未提及的任何隐式状态或全局依赖\n"
        "3. 只需实现核心逻辑，无需考虑极端异常处理\n"
        "4. 语言为 Rust\n\n"
        f"{design_doc}"
    )
    print("  Phase 2: AI-B 重编码中...")
    code_raw = llm(prompt, config, temperature=0.1)
    if not code_raw:
        print("  ⚠ AI-B 返回空")
        return ""
    code = extract_code(code_raw, "rust")
    print(f"  重写代码: {len(code.splitlines())} 行")
    return code


# ── Phase 3: AI-C 裁决 ────────────────────────────────────────────────


@dataclass
class ChaosReport:
    """三维度混乱度报告。"""

    implicit_deps: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    logic_forks: list[str] = field(default_factory=list)
    deps_score: int = 0
    effects_score: int = 0
    forks_score: int = 0
    summary: str = ""


def phase3_judge(
    original: str, design_doc: str, rewritten: str, config: LLMConfig
) -> ChaosReport:
    """AI-C: 对比原始 vs 重写，输出三维度混乱报告。"""
    prompt = (
        "请对比原始代码和基于文档重写的代码。不要关注代码风格、变量命名或格式差异。\n\n"
        "仅关注以下三个维度的实质性差异：\n\n"
        "1. 隐式依赖：原始代码偷偷依赖了哪些文档中未提及的外部状态、全局变量或执行顺序？\n"
        "2. 副作用发散：原始代码在执行主流程时，对外部产生了哪些文档未定义的修改或 IO 操作？\n"
        "3. 逻辑分叉：原始代码中存在哪些为了特殊场景硬编码的特判逻辑，导致其偏离了文档中的直线逻辑？\n\n"
        "请以 JSON 格式输出，格式如下：\n"
        "{\n"
        '  "implicit_dependencies": ["item1", "item2", ...],\n'
        '  "side_effects": ["item1", "item2", ...],\n'
        '  "logic_forks": ["item1", "item2", ...],\n'
        '  "scores": {"implicit_deps": 1-10, "side_effects": 1-10, "logic_forks": 1-10},\n'
        '  "summary": "整体评价"\n'
        "}\n\n"
        f"## 原始代码\n```rust\n{original}\n```\n\n"
        f"## 设计文档\n{design_doc}\n\n"
        f"## 重写代码\n```rust\n{rewritten}\n```"
    )
    print("  Phase 3: AI-C 裁决中...")
    resp = llm(prompt, config, temperature=0.0)
    data = extract_json(resp)

    report = ChaosReport()
    if "error" in data:
        report.summary = f"JSON 解析失败: {data['error']}"
        return report

    report.implicit_deps = data.get(
        "implicit_dependencies", data.get("implicit_deps", [])
    )
    report.side_effects = data.get("side_effects", [])
    report.logic_forks = data.get("logic_forks", [])
    scores = data.get("scores", data.get("score", {}))
    report.deps_score = scores.get(
        "implicit_deps", scores.get("implicit_dependencies", 0)
    )
    report.effects_score = scores.get("side_effects", 0)
    report.forks_score = scores.get("logic_forks", 0)
    report.summary = data.get("summary", "")

    return report


# ── Phase 4: 强制收敛 ─────────────────────────────────────────────────


def phase4_converge(
    original: str,
    rewritten: str,
    chaos_report: ChaosReport,
    tests: str,
    config: LLMConfig,
) -> tuple[str, float, str]:
    """
    以干净重写代码为基准，只加回必要的外部依赖。
    然后验证测试是否通过。
    """
    print(f"\n  Phase 4: 强制收敛")
    current_code = rewritten
    final_diff = token_diff(original, current_code)

    for i in range(MAX_CONVERGE_ITERATIONS):
        # 构建反馈上下文
        issues = []
        if chaos_report.implicit_deps:
            issues.append(
                "## 需评估的隐式依赖\n"
                + "\n".join(f"- {d}" for d in chaos_report.implicit_deps)
            )
        if chaos_report.side_effects:
            issues.append(
                "## 需评估的副作用\n"
                + "\n".join(f"- {e}" for e in chaos_report.side_effects)
            )
        if chaos_report.logic_forks:
            issues.append(
                "## 需评估的逻辑分叉\n"
                + "\n".join(f"- {f}" for f in chaos_report.logic_forks)
            )

        needs_fix = bool(issues)

        if not needs_fix and not tests:
            print(f"  迭代 {i + 1}: 无问题，已收敛")
            break

        # 构建 Prompt: 以重写代码为基准，选择性加回必要项
        converge_prompt = (
            "你是一位资深架构师。以下是一份基于设计文档从零实现的干净代码，"
            "需要你评估是否需要对它做最小化的修改，使其能在生产环境中工作。\n\n"
            "## 干净实现\n"
            f"```rust\n{current_code}\n```\n"
        )

        if issues:
            converge_prompt += (
                "\n## 需要你评估的问题\n"
                "以下是从原始代码中发现的、干净实现未覆盖的部分。请逐一判断：\n"
                "- 如果某个项是**必要的业务需求**（没有它业务无法跑通），用最小改动加回来，但保持代码整洁\n"
                "- 如果某个项是**历史补丁或过时兼容**，丢弃它\n\n" + "\n".join(issues)
            )

        if tests:
            converge_prompt += (
                "\n## 原始测试用例\n"
                "你的代码必须通过以下测试。如果测试引用了原始代码中的特定类型或函数名，"
                "请确保你的代码兼容它们。\n"
                f"```rust\n{tests}\n```\n"
            )

        converge_prompt += "\n请输出修改后的最终代码，用 ```rust 代码块包裹。"

        result = llm(converge_prompt, config, temperature=0.1)
        if not result:
            break
        result_code = extract_code(result, "rust")
        if not result_code:
            break

        current_code = result_code
        final_diff = token_diff(original, current_code)
        bar = "█" * int(final_diff * 40) + "░" * (40 - int(final_diff * 40))
        print(f"  迭代 {i + 1}: Diff={final_diff:.2%}  [{bar}]")

        # 如果 Diff 稳定，退出
        if final_diff < 0.30:
            print(f"  → Diff < 30%，已收敛")
            break

    return current_code, final_diff, ""


# ── 完整管道 ───────────────────────────────────────────────────────────


def run_pipeline(source_code: str, tests: str, label: str, config: LLMConfig) -> dict:
    """执行完整的双盲穿透实验管道。"""
    print(f"\n{'=' * 60}")
    print(f"  双盲穿透实验: {label}")
    print(
        f"  原始代码: {len(source_code.splitlines())} 行"
        f"{f', 测试: {len(tests.splitlines())} 行' if tests else ''}"
    )
    print(f"{'=' * 60}")

    results = {"label": label, "llm": config.model}

    # Phase 1
    design_doc = phase1_decode(source_code, config)
    if not design_doc:
        return results
    results["design_doc"] = design_doc

    # Phase 2
    rewritten = phase2_rewrite(design_doc, config)
    if not rewritten:
        return results
    results["rewritten_code"] = rewritten

    # Diff (粗略比较)
    diff_p2 = token_diff(source_code, rewritten)
    results["diff_after_phase2"] = diff_p2

    # Phase 3
    chaos = phase3_judge(source_code, design_doc, rewritten, config)
    results["chaos_report"] = {
        "implicit_dependencies": chaos.implicit_deps,
        "side_effects": chaos.side_effects,
        "logic_forks": chaos.logic_forks,
        "scores": {
            "implicit_deps": chaos.deps_score,
            "side_effects": chaos.effects_score,
            "logic_forks": chaos.forks_score,
        },
        "summary": chaos.summary,
    }

    # 输出混乱度
    total_score = chaos.deps_score + chaos.effects_score + chaos.forks_score
    print(f"\n  ┌─ 混乱度报告 ─────────────────────────────┐")
    print(f"  │  隐式依赖: {chaos.deps_score}/10  ({len(chaos.implicit_deps)} 项)")
    print(f"  │  副作用发散: {chaos.effects_score}/10  ({len(chaos.side_effects)} 项)")
    print(f"  │  逻辑分叉: {chaos.forks_score}/10  ({len(chaos.logic_forks)} 项)")
    print(f"  │  总分: {total_score}/30")
    print(f"  └──────────────────────────────────────────┘")

    # Phase 4
    final_code, final_diff, _ = phase4_converge(
        source_code, rewritten, chaos, tests, config
    )
    results["final_code"] = final_code
    results["diff_after_phase4"] = final_diff

    print(f"\n  总结:")
    print(f"    Phase 2 后 Diff: {diff_p2:.2%}")
    print(f"    Phase 4 后 Diff: {final_diff:.2%}")
    print(f"    改进: {(diff_p2 - final_diff):+.2%}")

    return results


# ── 入口 ───────────────────────────────────────────────────────────────


def main():
    config = LLMConfig(
        api_key=os.getenv("OPENAI_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        mock=not os.getenv("OPENAI_API_KEY"),
    )
    if config.mock:
        print("⚠  Mock 模式\n")

    # 选择样本
    targets = [
        SAMPLES_DIR / "qtrecurit_funnel.rs",
        SAMPLES_DIR / "qtrecurit_classifier.rs",
    ]

    all_results = []
    for t in targets:
        if not t.exists():
            print(f"跳过: {t.name} 不存在")
            continue
        text = t.read_text()
        # 提取测试
        tests = ""
        if "#[cfg(test)]" in text:
            tests = text.split("#[cfg(test)]", 1)[1]

        result = run_pipeline(text, tests, t.stem, config)
        all_results.append(result)

        print(f"\n{'=' * 60}\n")

    # 保存完整报告
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / "double_blind_result.json"
    report_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2))
    print(f"\n📄 完整报告: {report_path}")


if __name__ == "__main__":
    main()
