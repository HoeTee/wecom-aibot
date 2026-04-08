# wecom-aibot

这是一个面向企业微信文档工作流的 agent 项目。当前主链路是：

1. 接收企业微信消息或 PDF 文件
2. 基于知识库和会话状态理解用户意图
3. 通过 MCP tools 检索材料、创建文档或编辑文档
4. 用 `doc_id`、`doc_url`、`doc_name` 维持文档连续性
5. 通过 HE 层持续检查流程、回归和层级违规

## 当前能力

当前仓库已经支持：

- 企业微信文本消息转发到 backend
- PDF 上传后加入知识库
- 上传 PDF 的去重、同名更新提示
- 基于 `llamaindex_rag` 的知识库检索与总结
- 企业微信文档创建与编辑
- 会话级 memory
  - 最近上传文件
  - 当前绑定文档
  - 最近用户请求
- 最小增量索引
  - 新增 PDF 只增量插入
  - 修改 PDF 只重建该文件
  - 删除 PDF 只删该文件节点
- HE 基础设施
  - `flow_trace`
  - `gate_results`
  - `evaluator`
  - `layer_checks`

## 仓库结构

```text
backend/
  app.py                     # HTTP 入口、主流程编排、上传短路逻辑
  agent.py                   # LLM agent、tool 调用、query rewrite、文档校验
  memory.py                  # session memory、request_id、flow_events 持久化
  mcp_client/                # MCP tools 暴露、路由、连接
  mcp_server_local/
    llamaindex_rag/          # 本地 RAG 实现

docs/
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

evals/
  gates/
    global.yaml              # 共享 hard gates
  scenarios/                 # 场景定义
  runs/                      # 单次运行导出产物
  reports/                   # 汇总报告与 maintenance 输出

knowledge_base/
  papers/                    # 固定知识库 PDF
  papers/uploads/            # 用户上传 PDF 的落盘位置

prompts/
  system/
    assistant_v1.md          # 当前 system prompt

scripts/
  mcp_test.py                # MCP 连通性测试
  run_eval_case.py           # 导出 run artifacts + gates + evaluator
  check_layers.py            # 层级违规检查

gateway/
  long_connection.ts         # 企业微信长连接网关
```

## 分层设计

当前代码按下面几层来理解：

1. Entry / Transport
   - `gateway/long_connection.ts`
   - `backend/app.py` 的 HTTP 入口
2. Orchestration
   - `backend/app.py`
   - `backend/agent.py`
3. Policy / State
   - `backend/memory.py`
4. Adapter / Tool Runtime
   - `backend/mcp_client/*`
5. Tool Implementation
   - `backend/mcp_server_local/llamaindex_rag/*`
6. HE / Eval
   - `evals/*`
   - `scripts/run_eval_case.py`
   - `scripts/check_layers.py`

关键约束：

- Orchestration 不能直接依赖 Tool Implementation
- Tool Implementation 不能反向依赖 Orchestration
- 生产代码不能依赖 `evals/*`
- HE 层是外部迭代工具层，必须可拆卸

## Source of Record

以下文件是当前行为和架构的知识基线：

