import json
import os
from functools import wraps
from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from ..csrf import exempt
from ..models import (Team, _utcnow, db, is_verified_student,
                      owned_teams)
from ..session import current_user, login_required
from . import service
from .client import BillingError, create_checkout, create_portal_session
from .plans import PERKS, PLANS, available, is_configured, product_id
from .webhooks import WebhookError, verify

billing_bp = Blueprint("billing",__name__)

def pro_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login_page", next=request.full_path))
        if not service.is_pro(user):
            flash("That is a Pro feature.", "error")
            return redirect(url_for("billing.pricing"))
        return view(*args, **kwargs)
    return wrapped

@billing_bp.route("/pricing/")
def pricing():
    user = current_user()
    state = service.subscription_state(user) if user else {"pro": False}
    return render_template("billing/pricing.html", plans=available(),
                           perks=PERKS, state=state,
                           configured=is_configured(),
                           my_teams=owned_teams(user) if user else [],
                           student=is_verified_student(user) if user else False)


@billing_bp.route("/billing/checkout/<plan>", methods=["POST"])
@login_required
def checkout(plan):
    pid = product_id(plan)
    if pid is None:
        abort(404)

    user = current_user()
    spec = PLANS.get(plan) or {}
    meta = {"plan": plan}

    # Checked here and not only in the template: this form posts to a URL
    # anyone can type, so the discount has to be enforced server-side.
    if spec.get("requires") == "student" and not is_verified_student(user):
        flash("Verify your academic email before taking the student price.",
              "error")
        return redirect(url_for("students.index"))

    seats = None
    if spec.get("seats"):
        try:
            seats = int(request.form.get("seats") or spec["min_seats"])
        except (TypeError, ValueError):
            seats = spec["min_seats"]
        seats = max(spec["min_seats"], min(seats, spec["max_seats"]))

        if spec.get("group") == "team":
            # A licence attaches to a roster that already exists, and only
            # ever to one the buyer owns.
            try:
                team = db.session.get(Team, int(request.form.get("team_id") or 0))
            except (TypeError, ValueError):
                team = None
            if team is None or team.owner_id != user.id:
                flash("Pick a team you own.", "error")
                return redirect(url_for("billing.pricing"))
            meta["team_id"] = str(team.id)

    elif service.is_pro(user):
        flash("You are already subscribed", "error")
        return redirect(url_for("billing.pricing"))

    success = url_for("billing.success", _external=True) + "?checkout_id={CHECKOUT_ID}"
    try:
        url = create_checkout(pid, user, success, metadata=meta, seats=seats)
    except BillingError as exc:
        current_app.logger.warning("checkout failed for user %s: %s", user.id, exc)
        flash("Could not start the checkout. Try again in a moment.", "error")
        return redirect(url_for("billing.pricing"))

    return redirect(url, code=303)

@billing_bp.route("/billing/success")
@login_required
def success():
    state = service.subscription_state(current_user())
    return render_template("billing/success.html", state=state)

@billing_bp.route("/billing/portal", methods=["POST"])
@login_required
def portal():
    user = current_user() 
    try:
        url = create_portal_session(
            user, return_url=url_for("profile.settings", _external=True))
    except BillingError as exc:
        current_app.logger.warning("portal failed for user %s: %s", user.id, exc)
        flash("Could not open the billing portal. Try again in a moment.", "error")
        return redirect(url_for("profile.settings"))
    return redirect(url, code=303)


@billing_bp.route("/webhooks/polar", methods=["POST"])
@exempt                       # Polar has no session and no CSRF token
def polar_webhook():
    secret = os.environ.get("POLAR_WEBHOOK_SECRET") or ""
    try:
        # request.data, not request.json: the signature covers the exact bytes,
        # and re-serialising the parsed JSON changes whitespace and key order.
        event_id = verify(request.data, request.headers, secret)
    except WebhookError as exc:
        current_app.logger.warning("polar webhook rejected: %s", exc)
        return "", 403

    try:
        event = json.loads(request.data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "", 400

    event_type = event.get("type") or ""
    if service.already_seen(event_id, event_type):
        return "", 202                       # a retry of something we handled

    try:
        outcome = service.handle(event, event_at=_utcnow())
        current_app.logger.info("polar webhook %s: %s", event_id, outcome)
    except Exception:
        # The delivery is already logged as seen, so a 500 would have Polar
        # retry into the dedupe check for ever. Record it and investigate.
        current_app.logger.exception("polar webhook %s failed", event_id)

    return "", 202
