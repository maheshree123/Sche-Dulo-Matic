import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from werkzeug.security import check_password_hash, generate_password_hash   # noqa: E402

from schedulomatic.moves import available_moves                              # noqa: E402
from webapp import create_app, services                                      # noqa: E402
from webapp.db import get_db                                                 # noqa: E402

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "data", "sample.json")
FAST = "pbkdf2:sha256:1000"          # fast hashes keep the tests quick


class WebTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-key", "INSTANCE_PATH": self.tmp.name})
        with self.app.app_context():
            db = get_db()
            with open(SAMPLE, encoding="utf-8") as f:
                self.assertTrue(services.publish(db, json.load(f), seed=42).ok)
            self.add("admin", "College Office", "office@x.test", "Office#123")
            self.add("teacher", "Prof. Sharma", "sharma@x.test", "Teacher#123", "Prof. Sharma")
            self.add("teacher", "Prof. Iyer", "iyer@x.test", "Teacher#123", "Prof. Iyer")
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    # ---- helpers ----
    def add(self, role, name, email, password, teacher_name=None, status="approved"):
        db = get_db()
        with db:
            db.execute("INSERT INTO users (name, email, password_hash, role, teacher_name, status, created_at)"
                       " VALUES (?,?,?,?,?,?,?)", (name, email, generate_password_hash(password, method=FAST),
                                                   role, teacher_name, status, services.now()))

    def token(self, client):
        with client.session_transaction() as s:
            s.setdefault("_csrf", "tok123")
            return s["_csrf"]

    def post(self, client, url, data=None, follow=False, **kw):
        data = dict(data or {})
        data["_csrf"] = self.token(client)
        return client.post(url, data=data, follow_redirects=follow, **kw)

    def login(self, email, password, client=None):
        client = client or self.client
        return self.post(client, "/login", {"email": email, "password": password}, follow=True)

    def new_client(self, email, password):
        c = self.app.test_client()
        self.login(email, password, c)
        return c

    def query(self, sql, *args):
        with self.app.app_context():
            return [dict(r) for r in get_db().execute(sql, args).fetchall()]

    def lecture_and_target(self, teacher="Prof. Sharma"):
        with self.app.app_context():
            db = get_db()
            sessions, meta = services.all_sessions(db), services.get_meta(db)
            for s in sessions:
                if s.teacher == teacher:
                    opts = available_moves(sessions, services.all_rooms(db), meta["days"], meta["slots"],
                                           meta["break_after"], s.id)
                    if opts:
                        return s, opts[0]
        self.fail("no movable lecture found")

    def send_request(self, client, session_id, target, reason="I have a meeting at that time."):
        return self.post(client, f"/teacher/requests/new?session={session_id}",
                         {"session": session_id, "target": target, "reason": reason}, follow=True)


