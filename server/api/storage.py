"""SQLite-backed storage for the server (project v0.3).

Replaces the v0.1/v0.2 in-memory dicts with a durable SQLite database so data
survives a server restart. The public function signatures are unchanged, so
`main.py`, the protocol contract, and the edge agent keep working as-is.

Design
------
- stdlib ``sqlite3`` only (no ORM).
- detections / events keep searchable ``device_id`` + ``timestamp`` columns and
  store the full protocol payload as a JSON blob (preserves the ``class`` alias
  and Korean text exactly).
- The latest heartbeat per device is kept in ``device_state`` as JSON.
- Snapshot bytes are stored as a BLOB.
- DB path is configurable via ``CCTV_DB_PATH`` (default ``<repo>/data/cctv.db``);
  the ``data/`` dir is git-ignored.
- ``rpi-001`` is seeded only when the ``devices`` table is empty; existing data
  is never overwritten on restart.
"""

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional


# --- DB location -------------------------------------------------------------
# Default: <repo root>/data/cctv.db   (data/ is git-ignored)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB = _REPO_ROOT / "data" / "cctv.db"
_DB_PATH = Path(os.environ.get("CCTV_DB_PATH", str(_DEFAULT_DB)))

# Seed device (only applied when the devices table is empty).
_SEED_DEVICE = ("rpi-001", "dev-key-rpi-001", "정문 CCTV")

