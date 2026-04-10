# wecom-aibot

面向企业微信文档工作流的 agent。

它做三件事：

1. 接收用户消息或文件
2. 查询知识库、RAG 和文档能力
3. 创建或编辑企业微信文档，并用 `he/` 做回归验证

## 架构

这不是目录图，而是运行链路。

```text
原则层
  README.md / AGENTS.md / docs/*.md
    └─ 定义规则、边界、流程和检查项

运行时层
  用户输入
    ↓
  gateway
    ↓
  entry      receives
    ↓
  flow       orchestrates
    ├─ 读 policy 规则
    ├─ 读 state 事实
    └─ 选择 caps 动作
           ↓
        runtime   dispatches
           ↓
        tools     execute
           ↓
        企业微信 / 本地知识库 / RAG

验证层
  he
    └─ evaluates
```

运行时层级和模块关系：

```text
entry
  负责接收输入和返回输出

flow
  负责编排动作顺序，不直接持有大量业务细节

policy
  负责规则和边界，例如是否必须确认、哪些动作禁止直接执行

state
  负责会话事实，例如当前文档绑定、最近上传文件、flow trace

caps
  定义动作边界，例如：
  - kb.list
  - kb.rename
  - doc.read
  - doc.write
  - rag.search

runtime
  负责把动作分发到 MCP 或 CLI

tools
  负责真正执行

he
  负责 contract / flow / scenario 检查
```

当前能力来源：

```text
kb.*
  主要是本地知识库文件动作
  由 runtime 分发到本地 tools 执行

doc.*
  主要通过企业微信文档 MCP 调用

smartsheet.*
  主要通过企业微信智能表格 MCP 调用

rag.*
  当前通过本地 RAG MCP 调用
```

也就是说：

```text
agent / flow 不直接碰底层实现
而是先选动作，再由 runtime 决定这个动作最终走 MCP 还是本地 tools
```

## 仓库结构

```text
wecom-aibot/
  README.md
  AGENTS.md

  docs/            # 原则层
  backend/         # 运行时层
  he/              # 独立 HE 层

  gateway/
  knowledge_base/
  prompts/
  scripts/
  config/
  data/
```

知识库约定：

- 所有知识库 PDF 直接放在 `knowledge_base/` 根目录
- 不再使用 `papers/`、`uploads/` 子目录
- 上传文件通过文件名前缀 `upload__` 区分

## 快速启动

环境要求：

- Python 3.11+
- Node.js 20+

Windows:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
Copy-Item .env.example .env
Copy-Item config\mcp_servers.example.json config\mcp_servers.json
.venv\Scripts\python.exe -m backend.app
npm run gateway
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm install
cp .env.example .env
cp config/mcp_servers.example.json config/mcp_servers.json
.venv/bin/python -m backend.app
npm run gateway
```

健康检查：

Windows:

```powershell
Invoke-WebRequest http://127.0.0.1:5000/health
```

macOS / Linux:

```bash
curl http://127.0.0.1:5000/health
```

## 详细文档

更细的内容不要放在 README，去这里看：

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md)
- [docs/FLOWS.md](docs/FLOWS.md)
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)
- [docs/CHECKS.md](docs/CHECKS.md)
- [docs/EVALS.md](docs/EVALS.md)
- [docs/MEMORY.md](docs/MEMORY.md)
- [he/README.md](he/README.md)
