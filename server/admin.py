import json
import os
from datetime import timedelta
from functools import wraps
from uuid import uuid4
from flask import (Blueprint, Response, abort, current_app, flash, jsonify,
                   redirect, render_template, request, url_for, session)

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from .judge import LANGUAGES, TestCase, judge
from .learning.seed import seed_catalog
from .models import (AdminAction, DeletionRequest, Enrollment, Lesson, LessonProgress,
                     OAuthIdentity, Problem, ProblemTest, Submission, Track, Unit,
                     User, XpEvent, db, delete_account, mark_email_verified,
                     reject_deletion_request, TutorMessage, unlink_identity, Post,
                     _utcnow, replace_test_results, Report, REPORT_REASON_LABELS,
                     Team, open_report_count, SimilarityFlag,
                     GeneratedProblem, publish_generated, Contest, ContestEntry, ContestProblem)
from . import notify
from .oauth import PROVIDERS
from .progress import level_progress
from .session import current_user, is_safe_next
from .validators import (DELETION_REASON_LABELS, SLUG_RE, slugify,
                         validate_post)
from .admin_code import send_code, verify_code
from .admin_gate import (MAX_FAILURES, admin_email_required, admin_required,
                         admin_emails, gate_ready, is_admin, lock_session,
                         lockout_minutes_left, record_failure,
                         recent_failures, session_unlocked, unlock_methods,
                         unlock_session)
from .webauthn_keys import KeyError_ as WebAuthnError
from .webauthn_keys import begin_authentication, finish_authentication
from .authors.invites import MAX_TTL_DAYS, create_invite, revoke
from .billing import service as billing_service
from .billing import stats as billing_stats
from .billing.client import (BillingError, cancel_subscription,
                             get_subscription, revoke_subscription)
from .mailer import send_author_invite_email
from .models import (DRAFT, PUBLISHED, REVIEW, SUB_GRANTING, VERIFY_MONTHS,
                     AuthorInvite, AuthorInviteUse, Classroom,
                     StudentVerification, Subscription, Team, _utcnow,
                     new_join_code)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _xp_override(raw):
    raw = (raw or "").strip() if isinstance(raw, str) else raw
    if raw is None or raw == "":
        return None
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return None

PAGE_SIZE = 25

NAV = [("admin.overview", "Overview"), ("admin.users", "Users"),
       ("admin.deletions", "Deletions"),
       ("admin.problems", "Problems"), ("admin.submissions", "Submissions"),
       ("admin.content", "Content"), ("admin.lessons", "Lessons"),
       ("admin.blog", "Blog"),
       ("admin.tutor", "Tutor"),
       ("admin.system", "System"),
       ("admin.audit", "Audit log"),
       ("admin.reports","Reports"),
       ("admin.similarity", "Similarity"),
       ("admin.generated", "Generated"),
       ("admin.authors", "Authors"), ("admin.review", "Review"),
       ("admin.subscriptions", "Subscriptions"),
       ("admin.classrooms", "Classrooms"),
       ("admin.students", "Students"),
       ("admin.contests", "Contests"),
       ]


@admin_bp.context_processor
def _nav():
    return {"admin_nav" : NAV, "admin_active": request.endpoint}

def log_action(action, target ="", detail=""):
    db.session.add(AdminAction(admin_id=current_user().id, action=action, target=str(target)[:120], detail=str(detail)[:500]))
    db.session.commit()

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


def _count(model, *where):
    return db.session.execute(
        db.select(db.func.count()).select_from(model).where(*where)
    ).scalar() or 0


def _get_or_404(model, pk):
    row = db.session.get(model, pk)
    if row is None:
        abort(404)
    return row

@admin_bp.route("/")
@admin_required
def overview():
    counts = {
        "users": _count(User),
        "unverified": _count(User, User.email_verified_at.is_(None)),
        "problems": _count(Problem),
        "submissions": _count(Submission),
        "accepted": _count(Submission, Submission.verdict == "accepted"),
        "lessons_done": _count(LessonProgress),
    }

    recent_users = db.session.execute(
        db.select(User).order_by(User.created_at.desc()).limit(8)
    ).scalars().all()
    recent_subs = db.session.execute(
        db.select(Submission).order_by(Submission.created_at.desc()).limit(8)
    ).scalars().all()
    verdicts = db.session.execute(
        db.select(Submission.verdict, db.func.count())
        .group_by(Submission.verdict).order_by(db.func.count().desc())
    ).all()
    return render_template("admin/overview.html", counts=counts, verdicts=verdicts,
                           recent_users=recent_users, recent_subs=recent_subs)

@admin_bp.route("/users/")
@admin_required
def users():
    q = (request.args.get("q") or "").strip()
    only = request.args.get("filter") or ""


    stmt = db.select(User).order_by(User.created_at.desc())
    if q:
        like = "%%%s%%" % q.lower()
        stmt = stmt.where(or_(db.func.lower(User.email).like(like),
                              db.func.lower(User.username).like(like),
                              db.func.lower(User.name).like(like)))

    if only == "unverified":
         stmt = stmt.where(User.email_verified_at.is_(None))
    elif only == "oauth":
        stmt = stmt.where(User.password_hash.is_(None))

    rows, pager = _paginate(stmt, _page())
    return render_template("admin/users.html", users=rows, pager_=pager, q=q,
                           only=only, admin_set=admin_emails())

@admin_bp.route("/users/<int:user_id>/")
@admin_required
def user_detail(user_id):
    user = _get_or_404(User, user_id)
    identities = db.session.execute(
        db.select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)
    ).scalars().all()
    submissions = db.session.execute(
        db.select(Submission).where(Submission.user_id == user.id)
        .order_by(Submission.created_at.desc()).limit(10)
    ).scalars().all()
    xp_events = db.session.execute(
        db.select(XpEvent).where(XpEvent.user_id == user.id)
        .order_by(XpEvent.created_at.desc()).limit(10)
    ).scalars().all()
    enrollments = db.session.execute(
        db.select(Enrollment).where(Enrollment.user_id == user.id)
    ).scalars().all()
    return render_template(
        "admin/user_detail.html", u=user, identities=identities,
        submissions=submissions, xp_events=xp_events, enrollments=enrollments,
        progress=level_progress(user.xp_total or 0),
        provider_labels={n: c["label"] for n, c in PROVIDERS.items()},
        is_target_admin=is_admin(user),
    )

@admin_bp.route("/users/<int:user_id>/verify", methods=["POST"])
@admin_required
def user_verify(user_id):
    user = _get_or_404(User, user_id)
    mark_email_verified(user)
    log_action("verify_email", user.id, user.email)
    flash("%s marked verified." % user.email, "success")
    return redirect(url_for("admin.user_detail", user_id=user.id))


@admin_bp.route("/users/<int:user_id>/send-verification", methods=["POST"])
@admin_required
def user_send_verification(user_id):
    from .accounts import _send_verification

    user = _get_or_404(User, user_id)
    if _send_verification(user):
        log_action("send_verification", user_id, user.email)
        flash("Confirmation email sent to %s." % user.email, "success")
    else:
        flash("Send failed - check RESEND_API_KEY and the logs.", "error")
    return redirect(url_for("admin.user_detail", user_id = user.id))