_lock = threading.Lock()
_conn: sqlite3.Connection


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            api_key   TEXT NOT NULL,
            location  TEXT
        );

        CREATE TABLE IF NOT EXISTS device_state (
            device_id      TEXT PRIMARY KEY,
            last_seen      TEXT,
            status         TEXT,
            heartbeat_json TEXT
        );

        CREATE TABLE IF NOT EXISTS detections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id   TEXT NOT NULL,
            timestamp   TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_detections_device_ts
            ON detections (device_id, timestamp);

        CREATE TABLE IF NOT EXISTS events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id   TEXT NOT NULL,
            timestamp   TEXT,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_events_device_ts
            ON events (device_id, timestamp);

        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id   TEXT PRIMARY KEY,
            device_id     TEXT NOT NULL,
            content_type  TEXT,
            metadata_json TEXT,
            data          BLOB
        );
        """
    )
    # Seed only when there are no devices yet (never clobber existing data).
    count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    if count == 0:
        conn.execute(
            "INSERT INTO devices (device_id, api_key, location) VALUES (?, ?, ?)",
            _SEED_DEVICE,
        )
    conn.commit()


def _dumps(obj) -> str:
    # ensure_ascii=False keeps Korean readable in the DB; sqlite stores UTF-8.
    return json.dumps(obj, ensure_ascii=False)


# Initialise at import so main.py needs no startup hook.
_conn = _connect()
_init(_conn)


# --- Devices / auth ----------------------------------------------------------

def device_exists(device_id: str) -> bool:
    with _lock:
        row = _conn.execute(
            "SELECT 1 FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
    return row is not None


def get_api_key(device_id: str) -> Optional[str]:
    with _lock:
        row = _conn.execute(
            "SELECT api_key FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
    return row["api_key"] if row else None


def register_device(device_id: str, api_key: str, location: Optional[str] = None) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR REPLACE INTO devices (device_id, api_key, location) "
            "VALUES (?, ?, ?)",
            (device_id, api_key, location),
        )
        _conn.commit()


def list_devices() -> List[dict]:
    with _lock:
        rows = _conn.execute(
            """
            SELECT d.device_id, d.location, s.last_seen, s.status, s.heartbeat_json
            FROM devices d
            LEFT JOIN device_state s ON s.device_id = d.device_id
            ORDER BY d.device_id
            """
        ).fetchall()

    out = []
    for r in rows:
        hb = json.loads(r["heartbeat_json"]) if r["heartbeat_json"] else {}
        out.append({
            "device_id": r["device_id"],
            "last_seen": r["last_seen"],
            "status": r["status"],
            "location": r["location"],
            # Additive fields surfaced from the latest heartbeat (null until one
            # arrives). Existing consumers can ignore them; the protocol §4.5
            # shape is preserved.
            "fps": (hb.get("camera") or {}).get("fps"),
            "model_version": (hb.get("inference") or {}).get("model_version"),
        })
    return out


def get_device(device_id: str) -> Optional[dict]:
    with _lock:
        row = _conn.execute(
            """
            SELECT d.device_id, d.location, s.last_seen, s.status, s.heartbeat_json
            FROM devices d
            LEFT JOIN device_state s ON s.device_id = d.device_id
            WHERE d.device_id = ?
            """,
            (device_id,),
        ).fetchone()
    if row is None:
        return None
    hb = json.loads(row["heartbeat_json"]) if row["heartbeat_json"] else None
    return {
        "device_id": row["device_id"],
        "location": row["location"],
        "last_seen": row["last_seen"],
        "status": row["status"],
        "heartbeat": hb,
    }


# --- Writes ------------------------------------------------------------------

def record_heartbeat(device_id: str, hb: dict) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR REPLACE INTO device_state "
            "(device_id, last_seen, status, heartbeat_json) VALUES (?, ?, ?, ?)",
            (device_id, hb.get("timestamp"), hb.get("status"), _dumps(hb)),
        )
        _conn.commit()


def append_detections(device_id: str, items: List[dict]) -> int:
    with _lock:
        _conn.executemany(
            "INSERT INTO detections (device_id, timestamp, payload_json) "
            "VALUES (?, ?, ?)",
            [(device_id, d.get("timestamp"), _dumps(d)) for d in items],
        )
        _conn.commit()
    return len(items)


def append_event(device_id: str, ev: dict) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO events (device_id, timestamp, payload_json) VALUES (?, ?, ?)",
            (device_id, ev.get("timestamp"), _dumps(ev)),
        )
        _conn.commit()


def store_snapshot(
    device_id: str,
    snapshot_id: str,
    data: bytes,
    metadata: dict,
    content_type: str,
) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR REPLACE INTO snapshots "
            "(snapshot_id, device_id, content_type, metadata_json, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (snapshot_id, device_id, content_type, _dumps(metadata), sqlite3.Binary(data)),
        )
        _conn.commit()


def get_snapshot(snapshot_id: str) -> Optional[dict]:
    with _lock:
        row = _conn.execute(
            "SELECT device_id, content_type, metadata_json, data "
            "FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "device_id": row["device_id"],
        "data": bytes(row["data"]),
        "content_type": row["content_type"],
        "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {},
    }


# --- Reads -------------------------------------------------------------------

def _query(table: str, device_id: str, since: Optional[str],
           until: Optional[str], limit: int) -> List[dict]:
    # Mirror the previous in-memory semantics: ISO 8601 UTC strings sort
    # lexicographically; a NULL timestamp is always in range; return the most
    # recent `limit` matching rows in ascending insertion order (== list[-limit:]).
    where = ["device_id = ?"]
    params: list = [device_id]
    if since:
        where.append("(timestamp IS NULL OR timestamp >= ?)")
        params.append(since)
    if until:
        where.append("(timestamp IS NULL OR timestamp <= ?)")
        params.append(until)
    clause = " AND ".join(where)
    sql = (
        f"SELECT payload_json FROM ("
        f"  SELECT id, payload_json FROM {table} WHERE {clause} "
        f"  ORDER BY id DESC LIMIT ?"
        f") ORDER BY id ASC"
    )
    params.append(limit)
    with _lock:
        rows = _conn.execute(sql, params).fetchall()
    return [json.loads(r["payload_json"]) for r in rows]


def query_detections(
    device_id: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
) -> List[dict]:
    return _query("detections", device_id, since, until, limit)


def query_events(
    device_id: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
) -> List[dict]:
    return _query("events", device_id, since, until, limit)
