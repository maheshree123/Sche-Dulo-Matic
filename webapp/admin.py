"""Pages for the college / school office: publish the timetable, answer requests, approve teachers."""
import json
import os
import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from schedulomatic.moves import check_move, find_conflicts_in_sessions

from . import services
from .db import get_db
from .security import role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")
SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sample.json")


@bp.route("/")
@role_required("admin")
def dashboard():
    db = get_db()
    meta = services.get_meta(db)
    sessions = services.all_sessions(db)
    pending = db.execute("SELECT r.*, u.name AS who FROM change_requests r JOIN users u ON u.id = r.teacher_user_id "
                         "WHERE r.status = 'pending' ORDER BY r.id DESC LIMIT 5").fetchall()
    accounts = db.execute("SELECT * FROM users WHERE role = 'teacher' AND status = 'pending' "
                          "ORDER BY id LIMIT 5").fetchall()
    return render_template("admin/dashboard.html", meta=meta, pending=pending, accounts=accounts,
                           n_divisions=len(services.divisions(sessions)),
                           n_teachers=len(services.teachers(sessions)), n_lectures=len(sessions),
                           clashes=find_conflicts_in_sessions(sessions, meta["slots"]) if meta else [])


@bp.route("/timetable")
@role_required("admin")
def timetable():
    db = get_db()
    meta = services.get_meta(db)
    if not meta:
        return render_template("admin/timetable.html", meta=None)
    sessions = services.all_sessions(db)
    divs, tchs = services.divisions(sessions), services.teachers(sessions)
    teacher, division = request.args.get("teacher"), request.args.get("division")
    if teacher:
        if teacher not in tchs:
            abort(404)
        mode, current, grid = "teacher", teacher, services.build_grid(sessions, meta, teacher=teacher)
    else:
        division = division or divs[0]
        if division not in divs:
            abort(404)
        mode, current, grid = "division", division, services.build_grid(sessions, meta, division=division)
    return render_template("admin/timetable.html", meta=meta, divisions=divs, teachers=tchs, mode=mode,
                           current=current, grid=grid,
                           clashes=find_conflicts_in_sessions(sessions, meta["slots"]))


@bp.route("/timetable/publish", methods=("POST",))
@role_required("admin")
def publish():
    db = get_db()
    meta = services.get_meta(db)
    source = request.form.get("source", "current")
    seed = request.form.get("seed", type=int)
    if seed is None:
        seed = (meta["seed"] + 1) if meta else 42
    seed = max(0, min(seed, 1_000_000))
    config = None
    try:
        if source == "sample":
            with open(SAMPLE, encoding="utf-8") as f:
                config = json.load(f)
        elif source == "upload":
            upload = request.files.get("config")
            if upload is None or not upload.filename:
                raise ValueError("Please choose a JSON file to upload.")
            config = json.loads(upload.read().decode("utf-8"))
        else:
            if not meta:
                raise ValueError("There is no timetable yet. Load the sample or upload a configuration.")
            config = json.loads(meta["config"])
    except (ValueError, UnicodeDecodeError) as err:
        flash(f"Couldn't read the configuration: {err}", "error")
        return redirect(url_for("admin.timetable"))
    result = services.publish(db, config, seed)
    if result.ok:
        msg = f"Timetable v{result.version} published ({result.sessions} lectures)."
        if result.expired:
            msg += f" {result.expired} pending request(s) were closed because the timetable changed."
        flash(msg, "success")
    else:
        flash(result.error, "error")
    return redirect(url_for("admin.timetable"))


@bp.route("/requests")
@role_required("admin")
def requests_page():
    db = get_db()
    meta = services.get_meta(db)
    sessions, rooms = services.all_sessions(db), services.all_rooms(db)
    rows = db.execute("SELECT r.*, u.name AS who FROM change_requests r JOIN users u ON u.id = r.teacher_user_id "
                      "ORDER BY r.id DESC").fetchall()
    pending, history = [], []
    for r in rows:
        d = dict(r)
        if d["status"] == "pending":
            d["check"] = (check_move(sessions, rooms, meta["days"], meta["slots"], meta["break_after"],
                                     d["session_id"], d["to_day"], d["to_slot"]) if d["to_day"] else None)
            pending.append(d)
        elif len(history) < 30:
            history.append(d)
    return render_template("admin/requests.html", pending=pending, history=history)


@bp.route("/requests/<int:rid>/decide", methods=("POST",))
@role_required("admin")
def request_decide(rid):
    db = get_db()
    action = request.form.get("action")
    note = request.form.get("note", "").strip()[:300]
    if action not in ("approve", "reject"):
        abort(400)
    req = db.execute("SELECT * FROM change_requests WHERE id = ? AND status = 'pending'", (rid,)).fetchone()
    if req is None:
        flash("That request has already been handled.", "error")
        return redirect(url_for("admin.requests_page"))
    meta = services.get_meta(db)
    if action == "approve" and req["to_day"] is not None:
        res = check_move(services.all_sessions(db), services.all_rooms(db), meta["days"], meta["slots"],
                         meta["break_after"], req["session_id"], req["to_day"], req["to_slot"])
        if not res.ok:
            flash(f"This move can't be approved: {res.reason}", "error")
            return redirect(url_for("admin.requests_page"))
    with db:
        if action == "approve" and req["to_day"] is not None:
            db.execute("UPDATE sessions SET day = ?, start_slot = ?, room = ? WHERE id = ?",
                       (req["to_day"], req["to_slot"], res.room, req["session_id"]))
        db.execute("UPDATE change_requests SET status = ?, admin_note = ?, decided_at = ?, decided_by = ? "
                   "WHERE id = ? AND status = 'pending'",
                   ("approved" if action == "approve" else "rejected", note or None,
                    services.now(), g.user["id"], rid))
    flash("Request approved and the timetable was updated." if action == "approve" and req["to_day"]
          else "Request approved." if action == "approve" else "Request rejected.", "success")
    return redirect(url_for("admin.requests_page"))


@bp.route("/accounts")
@role_required("admin")
def accounts():
    rows = get_db().execute("SELECT * FROM users WHERE role = 'teacher' ORDER BY "
                            "CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, name").fetchall()
    return render_template("admin/accounts.html", rows=rows)


@bp.route("/accounts/<int:uid>/decide", methods=("POST",))
@role_required("admin")
def account_decide(uid):
    action = request.form.get("action")
    if action not in ("approve", "reject"):
        abort(400)
    db = get_db()
    try:
        with db:
            done = db.execute("UPDATE users SET status = ? WHERE id = ? AND role = 'teacher'",
                              ("approved" if action == "approve" else "rejected", uid)).rowcount
    except sqlite3.IntegrityError:
        flash("Another account already uses that teacher name.", "error")
        return redirect(url_for("admin.accounts"))
    flash("Account updated." if done else "Account not found.", "success" if done else "error")
    return redirect(url_for("admin.accounts"))
