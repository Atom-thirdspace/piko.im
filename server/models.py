import os
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import ARRAY

db = SQLAlchemy()


def _utcnow():
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255))
    username = db.Column(db.String(32), unique = True, index= True)
    password_hash = db.Column(db.Text)
    interest = db.Column(db.String(64))          # first pick; kept for topic matching
    interests = db.Column(ARRAY(db.String(64)), nullable=False,
                          server_default="{}", default=list)
    avatar_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    welcome_email_sent_at = db.Column(db.DateTime(timezone=True), nullable =True)
    email_verified_at = db.Column(db.DateTime(timezone=True))
    verification_sent_at = db.Column(db.DateTime(timezone=True))    
    xp_total = db.Column(db.Integer, nullable=False, default=0)
    daily_goal_xp = db.Column(db.Integer, nullable=False, default=30)
    streak_days = db.Column(db.Integer, nullable=False, default=0)
    streak_best = db.Column(db.Integer, nullable=False, default=0)
    last_active_date = db.Column(db.Date)
    timezone = db.Column(db.String(64), nullable=False, default="UTC")
    show_on_leaderboard = db.Column(
        db.Boolean, nullable=False, default=True, server_default="true"
    )
    discoverable = db.Column(db.Boolean, nullable=False, default=True,
                             server_default="true")
    bio = db.Column(db.Text, nullable=False, default="", server_default="")
    totp_secret = db.Column(db.Text)                 # Fernet-encrypted, never raw
    totp_confirmed_at = db.Column(db.DateTime(timezone=True))
    totp_last_step = db.Column(db.BigInteger)        # replay guard
    backup_codes = db.Column(ARRAY(db.Text), nullable=False,server_default="{}", default=list)
    preferred_language = db.Column(db.String(16))
    onboarded_at = db.Column(db.DateTime(timezone=True))
    identities = db.relationship(
        "OAuthIdentity", back_populates="user", cascade="all, delete-orphan"
    )
    is_suspended = db.Column(db.Boolean, nullable=False, default=False,
                             server_default="false")


    def __repr__(self):
        return f"<User {self.id} {self.email}>"
    
    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)
    
    def check_password(self, raw):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw)
    
    @property
    def interest_keys(self):
        """The array, falling back to the legacy single column."""
        if self.interests:
            return list(self.interests)
        return [self.interest] if self.interest else []

    @property
    def needs_onboarding(self):
        return not self.username or not self.interest_keys

    @property
    def needs_questionnaire(self):
        return self.onboarded_at is None

    @property
    def email_verified(self):
        return self.email_verified_at is not None

    @property
    def two_factor_on(self):
        return bool(self.totp_secret and self.totp_confirmed_at)


class AdminAction(db.Model):
    __tablename__ = "admin_actions"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"),
                        index=True)
    action = db.Column(db.String(64), nullable= False)
    target = db.Column(db.String(120), nullable = False, default = "")
    detail = db.Column(db.Text, nullable = False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    admin = db.relationship("User")

class OAuthIdentity(db.Model):
    """One row per linked provider account, so one user can have several."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_provider_account"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = db.Column(db.String(32), nullable=False)
    provider_user_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User", back_populates="identities")

    def __repr__(self):
        return f"<OAuthIdentity {self.provider}:{self.provider_user_id}>"


def _normalize_db_url(url):
    """Force the psycopg3 driver; Neon's channel_binding param needs a modern libpq."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def init_db(app):
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_db_url(url)
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Neon drops idle connections; pre_ping avoids handing out a dead one.
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 300}
    db.init_app(app)
    with app.app_context():
        db.create_all()


def load_user(user_id):
    return db.session.get(User, user_id)


def upsert_user(profile):
    is_new = False
    identity = db.session.execute(
        db.select(OAuthIdentity).filter_by(
            provider=profile["provider"],
            provider_user_id=profile["provider_user_id"],
        )
    ).scalar_one_or_none()

    if identity is not None:
        user = identity.user
    else:
        user = db.session.execute(
            db.select(User).filter_by(email=profile["email"])
        ).scalar_one_or_none()

        if user is None:
            user = User(
                email=profile["email"],
                name=profile.get("name"),
                avatar_url=profile.get("avatar_url"),
            )
            db.session.add(user)
            db.session.flush()  # assign user.id before the identity references it
            is_new = True

        db.session.add(
            OAuthIdentity(
                user_id=user.id,
                provider=profile["provider"],
                provider_user_id=profile["provider_user_id"],
            )
        )

    # Refresh display fields from whichever provider they just used.
    if profile.get("name"):
        user.name = profile["name"]
    if profile.get("avatar_url"):
        user.avatar_url = profile["avatar_url"]
    if profile.get("email_verified") and user.email_verified_at is None:
        user.email_verified_at = _utcnow()

    user.last_login_at = _utcnow()


    db.session.commit()
    return user, is_new

