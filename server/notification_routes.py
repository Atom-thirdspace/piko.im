from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, redirect, render_template, url_for

from . import notify
from .models import Notification, _utcnow, db
from .session import current_user, login_required

notifications_bp = Blueprint("notifications", __name__,
                             url_prefix="/notifications")

KEEP = 60

ICONS = {
    "classroom": "\U0001F393",
    "published": "✔",
    "rejected": "✖",
    "raid": "⚔",
    "rival": "⚡",
    "season": "\U0001F3C6",
    "streak": "\U0001F525",
}
DEFAULT_ICON = "\U0001F514"

NAMES = {
    "classroom": "Classroom",
    "published": "Published",
    "rejected": "Changes asked",
    "raid": "Team raid",
    "rival": "Rival",
    "season": "Season",
    "streak": "Streak",
}


def _zone(user):
    try:
        return ZoneInfo(user.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _ago(then, now):
    gap = now - then
    mins = int(gap.total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return "%dm ago" % mins
    if mins < 60 * 24:
        return "%dh ago" % (mins // 60)
    days = mins // (60 * 24)
    if days < 7:
        return "%dd ago" % days
    return then.strftime("%d %b")


def _grouped(rows, user):
    zone = _zone(user)
    now = _utcnow()
    today = now.astimezone(zone).date()
    out = []
    for row in rows:
        day = row.created_at.astimezone(zone).date()
        if day == today:
            label = "Today"
        elif day == today - timedelta(days=1):
            label = "Yesterday"
        elif (today - day).days < 7:
            label = day.strftime("%A")
        else:
            label = day.strftime("%d %B %Y")
        card = {
            "id": row.id,
            "kind": row.kind,
            "icon": ICONS.get(row.kind, DEFAULT_ICON),
            "name": NAMES.get(row.kind, row.kind.replace("_", " ").title()),
            "title": row.title,
            "body": row.body,
            "url": row.url,
            "unread": row.read_at is None,
            "ago": _ago(row.created_at, now),
            "exact": row.created_at.astimezone(zone).strftime("%d %b %Y, %H:%M"),
        }
        if out and out[-1][0] == label:
            out[-1][1].append(card)
        else:
            out.append((label, [card]))
    return out


@notifications_bp.route("/")
@login_required
def index():
    user = current_user()
    rows = db.session.execute(
        db.select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(KEEP)).scalars().all()
    days = _grouped(rows, user)
    return render_template("notifications.html", days=days, keep=KEEP,
                           shown=len(rows),
                           unread=sum(1 for r in rows if r.read_at is None))


@notifications_bp.route("/read", methods=["POST"])
@login_required
def read_all():
    notify.mark_all_read(current_user())
    return redirect(url_for("notifications.index"))


@notifications_bp.route("/<int:row_id>/open", methods=["POST"])
@login_required
def open_one(row_id):
    row = db.session.get(Notification, row_id)
    if row is None or row.user_id != current_user().id:
        return redirect(url_for("notifications.index"))
    if row.read_at is None:
        row.read_at = _utcnow()
        db.session.commit()
    return redirect(row.url or url_for("notifications.index"))