class AuthTests(WebTestCase):
    def test_anonymous_users_are_sent_to_sign_in(self):
        for url in ("/teacher/", "/admin/", "/teacher/requests"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login", r.headers["Location"])

    def test_signing_in_and_out(self):
        r = self.login("sharma@x.test", "Teacher#123")
        self.assertIn(b"My weekly timetable", r.data)
        r = self.post(self.client, "/logout", follow=True)
        self.assertIn(b"signed out", r.data)
        self.assertEqual(self.client.get("/teacher/").status_code, 302)

    def test_logout_must_be_a_post(self):
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_wrong_password_and_unknown_email_look_identical(self):
        a = self.login("sharma@x.test", "wrong-password")
        b = self.login("nobody@x.test", "whatever123")
        self.assertIn(b"Incorrect email or password", a.data)
        self.assertIn(b"Incorrect email or password", b.data)

    def test_forms_without_a_csrf_token_are_rejected(self):
        r = self.client.post("/login", data={"email": "sharma@x.test", "password": "Teacher#123"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get("/teacher/").status_code, 302)       # nobody got in

    def test_security_headers(self):
        h = self.client.get("/login").headers
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])

    def test_roles_are_enforced(self):
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        admin = self.new_client("office@x.test", "Office#123")
        self.assertEqual(teacher.get("/admin/").status_code, 403)
        self.assertEqual(teacher.get("/admin/requests").status_code, 403)
        self.assertEqual(self.post(teacher, "/admin/timetable/publish", {"source": "sample"}).status_code, 403)
        self.assertEqual(admin.get("/teacher/").status_code, 403)

    def test_sign_up_waits_for_approval_then_works(self):
        with self.app.app_context():
            self.assertEqual(services.unclaimed_teachers(get_db())[0], "Prof. Deshmukh")
        r = self.post(self.client, "/register", {"name": "Dr Rao", "email": "Rao@X.test", "teacher_name": "Prof. Rao",
                                                 "password": "Secret#123", "confirm": "Secret#123"}, follow=True)
        self.assertIn(b"must approve", r.data)
        row = self.query("SELECT * FROM users WHERE email = 'rao@x.test'")[0]       # email is lower-cased
        self.assertEqual(row["status"], "pending")
        self.assertNotEqual(row["password_hash"], "Secret#123")
        self.assertTrue(check_password_hash(row["password_hash"], "Secret#123"))
        self.assertIn(b"waiting for approval", self.login("rao@x.test", "Secret#123").data)
        self.assertEqual(self.client.get("/teacher/").status_code, 302)
        admin = self.new_client("office@x.test", "Office#123")
        self.post(admin, f"/admin/accounts/{row['id']}/decide", {"action": "approve"})
        self.assertIn(b"My weekly timetable", self.login("rao@x.test", "Secret#123").data)

    def test_sign_up_validation(self):
        good = {"name": "Dr Rao", "email": "rao@x.test", "teacher_name": "Prof. Rao",
                "password": "Secret#123", "confirm": "Secret#123"}
        cases = [({"password": "short", "confirm": "short"}, b"at least 8"),
                 ({"confirm": "different#1"}, b"don&#39;t match"),
                 ({"email": "not-an-email"}, b"valid email"),
                 ({"teacher_name": "Prof. Nobody"}, b"choose your name"),
                 ({"teacher_name": "Prof. Sharma"}, b"choose your name"),          # already claimed
                 ({"email": "sharma@x.test"}, b"already registered")]
        for change, message in cases:
            r = self.post(self.client, "/register", {**good, **change}, follow=True)
            self.assertIn(message, r.data, change)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM users")[0]["n"], 3)

    def test_rejected_or_revoked_accounts_lose_access(self):
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.assertEqual(teacher.get("/teacher/").status_code, 200)
        uid = self.query("SELECT id FROM users WHERE email = 'sharma@x.test'")[0]["id"]
        admin = self.new_client("office@x.test", "Office#123")
        self.post(admin, f"/admin/accounts/{uid}/decide", {"action": "reject"})
        self.assertEqual(teacher.get("/teacher/").status_code, 302)               # session no longer valid
        self.assertIn(b"not approved", self.login("sharma@x.test", "Teacher#123", self.app.test_client()).data)


class TeacherPageTests(WebTestCase):
    def test_dashboard_shows_only_my_lectures(self):
        c = self.new_client("sharma@x.test", "Teacher#123")
        html = c.get("/teacher/").data.decode()
        self.assertEqual(html.count('class="chip"'), 8)
        self.assertNotIn("Prof. Iyer", html)
        self.assertIn("SE-A", html)

    def test_class_pages(self):
        c = self.new_client("sharma@x.test", "Teacher#123")
        r = c.get("/teacher/classes/SE-A")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Data Structures", r.data)                 # another teacher's lecture, view only
        self.assertIn(b"TE-A", c.get("/teacher/classes").data)    # listed under other classes
        self.assertEqual(c.get("/teacher/classes/NOPE").status_code, 404)


