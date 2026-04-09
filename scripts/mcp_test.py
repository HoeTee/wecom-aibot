import asyncio
import pprint
import sys
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.runtime import MCPHost, load_mcp_server_configs_from_env

async def test_mcp_client():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    server_configs = load_mcp_server_configs_from_env()
    if not server_configs:
        raise ValueError("No MCP server configuration found. Set MCP_SERVERS_CONFIG or MCP_SERVER_URL.")

    mcp_host = MCPHost(server_configs)
    try:
        await mcp_host.connect_all()
        print("MCP host connected.")
        print("Connected servers:", list(mcp_host.connections))
        # print("Exposed MCP tools:")
        # pprint.pprint(mcp_host.tools)
        # print("Tool routes:")
        # pprint.pprint({name: asdict(route) for name, route in mcp_host.get_tool_routes().items()})
    finally:
        await mcp_host.cleanup()
        print("MCP host closed.")

async def main():
    await test_mcp_client()


if __name__ == "__main__":
    asyncio.run(main())
