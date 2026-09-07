#!/usr/bin/env python3
"""Bug is Feature —— 战略假设压力测试机"""

import json
import sys
import textwrap
from datetime import datetime
from pathlib import Path

from quanttide_agent import LLM
from quanttide_agent.config import settings

DATA_DIR = Path(__file__).parent
JOURNAL_DIR = DATA_DIR / "journal"
CLIENT = LLM(
    model=settings.llm_model or "deepseek-chat",
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key,
)

SYS1 = """你是一个战略分析师兼反事实推演专家。基于用户的战略上下文，做两件事：

第一，战略推演：识别核心逻辑和关键假设，指出依赖这些假设的风险。
第二，反事实推演：对每条假设做反事实分析——"如果这条假设不成立，会怎样？"

输出 JSON：
{
  "core_logic": "核心战略逻辑",
  "assumptions": [
    {
      "statement": "假设",
      "type": "internal/external",
      "risk": "风险",
      "counterfactual": "如果此假设不成立…",
      "implication": "对战略的影响",
      "signal_to_watch": "应关注什么信号"
    }
  ],
  "summary": "总结"
}"""

SYS2_PER = """你是一个事实校验分析师。下面是【AREA】的工作日记，请对照所有战略假设，找出日记中为每条假设提供的证据。

对每条假设：
- 支持证据：日记中有什么事实支持此假设（引用原文片段）
- 挑战证据：日记中有什么事实挑战此假设（引用原文片段）
- 如无直接证据则注明"无"

输出 JSON：{"area": "AREA", "findings": [{"index": I, "statement": "假设原文", "supporting": "支持证据或'无'", "challenging": "挑战证据或'无'"}]}

战略假设：
ASSUMPTIONS_PLACEHOLDER

工作日记：
JOURNAL_PLACEHOLDER"""

SYS2_SUM = """你是一个事实校验分析师。下面是所有业务线工作日记对每条战略假设的校验结果。

汇总判断每条假设的状态：
- confirmed：日记中有明确支持证据，且无实质性挑战
- rejected：日记中有明确挑战证据，且无实质性支持
- evidence_with_difficulty：既有支持也有挑战，或证据不充分
- no_evidence：日记中无相关证据

输出 JSON：{"verdicts": [{"assumption": "假设原文", "supporting": ["支持汇总"], "challenging": ["挑战汇总"], "verdict": "状态", "signals_to_watch": "关注信号"}], "new_signals": ["新发现的信号"], "summary": "总结"}

校验原始结果：
FINDINGS_PLACEHOLDER"""


