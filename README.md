# wecom-aibot

这个项目包含两个运行进程：

1. [backend/app.py](/C:/Users/18014/wecom-aibot/backend/app.py)
   - Flask backend
   - 负责调用 LLM
   - 可通过 MCP host 加载零个、一个或多个 MCP servers
2. [gateway/long_connection.ts](/C:/Users/18014/wecom-aibot/gateway/long_connection.ts)
   - 企业微信长连接 gateway
   - 负责接收企业微信消息并转发给 backend

## 目录结构

```text
backend/
  app.py
  agent.py
  memory.py
  mcp_client/
    config.py
    connection.py
    host.py
    mcp_logger.py
config/
  mcp_servers.example.json
data/
  memory.sqlite3  # 运行时自动生成
docs/
  *.md
evals/
  gates/
  scenarios/
gateway/
  long_connection.ts
knowledge_base/
  papers/
prompts/
  system/
scripts/
  mcp_test.py
```

## 已验证环境

- Node.js `v24.11.1`
- Python `3.11.9`

## 安装

Python：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Node.js：

```powershell
npm install
```

## 环境变量配置

复制 `.env.example` 为 `.env`，然后至少填写：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`，兼容旧字段 `LLM_NAME`
- `WECOM_BOT_ID`
- `WECOM_BOT_SECRET`

可选字段：

- `BACKEND_BASE_URL`：当 backend 不运行在 `http://127.0.0.1:5000` 时使用
- `MCP_SERVERS_CONFIG`：通过 JSON 配置文件加载一个或多个 MCP servers
- `MCP_SERVER_URL`：旧的单 server 兼容字段

如果缺少 `WECOM_BOT_ID` 或 `WECOM_BOT_SECRET`，执行 `npm run gateway` 时会直接启动失败。

backend 的 session memory 使用本地 SQLite 文件：

- `data/memory.sqlite3`

不需要额外的 memory 专用环境变量。

## MCP host 概览

backend 不再假定只有一个 MCP server。

现在它会把 server 定义加载进一个 MCP host，并具备以下能力：

- 连接多个 servers
- 支持远程 `streamable_http` 和 `sse` transport
- 支持本地 `stdio` servers，通过显式 `command + args` 启动
- 以标准 OpenAI function-calling 形式向模型暴露 tools
- 对外暴露的 tool 名称采用 `<tool_prefix>__<remote_tool_name>` 命名空间
- 按对外暴露的 tool 名称把调用路由回正确的 server

示例：

- server 名称：`wecom`
- 远端 tool 名称：`create_doc`
- 暴露给模型的 tool 名称：`wecom__create_doc`

请求流：

```text
User message
  -> Agent
  -> OpenAI chat.completions with host-exposed tools
  -> model selects tool name like wecom__create_doc
  -> MCPHost looks up route for wecom__create_doc
  -> MCPServerConnection for server "wecom"
  -> remote MCP tool "create_doc"
  -> tool result returns to MCPHost
  -> Agent appends tool message
  -> model produces final answer
```

## MCP server 配置

复制 `config/mcp_servers.example.json` 为 `config/mcp_servers.json`，然后设置：

- `name`：host 内部唯一 server 标识
- `transport`：`streamable_http`、`sse` 或 `stdio`
- `tool_prefix`：暴露 tool 名称时使用的前缀；为空时默认使用 `name` 的规范化形式
- `required`：如果该 server 无法连接，backend 启动是否直接失败

按 transport 区分的字段：

- `streamable_http` 或 `sse`：填写 `url`
- `stdio`：填写 `command`，可选 `args`、`cwd`、`env`

示例：

```json
{
  "servers": [
    {
      "name": "wecom",
      "tool_prefix": "wecom",
      "transport": "streamable_http",
      "url": "http://127.0.0.1:8000/mcp",
      "required": false
    },
    {
      "name": "filesystem",
      "tool_prefix": "fs",
      "transport": "stdio",
      "command": "npx.cmd",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\work"],
      "required": false
    },
    {
      "name": "local_python_server",
      "tool_prefix": "localpy",
      "transport": "stdio",
      "command": ".venv\\Scripts\\python.exe",
      "args": ["-m", "my_mcp_server"],
      "cwd": ".",
      "env": {
        "MY_SERVER_MODE": "dev"
      },
      "required": false
    }
  ]
}
```

