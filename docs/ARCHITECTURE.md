# 架构

## 目的

这份文档定义仓库的运行时层级，以及独立的 HE 层。

目标不是为了追求形式上的“好看”，而是为了：

- 让职责边界清楚
- 让 hook 和 evaluator 有稳定落点
- 让层级检查有真实目录可查
- 让后续重构和回归有明确参照

## 两套结构

这个仓库同时存在两套结构：

1. 运行时层级
2. 独立的 HE 层

两者不是同一套东西。

### 运行时层级

运行时按这七层理解：

- `entry`
- `flow`
- `policy`
- `state`
- `caps`
- `runtime`
- `tools`

### 独立 HE 层

`he` 不属于运行时七层。  
它是外部验证和回归层。

## 一句话关系

- `entry receives`
- `flow orchestrates`
- `policy governs`
- `state provides`
- `caps define`
- `runtime dispatches`
- `tools execute`
- `he evaluates`

## 各层职责

### 1. `entry`

职责：

- 接收输入
- 传递输入
- 返回输出

当前对应：

- `backend/app.py`
- `backend/entry/*`
- `gateway/long_connection.ts`

这一层不负责真正业务判断。

### 2. `flow`

职责：

- 决定下一步走哪条流程
- 决定是否 short-circuit
- 决定是否先澄清
- 决定调用哪些能力

当前对应：

- `backend/agent.py`
- `backend/flow/*`

这一层负责编排，不负责真正干活。

### 3. `policy`

职责：

- 定义业务规则

例如：

- 什么叫“重新生成”
- 什么情况下必须确认
- 什么情况下不能复用旧文档
- 什么情况下要先澄清

当前对应：

- `backend/policy/*`

### 4. `state`

职责：

- 提供当前会话事实
- 维护持久状态

例如：

- 当前绑定的 `doc_id` / `doc_url` / `doc_name`
- 最近上传文件状态
- request / flow event 的持久记录

当前对应：

- `backend/memory.py`
- `backend/state/*`

### 5. `caps`

职责：

- 定义对上层稳定可用的业务能力边界

例如：

- 知识库入库
- 知识库枚举
- RAG 查询
- 文档创建
- 文档编辑

当前对应：

- `backend/caps/*`

注意：

- `caps` 定义能力
- 但对 agent 可见的统一接口仍然通过 MCP 暴露

### 6. `runtime`

职责：

- 连接 MCP
- 暴露 MCP tools
- 路由和转发调用
- 统一参数和结果传递

当前对应：

- `backend/runtime/*`

兼容包装仍保留在：

- `backend/mcp_client/*`

这些旧路径现在主要用于兼容历史 import，不是新的主编辑位置。

### 7. `tools`

职责：

- 真正执行能力

例如：

- 本地 `llamaindex_rag`
- 企微文档相关 tool 实现
- 未来的知识库文件管理 tool 实现

当前对应：

- `backend/tools/*`

兼容包装仍保留在：

- `backend/mcp_server_local/*`

这些旧路径现在主要用于兼容旧 MCP 启动路径。

`tools` 层里的 stdio wrapper 还必须满足一条额外约束：

- 不能只做 import 转发
- 必须在 `__main__` 中显式启动 `run(...)`

### 8. `he`

职责：

- 定义场景
- 定义 gates
- 收集运行证据
- 输出报告
- 做层级检查和回归判断

当前对应：

- `he/gates/*`
- `he/scenarios/*`
- `he/runs/*`
- `he/reports/*`
- `scripts/run_eval_case.py`
- `scripts/check_layers.py`

## 仓库目录映射

```text
backend/
  entry/
  flow/
  policy/
  state/
  caps/
  runtime/
  tools/

he/
  gates/
  scenarios/
  runs/
  reports/
```

## 层级约束

### 1. `flow` 不能直接依赖 `tools`

`flow` 必须通过：

- `caps`
- `runtime`

去使用底层能力，不能直接 import `tools`。

### 2. `tools` 不能反向依赖 `flow`

下层不能反向依赖上层。  
尤其 `tools` 不能 import `backend/agent.py` 或 `backend/flow/*` 来决定流程。

### 3. 生产代码不能依赖 `he`

生产代码不能 import：

- `he/*`

`he` 是外部验证层，不是生产运行依赖。

### 4. `policy` 和 `state` 不决定完整流程

它们可以提供：

- 规则
- 会话事实

但完整流程仍由 `flow` 决定。

### 5. hook 属于可观测性输出，不替代流程决策

hook 负责：

- 记录 route
- 记录 state
- 记录 tool 调用
- 记录输出

hook 不负责：

- 取代 `flow`
- 取代 `policy`
- 取代 evaluator

## HE 为什么需要分层

HE 不是只看最终回复。  
HE 还要看层与层之间有没有断链。

例如：

- `entry -> flow`
  - 有没有分流正确
- `flow -> policy/state`
  - 有没有读对规则和会话事实
- `flow -> runtime`
  - 有没有选对能力和 tool
- `runtime -> tools`
  - 有没有正确转发到实现层
- `runtime -> tools`
  - required stdio MCP server 能不能先完成 initialize

所以分层不是为了抽象本身，而是为了让错误能被定位和验证。

## 运行产物位置

运行时产物统一收在 `data/` 下：

- `data/memory.sqlite3`
- `data/index/manifest.json`
- `data/index/persist/*`
- `data/logs/mcp/mcp_client.log`

`manifest/`、`persist/`、`logs/` 不再作为根目录一级目录参与结构表达。

`he/runs/` 和 `he/reports/` 也属于可清理的运行产物，不属于稳定代码结构。
