from flask import Blueprint, redirect, render_template, request, url_for, current_app, abort, flash
from flask_login import current_user, login_required, login_user, logout_user

from app import __version__
from app.extensions import limiter
from app.models import (
    count_users,
    create_user,
    delete_user,
    fetch_all_users,
    get_user_by_id,
    get_user_by_username,
    update_user,
)

auth_bp = Blueprint("auth", __name__)

# Rate limit helper — no-op if Flask-Limiter isn't installed
def _limit(limit_string, **kwargs):
    if limiter:
        return limiter.limit(limit_string, **kwargs)
    return lambda f: f


@auth_bp.route("/setup", methods=["GET", "POST"])
@_limit("5 per minute", methods=["POST"])
def setup():
    if count_users() > 0:
        return redirect(url_for("overview.overview"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username:
            error = "Username is required."
        elif len(username) < 3:
            error = "Username must be at least 3 characters."
        elif not password:
            error = "Password is required."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            create_user(username, password, is_admin=True)
            user = get_user_by_username(username)
            login_user(user)
            return redirect(url_for("overview.overview"))

    return render_template("auth/setup.html", error=error, version=__version__)


@auth_bp.route("/login", methods=["GET", "POST"])
@_limit("5 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("overview.overview"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_user_by_username(username)

        if user is None or not user.check_password(password):
            error = "Invalid username or password."
        else:
            login_user(user, remember=True)
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("overview.overview"))

    demo_username = current_app.config.get("DEMO_READ_ONLY_USERNAME", "demo")
    demo_public = bool(current_app.config.get("DEMO_PUBLIC_LOGIN_ENABLED", False))
    return render_template(
        "auth/login.html",
        error=error,
        version=__version__,
        demo_username=demo_username,
        demo_public=demo_public,
    )


@auth_bp.route("/demo")
def demo_login():
    if not current_app.config.get("DEMO_PUBLIC_LOGIN_ENABLED", False):
        abort(404)
    if current_user.is_authenticated:
        return redirect(url_for("overview.overview"))
    demo_username = current_app.config.get("DEMO_READ_ONLY_USERNAME", "demo")
    user = get_user_by_username(demo_username)
    if not user:
        flash(f"Demo user '{demo_username}' does not exist.", "error")
        return redirect(url_for("auth.login"))
    login_user(user, remember=False)
    return redirect(url_for("overview.overview"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/users")
@login_required
def manage_users():
    if not current_user.is_admin:
        return redirect(url_for("overview.overview"))

    users = fetch_all_users()
    mode = request.args.get("mode", "list")
    edit_uid = request.args.get("edit", type=int)
    edit_user = get_user_by_id(edit_uid) if edit_uid else None
    error = request.args.get("error")
    success = request.args.get("success")
    return render_template(
        "auth/users.html",
        users=users,
        mode=mode,
        edit_user=edit_user,
        error=error,
        success=success,
    )


@auth_bp.route("/users/<int:user_id>/edit", methods=["POST"])
@login_required
def edit_user_route(user_id):
    if not current_user.is_admin:
        return redirect(url_for("overview.overview"))

    username = request.form.get("username", "").strip() or None
    password = request.form.get("password", "").strip() or None
    # is_admin checkbox: only admins can change this, and can't demote themselves
    is_admin_val = request.form.get("is_admin")
    is_admin = None
    if user_id != current_user.id:  # can't change own role
        is_admin = bool(is_admin_val)

    if username and len(username) < 3:
        return redirect(url_for("auth.manage_users", edit=user_id, error="Username must be at least 3 characters."))
    if password and len(password) < 8:
        return redirect(url_for("auth.manage_users", edit=user_id, error="Password must be at least 8 characters."))

    ok, err = update_user(user_id, username=username, password=password, is_admin=is_admin)
    if not ok:
        return redirect(url_for("auth.manage_users", edit=user_id, error=err))
    return redirect(url_for("auth.manage_users", success="Changes saved."))


@auth_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user_route(user_id):
    if not current_user.is_admin:
        return redirect(url_for("overview.overview"))
    if user_id == current_user.id:
        return redirect(url_for("auth.manage_users", error="You cannot delete your own account."))
    ok, err = delete_user(user_id)
    if not ok:
        return redirect(url_for("auth.manage_users", error=err))
    return redirect(url_for("auth.manage_users", success="User deleted."))


@auth_bp.route("/users/create", methods=["POST"])
@login_required
def create_user_route():
    if not current_user.is_admin:
        return redirect(url_for("overview.overview"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    is_admin = bool(request.form.get("is_admin"))

    if not username or len(username) < 3:
        return redirect(url_for("auth.manage_users", mode="create", error="Username must be at least 3 characters."))
    if not password or len(password) < 8:
        return redirect(url_for("auth.manage_users", mode="create", error="Password must be at least 8 characters."))
    if get_user_by_username(username):
        return redirect(url_for("auth.manage_users", mode="create", error=f"Username '{username}' is already taken."))

    create_user(username, password, is_admin=is_admin)
    return redirect(url_for("auth.manage_users", success=f"User '{username}' created."))
