"""People and teams.

Following is one-directional and needs no approval - the friction of an
accept step buys very little on a learning site, and a mutual follow is
enough to call two people connected. If this ever needs real privacy, the
upgrade is a status column on Follow, not a new table.
"""

import secrets

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from .models import (Follow, Team, TeamMember, User, db, find_by_username)
from .progress import level_for_xp
from .session import current_user, is_safe_next, login_required
from .validators import (INTERESTS, MAX_TEAM_MEMBERS, MAX_TEAMS_PER_USER,
                         slugify, validate_blurb, validate_team_name,
                         validate_team_slug)

community_bp = Blueprint("community", __name__)

PAGE_SIZE = 24
SORTS = {"active": "Recently active", "xp": "Most XP", "new": "Newest"}
VISIBILITIES = {"open": "Anyone can join",
                "code": "Needs a join code",
                "closed": "Owner adds people"}


def _page():
    try:
        return max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        return 1

def _paginate(stmt, page, size=PAGE_SIZE):
        total = db.session.execute(
        db.select(db.func.count()).select_from(stmt.subquery())
        ).scalar() or 0
        rows = db.session.execute(stmt.limit(size).offset((page - 1) * size)).scalars().all()
        return rows, {"page": page, "pages": max(1, -(-total // size)), "total": total}


def _like(term):
    """A LIKE pattern with the wildcards escaped - otherwise a search for
    "100%" matches every row in the table."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


def _visible():
    return (User.username.isnot(None), User.discoverable.is_(True))


def following_ids(user):
    if user is None:
        return set()
    return set(db.session.execute(
        db.select(Follow.followee_id).where(Follow.follower_id == user.id)
    ).scalars())

def follower_ids(user):
     if user is None:
          return set()
     return set(db.session.execute(
        db.select(Follow.follower_id).where(Follow.followee_id == user.id)
     ).scalars())

def follow_counts(user):
    followers = db.session.execute(
        db.select(db.func.count()).select_from(Follow)
        .where(Follow.followee_id == user.id)).scalar() or 0
    following = db.session.execute(
        db.select(db.func.count()).select_from(Follow)
        .where(Follow.follower_id == user.id)).scalar() or 0
    return {"followers": followers, "following": following}

def _card(u, following, followers):
     return {"id": u.id, "username": u.username, "name": u.name or u.username,
            "avatar_url": u.avatar_url, "bio": u.bio or "",
            "level": level_for_xp(u.xp_total or 0), "xp": u.xp_total or 0,
            "streak": u.streak_days or 0, "interests": u.interest_keys,
            "you_follow": u.id in following,
            "follows_you": u.id in followers}


def _team_xp_column():
    return (db.select(db.func.coalesce(db.func.sum(User.xp_total), 0))
            .select_from(TeamMember).join(User, User.id == TeamMember.user_id)
            .where(TeamMember.team_id == Team.id)
            .correlate(Team).scalar_subquery())


def _member_count_column():
    return (db.select(db.func.count()).select_from(TeamMember)
            .where(TeamMember.team_id == Team.id)
            .correlate(Team).scalar_subquery())

def membership(team, user):
    if user is None:
        return None
    return db.session.execute(
        db.select(TeamMember).filter_by(team_id=team.id, user_id=user.id)
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# people
# --------------------------------------------------------------------------- #

@community_bp.route("/community/")
def index():
    viewer = current_user()
    q = (request.args.get("q") or "").strip()
    interest = request.args.get("interest") or ""
    sort = request.args.get("sort") if request.args.get("sort") in SORTS else "active"

    stmt = db.select(User).where(*_visible())
    if viewer is not None:
        stmt = stmt.where(User.id != viewer.id)
    if q:
        stmt = stmt.where(db.or_(User.username.ilike(_like(q)),
                                 User.name.ilike(_like(q))))
    if interest:
        stmt = stmt.where(User.interests.any(interest))

    order = {"xp": (User.xp_total.desc(),),
             "new": (User.created_at.desc(),),
             "active": (User.last_login_at.desc(),)}[sort]
    stmt = stmt.order_by(*order, User.id.asc())

    people, pager = _paginate(stmt, _page())
    following, followers = following_ids(viewer), follower_ids(viewer)

    teams = db.session.execute(
        db.select(Team, _member_count_column().label("members"),
                  _team_xp_column().label("xp"))
        .where(Team.visibility != "closed")
        .order_by(db.desc("xp")).limit(6)
    ).all()

    return render_template(
        "community.html",
        people=[_card(u, following, followers) for u in people],
        pager=pager, q=q, interest=interest, sort=sort, sorts=SORTS,
        interests=INTERESTS, teams=teams, viewer=viewer)


@community_bp.route("/community/follow/<username>", methods=["POST"])
@login_required
def follow(username):
    viewer = current_user()
    target = find_by_username(username)
    if target is None or target.id == viewer.id:
        abort(404)

    existing = db.session.execute(
        db.select(Follow).filter_by(follower_id=viewer.id, followee_id=target.id)
    ).scalar_one_or_none()

    if existing is None:
        db.session.add(Follow(follower_id=viewer.id, followee_id=target.id))
    else:
        db.session.delete(existing)          # the button is a toggle
    db.session.commit()

    back = request.form.get("next") or ""
    return redirect(back if is_safe_next(back) else url_for("community.index"))


# --------------------------------------------------------------------------- #
# teams
# --------------------------------------------------------------------------- #

def _slug_taken(slug):
    return db.session.execute(
        db.select(Team.id).filter_by(slug=slug)
    ).scalar_one_or_none() is not None


def _get_team(slug):
    team = db.session.execute(
        db.select(Team).filter_by(slug=slug)).scalar_one_or_none()
    if team is None:
        abort(404)
    return team


def _member_rows(team):
    return db.session.execute(
        db.select(TeamMember, User).join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team.id)
        .order_by(TeamMember.role.desc(), User.xp_total.desc())
    ).all()


def _owned_count(user):
    return db.session.execute(
        db.select(db.func.count()).select_from(TeamMember)
        .where(TeamMember.user_id == user.id, TeamMember.role == "owner")
    ).scalar() or 0


@community_bp.route("/teams/")
def teams():
    q = (request.args.get("q") or "").strip()
    stmt = (db.select(Team, _member_count_column().label("members"),
                      _team_xp_column().label("xp"))
            .where(Team.visibility != "closed"))
    if q:
        stmt = stmt.where(db.or_(Team.name.ilike(_like(q)),
                                 Team.slug.ilike(_like(q))))
    rows = db.session.execute(stmt.order_by(db.desc("xp")).limit(60)).all()

    mine = []
    viewer = current_user()
    if viewer is not None:
        mine = db.session.execute(
            db.select(Team).join(TeamMember, TeamMember.team_id == Team.id)
            .where(TeamMember.user_id == viewer.id)
            .order_by(TeamMember.joined_at.desc())
        ).scalars().all()

    return render_template("teams.html", rows=rows, mine=mine, q=q)


@community_bp.route("/teams/new", methods=["GET", "POST"])
@login_required
def team_new():
    user = current_user()
    if _owned_count(user) >= MAX_TEAMS_PER_USER:
        flash("You already run %d teams. Hand one over or close it first."
              % MAX_TEAMS_PER_USER, "error")
        return redirect(url_for("community.teams"))

    if request.method == "GET":
        return render_template("team_form.html", team=None, errors={}, form={},
                               visibilities=VISIBILITIES)

    form = request.form
    name = (form.get("name") or "").strip()
    slug = (form.get("slug") or "").strip().lower() or slugify(name)
    blurb = (form.get("blurb") or "").strip()
    visibility = (form.get("visibility") if form.get("visibility") in VISIBILITIES
                  else "open")

    errors = {}
    for field, err in (("name", validate_team_name(name)),
                       ("blurb", validate_blurb(blurb)),
                       ("slug", validate_team_slug(slug, _slug_taken))):
        if err:
            errors[field] = err
    if errors:
        return render_template("team_form.html", team=None, errors=errors,
                               form=form, visibilities=VISIBILITIES), 400

    team = Team(slug=slug, name=name, blurb=blurb, visibility=visibility,
                owner_id=user.id,
                join_code=secrets.token_hex(4) if visibility == "code" else "")
    db.session.add(team)
    db.session.flush()                      # need the id for the first membership
    db.session.add(TeamMember(team_id=team.id, user_id=user.id, role="owner"))
    db.session.commit()

    flash("Team created.", "success")
    return redirect(url_for("community.team_detail", slug=team.slug))


@community_bp.route("/teams/<slug>/")
def team_detail(slug):
    team = _get_team(slug)
    mine = membership(team, current_user())

    if team.visibility == "closed" and mine is None:
        abort(404)                          # a closed team is not browsable

    members = _member_rows(team)
    total_xp = sum((u.xp_total or 0) for _, u in members)

    return render_template(
        "team_detail.html", team=team, members=members, mine=mine,
        total_xp=total_xp, level=level_for_xp(total_xp),
        is_owner=mine is not None and mine.role == "owner",
        full=len(members) >= MAX_TEAM_MEMBERS,
        visibilities=VISIBILITIES)


@community_bp.route("/teams/<slug>/join", methods=["POST"])
@login_required
def team_join(slug):
    team = _get_team(slug)
    user = current_user()

    if membership(team, user) is not None:
        return redirect(url_for("community.team_detail", slug=team.slug))
    if team.visibility == "closed":
        abort(404)

    count = db.session.execute(
        db.select(db.func.count()).select_from(TeamMember)
        .where(TeamMember.team_id == team.id)).scalar() or 0
    if count >= MAX_TEAM_MEMBERS:
        flash("That team is full.", "error")
        return redirect(url_for("community.team_detail", slug=team.slug))

    if team.visibility == "code":
        given = (request.form.get("join_code") or "").strip()
        if not secrets.compare_digest(given, team.join_code or ""):
            flash("That join code is not right.", "error")
            return redirect(url_for("community.team_detail", slug=team.slug))

    db.session.add(TeamMember(team_id=team.id, user_id=user.id))
    db.session.commit()
    flash("You are in.", "success")
    return redirect(url_for("community.team_detail", slug=team.slug))


@community_bp.route("/teams/<slug>/leave", methods=["POST"])
@login_required
def team_leave(slug):
    team = _get_team(slug)
    mine = membership(team, current_user())
    if mine is None:
        return redirect(url_for("community.team_detail", slug=team.slug))
    if mine.role == "owner":
        # Otherwise the team is left with nobody who can administer it.
        flash("Hand the team to someone else before you leave.", "error")
        return redirect(url_for("community.team_detail", slug=team.slug))

    db.session.delete(mine)
    db.session.commit()
    flash("You left the team.", "success")
    return redirect(url_for("community.teams"))


@community_bp.route("/teams/<slug>/settings", methods=["POST"])
@login_required
def team_settings(slug):
    team = _get_team(slug)
    mine = membership(team, current_user())
    if mine is None or mine.role != "owner":
        abort(404)

    form = request.form
    name = (form.get("name") or "").strip()
    blurb = (form.get("blurb") or "").strip()
    visibility = (form.get("visibility") if form.get("visibility") in VISIBILITIES
                  else team.visibility)

    err = validate_team_name(name) or validate_blurb(blurb)
    if err:
        flash(err, "error")
        return redirect(url_for("community.team_detail", slug=team.slug))

    team.name, team.blurb, team.visibility = name, blurb, visibility
    if visibility == "code" and not team.join_code:
        team.join_code = secrets.token_hex(4)
    if form.get("rotate_code"):
        team.join_code = secrets.token_hex(4)
    db.session.commit()

    flash("Team updated.", "success")
    return redirect(url_for("community.team_detail", slug=team.slug))


@community_bp.route("/teams/<slug>/members/<int:user_id>/remove", methods=["POST"])
@login_required
def team_remove(slug, user_id):
    team = _get_team(slug)
    mine = membership(team, current_user())
    if mine is None or mine.role != "owner" or user_id == current_user().id:
        abort(404)

    row = db.session.execute(
        db.select(TeamMember).filter_by(team_id=team.id, user_id=user_id)
    ).scalar_one_or_none()
    if row is not None:
        db.session.delete(row)
        db.session.commit()
        flash("Removed.", "success")
    return redirect(url_for("community.team_detail", slug=team.slug))


@community_bp.route("/teams/<slug>/transfer", methods=["POST"])
@login_required
def team_transfer(slug):
    team = _get_team(slug)
    mine = membership(team, current_user())
    if mine is None or mine.role != "owner":
        abort(404)

    try:
        target_id = int(request.form.get("user_id") or 0)
    except (TypeError, ValueError):
        target_id = 0
    target = db.session.execute(
        db.select(TeamMember).filter_by(team_id=team.id, user_id=target_id)
    ).scalar_one_or_none()
    if target is None or target.id == mine.id:
        flash("Pick someone who is already in the team.", "error")
        return redirect(url_for("community.team_detail", slug=team.slug))

    # The new owner may already be at their own team limit; let it through
    # rather than stranding this team with an owner who wants out.
    mine.role, target.role = "member", "owner"
    team.owner_id = target.user_id
    db.session.commit()
    flash("Team handed over.", "success")
    return redirect(url_for("community.team_detail", slug=team.slug))


@community_bp.route("/teams/<slug>/delete", methods=["POST"])
@login_required
def team_delete(slug):
    team = _get_team(slug)
    mine = membership(team, current_user())
    if mine is None or mine.role != "owner":
        abort(404)
    if (request.form.get("confirm") or "").strip() != team.slug:
        flash("Type the team address to confirm.", "error")
        return redirect(url_for("community.team_detail", slug=team.slug))

    db.session.delete(team)                 # memberships cascade
    db.session.commit()
    flash("Team deleted.", "success")
    return redirect(url_for("community.teams"))