def _parse(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n", 1)
        text = lines[1] if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def load_journal_areas():
    if not JOURNAL_DIR.exists():
        return []
    areas = []
    for area_dir in sorted(JOURNAL_DIR.iterdir()):
        if not area_dir.is_dir() or area_dir.name.startswith("."):
            continue
        md_files = sorted(area_dir.glob("*.md"))
        if not md_files:
            continue
        lines = [f"\n{'=' * 50}\n=== {area_dir.name} ===\n{'=' * 50}"]
        for f in md_files[-8:]:
            content = f.read_text().strip()
            lines.append(f"\n--- {f.stem} ---\n{content}")
        areas.append((area_dir.name, "\n".join(lines)))
    return areas


def llm_call(prompt, **kwargs):
    """带重试的 LLM 调用，单个调用失败不中断流程"""
    for attempt in range(3):
        try:
            return CLIENT.complete(prompt, retry=2, **kwargs)
        except Exception as e:
            if attempt < 2:
                continue
            raise


def cmd_new(context_file=None):
    print("\n=== Bug is Feature ===\n")

    if context_file:
        raw = json.loads(Path(context_file).read_text())
        ctx = {
            "company": raw.get("corporate_strategy", {}).get("direction", ""),
            "businesses": [
                {"name": b["name"], "challenge": b.get("challenge", "")}
                for b in raw.get("business_strategy", [])
            ],
        }
        print(f"已从 {context_file} 加载上下文\n")
    else:
        ctx = {"company": input("公司方向：").strip(), "businesses": []}
        while True:
            name = input("  业务线名称（留空结束）：").strip()
            if not name:
                break
            challenge = input(f"  {name} 的挑战：").strip()
            ctx["businesses"].append({"name": name, "challenge": challenge})

    context_text = f"公司方向：{ctx['company']}\n" + "\n".join(
        f"业务 - {b['name']}：{b['challenge']}" for b in ctx.get("businesses", [])
    )

    # ---- System 1: 战略推演 + 反事实 ----
    print("System 1 -- 战略推演 & 反事实...")
    resp1 = llm_call(
        f"{SYS1}\n\n用户的战略上下文：\n{context_text}",
        temperature=0.6,
        max_tokens=3000,
    )
    s1 = _parse(resp1.content.strip())
    print(f"\n核心逻辑：{textwrap.fill(s1.get('core_logic', ''), width=72)}\n")
    for a in s1.get("assumptions", []):
        tag = "内" if a.get("type") == "internal" else "外"
        print(f"  [{tag}] {a.get('statement', '')}")
        print(
            f"        风险：{textwrap.fill(a.get('risk', ''), width=66, subsequent_indent='              ')}"
        )
        cf = a.get("counterfactual", "")
        if cf:
            print(
                f"        若不成立 → {textwrap.fill(cf, width=66, subsequent_indent='                    ')}"
            )
        imp = a.get("implication", "")
        if imp:
            print(
                f"        战略影响：{textwrap.fill(imp, width=66, subsequent_indent='              ')}"
            )
        sig = a.get("signal_to_watch", "")
        if sig:
            print(
                f"        关注信号：{textwrap.fill(sig, width=66, subsequent_indent='              ')}"
            )
        print()
    print(f"总结：{textwrap.fill(s1.get('summary', ''), width=72)}\n")

    # ---- System 2: 事实校验 ----
    areas = load_journal_areas()
    if not areas:
        print("System 2 -- 跳过（未找到日记数据）")
        return

    print("System 2 -- 事实校验...")
    assumptions_json = json.dumps(
        [
            {
                "index": i,
                "statement": a.get("statement", ""),
                "type": a.get("type", ""),
                "risk": a.get("risk", ""),
            }
            for i, a in enumerate(s1.get("assumptions", []))
        ],
        ensure_ascii=False,
        indent=2,
    )

    all_findings = []
    for area_name, area_text in areas:
        print(f"  [{area_name}]...", end=" ", flush=True)
        try:
            prompt = (
                SYS2_PER.replace("AREA", area_name)
                .replace("ASSUMPTIONS_PLACEHOLDER", assumptions_json)
                .replace("JOURNAL_PLACEHOLDER", area_text)
            )
            resp = llm_call(prompt, temperature=0.3, max_tokens=2000)
            result = _parse(resp.content.strip())
            findings = result.get("findings", [])
            print(f"{len(findings)} 条")
            all_findings.append({"area": area_name, "findings": findings})
        except Exception as e:
            print(f"失败 ({e})")
            all_findings.append({"area": area_name, "findings": []})

    # 保存中间结果（汇总前）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    partial = {
        "timestamp": ts,
        "context": ctx,
        "system1": s1,
        "system2": {"per_area": all_findings, "summary": {}},
    }
    result_dir = DATA_DIR / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_path = result_dir / f"{ts}.json"
    result_path.write_text(json.dumps(partial, ensure_ascii=False, indent=2))

    print("  汇总判断...")
    s2 = {}
    try:
        prompt_sum = SYS2_SUM.replace(
            "FINDINGS_PLACEHOLDER",
            json.dumps(all_findings, ensure_ascii=False, indent=2),
        )
        resp_sum = llm_call(prompt_sum, temperature=0.3, max_tokens=3000)
        s2 = _parse(resp_sum.content.strip())
    except Exception as e:
        print(f"  汇总失败 ({e})")
        s2 = {}

    for v in s2.get("verdicts", []):
        icon = {
            "confirmed": "✓",
            "rejected": "✗",
            "evidence_with_difficulty": "△",
            "no_evidence": "?",
        }.get(v.get("verdict", ""), "?")
        print(f"\n  {icon} {v.get('assumption', '')}")
        for e in v.get("supporting", []):
            print(
                f"     支持：{textwrap.fill(e, width=66, subsequent_indent='           ')}"
            )
        for e in v.get("challenging", []):
            print(
                f"     挑战：{textwrap.fill(e, width=66, subsequent_indent='           ')}"
            )
        print(f"     判断：{v.get('verdict', '')}")
        print(
            f"     信号：{textwrap.fill(v.get('signals_to_watch', ''), width=66, subsequent_indent='           ')}"
        )
    for ns in s2.get("new_signals", []):
        print(f"\n  [新信号] {textwrap.fill(ns, width=72)}")
    print(f"\n  总结：{textwrap.fill(s2.get('summary', ''), width=72)}\n")

    # 更新存档（含汇总）
    result = {
        "timestamp": ts,
        "context": ctx,
        "system1": s1,
        "system2": {"per_area": all_findings, "summary": s2},
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"结果已保存：{result_path}\n")


