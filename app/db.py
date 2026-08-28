"""SQLite schema + connection management, plain SQL (no ORM at this size).

One shared aiosqlite connection, opened at app startup (see main.py's
lifespan) and closed at shutdown. WAL mode so a slow read (e.g. tier-2
memory search) doesn't block a concurrent write.
"""

import aiosqlite

from . import config

_connection: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    name TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

CREATE TABLE IF NOT EXISTS user_facts (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    fired_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_at);

CREATE TABLE IF NOT EXISTS device_tokens (
    token TEXT PRIMARY KEY,
    device_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS google_oauth_tokens (
    provider TEXT PRIMARY KEY,
    access_token_enc BLOB NOT NULL,
    refresh_token_enc BLOB NOT NULL,
    expiry TEXT NOT NULL,
    scope TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON oauth_states(expires_at);

CREATE TABLE IF NOT EXISTS skill_usage (
    name TEXT PRIMARY KEY,
    activations INTEGER DEFAULT 0,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS action_patterns (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    args_template TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    first_at TEXT,
    last_at TEXT,
    nudge_count INTEGER DEFAULT 0,
    UNIQUE(name, args_template)
);

CREATE TABLE IF NOT EXISTS plugins (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    installed_at TEXT NOT NULL
);
"""


async def connect() -> aiosqlite.Connection:
    global _connection
    _connection = await aiosqlite.connect(config.DB_PATH)
    await _connection.execute("PRAGMA journal_mode=WAL")
    await _connection.executescript(SCHEMA)
    await _connection.commit()
    return _connection


async def disconnect() -> None:
    global _connection
    if _connection is not None:
        await _connection.close()
        _connection = None


def get_connection() -> aiosqlite.Connection:
    assert _connection is not None, "db not connected — call db.connect() at startup"
    return _connection
