import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schedulomatic.moves import (RoomRec, SessionRec, available_moves, check_move,   # noqa: E402
                                 find_conflicts_in_sessions)

DAYS, SLOTS, BREAK = ["Mon", "Tue"], [1, 2, 3, 4], 2
ROOMS = [RoomRec("R1", "classroom"), RoomRec("R2", "classroom"), RoomRec("L1", "lab")]


def S(id, div, subject, teacher, room, day, start, dur=1, kind="classroom"):
    return SessionRec(id, div, subject, teacher, room, kind, day, start, dur)


def base():
    return [S(1, "A", "Maths", "T1", "R1", "Mon", 1),
            S(2, "A", "Sci", "T2", "R1", "Mon", 2),
            S(3, "B", "Maths", "T1", "R2", "Tue", 1),
            S(4, "A", "Lab", "T3", "L1", "Tue", 3, 2, "lab")]


def move(sessions, sid, day, slot):
    return check_move(sessions, ROOMS, DAYS, SLOTS, BREAK, sid, day, slot)


class CheckMoveTests(unittest.TestCase):
    def test_current_slot_is_not_a_move(self):
        self.assertFalse(move(base(), 1, "Mon", 1).ok)

    def test_class_already_busy(self):
        r = move(base(), 1, "Mon", 2)
        self.assertFalse(r.ok)
        self.assertIn("A already has Sci", r.reason)

    def test_teacher_already_busy_with_another_class(self):
        r = move(base(), 1, "Tue", 1)
        self.assertFalse(r.ok)
        self.assertIn("T1", r.reason)

    def test_free_slot_keeps_the_same_room(self):
        r = move(base(), 1, "Tue", 2)
        self.assertEqual((r.ok, r.room), (True, "R1"))

    def test_falls_back_to_another_room_of_the_same_kind(self):
        sessions = base() + [S(5, "C", "Art", "T9", "R1", "Tue", 2)]
        r = move(sessions, 1, "Tue", 2)
        self.assertEqual((r.ok, r.room), (True, "R2"))

    def test_fails_when_every_room_is_taken(self):
        sessions = base() + [S(5, "C", "Art", "T9", "R1", "Tue", 2), S(6, "D", "Art", "T8", "R2", "Tue", 2)]
        r = move(sessions, 1, "Tue", 2)
        self.assertFalse(r.ok)
        self.assertIn("room", r.reason)

    def test_same_subject_twice_a_day_is_refused(self):
        sessions = base() + [S(5, "A", "Maths", "T7", "R2", "Tue", 4)]
        r = move(sessions, 1, "Tue", 2)
        self.assertFalse(r.ok)
        self.assertIn("already scheduled", r.reason)

    def test_long_sessions_cannot_cross_the_break_or_run_off_the_day(self):
        self.assertIn("lunch break", move(base(), 4, "Mon", 2).reason)
        self.assertIn("Not enough slots", move(base(), 4, "Tue", 4).reason)

    def test_lab_moves_only_to_lab_rooms(self):
        r = move(base(), 4, "Mon", 3)
        self.assertEqual((r.ok, r.room), (True, "L1"))

    def test_lab_blocked_when_the_only_lab_is_busy(self):
        sessions = base() + [S(5, "B", "Lab2", "T5", "L1", "Mon", 3, 2, "lab")]
        self.assertFalse(move(sessions, 4, "Mon", 3).ok)

    def test_unknown_inputs(self):
        self.assertFalse(move(base(), 99, "Mon", 1).ok)
        self.assertFalse(move(base(), 1, "Sun", 1).ok)
        self.assertFalse(move(base(), 1, "Mon", 9).ok)


class AvailableMovesTests(unittest.TestCase):
    def test_lists_only_valid_moves(self):
        options = available_moves(base(), ROOMS, DAYS, SLOTS, BREAK, 1)
        self.assertIn(("Tue", 2, "R1"), options)
        self.assertNotIn(("Mon", 2, "R1"), [(d, s, r) for d, s, r in options])
        self.assertNotIn(("Mon", 1), [(d, s) for d, s, _ in options])
        for day, slot, room in options:
            self.assertTrue(move(base(), 1, day, slot).ok)


class IntegrityTests(unittest.TestCase):
    def test_clean_timetable(self):
        self.assertEqual(find_conflicts_in_sessions(base(), SLOTS), [])

    def test_detects_double_booked_teacher_room_and_class(self):
        bad = base() + [S(5, "C", "Art", "T1", "R1", "Mon", 1)]          # T1 and R1 at Mon 1
        problems = find_conflicts_in_sessions(bad, SLOTS)
        self.assertTrue(any("teacher T1" in p for p in problems))
        self.assertTrue(any("room R1" in p for p in problems))
        bad2 = base() + [S(6, "A", "Art", "T8", "R2", "Mon", 1)]         # class A twice
        self.assertTrue(any("division A" in p for p in find_conflicts_in_sessions(bad2, SLOTS)))


if __name__ == "__main__":
    unittest.main()
