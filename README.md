# wecom-aibot

企业微信文档工作流 agent。用户在企微聊天里发消息或上传 PDF，bot 负责总结、整理、写入企微文档或智能表格。

> ⚠️ **推荐在个人聊天窗口（单聊）使用**。**知识库文件上传目前只支持 PDF 一种格式**，其它格式（Word / Excel / 图片 / txt 等）一律拒绝。群聊场景下意图识别易被多人插话污染、文档绑定也会串会话，不推荐。

## 能做什么

- **知识库**：上传 PDF 进本地向量库，做 RAG 问答与检索
- **文档**：创建企微文档壳，把总结/整理内容写入正文，追加/替换章节
- **智能表格**：创建表格，追加记录，读写列结构

## 能力边界

| 能做 | 不能做 |
|------|--------|
| 上传 PDF 入知识库（仅个人聊天，直接在窗口发送文件即可） | 群聊内上传文件 |
| 上传后台自动触发向量索引重建 | 同步等待索引完成 |
| 创建文档 + 写入正文 | 把文档内容展示给用户看 |
| 追加表格记录、改列结构 | 查看/读取/浏览表格行内容 |
| 追加表格行 | 修改/删除已有行 |
| 知识库文件列表、重命名、删除、导出 PDF | 修改/删除 PDF 内部内容 |
| 仅 PDF 入知识库 | Word / Excel / 图片 / txt 入知识库 |

能力清单与系统 prompt (`prompts/system/assistant_v1.md`) 保持一致。agent 遇到边界外请求会直接回复"暂不支持"；但"把 PDF 加入知识库"本身是产品固有能力，agent 会指引用户直接在个人聊天发送文件，而不是回"不支持"。

## 快速开始

### 前置

- Python 3.11+
- Node.js 20+
- 企业微信管理后台：创建 AI Bot，拿到 `WECOM_BOT_ID` / `WECOM_BOT_SECRET`
- LLM 服务：OpenAI-compatible endpoint（默认用 Moonshot 的 Kimi，模型 `kimi-k2.5`）
- 本地 RAG（可选）：阿里云 DashScope 的 embedding + rerank

### 安装

Windows (PowerShell)：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
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

> 后续 `python -m backend.app`、`python -m unittest ...`、`python scripts/...` 都假设 venv 已激活。新开终端记得重新激活（Windows `./.venv/Scripts/Activate.ps1`，macOS/Linux `source .venv/bin/activate`）。

### 配置

编辑 `.env`，至少填：

```env
# LLM（必填）
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=kimi-k2.5

# Embedding / Rerank（只要想用本地 RAG/知识库检索就必填；否则留空）
EMBED_API_KEY=sk-xxx
EMBED_MODEL=text-embedding-v4
RERANK_API_KEY=sk-xxx
RERANK_MODEL=qwen3-rerank

# 企微 AI Bot（长连接网关必填）
WECOM_BOT_ID=xxx
WECOM_BOT_SECRET=xxx

# 网关回 Flask 的地址，默认 127.0.0.1:5000。若改端口记得同步
BACKEND_BASE_URL=http://127.0.0.1:5000

# 外部 MCP server 清单（默认指向仓库里的 config/mcp_servers.json）
MCP_SERVERS_CONFIG=config/mcp_servers.json
```

完整变量清单见 `.env.example`（含 `TEMPERATURE`/`MAX_TOOL_CALLS` 等调参项）。

编辑 `config/mcp_servers.json`，把企微文档 MCP 的 `url` 换成你自己带 apikey 的地址。

### 启动

两个进程各自一个终端（都需要先激活 venv 再跑后端）：

```bash
# 终端 1 — 后端（Flask，监听 127.0.0.1:5000）
#   Windows:  .venv\Scripts\Activate.ps1
#   macOS/Linux:  source .venv/bin/activate
python -m backend.app

# 终端 2 — 企微长连接网关（Node，不需要 venv）
npm run gateway
```

验证：

```bash
curl http://127.0.0.1:5000/health
```

然后在企微里私聊 bot 发消息即可。

## 架构

```
企微客户端
   ↓ 长连接
gateway/long_connection.ts      Node 端，桥接企微协议
   ↓ HTTP POST /chat、/knowledge-base/upload
backend/entry/http.py           Flask 入口
   ↓
backend/flow/                   agent 主循环 (agent_core.py) + 消息编排 (chat.py)
   │
   ├→ backend/policy/           业务规则：意图识别、能力边界、上传策略
   ├→ backend/state/            SQLite 会话（对话历史、文档绑定、上传文件）
   ├→ backend/caps/             能力封装：documents / knowledge_base / rag
   └→ backend/runtime/          工具分发：外部 MCP host + 本地工具注册
                                   ↓
                                backend/tools/
                                   ├─ kb_cli.py / rag_cli.py   本地 CLI 入口
                                   └─ llamaindex_rag/          本地向量检索
```

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 目录速查

