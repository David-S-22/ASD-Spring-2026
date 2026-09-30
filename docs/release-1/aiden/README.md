# Release 1 - MCP Anomaly Review Integration

Release 1 adds MCP-backed retrieval to the anomaly-detection workflow. The
Ollama agent can retrieve reviewed transaction examples through the host MCP
server instead of receiving those examples embedded by the Anomalies backend.

## MCP server

The MCP server is implemented in
[`ai-services/mcp-server/server.py`](../../../ai-services/mcp-server/server.py).
It remains a host process rather than a Docker Compose service. The Anomalies
container reaches it through:

```text
http://host.docker.internal:8000/mcp
```

The URL is configured in `docker-compose.yml` as `MCP_SERVER_URL`. The MCP
server reads `TRANSACTIONS_DB_URL` and `ANOMALIES_DB_URL` to access the
transaction and anomaly APIs.

## Reviewed-anomaly tools

The server exposes two tools:

| Tool | Purpose |
| --- | --- |
| `get-transactions-with-confirmed-anomalies` | Returns transactions whose anomalies the user confirmed as suspicious. |
| `get-transactions-with-rejected-anomalies` | Returns transactions whose anomalies the user rejected as false positives. |

Each result contains the matching transaction and anomaly record. The tools
join records by `transaction_id` and exclude anomaly records whose transaction
no longer exists.

## Anomalies integration

Before classifying a transaction, the Anomalies prompt instructs the Ollama model
to call both MCP tools. Confirmed results are treated as positive examples and
rejected results as negative examples. The current transaction is still
evaluated on its own supplied fields; reviewed examples provide feedback rather
than an automatic classification.

The backend no longer loads all anomalies and transactions or constructs
historical context in `agent_api.py`. The review queue passes only the current
transaction to the agent, while the model retrieves historical examples on
demand through MCP.

## Review flow

1. A transaction is queued by the Anomalies backend.
2. Ollama calls both reviewed-anomaly MCP tools.
3. Ollama evaluates the current transaction using the returned examples.
4. The Anomalies backend validates the JSON finding and persists suspicious results.
5. The user confirms or rejects the finding.
6. The next review can retrieve that decision through the MCP tools.
