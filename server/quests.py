import random
from dataclasses import dataclass
from typing import Callable

from flask import g, has_request_context

from .models import (PUBLISHED, Enrollment, Lesson, LessonProgress,
                     Problem, ProblemSolve, Unit, XpEvent, db)
from .progress import award_xp, day_bounds, user_today

from .memo import per_request

QUESTS_PER_DAY = 3
ALL_THREE_BONUS = 40

def _solves(user, lo, hi, difficulties=None):
    stmt = (db.select(db.func.count()).select_from(ProblemSolve)
            .where(ProblemSolve.user_id == user.id,
                   ProblemSolve.solved_at >= lo, ProblemSolve.solved_at < hi))
    if difficulties:
        stmt = (stmt.join(Problem, Problem.id == ProblemSolve.problem_id)
                .where(Problem.difficulty.in_(difficulties)))
    return db.session.execute(stmt).scalar() or 0

def _ledger(user, lo, hi, reason):
    return db.session.execute(
        db.select(db.func.count()).select_from(XpEvent)
        .where(XpEvent.user_id == user.id, XpEvent.reason == reason,
               XpEvent.created_at >= lo, XpEvent.created_at < hi)).scalar() or 0

def _lessons(user, lo, hi, kind=None):
    stmt = (db.select(db.func.count()).select_from(LessonProgress)
            .where(LessonProgress.user_id == user.id,
                   LessonProgress.completed_at >= lo,
                   LessonProgress.completed_at < hi))
    if kind:
        stmt = (stmt.join(Lesson, Lesson.id == LessonProgress.lesson_id)
                .where(Lesson.kind == kind))
    return db.session.execute(stmt).scalar() or 0


def _new_topics(user, lo, hi):
    seen_before = (db.select(Problem.topic)
                   .select_from(ProblemSolve)
                   .join(Problem, Problem.id == ProblemSolve.problem_id)
                   .where(ProblemSolve.user_id == user.id,
                          ProblemSolve.solved_at < lo,
                          Problem.topic.isnot(None)))
    return db.session.execute(
        db.select(db.func.count(db.distinct(Problem.topic)))
        .select_from(ProblemSolve)
        .join(Problem, Problem.id == ProblemSolve.problem_id)
        .where(ProblemSolve.user_id == user.id,
               ProblemSolve.solved_at >= lo, ProblemSolve.solved_at < hi,
               Problem.topic.isnot(None),
               Problem.topic.notin_(seen_before))).scalar() or 0


def _goal_hit(user, lo, hi):
    target = user.daily_goal_xp or 0
    if not target:
        return 0
    earned = db.session.execute(
        db.select(db.func.coalesce(db.func.sum(XpEvent.amount), 0))
        .where(XpEvent.user_id == user.id,
               XpEvent.created_at >= lo, XpEvent.created_at < hi)).scalar() or 0
    return 1 if earned >= target else 0

def _unsolved_exists(user, difficulties=None):
    solved = (db.select(ProblemSolve.problem_id)
              .where(ProblemSolve.user_id == user.id))
    stmt = db.select(Problem.id).where(Problem.id.notin_(solved))
    if difficulties:
        stmt = stmt.where(Problem.difficulty.in_(difficulties))
    return db.session.execute(stmt.limit(1)).scalar() is not None 

def _unfinished_lesson_exists(user, kind=None, enrolled_only=False):
    done = (db.select(LessonProgress.lesson_id)
            .where(LessonProgress.user_id == user.id))
    stmt = (db.select(Lesson.id).join(Unit, Unit.id == Lesson.unit_id)
            .where(Lesson.status == PUBLISHED, Unit.status == PUBLISHED,
                   Lesson.id.notin_(done)))
    if kind:
        stmt = stmt.where(Lesson.kind == kind)
    if enrolled_only:
        tracks = (db.select(Enrollment.track_id)
                  .where(Enrollment.user_id == user.id))
        stmt = stmt.where(Unit.track_id.in_(tracks))
    return db.session.execute(stmt.limit(1)).scalar() is not None

def _capability(user):
    return {
        "unsolved": _unsolved_exists(user),
        "unsolved_hard": _unsolved_exists(user, ("medium", "hard")),
        "lesson": _unfinished_lesson_exists(user),
        "lesson_enrolled": _unfinished_lesson_exists(user, enrolled_only=True),
        "quiz": _unfinished_lesson_exists(user, kind="quiz"),
        "goal": (user.daily_goal_xp or 0) > 0,
    }


def capability(user):
    if not has_request_context():
        return _capability(user)
    cache = getattr(g, "_quest_caps", None)
    if cache is None:
        cache = g._quest_caps = {}
    if user.id not in cache:
        cache[user.id] = _capability(user)
    return cache[user.id]