def mark_welcome_sent(user_id):
    user = db.session.get(User, user_id)
    if user is not None:
        user.welcome_email_sent_at = _utcnow()
        db.session.commit()

def mark_email_verified(user):
    if user.email_verified_at is None:
        user.email_verified_at = _utcnow()
        db.session.commit()
    return user

def touch_verification_sent(user):
    user.verification_sent_at = _utcnow()
    db.session.commit()

def find_by_email(email):
    return db.session.execute(
        db.select(User).filter_by(email=email.lower())
    ).scalar_one_or_none()

def find_by_username(username):
    return db.session.execute(
        db.select(User).filter_by(username=username.lower())
    ).scalar_one_or_none()

def find_by_login(identifier):
    ident = identifier.strip().lower()
    if "@" in ident:
        return find_by_email(ident)
    return find_by_username(ident)

def set_interests(user, keys):
    """Always assign a new list - SQLAlchemy doesn't track in-place mutation of a
    plain ARRAY column, so user.interests.append(...) would not persist."""
    user.interests = list(keys)
    user.interest = keys[0] if keys else None

def create_email_user(email,username,name,interests,password):
    user = User(
        email=email.lower(),
        username=username.lower(),
        name=name,
    )
    set_interests(user, interests)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user

def complete_profile(user, username, interests):
    user.username = username.lower()
    set_interests(user, interests)
    db.session.commit()
    return user

def touch_login(user):
    user.last_login_at = _utcnow()
    db.session.commit()


class Problem(db.Model):
    __tablename__ = "problems"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    statement_md = db.Column(db.Text, nullable=False)
    difficulty = db.Column(db.String(16), nullable=False, default="easy")
    topic = db.Column(db.String(64), index=True)      # pairs with User.interest
    xp = db.Column(db.Integer, nullable=False, default=10)
    time_limit_sec = db.Column(db.Float, nullable=False, default=2.0)
    memory_mb = db.Column(db.Integer, nullable=False, default=256)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    tests = db.relationship("ProblemTest", back_populates="problem",
                            cascade="all, delete-orphan", order_by="ProblemTest.position")


class ProblemTest(db.Model):
    __tablename__ = "problem_tests"

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problems.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    stdin = db.Column(db.Text, nullable=False, default="")
    expected_stdout = db.Column(db.Text, nullable=False, default="")
    is_sample = db.Column(db.Boolean, nullable=False, default=False)

    problem = db.relationship("Problem", back_populates="tests")


