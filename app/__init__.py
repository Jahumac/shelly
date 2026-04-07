from flask import Flask, redirect, url_for, send_from_directory
from flask_login import LoginManager, current_user

from .models import count_users, fetch_assumptions, get_user_by_id, init_db

__version__ = "1.0.0"
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


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")

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

    # ── Service worker (must be served from / for full scope) ──────────────
    @app.route('/sw.js')
    def service_worker():
        return send_from_directory(app.static_folder, 'sw.js',
                                   mimetype='application/javascript',
                                   max_age=0)

    with app.app_context():
        init_db()

    # ── Redirect to setup if no users exist ──────────────────────────────────
    @app.before_request
    def redirect_to_setup_if_needed():
        from flask import request
        # Allow the setup page, login page, and static assets through
        if request.endpoint in ("auth.setup", "auth.login", "static", "service_worker", None):
            return
        if count_users() == 0:
            return redirect(url_for("auth.setup"))

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

    return app