class RequestFlowTests(WebTestCase):
    def test_approved_request_moves_the_lecture(self):
        s, (day, slot, room) = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        r = self.send_request(teacher, s.id, f"{day}|{slot}")
        self.assertIn(b"sent to the college", r.data)
        admin = self.new_client("office@x.test", "Office#123")
        page = admin.get("/admin/requests").data.decode()
        self.assertIn("Prof. Sharma", page)
        self.assertIn("No clash", page)
        rid = self.query("SELECT id FROM change_requests")[0]["id"]
        r = self.post(admin, f"/admin/requests/{rid}/decide", {"action": "approve", "note": "Fine, go ahead."}, follow=True)
        self.assertIn(b"timetable was updated", r.data)
        moved = self.query("SELECT * FROM sessions WHERE id = ?", s.id)[0]
        self.assertEqual((moved["day"], moved["start_slot"], moved["room"]), (day, slot, room))
        mine = teacher.get("/teacher/requests").data.decode()
        self.assertIn("badge approved", mine)
        self.assertIn("Fine, go ahead.", mine)
        with self.app.app_context():                               # still clash-free after the move
            from schedulomatic.moves import find_conflicts_in_sessions
            db = get_db()
            self.assertEqual(find_conflicts_in_sessions(services.all_sessions(db), services.get_meta(db)["slots"]), [])

    def test_rejected_request_changes_nothing(self):
        s, (day, slot, _) = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.send_request(teacher, s.id, f"{day}|{slot}")
        admin = self.new_client("office@x.test", "Office#123")
        rid = self.query("SELECT id FROM change_requests")[0]["id"]
        self.post(admin, f"/admin/requests/{rid}/decide", {"action": "reject", "note": "Exam week."})
        same = self.query("SELECT * FROM sessions WHERE id = ?", s.id)[0]
        self.assertEqual((same["day"], same["start_slot"]), (s.day, s.start_slot))
        mine = teacher.get("/teacher/requests").data.decode()
        self.assertIn("badge rejected", mine)
        self.assertIn("Exam week.", mine)

    def test_approval_is_blocked_if_the_slot_was_taken_meanwhile(self):
        s, (day, slot, _) = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.send_request(teacher, s.id, f"{day}|{slot}")
        rid = self.query("SELECT id FROM change_requests")[0]["id"]
        with self.app.app_context():                               # someone else's lecture now occupies it
            db = get_db()
            with db:
                db.execute("INSERT INTO sessions (division, subject, teacher, room, kind, day, start_slot, duration)"
                           " VALUES (?, 'Blocker', 'Prof. Blocker', 'X9', 'classroom', ?, ?, 1)", (s.division, day, slot))
        admin = self.new_client("office@x.test", "Office#123")
        page = admin.get("/admin/requests").data.decode()
        self.assertIn("Can't be applied", page)
        r = self.post(admin, f"/admin/requests/{rid}/decide", {"action": "approve"}, follow=True)
        self.assertIn(b"can&#39;t be approved", r.data)
        self.assertEqual(self.query("SELECT status FROM change_requests")[0]["status"], "pending")
        self.assertEqual(self.query("SELECT day FROM sessions WHERE id = ?", s.id)[0]["day"], s.day)

    def test_cannot_request_changes_for_someone_elses_lecture(self):
        with self.app.app_context():
            theirs = next(x for x in services.all_sessions(get_db()) if x.teacher == "Prof. Iyer")
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.assertEqual(teacher.get(f"/teacher/requests/new?session={theirs.id}").status_code, 404)
        self.assertEqual(self.send_request(teacher, theirs.id, "none").status_code, 404)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM change_requests")[0]["n"], 0)

    def test_tampered_or_invalid_form_values_are_rejected(self):
        s, _ = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        for target in (f"{s.day}|{s.start_slot}", "Mon|99", "Sun|1", "garbage"):          # current slot / nonsense
            r = self.send_request(teacher, s.id, target)
            self.assertIn(b"flash error", r.data, target)
        r = self.send_request(teacher, s.id, "none", reason="no")
        self.assertIn(b"explain your reason", r.data)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM change_requests")[0]["n"], 0)

    def test_one_pending_request_per_lecture_and_cancel(self):
        s, (day, slot, _) = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.send_request(teacher, s.id, f"{day}|{slot}")
        again = self.send_request(teacher, s.id, "none")
        self.assertIn(b"already have a pending request", again.data)
        rid = self.query("SELECT id FROM change_requests")[0]["id"]
        other = self.new_client("iyer@x.test", "Teacher#123")
        self.post(other, f"/teacher/requests/{rid}/cancel")                      # not theirs
        self.assertEqual(self.query("SELECT status FROM change_requests")[0]["status"], "pending")
        self.post(teacher, f"/teacher/requests/{rid}/cancel")
        self.assertEqual(self.query("SELECT status FROM change_requests")[0]["status"], "cancelled")

    def test_general_request_is_acknowledged_without_changing_the_timetable(self):
        s, _ = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.send_request(teacher, s.id, "none", reason="Please swap with a colleague if possible.")
        admin = self.new_client("office@x.test", "Office#123")
        self.assertIn("Acknowledge", admin.get("/admin/requests").data.decode())
        rid = self.query("SELECT id FROM change_requests")[0]["id"]
        self.post(admin, f"/admin/requests/{rid}/decide", {"action": "approve"})
        self.assertEqual(self.query("SELECT status FROM change_requests")[0]["status"], "approved")
        self.assertEqual(self.query("SELECT day FROM sessions WHERE id = ?", s.id)[0]["day"], s.day)

    def test_a_request_is_handled_only_once(self):
        s, (day, slot, _) = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.send_request(teacher, s.id, f"{day}|{slot}")
        admin = self.new_client("office@x.test", "Office#123")
        rid = self.query("SELECT id FROM change_requests")[0]["id"]
        self.post(admin, f"/admin/requests/{rid}/decide", {"action": "approve"})
        r = self.post(admin, f"/admin/requests/{rid}/decide", {"action": "reject"}, follow=True)
        self.assertIn(b"already been handled", r.data)
        self.assertEqual(self.query("SELECT status FROM change_requests")[0]["status"], "approved")

    def test_messages_are_escaped_not_executed(self):
        s, _ = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.send_request(teacher, s.id, "none", reason="<script>alert('x')</script> please")
        admin = self.new_client("office@x.test", "Office#123")
        page = admin.get("/admin/requests").data.decode()
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)


