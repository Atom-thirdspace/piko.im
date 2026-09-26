from flask import Blueprint, jsonify, redirect, render_template, url_for

from .achievements import describe
from .models import (Enrollment, LessonProgress, Submission, XpEvent, db,
                     earned_rows, recent_freeze_uses)
from .progress import level_progress, user_today, MAX_FREEZES, streak_state
from .session import current_user, login_required
from .validators import DAILY_GOAL_CHOICES
from .activity import heatmap

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
    # One grouped query replaces the old pass over every XpEvent row, and
    # serves the heatmap from the same result.
    grid = heatmap(user)
    today_xp = grid["today_xp"]

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
        "heatmap": grid,
        "streak": streak_state(user, today),
        "freeze_uses": recent_freeze_uses(user),
        "max_freezes": MAX_FREEZES,
        "achievements": describe([r.key for r in earned_rows(user, limit=6)]),
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
        "streak": data["streak"],
    }


@dashboard_bp.route("/")
def index():
    user = current_user()
    if user is None:
        return render_template("index.html")
    if user.needs_onboarding:
        return redirect(url_for("accounts.onboarding", next=url_for("dashboard.index")))
    if user.needs_questionnaire:
        return redirect(url_for("onboarding.page"))
    return render_template("dashboard.html", **_dashboard_data(user))


@dashboard_bp.route("/api/dashboard")
@login_required
def api():
    return jsonify(_json_data(_dashboard_data(current_user())))