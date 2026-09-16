from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from ..session import current_user, login_required
from . import service
from .steps import AnswerError

onboarding_bp = Blueprint("onboarding", __name__)

@onboarding_bp.route("/onboarding/start/")
@login_required
def page():
    user = current_user()
    if user.needs_onboarding:                     # username/interest comes first
        return redirect(url_for("accounts.onboarding", next=request.path))
    return render_template("questionnaire.html", user=user)

@onboarding_bp.route("/api/onboarding/state")
@login_required
def state():
    return jsonify(service.state(current_user()))

@onboarding_bp.route("/api/onboarding/answer", methods=["POST"])
@login_required
def answer():
    payload = request.get_json(silent=True) or {}
    key = payload.get("key")
    try:
        return jsonify(service.submit_answer(current_user(), key, payload.get("value")))
    except AnswerError as exc:
        return jsonify(error=str(exc), key=key), 400

@onboarding_bp.route("/api/onboarding/back", methods=["POST"])
@login_required
def back():
    return jsonify(service.back(current_user()))

@onboarding_bp.route("/api/onboarding/placement", methods=["GET", "POST"])
@login_required
def placement_route():
    user = current_user()
    try:
        if request.method == "GET":
            return jsonify(service.start_placement(user))
        payload = request.get_json(silent=True) or {}
        return jsonify(service.grade_placement(user, payload.get("responses")))
    except service.OnboardingError as exc:
        return jsonify(error=str(exc)), 400

@onboarding_bp.route("/api/onboarding/preview")
@login_required
def preview():
    try:
        rec = service.preview(current_user())
    except service.OnboardingError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(recommendation=rec, tracks=service.tracks_for_choice(rec["track_slug"]))

@onboarding_bp.route("/api/onboarding/complete", methods=["POST"])
@login_required
def complete():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(service.complete(current_user(), payload.get("track_slug")))
    except service.OnboardingError as exc:
        code = 503 if str(exc) == "catalog_missing" else 400
        return jsonify(error=str(exc)), code
