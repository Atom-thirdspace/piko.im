from flask import current_app
from .models import Notification, db, _utcnow

MAX_KEEP = 200

def send(user, kind, title, body="", url="", ref="", email=False):
    if user is None:
        return None
    row = Notification(user_id=user.id, kind=kind, ref=(ref or "")[:64],
                       title=title[:200], body=body or "", url=(url or "")[:300])
    db.session.add(row)
    db.session.commit()

    if email and user.email and user.email_verified_at:
        from . import mailer
        try:
            mailer.send_notification_email(user.email, title, body, url,
                                           name=user.name or user.username)
        except Exception:
            current_app.logger.exception("Failed to send notification email")
    return row

def send_once(user, kind, ref, title, body="", url="", email=False):
    if user is None:
        return None
    seen = db.session.execute(
        db.select(Notification.id).filter_by(user_id=user.id, kind=kind, ref=ref)
    ).scalar()
    if seen is not None:
        return None
    return send(user, kind, title, body, url, ref, email)

def mark_all_read(user):
    db.session.execute(
        db.update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=_utcnow()))
    db.session.commit()

def prune(keep=MAX_KEEP):
    from .models import User
    removed = 0
    for uid in db.session.execute(db.select(User.id)).scalars():
        old = db.session.execute(
            db.select(Notification.id).where(Notification.user_id == uid)
            .order_by(Notification.created_at.desc()).offset(keep)).scalars().all()
        if old:
            db.session.execute(db.delete(Notification)
                               .where(Notification.id.in_(old)))
            removed += len(old)
    db.session.commit()
    return removed


def register_cli(app):
    @app.cli.command("notify-streaks")
    def _streaks():
        from datetime import timedelta

        from .models import User
        from .progress import user_today

        sent = 0
        for user in db.session.execute(
                db.select(User).where(User.streak_days >= 3)).scalars():
            today = user_today(user)
            if user.last_active_date != today - timedelta(days=1):
                continue
            if send_once(user, "streak", today.isoformat(),
                         "Your %d-day streak ends tonight" % user.streak_days,
                         "Anything you finish today keeps it alive.",
                         url="/"):
                sent += 1
        print("warned %d" % sent)

    @app.cli.command("notify-prune")
    def _prune():
        print("removed %d" % prune())

def send_many(users, kind, title, body="", url="", ref="", email=False):
    people = [u for u in users if u is not None]
    if not people:
        return 0

    db.session.add_all([
        Notification(user_id=u.id, kind=kind, ref=(ref or "")[:64],
                     title=title[:200], body=body or "", url=(url or "")[:300])
        for u in people])
    db.session.commit()

    if email:
        from . import mailer
        for user in people:
            if not (user.email and user.email_verified_at):
                continue
            try:
                mailer.send_notification_email(user.email, title, body, url,
                                               name=user.name or user.username)
            except Exception:
                current_app.logger.exception("notify %s failed", user.id)
    return len(people)
