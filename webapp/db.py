"""SQLite access (standard library). One connection per request."""
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'teacher')),
    teacher_name  TEXT,                       -- the name used in the timetable
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at    TEXT NOT NULL
);
-- a timetable teacher can be claimed by only one live account
CREATE UNIQUE INDEX IF NOT EXISTS one_account_per_teacher
    ON users (teacher_name) WHERE role = 'teacher' AND status != 'rejected';

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS rooms (name TEXT PRIMARY KEY, kind TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    division   TEXT NOT NULL,
    subject    TEXT NOT NULL,
    teacher    TEXT NOT NULL,
    room       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    day        TEXT NOT NULL,
    start_slot INTEGER NOT NULL,
    duration   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS change_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_user_id INTEGER NOT NULL REFERENCES users(id),
    session_id      INTEGER NOT NULL,
    version         INTEGER NOT NULL,          -- timetable version it was made against
    division        TEXT NOT NULL,
    subject         TEXT NOT NULL,
    from_day        TEXT NOT NULL,
    from_slot       INTEGER NOT NULL,
    to_day          TEXT,                      -- NULL = general request, no specific slot
    to_slot         INTEGER,
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','approved','rejected','cancelled','expired')),
    admin_note      TEXT,
    created_at      TEXT NOT NULL,
    decided_at      TEXT,
    decided_by      INTEGER REFERENCES users(id)
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    with sqlite3.connect(app.config["DATABASE"]) as conn:
        conn.executescript(SCHEMA)
