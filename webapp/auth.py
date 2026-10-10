"""Sign up (teachers), sign in and sign out."""
import re
import sqlite3

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import services
from .db import get_db

bp = Blueprint("auth", __name__)
DUMMY_HASH = generate_password_hash("not-a-real-password")      # makes unknown emails cost the same time
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("admin.dashboard" if g.user["role"] == "admin" else "teacher.dashboard"))
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("auth.index"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        correct = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password)
        if not (user and correct):
            flash("Incorrect email or password.", "error")
        elif user["status"] == "pending":
            flash("Your account is waiting for approval by the college. "
                  "You can sign in as soon as it is approved.", "info")
        elif user["status"] == "rejected":
            flash("This account request was not approved. Please contact the college office.", "error")
        else:
            session.clear()                                       # new session on login
            session["uid"] = user["id"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("auth.index"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(url_for("auth.index"))
    db = get_db()
    names = services.unclaimed_teachers(db)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        teacher_name = request.form.get("teacher_name", "")
        password, confirm = request.form.get("password", ""), request.form.get("confirm", "")
        error = None
        if not 2 <= len(name) <= 80:
            error = "Please enter your full name."
        elif not EMAIL_RE.match(email) or len(email) > 120:
            error = "Please enter a valid email address."
        elif teacher_name not in names:
            error = ("Please choose your name from the list. If it is missing or already taken, "
                     "contact the college office.")
        elif len(password) < 8:
            error = "Your password must be at least 8 characters long."
        elif password != confirm:
            error = "The two passwords don't match."
        elif db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            error = "That email is already registered. Try signing in instead."
        if error is None:
            try:
                with db:
                    db.execute("INSERT INTO users (name, email, password_hash, role, teacher_name, status, created_at)"
                               " VALUES (?, ?, ?, 'teacher', ?, 'pending', ?)",
                               (name, email, generate_password_hash(password), teacher_name, services.now()))
            except sqlite3.IntegrityError:
                error = "That teacher name was just claimed by someone else."
            else:
                flash("Account created! The college must approve it before you can sign in.", "success")
                return redirect(url_for("auth.login"))
        flash(error, "error")
    return render_template("auth/register.html", names=names, form=request.form)
