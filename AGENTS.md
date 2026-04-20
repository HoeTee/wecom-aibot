# AGENTS

这个仓库是一个面向企业微信文档工作流的 agent。

核心闭环：

1. 接收企微文本消息或 PDF 上传
2. PDF 上传写入 `knowledge_base/` 后，由 `IndexRebuildScheduler` 在后台重建检索索引（非阻塞，与检索侧共用 `_BUILD_LOCK`）
3. 结合知识库、会话状态和外部 MCP 能力理解请求
4. 创建或更新企业微信文档 / 智能表格
5. 通过 `doc_id`、`doc_url`、`doc_name` 维持连续性
6. 通过 SQLite 和记日志保存最近上传状态、tool 调用和最终回复

`AGENTS.md` 只做索引，不写长手册。

## Source Of Record

- [docs/PRODUCT.md](/C:/Users/18014/wecom-aibot/docs/PRODUCT.md)
- [docs/DOC_WRITING.md](/C:/Users/18014/wecom-aibot/docs/DOC_WRITING.md)
- [docs/REPLY_STYLE.md](/C:/Users/18014/wecom-aibot/docs/REPLY_STYLE.md)
- [docs/MCP_TOOLS.md](/C:/Users/18014/wecom-aibot/docs/MCP_TOOLS.md)
- [docs/MEMORY.md](/C:/Users/18014/wecom-aibot/docs/MEMORY.md)
- [docs/ARCHITECTURE.md](/C:/Users/18014/wecom-aibot/docs/ARCHITECTURE.md)
- [docs/ROUTING_RULES.md](/C:/Users/18014/wecom-aibot/docs/ROUTING_RULES.md)
- [docs/FLOWS.md](/C:/Users/18014/wecom-aibot/docs/FLOWS.md)
- [docs/CHECKS.md](/C:/Users/18014/wecom-aibot/docs/CHECKS.md)
- [docs/EVALS.md](/C:/Users/18014/wecom-aibot/docs/EVALS.md)

## 当前目录约定

运行时目录：

- `backend/entry`
- `backend/flow`
- `backend/policy`
- `backend/state`
- `backend/caps`
- `backend/runtime`
- `backend/tools`
- `gateway`
- `scripts`
- `docs`

运行时数据目录：

- `data/`
- `knowledge_base/`

当前工作树里没有 `he/` 目录；如果看到旧文档提到 `he/`，请按历史设计说明理解，不要把它当作当前必改目录。

## 稳定入口文件名

- `backend/app.py`
- `backend/agent.py`
- `backend/memory.py`
- `backend/entry/http.py`
- `backend/flow/chat.py`
- `backend/flow/upload.py`
- `scripts/check_layers.py`
- `scripts/mcp_test.py`
- `scripts/cleanup_artifacts.py`
- `gateway/long_connection.ts`

## 可修改文件

正常迭代优先改这些位置：

- `prompts/system/*`
- `backend/app.py`
- `backend/agent.py`
- `backend/memory.py`
- `backend/entry/*`
- `backend/flow/*`
- `backend/policy/*`
- `backend/state/*`
- `backend/caps/*`
- `backend/runtime/*`
- `backend/tools/*`
- `docs/*.md`
- `README.md`
- `.gitignore`

## 非必要不要修改

- `knowledge_base/*.pdf`
- `config/mcp_servers.json`
- `data/`
- `gateway/long_connection.ts`

## 迭代规则

一次只改一个主要层面：

- prompt
- flow / policy / state
- runtime / tools
- docs

改代码后至少做这些检查：

- 跑相关单测
- 运行 `python scripts/check_layers.py`

如果只是改文档：

- 重点检查交叉引用、目录名、脚本名和当前工作树是否一致
