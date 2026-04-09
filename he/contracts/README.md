# Contracts

这里放动作级 contract checks。

当前方向：

- 先检查 `kb.*`
- 再扩到 `doc.*`
- 最后补 `rag.*`

contract check 重点不是用户场景，而是：

- 输入参数是否稳定
- JSON 输出是否稳定
- 返回码/结果字段是否稳定
- 副作用是否明确
