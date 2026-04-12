from flask import Flask, redirect, url_for, send_from_directory, request, flash, jsonify
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect

from .calculations import build_month_strip
from .models import count_users, fetch_assumptions, get_user_by_id, init_db, close_db
from .services.scheduler import init_scheduler

from .extensions import limiter
__version__ = "1.5.0"
from .routes.auth import auth_bp
from .routes.overview import overview_bp
from .routes.goals import goals_bp
from .routes.projections import projections_bp
from .routes.accounts import accounts_bp
from .routes.holdings import holdings_bp
from .routes.settings import settings_bp
from .routes.monthly_review import monthly_review_bp
from .routes.budget import budget_bp
from .routes.export import export_bp
from .routes.performance import performance_bp
from .routes.allowance import allowance_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")

    # ── Rate limiter ─────────────────────────────────────────────────────────
    if limiter is not None:
        limiter.init_app(app)

    # ── Secure session cookies (auto-detect HTTPS) ───────────────────────
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    app.config.setdefault("REMEMBER_COOKIE_HTTPONLY", True)
    app.config.setdefault("REMEMBER_COOKIE_SAMESITE", "Lax")

    # ── CSRF Protection ──────────────────────────────────────────────────────
    csrf = CSRFProtect(app)

    # ── Flask-Login ──────────────────────────────────────────────────────────
    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = ""

    @login_manager.user_loader
    def load_user(user_id):
        return get_user_by_id(int(user_id))

    # ── Blueprints ────────────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(overview_bp)
    app.register_blueprint(goals_bp, url_prefix="/goals")
    app.register_blueprint(projections_bp, url_prefix="/projections")
    app.register_blueprint(accounts_bp, url_prefix="/accounts")
    app.register_blueprint(holdings_bp, url_prefix="/holdings")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(monthly_review_bp, url_prefix="/monthly-review")
    app.register_blueprint(budget_bp, url_prefix="/budget")
    app.register_blueprint(export_bp)
    app.register_blueprint(performance_bp, url_prefix="/performance")
    app.register_blueprint(allowance_bp, url_prefix="/allowance")

    app.teardown_appcontext(close_db)

    # ── Service worker (must be served from / for full scope) ──────────────
    @app.route('/sw.js')
    def service_worker():
        return send_from_directory(app.static_folder, 'sw.js',
                                   mimetype='application/javascript',
                                   max_age=0)

    @app.route("/api/ping")
    def api_ping():
        return jsonify({"ok": True})

    with app.app_context():
        init_db()
        init_scheduler(app)

    # ── Redirect to setup if no users exist ──────────────────────────────────
    @app.before_request
    def redirect_to_setup_if_needed():
        from flask import request
        # Allow the setup page, login page, and static assets through
        if request.endpoint in ("auth.setup", "auth.login", "static", "service_worker", "api_ping", None):
            return
        if count_users() == 0:
            return redirect(url_for("auth.setup"))

    @app.before_request
    def enforce_read_only_demo():
        if not current_user.is_authenticated:
            return
        demo_user = app.config.get("DEMO_READ_ONLY_USERNAME")
        if not demo_user:
            return
        if not app.config.get("DEMO_PUBLIC_LOGIN_ENABLED", False):
            return
        if getattr(current_user, "username", None) != demo_user:
            return
        if request.method != "POST":
            return
        if request.headers.get("Accept", "").find("application/json") != -1 or request.path.find("/api/") != -1:
            return jsonify({"error": "Demo account is read-only"}), 403
        flash("Demo account is read-only", "error")
        return redirect(request.referrer or url_for("overview.overview"))
    # ── Context processors ────────────────────────────────────────────────────
    @app.context_processor
    def inject_dashboard_name():
        try:
            if current_user.is_authenticated:
                assumptions = fetch_assumptions(current_user.id)
                name = (assumptions["dashboard_name"] if assumptions else None) or "Shelly"
            else:
                name = "Shelly"
        except Exception:
            name = "Shelly"
        return {"dashboard_name": name}

    @app.context_processor
    def inject_month_strip():
        from datetime import date
        strip = build_month_strip(date.today())
        today_pill = next((m for m in strip if m["is_today"]), None)
        current_month_num = today_pill["month_num"] if today_pill else date.today().month
        return {"month_strip": strip, "current_month_num": current_month_num}

    # ── Security headers ────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        from flask import request as req
        if req.is_secure or req.headers.get("X-Forwarded-Proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    return app
