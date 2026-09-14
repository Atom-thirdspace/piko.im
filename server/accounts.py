from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)
from .oauth import enabled_providers
from .mailer import send_welcome_email
from .models import (
    complete_profile, create_email_user, find_by_email, find_by_login,
    find_by_username, mark_welcome_sent, touch_login,
)
from .session import current_user, is_safe_next, login_required
from .validators import INTERESTS, INTEREST_KEYS, validate_signup, validate_username

accounts_bp = Blueprint("accounts", __name__)


def start_session(user):
    """Rotate the session on every login - prevents session fixation."""
    session.clear()
    session["user_id"] = user.id
    session.permanent = True


def _email_taken(email):
    return find_by_email(email) is not None


def _username_taken(username):
    return find_by_username(username) is not None


@accounts_bp.route("/signup/", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect("/")

    nxt = request.args.get("next", "/")

    if request.method == "GET":
        return render_template(
            "signup.html", interests=INTERESTS, errors={}, form={}, next=nxt
        )

    form = request.form
    errors = validate_signup(form, _email_taken, _username_taken)

    # An OAuth user setting a password for the first time isn't a duplicate.
    if errors.get("email"):
        existing = find_by_email((form.get("email") or "").strip().lower())
        if existing is not None and not existing.password_hash:
            errors["email"] = (
                "You already signed up with Google or GitHub. "
                "Sign in that way instead."
            )

    if errors:
        return render_template(
            "signup.html", interests=INTERESTS, errors=errors, form=form, next=nxt
        ), 400

    user = create_email_user(
        email=form["email"].strip(),
        username=form["username"].strip(),
        name=form["name"].strip(),
        interest=form["interest"],
        password=form["password"],
    )

    if send_welcome_email(user.email, user.name):
        mark_welcome_sent(user.id)
    else:
        current_app.logger.warning("welcome email failed for user %s", user.id)

    start_session(user)
    return redirect(nxt if is_safe_next(nxt) else "/")


@accounts_bp.route("/login/password/", methods=["POST"])
def password_login():
    identifier = (request.form.get("identifier") or "").strip()
    password = request.form.get("password") or ""
    nxt = request.form.get("next", "/")

    user = find_by_login(identifier) if identifier else None

    if user is None or not user.check_password(password):
        # One message for both cases - don't leak which emails are registered.
        flash("Wrong email/username or password.", "error")
        return redirect(url_for("auth.login_page", next=nxt))

    touch_login(user)
    start_session(user)

    if user.needs_onboarding:
        return redirect(url_for("accounts.onboarding", next=nxt))
    return redirect(nxt if is_safe_next(nxt) else "/")


@accounts_bp.route("/onboarding/", methods=["GET", "POST"])
@login_required
def onboarding():
    """Collect username + interest from users who arrived via OAuth."""
    user = current_user()
    nxt = request.args.get("next", "/")

    if not user.needs_onboarding:
        return redirect("/")

    if request.method == "GET":
        return render_template(
            "onboarding.html", interests=INTERESTS, errors={}, user=user, next=nxt
        )

    errors = {}
    username = (request.form.get("username") or "").strip().lower()

    err = validate_username(
        username,
        lambda u: find_by_username(u) not in (None, user),
    )
    if err:
        errors["username"] = err

    interest = request.form.get("interest")
    if interest not in INTEREST_KEYS:
        errors["interest"] = "Pick what you want to focus on."

    if errors:
        return render_template(
            "onboarding.html", interests=INTERESTS, errors=errors,
            user=user, next=nxt,
        ), 400

    complete_profile(user, username, interest)
    return redirect(nxt if is_safe_next(nxt) else "/")
