from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, jsonify, redirect, render_template, url_for

from .models import Enrollment, LessonProgress, Submission, XpEvent, db
from .progress import level_progress, user_today
from .session import current_user, login_required
from .validators import DAILY_GOAL_CHOICES

dashboard_bp = Blueprint("dashboard", __name__)


def _stats(user):
    lessons_done = db.session.execute(
        db.select(db.func.count())
        .select_from(LessonProgress)
        .where(LessonProgress.user_id == user.id)
    ).scalar() or 0
    problems_solved = db.session.execute(
        db.select(db.func.count(db.distinct(Submission.problem_id)))
        .where(Submission.user_id == user.id, Submission.verdict == "accepted")
    ).scalar() or 0
    submissions = db.session.execute(
        db.select(db.func.count())
        .select_from(Submission)
        .where(Submission.user_id == user.id)
    ).scalar() or 0
    return {
        "lessons_done": lessons_done,
        "problems_solved": problems_solved,
        "submissions": submissions,
    }


def _primary_enrollment(user):
    enrollment = db.session.execute(
        db.select(Enrollment).where(
            Enrollment.user_id == user.id,
            Enrollment.is_primary.is_(True),
        )
    ).scalar_one_or_none()
    if enrollment is None:
        return None

    lesson = enrollment.current_lesson
    return {
        "track": {
            "slug": enrollment.track.slug,
            "title": enrollment.track.title,
            "description": enrollment.track.description,
        },
        "unit": (
            {"slug": lesson.unit.slug, "title": lesson.unit.title}
            if lesson is not None else None
        ),
        "lesson": (
            {
                "id": lesson.id,
                "slug": lesson.slug,
                "title": lesson.title,
                "kind": lesson.kind,
                "xp": lesson.xp,
            }
            if lesson is not None else None
        ),
        "started_at": enrollment.started_at,
    }


def _activity(user, limit=8):
    events = db.session.execute(
        db.select(XpEvent)
        .where(XpEvent.user_id == user.id)
        .order_by(XpEvent.created_at.desc())
        .limit(limit)
    ).scalars().all()
    labels = {"lesson": "Lesson", "problem": "Problem", "streak": "Streak bonus"}
    return [
        {
            "amount": event.amount,
            "label": labels.get(event.reason, event.reason),
            "reason": event.reason,
            "ref": event.ref,
            "at": event.created_at,
        }
        for event in events
    ]


def _dashboard_data(user):
    today = user_today(user)
    try:
        user_timezone = ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        user_timezone = ZoneInfo("UTC")
    today_xp = 0
    for event in db.session.execute(
        db.select(XpEvent).where(XpEvent.user_id == user.id)
    ).scalars():
        created_at = event.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at.astimezone(user_timezone).date() == today:
            today_xp += event.amount

    progress = level_progress(user.xp_total or 0)
    return {
        "user": user,
        "progress": progress,
        "stats": _stats(user),
        "current": _primary_enrollment(user),
        "activity": _activity(user),
        "daily_goal": {
            "target_xp": user.daily_goal_xp or 0,
            "earned_xp": today_xp,
            "remaining_xp": max((user.daily_goal_xp or 0) - today_xp, 0),
        },
        "goal_choices": DAILY_GOAL_CHOICES,
    }


def _json_data(data):
    current = data["current"]
    if current is not None:
        current = {
            **current,
            "started_at": (
                current["started_at"].isoformat()
                if current["started_at"] else None
            ),
        }
    return {
        "user": {
            "id": data["user"].id,
            "name": data["user"].name,
            "username": data["user"].username,
            "email": data["user"].email,
            "avatar_url": data["user"].avatar_url,
        },
        "progress": data["progress"],
        "stats": data["stats"],
        "current": current,
        "daily_goal": data["daily_goal"],
        "activity": [
            {**row, "at": row["at"].isoformat() if row["at"] else None}
            for row in data["activity"]
        ],
    }


@dashboard_bp.route("/dashboard/")
@login_required
def index():
    user = current_user()
    if user.needs_onboarding:
        return redirect(url_for("accounts.onboarding", next=url_for("dashboard.index")))
    if user.needs_questionnaire:
        return redirect(url_for("onboarding.page"))
    return render_template("dashboard.html", **_dashboard_data(user))


@dashboard_bp.route("/api/dashboard")
@login_required
def api():
    return jsonify(_json_data(_dashboard_data(current_user())))