@admin_bp.route("/users/<int:user_id>/xp", methods=["POST"])
@admin_required
def user_xp(user_id):
    user = _get_or_404(User, user_id)
    try:
        amount = int(request.form.get("amount") or 0)
    except ValueError:
        amount = 0
    note = (request.form.get("note") or "").strip()

    if amount == 0:
        flash("Enter a non-zero amount.", "error")
        return redirect(url_for("admin.user_detail", user_id=user.id))

    db.session.add(XpEvent(user_id=user.id, amount=amount, reason="admin",
                           ref=uuid4().hex))
    user.xp_total = max(0, (user.xp_total or 0) + amount)
    db.session.commit()
    log_action("adjust_xp", user.id, "%+d XP (%s)" % (amount, note or "no note"))
    flash("%+d XP applied." % amount, "success")
    return redirect(url_for("admin.user_detail", user_id=user.id))


@admin_bp.route("/users/<int:user_id>/reset-streak", methods=["POST"])
@admin_required
def user_reset_streak(user_id):
    user = _get_or_404(User, user_id)
    user.streak_days = 0
    user.last_active_date = None
    db.session.commit()
    log_action("reset_streak", user.id, user.email)
    flash("Streak reset.", "success")
    return redirect(url_for("admin.user_detail", user_id=user.id))

@admin_bp.route("/users/<int:user_id>/unlink/<provider>", methods=["POST"])
@admin_required
def user_unlink(user_id, provider):
    user = _get_or_404(User, user_id)
    # Same guard the user's own settings page applies: don't lock anyone out.
    identities = db.session.execute(
        db.select(OAuthIdentity).where(OAuthIdentity.user_id == user.id)
    ).scalars().all()
    if not user.password_hash and len(identities) <= 1:
        flash("That's their only way in - set a password first.", "error")
    else:
        unlink_identity(user, provider)
        log_action("unlink_identity", user.id, provider)
        flash("%s disconnected." % provider, "success")
    return redirect(url_for("admin.user_detail", user_id=user.id))

@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id):
    user = _get_or_404(User, user_id)
    if user.id == current_user().id:
        flash("Delete your own account from your settings page, not here.", "error")
        return redirect(url_for("admin.user_detail", user_id=user.id))
    if (request.form.get("confirm") or "").strip().lower() != (user.username or ""):
        flash("Type their username exactly to confirm.", "error")
        return redirect(url_for("admin.user_detail", user_id=user.id))

    email = user.email
    log_action("delete_user", user.id, email)     # log before the row disappears
    delete_account(user)
    flash("%s deleted." % email, "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/problems/")
@admin_required
def problems():
    q = (request.args.get("q") or "").strip()
    stmt = db.select(Problem).order_by(Problem.created_at.desc())
    if q:
        like = "%%%s%%" % q.lower()
        stmt = stmt.where(or_(db.func.lower(Problem.slug).like(like),
                              db.func.lower(Problem.title).like(like)))
    rows, pager = _paginate(stmt, _page())
    counts = {p.id: len(p.tests) for p in rows}
    return render_template("admin/problems.html", problems=rows, pager_=pager,
                           q=q, test_counts=counts)

@admin_bp.route("/problems/new", methods=["GET", "POST"])
@admin_bp.route("/problems/<int:problem_id>/edit", methods=["GET", "POST"])
@admin_required
def problem_form(problem_id=None):
    problem = _get_or_404(Problem, problem_id) if problem_id else None

    if request.method == "GET":
        return render_template("admin/problem_form.html", p=problem, errors={}, form={})

    form = request.form
    errors = {}
    slug = (form.get("slug") or "").strip().lower()
    title = (form.get("title") or "").strip()

    if not slug:
        errors["slug"] = "Give it a slug"
    else:
        clash = db.session.execute(
            db.select(Problem).filter_by(slug=slug)
        ).scalar_one_or_none()
        if clash is not None and (problem is None or clash.id != problem.id):
            errors["slug"] = "Another problem already uses that slug."
    if not title:
        errors["title"] = "Give it a title."
    if errors:
        return render_template("admin/problem_form.html", p=problem,
                               errors=errors, form=form), 400

    if problem is None:
        problem = Problem(slug=slug, status=PUBLISHED, published_at=_utcnow())
        db.session.add(problem)

    problem.slug = slug
    problem.title = title
    problem.statement_md = form.get("statement_md") or ""
    problem.difficulty = form.get("difficulty") or "easy"
    problem.topic = (form.get("topic") or "").strip() or None
    problem.xp_override = _xp_override(form.get("xp"))
    problem.time_limit_sec = float(form.get("time_limit_sec") or 2.0)
    problem.memory_mb = int(form.get("memory_mb") or 256)
    db.session.commit()

    log_action("save_problem", problem.id, problem.slug)
    flash("Problem saved.", "success")
    return redirect(url_for("admin.problem_form", problem_id=problem.id))


@admin_bp.route("/problems/<int:problem_id>/tests", methods=["POST"])
@admin_required
def problem_add_test(problem_id):
    problem = _get_or_404(Problem, problem_id)
    db.session.add(ProblemTest(
        problem_id=problem.id,
        position=len(problem.tests),
        stdin=request.form.get("stdin") or "",
        expected_stdout=request.form.get("expected_stdout") or "",
        is_sample=bool(request.form.get("is_sample")),
    ))
    db.session.commit()
    log_action("add_test", problem.id, problem.slug)
    return redirect(url_for("admin.problem_form", problem_id=problem.id))

@admin_bp.route("/problems/<int:problem_id>/tests/<int:test_id>/delete", methods=["POST"])
@admin_required
def problem_delete_test(problem_id, test_id):
    test = _get_or_404(ProblemTest, test_id)
    if test.problem_id != problem_id:
        abort(404)
    db.session.delete(test)
    db.session.commit()
    log_action("delete_test", problem_id, "test %s" % test_id)
    return redirect(url_for("admin.problem_form", problem_id=problem_id))

@admin_bp.route("/problems/<int:problem_id>/delete", methods=["POST"])
@admin_required
def problem_delete(problem_id):
    problem = _get_or_404(Problem, problem_id)
    if (request.form.get("confirm") or "").strip().lower() != problem.slug:
        flash("Type the slug exactly to confirm.", "error")
        return redirect(url_for("admin.problem_form", problem_id=problem.id))

    log_action("delete_problem", problem.id, problem.slug)
    db.session.delete(problem)      # tests cascade; lessons keep a NULL problem_id
    db.session.commit()
    flash("Problem deleted.", "success")
    return redirect(url_for("admin.problems"))

@admin_bp.route("/submissions/")
@admin_required
def submissions():
    verdict = request.args.get("verdict") or ""
    username = (request.args.get("user") or "").strip().lower()

    stmt = db.select(Submission).order_by(Submission.created_at.desc())
    if verdict:
        stmt = stmt.where(Submission.verdict == verdict)
    if username:
        stmt = stmt.join(User).where(db.func.lower(User.username) == username)

    rows, pager = _paginate(stmt, _page())
    verdict_options = db.session.execute(
        db.select(Submission.verdict).distinct().order_by(Submission.verdict)
    ).scalars().all()
    return render_template("admin/submissions.html", submissions=rows, pager_=pager,
                           verdict=verdict, username=username,
                           verdict_options=verdict_options)

@admin_bp.route("/submissions/<int:sub_id>/")
@admin_required
def submission_detail(sub_id):
    return render_template("admin/submission_detail.html", s=_get_or_404(Submission, sub_id))


