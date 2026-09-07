# API 参考

工作台不设 HTTP 服务，API 指 `store.py` 的状态迁移函数——每个函数是状态机的一个执行器，返回 `(bool, str)`：成功标志与可读错误信息。

## 状态机

```
applied → survey_done → invited → task_assigned → task_submitted
        → reviewing → graded → enrolled
```

终态外分支：`dormant`（超时未响应，可重新激活）、`rejected`（未通过，终态）。

## 状态迁移函数

| 函数 | 触发动作 | 状态迁移 | 留痕 |
|------|----------|----------|------|
| `create_application(name, school='', course='')` | 学员提交报名表 | → `applied` | `applied_at` |
| `submit_survey(name, answers)` | 学员提交准入问卷 | `applied` → `survey_done` | `survey_json`、`survey_at` |
| `grant_invite(name)` | 问卷提交后系统内自动触发 | `survey_done` → `invited` | — |
| `assign_task(name)` | 学员点击「已领到任务，标记进行中」 | `invited` → `task_assigned` | — |
| `submit_delivery(name, delivery)` | 学员在面板提交交付物 | `task_assigned` → `task_submitted` | `delivery_json` |

通用约束：姓名即身份（`UNIQUE`），重名建档被拦截并返回可读错误；操作不存在的报名记录返回「未找到报名记录」。

## 查询

| 函数 | 返回 |
|------|------|
| `get_application(name)` | 报名记录 dict（含状态、问卷、交付、时间戳），不存在返回 `None` |

## 规划中

评审环节的迁移函数（评估结论录入：授予免费学员资格 / 退回）尚未实现，见 [ROADMAP](../../ROADMAP.md)。付费点（与免费资格双轨）为更远期的预留，不进入当前状态机。
