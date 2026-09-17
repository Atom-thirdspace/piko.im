from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

from .judge.languages import LANGUAGES
from .models import (Enrollment, LessonProgress, OAuthIdentity, Submission,
                     XpEvent, User, db, delete_account, find_by_username,
                     set_user_password, unlink_identity, update_preferences,
                     update_profile)
from .progress import level_progress
from .session import current_user, login_required
from .validators import (COMMON_TIMEZONES, DAILY_GOAL_CHOICES, INTERESTS,
                         validate_avatar_url, validate_daily_goal,
                         validate_display_name, validate_interest,
                         validate_language, validate_password_change,
                         validate_timezone, validate_username)

profile_bp = Blueprint("profile", __name__)


# --------------------------------------------------------------------------- #
# read helpers
# --------------------------------------------------------------------------- #

def _counts(user):
    lessons_done = db.session.execute(
        db.select(db.func.count())
        .select_from(LessonProgress)
        .where(LessonProgress.user_id == user.id)
    ).scalar()

    problems_solved = db.session.execute(
        db.select(db.func.count(db.distinct(Submission.problem_id)))
        .where(Submission.user_id == user.id, Submission.verdict == "accepted")
    ).scalar()

    submissions = db.session.execute(
        db.select(db.func.count())
        .select_from(Submission)
        .where(Submission.user_id == user.id)
    ).scalar()

    return {"lessons_done": lessons_done or 0,
            "problems_solved": problems_solved or 0,
            "submissions": submissions or 0}


def _current_track(user):
    enrollment = db.session.execute(
        db.select(Enrollment).where(Enrollment.user_id == user.id,
                                    Enrollment.is_primary.is_(True))
    ).scalar_one_or_none()
    if enrollment is None:
        return None
    lesson = enrollment.current_lesson
    return {"track": enrollment.track,
            "lesson": lesson,
            "unit": lesson.unit if lesson is not None else None,
            "started_at": enrollment.started_at}


def _activity(user, limit=8):
    """Recent XP awards, labelled for display."""
    events = db.session.execute(
        db.select(XpEvent).where(XpEvent.user_id == user.id)
        .order_by(XpEvent.created_at.desc()).limit(limit)
    ).scalars().all()

    labels = {"lesson": "Lesson", "problem": "Problem", "streak": "Streak bonus"}
    return [{"amount": event.amount,
             "label": labels.get(event.reason, event.reason),
             "ref": event.ref,
             "at": event.created_at} for event in events]


# --------------------------------------------------------------------------- #
# public profile
# --------------------------------------------------------------------------- #

@profile_bp.route("/u/<username>/")
def public_profile(username):
    user = find_by_username(username)
    if user is None:
        abort(404)

    viewer = current_user()
    return render_template(
        "profile.html",
        profile_user=user,
        is_self=viewer is not None and viewer.id == user.id,
        progress=level_progress(user.xp_total or 0),
        stats=_counts(user),
        current=_current_track(user),
        activity=_activity(user),
    )


@profile_bp.route("/me/")
@login_required
def me():
    user = current_user()
    if user.needs_onboarding:                 # no username yet, nothing to show
        return redirect(url_for("accounts.onboarding", next=url_for("profile.me")))
    return redirect(url_for("profile.public_profile", username=user.username))


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #

def _render_settings(errors=None, form=None, status=200):
    user = current_user()
    identities = db.session.execute(
        db.select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)
    ).scalars().all()

    return render_template(
        "settings.html",
        user=user,
        errors=errors or {},
        form=form or {},
        interests=INTERESTS,
        languages=[(key, lang.label) for key, lang in LANGUAGES.items()],
        timezones=sorted(set(COMMON_TIMEZONES + [user.timezone or "UTC"])),
        goals=DAILY_GOAL_CHOICES,
        identities=identities,
        # Don't let someone strand themselves with no way back in.
        can_unlink=bool(user.password_hash) or len(identities) > 1,
    ), status


@profile_bp.route("/settings/")
@login_required
def settings():
    return _render_settings()


@profile_bp.route("/settings/profile", methods=["POST"])
@login_required
def save_profile():
    user = current_user()
    form = request.form
    errors = {}

    name = (form.get("name") or "").strip()
    username = (form.get("username") or "").strip().lower()
    interest = form.get("interest")
    avatar_url = (form.get("avatar_url") or "").strip()

    for field, err in (("name", validate_display_name(name)),
                       ("interest", validate_interest(interest)),
                       ("avatar_url", validate_avatar_url(avatar_url))):
        if err:
            errors[field] = err

    if username != (user.username or ""):
        err = validate_username(
            username, lambda u: find_by_username(u) not in (None, user)
        )
        if err:
            errors["username"] = err

    if errors:
        return _render_settings(errors, form, 400)

    update_profile(user, name, username, interest, avatar_url)
    flash("Profile updated.", "success")
    return redirect(url_for("profile.settings"))


@profile_bp.route("/settings/learning", methods=["POST"])
@login_required
def save_learning():
    user = current_user()
    form = request.form
    errors = {}

    goal = form.get("daily_goal_xp")
    language = form.get("preferred_language") or None
    timezone = form.get("timezone")

    for field, err in (("daily_goal_xp", validate_daily_goal(goal)),
                       ("preferred_language", validate_language(language, set(LANGUAGES))),
                       ("timezone", validate_timezone(timezone))):
        if err:
            errors[field] = err

    if errors:
        return _render_settings(errors, form, 400)

    update_preferences(user, goal, language, timezone)
    flash("Learning preferences saved.", "success")
    return redirect(url_for("profile.settings"))


@profile_bp.route("/settings/password", methods=["POST"])
@login_required
def save_password():
    user = current_user()
    form = request.form
    had_password = bool(user.password_hash)

    # Someone who signed up with OAuth has no password to confirm yet.
    current_ok = (not had_password
                  or user.check_password(form.get("current_password") or ""))
    errors = validate_password_change(
        form.get("new_password"), form.get("confirm_password"),
        user.email, user.username, current_ok,
    )
    if errors:
        return _render_settings(errors, form, 400)

    set_user_password(user, form["new_password"])
    flash("Password updated." if had_password else "Password set.", "success")
    return redirect(url_for("profile.settings"))


@profile_bp.route("/settings/unlink/<provider>", methods=["POST"])
@login_required
def unlink(provider):
    user = current_user()
    identities = db.session.execute(
        db.select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)
    ).scalars().all()

    if not any(i.provider == provider for i in identities):
        abort(404)
    if not user.password_hash and len(identities) <= 1:
        flash("Set a password first - that's your only way back in.", "error")
        return redirect(url_for("profile.settings"))

    unlink_identity(user, provider)
    flash("%s disconnected." % provider.title(), "success")
    return redirect(url_for("profile.settings"))


@profile_bp.route("/settings/delete", methods=["POST"])
@login_required
def delete():
    user = current_user()
    typed = (request.form.get("confirm_username") or "").strip().lower()

    if typed != (user.username or ""):
        return _render_settings(
            {"confirm_username": "Type your username exactly to confirm."},
            request.form, 400,
        )

    delete_account(user)
    session.clear()
    flash("Your account and everything in it has been deleted.", "success")
    return redirect("/")