class Submission(db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problems.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    language = db.Column(db.String(16), nullable=False)
    source = db.Column(db.Text, nullable=False)
    verdict = db.Column(db.String(32), nullable=False, index=True)
    passed = db.Column(db.Integer, nullable=False, default=0)
    total = db.Column(db.Integer, nullable=False, default=0)
    max_time_ms = db.Column(db.Integer, nullable=False, default=0)
    compile_output = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    # Cache key: identical source against an unchanged test suite can reuse
    # a previous verdict instead of starting another container.
    tests_hash = db.Column(db.String(64), nullable=False, default="", server_default="")
    source_hash = db.Column(db.String(64), nullable=False, default="", server_default="")
    is_public = db.Column(db.Boolean, nullable=False, default=False,
                          server_default="false")

    user = db.relationship("User")
    problem = db.relationship("Problem")

    test_results = db.relationship("SubmissionTest", back_populates="submission",
                                   cascade="all, delete-orphan",
                                   order_by="SubmissionTest.position")

    @property
    def first_failure(self):
        """The case that broke - what anyone opening this submission wants."""
        return next((t for t in self.test_results if t.verdict != "accepted"), None)


MAX_CAPTURE = 2000          # per field; a runaway print loop must not fill the disk


class SubmissionTest(db.Model):
    """One test case's outcome within a submission.

    Stored so a learner can reopen an old attempt and still see which case
    broke, and so an admin can tell a bad test from bad code without
    re-running anything.

    Only the actual output is kept. Expected output is read live from
    ProblemTest, so editing a test doesn't rewrite history into a lie - it
    just means an old submission is shown against today's expectations.
    """

    __tablename__ = "submission_tests"
    __table_args__ = (
        UniqueConstraint("submission_id", "position", name="uq_submission_test"),
    )

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer,
                              db.ForeignKey("submissions.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False)
    verdict = db.Column(db.String(32), nullable=False)
    time_ms = db.Column(db.Integer, nullable=False, default=0)
    is_sample = db.Column(db.Boolean, nullable=False, default=False)
    stdout = db.Column(db.Text, nullable=False, default="")
    stderr = db.Column(db.Text, nullable=False, default="")

    submission = db.relationship("Submission", back_populates="test_results")


def _clip(text):
    text = text or ""
    if len(text) <= MAX_CAPTURE:
        return text
    return text[:MAX_CAPTURE] + "\n... truncated"


def replace_test_results(sub, result):
    """Swap in the outcomes from a judge run. Used by submit and by re-judge."""
    sub.test_results.clear()
    db.session.flush()                  # the delete-orphans go before the inserts
    for outcome in result.tests:
        sub.test_results.append(SubmissionTest(
            position=outcome.index,
            verdict=outcome.verdict,
            time_ms=outcome.time_ms,
            is_sample=outcome.is_sample,
            stdout=_clip(outcome.stdout),
            stderr=_clip(outcome.stderr),
        ))


def record_submission(user_id, problem, language, source, result):
    sub = Submission(
        user_id=user_id, problem_id=problem.id, language=language, source=source,
        verdict=result.verdict, passed=result.passed, total=result.total,
        max_time_ms=result.max_time_ms, compile_output=result.compile_output or None,
    )
    db.session.add(sub)
    replace_test_results(sub, result)
    db.session.commit()
    return sub


def first_accepted(user_id, problem_id):
    return db.session.execute(
        db.select(Submission.id).filter_by(
            user_id=user_id, problem_id=problem_id, verdict="accepted"
        ).limit(1)
    ).scalar_one_or_none() is None


class OnboardingSession(db.Model):

    __tablename__ = "onboarding_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, unique=True)
    answers = db.Column(db.JSON, nullable=False, default=dict)
    placement_question_ids = db.Column(db.JSON)
    placement_score = db.Column(db.Integer)
    placement_possible = db.Column(db.Integer)
    level = db.Column(db.String(16))
    recommendation = db.Column(db.JSON)
    started_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           onupdate=_utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User")


class Track(db.Model):
    __tablename__ = "tracks"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    position = db.Column(db.Integer, nullable=False, default=0)

    units = db.relationship("Unit", back_populates="track",
                            cascade="all, delete-orphan", order_by="Unit.position")


class Unit(db.Model):
    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint("track_id", "slug", name="uq_unit_track_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    slug = db.Column(db.String(64), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    level = db.Column(db.String(16), nullable=False, default="beginner")
    topic = db.Column(db.String(64))
    position = db.Column(db.Integer, nullable=False, default=0)

    track = db.relationship("Track", back_populates="units")
    lessons = db.relationship("Lesson", back_populates="unit",
                              cascade="all, delete-orphan", order_by="Lesson.position")


class Lesson(db.Model):
    __tablename__ = "lessons"
    __table_args__ = (
        UniqueConstraint("unit_id", "slug", name="uq_lesson_unit_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("units.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    slug = db.Column(db.String(64), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    kind = db.Column(db.String(16), nullable=False, default="reading")   # reading | quiz | code
    xp = db.Column(db.Integer, nullable=False, default=10)
    body_md = db.Column(db.Text, nullable=False, default="")
    position = db.Column(db.Integer, nullable=False, default=0)
    # SET NULL, not CASCADE: deleting a problem must not delete the lesson around it.
    problem_id = db.Column(db.Integer, db.ForeignKey("problems.id", ondelete="SET NULL"))

    unit = db.relationship("Unit", back_populates="lessons")
    problem = db.relationship("Problem")


class Enrollment(db.Model):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("user_id", "track_id", name="uq_enrollment"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id", ondelete="CASCADE"),
                         nullable=False)
    current_lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id", ondelete="SET NULL"))
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    started_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User")
    track = db.relationship("Track")
    current_lesson = db.relationship("Lesson")


class LessonProgress(db.Model):
    __tablename__ = "lesson_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id", name="uq_lesson_progress"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id", ondelete="CASCADE"),
                          nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User")
    lesson = db.relationship("Lesson")


class XpEvent(db.Model):
    """Ledger of every XP award. The unique constraint is what makes awards idempotent."""

    __tablename__ = "xp_events"
    __table_args__ = (
        UniqueConstraint("user_id", "reason", "ref", name="uq_xp_award"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(32), nullable=False)      # lesson | problem | streak
    ref = db.Column(db.String(64), nullable=False)         # e.g. the lesson or problem id
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User")

class Follow(db.Model):
        __tablename__ = "follows"
        __table_args__ = (
            UniqueConstraint("follower_id", "followee_id", name="uq_follow"),
        db.CheckConstraint("follower_id <> followee_id", name="ck_follow_not_self"),
        )

        id = db.Column(db.Integer, primary_key=True)
        follower_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                            nullable=False, index=True)
        followee_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                                nullable=False, index=True)
        created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

        follower = db.relationship("User", foreign_keys=[follower_id])
        followee = db.relationship("User", foreign_keys=[followee_id])

class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(40), unique=True, nullable=False, index=True)
    name = db.Column(db.String(60), nullable=False)
    blurb = db.Column(db.Text, nullable=False, default="")
    visibility = db.Column(db.String(16), nullable=False, default="open")
    join_code = db.Column(db.String(16), nullable=False, default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    owner = db.relationship("User")
    members = db.relationship("TeamMember", back_populates="team",
                              cascade="all, delete-orphan")

class TeamMember(db.Model):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False, default="member")
    joined_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    team = db.relationship("Team", back_populates="members")
    user = db.relationship("User")

class Post(db.Model):
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.String(300), nullable=False, default="")
    body_md = db.Column(db.Text, nullable=False, default="")
    cover_url = db.Column(db.Text)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    status = db.Column(db.String(16), nullable=False, default="draft")
    published_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           onupdate=_utcnow, nullable=False)

    author = db.relationship("User")

    @property
    def is_live(self):
        return self.status == "published" and self.published_at is not None

class DeletionRequest(db.Model):
    """A user asking to leave. Nothing is destroyed until an admin approves."""

    __tablename__ = "deletion_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    reason = db.Column(db.String(32), nullable=False)
    detail = db.Column(db.Text, nullable=False, default="")
    # pending | rejected | cancelled. An approved row is gone with the user.
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    decided_at = db.Column(db.DateTime(timezone=True))
    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    decision_note = db.Column(db.Text, nullable=False, default="")

    # Two FKs to the same table, so the join condition has to be spelled out.
    user = db.relationship("User", foreign_keys=[user_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_id])


class TutorMessage(db.Model):
    """Every tutor exchange, for rate limiting and abuse review."""

    __tablename__ = "tutor_messages"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id", ondelete="SET NULL"))
    problem_id = db.Column(db.Integer, db.ForeignKey("problems.id", ondelete="SET NULL"))
    mode = db.Column(db.String(16), nullable=False, default="hint")
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False, default="")
    model = db.Column(db.String(64), nullable=False, default="")
    ok = db.Column(db.Boolean, nullable=False, default=True)
    flagged = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           nullable=False, index=True)

    user = db.relationship("User")
    lesson = db.relationship("Lesson")
    problem = db.relationship("Problem")