class PublishTests(WebTestCase):
    def upload(self, client, payload):
        data = {"source": "upload", "config": (io.BytesIO(payload), "config.json"), "_csrf": self.token(client)}
        return client.post("/admin/timetable/publish", data=data, follow_redirects=True)

    def test_regenerating_closes_pending_requests_and_bumps_the_version(self):
        s, (day, slot, _) = self.lecture_and_target()
        teacher = self.new_client("sharma@x.test", "Teacher#123")
        self.send_request(teacher, s.id, f"{day}|{slot}")
        admin = self.new_client("office@x.test", "Office#123")
        r = self.post(admin, "/admin/timetable/publish", {"source": "current", "seed": "7"}, follow=True)
        self.assertIn(b"v2 published", r.data)
        self.assertIn(b"closed", r.data)
        row = self.query("SELECT status, admin_note FROM change_requests")[0]
        self.assertEqual(row["status"], "expired")
        self.assertIn("regenerated", row["admin_note"])

    def test_invalid_uploads_leave_the_live_timetable_alone(self):
        admin = self.new_client("office@x.test", "Office#123")
        before = self.query("SELECT COUNT(*) AS n FROM sessions")[0]["n"]
        self.assertIn(b"Couldn", self.upload(admin, b"this is not json").data)
        self.assertIn(b"isn&#39;t valid", self.upload(admin, b'{"rooms": []}').data)
        impossible = {"days": ["Mon"], "slots": [1], "rooms": [{"number": "R1"}],
                      "divisions": [{"name": "A", "subjects": [
                          {"name": "X", "teacher": "T1", "lectures_per_week": 1},
                          {"name": "Y", "teacher": "T2", "lectures_per_week": 1}]}]}
        self.assertIn(b"fit every lecture", self.upload(admin, json.dumps(impossible).encode()).data)
        self.assertEqual(self.query("SELECT COUNT(*) AS n FROM sessions")[0]["n"], before)
        self.assertEqual(services_version(self), 1)

    def test_a_valid_upload_replaces_the_timetable(self):
        admin = self.new_client("office@x.test", "Office#123")
        tiny = {"days": ["Mon", "Tue"], "slots": [1, 2, 3], "rooms": [{"number": "R1"}],
                "divisions": [{"name": "Z-1", "subjects": [{"name": "Art", "teacher": "Prof. Zed", "lectures_per_week": 2}]}]}
        self.assertIn(b"v2 published", self.upload(admin, json.dumps(tiny).encode()).data)
        self.assertEqual({r["division"] for r in self.query("SELECT division FROM sessions")}, {"Z-1"})
        self.assertIn(b"Prof. Zed", admin.get("/admin/timetable?teacher=Prof.+Zed").data)

    def test_admin_timetable_views_and_404s(self):
        admin = self.new_client("office@x.test", "Office#123")
        self.assertIn(b"no clashes", admin.get("/admin/timetable").data)
        self.assertEqual(admin.get("/admin/timetable?division=NOPE").status_code, 404)
        self.assertEqual(admin.get("/admin/timetable?teacher=NOPE").status_code, 404)


def services_version(case):
    with case.app.app_context():
        return services.get_meta(get_db())["version"]


if __name__ == "__main__":
    unittest.main()
