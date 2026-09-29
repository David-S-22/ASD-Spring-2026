import asyncio
import os

from fastmcp import Client

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
FEATURE = "billing"
QUESTION = "Which bill is overdue?"


async def main():
    """Call the RAG retrieval tool on the running MCP server and print what comes back."""
    async with Client(MCP_SERVER_URL) as client:
        print("tools:", [tool.name for tool in await client.list_tools()])
        rows = await client.call_tool("search_transactions", {"merchant": "FibreLink"})
        print("search_transactions merchant=FibreLink:", len(rows.data), "rows; first:", rows.data[0] if rows.data else None)
        found = await client.call_tool("retrieve_context", {"feature": FEATURE, "question": QUESTION, "k": 2})
        for result in found.data["results"]:
            print(result["id"], round(result["distance"], 3), result["text"])


if __name__ == "__main__":
    asyncio.run(main())
