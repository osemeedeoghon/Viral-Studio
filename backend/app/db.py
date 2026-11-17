"""Tiny SQLite store for jobs and key/value settings (shared by api + worker via the data volume)."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .config import settings

DB_PATH = settings.DATA_DIR / "viral.db"
JSON_FIELDS = ("input", "output")


@contextmanager
def connect():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT, title TEXT, status TEXT, progress REAL,
                message TEXT, input TEXT, output TEXT, error TEXT,
                created_at REAL, updated_at REAL)"""
        )
        c.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")


def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for f in JSON_FIELDS:
        d[f] = json.loads(d[f]) if d.get(f) else None
    return d


def create_job(kind: str, data: dict, title: str = "") -> str:
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with connect() as c:
        c.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, kind, title, "queued", 0.0, "Waiting for a worker…", json.dumps(data), None, None, now, now),
        )
    return job_id


def update_job(job_id: str, **fields):
    for f in JSON_FIELDS:
        if f in fields and fields[f] is not None:
            fields[f] = json.dumps(fields[f])
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k}=?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def get_job(job_id: str) -> dict | None:
    with connect() as c:
        return _row(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def list_jobs(limit: int = 100, kind: str | None = None) -> list[dict]:
    with connect() as c:
        if kind:
            rows = c.execute("SELECT * FROM jobs WHERE kind=? ORDER BY created_at DESC LIMIT ?", (kind, limit))
        else:
            rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_row(r) for r in rows.fetchall()]


def delete_job(job_id: str):
    with connect() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def kv_get(key: str, default: str | None = None) -> str | None:
    with connect() as c:
        r = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


def kv_set(key: str, value: str | None):
    with connect() as c:
        if value is None:
            c.execute("DELETE FROM kv WHERE key=?", (key,))
        else:
            c.execute("INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


init()