## 为什么本地 server 使用 `command + args`

本地 MCP server 不再根据文件扩展名做推断。

现在 host 会显式通过以下字段启动本地 server：

- `command`：可执行程序
- `args`：传给该程序的 argv 列表

这样可以同时支持：

- Python scripts
- 通过 `-m` 启动的 Python modules
- Node entrypoints
- 基于 `npx` 的 MCP servers
- 原生二进制程序

示例：

```json
{
  "name": "py_script",
  "tool_prefix": "pyscript",
  "transport": "stdio",
  "command": ".venv\\Scripts\\python.exe",
  "args": ["servers\\demo_server.py"]
}
```

```json
{
  "name": "py_module",
  "tool_prefix": "pymodule",
  "transport": "stdio",
  "command": ".venv\\Scripts\\python.exe",
  "args": ["-m", "demo_server"]
}
```

```json
{
  "name": "node_server",
  "tool_prefix": "node",
  "transport": "stdio",
  "command": "node",
  "args": ["dist\\server.js"]
}
```

## 旧兼容路径

`MCP_SERVER_URL` 仍然保留，用于兼容旧的单 server 配置方式。

旧行为如下：

- `http://...` 或 `https://...`：按 `streamable_http` 处理
- `*.py`：按 `stdio`，使用 `python <file>`
- `*.js`：按 `stdio`，使用 `node <file>`

新配置应优先使用 `MCP_SERVERS_CONFIG`。

## 运行

终端 1：

```powershell
.venv\Scripts\python.exe -m backend.app
```

终端 2：

```powershell
npm run gateway
```

## Session memory

backend 现在会为每个企业微信会话维护一份轻量本地 memory。

存储位置：

- `data/memory.sqlite3`

会话标识：

- 单聊：`dm:{userId}`
- 群聊：`group:{chatId}`

存储内容：

- 最近对话
- 最近 MCP tool 调用
- 最近绑定的企业微信文档

对于每个绑定文档，backend 会持久化保存下面这个文档三元组：

- `doc_id`
- `doc_url`
- `doc_name`

这套 memory 主要服务于企业微信文档工作流。当用户后续说“修改刚才那个文档”或“更新那个周报”时，agent 会优先读取当前 session 最近绑定的文档，并使用记录下来的 `doc_id`。

当前读取窗口：

- 最近 7 天内最多 10 条对话
- 最近 30 天内最多 6 次 MCP 调用
- 最近 30 天内最多 5 份已绑定文档

memory 数据库会在 backend 启动时自动创建。

## MCP 连通性测试

在 `.env` 里设置好 `MCP_SERVERS_CONFIG` 后，执行：

```powershell
.venv\Scripts\python.exe -m scripts.mcp_test
```

这个脚本会：

- 加载配置好的 servers
- 连接 MCP host
- 打印暴露出来的 tools
- 打印 host 路由表
- 关闭所有 server 连接

如果你仍然只设置了旧的单 server 环境变量，这个脚本也会通过兼容路径工作：

```powershell
.venv\Scripts\python.exe -m scripts.mcp_test
```

## backend 当前行为

对于每次聊天请求，backend 会：

1. 根据企业微信会话元数据生成 session ID
2. 从 `data/memory.sqlite3` 读取最近 session memory
3. 从环境变量加载 MCP server 配置
4. 构造 `MCPHost`
5. 连接所有已配置 servers
6. 把聚合后的 tools 和 session memory context 一起传给 agent
7. 按对外 tool 名称把调用路由回正确的 MCP server
8. 记录最近 tool 使用和文档绑定，例如 `doc_id`、`doc_url`、`doc_name`
9. 把用户消息和 assistant 回复写回 session memory
10. 在 `finally` 中清理所有 MCP 连接

这样可以在保持 host 生命周期简单的同时，为 agent 提供跨请求的短期会话记忆和文档连续性。
