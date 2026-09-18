# RAG Tool Contracts

The three Lab 8 tools, exposed over HTTP by `rag_http_server.py` (host, `127.0.0.1:5003`) and
relayed to the application by the shared MCP server's `retrieve_context` / `answer_question` tools.

## refresh_corpus
- Purpose: rebuild the vector index from the corpus files (`corpus/<feature>.jsonl`)
- Input: `feature` (optional — one feature's rows are replaced; omitted = whole collection recreated)
- Output: `status`, `chunk_count`, `collection`, `features` (per-feature counts), `corpus_files`, or `error`
- Policy class: read + index update

## retrieve_context
- Purpose: top-k chunks for a query, ranked by authority tier then distance
- Input: `query` (required), `k` (optional, 5), `feature` (optional), `where` (optional Chroma metadata filter)
- Output: `status`, `retrieval_mode`, `results[]` with `rank`, `chunk_id`, `source_id`, `authority_tier`, `feature`, `distance`, `text` and the chunk's own metadata
- Policy class: read

## answer_question
- Purpose: answer from retrieved context only; "Insufficient evidence." when nothing is within `RAG_MAX_DISTANCE` (decided before any model call)
- Input: `query` (required), `k` (optional), `feature` (optional), `model` (optional — a model in `OLLAMA_PULL_MODELS`)
- Output: `answer`, `insufficient_context`, `citations[]` (`chunk_id`, `source_id`, `authority_tier`), `confidence_category` (High / Medium / Low / Unknown — from evidence quantity and authority), `retrieval_summary` (`k`, `retrieved_count`, `relevant_count`, `top_chunk`, `closest_distance`), or `error`
- Policy class: read + grounded response

## Corpus chunk (what a feature writes, one per line)
- `chunk_id` unique, `"<feature>:<what>"` · `source_id` where it came from · `authority_tier` `tier_1` record / `tier_2` approved doc / `tier_3` repository · `text` · `metadata` optional flat dict · `indexed_at` filled in by refresh
