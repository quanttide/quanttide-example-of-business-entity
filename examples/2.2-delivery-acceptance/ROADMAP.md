# 实验 2.2：交付验收准则系统化

**阶段二：技术管理体系代码化**

## 实验目标

将 BRD 场景五定义的交付规范转化为系统化的验收状态追踪，每个交付物关联验收准则，验收流程 CLI 闭环。

## 验收条件

一个交付物从创建→提交→验证→签署/驳回的全过程，可通过 CLI 完成，验收结论可追溯。

## 任务清单

- [ ] `qtdata asset create` — 创建交付物（类型：dataset/processor/doc，关联流程、验收准则）
- [ ] `qtdata asset list` — 列出交付物及状态
- [ ] `qtdata asset submit` — 提交交付物待验收
- [ ] `qtdata asset verify` — 客户验证交付物，记录验收结论
- [ ] `qtdata asset accept|reject` — 签署验收/驳回，触发状态流转

## 数据存储

```
data/qtdata/
  assets/          — 交付物 JSON（含状态、验收记录）
```
