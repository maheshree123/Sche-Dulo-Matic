"""Command-line helper for the web app.

    python manage.py create-admin     create the college/school office account
    python manage.py demo             fill a fresh database with DEMO data and accounts
    python manage.py run              start the website at http://127.0.0.1:5000
"""
import argparse
import getpass
import json
import os
import sys

from werkzeug.security import generate_password_hash

from webapp import create_app, services
from webapp.db import get_db

DEMO_PASSWORD_ADMIN = "Admin@1234"
DEMO_PASSWORD_TEACHER = "Teacher@1234"


def add_user(db, name, email, password, role, teacher_name=None, status="approved"):
    with db:
        db.execute("INSERT INTO users (name, email, password_hash, role, teacher_name, status, created_at)"
                   " VALUES (?,?,?,?,?,?,?)",
                   (name, email.lower(), generate_password_hash(password), role, teacher_name, status,
                    services.now()))


def create_admin(app, args):
    name = args.name or input("Name of the office / administrator: ").strip()
    email = args.email or input("Email: ").strip()
    password = getpass.getpass("Password (min 8 characters): ")
    if len(password) < 8 or password != getpass.getpass("Repeat password: "):
        print("Passwords must match and be at least 8 characters.")
        return 1
    with app.app_context():
        add_user(get_db(), name, email, password, "admin")
    print(f"Admin account created for {email}.")
    return 0


def demo(app, args):
    from schedulomatic.moves import available_moves
    sample = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sample.json")
    with app.app_context():
        db = get_db()
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            print("The database already has users. Delete instance/schedulomatic.db to start over.")
            return 1
        with open(sample, encoding="utf-8") as f:
            result = services.publish(db, json.load(f), seed=42)
        add_user(db, "College Office", "admin@college.test", DEMO_PASSWORD_ADMIN, "admin")
        teachers = [("Prof. Sharma", "sharma@college.test", "approved"),
                    ("Prof. Iyer", "iyer@college.test", "approved"),
                    ("Prof. Khan", "khan@college.test", "approved"),
                    ("Prof. Rao", "rao@college.test", "pending")]
        for name, email, status in teachers:
            add_user(db, name, email, DEMO_PASSWORD_TEACHER, "teacher", name, status)
        # one example request so the office inbox isn't empty
        sessions, meta = services.all_sessions(db), services.get_meta(db)
        mine = next(s for s in sessions if s.teacher == "Prof. Sharma")
        options = available_moves(sessions, services.all_rooms(db), meta["days"], meta["slots"],
                                  meta["break_after"], mine.id)
        uid = db.execute("SELECT id FROM users WHERE email = 'sharma@college.test'").fetchone()["id"]
        if options:
            day, slot, _ = options[0]
            with db:
                db.execute("INSERT INTO change_requests (teacher_user_id, session_id, version, division, subject,"
                           " from_day, from_slot, to_day, to_slot, reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (uid, mine.id, meta["version"], mine.division, mine.subject, mine.day, mine.start_slot,
                            day, slot, "I have a department meeting at that time.", services.now()))
    print(f"DEMO data created: timetable v{result.version} with {result.sessions} lectures.\n"
          f"  Office login : admin@college.test / {DEMO_PASSWORD_ADMIN}\n"
          f"  Teacher login: sharma@college.test / {DEMO_PASSWORD_TEACHER}  (also iyer@ and khan@college.test)\n"
          f"  rao@college.test is waiting for approval.\n"
          "These are demo credentials only. Never use them on a real site.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--name")
    a.add_argument("--email")
    sub.add_parser("demo")
    r = sub.add_parser("run")
    r.add_argument("--host", default="127.0.0.1")
    r.add_argument("--port", type=int, default=5000)
    args = p.parse_args()
    app = create_app()
    if args.cmd == "create-admin":
        return create_admin(app, args)
    if args.cmd == "demo":
        return demo(app, args)
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
