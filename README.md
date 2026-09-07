# 量潮科技实验室

公司级实验空间：正式流程之外「先试一试」的地方。实验验证有效后，把方法与经验提取到对应档案、产品与流程。

## 结构

| 目录 | 说明 |
|------|------|
| `docs/` | 实验文档 |
| `examples/` | 实验代码、样本与报告 |

## 实验

- **交叉审查与收敛性验证**（`validate_cross_review.py`、`validate_convergence.py`）：在「代码 → 文档 → 重写代码」的交叉审查机制下，验证稳态模块能否收敛，用 Token Diff 量化代码混乱度。样本来自生产代码（`samples/`），报告见 `cross_review_report.md` 与 `reports/`
- **双盲穿透**（`double_blind_penetration.py`）：利用 AI 的「过度合理化」倾向作为探针，通过信息保真度量化代码混乱度
- 实验产出 JSON 结果统一存放于 `reports/`，由 `gen_report.py` 生成可读报告

## 工作纪律

见 [AGENTS.md](./AGENTS.md)：人类优先于 AI，结构性变更前先确认。
