# asset submit

提交交付物待验收。

## 输入

- 交付物 ID
- 交付物文件路径
- 版本说明

## 输出

更新 `data/qtdata/assets/<id>.json`，状态变为 submitted

## 验收

- [ ] 提交后状态变为 submitted
- [ ] 记录版本信息和提交时间
