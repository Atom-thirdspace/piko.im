import uuid
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

from ..models import (Subscription, User, WebhookEvent, _utcnow, active_seat,
                      active_subscription, db, licensed_team,
                      owned_licensed_team, owned_live_classroom)
from .plans import plan_for_product

# Events that carry a subscription object we should store.
SUBSCRIPTION_EVENTS = {
    "subscription.created", "subscription.active", "subscription.updated",
    "subscription.canceled", "subscription.uncanceled", "subscription.revoked",
    "subscription.past_due", "subscription.paused", "subscription.resumed",
    "subscription.cycled", "subscription.migrated",
}


def _dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def already_seen(event_id, event_type):
    db.session.add(WebhookEvent(source="polar", event_id=event_id,
                                event_type=event_type[:64]))
    try:
        db.session.commit()
        return False
    except IntegrityError:
        db.session.rollback()
        return True


def _owner(data):
    customer = data.get("customer") or {}
    external = customer.get("external_id") or data.get("external_customer_id")
    if external:
        try:
            user = db.session.get(User, int(external))
        except (TypeError, ValueError):
            user = None
        if user is not None:
            return user

    # metadata.user_id is our own belt-and-braces from checkout creation.
    meta = data.get("metadata") or {}
    try:
        return db.session.get(User, int(meta.get("user_id")))
    except (TypeError, ValueError):
        return None


def apply_subscription(data, event_type, event_at=None):
    polar_id = data.get("id")
    if not polar_id:
        return None

    row = db.session.execute(
        db.select(Subscription).filter_by(polar_subscription_id=polar_id)
    ).scalar_one_or_none()

    if row is None:
        user = _owner(data)
        if user is None:
            # Nothing to attach it to. The caller logs it; Polar still gets a
            # 202 so it stops retrying a delivery we can never resolve.
            return None
        row = Subscription(user_id=user.id, polar_subscription_id=polar_id)
        db.session.add(row)
    elif row.event_at and event_at and event_at < row.event_at:
        return row              # a straggler from before what we already hold

    customer = data.get("customer") or {}
    row.polar_customer_id = str(data.get("customer_id") or customer.get("id") or "")[:64]
    row.polar_product_id = str(data.get("product_id") or "")[:64]
    row.plan = plan_for_product(row.polar_product_id)[:32]

    # Money comes from what Polar actually charged, never from our own price
    # table - otherwise a price change silently rewrites revenue history.
    row.amount = int(data.get("amount") or 0)
    row.currency = str(data.get("currency") or "usd")[:8]
    row.recurring_interval = str(data.get("recurring_interval") or "month")[:16]
    row.recurring_interval_count = int(data.get("recurring_interval_count") or 1)

    # revoked is terminal, and Polar may still report status=active on it.
    row.status = "canceled" if event_type == "subscription.revoked" \
        else str(data.get("status") or row.status)[:32]

    row.cancel_at_period_end = bool(data.get("cancel_at_period_end"))
    row.current_period_start = _dt(data.get("current_period_start"))
    row.current_period_end = _dt(data.get("current_period_end"))
    row.started_at = _dt(data.get("started_at"))
    row.ends_at = _dt(data.get("ends_at"))
    row.canceled_at = _dt(data.get("canceled_at"))
    row.event_at = event_at or _utcnow()
    db.session.commit()
    sync_classroom(row, data)
    sync_team(row, data)
    return row


def handle(event, event_at=None):
    event_type = event.get("type") or ""
    data = event.get("data") or {}

    if event_type in SUBSCRIPTION_EVENTS:
        row = apply_subscription(data, event_type, event_at=event_at)
        if row is None:
            return "unmatched:" + event_type
        return "%s -> %s" % (event_type, row.status)

    return "ignored:" + event_type


# --------------------------------------------------------------------------- #
# entitlement
# --------------------------------------------------------------------------- #

def is_pro(user):
    return pro_source(user) is not None


# --------------------------------------------------------------------------- #
# complimentary access
# --------------------------------------------------------------------------- #

