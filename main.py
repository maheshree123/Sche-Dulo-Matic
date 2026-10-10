"""Command-line entry point.

Examples:
    python main.py
    python main.py --input data/sample.json --out output --seed 7
    python main.py --teacher "Prof. Sharma"
"""
import argparse
import os
import sys

from schedulomatic import Timetable, find_conflicts, load_config
from schedulomatic.exporter import (division_grid, grid_to_csv, grid_to_text,
                                    teacher_grid)


def main():
    p = argparse.ArgumentParser(description="Sche-Dulo-Matic timetable generator")
    p.add_argument("--input", default="data/sample.json", help="JSON config file")
    p.add_argument("--out", default="output", help="folder for CSV files")
    p.add_argument("--seed", type=int, default=42, help="random seed (same seed = same result)")
    p.add_argument("--teacher", help="also print one teacher's timetable")
    args = p.parse_args()

    divisions, rooms, days, slots, break_after = load_config(args.input)
    tt = Timetable(divisions, rooms, days, slots, break_after)
    ok = tt.generate(seed=args.seed)

    for d in divisions:
        grid = division_grid(d, days, slots)
        print(grid_to_text(f"Timetable: {d.name}", grid))
        grid_to_csv(grid, os.path.join(args.out, f"{d.name}.csv"))

    for t in tt.teachers:
        grid_to_csv(teacher_grid(tt, t.name),
                    os.path.join(args.out, f"teacher_{t.name.replace(' ', '_').replace('.', '')}.csv"))
    if args.teacher:
        print(grid_to_text(f"Teacher: {args.teacher}", teacher_grid(tt, args.teacher)))

    problems = find_conflicts(divisions)
    print()
    if ok and not problems:
        print(f"All lectures scheduled with no clashes. CSV files saved in '{args.out}/'.")
        return 0
    if tt.unscheduled:
        print("Could not place:", tt.unscheduled)
    for line in problems:
        print("CONFLICT:", line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