@admin_bp.route("/submissions/<int:sub_id>/rejudge", methods=["POST"])
@admin_required
def submission_rejudge(sub_id):
    sub = _get_or_404(Submission, sub_id)
    problem = sub.problem
    if problem is None or not problem.tests:
        flash("That problem has no tests to run.", "error")
        return redirect(url_for("admin.submission_detail", sub_id=sub.id))
    if sub.language not in LANGUAGES:
        flash("Language %s is no longer supported." % sub.language, "error")
        return redirect(url_for("admin.submission_detail", sub_id=sub.id))

    tests = [TestCase(stdin=t.stdin, expected_stdout=t.expected_stdout,
                      is_sample=t.is_sample) for t in problem.tests]
    result = judge(sub.source, sub.language, tests,
                   time_limit_sec=problem.time_limit_sec, memory_mb=problem.memory_mb)

    was = sub.verdict
    sub.verdict, sub.passed, sub.total = result.verdict, result.passed, result.total
    sub.max_time_ms = result.max_time_ms
    sub.compile_output = result.compile_output or None
    replace_test_results(sub, result)
    db.session.commit()

    log_action("rejudge", sub.id, "%s -> %s" % (was, sub.verdict))
    flash("Re-judged: %s -> %s. XP unchanged." % (was, sub.verdict), "success")
    return redirect(url_for("admin.submission_detail", sub_id=sub.id))

@admin_bp.route("/content/")
@admin_required
def content():
    tracks = db.session.execute(
         db.select(Track).order_by(Track.position)
    ).scalars().all()
    orphan_lessons = db.session.execute(
        db.select(Lesson).where(Lesson.kind == "code", Lesson.problem_id.is_(None))
    ).scalars().all()
    return render_template("admin/content.html", tracks=tracks,
                           orphan_lessons=orphan_lessons)


@admin_bp.route("/content/seed", methods=["POST"])
@admin_required
def content_seed():
    counts = seed_catalog()
    log_action("seed_catalog", "", str(counts))
    flash("Seeded: %d tracks, %d units, %d lessons.%s" % (
        counts["tracks"], counts["units"], counts["lessons"],
        (" Unlinked: %s" % ", ".join(sorted(set(counts["unlinked"]))))
        if counts["unlinked"] else ""), "success")
    return redirect(url_for("admin.content"))

@admin_bp.route("/system/")
@admin_required
def system():
    try:
        db.session.execute(db.text("select 1"))
        db_ok = True
    except Exception:
        db_ok = False

    checks = [
        ("Database", "reachable" if db_ok else "NOT reachable", db_ok),
        ("Mail (RESEND_API_KEY)", "set" if os.environ.get("RESEND_API_KEY") else "missing",
         bool(os.environ.get("RESEND_API_KEY"))),
        ("MAIL_FROM", os.environ.get("MAIL_FROM", "default resend.dev sender"), True),
        ("SECRET_KEY", "set" if current_app.secret_key not in (None, "dev") else "still 'dev'",
         current_app.secret_key not in (None, "dev")),
        ("Secure cookies", str(current_app.config.get("SESSION_COOKIE_SECURE")),
         bool(current_app.config.get("SESSION_COOKIE_SECURE"))),
        ("OAuth providers", ", ".join(current_app.config.get("ENABLED_PROVIDERS", [])) or "none",
         bool(current_app.config.get("ENABLED_PROVIDERS"))),
        ("Admins", ", ".join(sorted(admin_emails())) or "none", bool(admin_emails())),
    ]
    return render_template("admin/system.html", checks=checks)

@admin_bp.route("/audit/")
@admin_required
def audit():
    rows, pager = _paginate(
        db.select(AdminAction).order_by(AdminAction.created_at.desc()), _page())
    return render_template("admin/audit.html", actions=rows, pager_=pager)

@admin_bp.route("/deletions/")
@admin_required
def deletions():
    pending = db.session.execute(
        db.select(DeletionRequest).where(DeletionRequest.status == "pending")
        .order_by(DeletionRequest.created_at)
    ).scalars().all()
    decided = db.session.execute(
        db.select(DeletionRequest).where(DeletionRequest.status != "pending")
        .order_by(DeletionRequest.decided_at.desc()).limit(25)
    ).scalars().all()
    return render_template("admin/deletions.html", pending=pending, decided=decided,
                           reason_labels=DELETION_REASON_LABELS)


@admin_bp.route("/deletions/<int:req_id>/approve", methods=["POST"])
@admin_required
def deletion_approve(req_id):
    req = _get_or_404(DeletionRequest, req_id)
    if req.status != "pending":
        flash("That request was already decided.", "error")
        return redirect(url_for("admin.deletions"))

    user = req.user
    if user.id == current_user().id:
        flash("Approve your own deletion from settings, not here.", "error")
        return redirect(url_for("admin.deletions"))
    if (request.form.get("confirm") or "").strip().lower() != (user.username or ""):
        flash("Type their username exactly to confirm.", "error")
        return redirect(url_for("admin.deletions"))

    # The request row cascades away with the user, so the audit entry is written
    # first - it is the only record that survives.
    log_action("approve_deletion", user.id,
               "%s - %s: %s" % (user.email, req.reason, (req.detail or "")[:200]))
    delete_account(user)
    flash("Account deleted.", "success")
    return redirect(url_for("admin.deletions"))


@admin_bp.route("/deletions/<int:req_id>/reject", methods=["POST"])
@admin_required
def deletion_reject(req_id):
    req = _get_or_404(DeletionRequest, req_id)
    if req.status != "pending":
        flash("That request was already decided.", "error")
        return redirect(url_for("admin.deletions"))

    note = (request.form.get("note") or "").strip()
    reject_deletion_request(req, current_user(), note)
    log_action("reject_deletion", req.user_id, note[:200])
    flash("Request declined. The account stays.", "success")
    return redirect(url_for("admin.deletions"))

@admin_bp.route("/tutor/")
@admin_required
def tutor():
    """Review what learners are asking the AI tutor, and what it said back."""
    flagged_only = request.args.get("flagged") == "1"
    stmt = db.select(TutorMessage).order_by(TutorMessage.created_at.desc())
    if flagged_only:
        stmt = stmt.where(TutorMessage.flagged.is_(True))

    rows, pager = _paginate(stmt, _page())
    stats = {
        "total": _count(TutorMessage),
        "flagged": _count(TutorMessage, TutorMessage.flagged.is_(True)),
        "failed": _count(TutorMessage, TutorMessage.ok.is_(False)),
    }
    return render_template("admin/tutor.html", rows=rows, pager_=pager,
                           flagged_only=flagged_only, stats=stats)

@admin_bp.route("/unlock", methods=["GET", "POST"])
@admin_email_required
def unlock():
    user = current_user()
    target = request.values.get("next") or ""
    if not is_safe_next(target):
        target = url_for("admin.overview")

    if not gate_ready(user) or session_unlocked(user):
        return redirect(target)

    methods = unlock_methods(user)
    error = None
    wait = lockout_minutes_left(user)
    action = request.form.get("action") if request.method == "POST" else None

    if action == "send-code":
        if wait:
            flash("Too many wrong tries. Wait about %d min." % wait, "error")
        else:
            sent, message = send_code(user)
            flash(message, "success" if sent else "error")
        return redirect(url_for("admin.unlock", next=target))

    if action == "code":
        if wait:
            error = "Too many wrong tries. Wait about %d min." % wait
        elif verify_code(user, request.form.get("code")):
            unlock_session(user)
            return redirect(target)
        else:
            record_failure(user)
            wait = lockout_minutes_left(user)
            left = max(0, MAX_FAILURES - recent_failures(user))
            error = ("Locked for about %d min." % wait if wait
                     else "Wrong code - %d tr%s left."
                          % (left, "y" if left == 1 else "ies"))

    return render_template("admin/unlock.html", error=error, wait=wait,
                           next=target, methods=methods)


