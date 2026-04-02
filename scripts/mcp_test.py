import asyncio
import os

from backend.mcp_client.mcp_minimal import MinimalMCPClient


server_script_path = os.getenv("MCP_SERVER_URL", "").strip()


async def main():
    if not server_script_path:
        raise ValueError("MCP_SERVER_URL is required to run mcp_test.py")
    client = MinimalMCPClient(server_script_path)
    await client.connect()
    await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
