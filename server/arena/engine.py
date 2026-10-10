import random
from datetime import timedelta

from ..models import (PUBLISHED, Boss, BossQuestion, BossRun, BossRunQuestion,
                      XpEvent, _utcnow, db)
from ..progress import award_xp, day_bounds, user_today
from . import rules
from .grading import is_correct
from ..  import economy

XP_REASON = "boss"

def _pool(boss, size=rules.POOL_SIZE):
    stmt = (db.select(BossQuestion.id)
            .where(BossQuestion.status == PUBLISHED))
    if boss.topic:
        stmt = stmt.where(BossQuestion.topic == boss.topic)
    if boss.difficulty:
        stmt = stmt.where(BossQuestion.difficulty == boss.difficulty)
    ids = list(db.session.execute(stmt).scalars())
    return ids, size

def start(user, boss, mode="boss", stake=rules.DEFAULT_STAKE, raid=None):
    from ..models import active_boss_run

    open_run = active_boss_run(user)
    if open_run is not None:
        return open_run, None

    ids, size = _pool(boss)
    if len(ids) < rules.MIN_POOL:
        return None, "This boss has no question pool yet."

    seed = random.getrandbits(48)
    random.Random(seed).shuffle(ids)
    if stake not in rules.STAKES:
        stake = rules.DEFAULT_STAKE

    run = BossRun(
        user_id=user.id, boss_id=boss.id, seed=seed, plan=ids[:size],
        mode=mode, stake=stake,
        raid_id=raid.id if raid is not None else None,
        # Endless has no boss to kill and no HP to lose - it has lives.
        boss_hp=boss.hp if mode == "boss" else 0,
        player_hp=rules.PLAYER_HP if mode == "boss" else 0,
        lives=rules.ENDLESS_LIVES if mode == "endless" else 0)
    db.session.add(run)
    db.session.commit()
    return run, None

def open_question(run):
    return db.session.execute(
        db.select(BossRunQuestion)
        .where(BossRunQuestion.run_id == run.id,
               BossRunQuestion.answered_at.is_(None))
        .order_by(BossRunQuestion.position.desc()).limit(1)
    ).scalar_one_or_none()


def shuffled_choices(run, question):
    options = list(question.choices or [])
    random.Random(run.seed ^ (question.id * 2654435761)).shuffle(options)
    return options

def serve(run):
    existing = open_question(run)
    if existing is not None:
        return existing

    if run.cursor >= len(run.plan):
        if run.mode != "endless" or not _refill_plan(run):
            return None

    question_id = run.plan[run.cursor]
    question = db.session.get(BossQuestion, question_id)
    run.cursor += 1
    if question is None or question.status != PUBLISHED:
        db.session.commit()
        return serve(run)

    now = _utcnow()
    row = BossRunQuestion(
        run_id=run.id, question_id=question.id, position=run.asked,
        served_at=now,
        deadline_at=now + timedelta(seconds=question.seconds))
    run.asked += 1
    db.session.add(row)
    db.session.commit()
    return row 

def as_payload(run, row):
    question = row.question
    left = (row.deadline_at - _utcnow()).total_seconds()
    body = {
        "question_id": question.id,
        "kind": question.kind,
        "prompt": question.prompt,
        "difficulty": question.difficulty,
        "window": question.seconds,
        "seconds_left": max(0.0, round(left, 2)),
        "position": row.position + 1,
    }
    if question.kind == "choice":
        body["choices"] = [{"key": i, "text": text} for i, text
                           in enumerate(shuffled_choices(run, question))]
    return body

def answer(run, question_id, given, choice_key=None):
    row = open_question(run)
    if row is None or row.question_id != int(question_id or 0):
        return {"stale": True, **state(run)}

    question = row.question
    now = _utcnow()
    late = now > row.deadline_at + timedelta(seconds=rules.GRACE_SECONDS)

    if question.kind == "choice":
        options = shuffled_choices(run, question)
        try:
            given = options[int(choice_key)]
        except (TypeError, ValueError, IndexError):
            given = ""

    hit = (not late) and is_correct(question, given)
    left = max(0.0, (row.deadline_at - now).total_seconds())


    row.answered_at = now
    row.given = (given or "")[:200]
    row.correct = hit

    gained = 0
    if hit:
        if run.mode == "endless":
            gained = rules.endless_points(question.difficulty, left,
                                          question.seconds, run.combo)
            run.score += gained
            row.damage = gained
        else:
            raw = rules.damage_for(question.difficulty, left,
                                   question.seconds, run.combo)
            row.damage = rules.staked_damage(raw, run.stake)
            run.boss_hp = max(0, run.boss_hp - row.damage)
        run.combo += 1
        run.best_combo = max(run.best_combo, run.combo)
        run.correct += 1
        if question.topic:
            from .. import mastery
            mastery.add(run.user, question.topic, mastery.ARENA_POINTS)
    else:
        row.damage = 0
        run.combo = 0
        if run.mode == "endless":
            run.lives = max(0, run.lives - 1)
        else:
            run.player_hp = max(0, run.player_hp
                                - rules.staked_hit(run.boss.attack, run.stake))

        outcome = {
        "stale": False,
        "correct": hit,
        "timed_out": late,
        "damage": row.damage,
        "gained": gained,
        "answer": question.answer,
        "explain": question.explain_md,
    }

    if run.mode == "endless":
        if run.lives <= 0:
            finish(run, "lost")
        else:
            db.session.commit()
    elif run.boss_hp <= 0:
        finish(run, "won")
    elif run.player_hp <= 0:
        finish(run, "lost")
    elif run.cursor >= len(run.plan):
        finish(run, "draw")
    else:
        db.session.commit()

    outcome.update(state(run))
    return outcome


    
