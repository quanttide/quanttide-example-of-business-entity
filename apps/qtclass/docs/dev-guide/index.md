# 开发者指南

工作台是「河床架构」的参考实现：学员旅程是单一系统内的连续流程，每个状态迁移都是系统内事件，不需要任何人在中间缝合。

业务背景对设计的约束（详见 [README](../../README.md)）：这是卖课平台，当前只承载免费学员资格——流程脱胎于招聘考核并与之同构，评审环节的产出是资格授予结论而非质检打分；授予即入册（加入实训基地），基地内培养由另一飞书账户承载，不在本系统状态机内；付费点只是预留，状态机与文档不为其提前建模。

## 架构

```
workbench.py（GUI）            store.py（存储）
┌──────────────────┐          ┌──────────────────┐
│ JOURNEY 时间线     │          │ 状态迁移函数       │
│ STAGE_DETAIL 面板 │ ──动作──▶ │ （状态机的执行器）  │
│ STATUS_STAGE 映射 │ ◀─状态──  │ SQLite 单文件      │
└──────────────────┘          └──────────────────┘
```

- **河床存储**：SQLite 单文件（`data/workbench.db`），零外部依赖
- **工作台 GUI**：PySide6 单窗口，时间线主干 + 当前节点动作面板 + 内嵌表单

## 状态机即数据

状态枚举、状态到旅程阶段的映射、各节点的动作清单全部是代码里的表：

| 表 | 位置 | 职责 |
|----|------|------|
| 迁移函数 | `store.py` | 每个「状态迁移 = 一个函数」，写入新状态与留痕字段 |
| `STATUS_STAGE` | `workbench.py` | 状态机状态 → 旅程阶段（面板）索引 |
| `STAGE_JOURNEY` | `workbench.py` | 旅程面板 → 时间线节点高亮 |
| `STAGE_DETAIL` | `workbench.py` | 各面板的标题、说明、动作清单 |

改流程 = 改表：新增节点只需加迁移函数与面板条目，界面自动跟随。

## API 参考

工作台不设 HTTP 服务，API 指 `store.py` 的状态迁移函数——每个函数返回 `(bool, str)`：成功标志与可读错误信息。

状态机全图：

```
applied → survey_done → invited → task_assigned → task_submitted
        → reviewing → graded → enrolled
```

终态外分支：`dormant`（超时未响应，可重新激活）、`rejected`（未通过，终态）。

状态迁移函数：

| 函数 | 触发动作 | 状态迁移 | 留痕 |
|------|----------|----------|------|
| `create_application(name, school='', course='')` | 学员提交报名表 | → `applied` | `applied_at` |
| `submit_survey(name, answers)` | 学员提交准入问卷 | `applied` → `survey_done` | `survey_json`、`survey_at` |
| `grant_invite(name)` | 问卷提交后系统内自动触发 | `survey_done` → `invited` | — |
| `assign_task(name)` | 学员点击「已领到任务，标记进行中」 | `invited` → `task_assigned` | — |
| `submit_delivery(name, delivery)` | 学员在面板提交交付物 | `task_assigned` → `task_submitted` | `delivery_json` |

查询：`get_application(name)` 返回报名记录 dict（含状态、问卷、交付、时间戳），不存在返回 `None`。

通用约束：姓名即身份（`UNIQUE`），重名建档被拦截并返回可读错误；操作不存在的报名记录返回「未找到报名记录」。

评审环节的迁移函数（评估结论录入：授予免费学员资格 / 退回）尚未实现，见 [ROADMAP](../../ROADMAP.md)。付费点（与免费资格双轨）为更远期的预留，不进入当前状态机。

## 运行与测试

```bash
uv sync                                        # 安装依赖（PySide6 + pytest）
uv run python apps/qtclass/src/workbench.py    # 启动工作台
uv run pytest                                  # 集成测试（离屏，不触碰演示数据）
```

测试约束：

- 每个测试独享临时数据库（`conftest.py` 的 `tmp_store` 夹具），不读写 `data/`
- GUI 测试在 `QT_QPA_PLATFORM=offscreen` 下运行，无需显示器
- 旅程测试覆盖全链路：报名 → 问卷 → 领任务 → 交付，断点续接与校验分支

## 扩展约定

- 新的状态迁移：先在 `store.py` 加函数（函数文档字符串写清触发者与语义），再改 `STATUS_STAGE`/`STAGE_DETAIL`，最后补测试
- 时间线与面板分离：面板以动作定义（`STAGE_DETAIL`），时间线以旅程节点高亮（`STAGE_JOURNEY`），两者通过映射对齐

## 边界

- 生产实现运行于内部环境（飞书档案镜像、邮件异常通道等业务集成），不在本仓库
- 跨模块共用机制（部署、文档标准）见主仓库，不在本目录
