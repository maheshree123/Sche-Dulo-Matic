"""Rules for moving ONE already-scheduled session to a different slot.

Used when a teacher asks for a change: the same constraints as the generator
are re-checked against the published timetable, so we never offer or approve
a move that would create a clash.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionRec:
    id: int
    division: str
    subject: str
    teacher: str
    room: str
    kind: str               # "classroom" or "lab"
    day: str
    start_slot: int
    duration: int


@dataclass(frozen=True)
class RoomRec:
    name: str
    kind: str


@dataclass(frozen=True)
class MoveResult:
    ok: bool
    reason: str = ""
    room: str = None        # the room the moved session would use


def occupied(session, slots):
    """The (day, slot) cells a session covers."""
    i = slots.index(session.start_slot)
    return {(session.day, s) for s in slots[i:i + session.duration]}


def check_move(sessions, rooms, days, slots, break_after, session_id, day, start_slot):
    me = next((s for s in sessions if s.id == session_id), None)
    if me is None:
        return MoveResult(False, "That session no longer exists.")
    if day not in days or start_slot not in slots:
        return MoveResult(False, "That day or slot doesn't exist.")
    if (day, start_slot) == (me.day, me.start_slot):
        return MoveResult(False, "That is the current slot.")
    i = slots.index(start_slot)
    block = slots[i:i + me.duration]
    if len(block) < me.duration:
        return MoveResult(False, "Not enough slots left that day for this session.")
    if break_after is not None and break_after in block[:-1]:
        return MoveResult(False, "The session would run across the lunch break.")

    cells = {(day, s) for s in block}
    others = [s for s in sessions if s.id != me.id]
    for o in others:
        clash = cells & occupied(o, slots)
        if clash and o.division == me.division:
            return MoveResult(False, f"{me.division} already has {o.subject} at that time.")
        if clash and o.teacher == me.teacher:
            return MoveResult(False, f"{me.teacher} is already teaching {o.division} at that time.")
        if o.division == me.division and o.subject == me.subject and o.day == day:
            return MoveResult(False, f"{me.subject} is already scheduled for {me.division} that day.")

    candidates = [me.room] + [r.name for r in rooms if r.kind == me.kind and r.name != me.room]
    for room in candidates:
        if not any(o.room == room and cells & occupied(o, slots) for o in others):
            return MoveResult(True, "", room)
    return MoveResult(False, "No suitable room is free at that time.")


def available_moves(sessions, rooms, days, slots, break_after, session_id):
    """Every (day, start_slot, room) the session could legally move to."""
    options = []
    for day in days:
        for slot in slots:
            r = check_move(sessions, rooms, days, slots, break_after, session_id, day, slot)
            if r.ok:
                options.append((day, slot, r.room))
    return options


def find_conflicts_in_sessions(sessions, slots):
    """Integrity check over stored sessions: returns a list of clashes (empty = clean)."""
    seen, problems = {}, []
    for s in sessions:
        for cell in occupied(s, slots):
            for label, owner in (("teacher", s.teacher), ("room", s.room), ("division", s.division)):
                tag = (label, owner, cell)
                if tag in seen:
                    problems.append(f"{label} {owner} is double-booked at {cell[0]} slot {cell[1]}")
                else:
                    seen[tag] = s.id
    return problems