def grant_manual(user, admin, months=12, note=""):
    ends = _utcnow() + timedelta(days=30 * max(1, int(months)))
    row = Subscription(
        user_id=user.id,
        polar_subscription_id="manual:" + uuid.uuid4().hex,
        source="manual",
        status="active",
        plan="complimentary",
        amount=0,
        note=(note or "")[:2000],
        granted_by_id=admin.id,
        started_at=_utcnow(),
        current_period_start=_utcnow(),
        current_period_end=ends,
        event_at=_utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    return row


def end_manual(row):
    if not row.is_manual:
        return False
    row.status = "canceled"
    row.ends_at = _utcnow()
    row.canceled_at = _utcnow()
    db.session.commit()
    return True

def pro_source(user):
    """Why this user has Pro: (kind, row) or None.

    Order matters. Their own subscription wins, so a teacher who also sits in
    a colleague's class still sees their own billing. Owning a classroom
    comes next - whoever pays for the room is never the one locked out of it.
    """
    sub = active_subscription(user)
    if sub is not None:
        return ("subscription", sub)
    owned_room = owned_live_classroom(user)
    if owned_room is not None:
        return ("classroom_owner", owned_room)

    owned_team = owned_licensed_team(user)
    if owned_team is not None:
        return ("team_owner", owned_team)

    seat = active_seat(user)
    if seat is not None:
        return ("classroom", seat)

    team = licensed_team(user)
    if team is not None:
        return ("team", team)

    return None

def subscription_state(user):
    kind_row = pro_source(user)
    kind = kind_row[0] if kind_row else None
    sub = kind_row[1] if kind == "subscription" else None
    seat = kind_row[1] if kind == "classroom" else None
    room = (kind_row[1] if kind == "classroom_owner"
            else (seat.classroom if seat else None))
    team = kind_row[1] if kind in ("team", "team_owner") else None

    owns = kind in ("classroom_owner", "team_owner")
    group = room or team
    return {
        "pro": kind is not None,
        "via": kind,
        "subscription": sub,
        "classroom": room,
        "team": team,
        # Whichever group is paying, so a template can branch on one value.
        "group": group,
        "group_kind": "team" if team else ("classroom" if room else None),
        # True when the group is theirs, so the UI offers the roster rather
        # than telling them to ask whoever runs it.
        "owns_classroom": kind == "classroom_owner",
        "owns_group": owns,
        "plan": sub.plan if sub else (
            "team" if team else ("classroom" if room else "")),
        "renews_at": sub.current_period_end if sub else (
            room.expires_at if room else (
                team.licence_expires_at if team else None)),
        "ending": bool(sub and sub.cancel_at_period_end),
        "manageable": kind == "subscription" and not sub.is_manual,
    }

CLASSROOM_PLAN = "classroom"
def sync_classroom(row, data):
    from ..models import Classroom, new_join_code

    if row.plan != CLASSROOM_PLAN:
        return None

    seats = int(data.get("seats") or 0)
    cls = db.session.execute(
        db.select(Classroom).filter_by(polar_subscription_id=row.polar_subscription_id)
    ).scalar_one_or_none()

    if cls is None:
        cls = Classroom(owner_id=row.user_id, source="polar",
                        polar_subscription_id=row.polar_subscription_id,
                        join_code=new_join_code(),
                        name="My classroom")
        db.session.add(cls)

    cls.seats = seats
    cls.archived_at = None if row.grants_access else _utcnow()
    db.session.commit()
    return cls


TEAM_PLAN = "team"


def sync_team(row, data):
    """Keep a team's licence in step with the subscription behind it.

    A licence attaches to a roster that already exists rather than creating
    one, so checkout puts the team id in metadata and we look it up here.
    """
    from ..models import Team

    if row.plan != TEAM_PLAN:
        return None

    team = db.session.execute(
        db.select(Team).filter_by(polar_subscription_id=row.polar_subscription_id)
    ).scalar_one_or_none()

    if team is None:
        meta = data.get("metadata") or {}
        try:
            team = db.session.get(Team, int(meta.get("team_id")))
        except (TypeError, ValueError):
            team = None
        # Only the owner's own team, or a crafted metadata value could
        # license somebody else's roster.
        if team is None or team.owner_id != row.user_id:
            return None
        team.polar_subscription_id = row.polar_subscription_id

    team.seats = int(data.get("seats") or 0)
    team.licence_source = "polar" if row.grants_access else "none"
    db.session.commit()
    return team
