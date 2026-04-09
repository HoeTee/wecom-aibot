# PLAN

## 目标

这轮计划的目标不是继续往现有 `flow` 里堆更多流程分支，而是把仓库从“按流程写逻辑”逐步改成“按动作组织能力、按原则约束动作、按 HE 验证动作和流程”。

这轮改造的 north star 是：

`让 agent 主要负责路由和结构化意图判断，让动作成为稳定接口，让 flow 只负责编排，让 HE 先测动作契约再测流程。`

## 背景判断

当前仓库已经完成了三件重要事情：

1. 运行时层级已经明确：
   - `entry`
   - `flow`
   - `policy`
   - `state`
   - `caps`
   - `runtime`
   - `tools`
2. `he/` 已经从运行时层中独立出来。
3. 多个真实用户问题已经沉淀成了规则文档和回归场景。

但当前仓库仍有一个核心问题：

- 运行时逻辑依然偏“按流程组织”
- 很多业务能力还没有先收敛成稳定动作
- HE 仍然主要围着高层场景做回归

这会导致：

- 新需求一来，容易继续往 `flow` 堆 if/else
- 同一动作在多个流程里重复实现
- HE 很难先测动作，只能围绕场景补洞

## 基本原则

这轮改造遵守以下原则：

1. 文档层是上位约束，不是说明书
   - `README.md`
   - `AGENTS.md`
   - `docs/*.md`
   共同构成 Source of Record

2. 运行时代码只负责实现这些原则

3. HE 是外部验证层
   - 不参与生产依赖
   - 只负责检查和回归

4. agent 负责路由，不负责自由决定所有副作用流程

5. policy 和 state 必须形成硬约束
   - 不能只写进提示词
   - 必须落进代码

6. 先动作化，再流程化，再场景化

7. 保持稳定入口文件名不变
   - `backend/app.py`
   - `backend/agent.py`
   - `backend/memory.py`
   - `scripts/run_eval_case.py`
   - `scripts/check_layers.py`
   - `scripts/mcp_test.py`
   - `gateway/long_connection.ts`

## 总体结构

### 原则层

```text
README.md
AGENTS.md
docs/
```

职责：

- 定义目标
- 定义边界
- 定义路由规则
- 定义流程原则
- 定义检查方式
- 定义 HE 工作方式

### 运行时层

```text
backend/
  entry/
  flow/
  policy/
  state/
  caps/
  runtime/
  tools/
```

一句话关系：

```text
entry receives
flow orchestrates
policy governs
state provides
caps define
runtime dispatches
tools execute
```

### HE 层

```text
he/
  docs/
  gates/
  scenarios/
  runs/
  reports/
```

职责：

- 固定规则
- 固定场景
- 导出证据
- 自动检查
- 汇总报告

## 目标形态：动作化架构

### 当前问题

当前更像：

```text
route -> 一段流程代码
```

目标改成：

```text
route -> 一个动作或动作集合
flow -> 组合动作
```

### 动作集合

第一批需要成为稳定动作的能力：

#### knowledge base

- `kb.list`
- `kb.list_uploads`
- `kb.export`
- `kb.rename`
- `kb.delete`
- `kb.match_related`

#### documents

- `doc.read`
- `doc.write`
- `doc.append`
- `doc.replace`
- `doc.expand`

#### RAG

- `rag.search`
- `rag.summarize`

### agent 的职责

agent 的职责收敛成两件事：

1. 识别意图
2. 输出结构化动作计划

目标输出形态类似：

```json
{
  "intent": "kb.rename",
  "target": "linux-part1.pdf",
  "params": {
    "new_name": "linux-renamed.pdf"
  },
  "confidence": 0.86,
  "need_confirm": true,
  "missing": []
}
```

### self-check hook

在 agent 给出动作计划后，强制加一层 self-check hook。

这层不是最终裁决，但必须存在。

默认检查：

- 对象是否明确
- 参数是否齐全
- 是否需要确认
- 动作顺序是否合理
- 是否有明显幻觉

### policy 的职责

policy 负责把规则落成代码约束。

例如：

- 改名只允许 uploads
- 删除必须确认
- 缺对象不能执行
- 缺参数不能执行
- 高风险动作必须先澄清或确认

