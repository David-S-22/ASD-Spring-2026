PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    merchant TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    cadence TEXT NOT NULL CHECK(cadence IN ('weekly','fortnightly','monthly')),
    next_billing_date TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('bill','subscription')),
    payment_method TEXT,
    status TEXT NOT NULL DEFAULT 'due' CHECK(status IN ('paid','due','overdue')),
    end_date TEXT,
    source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','f3_handoff','f4_handoff','chat')),
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    exclude_from_plan INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','sent','resolved')),
    opened_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dispute_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dispute_id INTEGER NOT NULL REFERENCES disputes(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    letter_text TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(dispute_id, version)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL,
    op_json TEXT,
    applied INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
