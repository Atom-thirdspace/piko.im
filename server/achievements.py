from dataclasses import dataclass
from typing import Callable

from sqlalchemy.exc import IntegrityError

from .models import (LessonProgress, Problem, Submission, UserAchievement,
                     XpEvent, db, earned_keys)
from .progress import level_for_xp


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    description: str
    group: str
    test: Callable[[dict], bool]


def snapshot(user):
    def count(stmt):
        return db.session.execute(stmt).scalar() or 0

    solved = count(
        db.select(db.func.count(db.distinct(Submission.problem_id)))
        .where(Submission.user_id == user.id, Submission.verdict == "accepted"))

    return {
        "xp": user.xp_total or 0,
        "level": level_for_xp(user.xp_total or 0),
        "streak_best": user.streak_best or 0,
        "lessons": count(
            db.select(db.func.count()).select_from(LessonProgress)
            .where(LessonProgress.user_id == user.id)),
        "solved": solved,
        "submissions": count(
            db.select(db.func.count()).select_from(Submission)
            .where(Submission.user_id == user.id)),
        "topics": count(
            db.select(db.func.count(db.distinct(Problem.topic)))
            .select_from(Submission).join(Problem, Problem.id == Submission.problem_id)
            .where(Submission.user_id == user.id,
                   Submission.verdict == "accepted",
                   Problem.topic.isnot(None))),
        "languages": count(
            db.select(db.func.count(db.distinct(Submission.language)))
            .where(Submission.user_id == user.id,
                   Submission.verdict == "accepted")),
        "active_days": count(
            db.select(db.func.count(db.distinct(
                db.func.date(db.func.timezone(user.timezone or "UTC",
                                              XpEvent.created_at)))))
            .where(XpEvent.user_id == user.id)),
        "shared": count(
            db.select(db.func.count()).select_from(Submission)
            .where(Submission.user_id == user.id, Submission.is_public.is_(True))),
    }


def _at_least(field, n):
    return lambda s: s[field] >= n


REGISTRY = (
    Achievement("first_lesson", "First steps", "Finish your first lesson",
                "start", _at_least("lessons", 1)),
    Achievement("first_solve", "It compiles!", "Solve your first problem",
                "start", _at_least("solved", 1)),
    Achievement("first_share", "Showing your work", "Share a solution",
                "start", _at_least("shared", 1)),

    Achievement("solve_10", "Getting the hang of it", "Solve 10 problems",
                "volume", _at_least("solved", 10)),
    Achievement("solve_50", "Regular", "Solve 50 problems",
                "volume", _at_least("solved", 50)),
    Achievement("solve_200", "Prolific", "Solve 200 problems",
                "volume", _at_least("solved", 200)),
    Achievement("lessons_25", "Studious", "Finish 25 lessons",
                "volume", _at_least("lessons", 25)),

    Achievement("streak_7", "A week of it", "Reach a 7-day streak",
                "consistency", _at_least("streak_best", 7)),
    Achievement("streak_30", "A month of it", "Reach a 30-day streak",
                "consistency", _at_least("streak_best", 30)),
    Achievement("streak_100", "Hundred days", "Reach a 100-day streak",
                "consistency", _at_least("streak_best", 100)),
    Achievement("days_50", "Half a hundred", "Practise on 50 different days",
                "consistency", _at_least("active_days", 50)),

    Achievement("polyglot", "Polyglot", "Solve problems in two languages",
                "range", _at_least("languages", 2)),
    Achievement("polyglot_3", "Trilingual", "Solve problems in three languages",
                "range", _at_least("languages", 3)),
    Achievement("well_rounded", "Well rounded", "Solve problems in four topics",
                "range", _at_least("topics", 4)),

    Achievement("level_5", "Level 5", "Reach level 5", "level",
                _at_least("level", 5)),
    Achievement("level_10", "Level 10", "Reach level 10", "level",
                _at_least("level", 10)),
    Achievement("level_25", "Level 25", "Reach level 25", "level",
                _at_least("level", 25)),
)

BY_KEY = {a.key: a for a in REGISTRY}


def evaluate(user):
    already = earned_keys(user)
    todo = [a for a in REGISTRY if a.key not in already]
    if not todo:
        return []

    snap = snapshot(user)
    fresh = []
    for ach in todo:
        try:
            if ach.test(snap):
                fresh.append(ach)
        except KeyError:              # a rule referencing an input we dropped
            continue

    if not fresh:
        return []

    for ach in fresh:
        db.session.add(UserAchievement(user_id=user.id, key=ach.key))
    try:
        db.session.commit()
    except IntegrityError:
        # Two workers evaluated the same user at once; the constraint won.
        db.session.rollback()
        return []
    return fresh


def describe(keys):
    return [BY_KEY[k] for k in keys if k in BY_KEY]


def register_cli(app):
    @app.cli.command("backfill-achievements")
    def _backfill():
        """Award badges people already qualify for. Safe to re-run."""
        from .models import User
        users = db.session.execute(db.select(User)).scalars().all()
        total = 0
        for user in users:
            got = evaluate(user)
            total += len(got)
            if got:
                print("%s: %s" % (user.username,
                                  ", ".join(a.key for a in got)))
        print("awarded %d achievements across %d users" % (total, len(users)))
