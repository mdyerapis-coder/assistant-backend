# ADR-010: no vector DB / embeddings in v1 — deliberately deferred, not forgotten

**Status:** live

`search_past_conversations` is plain SQLite `LIKE`/FTS5 text search over `messages.content`. No embeddings, no pgvector, no dedicated vector store.

**Why:** researched Khoj before writing this down as a real decision rather than an oversight. Khoj's Postgres+pgvector RAG-over-documents architecture is a proven pattern, but it's solving a different problem (semantic search over an arbitrary document corpus) than this project has in v1 (structured tool-driven data — reminders, events, emails — plus a modest amount of chat history). Revisit only if keyword search over months of accumulated history genuinely proves insufficient. Don't pre-build retrieval infrastructure this project doesn't yet need.
