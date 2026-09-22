import asyncio
import os

from fastmcp import Client

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")
FEATURE = "bills"
QUESTION = "Which bill is overdue?"


async def main():
    """Call the three RAG tools on the running MCP server and print what comes back."""
    async with Client(MCP_SERVER_URL) as client:
        print("tools:", [tool.name for tool in await client.list_tools()])
        found = await client.call_tool("retrieve_context", {"feature": FEATURE, "question": QUESTION, "k": 2})
        for result in found.data["results"]:
            print(result["id"], round(result["distance"], 3), result["text"])
        answered = await client.call_tool("answer_question", {"feature": FEATURE, "question": QUESTION})
        print(answered.data)
        reviewed = await client.call_tool("review_answer", {"feature": FEATURE, "question": QUESTION, "answer": answered.data["answer"]})
        print(reviewed.data)


if __name__ == "__main__":
    asyncio.run(main())