@admin_bp.route("/unlock/key/begin", methods=["POST"])
@admin_email_required
def unlock_key_begin():
    user = current_user()
    if lockout_minutes_left(user):
        return jsonify(error="Too many wrong tries. Wait a few minutes."), 429
    try:
        return current_app.response_class(
            begin_authentication(user, admin_only=True),
            mimetype="application/json")
    except WebAuthnError as exc:
        return jsonify(error=str(exc)), 400


@admin_bp.route("/unlock/key/finish", methods=["POST"])
@admin_email_required
def unlock_key_finish():
    user = current_user()
    if lockout_minutes_left(user):
        return jsonify(error="Too many wrong tries."), 429
    try:
        finish_authentication(request.get_json(silent=True) or {},
                              user=user, admin_only=True)
    except WebAuthnError as exc:
        record_failure(user)
        return jsonify(error=str(exc)), 400

    unlock_session(user)
    return jsonify(ok=True)


@admin_bp.route("/lock", methods=["POST"])
@admin_email_required
def lock():
    lock_session()
    flash("Admin locked.", "success")
    return redirect(url_for("dashboard.index"))

@admin_bp.route("/blog/")
@admin_required
def blog():
    page = _page()
    stmt = db.select(Post).order_by(Post.updated_at.desc())
    posts, pager = _paginate(stmt, page)
    return render_template("admin/blog.html", posts=posts, p=pager)


@admin_bp.route("/blog/new", methods=["GET", "POST"])
@admin_bp.route("/blog/<int:post_id>/edit", methods=["GET", "POST"])
@admin_required
def blog_form(post_id = None):
    post = _get_or_404(Post, post_id) if post_id else None

    if request.method == "GET":
        return render_template("admin/blog_form.html", post=post, errors={}, form={})

    form = request.form
    slug = (form.get("slug") or "").strip().lower() or slugify(form.get("title"))

    def taken(candidate):
        clash = db.session.execute(
            db.select(Post).filter_by(slug=candidate)).scalar_one_or_none()
        return clash is not None and (post is None or clash.id != post.id)

    errors = validate_post({**form, "slug": slug}, taken)
    if errors:
        return render_template("admin/blog_form.html", post=post, errors=errors,
                               form=form), 400

    if post is None:
        post = Post(slug=slug, author_id=current_user().id)
        db.session.add(post)

    post.slug = slug
    post.title = (form.get("title") or "").strip()
    post.summary = (form.get("summary") or "").strip()
    post.body_md = form.get("body_md") or ""
    post.cover_url = (form.get("cover_url") or "").strip() or None
    db.session.commit()

    log_action("save_post", post.id, post.slug)
    flash("Post saved.", "success")
    return redirect(url_for("admin.blog_form", post_id=post.id))

@admin_bp.route("/blog/<int:post_id>/publish", methods=["POST"])
@admin_required
def blog_publish(post_id):
    post = _get_or_404(Post, post_id)
    going_live = post.status != "published"

    post.status = "published" if going_live else "draft"
    if going_live and post.published_at is None:
        # Set once. Re-publishing an old post shouldn't jump it to the top.
        post.published_at = _utcnow()
    db.session.commit()

    log_action("publish_post" if going_live else "unpublish_post", post.id, post.slug)
    flash("Published." if going_live else "Moved back to draft.", "success")
    return redirect(url_for("admin.blog_form", post_id=post.id))


@admin_bp.route("/blog/<int:post_id>/delete", methods=["POST"])
@admin_required
def blog_delete(post_id):
    post = _get_or_404(Post, post_id)
    if (request.form.get("confirm") or "").strip() != post.slug:
        flash("Type the post's slug to confirm.", "error")
        return redirect(url_for("admin.blog_form", post_id=post.id))

    slug = post.slug
    db.session.delete(post)
    db.session.commit()
    log_action("delete_post", post_id, slug)
    flash("Post deleted.", "success")
    return redirect(url_for("admin.blog"))

@admin_bp.route("/reports/")
@admin_required
def reports():
    status = request.args.get("status","open")
    if status not in ("open", "actioned","dismissed","all"):
        status = "open"
    
    stmt = db.select(Report).order_by(Report.created_at.desc())
    if status != "all":
        stmt = stmt.where(Report.status == status)
    rows, pager = _paginate(stmt, _page())

    targets = {}
    for r in rows:
        if r.kind == "user":
            targets[r.id] = db.session.get(User, r.target_id)
        elif r.kind == "team":
            targets[r.id] = db.session.get(Team, r.target_id)
        else:
            targets[r.id] = db.session.get(Submission, r.target_id)

    return render_template("admin/reports.html", rows=rows, p=pager,
                           status=status, targets=targets,
                           reasons=REPORT_REASON_LABELS)

@admin_bp.route("/reports/<int:report_id>/resolve", methods=["POST"])
@admin_required
def report_resolve(report_id):
    rep = _get_or_404(Report, report_id)
    action = request.form.get("action") or "dismiss"
    note = (request.form.get("note") or "").strip()

    if action == "blank_bio" and rep.kind == "user":
        target = db.session.get(User, rep.target_id)
        if target is not None:
            target.bio = ""
            target.discoverable = False

    elif action == "blank_blurb" and rep.kind == "team":
        target = db.session.get(Team, rep.target_id)
        if target is not None:
            target.blurb = ""

    elif action == "unshare" and rep.kind == "solution":
        target = db.session.get(Submission, rep.target_id)
        if target is not None:
            target.is_public = False

    elif action == "suspend" and rep.kind == "user":
        target = db.session.get(User, rep.target_id)
        if target is not None:
            # Keeps the account and its history; stops it being seen or used.
            target.is_suspended = True
            target.discoverable = False
            target.show_on_leaderboard = False

    rep.status = "dismissed" if action == "dismiss" else "actioned"
    rep.handled_by = current_user().id
    rep.handled_note = note[:500]
    rep.handled_at = _utcnow()
    db.session.commit()

    log_action("report_%s" % action, rep.id, "%s#%s" % (rep.kind, rep.target_id))
    flash("Report resolved.", "success")
    return redirect(url_for("admin.reports"))


# --------------------------------------------------------------------------- #
# lesson authoring
# --------------------------------------------------------------------------- #

LESSON_KINDS = ("reading", "quiz", "code")


@admin_bp.route("/lessons/")
@admin_required
def lessons():
    stmt = (db.select(Lesson).join(Unit).join(Track)
            .order_by(Track.position, Unit.position, Lesson.position))
    rows, pager = _paginate(stmt, _page())
    return render_template("admin/lessons.html", lessons=rows, p=pager)