def tutor_calls_since(user, since):
    return db.session.execute(
        db.select(db.func.count()).select_from(TutorMessage)
        .where(TutorMessage.user_id == user.id, TutorMessage.created_at >= since)
    ).scalar() or 0


def log_tutor_message(user, lesson, problem, mode, question, answer, model,
                      ok=True, flagged=False):
    row = TutorMessage(
        user_id=user.id,
        lesson_id=lesson.id if lesson else None,
        problem_id=problem.id if problem else None,
        mode=mode, question=question[:4000], answer=(answer or "")[:8000],
        model=model, ok=ok, flagged=flagged,
    )
    db.session.add(row)
    db.session.commit()
    return row


def pending_deletion_request(user):
    return db.session.execute(
        db.select(DeletionRequest).filter_by(user_id=user.id, status="pending")
    ).scalar_one_or_none()


def create_deletion_request(user, reason, detail):
    existing = pending_deletion_request(user)
    if existing is not None:
        return existing
    req = DeletionRequest(user_id=user.id, reason=reason, detail=detail)
    db.session.add(req)
    try:
        db.session.commit()
    except IntegrityError:
        # The partial unique index caught a double submit; hand back the winner.
        db.session.rollback()
        return pending_deletion_request(user)
    return req


def cancel_deletion_request(user):
    req = pending_deletion_request(user)
    if req is None:
        return None
    req.status = "cancelled"
    req.decided_at = _utcnow()
    db.session.commit()
    return req


