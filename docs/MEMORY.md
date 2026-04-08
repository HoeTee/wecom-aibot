# Memory

## 目的

session memory 的存在，是为了在企业微信会话里维持文档连续性。

## 真正重要的字段

- `session_id`
- `doc_id`
- `doc_url`
- `doc_name`
- 最近上传文件状态：`file_name`、`stored_path`、`file_sha256`、`upload_action`

## 预期行为

- 当用户说“上一个文档”时，memory 应该能解析这个引用
- 当用户要求编辑时，系统应更新现有文档绑定
- 当用户刚上传 PDF，又说“把这份文档添加到知识库”时，系统应直接消费最近上传文件状态，而不是再次向用户索要文件
- memory 注入应优先提供当前绑定文档信息和最近用户请求，不应把旧 assistant 结论当作权威事实反复注入
- memory 的迭代方式是修改读写逻辑或注入逻辑，而不是回写历史记录
