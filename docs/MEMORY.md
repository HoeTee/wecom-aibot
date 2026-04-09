# Memory

## 目的

session memory 的存在，是为了在企业微信会话里维持文档连续性和上传状态连续性。

当前代码上：

- 稳定入口仍是 `backend/memory.py`
- 真实实现优先收敛到 `backend/state/*`

## 真正重要的字段

- `session_id`
- `doc_id`
- `doc_url`
- `doc_name`
- 最近上传文件状态：
  - `file_name`
  - `stored_path`
  - `file_sha256`
  - `upload_action`

## 预期行为

- 当用户说“上一个文档”时，memory 应该能解析这个引用
- 当用户要求编辑时，系统应更新现有文档绑定
- 当用户刚上传 PDF，又说“把这份文档添加到知识库”时，系统应直接消费最近上传文件状态，而不是再次索要文件
- memory 注入应优先提供当前绑定文档信息和最近用户请求，不应把旧 assistant 结论当作权威事实反复注入
- memory 的迭代方式是修改读写逻辑或注入逻辑，而不是回写历史记录

## 分层位置

`memory` 现在属于 `state` 层，不属于 `flow`。

它负责：

- 提供会话事实
- 维护持久状态
- 提供当前绑定对象

它不负责：

- 决定完整业务流程
- 自己选择 route
- 自己决定是否调用 tool

## 与 HE 的关系

HE 会重点看这些 memory 相关问题：

- 是否误复用旧文档
- 是否上传状态丢失
- 是否把旧 assistant 结论当事实
- 是否在 follow-up 里取错当前绑定文档

相关证据主要体现在：

- `doc_binding.json`
- `uploaded_file.json`
- `flow_trace.json`
