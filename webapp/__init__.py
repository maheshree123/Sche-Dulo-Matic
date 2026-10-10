"""Sche-Dulo-Matic web application (Flask)."""
import os

from flask import Flask, render_template, request
from markupsafe import Markup

from . import services
from .db import close_db, get_db, init_db
from .security import check_csrf, csrf_token, load_user

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _persistent_secret(instance_path):
    """A random secret key generated once and kept in instance/secret_key."""
    path = os.path.join(instance_path, "secret_key")
    if not os.path.exists(path):
        with open(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            f.write(os.urandom(32).hex())
    with open(path) as f:
        return f.read().strip()


def create_app(config=None):
    config = dict(config or {})
    instance_path = config.pop("INSTANCE_PATH", os.path.join(ROOT, "instance"))
    app = Flask(__name__, instance_path=instance_path)
    os.makedirs(instance_path, exist_ok=True)
    app.config.update(DATABASE=os.path.join(instance_path, "schedulomatic.db"),
                      MAX_CONTENT_LENGTH=1_000_000,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1")
    app.config.update(config)
    app.config["SECRET_KEY"] = (app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY")
                                or _persistent_secret(instance_path))
    init_db(app)
    app.teardown_appcontext(close_db)

    @app.before_request
    def guard():
        load_user()
        if request.method == "POST":
            check_csrf()

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "form-action 'self'; frame-ancestors 'none'; base-uri 'self'")
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.context_processor
    def helpers():
        from flask import g
        counts = None
        if getattr(g, "user", None) is not None and g.user["role"] == "admin":
            counts = services.pending_counts(get_db())
        def hue(subject):
            """Evenly spread colours: subjects are coloured by their position in the sorted list."""
            if "hues" not in g:
                names = sorted(r[0] for r in get_db().execute("SELECT DISTINCT subject FROM sessions"))
                g.hues = {n: round((i * 137.508 + 215) % 360) for i, n in enumerate(names)}
            return g.hues.get(subject, services.hue(subject))

        return {"csrf_input": lambda: Markup(f'<input type="hidden" name="_csrf" value="{csrf_token()}">'),
                "hue": hue, "nav_counts": counts}

    from . import admin, auth, teacher
    app.register_blueprint(auth.bp)
    app.register_blueprint(teacher.bp)
    app.register_blueprint(admin.bp)

    for code, title, text in ((400, "Something went wrong", None), (403, "Not allowed",
                              "You don't have permission to open this page."),
                              (404, "Page not found", "We couldn't find what you were looking for."),
                              (413, "File too large", "Please upload a smaller file.")):
        def handler(err, code=code, title=title, text=text):
            return render_template("error.html", code=code, title=title,
                                   text=text or getattr(err, "description", "Bad request.")), code
        app.register_error_handler(code, handler)
    return app
