# wecom-aibot

企业微信文档工作流 agent。用户在企微里发文本消息或上传 PDF，bot 会结合本地知识库、外部 MCP 能力和会话状态，去创建或更新企业微信文档/智能表格。

> 推荐在个人聊天窗口使用。当前文件上传仅支持 PDF，且网关按会话串行处理消息；群聊里更容易出现会话串线和意图污染。

## 当前能力

- PDF 上传到本地知识库，并记录最近上传状态
- 知识库 PDF 列表、相关文件匹配、导出原 PDF、重命名、删除
- 企业微信文档创建与正文写入
- 基于当前绑定文档做章节追加、替换、扩写
- 智能表格创建、字段追加、记录追加

## 能力边界

| 能做 | 不能做 |
|------|--------|
| 单聊中上传 PDF 到知识库 | 群聊中上传文件到知识库 |
| 创建或更新企微文档，并返回链接 | 把文档全文展示在聊天里 |
| 创建智能表格、追加字段和记录 | 查看、读取、修改、删除已有表格行 |
| 导出、重命名、删除知识库中的 PDF 文件 | 修改 PDF 文件内部内容 |
| 仅支持 PDF 入知识库 | Word / Excel / 图片 / txt 入知识库 |

系统约束以 [prompts/system/assistant_v1.md](prompts/system/assistant_v1.md) 为准。超出边界时，agent 会直接回复不支持，而不是绕路调用其它工具。

## 快速开始

### 前置

- Python 3.11+
- Node.js 20+
- 企业微信 AI Bot 的 `WECOM_BOT_ID` / `WECOM_BOT_SECRET`
- 可用的 LLM、Embedding、Rerank 服务
- 可用的企业微信文档 MCP 服务

### 安装

Windows (PowerShell)：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
Copy-Item .env.example .env
Copy-Item config\mcp_servers.example.json config\mcp_servers.json
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
cp .env.example .env
cp config/mcp_servers.example.json config/mcp_servers.json
```

### 配置

编辑 `.env`，至少补全这些变量：

```env
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

EMBED_API_KEY=sk-xxx
EMBED_MODEL=text-embedding-v4
RERANK_API_KEY=sk-xxx
RERANK_MODEL=qwen3-rerank

WECOM_BOT_ID=xxx
WECOM_BOT_SECRET=xxx
BACKEND_BASE_URL=http://127.0.0.1:5000
MCP_SERVERS_CONFIG=config/mcp_servers.json
```

编辑 `config/mcp_servers.json`，把企业微信文档 MCP 的地址和认证信息换成你自己的配置。样例文件在 [config/mcp_servers.example.json](config/mcp_servers.example.json)。

### 启动

两个进程同时运行：

```bash
# 1) Flask 后端
python -m backend.app

# 2) 企业微信长连接网关
npm run gateway
```

验证后端：

```bash
curl http://127.0.0.1:5000/health
```

网关会把文本消息转发到 `/chat`，把 PDF 文件转发到 `/knowledge-base/upload`。

## 架构概览

```text
企微客户端
   ↓
gateway/long_connection.ts
   ├─ 文本消息 -> POST /chat
   └─ PDF 文件 -> POST /knowledge-base/upload

backend/entry/http.py
   ├─ /chat -> backend/flow/chat.py
   └─ /knowledge-base/upload -> backend/flow/upload.py

backend/flow/
   ├─ 生成 request_id / session_id
   ├─ 加载 memory_context / chat_history
   ├─ 生成 intent packet
   ├─ 连接外部 MCP
   └─ 混合调用 MCP 工具和本地工具

backend/state/store.py
   ├─ conversation_turns
   ├─ tool_calls
   ├─ session_docs
   └─ session_uploaded_files

backend/tools/
   ├─ kb_cli.py
   ├─ doc_cli.py
   ├─ rag_cli.py
   └─ llamaindex_rag/
```

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 目录速查

| 路径 | 说明 |
|------|------|
| `backend/entry/http.py` | Flask 入口，暴露 `/health`、`/chat`、`/knowledge-base/upload` |
| `backend/flow/chat.py` | 文本消息主流程，负责 intent packet、memory、tool runtime、最终回复 |
| `backend/flow/upload.py` | PDF 上传入知识库与上传状态持久化 |
| `backend/policy/` | 新建文档判定、上传校验、智能表格限制、flow payload 构造 |
| `backend/state/store.py` | SQLite 会话状态、文档绑定、上传记录、flow 日志 |
| `backend/runtime/` | MCP 连接、路由、CLI dispatch、本地工具注册 |
| `backend/runtime/local_tools.py` | agent 可直接调用的本地 KB/doc/RAG 工具定义 |
| `backend/tools/doc_cli.py` | 文档 Markdown 读改写逻辑 |
| `backend/tools/kb_cli.py` | 本地知识库 PDF 管理 |
| `backend/tools/llamaindex_rag/` | 本地 RAG 检索实现 |
| `data/memory.sqlite3` | 会话数据库 |
| `data/logs/flow/` | flow 事件日志 |
| `data/logs/cli/` | 本地 CLI/RAG 运行日志 |

## 故障排查

- 文档创建成功但正文没写进去：`create_doc` 只会创建空壳，后面必须还有正文写入动作。先看 `data/logs/flow/flow_runtime.log`，再看 `data/logs/cli/cli_runtime.log`。
- PDF 上传被拒：当前只接受扩展名和文件头都合法的 PDF；其它文件类型会直接报错。
- 知识库文件重命名/删除没有执行：这两个动作要求 agent 先拿到明确确认，再带 `confirmed=true` 调本地工具。
- 智能表格要改已有行：当前实现直接视为不支持，只支持追加字段和新记录。

## 其它文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 当前运行时结构、状态存储与日志落点
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) — agent 实际可见的 MCP / 本地工具面
- [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md) — 当前代码里真正生效的路由规则
- [docs/FLOWS.md](docs/FLOWS.md) — 真实存在的端到端流程
- [docs/DOC_WRITING.md](docs/DOC_WRITING.md) — 文档创建、续写、替换时的写入约束
- [docs/REPLY_STYLE.md](docs/REPLY_STYLE.md) — 面向用户的最终回复约束
- [AGENTS.md](AGENTS.md) — 仓库索引与改动边界