@admin_bp.route("/lessons/new", methods=["GET", "POST"])
@admin_bp.route("/lessons/<int:lesson_id>/edit", methods=["GET", "POST"])
@admin_required
def lesson_form(lesson_id=None):
    lesson = _get_or_404(Lesson, lesson_id) if lesson_id else None
    units = db.session.execute(
        db.select(Unit).join(Track).order_by(Track.position, Unit.position)
    ).scalars().all()
    problems = db.session.execute(
        db.select(Problem).order_by(Problem.slug)).scalars().all()

    if request.method == "GET":
        return render_template("admin/lesson_form.html", lesson=lesson, errors={},
                               form={}, units=units, problems=problems,
                               kinds=LESSON_KINDS)

    form = request.form
    errors = {}
    title = (form.get("title") or "").strip()
    slug = (form.get("slug") or "").strip().lower() or slugify(title)
    kind = form.get("kind") if form.get("kind") in LESSON_KINDS else "reading"

    try:
        unit_id = int(form.get("unit_id") or 0)
    except (TypeError, ValueError):
        unit_id = 0
    unit = db.session.get(Unit, unit_id)

    if not title:
        errors["title"] = "Give it a title."
    if unit is None:
        errors["unit_id"] = "Pick a unit."
    if not SLUG_RE.match(slug):
        errors["slug"] = "Lowercase letters, numbers and hyphens."
    elif unit is not None:
        # The unique constraint is (unit_id, slug), so a clash is per-unit.
        clash = db.session.execute(
            db.select(Lesson).filter_by(unit_id=unit.id, slug=slug)
        ).scalar_one_or_none()
        if clash is not None and (lesson is None or clash.id != lesson.id):
            errors["slug"] = "That slug is already used in this unit."

    problem_id = form.get("problem_id") or ""
    if kind == "code" and not problem_id:
        errors["problem_id"] = "A code lesson needs a problem."

    if errors:
        return render_template("admin/lesson_form.html", lesson=lesson,
                               errors=errors, form=form, units=units,
                               problems=problems, kinds=LESSON_KINDS), 400

    if lesson is None:
        lesson = Lesson(unit_id=unit.id, slug=slug)
        db.session.add(lesson)

    lesson.unit_id = unit.id
    lesson.slug = slug
    lesson.title = title
    lesson.kind = kind
    lesson.xp_override = _xp_override(form.get("xp"))
    lesson.body_md = form.get("body_md") or ""
    lesson.position = int(form.get("position") or 0)
    lesson.problem_id = int(problem_id) if problem_id else None
    db.session.commit()

    log_action("save_lesson", lesson.id, lesson.slug)
    flash("Lesson saved.", "success")
    return redirect(url_for("admin.lesson_form", lesson_id=lesson.id))


@admin_bp.route("/lessons/<int:lesson_id>/delete", methods=["POST"])
@admin_required
def lesson_delete(lesson_id):
    lesson = _get_or_404(Lesson, lesson_id)
    if (request.form.get("confirm") or "").strip() != lesson.slug:
        flash("Type the slug to confirm.", "error")
        return redirect(url_for("admin.lesson_form", lesson_id=lesson.id))

    slug = lesson.slug
    db.session.delete(lesson)
    db.session.commit()
    log_action("delete_lesson", lesson_id, slug)
    flash("Lesson deleted.", "success")
    return redirect(url_for("admin.lessons"))


# --------------------------------------------------------------------------- #
# import / export / bulk / preview
# --------------------------------------------------------------------------- #

def _problem_blob(p):
    return {"slug": p.slug, "title": p.title, "statement_md": p.statement_md,
            "difficulty": p.difficulty, "topic": p.topic,
            "xp": p.xp_override,
            "time_limit_sec": p.time_limit_sec, "memory_mb": p.memory_mb,
            "tests": [{"stdin": t.stdin, "expected_stdout": t.expected_stdout,
                       "is_sample": t.is_sample} for t in p.tests]}


def _json_download(payload, filename):
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename})


@admin_bp.route("/problems/<int:problem_id>/export")
@admin_required
def problem_export(problem_id):
    p = _get_or_404(Problem, problem_id)
    return _json_download(_problem_blob(p), "%s.json" % p.slug)


@admin_bp.route("/problems/export-all")
@admin_required
def problems_export_all():
    rows = db.session.execute(
        db.select(Problem).order_by(Problem.slug)).scalars().all()
    return _json_download([_problem_blob(p) for p in rows], "problems.json")


@admin_bp.route("/problems/import", methods=["GET", "POST"])
@admin_required
def problems_import():
    if request.method == "GET":
        return render_template("admin/problems_import.html", report=None)

    raw = request.form.get("payload") or ""
    upload = request.files.get("file")
    if upload is not None and upload.filename:
        raw = upload.read().decode("utf-8", "replace")

    try:
        data = json.loads(raw)
    except ValueError as exc:
        flash("That is not valid JSON: %s" % exc, "error")
        return redirect(url_for("admin.problems_import"))

    items = data if isinstance(data, list) else [data]
    replace = request.form.get("replace") == "on"
    added = updated = skipped = 0
    notes = []

    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            notes.append("skipped a non-object entry")
            continue

        slug = (item.get("slug") or "").strip().lower()
        title = (item.get("title") or "").strip()
        if not slug or not title:
            skipped += 1
            notes.append("skipped an entry with no slug or title")
            continue

        existing = db.session.execute(
            db.select(Problem).filter_by(slug=slug)).scalar_one_or_none()
        if existing is not None and not replace:
            skipped += 1
            notes.append("%s already exists" % slug)
            continue

        problem = existing or Problem(slug=slug, statement_md="")
        problem.title = title
        problem.statement_md = item.get("statement_md") or ""
        problem.difficulty = item.get("difficulty") or "easy"
        problem.topic = item.get("topic") or None
        try:
            problem.xp_override = _xp_override(item.get("xp"))
            problem.time_limit_sec = float(item.get("time_limit_sec") or 2.0)
            problem.memory_mb = int(item.get("memory_mb") or 256)
        except (TypeError, ValueError):
            skipped += 1
            notes.append("%s has a non-numeric xp/limit" % slug)
            continue

        if existing is None:
            db.session.add(problem)
            added += 1
        else:
            problem.tests.clear()      # replacing a problem replaces its tests
            updated += 1
        db.session.flush()

        for i, t in enumerate(item.get("tests") or []):
            db.session.add(ProblemTest(
                problem_id=problem.id, position=i,
                stdin=t.get("stdin") or "",
                expected_stdout=t.get("expected_stdout") or "",
                is_sample=bool(t.get("is_sample"))))

    db.session.commit()
    log_action("import_problems", "", "+%d ~%d skip%d" % (added, updated, skipped))
    return render_template("admin/problems_import.html",
                           report={"added": added, "updated": updated,
                                   "skipped": skipped, "notes": notes})


@admin_bp.route("/problems/<int:problem_id>/tests/bulk", methods=["POST"])
@admin_required
def problem_bulk_tests(problem_id):
    """Paste many cases at once.

    Cases are separated by a line of '---', input and expected by a line of
    '==='. A case whose first line is '#sample' is marked as a sample.
    """
    problem = _get_or_404(Problem, problem_id)
    blob = (request.form.get("bulk") or "").replace("\r\n", "\n")
    if not blob.strip():
        flash("Nothing pasted.", "error")
        return redirect(url_for("admin.problem_form", problem_id=problem.id))

    start = len(problem.tests)
    made = 0
    for chunk in blob.split("\n---\n"):
        if not chunk.strip():
            continue
        is_sample = False
        if chunk.lstrip().startswith("#sample"):
            is_sample = True
            chunk = chunk.lstrip()[len("#sample"):].lstrip("\n")
        if "\n===\n" not in chunk:
            continue
        stdin, expected = chunk.split("\n===\n", 1)
        db.session.add(ProblemTest(
            problem_id=problem.id, position=start + made,
            stdin=stdin.strip("\n"), expected_stdout=expected.strip("\n"),
            is_sample=is_sample))
        made += 1

    db.session.commit()
    log_action("bulk_tests", problem.id, "+%d" % made)
    flash("Added %d test case%s." % (made, "" if made == 1 else "s"), "success")
    return redirect(url_for("admin.problem_form", problem_id=problem.id))


@admin_bp.route("/preview", methods=["POST"])
@admin_required
def preview():
    """Render the Markdown subset exactly as the real page will."""
    from .learning.markdown import render as render_md
    return jsonify(html=str(render_md(request.form.get("body_md") or "")))


# --------------------------------------------------------------------------- #
# similarity queue
# --------------------------------------------------------------------------- #

