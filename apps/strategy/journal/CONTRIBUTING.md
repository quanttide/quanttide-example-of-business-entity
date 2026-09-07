# CONTRIBUTING

## 日志分类标准

日志按业务领域分类，每个领域一个目录，按日期记录。

**目录结构**：
- 第一级：业务领域（qtadmin、qtclass、qtcloud、qtconsult、qtdata）
- 第二级：日期日志（YYYY-MM-DD.md）

**命名规范**：
- 目录名以 `qt` 开头，对应业务线标识
- 文件名统一为 `YYYY-MM-DD.md`

**日志内容规范**：
- 记录事实：什么时间、什么人、什么事
- 记录决策：为什么这么做、有什么依据
- 记录结果：做完了还是没做完、后续安排
- 避免空泛评价，用具体证据支撑观点

## 提交规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 规范：`<type>: <description>`

### 提交类型

- feat：新功能
- fix：修复 bug
- docs：文档更新
- test：测试相关
- refactor：代码重构
- chore：构建/工具