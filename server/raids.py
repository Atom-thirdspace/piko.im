from datetime import timedelta

from .models import (Boss, Raid, RaidContribution, Team, TeamMember, _utcnow,
                     db, open_raid)

HP_PER_MEMBER = 900
HP_FLOOR = 1200
LENGTH_DAYS = 7

WIN_COINS = 120
PARTICIPATION_COINS = 25
MIN_DAMAGE_TO_PAY = 100

def hp_for(team):
    return max(HP_FLOOR, HP_PER_MEMBER * max(1, len(team.members)))

def start(team, boss):
    existing = open_raid(team)
    if existing is not None:
        return existing, None

    hp = hp_for(team)
    row = Raid(team_id=team.id, boss_id=boss.id, hp_total=hp, hp_left=hp,
               ends_at=_utcnow() + timedelta(days=LENGTH_DAYS))
    db.session.add(row)
    db.session.commit()

    from . import notify
    notify.send_many([m.user for m in team.members], "raid",
                     "%s has appeared" % boss.name,
                     body="%s is raiding. %d HP, %d days."
                          % (team.name, hp, LENGTH_DAYS),
                     url="/teams/%s/raid" % team.slug,
                     ref="raid:%d" % row.id)
    return row, None


def contribute(run):
    raid = db.session.get(Raid, run.raid_id)
    if raid is None or raid.status != "open":
        return None

    dealt = sum(r.damage for r in run.asked_rows)
    if dealt <= 0:
        return None

    row = db.session.execute(
        db.select(RaidContribution).filter_by(raid_id=raid.id,
                                              user_id=run.user_id)
    ).scalar_one_or_none()
    if row is None:
        row = RaidContribution(raid_id=raid.id, user_id=run.user_id)
        db.session.add(row)

    row.damage += dealt
    row.fights += 1
    raid.hp_left = max(0, raid.hp_left - dealt)
    db.session.commit()

    if raid.hp_left <= 0:
        close(raid, "won")
    return dealt

def board(raid):
    rows = db.session.execute(
        db.select(RaidContribution)
        .where(RaidContribution.raid_id == raid.id)
        .order_by(RaidContribution.damage.desc())).scalars().all()
    total = sum(r.damage for r in rows) or 1
    return [{"rank": i, "user": r.user, "damage": r.damage,
             "fights": r.fights, "share": r.damage / total}
            for i, r in enumerate(rows, 1)]

def close(raid,status):
    if raid.status != "open":
        return False

    raid.status = status
    raid.closed_at = _utcnow()
    db.session.commit()

    from . import economy, notify
    for place in board(raid):
        if place["damage"] < MIN_DAMAGE_TO_PAY:
            continue
        payout = WIN_COINS if status == "won" else PARTICIPATION_COINS
        economy.earn(place["user"], payout, "raid", str(raid.id))
        notify.send_once(
            place["user"], "raid", str(raid.id),
            "%s %s" % (raid.boss.name,
                       "has fallen" if status == "won" else "survived"),
            body="You dealt %d damage - %d%% of the total."
                 % (place["damage"], round(100 * place["share"])),
            url="/teams/%s/raid" % raid.team.slug)
    return True

def expire_stale():
    rows = db.session.execute(
        db.select(Raid).where(Raid.status == "open",
                              Raid.ends_at <= _utcnow())).scalars().all()
    for raid in rows:
        close(raid, "failed")
    return len(rows)


def register_cli(app):
    @app.cli.command("raids-expire")
    def _expire():
        print("closed %d" % expire_stale())