@admin_bp.route("/similarity/")
@admin_required
def similarity():
    status = request.args.get("status", "open")
    if status not in ("open", "cleared", "confirmed", "all"):
        status = "open"

    stmt = db.select(SimilarityFlag).order_by(SimilarityFlag.score.desc())
    if status != "all":
        stmt = stmt.where(SimilarityFlag.status == status)
    rows, pager = _paginate(stmt, _page())
    return render_template("admin/similarity.html", rows=rows, p=pager,
                           status=status)


@admin_bp.route("/similarity/<int:flag_id>/resolve", methods=["POST"])
@admin_required
def similarity_resolve(flag_id):
    flag = _get_or_404(SimilarityFlag, flag_id)
    action = request.form.get("action")
    flag.status = "confirmed" if action == "confirm" else "cleared"

    if action == "confirm":
        # Unshare both. Deciding who copied whom is not something a hash
        # comparison can tell you, and guessing punishes the wrong person.
        for s in (flag.submission, flag.matched):
            if s is not None:
                s.is_public = False

    db.session.commit()
    log_action("similarity_%s" % flag.status, flag.id, "%.2f" % flag.score)
    flash("Flag resolved.", "success")
    return redirect(url_for("admin.similarity"))

@admin_bp.route("/generated/")
@admin_required
def generated():
    status = request.args.get("status", "draft")
    if status not in ("draft", "approved", "rejected", "all"):
        status = "draft"

    stmt = db.select(GeneratedProblem).order_by(GeneratedProblem.created_at.desc())
    if status != "all":
        stmt = stmt.where(GeneratedProblem.status == status)
    rows, pager = _paginate(stmt, _page())
    return render_template("admin/generated.html", rows=rows, p=pager,
                           status=status)


@admin_bp.route("/generated/<int:draft_id>/resolve", methods=["POST"])
@admin_required
def generated_resolve(draft_id):
    draft = _get_or_404(GeneratedProblem, draft_id)
    action = request.form.get("action")
    draft.note = (request.form.get("note") or "").strip()[:1000]

    if action == "approve":
        problem = publish_generated(draft, current_user())
        if problem is None:
            flash("A problem with slug %r already exists. Rename the draft "
                  "first." % draft.slug, "error")
            return redirect(url_for("admin.generated"))
        log_action("approve_generated", draft.id, draft.slug)
        flash("Published as %s." % problem.slug, "success")
        return redirect(url_for("admin.problem_form", problem_id=problem.id))

    draft.status = "rejected"
    draft.reviewed_by = current_user().id
    draft.reviewed_at = _utcnow()
    db.session.commit()
    log_action("reject_generated", draft.id, draft.slug)
    flash("Draft rejected.", "success")
    return redirect(url_for("admin.generated"))

@admin_bp.route("/authors/")
@admin_required
def authors():
    invites = db.session.execute(
      db.select(AuthorInvite).order_by(AuthorInvite.created_at.desc()).limit(50)
    ).scalars().all()
    people = db.session.execute(
        db.select(User).where(User.is_author.is_(True)).order_by(User.author_since.desc())
    ).scalars().all()
    fresh = session.pop("fresh_invite", None)
    return render_template("admin/authors.html", invites=invites, people=people,
                           fresh=fresh, max_ttl=MAX_TTL_DAYS)


@admin_bp.route("/authors/invite", methods=["POST"])
@admin_required
def author_invite():
    form = request.form
    try:
        uses = int(form.get("max_uses") or 1)
        ttl = int(form.get("ttl_days") or 14)
    except (TypeError, ValueError):
        uses, ttl = 1, 14

    admin = current_user()
    row, raw = create_invite(admin, email=form.get("email"),
                             note=form.get("note") or "", max_uses=uses,
                             ttl_days=ttl)
    log_action("author_invite", row.id, row.email or "open link")

    link = url_for("authors.join", token=raw, _external=True)

    # Mail it when it is addressed to someone. The link is still shown either
    # way: Resend may not be configured, and _send swallows its own failures.
    mailed = False
    if row.email:
        mailed = send_author_invite_email(
            row.email, link, row.expires_at,
            inviter=(admin.username or admin.name or None),
            note=row.note)

    session["fresh_invite"] = link
    if mailed:
        flash("Invite created and emailed to %s. The link is shown once - "
              "copy it if you want to send it yourself." % row.email, "success")
    elif row.email:
        flash("Invite created, but the email could not be sent. Send them "
              "this link yourself - it is shown only once.", "error")
    else:
        flash("Invite created. Copy the link now - it is not shown again.", "success")
    return redirect(url_for("admin.authors"))

@admin_bp.route("/authors/invite/<int:invite_id>/revoke", methods=["POST"])
@admin_required
def author_invite_revoke(invite_id):
    invite = _get_or_404(AuthorInvite, invite_id)
    revoke(invite)
    log_action("author_invite_revoke", invite.id, invite.email or "open link")
    flash("Invite revoked.", "success")
    return redirect(url_for("admin.authors"))

@admin_bp.route("/authors/<int:user_id>/remove", methods=["POST"])
@admin_required
def author_remove(user_id):
    user = _get_or_404(User, user_id)
    user.is_author = False
    db.session.commit()
    log_action("author_remove", user.id, user.email)
    flash("Authorship removed. Their published work stays up.", "success")
    return redirect(url_for("admin.authors"))

def _public_url(kind, row):
    """Where the author should land. The admin queue 403s for them."""
    if kind == "problem":
        return url_for("problems.page", slug=row.slug)
    if kind == "track":
        return url_for("learn.track", track_slug=row.slug)
    if kind == "lesson" and row.unit is not None and row.unit.track is not None:
        return url_for("learn.lesson", track_slug=row.unit.track.slug,
                       unit_slug=row.unit.slug, lesson_slug=row.slug)
    return url_for("authors.index")


REVIEWABLE = {"track": Track, "unit": Unit, "lesson": Lesson,
              "problem": Problem}


@admin_bp.route("/review/")
@admin_required
def review():
    queue = []
    for kind, model in REVIEWABLE.items():
        rows = db.session.execute(
            db.select(model).where(model.status == REVIEW)
            .order_by(model.submitted_at)
        ).scalars().all()
        queue.extend((kind, r) for r in rows)
    queue.sort(key=lambda pair: pair[1].submitted_at or _utcnow())
    return render_template("admin/review.html", queue=queue)

def _parent_unpublished(kind, row):
    from .authors.blockers import waiting_on
    pending = waiting_on(kind, row)
    return "Publish %s first." % " and ".join(pending) if pending else None


@admin_bp.route("/review/<kind>/<int:row_id>/publish", methods=["POST"])
@admin_required
def review_publish(kind, row_id):
    model = REVIEWABLE.get(kind)
    if model is None:
        abort(404)

    row = _get_or_404(model, row_id)

    blocked = _parent_unpublished(kind, row)
    if blocked:
        flash(blocked, "error")
        return redirect(url_for("admin.review"))

    row.status = PUBLISHED
    row.published_at = _utcnow()
    row.review_note = ""
    db.session.commit()
    if row.created_by is not None:
        notify.send(row.created_by, "published",
                    "%s is live" % row.title,
                    "An editor published your %s." % kind,
                    url=_public_url(kind, row), email=True)
    log_action("publish_%s" % kind, row.id, row.slug)
    flash("Published.", "success")
    return redirect(url_for("admin.review"))