def reject_deletion_request(req, admin, note):
    req.status = "rejected"
    req.decided_at = _utcnow()
    req.decided_by_id = admin.id
    req.decision_note = (note or "")[:2000]
    db.session.commit()
    return req


def update_profile(user, name, username, interests, avatar_url):
    user.name = name.strip()
    user.username = username.strip().lower()
    set_interests(user, interests)
    user.avatar_url = (avatar_url or "").strip() or None
    db.session.commit()
    return user

def update_preferences(user, daily_goal_xp, preferred_language, timezone):
    user.daily_goal_xp = int(daily_goal_xp)
    user.preferred_language = preferred_language or None
    user.timezone = timezone
    db.session.commit()
    return user
    

def set_user_password(user, raw):
    user.set_password(raw)
    db.session.commit()
    return user

def link_identity(user, profile):
    existing = db.session.execute(
        db.select(OAuthIdentity).filter_by(
            provider=profile["provider"],
            provider_user_id=profile["provider_user_id"],
        )
    ).scalar_one_or_none()
    if existing is not None:
        return "already_linked" if existing.user_id == user.id else "taken"

    same_provider = db.session.execute(
        db.select(OAuthIdentity.id).filter_by(user_id=user.id, provider = profile["provider"])
    ).first()
    if same_provider is not None:
        return "provider_in_use"

    db.session.add(OAuthIdentity(
        user_id = user.id,
        provider=profile["provider"],
        provider_user_id=profile["provider_user_id"],
    ))
    if not user.avatar_url and profile.get("avatar_url"):
        user.avatar_url = profile["avatar_url"]

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return "taken"
    return "linked"

def unlink_identity(user, provider):
    db.session.execute(
        db.delete(OAuthIdentity).where(
            OAuthIdentity.user_id == user.id, OAuthIdentity.provider == provider
        )
    )
    db.session.commit()

def delete_account(user):
    db.session.execute(db.delete(User).where(User.id == user.id))
    db.session.commit()


# --------------------------------------------------------------------------- #
# reports and moderation
# --------------------------------------------------------------------------- #

REPORT_KINDS = ("user", "team", "solution")
REPORT_REASONS = [
    ("abuse", "Abusive or hateful"),
    ("spam", "Spam or advertising"),
    ("nsfw", "Sexual or graphic content"),
    ("impersonation", "Pretending to be someone else"),
    ("other", "Something else"),
]
REPORT_REASON_LABELS = dict(REPORT_REASONS)


class Report(db.Model):
    """Someone flagging a bio, a team blurb or a shared solution.

    Reports are resolved, never deleted - the history is what tells you
    whether a repeat offender is a pattern or a bad week.
    """

    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    kind = db.Column(db.String(16), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(32), nullable=False)
    detail = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default="open")
    handled_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    handled_note = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    handled_at = db.Column(db.DateTime(timezone=True))

    reporter = db.relationship("User", foreign_keys=[reporter_id])
    handler = db.relationship("User", foreign_keys=[handled_by])


def file_report(reporter, kind, target_id, reason, detail=""):
    """False when this reporter already has an open report on the same thing."""
    if kind not in REPORT_KINDS or reason not in REPORT_REASON_LABELS:
        return False

    existing = db.session.execute(
        db.select(Report.id).filter_by(
            reporter_id=reporter.id, kind=kind, target_id=target_id, status="open")
    ).scalar_one_or_none()
    if existing is not None:
        return False

    db.session.add(Report(reporter_id=reporter.id, kind=kind, target_id=target_id,
                          reason=reason, detail=(detail or "")[:1000]))
    db.session.commit()
    return True


def open_report_count():
    return db.session.execute(
        db.select(db.func.count()).select_from(Report).where(Report.status == "open")
    ).scalar() or 0


# --------------------------------------------------------------------------- #
# judge queue
# --------------------------------------------------------------------------- #

class JudgeJob(db.Model):
    """A submission waiting for a container.

    The Submission row is created immediately with verdict 'queued', so the
    browser has something to poll and a learner's history never silently
    loses an attempt they made.
    """

    __tablename__ = "judge_jobs"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer,
                              db.ForeignKey("submissions.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default="queued")
    attempts = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    claimed_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))

    submission = db.relationship("Submission")
