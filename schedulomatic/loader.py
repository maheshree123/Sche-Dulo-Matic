"""Load and validate a timetable configuration from JSON."""
import json

from .models import Teacher, Room, LabRoom, Subject, Division


def load_config(source):
    """`source` may be a path to a JSON file or an already-parsed dict.

    Returns (divisions, rooms, days, slots, break_after).
    """
    if isinstance(source, dict):
        cfg = source
    else:
        with open(source, encoding="utf-8") as f:
            cfg = json.load(f)

    days = cfg.get("days") or ["Mon", "Tue", "Wed", "Thu", "Fri"]
    slots = cfg.get("slots") or [1, 2, 3, 4, 5, 6]
    break_after = cfg.get("break_after")

    rooms = []
    for r in cfg.get("rooms", []):
        rooms.append(LabRoom(r["number"]) if r.get("kind") == "lab" else Room(r["number"]))
    if not rooms:
        raise ValueError("Config needs at least one room.")

    teachers = {}                       # create each Teacher once, share the object
    divisions = []
    for d in cfg.get("divisions", []):
        subjects = []
        for s in d.get("subjects", []):
            teacher = teachers.setdefault(s["teacher"], Teacher(s["teacher"]))
            subj = Subject(s["name"], teacher, int(s["lectures_per_week"]),
                           needs_lab=bool(s.get("needs_lab", False)),
                           duration=s.get("duration"))
            if subj.lectures_per_week > len(days):
                raise ValueError(f"{subj.name}: {subj.lectures_per_week} sessions/week but only "
                                 f"{len(days)} days (a subject is placed once per day).")
            if subj.room_kind == "lab" and not any(r.kind == "lab" for r in rooms):
                raise ValueError(f"{subj.name} needs a lab but no lab room is defined.")
            subjects.append(subj)
        divisions.append(Division(d["name"], subjects))
    if not divisions:
        raise ValueError("Config needs at least one division.")
    return divisions, rooms, days, slots, break_after