def cmd_report(name=None):
    result_dir = DATA_DIR / "results"
    if not result_dir.exists():
        print("暂无保存的结果\n")
        return
    if name:
        path = result_dir / name
        if not path.exists():
            print(f"未找到：{name}\n")
            return
        r = json.loads(path.read_text())
        print(f"\n结果：{path.stem}")
        print(f"时间：{r.get('timestamp', '')}")
        print(f"\n--- System 1 ---")
        print(f"核心逻辑：{r.get('system1', {}).get('core_logic', '')}")
        for a in r.get("system1", {}).get("assumptions", []):
            print(f"  [{a.get('type', '')}] {a.get('statement', '')}")
            print(f"    风险：{a.get('risk', '')}")
            print(f"    若不成立 → {a.get('counterfactual', '')}")
            print(f"    信号：{a.get('signal_to_watch', '')}")
        print(f"\n--- System 2 ---")
        for v in r.get("system2", {}).get("summary", {}).get("verdicts", []):
            print(f"  {v.get('verdict', '?')} {v.get('assumption', '')}")
        print(f"总结：{r.get('system2', {}).get('summary', {}).get('summary', '')}\n")
    else:
        files = sorted(result_dir.glob("*.json"), reverse=True)
        if not files:
            print("暂无保存的结果\n")
            return
        print(f"\n保存的结果（共 {len(files)} 个）：\n")
        for f in files:
            r = json.loads(f.read_text())
            ts = r.get("timestamp", f.stem)
            ctx = r.get("context", {})
            company = ctx.get("company", "?")
            verdicts = r.get("system2", {}).get("summary", {}).get("verdicts", [])
            n_rejected = sum(1 for v in verdicts if v.get("verdict") == "rejected")
            n_confirmed = sum(1 for v in verdicts if v.get("verdict") == "confirmed")
            print(f"  {f.name}  {ts}")
            print(f"    公司：{company}")
            print(
                f"    状态：✓{n_confirmed} ✗{n_rejected} △{len(verdicts) - n_confirmed - n_rejected}\n"
            )


def cmd_help():
    print("""Bug is Feature -- 战略假设压力测试机

用法：./strategy.py <命令>

命令：
  new [file]           发起推演（可指定 JSON 上下文文件）
  report [文件名]       查看保存的结果（不指定文件名则列出所有）
  help                 显示帮助
""")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) < 2 or sys.argv[1] == "help":
        cmd_help()
        return
    cmd = sys.argv[1]
    if cmd == "new":
        cmd_new(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "report":
        cmd_report(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        cmd_help()


if __name__ == "__main__":
    main()
