from fastmcp import FastMCP

mcp = FastMCP("Transactions")

@mcp.resource("docs:://readme", mime_type="text/markdown")
def readme() -> str:
    return "Fetch transactions using requirements with the 'search_transactions' tool";

@mcp.resource("data://transactions")
def search_transactions() -> dict[int, str]:
    return { {1, "gym"}, {2, "food"} }

if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
