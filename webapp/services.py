"""Business logic shared by the pages: publishing, grids, queries."""
import json
import zlib
from dataclasses import dataclass
from datetime import datetime

from schedulomatic import Timetable, find_conflicts, load_config
from schedulomatic.moves import RoomRec, SessionRec


def now():
    return datetime.now().isoformat(timespec="seconds")


def hue(text):
    """A stable colour (0-359) for a subject name."""
    return zlib.crc32(text.encode("utf-8")) % 360


# ---------------------------------------------------------------- reading
def get_meta(db):
    rows = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta")}
    if "version" not in rows:
        return None
    return {"version": int(rows["version"]), "days": json.loads(rows["days"]),
            "slots": json.loads(rows["slots"]), "break_after": json.loads(rows["break_after"]),
            "published_at": rows["published_at"], "seed": int(rows["seed"]),
            "config": rows["config"]}


def all_sessions(db):
    return [SessionRec(**dict(r)) for r in db.execute("SELECT * FROM sessions ORDER BY id")]


def all_rooms(db):
    return [RoomRec(r["name"], r["kind"]) for r in db.execute("SELECT * FROM rooms ORDER BY name")]


def divisions(sessions):
    return sorted({s.division for s in sessions})


def teachers(sessions):
    return sorted({s.teacher for s in sessions})


def unclaimed_teachers(db):
    rows = db.execute(
        "SELECT DISTINCT teacher FROM sessions WHERE teacher NOT IN "
        "(SELECT teacher_name FROM users WHERE role = 'teacher' AND status != 'rejected' "
        " AND teacher_name IS NOT NULL) ORDER BY teacher").fetchall()
    return [r["teacher"] for r in rows]


def pending_counts(db):
    return {"requests": db.execute("SELECT COUNT(*) FROM change_requests WHERE status='pending'").fetchone()[0],
            "accounts": db.execute("SELECT COUNT(*) FROM users WHERE role='teacher' AND status='pending'").fetchone()[0]}


def classes_taught(sessions, teacher):
    found = {}
    for s in sessions:
        if s.teacher != teacher:
            continue
        c = found.setdefault(s.division, {"division": s.division, "sessions": 0, "subjects": {}})
        sub = c["subjects"].setdefault(s.subject, {"subject": s.subject, "kind": s.kind,
                                                   "sessions": 0, "rooms": set()})
        sub["sessions"] += 1
        sub["rooms"].add(s.room)
        c["sessions"] += 1
    result = []
    for name in sorted(found):
        c = found[name]
        c["subjects"] = [dict(v, rooms=sorted(v["rooms"])) for v in c["subjects"].values()]
        result.append(c)
    return result


# ---------------------------------------------------------------- grid for the HTML table
def build_grid(sessions, meta, division=None, teacher=None):
    """Rows of slots x days. A cell is None (empty), {'skip': True} (covered by a
    taller cell above it) or {'session': ..., 'rowspan': n}."""
    days, slots, brk = meta["days"], meta["slots"], meta["break_after"]
    chosen = [s for s in sessions
              if (division is None or s.division == division)
              and (teacher is None or s.teacher == teacher)]
    cells = {}
    for s in chosen:
        i = slots.index(s.start_slot)
        for k in range(s.duration):
            cells[(s.day, slots[i + k])] = {"skip": True} if k else {"session": s, "rowspan": s.duration}
    rows = [{"slot": slot, "break_after": brk == slot and slot != slots[-1],
             "cells": [cells.get((d, slot)) for d in days]} for slot in slots]
    return {"days": days, "rows": rows, "count": len(chosen)}


# ---------------------------------------------------------------- publishing
@dataclass
class PublishResult:
    ok: bool
    error: str = ""
    version: int = 0
    sessions: int = 0
    expired: int = 0


def publish(db, config, seed=42):
    """Generate a clash-free timetable from `config` and replace the published one."""
    try:
        divs, rooms, days, slots, brk = load_config(config)
    except (ValueError, KeyError, TypeError, AttributeError) as err:
        return PublishResult(False, f"The configuration isn't valid: {err}")
    tt = Timetable(divs, rooms, days, slots, brk)
    complete = tt.generate(seed=seed)
    problems = find_conflicts(divs)
    if not complete or problems:
        missing = ", ".join(f"{d}: {s}" for d, s in tt.unscheduled[:6]) or "see the clashes"
        return PublishResult(False, "Couldn't fit every lecture without clashes "
                                    f"(unplaced: {missing}). Add rooms or slots, or reduce lectures per week.")

    records = []
    for d in divs:
        groups = {}
        for (day, slot), (subj, room) in d.schedule.items():
            g = groups.setdefault((subj.name, day), {"teacher": subj.teacher.name, "room": room.number,
                                                    "kind": subj.room_kind, "slots": []})
            g["slots"].append(slot)
        for (subject, day), g in groups.items():
            records.append((d.name, subject, g["teacher"], g["room"], g["kind"], day,
                            min(g["slots"]), len(g["slots"])))

    previous = get_meta(db)
    version = (previous["version"] if previous else 0) + 1
    stamp = now()
    with db:
        db.execute("DELETE FROM sessions")
        db.execute("DELETE FROM rooms")
        db.executemany("INSERT INTO rooms (name, kind) VALUES (?, ?)", [(r.number, r.kind) for r in rooms])
        db.executemany("INSERT INTO sessions (division, subject, teacher, room, kind, day, start_slot, duration)"
                       " VALUES (?,?,?,?,?,?,?,?)", records)
        meta = {"version": version, "days": json.dumps(days), "slots": json.dumps(slots),
                "break_after": json.dumps(brk), "published_at": stamp, "seed": seed,
                "config": config if isinstance(config, str) else json.dumps(config)}
        for k, v in meta.items():
            db.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (k, str(v)))
        expired = db.execute(
            "UPDATE change_requests SET status='expired', decided_at=?, "
            "admin_note='The timetable was regenerated. Please send a new request if you still need a change.' "
            "WHERE status = 'pending'", (stamp,)).rowcount
    return PublishResult(True, version=version, sessions=len(records), expired=expired)
