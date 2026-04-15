# 架构

## 目的

这份文档只描述当前仓库里已经存在的运行时结构，不写未来规划。

## 顶层组件

当前工作树里的主要组件是：

- `gateway/long_connection.ts`
- `backend/app.py`
- `backend/entry/http.py`
- `backend/flow/*`
- `backend/policy/*`
- `backend/state/*`
- `backend/caps/*`
- `backend/runtime/*`
- `backend/tools/*`
- `scripts/*`

当前仓库里没有 `he/` 目录；如果其它文档提到 HE，请按“历史设计说明”理解，而不要把它当成当前工作树的一部分。

## 两条入口链路

### 1. 文本消息链路

入口：

- 企业微信消息
- `gateway/long_connection.ts`
- `POST /chat`

实际顺序：

1. 网关把文本消息转成 `ChatRequest`
2. `backend/entry/http.py` 调 `backend.flow.chat.run_chat`
3. `run_chat` 生成 `request_id` 和 `session_id`
4. 先检查是否命中“最近上传 PDF 的 follow-up 确认”短路逻辑
5. 决定是否把当前绑定文档注入 memory
6. 连接外部 MCP，并拼接本地 KB/doc/RAG 工具
7. 从 SQLite 读取当前绑定文档、最近对话、最近上传文件
8. 调 LLM 生成结构化 `intent packet`
9. 进入 agent tool loop
10. 持久化 tool call、文档绑定、最终回复

### 2. PDF 上传链路

入口：

- 企业微信文件消息
- `gateway/long_connection.ts`
- `POST /knowledge-base/upload`

实际顺序：

1. 网关下载文件
2. `backend/flow/upload.py` 校验扩展名和 PDF 文件头
3. 调 `backend.caps.knowledge_base.store_pdf_in_knowledge_base`
4. 写入 `knowledge_base/`
5. 保存最近上传状态到 `session_uploaded_files`
6. 返回上传结果给用户

## 运行时层级

### `entry`

当前对应：

- `backend/app.py`
- `backend/entry/http.py`
- `gateway/long_connection.ts`

职责：

- 接收外部输入
- 调用后端入口
- 返回文本回复或文件附件

### `flow`

当前对应：

- `backend/agent.py`
- `backend/flow/chat.py`
- `backend/flow/upload.py`
- `backend/flow/agent_core.py`

职责：

- 生成当前请求的执行上下文
- 组织 memory、tool runtime、agent 循环
- 处理短路分支、超时和停止原因

当前 hard-coded 规则主要只有几类：

- 最近上传文件的 follow-up 确认
- “重新生成一份文档”时不复用当前绑定文档
- 智能表格已有行修改/删除直接判不支持

更细的意图分流主要仍然依赖 `intent packet + prompt`。

### `policy`

当前对应：

- `backend/policy/document.py`
- `backend/policy/upload.py`
- `backend/policy/smartsheet.py`
- `backend/policy/payloads.py`

职责：

- 定义少量确定性规则
- 构造 flow 事件 payload
- 做上传校验和智能表格限制

说明：

- `backend/policy/knowledge_base.py` 当前基本是占位文件
- 知识库的主路由并不在 Python 里做关键词树，而是交给 LLM 分类

### `state`

当前对应：

- `backend/memory.py`
- `backend/state/store.py`

职责：

- 持久化会话状态
- 维护当前绑定文档
- 提供 recent chat history 和 memory context
- 写 flow log

### `caps`

当前对应：

- `backend/caps/documents.py`
- `backend/caps/knowledge_base.py`
- `backend/caps/rag.py`

职责：

- 给上层提供薄封装
- 把常用动作收敛成可复用接口

当前特点：

- `caps` 很薄，很多实际分发仍然落在 `runtime` 和 `tools`

### `runtime`

当前对应：

- `backend/runtime/host.py`
- `backend/runtime/connection.py`
- `backend/runtime/cli.py`

所有 MCP 连接逻辑已统一到此目录。

### 7. `tools`

职责：

- 连接外部 MCP server
- 把远端工具暴露成 agent 可调用的工具名
- 注册本地 KB/doc/RAG 工具
- 记录 MCP 与 CLI 调用日志

当前实现里，agent 实际使用的是两类工具：

1. 外部 MCP 工具
2. `backend/runtime/local_tools.py` 注册的本地工具

### `tools`

当前对应：

- `backend/tools/kb_cli.py`
- `backend/tools/doc_cli.py`
- `backend/tools/rag_cli.py`

`tools` 层里的 stdio wrapper 还必须满足一条额外约束：

- 不能只做 import 转发
- 必须在 `__main__` 中显式启动 `run(...)`

### 8. `he`

职责：

- 真正执行本地动作
- 封装 WeCom 文档 Markdown 读改写
- 管理本地知识库 PDF
- 提供本地 RAG 检索

## 文本消息主流程中的关键对象

### `intent packet`

由 `backend/flow/agent_core.py` 里的 `classify_intent_packet` 生成。

当前允许的 family：

- `knowledge_base`
- `document`
- `smartsheet`
- `upload_followup`
- `general`

它不是最终执行结果，只是给 agent 提示“当前更像哪类请求”。

### `memory_context`

由 `backend/state/store.py` 动态拼出，当前可能包含：

- 当前绑定文档
- 最近若干轮用户请求及对应 tool 摘要
- 最近上传的 PDF

### `chat_history`

同样来自 `backend/state/store.py`，会按 `user -> assistant(tool_calls) -> tool -> assistant` 的格式重建最近若干轮消息，供 LLM 延续上下文。

## 文档连续性

文档连续性当前依赖 `session_docs` 表里的这些字段：

- `doc_id`
- `doc_url`
- `doc_name`
- `last_tool_name`
- `last_user_text`

一旦 tool 结果里能解析出有效 `doc_id`，系统就会更新绑定文档。  
后续如果命中“继续编辑上一个文档”的语义，默认会把这份绑定文档注入 memory。

## 上传连续性

上传连续性依赖 `session_uploaded_files` 表里的这些字段：

- `file_name`
- `stored_path`
- `file_sha256`
- `upload_action`
- `matched_file_name`
- `matched_stored_path`

当前 upload action 可能是：

- `added`
- `replaced`
- `unchanged`
- `duplicate_content`

## 日志与运行产物

当前主要运行产物在 `data/` 下：

- `data/memory.sqlite3`
- `data/logs/flow/flow_runtime.log`
- `data/logs/cli/cli_runtime.log`
- `data/logs/cli/rag_runtime.log`
- `data/logs/mcp/*`（stdio MCP 失败时最重要）

## 依赖方向

当前仓库仍按这条方向理解：

- `entry -> flow`
- `flow -> policy/state/runtime/caps`
- `runtime -> tools`

`scripts/check_layers.py` 会检查两类约束：

- 下层不能反向依赖上层
- `flow` 不能直接 import `tools`

## 当前应如何理解智能表格

智能表格仍然是独立意图家族，不等同于普通文档。

当前代码里实际存在的约束是：

- 能识别 `smartsheet` family
- 能把智能表格 URL 绑定进 `session_docs`
- 如果用户要求修改或删除已有行，直接回复不支持
- 其它智能表格动作是否能成功，取决于外部 MCP server 是否真正提供对应工具
