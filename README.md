# wecom-aibot

这是一个面向企业微信文档工作流的 agent 项目。主链路是：

1. 接收用户消息或文件
2. 理解意图并选择正确流程
3. 检索知识库或调用文档能力
4. 创建或编辑企业微信文档
5. 用独立的 HE 层做回归、检查和报告

## 分层关系

当前仓库按这组关系理解：

- `entry receives`
- `flow orchestrates`
- `policy governs`
- `state provides`
- `caps define`
- `runtime dispatches`
- `tools execute`
- `he evaluates`

这几条不是口号，而是目录约束：

- `entry` 只负责接收和返回
- `flow` 只负责流程编排
- `policy` 只负责规则
- `state` 只负责会话事实和持久状态
- `caps` 只负责定义业务能力边界
- `runtime` 只负责 MCP 连接、暴露和转发
- `tools` 只负责真正执行能力
- `he` 是独立外部层，不参与生产运行

## 仓库结构

```text
wecom-aibot/
  README.md
  AGENTS.md

  backend/                     # 生产代码层
    app.py                     # 稳定 Flask 入口 facade
    agent.py                   # 稳定 agent facade
    memory.py                  # 稳定 memory facade

    entry/                     # entry
    flow/                      # flow
    policy/                    # policy
    state/                     # state
    caps/                      # caps
    runtime/                   # runtime
    tools/                     # tools

    mcp_client/                # 兼容包装层，保持旧 import 不断
    mcp_server_local/          # 兼容包装层，保持旧 MCP 入口不变

  gateway/
    long_connection.ts         # 企业微信网关入口

  docs/                        # 规则和架构基线
    PRODUCT.md
    DOC_WRITING.md
    REPLY_STYLE.md
    MCP_TOOLS.md
    MEMORY.md
    EVALS.md
    ROUTING_RULES.md
    FLOWS.md
    CHECKS.md
    ARCHITECTURE.md

  he/                          # Harness Engineering 独立层
    README.md
    review_template.md
    gates/
    scenarios/
    runs/
    reports/

  scripts/                     # 稳定脚本入口
    run_eval_case.py
    check_layers.py
    mcp_test.py

  prompts/
    system/

  knowledge_base/
    papers/
      uploads/

  config/
    mcp_servers.example.json
    mcp_servers.json

  data/
  manifest/
  persist/
```

## Source of Record

规则文档和架构说明在 `docs/`，HE 数据和运行结果在 `he/`。

关键基线文件：

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md)
- [docs/FLOWS.md](docs/FLOWS.md)
- [docs/CHECKS.md](docs/CHECKS.md)
- [docs/EVALS.md](docs/EVALS.md)
- [docs/MEMORY.md](docs/MEMORY.md)
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)
- [he/gates/global.yaml](he/gates/global.yaml)

## 当前能力

当前已经落下来的能力包括：

- 企业微信文本消息接入
- PDF 上传后自动入知识库
- PDF 重复上传和同名更新提示
- 本地 `llamaindex_rag` 检索与总结
- 企业微信文档创建与编辑
- `doc_id` / `doc_url` / `doc_name` 连续性维护
- 单次请求的 `flow_trace`
- `run_eval_case` 导出 run artifacts
- `check_layers` 层级违规检查

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

## HE

HE 层现在明确独立在 `he/` 下。

它负责：

- `gates/`：共享 hard gates
- `scenarios/`：固定回归场景
- `runs/`：单次运行证据包
- `reports/`：汇总报告和 maintenance 输出

单次评测执行入口保持不变：

```powershell
.venv\Scripts\python.exe scripts\run_eval_case.py --scenario-id <scenario_id> --session-id <session_id>
```

层级检查入口保持不变：

```powershell
.venv\Scripts\python.exe scripts\check_layers.py
```

## 常用脚本

MCP 连通性检查：

```powershell
.venv\Scripts\python.exe -m scripts.mcp_test
```

单场景评测：

```powershell
.venv\Scripts\python.exe scripts\run_eval_case.py --scenario-id pdf_3papers_create_summary_doc --session-id dm:14292
```

层级检查：

```powershell
.venv\Scripts\python.exe scripts\check_layers.py
```

## 兼容包装

当前仓库里还保留了两个旧目录：

- `backend/mcp_client/`
- `backend/mcp_server_local/`

它们现在主要用于兼容旧 import 路径和旧 MCP 启动路径。新代码应优先落在：

- `backend/runtime/`
- `backend/tools/`

## 运行产物

以下内容属于运行产物，不应提交：

- `data/`
- `manifest/`
- `persist/`
- `he/runs/`
- `he/reports/`

## Git 工作流

推荐流程：

1. 从 `main` 切功能分支
2. 在功能分支修改
3. 本地验证
4. push
5. 通过 PR 合回 `main`

推荐合并方式：

- `Squash and merge`
