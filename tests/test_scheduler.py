import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schedulomatic import Timetable, find_conflicts, load_config   # noqa: E402

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "data", "sample.json")


def tiny_config(**over):
    cfg = {
        "days": ["Mon", "Tue"], "slots": [1, 2, 3, 4], "break_after": 2,
        "rooms": [{"number": "R1", "kind": "classroom"}, {"number": "L1", "kind": "lab"}],
        "divisions": [{"name": "A", "subjects": [
            {"name": "Maths", "teacher": "T1", "lectures_per_week": 2},
            {"name": "Lab", "teacher": "T2", "lectures_per_week": 1, "needs_lab": True}]}],
    }
    cfg.update(over)
    return cfg


class SchedulerTests(unittest.TestCase):
    def build(self, source):
        divisions, rooms, days, slots, brk = load_config(source)
        tt = Timetable(divisions, rooms, days, slots, brk)
        return tt, divisions

    def test_sample_is_fully_scheduled_without_conflicts(self):
        tt, divisions = self.build(SAMPLE)
        self.assertTrue(tt.generate())
        self.assertEqual(find_conflicts(divisions), [])
        self.assertEqual(tt.unscheduled, [])

    def test_every_lecture_is_placed_the_right_number_of_times(self):
        tt, divisions = self.build(SAMPLE)
        tt.generate()
        for d in divisions:
            for s in d.subjects:
                slots_used = sum(1 for (subj, _) in d.schedule.values() if subj is s)
                self.assertEqual(slots_used, s.lectures_per_week * s.duration)

    def test_labs_use_lab_rooms_and_two_consecutive_slots(self):
        tt, divisions = self.build(SAMPLE)
        tt.generate()
        for d in divisions:
            for (day, slot), (subj, room) in d.schedule.items():
                if subj.room_kind == "lab":
                    self.assertEqual(room.kind, "lab")
                    partner = [(day, slot - 1), (day, slot + 1)]
                    self.assertTrue(any(k in d.schedule and d.schedule[k][0] is subj
                                        for k in partner))

    def test_sessions_never_cross_the_break(self):
        tt, divisions = self.build(SAMPLE)       # break_after = 3
        tt.generate()
        for d in divisions:
            for day in tt.days:
                before = d.schedule.get((day, 3))
                after = d.schedule.get((day, 4))
                if before and after:
                    self.assertIsNot(before[0], after[0],
                                     "one session spans the break between slot 3 and 4")

    def test_same_seed_gives_same_result(self):
        grids = []
        for _ in range(2):
            tt, divisions = self.build(SAMPLE)
            tt.generate(seed=5)
            grids.append({d.name: sorted((k, v[0].name, v[1].number) for k, v in d.schedule.items())
                          for d in divisions})
        self.assertEqual(grids[0], grids[1])

    def test_impossible_demand_is_reported_not_hidden(self):
        cfg = tiny_config(slots=[1, 2], divisions=[{"name": "A", "subjects": [
            {"name": "Maths", "teacher": "T1", "lectures_per_week": 2},
            {"name": "Sci", "teacher": "T2", "lectures_per_week": 2},
            {"name": "Art", "teacher": "T3", "lectures_per_week": 2}]}])
        tt, divisions = self.build(cfg)       # 6 lectures but only 4 slots exist
        self.assertFalse(tt.generate(attempts=20))
        self.assertTrue(tt.unscheduled)
        self.assertEqual(find_conflicts(divisions), [])

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            load_config(tiny_config(rooms=[{"number": "R1", "kind": "classroom"}]))   # lab needed
        bad = tiny_config()
        bad["divisions"][0]["subjects"][0]["lectures_per_week"] = 9
        with self.assertRaises(ValueError):
            load_config(bad)

    def test_conflict_checker_catches_a_double_booking(self):
        tt, divisions = self.build(tiny_config())
        tt.generate()
        # force a clash: copy one booking onto another division with same teacher/room
        from schedulomatic import Division
        a = divisions[0]
        key, (subj, room) = next(iter(a.schedule.items()))
        clone = Division("B", [subj])
        clone.schedule[key] = (subj, room)
        self.assertTrue(find_conflicts([a, clone]))


if __name__ == "__main__":
    unittest.main()