def state(run):
    return {"run_id": run.id, "status": run.status, "mode": run.mode,
            "stake": run.stake, "boss_hp": run.boss_hp,
            "boss_hp_max": run.boss.hp, "player_hp": run.player_hp,
            "player_hp_max": rules.PLAYER_HP, "lives": run.lives,
            "score": run.score, "combo": run.combo,
            "best_combo": run.best_combo, "asked": run.asked,
            "hits": run.correct, "xp": run.xp_awarded}


def _paid_today(user):
    lo, hi = day_bounds(user, user_today(user))
    return db.session.execute(
        db.select(db.func.count()).select_from(XpEvent)
        .where(XpEvent.user_id == user.id, XpEvent.reason == XP_REASON,
               XpEvent.created_at >= lo, XpEvent.created_at < hi)).scalar() or 0

def finish(run, status):
    run.status = status
    run.ended_at = _utcnow()

    amount = coins = 0
    if _paid_today(run.user) < rules.PAID_RUNS_PER_DAY:
        if run.mode == "endless":
            amount = run.score // 10
            coins = (run.score // 10) * economy.ENDLESS_COINS_PER_10 // 3
        elif status == "won":
            amount = rules.staked_xp(
                rules.win_xp(run.boss.tier, run.correct == run.asked),
                run.stake)
            coins = economy.BOSS_COINS.get(run.boss.tier, 8)
        elif run.correct >= 3:
            amount = rules.CONSOLATION_XP

    if amount:
        award_xp(run.user, amount, XP_REASON, str(run.id))
        run.xp_awarded = amount
    if coins:
        economy.earn(run.user, coins, "boss", str(run.id))

    db.session.commit()

    if run.raid_id:
        from .. import raids
        raids.contribute(run)

    from .. import quests
    quests.sync(run.user)

    from ..achievements import evaluate
    from .. import cosmetics
    cosmetics.grant_for_achievements(run.user, evaluate(run.user) or [])
    return run

def retry(run):
    if run.status == "active":
        return False, "That fight is still going"
    if not economy.spend(run.user, economy.ARENA_RETRY_COST, "retry",
                         str(run.id)):
        return False, "Not enough coins."

    if run.mode == "endless":
        run.lives = 1
    else:
        run.player_hp = max(1, rules.PLAYER_HP // 2)
    run.status = "active"
    run.ended_at = None
    db.session.commit()
    return True, "Back on your feet."

def forfeit(run):
    if run.status == "active":
        finish(run, "lost")
    return run

def expire_stale(older_than_minutes = 45):
    cutoff = _utcnow() - timedelta(minutes=older_than_minutes)
    rows = db.session.execute(
        db.select(BossRun).where(BossRun.status == "active",
                                 BossRun.started_at < cutoff)).scalars().all()
    for run in rows:
        run.status = "abandoned"
        run.ended_at = _utcnow()
    db.session.commit()
    return len(rows)

def _refill_plan(run):
    ids, _ = _pool(run.boss)
    if not ids:
        return False
    random.Random(run.seed + run.cursor).shuffle(ids)
    asked = {r.question_id for r in run.asked_rows}
    fresh = [i for i in ids if i not in asked]
    if not fresh:
        return False
    run.plan = list(run.plan) + fresh
    db.session.commit()
    return True

def endless_board(limit=20):
    from ..models import User
    rows = db.session.execute(
        db.select(BossRun, User).join(User, User.id == BossRun.user_id)
        .where(BossRun.mode == "endless", BossRun.status != "active",
               User.show_on_leaderboard.is_(True))
        .order_by(BossRun.score.desc(), BossRun.ended_at.asc())
        .limit(limit)).all()
    return [{"rank": i, "user": u, "score": r.score, "hits": r.correct,
             "combo": r.best_combo, "at": r.ended_at}
            for i, (r, u) in enumerate(rows, 1)]
