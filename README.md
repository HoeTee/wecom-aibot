# wecom-aibot

这是一个面向企业微信文档工作流的 agent 项目。主链路是：

1. 接收用户消息或文件
2. 判断正确流程
3. 查询知识库或调用文档能力
4. 创建或编辑企业微信文档
5. 通过独立的 HE 层做回归、检查和报告

## 架构

```text
原则层
  README.md
  AGENTS.md
  docs/*.md
    └─ 定义规则、边界和 Source of Record

运行时层
  backend/
    entry/    receives
    flow/     orchestrates
    policy/   governs
    state/    provides
    caps/     defines actions
    runtime/  dispatches
    tools/    executes

验证层
  he/
    └─ evaluates
```

```text
用户输入
  ↓
gateway/
  ↓
backend/entry
  ↓
backend/flow
  ├─ 读取 policy 规则
  ├─ 读取 state 事实
  └─ 选择 caps 动作
        ↓
     backend/runtime
        ↓
     backend/tools
        ↓
     外部系统 / 本地执行

he/
  └─ 检查整个过程和结果
```

```text
wecom-aibot/
  README.md
  AGENTS.md
  docs/                     # 原则层
  backend/                  # 运行时层
    app.py
    agent.py
    memory.py
    entry/
    flow/
    policy/
    state/
    caps/
    runtime/
    tools/
  he/                       # 独立 HE 层
  gateway/
  knowledge_base/
  prompts/
  scripts/
  config/
  data/
```

知识库目录约定：

- 所有知识库 PDF 直接放在 `knowledge_base/` 根目录
- 固定材料和上传材料不再分子目录
- 上传文件只通过文件名前缀 `upload__` 区分

## data 目录

运行产物统一收在 `data/` 下：

```text
data/
  memory.sqlite3            # 会话状态
  index/
    manifest.json           # 索引 manifest
    persist/                # 向量索引持久化
  logs/
    mcp/
      mcp_client.log        # MCP 客户端日志
      llamaindex_rag_stderr.log  # 本地 llamaindex_rag stdio 子进程 stderr
```

`manifest/`、`persist/`、`logs/` 不再作为根目录一级结构存在。

## HE 目录

HE 独立于运行时层，不属于 `backend/` 的七层。

```text
he/
  README.md
  review_template.md
  contracts/
  flows/
  gates/
  scenarios/
  runs/
  reports/
```

- `gates/`：共享 hard gates
- `contracts/`：动作级 contract checks
- `flows/`：flow checks
- `scenarios/`：固定回归场景
- `runs/`：单次运行证据包
- `reports/`：总结报告和 maintenance 输出

## 当前能力

当前已经落地的主能力分三类：

- 知识库：上传、去重、列表、相关候选、改名、导出、删除前确认
- 文档：创建、读取、覆盖、追加、替换、扩写，以及 `doc_id/doc_url/doc_name` 连续性维护
- HE：`flow_trace`、`run_eval_case`、`check_layers`、required stdio MCP boot preflight

## Source of Record

关键规则文档：

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md)
- [docs/FLOWS.md](docs/FLOWS.md)
- [docs/CHECKS.md](docs/CHECKS.md)
- [docs/EVALS.md](docs/EVALS.md)
- [docs/MEMORY.md](docs/MEMORY.md)
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)
- [he/gates/global.yaml](he/gates/global.yaml)

## 启动

环境要求：

- Python 3.11+
- Node.js 20+

安装依赖：

Windows:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm install
```

准备配置：

Windows:

```powershell
Copy-Item .env.example .env
Copy-Item config\mcp_servers.example.json config\mcp_servers.json
```

macOS / Linux:

```bash
cp .env.example .env
cp config/mcp_servers.example.json config/mcp_servers.json
```

启动 backend：

Windows:

```powershell
.venv\Scripts\python.exe -m backend.app
```

macOS / Linux:

```bash
.venv/bin/python -m backend.app
```

启动 gateway：

Windows / macOS / Linux:

```bash
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

## 常用脚本

单场景评测：

```powershell
.venv\Scripts\python.exe scripts\run_eval_case.py --scenario-id <scenario_id> --session-id <session_id>
```

层级检查：

```powershell
.venv\Scripts\python.exe scripts\check_layers.py
```

required stdio MCP 预检查：

- `scripts/run_eval_case.py` 会在场景 gates 之前先检查所有 `required: true` 的 stdio MCP server 是否能完成 initialize
- 如果失败，先看 `data/logs/mcp/<server_name>_stderr.log`

MCP 连通性检查：

```powershell
.venv\Scripts\python.exe -m scripts.mcp_test
```

清理测试产物：

```powershell
.venv\Scripts\python.exe scripts\cleanup_artifacts.py
```

## CLI 动作层

当前动作层已经覆盖：

- `kb.*`
- `doc.*`
- `rag.*`

主要入口：

- `backend/runtime/cli.py`
- `backend/tools/kb_cli.py`
- `backend/tools/doc_cli.py`
- `backend/tools/rag_cli.py`

当前 `agent` 侧新增了：

- `agent_plan_created`
- `agent_self_check`

## 本地环境目录

`.venv/` 和 `node_modules/` 是本地依赖缓存，不属于逻辑结构的一部分，也不应该作为项目分层来理解。

## 不应提交的内容

- `data/`
- `he/runs/`
- `he/reports/`
- `knowledge_base/upload__*.pdf`

## Git 工作流

推荐流程：

1. 从 `main` 切功能分支
2. 在功能分支修改
3. 本地验证
4. push
5. 通过 PR 合回 `main`

推荐合并方式：

- `Squash and merge`
