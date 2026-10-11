from flask import Blueprint, jsonify, redirect, render_template, url_for
from .achievements import describe
from sqlalchemy.orm import joinedload

from .models import (Enrollment, Lesson, LessonProgress, Submission, XpEvent,
                     db, earned_rows, recent_freeze_uses)
from .progress import level_progress, user_today, MAX_FREEZES, streak_state
from .session import current_user, login_required
from .validators import DAILY_GOAL_CHOICES
from .activity import heatmap
from . import companion, economy, mastery, potd, quests, rivals, seasons, recommend

dashboard_bp = Blueprint("dashboard", __name__)


def _stats(user):
    row = db.session.execute(db.select(
        db.select(db.func.count()).select_from(LessonProgress)
          .where(LessonProgress.user_id == user.id).scalar_subquery(),
        db.select(db.func.count(db.distinct(Submission.problem_id)))
          .where(Submission.user_id == user.id,
                 Submission.verdict == "accepted").scalar_subquery(),
        db.select(db.func.count()).select_from(Submission)
          .where(Submission.user_id == user.id).scalar_subquery(),
    )).one()
    return {
        "lessons_done": row[0] or 0,
        "problems_solved": row[1] or 0,
        "submissions": row[2] or 0,
    }


def _primary_enrollment(user):
    # track, current_lesson and that lesson's unit were four separate lazy
    # loads; one join fetches the lot.
    enrollment = db.session.execute(
        db.select(Enrollment)
        .options(joinedload(Enrollment.track),
                 joinedload(Enrollment.current_lesson).joinedload(Lesson.unit))
        .where(
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
    # One evaluation of the quest board, shared between the payout and
    # the render.
    _, board = quests.sync_board(user, today)
    # One grouped query replaces the old pass over every XpEvent row, and
    # serves the heatmap from the same result.
    grid = heatmap(user)
    today_xp = grid["today_xp"]

    progress = level_progress(user.xp_total or 0)
    topics = mastery.for_user(user)
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
        "next_up": recommend.next_problem(user),
        "quests": board,
        "potd": potd.card(user),
        "goal_choices": DAILY_GOAL_CHOICES,
        "companion": companion.state(user, today_xp, user.streak_days or 0),
        "coins": economy.balance(user),
        "mastery": topics[:6],
        "rusty": mastery.rusty(user, rows=topics),
        "combo": {"now": user.solve_combo or 0, "best": user.combo_best or 0},
        "season": seasons.card(user),
        "rival": rivals.card(user),
    }


def _json_potd(card):
    if card is None:
        return None
    problem = card["problem"]
    return {**card, "day": card["day"].isoformat(),
            "problem": {"slug": problem.slug, "title": problem.title,
                        "difficulty": problem.difficulty, "xp": problem.xp}}


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
    out = {
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
        "quests": {**data["quests"], "day": data["quests"]["day"].isoformat()},
        "potd": _json_potd(data["potd"]),
    }

    out["companion"] = data["companion"]
    out["coins"] = data["coins"]
    out["combo"] = data["combo"]
    out["mastery"] = [
        {"topic": m["topic"], "value": m["value"], "band": m["band"],
         "fraction": m["fraction"], "faded": m["faded"]}
        for m in data["mastery"]
    ]
    out["rusty"] = [r["topic"] for r in data["rusty"]]

    season = data.get("season")
    out["season"] = None if season is None else {
        "name": season["season"].name,
        "score": season["score"],
        "tier": season["tier"],
        "next": season["next"],
        "days_left": season["days_left"],
    }

    rival = data.get("rival")
    if rival is None or rival.get("waiting"):
        out["rival"] = {"waiting": True} if rival else None
    else:
        out["rival"] = {
            "waiting": False,
            "ghost": rival["ghost"],
            "yours": rival["yours"],
            "theirs": rival["theirs"],
            "leading": rival["leading"],
            "opponent": (rival["opponent"].username
                         if rival["opponent"] else None),
        }
    return out


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