import os
from functools import wraps
from uuid import uuid4
from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, url_for)

from sqlalchemy import or_
from .judge import LANGUAGES, TestCase, judge
from .learning.seed import seed_catalog
from .models import (AdminAction, DeletionRequest, Enrollment, Lesson, LessonProgress,
                     OAuthIdentity, Problem, ProblemTest, Submission, Track, Unit,
                     User, XpEvent, db, delete_account, mark_email_verified,
                     reject_deletion_request, TutorMessage, unlink_identity, Post, _utcnow)
from .oauth import PROVIDERS
from .progress import level_progress
from .session import current_user, is_safe_next
from .validators import DELETION_REASON_LABELS, slugify, validate_post
from .admin_gate import (MAX_FAILURES, admin_email_required, admin_required,
                         admin_emails, is_admin, lock_session,
                         lockout_minutes_left, passcode_set, record_failure,
                         recent_failures, session_unlocked, unlock_session,
                         verify_passcode)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
PAGE_SIZE = 25

NAV = [("admin.overview", "Overview"), ("admin.users", "Users"),
       ("admin.deletions", "Deletions"),
       ("admin.problems", "Problems"), ("admin.submissions", "Submissions"),
       ("admin.content", "Content"), ("admin.blog", "Blog"),
       ("admin.tutor", "Tutor"),
       ("admin.system", "System"),
       ("admin.audit", "Audit log")]


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
        problem = Problem(slug=slug)
        db.session.add(problem)

    problem.slug = slug
    problem.title = title
    problem.statement_md = form.get("statement_md") or ""
    problem.difficulty = form.get("difficulty") or "easy"
    problem.topic = (form.get("topic") or "").strip() or None
    problem.xp = int(form.get("xp") or 10)
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

    if not passcode_set() or session_unlocked(user):
        return redirect(target)

    error = None
    wait = lockout_minutes_left(user)
    if request.method == "POST":
        if wait:
            error = "Too many wrong tries. Try again in about %d min." % wait
        elif verify_passcode(request.form.get("passcode")):
            unlock_session(user)
            return redirect(target)
        else:
            record_failure(user)
            wait = lockout_minutes_left(user)
            left = max(0, MAX_FAILURES - recent_failures(user))
            error = ("Too many wrong tries. Locked for about %d min." % wait if wait
                     else "Wrong passcode - %d tr%s left."
                          % (left, "y" if left == 1 else "ies"))

    return render_template("admin/unlock.html", error=error, wait=wait, next=target)


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