@admin_bp.route("/review/<kind>/<int:row_id>/reject", methods=["POST"])
@admin_required
def review_reject(kind, row_id):
    model = REVIEWABLE.get(kind)
    if model is None:
        abort(404)
    row = _get_or_404(model, row_id)
    row.status = DRAFT
    row.submitted_at = None
    row.review_note = (request.form.get("note") or "").strip()[:2000]
    db.session.commit()
    if row.created_by is not None:
        notify.send(row.created_by, "rejected",
                    "%s was sent back" % row.title,
                    row.review_note or "No note was left.",
                    url=url_for("authors.index"), email=True)
    log_action("reject_%s" % kind, row.id, row.slug)
    flash("Sent back to the author.", "success")
    return redirect(url_for("admin.review"))

@admin_bp.route("/review/<kind>/<int:row_id>/unpublish", methods=["POST"])
@admin_required
def review_unpublish(kind, row_id):
    model = REVIEWABLE.get(kind)
    if model is None:
        abort(404)
    row = _get_or_404(model, row_id)
    row.status = DRAFT
    db.session.commit()
    log_action("unpublish_%s" % kind, row.id, row.slug)
    flash("Taken down.", "success")
    return redirect(url_for("admin.review"))
# --------------------------------------------------------------------------- #
# subscriptions
# --------------------------------------------------------------------------- #

SUB_FILTERS = ("live", "active", "trialing", "past_due", "canceled",
               "ending", "manual")


@admin_bp.route("/subscriptions/")
@admin_required
def subscriptions():
    which = request.args.get("status") or "live"
    query = (request.args.get("q") or "").strip()

    stmt = db.select(Subscription).join(User, User.id == Subscription.user_id)

    if which == "live":
        stmt = stmt.where(Subscription.status.in_(SUB_GRANTING))
    elif which == "ending":
        stmt = stmt.where(Subscription.status.in_(SUB_GRANTING),
                          Subscription.cancel_at_period_end.is_(True))
    elif which == "manual":
        stmt = stmt.where(Subscription.source == "manual")
    elif which in SUB_FILTERS:
        stmt = stmt.where(Subscription.status == which)

    if query:
        like = "%" + query + "%"
        stmt = stmt.where(or_(User.email.ilike(like), User.username.ilike(like)))

    stmt = stmt.order_by(Subscription.created_at.desc())
    rows, pager_ = _paginate(stmt, _page())

    return render_template("admin/subscriptions.html", rows=rows, p=pager_,
                           stats=billing_stats.overview(),
                           series=billing_stats.monthly_series(),
                           status=which, q=query, filters=SUB_FILTERS)


@admin_bp.route("/subscriptions/<int:sub_id>/")
@admin_required
def subscription_detail(sub_id):
    row = _get_or_404(Subscription, sub_id)
    remote, remote_error = None, None
    if not row.is_manual:
        try:
            remote = get_subscription(row.polar_subscription_id)
        except BillingError as exc:
            # A provider outage must not take this page down with it.
            remote_error = str(exc)
    return render_template("admin/subscription_detail.html", sub=row,
                           remote=remote, remote_error=remote_error,
                           monthly=billing_stats.monthly_cents(row) / 100.0)


def _sub_action(sub_id, fn, verb):
    """Shared body for cancel / uncancel / revoke."""
    row = _get_or_404(Subscription, sub_id)
    if row.is_manual:
        flash("That is a complimentary grant - withdraw it instead.", "error")
        return redirect(url_for("admin.subscription_detail", sub_id=sub_id))

    try:
        data = fn(row.polar_subscription_id)
    except BillingError as exc:
        current_app.logger.warning("polar %s failed for sub %s: %s",
                                   verb, sub_id, exc)
        flash("The payment provider refused that. Nothing changed.", "error")
        return redirect(url_for("admin.subscription_detail", sub_id=sub_id))

    # Write the response back through the same path a webhook uses, so the row
    # is right immediately rather than whenever the webhook turns up.
    billing_service.apply_subscription(data, "subscription." + verb,
                                       event_at=_utcnow())
    log_action("subscription_" + verb, row.id, row.polar_subscription_id)
    flash("Done.", "success")
    return redirect(url_for("admin.subscription_detail", sub_id=sub_id))


@admin_bp.route("/subscriptions/<int:sub_id>/cancel", methods=["POST"])
@admin_required
def subscription_cancel(sub_id):
    return _sub_action(sub_id, lambda pid: cancel_subscription(pid, True),
                       "canceled")


@admin_bp.route("/subscriptions/<int:sub_id>/uncancel", methods=["POST"])
@admin_required
def subscription_uncancel(sub_id):
    return _sub_action(sub_id, lambda pid: cancel_subscription(pid, False),
                       "uncanceled")


@admin_bp.route("/subscriptions/<int:sub_id>/revoke", methods=["POST"])
@admin_required
def subscription_revoke(sub_id):
    return _sub_action(sub_id, revoke_subscription, "revoked")


@admin_bp.route("/subscriptions/<int:sub_id>/sync", methods=["POST"])
@admin_required
def subscription_sync(sub_id):
    """Re-pull from Polar. The fix when a webhook was missed or mishandled."""
    row = _get_or_404(Subscription, sub_id)
    if row.is_manual:
        abort(404)
    try:
        data = get_subscription(row.polar_subscription_id)
    except BillingError:
        flash("Could not read that subscription from the provider.", "error")
        return redirect(url_for("admin.subscription_detail", sub_id=sub_id))

    billing_service.apply_subscription(data, "subscription.updated",
                                       event_at=_utcnow())
    log_action("subscription_sync", row.id, row.polar_subscription_id)
    flash("Synced from the provider.", "success")
    return redirect(url_for("admin.subscription_detail", sub_id=sub_id))


@admin_bp.route("/subscriptions/grant", methods=["POST"])
@admin_required
def subscription_grant():
    form = request.form
    who = (form.get("user") or "").strip()
    user = db.session.execute(
        db.select(User).where(or_(User.email == who.lower(),
                                  User.username == who))
    ).scalar_one_or_none()

    if user is None:
        flash("No user with that email or username.", "error")
        return redirect(url_for("admin.subscriptions"))
    if billing_service.is_pro(user):
        flash("They already have Pro.", "error")
        return redirect(url_for("admin.subscriptions"))

    try:
        months = max(1, min(int(form.get("months") or 12), 120))
    except (TypeError, ValueError):
        months = 12

    row = billing_service.grant_manual(user, current_user(), months=months,
                                       note=form.get("note") or "")
    log_action("subscription_grant", row.id,
               "%s / %d months" % (user.email, months))
    flash("Granted Pro to %s for %d months." % (user.email, months), "success")
    return redirect(url_for("admin.subscriptions", status="manual"))


@admin_bp.route("/subscriptions/<int:sub_id>/ungrant", methods=["POST"])
@admin_required
def subscription_ungrant(sub_id):
    row = _get_or_404(Subscription, sub_id)
    if not billing_service.end_manual(row):
        flash("That is a paid subscription - cancel it at the provider.", "error")
    else:
        log_action("subscription_ungrant", row.id,
                   row.user.email if row.user else "")
        flash("Complimentary Pro withdrawn.", "success")
    return redirect(url_for("admin.subscriptions", status="manual"))

@admin_bp.route("/classrooms/")
@admin_required
def classrooms():
    rows = db.session.execute(
        db.select(Classroom).order_by(Classroom.created_at.desc())).scalars().all()
    return render_template("admin/classrooms.html", rows=rows)

