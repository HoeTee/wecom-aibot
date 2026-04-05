import asyncio
import os
import pprint
from dotenv import load_dotenv
from backend.mcp_client.mcp_minimal import MinimalMCPClient

async def test_mcp_client():
    load_dotenv()
    server_target = os.getenv("MCP_SERVER_URL")
    mcp_client = MinimalMCPClient(server_target)
    try:
        await mcp_client.connect()
        print("MCP client connected to server.")
        print("MCP client tools:")
        pprint.pprint(mcp_client.tools)
    finally:
        await mcp_client.cleanup()
        print("MCP client closed.")

async def main():
    await test_mcp_client()


if __name__ == "__main__":
    asyncio.run(main())
