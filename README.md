# wecom-aibot

This project has two runtime processes:

1. `backend/app.py`
   - Flask backend
   - calls the LLM
   - can load zero, one, or many MCP servers through an MCP host
2. `gateway/long_connection.ts`
   - WeCom long connection gateway
   - receives WeCom messages and forwards them to the backend

## Layout

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
    mcp_minimal.py
config/
  mcp_servers.example.json
data/
  memory.sqlite3  # runtime-generated
gateway/
  long_connection.ts
scripts/
  mcp_test.py
```

## Verified environment

- Node.js `v24.11.1`
- Python `3.11.9`

## Install

Python:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Node.js:

```powershell
npm install
```

## Environment configuration

Copy `.env.example` to `.env`, then fill in:

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL` (or legacy `LLM_NAME`)
- `WECOM_BOT_ID`
- `WECOM_BOT_SECRET`

Optional:

- `BACKEND_BASE_URL` if backend is not running on `http://127.0.0.1:5000`
- `MCP_SERVERS_CONFIG` to load one or more MCP servers through a JSON config file
- `MCP_SERVER_URL` as a legacy fallback for a single server only

Security note:

- `config/mcp_servers.json` is a local-only file and must not be committed because it may contain secrets such as API keys
- runtime artifacts under `data/`, `persist/`, and `manifest/` must not be committed

If `WECOM_BOT_ID` or `WECOM_BOT_SECRET` is missing, `npm run gateway` will fail at startup.

The backend session memory uses a local SQLite file at `data/memory.sqlite3`.
No extra memory-specific environment variable is required.

## MCP host overview

The backend no longer assumes a single MCP server.

It now loads server definitions into an MCP host that:

- connects to multiple servers
- supports remote `streamable_http` and `sse` transports
- supports local `stdio` servers through explicit `command + args`
- exposes all tools to the model in standard OpenAI function-calling shape
- namespaces exposed tool names as `<tool_prefix>__<remote_tool_name>`
- routes tool calls back to the correct server by exposed tool name

Example:

- server name: `wecom`
- remote tool name: `create_doc`
- exposed tool name to the model: `wecom__create_doc`

Request flow:

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

## MCP server config

Copy `config/mcp_servers.example.json` to `config/mcp_servers.json`, then set:

- `name`: unique server identifier inside the host
- `transport`: one of `streamable_http`, `sse`, or `stdio`
- `tool_prefix`: optional prefix used when exposing tools to the model. If omitted, it defaults to a normalized form of `name`
- `required`: whether backend startup should fail if this server cannot connect

Transport-specific fields:

- `streamable_http` or `sse`: set `url`
- `stdio`: set `command`, optional `args`, optional `cwd`, optional `env`

Example:

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

## Why `command + args` for local servers

Local MCP servers are not inferred from file extension anymore.

Instead of guessing from `.py` or `.js`, the host launches local servers explicitly with:

- `command`: executable to run
- `args`: argv list passed to that executable

That supports:

- Python scripts
- Python modules via `-m`
- Node entrypoints
- `npx`-based MCP servers
- native binaries

Examples:

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

## Legacy fallback

`MCP_SERVER_URL` still works for compatibility with the older single-server path.

Legacy behavior:

- `http://...` or `https://...` -> treated as `streamable_http`
- `*.py` -> treated as `stdio` with `python <file>`
- `*.js` -> treated as `stdio` with `node <file>`

New setups should prefer `MCP_SERVERS_CONFIG`.

## Run

Terminal 1:

```powershell
.venv\Scripts\python.exe -m backend.app
```

Terminal 2:

```powershell
npm run gateway
```

## Session memory

The backend now keeps a small local memory for each WeCom conversation.

Storage:

- `data/memory.sqlite3`

Session identity:

- single chat -> `dm:{userId}`
- group chat -> `group:{chatId}`

Stored memory:

- recent dialogue turns
- recent MCP tool calls
- recently bound WeCom documents

For each bound document, the backend persists the document triple:

- `doc_id`
- `doc_url`
- `doc_name`

This is primarily used for the WeCom document workflow. If the user later says things like "modify the last document" or "update that weekly report", the agent can look up the current session's recent document bindings and prefer the recorded `doc_id`.

Current read window:

- up to 10 recent dialogue turns from the last 7 days
- up to 6 recent MCP calls from the last 30 days
- up to 5 recent bound documents from the last 30 days

The memory database is created automatically on backend startup.

## MCP connectivity tests

After setting `MCP_SERVERS_CONFIG` in `.env`:

```powershell
.venv\Scripts\python.exe -m scripts.mcp_test
```

That script:

- loads the configured servers
- connects the MCP host
- prints exposed tools
- prints the host routing table
- closes all server connections

If you only have the old single-server environment variable set, the same script still works through the legacy fallback:

```powershell
.venv\Scripts\python.exe -m scripts.mcp_test
```

## Current backend behavior

For each chat request, the backend:

1. builds a session ID from the incoming WeCom chat metadata
2. loads recent session memory from `data/memory.sqlite3`
3. loads MCP server config from environment
4. constructs an `MCPHost`
5. connects all configured servers
6. passes both the aggregated tools and the session memory context into the agent
7. routes tool calls back to the correct MCP server by exposed tool name
8. stores recent tool usage and document bindings such as `doc_id`, `doc_url`, and `doc_name`
9. stores the user turn and assistant reply in session memory
10. cleans up all MCP connections in `finally`

This keeps host lifecycle simple while still giving the agent short-term conversation and document memory across requests.
