from flask import Blueprint, redirect, render_template, url_for

from . import notify
from .models import Notification, _utcnow, db
from .session import current_user, login_required

notifications_bp = Blueprint("notifications", __name__,
                             url_prefix="/notifications")


@notifications_bp.route("/")
@login_required
def index():
    user = current_user()
    rows = db.session.execute(
        db.select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc()).limit(60)).scalars().all()
    return render_template("notifications.html", rows=rows)


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
