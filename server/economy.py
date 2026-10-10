from sqlalchemy.exc import IntegrityError
from .models import CoinEvent, User, _utcnow, db

SOLVE_COINS = {"easy": 5, "medium": 10, "hard": 18}
FALLBACK_SOLVE_COINS = 5
QUEST_COINS = 5
ALL_QUESTS_COINS = 15
BOSS_COINS = {1: 8, 2: 14, 3: 20}
ENDLESS_COINS_PER_100 = 6
STREAK_WEEK_COINS = 25
SPEED_RECORD_COINS = 6

HINT_COST = 15
FREEZE_COST = 60
ARENA_RETRY_COST = 25

LABELS = {
    "solve": "Problem solved",
    "quest": "Daily quest",
    "quest_all": "All quests done",
    "boss": "Boss fight",
    "endless": "Endless run",
    "streak": "Streak milestone",
    "speed": "Personal best",
    "hint": "Hint opened",
    "freeze": "Streak freeze",
    "retry": "Arena retry",
    "cosmetic": "Unlocked",
    "admin": "Adjustment",
}

def balance(user):
    return max(0, user.coin_balance or 0)

def earn(user, amount, reason, ref):
    if user is None or amount <= 0:
        return 0
    try:
        with db.session.begin_nested():
            db.session.add(CoinEvent(user_id=user.id, amount=amount,
                                     reason=reason, ref=str(ref)))
    except IntegrityError:
        return 0

    db.session.execute(
        db.update(User).where(User.id == user.id)
        .values(coin_balance=User.coin_balance + amount)
        .execution_options(synchronize_session=False))
    db.session.commit()
    db.session.refresh(user, attribute_names=["coin_balance"])
    return amount

def spend(user, amount, reason, ref):
    if user is None or amount <= 0:
        return False

    try:
        with db.session.begin_nested():
            db.session.add(CoinEvent(user_id=user.id, amount=-amount,
                                     reason=reason, ref=str(ref)))
    except IntegrityError:
        return False

    charged = db.session.execute(
        db.update(User)
        .where(User.id == user.id, User.coin_balance >= amount)
        .values(coin_balance=User.coin_balance - amount)
        .execution_options(synchronize_session=False)).rowcount

    if not charged:
        db.session.rollback()     # drops the ledger row with it
        return False

    db.session.commit()
    db.session.refresh(user, attribute_names=["coin_balance"])
    return True

def solve_coins(problem):
    return SOLVE_COINS.get(problem.difficulty, FALLBACK_SOLVE_COINS)

def recent(user, limit=12):
    return db.session.execute(
        db.select(CoinEvent).where(CoinEvent.user_id == user.id)
        .order_by(CoinEvent.created_at.desc()).limit(limit)).scalars().all()

def reconcile(user):
    total = db.session.execute(
        db.select(db.func.coalesce(db.func.sum(CoinEvent.amount), 0))
        .where(CoinEvent.user_id == user.id)).scalar() or 0
    total = max(0, int(total))
    drift = total - (user.coin_balance or 0)
    if drift:
        user.coin_balance = total
        db.session.commit()
    return {"balance": total, "drift": drift}

