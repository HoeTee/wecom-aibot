# wecom-aibot

这是一个面向企业微信文档工作流的 agent 项目。主链路是：

1. 接收用户消息或文件
2. 判断正确流程
3. 查询知识库或调用文档能力
4. 创建或编辑企业微信文档
5. 通过独立的 HE 层做回归、检查和报告

## 分层关系

- `entry receives`
- `flow orchestrates`
- `policy governs`
- `state provides`
- `caps define`
- `runtime dispatches`
- `tools execute`
- `he evaluates`

这组关系不是口号，而是目录约束。

## 逻辑结构

```text
wecom-aibot/
  README.md
  AGENTS.md

  backend/                  # 生产代码
    app.py                  # 稳定 Flask 入口 facade
    agent.py                # 稳定 agent facade
    memory.py               # 稳定 memory facade
    entry/                  # entry
    flow/                   # flow
    policy/                 # policy
    state/                  # state
    caps/                   # caps
    runtime/                # runtime
    tools/                  # tools

  gateway/
    long_connection.ts      # 企业微信网关入口

  docs/                     # 规则和架构文档
  he/                       # 独立 HE 层
  knowledge_base/           # 固定知识库材料
  prompts/                  # prompt 文件
  scripts/                  # 稳定脚本入口
  config/                   # 本地配置模板
  data/                     # 本地状态、索引、日志
```

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
  gates/
  scenarios/
  runs/
  reports/
```

- `gates/`：共享 hard gates
- `scenarios/`：固定回归场景
- `runs/`：单次运行证据包
- `reports/`：总结报告和 maintenance 输出

## 当前能力

当前已经落地的主能力包括：

- PDF 上传后入知识库
- 重复上传和同名更新提示
- 知识库文件列表查询
- 相关文档候选查询
- 原 PDF 导出前澄清与原文件返回
- 删除知识库文件前确认
- 本地 RAG 检索与总结
- 企业微信文档创建与编辑
- 把知识库内容并入当前文档
- 用知识库内容替换当前文档相关部分
- 把知识库内容扩写成当前文档的一节
- `doc_id` / `doc_url` / `doc_name` 连续性维护
- `flow_trace`
- `run_eval_case`
- `check_layers`
- required stdio MCP boot preflight

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

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
```

准备配置：

```powershell
Copy-Item .env.example .env
Copy-Item config\mcp_servers.example.json config\mcp_servers.json
```

启动 backend：

```powershell
.venv\Scripts\python.exe -m backend.app
```

启动 gateway：

```powershell
npm run gateway
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:5000/health
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

## 兼容层

以下目录目前保留为兼容包装：

- `backend/mcp_client/`
- `backend/mcp_server_local/`

新代码优先落到：

- `backend/runtime/`
- `backend/tools/`

## 本地环境目录

`.venv/` 和 `node_modules/` 是本地依赖缓存，不属于逻辑结构的一部分，也不应该作为项目分层来理解。

## 不应提交的内容

- `data/`
- `he/runs/`
- `he/reports/`
- `knowledge_base/papers/uploads/`

## Git 工作流

推荐流程：

1. 从 `main` 切功能分支
2. 在功能分支修改
3. 本地验证
4. push
5. 通过 PR 合回 `main`

推荐合并方式：

- `Squash and merge`
