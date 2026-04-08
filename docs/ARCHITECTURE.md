# 架构

## 目的

这份文档定义这个仓库的分层。

目标不是一次把目录完全重构完，而是先把层级边界说清楚，避免不同职责混在一起，影响后续 HE。

## 总体原则

先分层，再在层内模块化。

分层的目的：

- 让职责边界清楚
- 让 hook 和 evaluator 能插在层与层之间
- 让迭代时能知道问题发生在哪一层

新增能力时，先定层，再定文件，再写代码。

## 六层结构

### 第 1 层：Entry / Transport

职责：

- 接收输入
- 传递输入
- 返回输出

例如：

- 接收企微消息
- 区分 text / file
- 调 backend 接口
- 把回复发回企微

这一层不负责真正业务判断。

### 第 2 层：Orchestration

职责：

- 指挥谁去做事
- 决定下一步走哪条流程
- 决定是否先澄清、先 short-circuit、先读 state、还是先调 tool

这一层不亲自执行底层能力。

### 第 3 层：Policy / State

职责：

- 维护业务规则
- 维护当前会话事实

规则例如：

- 什么叫“重新生成”
- 什么情况下必须确认
- 什么情况下不能复用旧文档

状态例如：

- 当前绑定的 `doc_id` / `doc_url` / `doc_name`
- 最近上传文件状态
- 当前会话最近用户请求

这一层可以理解为：

规则 + 当前会话事实

### 第 4 层：Capability

职责：

- 定义对上层稳定可用的业务能力

例如：

- 列知识库文件
- 上传 PDF 到知识库
- 查询知识库
- 创建文档
- 编辑文档

约束：

- 对 agent 可用的业务能力，最终统一通过 MCP tools 暴露
- agent 不直接调用底层本地函数能力

### 第 5 层：Adapter / Tool Runtime

职责：

- 作为 capability 和 agent/orchestration 之间的中介层
- 负责 MCP tools 的连接、暴露、路由、参数传递

例如：

- 发现有哪些 MCP tools 可用
- 给 tool 加统一命名
- 把调用路由到正确的 MCP 服务
- 把参数和结果传回来

这一层不负责决定用户意图，只负责把 tool 接通并转发。

### 第 6 层：Tool Implementation

职责：

- 真正执行能力

例如：

- 本地 `llamaindex_rag`
- 企微文档 MCP 服务
- 未来的知识库文件管理 MCP 服务

这一层负责真正干活，但不负责：

- 判断用户意图
- 决定走哪条流程
- 决定是否澄清

## 当前文件与层级的对应关系

### 第 1 层：Entry / Transport

- `gateway/long_connection.ts`
- `backend/app.py` 中的 HTTP entry

### 第 2 层：Orchestration

- `backend/app.py`
- `backend/agent.py`

### 第 3 层：Policy / State

- `backend/memory.py`
- 后续建议拆出的 `backend/policies/*`

### 第 4 层：Capability

当前还没有完全显式抽出。

后续建议逐步形成：

- `backend/capabilities/knowledge_base.py`
- `backend/capabilities/rag.py`
- `backend/capabilities/documents.py`

### 第 5 层：Adapter / Tool Runtime

- `backend/mcp_client/host.py`
- `backend/mcp_client/connection.py`

### 第 6 层：Tool Implementation

- `backend/mcp_server_local/llamaindex_rag/*`
- 其他 MCP 服务端实现

## 分层与 HE 的关系

HE 不只是看最终结果，也要看层间组合。

例如：

- Entry -> Orchestration
  - 是否分流正确
- Orchestration -> Policy / State
  - 是否读对了当前会话状态
- Orchestration -> Capability / Tool Runtime
  - 是否选对了能力和 tool
- Tool Runtime -> Tool Implementation
  - 是否把调用正确转发

所以，分层不是为了形式，而是为了：

- 更清楚地插 hook
- 更清楚地写 evaluator
- 更清楚地定位回归

## 层级约束

### 1. Orchestration 不能直接依赖 Tool Implementation

Orchestration 层不能直接 import Tool Implementation 层。

它必须通过：

- MCP
- tool runtime
- 统一的能力边界

来调用底层能力。

### 2. Tool Implementation 不能反向依赖 Orchestration

下层不能反向依赖上层。

尤其：

- `llamaindex_rag`
- 具体 MCP tool 实现

不能 import `backend/app.py` 或 `backend/agent.py` 去决定用户流程。

### 3. HE / eval 层不能被生产代码依赖

HE 是外部迭代工具层，不是生产链路的一部分，应保持可拆卸。

也就是：

- `backend/*` 不应 import `evals/*`
- 生产流程不应依赖 `review.json`
- 生产流程不应依赖 `gate_results.json`

### 4. Policy / State 不决定完整流程

Policy / State 层可以提供：

- 规则
- 当前会话事实

但不能自己决定完整业务流程。

完整流程应由 Orchestration 层决定。

### 5. hook 的位置

hook 属于生产代码里的可观测性输出，不是独立业务层。

它的职责是：

- 导出事件
- 记录 route / state / tool / output

它不负责：

- 决定业务流程
- 替代 orchestration
- 替代 evaluator