### state 的职责

state 提供事实，不决定流程。

重点事实：

- 当前绑定文档
- 最近上传文件
- 当前候选对象
- 最近一次 route
- flow event

### flow 的职责

flow 不再拥有大量业务细节。

flow 只做：

- 组合动作
- 决定动作顺序
- 决定何时停止

flow 决定顺序时遵守这些原则：

1. 先确认对象，再执行动作
2. 先做无副作用动作，再做有副作用动作
3. 缺信息时先澄清
4. 信息充分时直接执行

### caps 的职责

caps 定义稳定动作边界。

它回答的是：

- 系统到底支持哪些动作
- 每个动作需要什么输入
- 每个动作返回什么输出

### runtime 的职责

runtime 负责把动作调度到执行层。

当前目标是：

- 对 agent 仍可保留 MCP 边界
- 在本地实现侧逐步统一到 CLI 风格

也就是：

```text
agent
-> flow
-> caps
-> runtime
-> CLI / MCP
-> tools
```

### tools 的职责

tools 负责真正执行动作。

它不应该决定：

- 用户意图
- 高层流程
- 是否需要确认

## CLI 化策略

### 为什么做 CLI

CLI 化的目的不是为了“看起来高级”，而是为了解决：

- 能力边界不稳定
- 输入输出不统一
- 测试难
- 排错难
- HE 难先测动作契约

### CLI 的定位

CLI 是稳定动作接口，不是开放 shell。

CLI 的要求：

- 参数化输入
- JSON 输出
- 明确返回码
- 非交互式
- 副作用明确

### 目标命令形态

```text
kb list --scope all --json
kb list --scope uploads --json
kb export --file xxx.pdf --json
kb rename --file old.pdf --to new.pdf --json
kb delete --file old.pdf --confirm --json

doc read --doc-id xxx --json
doc write --doc-id xxx --input payload.json --json
doc append --doc-id xxx --input payload.json --json
doc replace --doc-id xxx --input payload.json --json
doc expand --doc-id xxx --input payload.json --json

rag search --query "..." --json
rag summarize --query "..." --json
```

### CLI 目录落点

目标目录：

```text
backend/tools/
  kb_cli.py
  doc_cli.py
  rag_cli.py

backend/runtime/
  cli.py
  mcp.py
  logs.py
```

## HE 改造方向

### 当前问题

当前 HE 已经能做：

- `flow_trace`
- `layer_checks`
- stdio MCP preflight
- 部分场景 evaluator

但仍然偏场景回归。

### 目标

让 HE 分三层：

1. contract check
2. flow check
3. scenario check

### 1. contract check

先测动作契约，而不是先测整条用户流程。

例如：

- `kb.list` 输出是否是正确 JSON
- `kb.rename` 是否在 uploads 上生效、在 base 上拒绝
- `doc.append` 是否需要明确对象和位置

目标目录：

```text
he/contracts/
```

### 2. flow check

测 flow 是否按原则组合动作。

重点检查：

- route 是否正确
- self-check hook 是否执行
- 是否在需要时先确认
- 是否按无副作用 -> 有副作用顺序执行

目标目录：

```text
he/flows/
```

### 3. scenario check

保留少量端到端场景，作为最终用户体验验证。

保留原则：

- 代表性强
- 可重复
- 覆盖真实失败模式

### HE 的目的

HE 的目的不是“堆更多场景”，而是：

- 先证明动作可靠
- 再证明 flow 没漂
- 最后证明真实体验没回归

## 日志改造

### 当前问题

当前日志已有：

- `mcp_client.log`
- 某些本地 MCP stderr 日志
- `flow_events`

但仍然缺少：

- 动作级日志
- CLI 执行日志
- 明确的 route / action / target 维度

### 目标目录

```text
data/logs/
  app/
  flow/
  cli/
  mcp/
  he/
```

### 统一日志字段

每次关键动作至少记录：

- `request_id`
- `session_id`
- `route`
- `action`
- `target`
- `params_summary`
- `result_status`
- `stop_reason`

### flow 日志

记录：

- `route_selected`
- `route_reason`
- `self_check_result`
- `clarify_needed`
- `stop_reason`