| 目录 | 内容 |
|------|------|
| `backend/app.py` | Flask 应用入口（`python -m backend.app`） |
| `backend/entry/http.py` | HTTP 路由：`/chat`、`/knowledge-base/upload`、`/health` |
| `backend/flow/` | agent 主循环 (`agent_core.py`) + 消息编排 (`chat.py`) + 上传处理 (`upload.py`) |
| `backend/policy/` | 能力边界、意图识别、上传策略、payload 生成 |
| `backend/state/store.py` | SQLite 持久化（conversation_turns / tool_calls / session_docs / session_uploaded_files） |
| `backend/caps/` | 能力封装层（documents / knowledge_base / rag） |
| `backend/runtime/` | 外部 MCP host (`host.py`) + 本地工具注册 (`local_tools.py`) + 分发 (`cli.py`) |
| `backend/tools/kb_cli.py` / `rag_cli.py` | 本地工具的 CLI 入口（知识库文件管理 / 本地 RAG 检索） |
| `backend/tools/llamaindex_rag/` | 本地 RAG：PDFReader + 向量检索 + Qwen reranker |
| `config/mcp_servers.json` | 外部 MCP server 配置（企微文档/智能表格能力） |
| `knowledge_base/` | 用户上传的 PDF（不入版本控制） |
| `prompts/system/assistant_v1.md` | 系统 prompt（含能力边界声明与模型身份约束） |
| `data/logs/flow/flow_runtime.log` | 结构化 JSON 运行日志 |
| `data/logs/mcp/<server>_stderr.log` | stdio MCP server 的 stderr（排查启动失败） |
| `data/memory.sqlite3` | 会话状态数据库 |

## 开发

```bash
# 测试
python -m unittest discover backend

# 分层检查（防止下层反向依赖上层）
python scripts/check_layers.py

# 清理日志
python scripts/cleanup_artifacts.py
```

## 上传与索引行为

用户在个人聊天窗口直接发送 PDF 即可入知识库，流程是固化的 HTTP 端点（`POST /knowledge-base/upload`），**不是 agent 可调用的工具**。入库后 `backend/flow/upload.py` 会根据 `upload_action`（`added` / `replaced` / `unchanged` / `duplicate_content`）决定是否触发后台索引重建：

- `added` / `replaced` → 调 `schedule_index_rebuild(file_name)`，唤醒 `IndexRebuildScheduler` 的守护线程重建向量索引；多次快速上传会被合并（coalesce）成至多一次额外重建
- `unchanged` / `duplicate_content` → 不改动 `knowledge_base/*.pdf`，不触发重建

索引重建期间（`_BUILD_LOCK` 被占用），`llamaindex_rag__llamaindex_rag_search` 会 fail-fast 返回结构化错误 `{"error_code":"index_busy","pending_files":[...],"eta_seconds":N}`，agent 按 prompt 的"检索正忙"规则提示用户稍等重试，不改道调其它工具。

## 故障排查

- **文档写入返回 `errcode=0` 但内容为空**：`agent_core.py` 有 docid 自动纠错逻辑，若仍异常检查 `data/logs/flow/flow_runtime.log` 里最近的 `tool_called` 事件看实际写入的 docid
- **RAG 命中页码不合理**：调 `backend/tools/llamaindex_rag/llamaindex/engine.py` 里的 `similarity_top_k` / `reranker_top_k` / `min_relevance_score`
- **知识库上传失败**：确认是 PDF，且在个人聊天（非群聊）中上传
- **agent 越权承诺**（例如承诺"查看表格"）：检查 prompt 的"不支持的能力"段是否被正确应用
- **上传后检索提示"正在建立索引"**：属正常现象，`IndexRebuildScheduler` 在后台重建向量索引，等 `pending_files` 清零后再发一遍问题即可；若长时间不结束看 `data/logs/flow/flow_runtime.log` 里的 `index_rebuild_scheduled` 与 `rag_index_built` 事件

## 项目不足与可优化方向

当前版本仍有若干明确的改进空间，欢迎后续迭代：

- **文件上传类型受限**：目前只接受 PDF，Word / Excel / 图片 / Markdown / txt 等格式无法入库。后续可扩展解析器，覆盖办公场景常见文档类型。
- **检索算法可优化**：目前知识库检索基于 LlamaIndex 的向量检索（embedding + rerank），在长文档、表格型内容、跨文档关联问答上召回和相关性仍有不足。可考虑混合检索（BM25 + 向量）、层级检索、query 改写等方式。
- **工具边界仍可细化**：部分能力（如智能表格改行、文档内容读回展示、文档分段覆盖）尚未支持；工具参数 schema 与 system prompt 的约束也可以进一步收紧，避免模型在边界情况下幻觉。
- **回答结构可迭代**：当前回复格式主要靠 prompt 约束，针对不同场景（结构化总结、长文档摘要、表格输出）仍可通过模板化或结构化输出来提升一致性。
- **观测与调试**：flow / cli 日志齐备，但缺少端到端 trace 视图与自动化评测。

## 其它文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 分层与依赖
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) — MCP 工具清单
- [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md) — 路由规则
- [docs/FLOWS.md](docs/FLOWS.md) — 典型对话流
- [docs/DOC_WRITING.md](docs/DOC_WRITING.md) — 文档写入约定
- [docs/REPLY_STYLE.md](docs/REPLY_STYLE.md) — 回复格式
- [AGENTS.md](AGENTS.md) — 贡献者约定
