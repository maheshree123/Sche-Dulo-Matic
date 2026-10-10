"""CSRF protection, login helpers and role checks."""
import functools
import hmac
import secrets

from flask import abort, flash, g, redirect, request, session, url_for

from .db import get_db


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def check_csrf():
    expected = session.get("_csrf")
    sent = request.form.get("_csrf", "")
    # no token in the session means the form didn't come from one of our pages
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "Your form expired. Please go back, refresh the page and try again.")


def load_user():
    """Run before every request: attach the signed-in user (if still approved)."""
    g.user = None
    uid = session.get("uid")
    if uid is not None:
        row = get_db().execute("SELECT * FROM users WHERE id = ? AND status = 'approved'",
                               (uid,)).fetchone()
        if row is None:
            session.pop("uid", None)             # deleted or rejected since login
        g.user = row


def login_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        if g.user is None:
            flash("Please sign in first.", "info")
            return redirect(url_for("auth.login"))
        return view(*a, **kw)
    return wrapped


def role_required(role):
    def decorator(view):
        @functools.wraps(view)
        @login_required
        def wrapped(*a, **kw):
            if g.user["role"] != role:
                abort(403)
            return view(*a, **kw)
        return wrapped
    return decorator
