"""Pages for teachers: their timetable, their classes, change requests."""
from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from schedulomatic.moves import available_moves

from . import services
from .db import get_db
from .security import role_required

bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def greeting():
    hour = datetime.now().hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"


@bp.route("/")
@role_required("teacher")
def dashboard():
    db, me = get_db(), g.user["teacher_name"]
    meta = services.get_meta(db)
    ctx = {"meta": meta, "teacher": me, "greeting": greeting()}
    if meta:
        sessions = services.all_sessions(db)
        mine = [s for s in sessions if s.teacher == me]
        today = datetime.now().strftime("%a")
        ctx.update(grid=services.build_grid(sessions, meta, teacher=me),
                   classes=services.classes_taught(sessions, me), today=today,
                   today_sessions=sorted((s for s in mine if s.day == today), key=lambda s: s.start_slot),
                   lectures=len(mine), periods=sum(s.duration for s in mine))
    ctx["recent"] = db.execute("SELECT * FROM change_requests WHERE teacher_user_id = ? "
                               "ORDER BY id DESC LIMIT 4", (g.user["id"],)).fetchall()
    ctx["pending"] = db.execute("SELECT COUNT(*) FROM change_requests WHERE teacher_user_id = ? "
                                "AND status = 'pending'", (g.user["id"],)).fetchone()[0]
    return render_template("teacher/dashboard.html", **ctx)


@bp.route("/classes")
@bp.route("/classes/<division>")
@role_required("teacher")
def classes(division=None):
    db, me = get_db(), g.user["teacher_name"]
    meta = services.get_meta(db)
    if not meta:
        return render_template("teacher/classes.html", meta=None)
    sessions = services.all_sessions(db)
    mine = services.classes_taught(sessions, me)
    mine_names = [c["division"] for c in mine]
    others = [d for d in services.divisions(sessions) if d not in mine_names]
    if division is None:
        division = (mine_names or others or [None])[0]
    if division not in mine_names + others:
        abort(404)
    return render_template("teacher/classes.html", meta=meta, teacher=me, mine=mine, mine_names=mine_names,
                           others=others, division=division,
                           grid=services.build_grid(sessions, meta, division=division),
                           info=next((c for c in mine if c["division"] == division), None))


@bp.route("/requests")
@role_required("teacher")
def requests_list():
    rows = get_db().execute("SELECT * FROM change_requests WHERE teacher_user_id = ? ORDER BY id DESC",
                            (g.user["id"],)).fetchall()
    return render_template("teacher/requests.html", rows=rows)


@bp.route("/requests/new", methods=("GET", "POST"))
@role_required("teacher")
def request_new():
    db, me = get_db(), g.user["teacher_name"]
    meta = services.get_meta(db)
    sid = request.values.get("session", type=int)
    sessions = services.all_sessions(db)
    target = next((s for s in sessions if s.id == sid), None)
    if meta is None or target is None or target.teacher != me:
        abort(404)                                           # not your lecture (or it doesn't exist)
    options = available_moves(sessions, services.all_rooms(db), meta["days"], meta["slots"],
                              meta["break_after"], target.id)

    if request.method == "POST":
        choice = request.form.get("target", "")
        reason = request.form.get("reason", "").strip()
        to_day = to_slot = None
        error = None
        if choice != "none":
            try:
                to_day, slot_text = choice.split("|")
                to_slot = int(slot_text)
            except ValueError:
                error = "Please choose one of the listed time slots."
            else:
                if (to_day, to_slot) not in {(d, s) for d, s, _ in options}:
                    error = "That slot isn't available any more. Please pick another."
        if error is None and not 5 <= len(reason) <= 500:
            error = "Please explain your reason (5 to 500 characters)."
        if error is None and db.execute("SELECT 1 FROM change_requests WHERE session_id = ? AND version = ? "
                                        "AND status = 'pending'", (target.id, meta["version"])).fetchone():
            error = "You already have a pending request for this lecture."
        if error is None:
            with db:
                db.execute("INSERT INTO change_requests (teacher_user_id, session_id, version, division, subject,"
                           " from_day, from_slot, to_day, to_slot, reason, created_at) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (g.user["id"], target.id, meta["version"], target.division, target.subject,
                            target.day, target.start_slot, to_day, to_slot, reason, services.now()))
            flash("Your request was sent to the college. You'll see the decision here.", "success")
            return redirect(url_for("teacher.requests_list"))
        flash(error, "error")
    return render_template("teacher/request_new.html", s=target, options=options, form=request.form)


@bp.route("/requests/<int:rid>/cancel", methods=("POST",))
@role_required("teacher")
def request_cancel(rid):
    db = get_db()
    with db:
        done = db.execute("UPDATE change_requests SET status = 'cancelled', decided_at = ? "
                          "WHERE id = ? AND teacher_user_id = ? AND status = 'pending'",
                          (services.now(), rid, g.user["id"])).rowcount
    flash("Request cancelled." if done else "That request can't be cancelled.", "info" if done else "error")
    return redirect(url_for("teacher.requests_list"))
