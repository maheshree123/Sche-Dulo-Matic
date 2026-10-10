"""Core data models (the "blueprints") for Sche-Dulo-Matic."""


class Teacher:
    def __init__(self, name):
        self.name = name
        self.busy = set()          # {(day, slot), ...} when this teacher is taken

    def __repr__(self):
        return f"Teacher({self.name!r})"


class Room:
    kind = "classroom"

    def __init__(self, number):
        self.number = number
        self.busy = set()

    def __repr__(self):
        return f"{type(self).__name__}({self.number!r})"


class LabRoom(Room):               # INHERITANCE: a LabRoom is a Room
    kind = "lab"


class Subject:
    """A subject taught to one division by one teacher.

    lectures_per_week : how many sessions are needed each week
    needs_lab         : must be placed in a LabRoom
    duration          : consecutive slots per session (labs default to 2)
    """

    def __init__(self, name, teacher, lectures_per_week, needs_lab=False, duration=None):
        self.name = name
        self.teacher = teacher
        self.lectures_per_week = lectures_per_week
        self.room_kind = "lab" if needs_lab else "classroom"
        self.duration = duration if duration else (2 if needs_lab else 1)

    def __repr__(self):
        return f"Subject({self.name!r})"


class Division:
    """A group of students (e.g. SE-A) who attend lectures together."""

    def __init__(self, name, subjects):
        self.name = name
        self.subjects = subjects
        self.busy = set()
        self.schedule = {}         # (day, slot) -> (subject, room)

    def __repr__(self):
        return f"Division({self.name!r})"
