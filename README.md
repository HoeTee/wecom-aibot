# wecom-aibot

企业微信文档工作流 agent。用户在企微聊天里发消息或上传 PDF，bot 负责总结、整理、写入企微文档或智能表格。

> ⚠️ **推荐在个人聊天窗口（单聊）使用**。群聊场景下意图识别易被多人插话污染、文档绑定也会串会话，不推荐。

## 能做什么

- **知识库**：上传 PDF 进本地向量库，做 RAG 问答与检索
- **文档**：创建企微文档壳，把总结/整理内容写入正文，追加/替换章节
- **智能表格**：创建表格，追加记录，读写列结构

## 能力边界

| 能做 | 不能做 |
|------|--------|
| 上传 PDF 入知识库（仅个人聊天） | 群聊内上传文件 |
| 创建文档 + 写入正文 | 把文档内容展示给用户看 |
| 追加表格记录、改列结构 | 查看/读取/浏览表格行内容 |
| 追加表格行 | 修改/删除已有行 |
| 知识库文件列表、重命名、删除、导出 PDF | 修改/删除 PDF 内部内容 |
| 仅 PDF 入知识库 | Word / Excel / 图片 / txt 入知识库 |

能力清单与系统 prompt (`prompts/system/assistant_v1.md`) 保持一致。agent 遇到边界外请求会直接回复"暂不支持"。

## 快速开始

### 前置

- Python 3.11+
- Node.js 20+
- 企业微信管理后台：创建 AI Bot，拿到 `WECOM_BOT_ID` / `WECOM_BOT_SECRET`
- LLM 服务：OpenAI-compatible endpoint（默认用阿里云 DashScope 的 Qwen）

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

编辑 `.env`，至少填：

```env
# LLM（必填）
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

# Embedding / Rerank（本地 RAG 必填）
EMBED_API_KEY=sk-xxx
EMBED_MODEL=text-embedding-v4
RERANK_API_KEY=sk-xxx
RERANK_MODEL=qwen3-rerank

# 企微 AI Bot（长连接网关必填）
WECOM_BOT_ID=xxx
WECOM_BOT_SECRET=xxx
```

编辑 `config/mcp_servers.json`，把企微文档 MCP 的 `url` 换成你自己带 apikey 的地址。

### 启动

两个进程同时跑：

```bash
# 1) 后端（Flask，监听 127.0.0.1:5000）
python -m backend.app

# 2) 企微长连接网关
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
   ↓ HTTP POST /chat
backend/entry/http.py           Flask 入口
   ↓
backend/flow/                   agent 主循环 + chat 编排
   ├─ policy/                   业务规则、意图识别、能力边界
   ├─ state/                    SQLite 会话（对话历史、文档绑定、上传文件）
   ├─ caps/                     能力封装层
   └─ runtime/                  工具分发（MCP 或本地）
                                   ↓
                                tools/
                                   ├─ doc_cli / kb_cli / rag_cli   MCP wrapper
                                   └─ llamaindex_rag/              本地 RAG
```

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 目录速查

| 目录 | 内容 |
|------|------|
| `backend/flow/` | agent 主循环 (`agent_core.py`) + 消息入口 (`chat.py`) |
| `backend/policy/` | 能力边界、意图识别、上传策略 |
| `backend/state/store.py` | SQLite 持久化（conversation_turns / tool_calls / session_docs / session_uploaded_files） |
| `backend/tools/llamaindex_rag/` | 本地 RAG：PDFReader + 向量检索 + Qwen reranker |
| `backend/tools/*_cli.py` | MCP 工具 wrapper（doc / kb / rag） |
| `config/mcp_servers.json` | 外部 MCP server 配置 |
| `knowledge_base/` | 用户上传的 PDF（不入版本控制） |
| `prompts/system/assistant_v1.md` | 系统 prompt（含能力边界声明） |
| `data/logs/flow/flow_runtime.log` | 结构化 JSON 运行日志 |
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

## 故障排查

- **文档写入返回 `errcode=0` 但内容为空**：`agent_core.py` 有 docid 自动纠错逻辑，若仍异常检查 `data/logs/flow/flow_runtime.log` 里最近的 `tool_called` 事件看实际写入的 docid
- **RAG 命中页码不合理**：调 `backend/tools/llamaindex_rag/llamaindex/engine.py` 里的 `similarity_top_k` / `reranker_top_k` / `min_relevance_score`
- **知识库上传失败**：确认是 PDF，且在个人聊天（非群聊）中上传
- **agent 越权承诺**（例如承诺"查看表格"）：检查 prompt 的"不支持的能力"段是否被正确应用

## 其它文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 分层与依赖
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) — MCP 工具清单
- [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md) — 路由规则
- [docs/FLOWS.md](docs/FLOWS.md) — 典型对话流
- [docs/DOC_WRITING.md](docs/DOC_WRITING.md) — 文档写入约定
- [docs/REPLY_STYLE.md](docs/REPLY_STYLE.md) — 回复格式
- [AGENTS.md](AGENTS.md) — 贡献者约定
