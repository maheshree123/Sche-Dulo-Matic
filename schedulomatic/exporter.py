"""Turn schedules into grids and CSV files."""
import csv
import os


def division_grid(division, days, slots):
    """Header + rows: one row per slot, one column per day."""
    rows = [["Slot"] + list(days)]
    for slot in slots:
        row = [slot]
        for day in days:
            entry = division.schedule.get((day, slot))
            row.append(f"{entry[0].name} ({entry[1].number})" if entry else "-")
        rows.append(row)
    return rows


def teacher_grid(timetable, teacher_name):
    view = timetable.teacher_view(teacher_name)
    rows = [["Slot"] + list(timetable.days)]
    for slot in timetable.slots:
        row = [slot]
        for day in timetable.days:
            e = view.get((day, slot))
            row.append(f"{e[1]} - {e[0]} ({e[2]})" if e else "-")
        rows.append(row)
    return rows


def grid_to_text(title, grid):
    widths = [max(len(str(r[i])) for r in grid) for i in range(len(grid[0]))]
    lines = [f"\n=== {title} ==="]
    for n, row in enumerate(grid):
        lines.append(" | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))
        if n == 0:
            lines.append("-+-".join("-" * w for w in widths))
    return "\n".join(lines)


def grid_to_csv(grid, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(grid)
