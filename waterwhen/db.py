"""SQLite store for beds, waterings, readings and the weather cache."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS beds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    length_m REAL NOT NULL,
    width_m REAL NOT NULL,
    depth_m REAL NOT NULL,
    soil TEXT NOT NULL,
    mulch TEXT NOT NULL,
    crop TEXT NOT NULL,
    stage TEXT NOT NULL,
    kc_override REAL,
    method TEXT NOT NULL,
    can_litres REAL NOT NULL,
    flow_lpm REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS waterings (
    id TEXT PRIMARY KEY,
    bed_id TEXT NOT NULL REFERENCES beds(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    litres REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    id TEXT PRIMARY KEY,
    bed_id TEXT NOT NULL REFERENCES beds(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    feel TEXT,
    value REAL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weather_cache (
    location_key TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_waterings_bed ON waterings(bed_id, date);
CREATE INDEX IF NOT EXISTS idx_readings_bed ON readings(bed_id, date);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:10]


class Store:
    def __init__(self, path: str):
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---- beds ------------------------------------------------------------
    def list_beds(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM beds ORDER BY created_at ASC").fetchall()
        return [dict(row) for row in rows]

    def get_bed(self, bed_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM beds WHERE id = ?", (bed_id,)).fetchone()
        return dict(row) if row else None

    def create_bed(self, data: dict) -> dict:
        bed_id = new_id()
        stamp = now_iso()
        self.conn.execute(
            """INSERT INTO beds (id, name, lat, lon, length_m, width_m, depth_m, soil, mulch,
               crop, stage, kc_override, method, can_litres, flow_lpm, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bed_id,
                data["name"],
                data["lat"],
                data["lon"],
                data["length_m"],
                data["width_m"],
                data["depth_m"],
                data["soil"],
                data["mulch"],
                data["crop"],
                data["stage"],
                data.get("kc_override"),
                data["method"],
                data["can_litres"],
                data["flow_lpm"],
                stamp,
                stamp,
            ),
        )
        self.conn.commit()
        return self.get_bed(bed_id)

    def update_bed(self, bed_id: str, data: dict) -> dict | None:
        existing = self.get_bed(bed_id)
        if not existing:
            return None
        merged = {**existing, **data}
        self.conn.execute(
            """UPDATE beds SET name = ?, lat = ?, lon = ?, length_m = ?, width_m = ?,
               depth_m = ?, soil = ?, mulch = ?, crop = ?, stage = ?, kc_override = ?,
               method = ?, can_litres = ?, flow_lpm = ?, updated_at = ? WHERE id = ?""",
            (
                merged["name"],
                merged["lat"],
                merged["lon"],
                merged["length_m"],
                merged["width_m"],
                merged["depth_m"],
                merged["soil"],
                merged["mulch"],
                merged["crop"],
                merged["stage"],
                merged.get("kc_override"),
                merged["method"],
                merged["can_litres"],
                merged["flow_lpm"],
                now_iso(),
                bed_id,
            ),
        )
        self.conn.commit()
        return self.get_bed(bed_id)

    def delete_bed(self, bed_id: str) -> bool:
        cursor = self.conn.execute("DELETE FROM beds WHERE id = ?", (bed_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- waterings -------------------------------------------------------
    def add_watering(self, bed_id: str, date: str, litres: float, note: str = "") -> dict:
        watering_id = new_id()
        self.conn.execute(
            "INSERT INTO waterings (id, bed_id, date, litres, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (watering_id, bed_id, date, litres, note, now_iso()),
        )
        self.conn.commit()
        return self.get_watering(watering_id)

    def get_watering(self, watering_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM waterings WHERE id = ?", (watering_id,)).fetchone()
        return dict(row) if row else None

    def list_waterings(self, bed_id: str, since: str | None = None) -> list[dict]:
        if since:
            rows = self.conn.execute(
                "SELECT * FROM waterings WHERE bed_id = ? AND date >= ? ORDER BY date ASC",
                (bed_id, since),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM waterings WHERE bed_id = ? ORDER BY date ASC", (bed_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_watering(self, bed_id: str, watering_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM waterings WHERE id = ? AND bed_id = ?", (watering_id, bed_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- readings --------------------------------------------------------
    def add_reading(self, bed_id: str, date: str, feel: str | None, value: float | None, note: str = "") -> dict:
        reading_id = new_id()
        self.conn.execute(
            "INSERT INTO readings (id, bed_id, date, feel, value, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (reading_id, bed_id, date, feel, value, note, now_iso()),
        )
        self.conn.commit()
        return self.get_reading(reading_id)

    def get_reading(self, reading_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM readings WHERE id = ?", (reading_id,)).fetchone()
        return dict(row) if row else None

    def latest_reading(self, bed_id: str, within_days: int = 14) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM readings WHERE bed_id = ? "
            "AND date >= date('now', ?) ORDER BY date DESC, created_at DESC LIMIT 1",
            (bed_id, f"-{within_days} days"),
        ).fetchone()
        return dict(row) if row else None

    def list_readings(self, bed_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM readings WHERE bed_id = ? ORDER BY date ASC, created_at ASC", (bed_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    # ---- weather cache ---------------------------------------------------
    def weather_get(self, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT location_key, fetched_at, payload FROM weather_cache WHERE location_key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0
        try:
            payload = json.loads(row["payload"])
        except json.JSONDecodeError:
            return None
        return {
            "location_key": row["location_key"],
            "fetched_at": row["fetched_at"],
            "payload": payload,
            "age_hours": age,
        }

    def weather_put(self, key: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO weather_cache (location_key, fetched_at, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(location_key) DO UPDATE SET fetched_at = excluded.fetched_at, payload = excluded.payload",
            (key, now_iso(), json.dumps(payload)),
        )
        self.conn.commit()