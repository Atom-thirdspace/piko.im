import base64

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)

from . import twofa

from .judge.languages import LANGUAGES
from .models import (Enrollment, LessonProgress, OAuthIdentity, Submission,
                     XpEvent, User, db, delete_account, find_by_username,
                     set_user_password, unlink_identity, update_preferences,
                     update_profile, DeletionRequest, cancel_deletion_request, create_deletion_request, pending_deletion_request,
                     Problem, Team, TeamMember)
from .progress import level_progress
from .session import current_user, login_required
from .validators import (COMMON_TIMEZONES, DAILY_GOAL_CHOICES, INTERESTS, DELETION_REASONS,
                         validate_avatar_url, validate_daily_goal,
                         validate_display_name, clean_interests,
                         validate_interests,
                         validate_deletion_request,
                         validate_language, validate_password_change,
                         validate_timezone, validate_username)

profile_bp = Blueprint("profile", __name__)
from .oauth import PROVIDERS, enabled_providers


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

def _showcase(user):
    """The things worth putting at the top of a profile."""
    from .community import follow_counts      # imported here: community imports models

    by_topic = db.session.execute(
        db.select(Problem.topic, db.func.count(db.distinct(Submission.problem_id)))
        .join(Submission, Submission.problem_id == Problem.id)
        .where(Submission.user_id == user.id, Submission.verdict == "accepted",
               Problem.topic.isnot(None))
        .group_by(Problem.topic)
        .order_by(db.func.count(db.distinct(Submission.problem_id)).desc())
    ).all()

    teams = db.session.execute(
        db.select(Team).join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user.id)
        .order_by(TeamMember.joined_at.desc()).limit(3)
    ).scalars().all()

    languages = db.session.execute(
        db.select(Submission.language, db.func.count())
        .where(Submission.user_id == user.id, Submission.verdict == "accepted")
        .group_by(Submission.language)
        .order_by(db.func.count().desc()).limit(3)
    ).all()

    return {"by_topic": by_topic, "teams": teams, "languages": languages,
            "follows": follow_counts(user)}


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
        showcase=_showcase(user),
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
    linked = {identity.provider for identity in identities}

    return render_template(
        "settings.html",
        user=user,
        errors=errors or {},
        form=form if form is not None else request.form,
        interests=INTERESTS,
        languages=[(key, lang.label) for key, lang in LANGUAGES.items()],
        timezones=sorted(set(COMMON_TIMEZONES + [user.timezone or "UTC"])),
        goals=DAILY_GOAL_CHOICES,
        identities=identities,
        provider_labels={name: cfg["label"] for name, cfg in PROVIDERS.items()},
        connectable=[(name, label) for name, label in enabled_providers()
                     if name not in linked],        # Don't let someone strand themselves with no way back in.
        can_unlink=bool(user.password_hash) or len(identities) > 1,
        pending_deletion = pending_deletion_request(user)
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
    interests = clean_interests(form.getlist("interest"))
    avatar_url = (form.get("avatar_url") or "").strip()

    for field, err in (("name", validate_display_name(name)),
                       ("interest", validate_interests(interests)),
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

    update_profile(user, name, username, interests, avatar_url)
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

@profile_bp.route("/settings/privacy", methods=["POST"])
@login_required
def save_privacy():
    user = current_user()
    user.show_on_leaderboard = request.form.get("show_on_leaderboard") == "on"
    user.discoverable = request.form.get("discoverable") == "on"
    user.bio = (request.form.get("bio") or "").strip()[:280]
    db.session.commit()
    flash("Saved.", "success")
    return redirect(url_for("profile.settings") + "#privacy")


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


# --------------------------------------------------------------------------- #
# two-factor
# --------------------------------------------------------------------------- #

SETUP_KEY = "2fa_setup"          # the unconfirmed secret, session-only


@profile_bp.route("/settings/2fa/start", methods=["POST"])
@login_required
def two_factor_start():
    user = current_user()
    if not twofa.configured():
        flash("Two-factor isn't switched on for this site yet.", "error")
        return redirect(url_for("profile.settings"))
    if user.two_factor_on:
        return redirect(url_for("profile.settings") + "#twofa")

    secret = twofa.new_secret()
    # Held in the session, not the database: a secret they never prove should
    # leave no trace on the account.
    session[SETUP_KEY] = base64.b32encode(secret).decode()
    return _render_2fa_setup(user, secret)


def _render_2fa_setup(user, secret, error=None, status=200):
    uri = twofa.provisioning_uri(secret, user.email)
    return render_template("settings_2fa.html", qr=twofa.qr_svg(uri),
                           manual_key=twofa.manual_key(secret), uri=uri,
                           error=error), status


@profile_bp.route("/settings/2fa/enable", methods=["POST"])
@login_required
def two_factor_enable():
    user = current_user()
    packed = session.get(SETUP_KEY)
    if not packed:
        flash("That setup expired. Start again.", "error")
        return redirect(url_for("profile.settings") + "#twofa")

    secret = base64.b32decode(packed)
    step = twofa.check_code(secret, request.form.get("code"))
    if step is None:
        return _render_2fa_setup(
            user, secret, status=400,
            error="That code isn't right. The app's clock may be off - "
                  "wait for the next code and try again.")

    plain, hashed = twofa.make_backup_codes()
    twofa.enable(user, secret, hashed, step)
    session.pop(SETUP_KEY, None)
    # Shown exactly once - we keep only hashes, so we can't show them again.
    return render_template("backup_codes.html", codes=plain)


@profile_bp.route("/settings/2fa/disable", methods=["POST"])
@login_required
def two_factor_disable():
    user = current_user()
    if not user.two_factor_on:
        return redirect(url_for("profile.settings") + "#twofa")

    # Turning it off is a security decision, so prove it is still you.
    proof = request.form.get("proof") or ""
    secret = twofa.unseal(user.totp_secret)
    ok = (secret is not None
          and twofa.check_code(secret, proof, user.totp_last_step) is not None)
    if not ok and user.password_hash:
        ok = user.check_password(proof)

    if not ok:
        flash("Enter a current code or your password to turn it off.", "error")
        return redirect(url_for("profile.settings") + "#twofa")

    twofa.disable(user)
    flash("Two-factor turned off.", "success")
    return redirect(url_for("profile.settings") + "#twofa")


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
    flash("%s disconnected." % PROVIDERS.get(provider, {}).get("label", provider.title()),
          "success")
    return redirect(url_for("profile.settings"))


@profile_bp.route("/settings/leave/", methods=["GET", "POST"])
@login_required
def leave():
    user = current_user()
    pending = pending_deletion_request(user)

    if request.method == "POST" and pending is None:
        errors, reason, detail = validate_deletion_request(request.form, user.username)
        if errors:
            return render_template("leave.html", user=user, pending=None,
                                   reasons=DELETION_REASONS, errors=errors,
                                   form=request.form), 400

        create_deletion_request(user, reason, detail)
        flash("Request sent. An admin will review it - you can cancel until they do.",
              "success")
        return redirect(url_for("profile.settings"))

    return render_template("leave.html", user=user, pending=pending,
                           reasons=DELETION_REASONS, errors={}, form={})


@profile_bp.route("/settings/leave/cancel", methods=["POST"])
@login_required
def leave_cancel():
    if cancel_deletion_request(current_user()) is None:
        flash("You don't have a deletion request open.", "error")
    else:
        flash("Deletion request withdrawn. Your account stays as it is.", "success")
    return redirect(url_for("profile.settings"))