### CLI 日志

记录：

- `command`
- `args`
- `exit_code`
- `stdout_path`
- `stderr_path`

### MCP 日志

记录：

- `server_name`
- `transport`
- `initialize_status`
- `child_stderr_path`

### HE 日志

记录：

- contract 结果
- flow 检查结果
- scenario 结果
- suggested fix layer

## 代码迁移计划

### Phase 1：把 knowledge base 动作做实

目标：

- 让 KB 相关能力先完全动作化

包括：

- `kb.list`
- `kb.list_uploads`
- `kb.export`
- `kb.rename`
- `kb.delete`
- `kb.match_related`

产物：

- `caps` 收口
- `runtime` 可调
- `tools` 具备 CLI 风格入口
- HE 增加 KB contract checks

### Phase 2：把 document 动作做实

目标：

- 让文档操作从“流程逻辑”变成“动作能力”

包括：

- `doc.read`
- `doc.write`
- `doc.append`
- `doc.replace`
- `doc.expand`

产物：

- 文档高级编辑流程不再主要写死在 `flow`
- HE 可直接测试文档动作契约

### Phase 3：改造 agent + flow

目标：

- agent 主要负责结构化意图识别
- flow 主要负责动作顺序

包括：

- route 产出结构化计划
- 强制 self-check hook
- policy/state 校验
- flow 执行计划

### Phase 4：改造 HE

目标：

- 从“主要测场景”升级为“先测动作、再测 flow、最后测场景”

包括：

- `he/contracts`
- `he/flows`
- 更新 `scripts/run_eval_case.py`

### Phase 5：日志与清理

目标：

- 问题可定位
- 测试后可清理

包括：

- 日志目录重构
- 动作级日志
- 提供测试产物清理脚本或固定清理入口

## 文档同步范围

这轮及后续所有结构改造，都必须同步更新这些文档：

- `README.md`
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/MCP_TOOLS.md`
- `docs/MEMORY.md`
- `docs/ROUTING_RULES.md`
- `docs/FLOWS.md`
- `docs/CHECKS.md`
- `docs/EVALS.md`

要求：

1. 目录结构、层级命名和文档描述一致
2. 动作清单和代码能力一致
3. HE 检查项和真实实现一致

## 验证方式

每轮改动后至少跑：

1. `py_compile`
2. `scripts/check_layers.py`
3. 相关 contract check
4. 相关 flow check
5. 必要的 scenario check

required stdio MCP server 还必须通过：

- preflight initialize check

## 清理策略

项目修改完成后，应清理：

- `he/runs/*`
- `he/reports/*`
- `data/logs/*`
- 测试临时上传文件
- 测试临时索引或中间文件
- 已废弃的旧兼容目录

保留：

- 稳定代码
- 稳定文档
- 固定知识库材料
- 必要配置模板

运行产物不应进入提交：

- `data/`
- `he/runs/`
- `he/reports/`
- `knowledge_base/papers/uploads/`

## 风险与注意点

1. 不要把 CLI 做成开放 shell
2. 不要让 agent 直接自由执行副作用动作
3. 不要把 policy 只写进 prompt，不落代码
4. 不要把 HE 继续主要做成场景补丁系统
5. 不要在重构时破坏稳定入口文件名

## 成功标准

当以下条件成立时，这轮改造算成功：

1. `flow` 明显变薄
2. 核心能力已动作化
3. KB 和文档动作可独立测试
4. HE 已能先测 contract，再测 flow
5. agent 主要负责路由和结构化意图，而不是自由拍板副作用流程
6. 文档、代码、HE 三层一致

## 时间预估

如果按最小可用版推进：

- KB 动作 CLI 化 + flow 改造：`4-6 小时`
- 文档动作 CLI 化 + flow 改造：`4-6 小时`
- HE contract / flow 改造：`4-8 小时`
- 日志和清理收尾：`2-4 小时`

完整做完一轮，预计：

`1 到 2 天`

## 当前优先级

当前优先级固定为：

1. `kb.*` 动作彻底收口
2. `doc.*` 动作彻底收口
3. agent 结构化意图 + self-check hook
4. HE contract / flow checks
5. 日志与清理
