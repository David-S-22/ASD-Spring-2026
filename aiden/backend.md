# Anomalies Backend

## Overview

The backend is a Flask application that provides the anomaly-detection API. It
coordinates transaction retrieval, asynchronous reviews, model requests, and
anomaly persistence. The application starts a daemon review worker when it is
initialised and returns JSON for API responses or rendered Jinja fragments for
the frontend.

Transactions are submitted for review as `dto.Transaction` objects. The backend
does not store transaction records itself; it retrieves transactions from the
transactions database and sends detected anomalies to the anomalies database.
Configuration such as service URLs, the model name, and polling timeouts is
read from environment variables.

## Agentic workflow

1. The frontend sends a transaction to `POST /check-transaction`.
2. The backend validates and deserialises the request into a transaction DTO.
3. The transaction is placed on the in-process review queue, and the endpoint
   immediately returns `HTTP 202 (Accepted)` with the transaction ID.
4. A background worker retrieves the transaction and loads existing anomalies
   and transactions to provide reviewed context to the agent.
5. The agent builds a constrained prompt for the language model, including the
   transaction fields and confirmed or denied historical findings.
6. The model must return JSON containing `is_suspicious` and `justification`.
   Invalid responses are retried with increasing temperature, up to four
   attempts.
7. If the transaction is suspicious, the resulting anomaly is written to the
   anomalies database. Otherwise, no anomaly is created.
8. The worker marks the transaction as complete. The frontend can poll
   `GET /anomaly-alert?key=<transaction-id>` for a rendered alert fragment.

The agent is instructed to be cautious, avoid claiming fraud as fact, use only
the supplied transaction information, and incorporate the user's previous
confirmation or dismissal decisions.

## Services

### `services/agent_api.py`

Implements the anomaly-detection agent. It creates prompts, builds context from
reviewed anomalies, parses model JSON, validates the expected response fields,
and converts suspicious findings into anomaly DTOs.

### `services/review_queue.py`

Provides the in-process queue and daemon worker. It tracks pending and
completed transaction IDs, runs reviews outside the request thread, persists
findings, and allows callers to wait for a specific transaction's result.

### `services/anomalies_api.py`

HTTP client for the anomalies database. It retrieves all anomalies, looks up an
anomaly by transaction ID, creates anomalies, and updates user confirmation
status.

### `services/transaction_api.py`

HTTP client for the transactions database. It retrieves transaction records
used for anomaly listings and agent context.

### `services/ollama_api.py`

OpenAI-compatible client wrapper for the model server. It caches one client
instance and sends system and user prompts with the configured model,
temperature, token limit, and timeout.

### `helpers.py`

Contains request DTO deserialisation, DTO serialisation, and environment
variable helpers used by the application and integration clients.

## Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/` | Returns the backend health response. |
| `GET` | `/fact` | Requests and returns a random fact from the configured model. |
| `GET` | `/anomalies` | Retrieves anomalies and transactions, then renders the anomaly list. |
| `POST` | `/check-transaction` | Validates and queues a transaction for asynchronous review; returns `202`. |
| `GET` | `/anomaly-alert?key=<id>` | Waits for a queued review and returns an alert fragment when an anomaly exists, otherwise `204`. |
| `POST` | `/anomalies/<id>/confirm` | Marks an anomaly as confirmed and returns the refreshed anomaly list. |
| `POST` | `/anomalies/<id>/dismiss` | Marks an anomaly as dismissed and returns the refreshed anomaly list. |
| `POST` | `/dummy-anomaly` | Creates a random test anomaly and returns the refreshed anomaly list. |
