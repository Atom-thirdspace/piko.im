"""Subscription numbers for the admin page."""

from datetime import timedelta

from ..models import Subscription, User, _utcnow, db

# How many months one billing period covers, for normalising to MRR.
# 30.44 is the mean month length, which keeps a weekly plan honest.
INTERVAL_MONTHS = {"day": 1 / 30.44, "week": 7 / 30.44, "month": 1.0, "year": 12.0}

LIVE = ("active", "trialing")


def monthly_cents(sub):
    """One subscription's contribution to MRR, in minor units."""
    if not sub.amount:
        return 0.0
    months = INTERVAL_MONTHS.get(sub.recurring_interval or "month", 1.0)
    months *= max(1, sub.recurring_interval_count or 1)
    return sub.amount / months if months else 0.0


def _count(*where):
    return db.session.execute(
        db.select(db.func.count()).select_from(Subscription).where(*where)
    ).scalar() or 0


def overview():
    now = _utcnow()
    month_ago = now - timedelta(days=30)

    # Same predicate as active_subscription: status alone would count a
    # lapsed comp as live.
    live = db.session.execute(
        db.select(Subscription).where(
            Subscription.status.in_(LIVE),
            db.or_(Subscription.current_period_end.is_(None),
                   Subscription.current_period_end > now))
    ).scalars().all()

    paid = [s for s in live if not s.is_manual]

    # Summed per currency. Adding USD to EUR would quietly invent revenue.
    mrr = {}
    for sub in paid:
        mrr[sub.currency] = mrr.get(sub.currency, 0.0) + monthly_cents(sub)

    users_total = db.session.execute(
        db.select(db.func.count()).select_from(User)).scalar() or 0

    plans = {}
    for sub in live:
        key = sub.plan or "unknown"
        plans[key] = plans.get(key, 0) + 1

    return {
        "live": len(live),
        "paid": len(paid),
        "comped": len(live) - len(paid),
        "trialing": sum(1 for s in live if s.status == "trialing"),
        "past_due": _count(Subscription.status == "past_due"),
        "ending": sum(1 for s in live if s.cancel_at_period_end),
        "canceled_total": _count(Subscription.status == "canceled"),
        "new_30d": _count(Subscription.created_at >= month_ago),
        "churned_30d": _count(Subscription.status == "canceled",
                              Subscription.canceled_at >= month_ago),
        "mrr": {cur: cents / 100.0 for cur, cents in mrr.items()},
        "arr": {cur: cents * 12 / 100.0 for cur, cents in mrr.items()},
        "arpu": (sum(mrr.values()) / len(paid) / 100.0) if paid else 0.0,
        "conversion": (len(paid) * 100.0 / users_total) if users_total else 0.0,
        "users_total": users_total,
        "plans": sorted(plans.items(), key=lambda kv: -kv[1]),
    }


def _month_starts(months):
    """The first instant of each of the last `months` calendar months."""
    now = _utcnow()
    cursor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    out = [cursor]
    for _ in range(months - 1):
        # Step into the previous month by landing on its last day first;
        # arithmetic on day counts drifts across February.
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        out.append(cursor)
    return list(reversed(out))


def monthly_series(months=6):
    """New vs churned per calendar month, oldest first."""
    starts = _month_starts(months)
    rows = []
    for i, start in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else None
        new_where = [Subscription.created_at >= start]
        churn_where = [Subscription.canceled_at >= start]
        if nxt is not None:
            new_where.append(Subscription.created_at < nxt)
            churn_where.append(Subscription.canceled_at < nxt)
        rows.append({
            "label": start.strftime("%b %Y"),
            "new": _count(*new_where),
            "churned": _count(*churn_where),
        })
    return rows


def recent(limit=10):
    return db.session.execute(
        db.select(Subscription).order_by(Subscription.created_at.desc()).limit(limit)
    ).scalars().all()