@admin_bp.route("/classrooms/grant", methods=["POST"])
@admin_required
def classroom_grant():
    form = request.form
    who = (form.get("owner") or "").strip()
    owner = db.session.execute(
        db.select(User).where(or_(User.email == who.lower(),
                                  User.username == who))).scalar_one_or_none()
    if owner is None:
        flash("No user with that email or username.", "error")
        return redirect(url_for("admin.classrooms"))

    try:
        seats = max(1, min(int(form.get("seats") or 30), 1000))
        months = max(1, min(int(form.get("months") or 12), 60))
    except (TypeError, ValueError):
        seats, months = 30, 12

    cls = Classroom(
        owner_id=owner.id, source="academic", seats=seats,
        join_code=new_join_code(),
        name=(form.get("name") or "Classroom")[:120],
        institution=(form.get("institution") or "")[:160],
        note=(form.get("note") or "")[:2000],
        granted_by_id=current_user().id,
        expires_at=_utcnow() + timedelta(days=30 * months),
    )
    db.session.add(cls)
    db.session.commit()
    log_action("classroom_grant", cls.id,
               "%s / %d seats / %d months" % (owner.email, seats, months))
    flash("Academic licence granted: %d seats, code %s."
          % (seats, cls.join_code), "success")
    return redirect(url_for("admin.classrooms"))

@admin_bp.route("/classrooms/<int:class_id>/archive", methods=["POST"])
@admin_required
def classroom_archive(class_id):
    cls = _get_or_404(Classroom, class_id)
    cls.archived_at = _utcnow()
    db.session.commit()
    log_action("classroom_archive", cls.id, cls.name)
    flash("Classroom archived. Its members lose Pro.", "success")
    return redirect(url_for("admin.classrooms"))


# --------------------------------------------------------------------------- #
# team licences
# --------------------------------------------------------------------------- #

@admin_bp.route("/teams/licence", methods=["POST"])
@admin_required
def team_licence_grant():
    """A free licence on an existing team. No provider, no money."""
    form = request.form
    slug = (form.get("slug") or "").strip().lower()
    team = db.session.execute(
        db.select(Team).filter_by(slug=slug)).scalar_one_or_none()
    if team is None:
        flash("No team with that slug.", "error")
        return redirect(url_for("admin.classrooms"))

    try:
        seats = max(1, min(int(form.get("seats") or 10), 500))
        months = max(1, min(int(form.get("months") or 12), 60))
    except (TypeError, ValueError):
        seats, months = 10, 12

    team.seats = seats
    team.licence_source = "granted"
    team.licence_expires_at = _utcnow() + timedelta(days=30 * months)
    team.licence_note = (form.get("note") or "")[:2000]
    team.granted_by_id = current_user().id
    db.session.commit()

    log_action("team_licence_grant", team.id,
               "%s / %d seats / %d months" % (team.slug, seats, months))
    flash("Licensed %s with %d seats." % (team.slug, seats), "success")
    return redirect(url_for("admin.classrooms"))


@admin_bp.route("/teams/<int:team_id>/licence/revoke", methods=["POST"])
@admin_required
def team_licence_revoke(team_id):
    team = _get_or_404(Team, team_id)
    team.licence_source = "none"
    team.seats = 0
    db.session.commit()
    log_action("team_licence_revoke", team.id, team.slug)
    flash("Licence removed. The team itself is untouched.", "success")
    return redirect(url_for("admin.classrooms"))


# --------------------------------------------------------------------------- #
# student verification
# --------------------------------------------------------------------------- #

@admin_bp.route("/students/")
@admin_required
def students():
    pending = db.session.execute(
        db.select(StudentVerification)
        .where(StudentVerification.status == "pending")
        .order_by(StudentVerification.created_at)
    ).scalars().all()
    recent = db.session.execute(
        db.select(StudentVerification)
        .where(StudentVerification.status != "pending")
        .order_by(StudentVerification.created_at.desc()).limit(40)
    ).scalars().all()
    return render_template("admin/students.html", pending=pending,
                           recent=recent, months=VERIFY_MONTHS)


@admin_bp.route("/students/<int:row_id>/approve", methods=["POST"])
@admin_required
def student_approve(row_id):
    row = _get_or_404(StudentVerification, row_id)
    row.status = "verified"
    row.verified_at = _utcnow()
    row.expires_at = _utcnow() + timedelta(days=30 * VERIFY_MONTHS)
    row.reviewed_by_id = current_user().id
    row.review_note = (request.form.get("note") or "")[:2000]
    row.code_hash = ""
    db.session.commit()
    log_action("student_approve", row.id, row.academic_email)
    flash("Approved.", "success")
    return redirect(url_for("admin.students"))


@admin_bp.route("/students/<int:row_id>/reject", methods=["POST"])
@admin_required
def student_reject(row_id):
    row = _get_or_404(StudentVerification, row_id)
    row.status = "rejected"
    row.reviewed_by_id = current_user().id
    row.review_note = (request.form.get("note") or "")[:2000]
    row.code_hash = ""
    db.session.commit()
    log_action("student_reject", row.id, row.academic_email)
    flash("Rejected.", "success")
    return redirect(url_for("admin.students"))


@admin_bp.route("/contests/")
@admin_required
def contests():
    rows = db.session.execute(
        db.select(Contest).order_by(Contest.starts_at.desc())).scalars().all()
    return render_template("admin/contests.html", contests=rows,
                           problems=db.session.execute(
                               db.select(Problem).where(Problem.status == PUBLISHED)
                               .order_by(Problem.slug)).scalars().all())


@admin_bp.route("/contests/save", methods=["POST"])
@admin_required
def contest_save():
    from datetime import datetime, timezone as _tz
    form = request.form
    slug = (form.get("slug") or "").strip().lower()
    if not SLUG_RE.match(slug or ""):
        flash("Lowercase letters, numbers and hyphens.", "error")
        return redirect(url_for("admin.contests"))

    def when(field):
        raw = (form.get(field) or "").strip()
        try:                               # the browser sends local wall time
            return datetime.fromisoformat(raw).replace(tzinfo=_tz.utc)
        except ValueError:
            return None

    starts, ends = when("starts_at"), when("ends_at")
    if starts is None or ends is None or ends <= starts:
        flash("Give a start and an end, with the end later.", "error")
        return redirect(url_for("admin.contests"))

    contest = db.session.execute(
        db.select(Contest).filter_by(slug=slug)).scalar_one_or_none()
    if contest is None:
        contest = Contest(slug=slug, created_by_id=current_user().id)
        db.session.add(contest)
    contest.title = (form.get("title") or slug)[:200]
    contest.description_md = form.get("description_md") or ""
    contest.starts_at, contest.ends_at = starts, ends
    contest.freeze_minutes = max(0, min(int(form.get("freeze_minutes") or 30), 240))
    contest.published = bool(form.get("published"))
    db.session.commit()
    log_action("save_contest", contest.id, contest.slug)
    flash("Contest saved.", "success")
    return redirect(url_for("admin.contests"))


@admin_bp.route("/contests/<int:contest_id>/problems", methods=["POST"])
@admin_required
def contest_add_problem(contest_id):
    contest = _get_or_404(Contest, contest_id)
    problem = db.session.get(Problem, int(request.form.get("problem_id") or 0))
    if problem is None:
        flash("No such problem.", "error")
        return redirect(url_for("admin.contests"))
    last = db.session.execute(
        db.select(db.func.coalesce(db.func.max(ContestProblem.position), -1))
        .where(ContestProblem.contest_id == contest.id)).scalar()
    db.session.add(ContestProblem(contest_id=contest.id, problem_id=problem.id,
                                  position=last + 1))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Already in this contest.", "error")
    return redirect(url_for("admin.contests"))


@admin_bp.route("/contests/problems/<int:row_id>/remove", methods=["POST"])
@admin_required
def contest_remove_problem(row_id):
    row = _get_or_404(ContestProblem, row_id)
    db.session.delete(row)
    db.session.commit()
    return redirect(url_for("admin.contests"))
