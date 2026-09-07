# 路线图 — 量潮数据（qtdata）

所有功能通过 `qtdata` CLI 实现（位于 `src/cli/`），数据存储在本地契约文件（JSON/YAML）中，不依赖 Provider API 或 Studio 端。

## 阶段二：技术管理体系代码化

**目标：把"需求拆解→过程管控→质量兜底"这套体系从文档变成可执行的 CLI 命令。**

验收条件：一个新项目从接单到交付的全过程，可以通过 CLI 走完，不依赖微信群聊。

---

### 2.1 需求拆解模板化

**现状**：PRD 定义了 5 阶段用户故事地图，流程靠人在群里走。

**目标**：每个阶段有 CLI 子命令管理标准化表单和流转。

- [ ] `qtdata requirement create` — 创建需求规格（业务目标、场景描述、样本数据、验收标准）
- [ ] `qtdata requirement list` — 列出需求清单及确认状态
- [ ] `qtdata pseudocode submit` — 提交清洗伪代码版本
- [ ] `qtdata pseudocode confirm` — 客户确认伪代码，状态流转
- [ ] `qtdata quotation create` — 创建报价单（定价规则、分阶段付款、变更成本）
- [ ] `qtdata change-request create` — 提交变更请求（影响评估、成本变更）
- [ ] `qtdata change-request approve|reject` — 审批变更请求

### 2.2 交付验收准则系统化

**现状**：BRD 场景五定义了交付规范，但交付物无系统化验收状态追踪。

**目标**：每个交付物关联验收准则，验收流程 CLI 闭环。

- [ ] `qtdata asset create` — 创建交付物（类型：dataset/processor/doc，关联流程、验收准则）
- [ ] `qtdata asset list` — 列出交付物及状态
- [ ] `qtdata asset submit` — 提交交付物待验收
- [ ] `qtdata asset verify` — 客户验证交付物，记录验收结论
- [ ] `qtdata asset accept|reject` — 签署验收/驳回，触发状态流转

### 2.3 质量回溯机制

**现状**：问题追溯困难，数据血缘只有文档定义。

**目标**：每个交付物可回溯到数据来源、处理步骤、责任人。

- [ ] `qtdata pipeline create` — 创建数据处理流程定义（输入/输出 Dataset 关联）
- [ ] `qtdata pipeline log` — 记录处理步骤日志（参数、执行时间、异常）
- [ ] `qtdata issue create` — 创建问题工单，关联交付物/数据集
- [ ] `qtdata issue trace` — 展示指定交付物的完整血缘链（数据来源→处理步骤→产出）
- [ ] `qtdata issue resolve` — 标记工单已修复，关联修复版本

### 2.4 供应商侧标准映射

**现状**：内部标准无法被外部团队执行。

**目标**：内部标准可导出、外部交付物可自动校验。

- [ ] `qtdata standard export` — 导出内部交付规范为外部可读格式（Markdown/JSON schema）
- [ ] `qtdata asset validate` — 校验外部提交的交付物是否符合验收准则
- [ ] `qtdata task assign` — 分配任务给外部供应商（含交付标准、截止日期）

---

### 数据存储

所有数据以契约文件（JSON/YAML）形式存储在本地，遵循 `data/` 档案库惯例：

```
data/qtdata/
  requirements/    — 需求规格
  pseudocodes/     — 伪代码版本
  quotations/      — 报价单
  change-requests/ — 变更请求
  assets/          — 交付物
  pipelines/       — 流程定义
  issues/          — 问题工单
```
