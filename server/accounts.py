from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint, current_app, flash, make_response, redirect, render_template,
    request, session, url_for,
)
from .devices import notify_new_device, remember_device
from .oauth import enabled_providers
from .mailer import send_verification_email
from .models import (
    complete_profile, create_email_user, find_by_email, find_by_login,
    find_by_username, load_user, mark_email_verified, mark_welcome_sent,
    touch_login, touch_verification_sent,
)
from .session import current_user, is_safe_next, login_required
from .tokens import make_verify_token, read_verify_token
from .validators import INTERESTS, INTEREST_KEYS, validate_signup, validate_username

accounts_bp = Blueprint("accounts", __name__)

RESEND_COOLDOWN = timedelta(minutes=2)


def start_session(user):
    """Rotate the session on every login - prevents session fixation."""
    session.clear()
    session["user_id"] = user.id
    session.permanent = True


def _email_taken(email):
    return find_by_email(email) is not None


def _username_taken(username):
    return find_by_username(username) is not None


def _age(dt):
    """SQLite hands back naive datetimes; treat those as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - dt


def _send_verification(user, welcome=False):
    token = make_verify_token(user)
    url = url_for("accounts.verify_email", token=token, _external=True)
    if send_verification_email(user.email, url, user.name, welcome=welcome):
        touch_verification_sent(user)
        if welcome:
            mark_welcome_sent(user.id)
        return True
    current_app.logger.warning("verification email failed for user %s", user.id)
    return False


@accounts_bp.route("/signup/", methods=["GET", "POST"])
def signup():
    if current_user():
        return redirect(url_for("dashboard.index"))

    nxt = request.args.get("next", url_for("dashboard.index"))

    if request.method == "GET":
        return render_template(
            "signup.html", interests=INTERESTS, errors={}, form={}, next=nxt,
            providers=enabled_providers(),
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
            "signup.html", interests=INTERESTS, errors=errors, form=form, next=nxt,
            providers=enabled_providers(),
        ), 400

    user = create_email_user(
        email=form["email"].strip(),
        username=form["username"].strip(),
        name=form["name"].strip(),
        interest=form["interest"],
        password=form["password"],
    )

    _send_verification(user, welcome=True)      # welcome and confirm in one email
    start_session(user)

    response = make_response(
        redirect(nxt if is_safe_next(nxt) else url_for("dashboard.index"))
    )
    remember_device(response, user)             # signing up isn't a sign-in worth warning about
    return response


@accounts_bp.route("/login/password/", methods=["POST"])
def password_login():
    if current_user():
        return redirect(url_for("dashboard.index"))
    identifier = (request.form.get("identifier") or "").strip()
    password = request.form.get("password") or ""
    nxt = request.form.get("next", url_for("dashboard.index"))

    user = find_by_login(identifier) if identifier else None

    if user is None or not user.check_password(password):
        # One message for both cases - don't leak which emails are registered.
        flash("Wrong email/username or password.", "error")
        return redirect(url_for("auth.login_page", next=nxt))

    touch_login(user)
    start_session(user)

    if user.needs_onboarding:
        target = url_for("accounts.onboarding", next=nxt)
    elif user.needs_questionnaire:
        target = url_for("onboarding.page")
    else:
        target = nxt if is_safe_next(nxt) else url_for("dashboard.index")

    response = make_response(redirect(target))
    notify_new_device(user, response)
    return response


@accounts_bp.route("/verify/<token>/")
def verify_email(token):
    data, problem = read_verify_token(token)
    if problem == "expired":
        flash("That confirmation link has expired. Sign in and we'll send a fresh one.", "error")
        return redirect(url_for("auth.login_page"))
    if problem:
        flash("That confirmation link isn't valid.", "error")
        return redirect(url_for("auth.login_page"))

    user = load_user(data["uid"])
    # The token carries the address it was sent to, so an email change kills old links.
    if user is None or user.email != data["email"]:
        flash("That confirmation link isn't valid any more.", "error")
        return redirect(url_for("auth.login_page"))

    if user.email_verified:
        flash("Your email is already confirmed.", "success")
    else:
        mark_email_verified(user)
        flash("Email confirmed - thanks.", "success")

    # Confirming never signs anyone in: these links get forwarded.
    viewer = current_user()
    if viewer is not None and viewer.id == user.id:
        return redirect(url_for("dashboard.index"))
    return redirect(url_for("auth.login_page"))


@accounts_bp.route("/verify/resend/", methods=["POST"])
@login_required
def resend_verification():
    user = current_user()
    back = request.form.get("next") or url_for("profile.settings")
    if not is_safe_next(back):
        back = url_for("profile.settings")

    if user.email_verified:
        return redirect(back)

    since = _age(user.verification_sent_at)
    if since is not None and since < RESEND_COOLDOWN:
        flash("We just sent one - give it a minute, and check spam.", "error")
    elif _send_verification(user):
        flash("Confirmation email sent to %s." % user.email, "success")
    else:
        flash("We couldn't send that email just now. Try again shortly.", "error")
    return redirect(back)


@accounts_bp.route("/onboarding/", methods=["GET", "POST"])
@login_required
def onboarding():
    """Collect username + interest from users who arrived via OAuth."""
    user = current_user()
    nxt = request.args.get("next", url_for("dashboard.index"))

    if not user.needs_onboarding:
        return redirect(url_for("dashboard.index"))

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
    if user.needs_questionnaire:
        return redirect(url_for("onboarding.page"))
    return redirect(nxt if is_safe_next(nxt) else url_for("dashboard.index"))
