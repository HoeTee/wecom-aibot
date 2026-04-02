# wecom-aibot

This project has two processes:

1. `backend/app.py`
   - Flask backend
   - calls the LLM
   - optionally connects to an MCP server through `MCP_SERVER_URL`
2. `gateway/long_connection.ts`
   - WeCom long connection gateway
   - receives WeCom messages and forwards them to the backend

## Layout

```text
backend/
  app.py
  agent.py
  mcp_client/
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

## Configure

Copy `.env.example` to `.env`, then fill in:

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_NAME`
- `WECOM_BOT_ID`
- `WECOM_BOT_SECRET`

Optional:

- `BACKEND_BASE_URL` if backend is not running on `http://127.0.0.1:5000`
- `MCP_SERVER_URL` if you want the agent to call MCP tools

## Run

Terminal 1:

```powershell
.venv\Scripts\python.exe -m backend.app
```

Terminal 2:

```powershell
npm run gateway
```

## Current blocking issue

If you run `npm run gateway` with the current repository state, it fails because the WeCom credentials are missing:

```text
Missing WECOM_BOT_ID or WECOM_BOT_SECRET in environment.
```

If you provide placeholder values, the SDK proceeds to connect and then fails authentication, which confirms the remaining missing content is the real WeCom bot credential pair rather than missing code dependencies.

## Optional MCP connectivity test

After setting `MCP_SERVER_URL` in `.env`:

```powershell
.venv\Scripts\python.exe -m scripts.mcp_test
```
