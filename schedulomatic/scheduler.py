"""The scheduling engine.

Approach: greedy placement + randomized restarts.
  * Longest sessions (labs) are placed first because they are hardest to fit.
  * For each session we try the least-loaded days first so lectures spread out.
  * If a run leaves lectures unplaced, we retry with a different random order
    and finally keep the best attempt.
"""
import random


class Timetable:
    def __init__(self, divisions, rooms, days, slots, break_after=None):
        self.divisions = divisions
        self.rooms = rooms
        self.days = days
        self.slots = slots
        self.break_after = break_after      # a session may not span the lunch break
        self.teachers = []
        for d in divisions:
            for s in d.subjects:
                if s.teacher not in self.teachers:
                    self.teachers.append(s.teacher)
        self.unscheduled = []

    # ---------- state handling ----------
    def reset(self):
        for t in self.teachers:
            t.busy.clear()
        for r in self.rooms:
            r.busy.clear()
        for d in self.divisions:
            d.busy.clear()
            d.schedule.clear()
        self.unscheduled = []

    # ---------- helpers ----------
    def _blocks(self, duration):
        """Every run of `duration` consecutive slots that doesn't cross the break."""
        for i in range(len(self.slots) - duration + 1):
            block = self.slots[i:i + duration]
            if self.break_after is not None and any(s == self.break_after for s in block[:-1]):
                continue
            yield block

    @staticmethod
    def _load(division, day):
        return sum(1 for (d, _) in division.busy if d == day)

    @staticmethod
    def _subject_on_day(division, subject, day):
        return any(d == day and subj is subject
                   for (d, _), (subj, _) in division.schedule.items())

    def _find_room(self, subject, keys):
        for room in self.rooms:
            if room.kind == subject.room_kind and all(k not in room.busy for k in keys):
                return room
        return None

    # ---------- placement ----------
    def try_place(self, division, subject, days):
        """Find the first valid (day, slots, room) for one session and book it."""
        for day in days:
            if self._subject_on_day(division, subject, day):          # rule 4
                continue
            for block in self._blocks(subject.duration):
                keys = [(day, s) for s in block]
                if any(k in division.busy for k in keys):             # rule 3
                    continue
                if any(k in subject.teacher.busy for k in keys):      # rule 1
                    continue
                room = self._find_room(subject, keys)                 # rules 2 and 5
                if room is None:
                    continue
                for k in keys:                                        # book it
                    division.busy.add(k)
                    subject.teacher.busy.add(k)
                    room.busy.add(k)
                    division.schedule[k] = (subject, room)
                return True
        return False

    def _run_attempt(self, seed):
        rng = random.Random(seed)
        self.reset()
        jobs = [(d, s) for d in self.divisions for s in d.subjects
                for _ in range(s.lectures_per_week)]
        rng.shuffle(jobs)
        jobs.sort(key=lambda j: -j[1].duration)       # labs first (stable sort)
        for division, subject in jobs:
            days = sorted(self.days, key=lambda d: (self._load(division, d), rng.random()))
            if not self.try_place(division, subject, days):
                self.unscheduled.append((division.name, subject.name))
        return len(self.unscheduled)

    def generate(self, attempts=200, seed=42):
        """Build the timetable. Returns True if every lecture was placed."""
        best_seed, best_missing = seed, None
        for i in range(attempts):
            missing = self._run_attempt(seed + i)
            if best_missing is None or missing < best_missing:
                best_seed, best_missing = seed + i, missing
            if missing == 0:
                return True
        self._run_attempt(best_seed)                  # restore the best attempt
        return best_missing == 0

    # ---------- views ----------
    def teacher_view(self, teacher_name):
        """{(day, slot): (division, subject, room)} for one teacher."""
        view = {}
        for d in self.divisions:
            for key, (subject, room) in d.schedule.items():
                if subject.teacher.name == teacher_name:
                    view[key] = (d.name, subject.name, room.number)
        return view


def find_conflicts(divisions):
    """Independent safety check: returns a list of human-readable clashes (empty = valid)."""
    seen, problems = {}, []
    for d in divisions:
        for key, (subject, room) in d.schedule.items():
            if room.kind != subject.room_kind:
                problems.append(f"{subject.name} in wrong room type {room.number}")
            for label, owner in (("teacher", subject.teacher.name), ("room", room.number)):
                tag = (label, owner, key)
                if tag in seen:
                    problems.append(f"{label} {owner} double-booked at {key}: "
                                    f"{seen[tag]} and {d.name}")
                else:
                    seen[tag] = d.name
    return problems
