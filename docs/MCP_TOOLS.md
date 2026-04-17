# MCP Tools

## 目的

这份文档只记录 agent 当前实际能看到和调用的工具面。

## 工具来源

- MCP 连接与调度统一在 `backend/runtime/*`
- 本地 tool 实现统一在 `backend/tools/*`
- 当前动作层开始收敛成 CLI 风格：
  - `backend/runtime/cli.py`
  - `backend/tools/kb_cli.py`
  - `backend/tools/rag_cli.py`
- 本地 `stdio` MCP 服务如果启动即退出，应优先检查 `data/logs/mcp/<server_name>_stderr.log`
- `runtime` 在 stdio 连接失败时，应同时记录 `command`、`args`、`cwd` 和对应 stderr 日志路径

1. 外部 MCP server 暴露的工具
2. 本地注册的 KB / doc / RAG 工具

## 外部 MCP 工具

外部 MCP 工具由 `backend/runtime/host.py` 注册。

规则：

- 配置来源是 `.env` 里的 `MCP_SERVERS_CONFIG`
- 样例文件是 `config/mcp_servers.example.json`
- 每个远端工具会被暴露成 `<tool_prefix>__<remote_tool_name>`

例如：

- 远端 `create_doc`
- 如果 `tool_prefix=wecom_docs`
- agent 看到的就是 `wecom_docs__create_doc`

当前仓库默认假设企业微信文档 / 智能表格能力来自外部 MCP，而不是本地 Python 直接实现。

## 本地 agent 工具

本地工具定义在 `backend/runtime/local_tools.py`。

当前实际暴露给 agent 的工具名是：

```text
agent__no_tool_needed
kb__list_files
kb__match_related_files
kb__export_file
kb__rename_file
kb__delete_file
llamaindex_rag__llamaindex_rag_search
```

说明：

- `kb__list_recent_uploads` 在本地 runtime 里有实现，但当前没有加入 agent 可见工具列表
- `llamaindex_rag__llamaindex_rag_summarize` 有底层实现，但当前没有暴露给 agent，原因是延迟较高
- 历史版本曾暴露过 `doc__read_markdown` / `doc__append_section` / `doc__preview_replace` / `doc__replace_section` / `doc__expand_section` 一族本地工具；当前版本已从 agent 可见列表移除，运行时侧同时加了硬拦截。所有文档正文写入统一走外部 MCP 的 `edit_doc_content`

## 各工具家族的实际边界

### `kb__*`

当前对应：

- `backend/tools/kb_cli.py`

职责：

- 列出本地 `knowledge_base/*.pdf`
- 按文件名和最近对话别名做相关匹配
- 导出原始 PDF
- 重命名文件
- 删除文件

关键约束：

- 操作对象是本地 PDF 文件，不是文档正文
- `kb__rename_file` 和 `kb__delete_file` 必须带 `confirmed=true`
- 目标文件通过 `file_name` 或 `stored_path` 指定

### `wecom_*` / `wecom_docs__*`

这类工具来自外部 MCP server，通常承担：

- `create_doc`
- `edit_doc_content`
- 智能表格创建
- 智能表格字段追加
- 智能表格记录追加

关键约束：

- `create_doc` 只创建空壳
- 真正完成文档任务，后面还必须跟正文写入动作
- 能不能读取文档、能不能创建智能表格，取决于当前 MCP server 暴露了哪些 remote tools

### `llamaindex_rag__*`

当前对应：

- `backend/tools/llamaindex_rag/runtime.py`
- `backend/tools/rag_cli.py`

当前 agent 实际只会用到：

- `llamaindex_rag__llamaindex_rag_search`

用途：

- 对本地知识库 PDF 做检索
- 给文档写作提供来源片段

## prompt 对工具调用的额外限制

除了工具本身的参数校验，系统 prompt 还施加了这些约束：

- 只要请求可以通过工具执行，就必须调用工具
- 创建文档后必须继续调用写入工具
- 不允许把 `kb__export_file` 当成“写文档”的替代动作
- 不允许通过别的写入工具去伪装“查看文档/查看表格内容”
- 智能表格已有行不支持修改或删除

## runtime 如何分发

当前分发路径是：

1. `backend/flow/chat.py` 连接 `MCPHost`
2. `MCPHost` 加载外部 MCP tools
3. `get_local_agent_tools()` 加载本地工具
4. agent 在同一个 tool loop 里混合调用两类工具

本地动作最终会进入：

- `backend/runtime/cli.py`
- `backend/tools/kb_cli.py`
- `backend/tools/rag_cli.py`

## 日志定位

查工具相关问题时，优先看这些位置：

- `data/logs/flow/flow_runtime.log`
- `data/logs/cli/cli_runtime.log`
- `data/logs/cli/rag_runtime.log`
- `data/logs/mcp/<server_name>_stderr.log`

其中 stdio MCP server 启动失败时，`stderr.log` 最关键。
