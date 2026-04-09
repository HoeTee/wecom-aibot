# MCP Tools

## 目的

agent 通过 MCP tools 调用外部能力，而不是直接自由执行本地命令。

当前代码上：

- 稳定 MCP 连接入口仍保留在 `backend/mcp_client/*`
- 新的主编辑位置优先收敛到 `backend/runtime/*`
- 真正的本地 tool 实现优先收敛到 `backend/tools/*`
- 当前动作层开始收敛成 CLI 风格：
  - `backend/runtime/cli.py`
  - `backend/tools/kb_cli.py`
  - `backend/tools/doc_cli.py`
  - `backend/tools/rag_cli.py`
- 本地 `stdio` MCP 服务如果启动即退出，应优先检查 `data/logs/mcp/<server_name>_stderr.log`
- `runtime` 在 stdio 连接失败时，应同时记录 `command`、`args`、`cwd` 和对应 stderr 日志路径

## 分层关系

这里的关系是：

- `caps define`
- `runtime dispatches`
- `tools execute`

也就是：

1. `caps` 定义有哪些业务能力
2. `runtime` 把这些能力映射成 MCP 调用
3. `tools` 真正执行能力

## 关键约束

- 文档连续性依赖 `doc_id`、`doc_url`、`doc_name`
- 用户提到“上一个文档”时，后续编辑应优先复用当前绑定文档
- tool 使用本身就是 eval 的一部分，不只看最终自然语言输出
- `flow` 不应直接 import `tools`
- agent 不应直接使用开放 shell 代替受控 MCP 能力

## tool 质量重点

- 选择正确的文档 tool
- 传入正确的文档标识
- 用户没有明确要求新建文档时，后续编辑不应新建文档
- 调用 `llamaindex_rag` 前，允许做面向检索的 query 改写，但不能丢失用户明确提出的内容要求、结构要求和补充要求
- 本地 `stdio` tool 不应在模块 import 阶段做重型初始化；应优先采用 lazy init，避免 MCP 握手前子进程直接退出
- 本地 `stdio` wrapper 不应只做 import 转发；必须在 `__main__` 中显式启动 `run(...)`

## 当前边界

当前最重要的 MCP 相关能力包括：

- RAG 检索与总结
- 知识库文件枚举
- 上传文件范围枚举
- 知识库文件导出
- 知识库文件删除
- 上传文件改名
- 企业微信文档创建
- 企业微信文档编辑
- 把知识库内容并入当前文档
- 用知识库内容替换当前文档相关部分
- 把知识库内容扩写成新章节

这些能力都应优先做成受控能力，而不是开放 shell。