@dataclass(frozen=True)
class Quest:
    key: str
    title: str
    target: int
    reward: int
    count: Callable
    feasible: Callable        # (capability dict) -> bool

REGISTRY = (
    Quest("solve_any", "Solve a problem", 1, 20,
          lambda u, lo, hi: _solves(u, lo, hi),
          lambda c: c["unsolved"]),
    Quest("solve_two", "Solve two problems", 2, 35,
          lambda u, lo, hi: _solves(u, lo, hi),
          lambda c: c["unsolved"]),
    Quest("solve_medium", "Solve a medium or hard problem", 1, 30,
          lambda u, lo, hi: _solves(u, lo, hi, ("medium", "hard")),
          lambda c: c["unsolved_hard"]),
    Quest("clean_solve", "Solve one without opening a hint", 1, 25,
          lambda u, lo, hi: _ledger(u, lo, hi, "no_hints"),
          lambda c: c["unsolved"]),
    Quest("one_shot", "Solve one on your first submission", 1, 30,
          lambda u, lo, hi: _ledger(u, lo, hi, "first_try"),
          lambda c: c["unsolved"]),
    Quest("new_topic", "Solve in a topic you have never solved", 1, 35,
          _new_topics,
          lambda c: c["unsolved"]),
    Quest("lesson_any", "Finish a lesson", 1, 15,
          lambda u, lo, hi: _lessons(u, lo, hi),
          lambda c: c["lesson"]),
    Quest("lesson_track", "Finish a lesson in a track you have started", 1, 20,
          lambda u, lo, hi: _lessons(u, lo, hi),
          lambda c: c["lesson_enrolled"]),
    Quest("quiz", "Pass a quiz", 1, 20,
          lambda u, lo, hi: _lessons(u, lo, hi, kind="quiz"),
          lambda c: c["quiz"]),
    Quest("goal", "Hit your daily XP goal", 1, 15,
          _goal_hit,
          lambda c: c["goal"]),
)

BY_KEY = {q.key: q for q in REGISTRY}


@per_request(lambda user, day : (user.id, day))
def todays_quests(user, day):
    cap = capability(user)
    order = list(REGISTRY)
    random.Random("%s:%d" % (day.isoformat(), user.id)).shuffle(order)

    locked = _paid_keys(user, day)
    picked = [q for q in order if q.key in locked]
    for q in order:
        if len(picked) >= QUESTS_PER_DAY:
            break
        if q.key not in locked and q.feasible(cap):
            picked.append(q)
    return sorted(picked, key=REGISTRY.index)

def _ref(day, key):
    return "%s:%s" % (day.isoformat(), key)

@per_request(lambda user, day: (user.id, day))
def _paid_keys(user, day):
    return {r.split(":", 1)[1] for r in _paid_refs(user, day)} - {"all"}


def _paid_refs(user, day):
    return set(db.session.execute(
        db.select(XpEvent.ref).where(XpEvent.user_id == user.id,
                                     XpEvent.reason == "daily",
                                     XpEvent.ref.like("%s:%%" % day.isoformat()))
    ).scalars())


def board(user, day=None):
    day = day or user_today(user)
    lo, hi = day_bounds(user, day)
    paid = _paid_refs(user, day)
    quests = todays_quests(user, day)

    # "tasks", not "items": Jinja resolves a dict's .items to the method.
    tasks = []
    for q in quests:
        done = min(q.count(user, lo, hi), q.target)
        tasks.append({"key": q.key, "title": q.title, "reward": q.reward,
                      "done": done, "target": q.target,
                      "complete": done >= q.target,
                      "paid": _ref(day, q.key) in paid})

    return {"day": day, "tasks": tasks,
            "finished": sum(1 for i in tasks if i["complete"]),
            "total": len(tasks),
            "all_done": bool(tasks) and all(i["complete"] for i in tasks),
            "bonus": ALL_THREE_BONUS,
            "bonus_paid": _ref(day, "all") in paid}


def sync_board(user, day=None):
    """Pay for anything finished, and hand back the board it was read from.

    One evaluation instead of two. board() is deliberately not cached - a
    request that solves a problem and then reads the board must see the
    solve - so the saving comes from sharing this result, not from a memo.
    """
    day = day or user_today(user)
    state = board(user, day)

    gained = 0
    for task in state["tasks"]:
        if task["complete"] and not task["paid"]:
            got = award_xp(user, task["reward"], "daily",
                           _ref(day, task["key"]))["awarded"]
            if got:
                task["paid"] = True
            gained += got

    if state["all_done"] and not state["bonus_paid"]:
        got = award_xp(user, ALL_THREE_BONUS, "daily",
                       _ref(day, "all"))["awarded"]
        if got:
            state["bonus_paid"] = True
        gained += got
    return gained, state


def sync(user, day=None):
    """Just the payout, for callers with no page to render."""
    return sync_board(user, day)[0]