- [docs/PRODUCT.md](docs/PRODUCT.md)
- [docs/DOC_WRITING.md](docs/DOC_WRITING.md)
- [docs/REPLY_STYLE.md](docs/REPLY_STYLE.md)
- [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md)
- [docs/MEMORY.md](docs/MEMORY.md)
- [docs/EVALS.md](docs/EVALS.md)
- [docs/ROUTING_RULES.md](docs/ROUTING_RULES.md)
- [docs/FLOWS.md](docs/FLOWS.md)
- [docs/CHECKS.md](docs/CHECKS.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [evals/gates/global.yaml](evals/gates/global.yaml)

如果代码行为和这些文档不一致，应优先修代码或更新文档，不要让两边长期漂移。

## 环境要求

- Python 3.11+
- Node.js 20+

## 安装

Python 依赖：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Node.js 依赖：

```powershell
npm install
```

## 配置

先复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

至少需要配置：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `WECOM_BOT_ID`
- `WECOM_BOT_SECRET`

可选配置：

- `BACKEND_BASE_URL`
- `MCP_SERVERS_CONFIG`
- `MCP_SERVER_URL`（旧兼容入口）

MCP servers 建议复制：

```powershell
Copy-Item config\mcp_servers.example.json config\mcp_servers.json
```

然后只在本地填写 `config/mcp_servers.json`。这个文件不应提交。

## 启动

终端 1：

```powershell
.venv\Scripts\python.exe -m backend.app
```

终端 2：

```powershell
npm run gateway
```

健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:5000/health
```

## 主流程说明

### 1. 文本消息

- 由 `gateway` 转发到 `backend /chat`
- `backend/app.py` 负责：
  - 生成 `request_id`
  - 选路
  - 读取 `memory_context`
  - 记录 `flow_events`
  - 调起 `Agent`

### 2. PDF 上传

- `gateway` 把 PDF 发到 `POST /knowledge-base/upload`
- backend 会：
  - 校验 PDF
  - 写入 `knowledge_base/papers/uploads/`
  - 判断是否重复内容或同名更新
  - 保存结构化上传状态
  - 记录 upload flow trace

### 3. 文档连续性

当 tool 返回了文档相关结果时，系统会尝试提取并持久化：

- `doc_id`
- `doc_url`
- `doc_name`

之后用户说“刚才那个文档”“继续改”这类 follow-up 时，系统优先复用当前绑定文档。

## knowledge base

当前知识库由两部分组成：

- 固定 PDF：`knowledge_base/papers/`
- 用户上传 PDF：`knowledge_base/papers/uploads/`

索引行为：

- 未变化时直接复用持久化索引
- 新增 PDF：增量插入
- 修改 PDF：只重建该文件
- 删除 PDF：只删除该文件相关节点

## HE / Evals

当前 HE 层围绕三类对象工作：

1. 场景
2. 运行证据
3. 自动检查

### 场景定义

场景在：

```text
evals/scenarios/*
```

当前已覆盖的代表性场景包括：

- 三篇论文生成综述文档
- 后续补 comparison table
- 引用上一个文档继续编辑
- 上传 PDF 后加入知识库确认
- 同内容重复上传提示
- 同名不同内容上传更新提示

### 单次运行产物

执行：

```powershell
.venv\Scripts\python.exe scripts\run_eval_case.py --scenario-id <scenario_id> --session-id <session_id>
```

会导出：

```text
evals/runs/<run_id>/<scenario_id>/
  metadata.json
  user_request.txt
  assistant_reply.txt
  flow_trace.json
  tool_trace.json
  rag_query.json
  doc_binding.json
  uploaded_file.json
  written_doc_content.md
  gate_results.json
  evaluator.json
```

同时还会产出：

```text
evals/runs/<run_id>/layer_checks.json
evals/reports/<run_id>.md
evals/reports/<run_id>.json
```

### flow_trace

`flow_trace.json` 现在是单次运行的核心证据之一。

默认会记录：

- `route_selected`
- `route_reason`
- `selected_target`
- `guard_hit`
- `tool_called`
- `clarify_needed`
- `stop_reason`

每条 event 都带：

- `timestamp`
- `layer_at_event`

### evaluator

`evaluator.json` 默认输出：

- `passed`
- `failed_checks`
- `reasons`
- `suggested_fix_layer`

### layer checks

`scripts/check_layers.py` 当前第一阶段会优先检查：

- 下层反向 import 上层
- production 代码 import `evals/*`
- orchestration 直接 import tool implementation

layer checks 当前策略是 hard fail。

## Maintenance

maintenance 不是后台常驻任务。当前默认方式是：

1. 主链路发生重要修改
2. coding agent 主动建议跑一轮 maintenance
3. 用户同意后再生成 maintenance summary

输出位置：

```text
evals/reports/maintenance/*.md
evals/reports/maintenance/*.json
```

## 常用脚本

MCP 连通性：

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

## 运行产物

以下内容属于运行产物，不应提交：

- `data/`
- `persist/`
- `manifest/`
- `evals/runs/`
- `evals/reports/`

## Git 工作流

推荐工作流：

1. 从 `main` 切功能分支
2. 在功能分支修改
3. 本地验证
4. push
5. 通过 PR 合并回 `main`

推荐合并方式：

- `Squash and merge`

## 当前改造重点

这一轮改造重点是：

- 把文档规则真正落到代码里
- 让 `flow_trace / evaluator / layer checks` 成为真实可运行能力
- 让 README、架构文档、代码结构三者开始对齐
