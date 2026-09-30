import os
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declared_attr
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

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
    streak_freezes = db.Column(db.Integer, nullable=False, default=0,
                               server_default="0")
    freezes_granted_on = db.Column(db.Date)
    is_author = db.Column(db.Boolean, nullable=False, default=False,
                          server_default="false")
    author_since = db.Column(db.DateTime(timezone=True))


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
    hints = db.relationship("ProblemHint", back_populates="problem",
                            cascade="all, delete-orphan",
                            order_by="ProblemHint.position")

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


# --------------------------------------------------------------------------- #
# content ownership and the draft -> review -> published workflow
# --------------------------------------------------------------------------- #

DRAFT, REVIEW, PUBLISHED = "draft", "review", "published"
CONTENT_STATUSES = (DRAFT, REVIEW, PUBLISHED)

class Authored:
    status = db.Column(db.String(16), nullable = False, default = DRAFT, server_default = DRAFT, index = True)
    review_note = db.Column(db.Text, nullable=False, default="", server_default="")
    submitted_at = db.Column(db.DateTime(timezone=True))
    published_at = db.Column(db.DateTime(timezone=True))

    @declared_attr
    def created_by_id(cls):
        return db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    @declared_attr
    def created_by(cls):
        return db.relationship("User", foreign_keys=[cls.created_by_id])


class Track(Authored, db.Model):
    __tablename__ = "tracks"

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    position = db.Column(db.Integer, nullable=False, default=0)

    units = db.relationship("Unit", back_populates="track",
                            cascade="all, delete-orphan", order_by="Unit.position")


class Unit(Authored, db.Model):
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


class Lesson(Authored, db.Model):
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

class StreakFreezeUse(db.Model):
    __tablename__ = "streak_freeze_uses"
    __table_args__ = (
        UniqueConstraint("user_id", "covered_date", name="uq_freeze_day"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    covered_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User")


def recent_freeze_uses(user, limit=5):
    return db.session.execute(
        db.select(StreakFreezeUse)
        .where(StreakFreezeUse.user_id == user.id)
        .order_by(StreakFreezeUse.covered_date.desc()).limit(limit)
    ).scalars().all()

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


class ScratchRun(db.Model):
    """A Run-button execution: the learner's code against their own input.

    Kept apart from Submission on purpose - a run is not an attempt. It earns
    no XP, sets no verdict on the problem, never touches the streak, and is
    not what the similarity checker or the leaderboard look at. Rows are
    disposable; prune_scratch_runs clears them out.
    """
    __tablename__ = "scratch_runs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    # Null means the playground rather than a specific problem.
    problem_id = db.Column(db.Integer, db.ForeignKey("problems.id", ondelete="CASCADE"),
                           index=True)
    language = db.Column(db.String(16), nullable=False)
    source = db.Column(db.Text, nullable=False)
    stdin = db.Column(db.Text, nullable=False, default="", server_default="")

    status = db.Column(db.String(16), nullable=False, default="queued", index=True)
    verdict = db.Column(db.String(32), nullable=False, default="", server_default="")
    stdout = db.Column(db.Text, nullable=False, default="", server_default="")
    stderr = db.Column(db.Text, nullable=False, default="", server_default="")
    compile_output = db.Column(db.Text, nullable=False, default="", server_default="")
    time_ms = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text, nullable=False, default="", server_default="")

    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           nullable=False, index=True)
    claimed_at = db.Column(db.DateTime(timezone=True))
    finished_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User")
    problem = db.relationship("Problem")


def prune_scratch_runs(older_than_hours=6):
    """Runs are scratch paper. Drop anything that has been sitting a while."""
    cutoff = _utcnow() - timedelta(hours=older_than_hours)
    deleted = db.session.execute(
        db.delete(ScratchRun).where(ScratchRun.created_at < cutoff)
    ).rowcount
    db.session.commit()
    return deleted or 0


class UserAchievement(db.Model):
    __tablename__ = "user_achievements"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_achievement"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    key = db.Column(db.String(48), nullable=False)
    earned_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    user = db.relationship("User")

def earned_keys(user):
    return set(db.session.execute(
        db.select(UserAchievement.key).where(UserAchievement.user_id == user.id)
    ).scalars())

def earned_rows(user, limit=None):
    stmt = (db.select(UserAchievement)
            .where(UserAchievement.user_id == user.id)
            .order_by(UserAchievement.earned_at.desc()))
    if limit:
        stmt = stmt.limit(limit)
    return db.session.execute(stmt).scalars().all()

class ProblemHint(db.Model):
    __tablename__ = "problem_hints"
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer,
                           db.ForeignKey("problems.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)
    body_md = db.Column(db.Text, nullable=False, default="")
    cost_xp = db.Column(db.Integer, nullable=False, default=2)

    problem = db.relationship("Problem", back_populates="hints")


class HintReveal(db.Model):
    __tablename__ = "hint_reveals"
    __table_args__ = (
        UniqueConstraint("user_id", "hint_id", name="uq_hint_reveal"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    hint_id = db.Column(db.Integer,
                        db.ForeignKey("problem_hints.id", ondelete="CASCADE"),
                        nullable=False)
    revealed_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                            nullable=False)
    hint = db.relationship("ProblemHint")

MIN_PROBLEM_XP_FRACTION = 4          # a solve never pays less than xp // 4


def revealed_hint_ids(user, problem):
    return set(db.session.execute(
        db.select(HintReveal.hint_id)
        .join(ProblemHint, ProblemHint.id == HintReveal.hint_id)
        .where(HintReveal.user_id == user.id,
               ProblemHint.problem_id == problem.id)
    ).scalars())


def hint_penalty(user_id, problem_id):
    return db.session.execute(
        db.select(db.func.coalesce(db.func.sum(ProblemHint.cost_xp), 0))
        .select_from(HintReveal)
        .join(ProblemHint, ProblemHint.id == HintReveal.hint_id)
        .where(HintReveal.user_id == user_id,
               ProblemHint.problem_id == problem_id)
    ).scalar() or 0


def award_after_hints(problem, penalty):
    floor = max(1, problem.xp // MIN_PROBLEM_XP_FRACTION)
    return max(problem.xp - penalty, floor)


def reveal_hint(user, hint):
    existing = db.session.execute(
        db.select(HintReveal.id).filter_by(user_id=user.id, hint_id=hint.id)
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.session.add(HintReveal(user_id=user.id, hint_id=hint.id))
    try:
        db.session.commit()
    except IntegrityError:            # two tabs, same hint
        db.session.rollback()
        return False
    return True


# --------------------------------------------------------------------------- #
# solve statistics
# --------------------------------------------------------------------------- #

class ProblemSolve(db.Model):
    """One row per person who has solved a problem, written at first accept.

    Denormalised on purpose: deriving 'time to solve' from the submissions
    table means a correlated min() per user per problem, which is fine for
    one profile and hopeless for a percentile across every solver.
    """

    __tablename__ = "problem_solves"
    __table_args__ = (
        UniqueConstraint("user_id", "problem_id", name="uq_problem_solve"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    problem_id = db.Column(db.Integer,
                           db.ForeignKey("problems.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    seconds = db.Column(db.Integer, nullable=False)
    attempts = db.Column(db.Integer, nullable=False)
    solved_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                          nullable=False)


MIN_SOLVERS_FOR_PERCENTILE = 5      # below this the number is noise, not signal


def record_solve(sub):
    """Called once, when a submission is the user's first accept."""
    first_at, attempts = db.session.execute(
        db.select(db.func.min(Submission.created_at), db.func.count())
        .where(Submission.user_id == sub.user_id,
               Submission.problem_id == sub.problem_id)
    ).one()

    started = first_at or sub.created_at
    seconds = int((sub.created_at - started).total_seconds())

    db.session.add(ProblemSolve(user_id=sub.user_id, problem_id=sub.problem_id,
                                seconds=max(seconds, 0), attempts=attempts or 1))
    try:
        db.session.commit()
    except IntegrityError:           # a retried job; the first write stands
        db.session.rollback()


def solve_percentile(user_id, problem_id):
    """'Faster than N% of solvers', or None when there aren't enough solvers.

    Measured from a person's *first submission* on the problem, so it is
    really 'time from first attempt to working', not time spent thinking.
    A first-try solve therefore lands near zero.
    """
    mine = db.session.execute(
        db.select(ProblemSolve.seconds, ProblemSolve.attempts)
        .filter_by(user_id=user_id, problem_id=problem_id)
    ).one_or_none()
    if mine is None:
        return None

    seconds, attempts = mine
    slower, total = db.session.execute(
        db.select(
            db.func.count().filter(ProblemSolve.seconds > seconds),
            db.func.count())
        .select_from(ProblemSolve)
        .where(ProblemSolve.problem_id == problem_id)
    ).one()

    if (total or 0) < MIN_SOLVERS_FOR_PERCENTILE:
        return {"seconds": seconds, "attempts": attempts,
                "percentile": None, "solvers": total or 0}

    return {"seconds": seconds, "attempts": attempts,
            "percentile": round(100 * slower / total),
            "solvers": total}


def problem_stats(problem_id):
    """The quality signals that fall out of the same table."""
    solvers, med_sec, med_att = db.session.execute(
        db.select(db.func.count(),
                  db.func.percentile_cont(0.5).within_group(ProblemSolve.seconds),
                  db.func.percentile_cont(0.5).within_group(ProblemSolve.attempts))
        .select_from(ProblemSolve)
        .where(ProblemSolve.problem_id == problem_id)
    ).one()

    attempted = db.session.execute(
        db.select(db.func.count(db.distinct(Submission.user_id)))
        .where(Submission.problem_id == problem_id)
    ).scalar() or 0

    return {"solvers": solvers or 0, "attempted": attempted,
            "solve_rate": round(100 * (solvers or 0) / attempted) if attempted else None,
            "median_seconds": int(med_sec) if med_sec else None,
            "median_attempts": round(med_att, 1) if med_att else None}


# --------------------------------------------------------------------------- #
# similarity
# --------------------------------------------------------------------------- #

class SubmissionFingerprint(db.Model):
    __tablename__ = "submission_fingerprints"

    submission_id = db.Column(db.Integer,
                              db.ForeignKey("submissions.id", ondelete="CASCADE"),
                              primary_key=True)
    hash = db.Column(db.BigInteger, primary_key=True)
    problem_id = db.Column(db.Integer,
                           db.ForeignKey("problems.id", ondelete="CASCADE"),
                           nullable=False, index=True)


class SimilarityFlag(db.Model):
    __tablename__ = "similarity_flags"
    __table_args__ = (
        UniqueConstraint("submission_id", "matched_id", name="uq_sim_pair"),
    )

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer,
                              db.ForeignKey("submissions.id", ondelete="CASCADE"),
                              nullable=False)
    matched_id = db.Column(db.Integer,
                           db.ForeignKey("submissions.id", ondelete="CASCADE"),
                           nullable=False)
    score = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="open")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           nullable=False)

    submission = db.relationship("Submission", foreign_keys=[submission_id])
    matched = db.relationship("Submission", foreign_keys=[matched_id])

class GeneratedProblem(db.Model):
    """A problem waiting for a human to approve it.

    Nothing generated goes live on its own. Approval is what copies it into
    the real Problem table; until then it is inert.
    """

    __tablename__ = "generated_problems"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_generated_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(64), nullable=False)
    slug = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    topic = db.Column(db.String(64), nullable=False)
    difficulty = db.Column(db.String(16), nullable=False)
    xp = db.Column(db.Integer, nullable=False, default=15)
    statement_md = db.Column(db.Text, nullable=False)
    payload = db.Column(JSONB, nullable=False, default=dict)
    status = db.Column(db.String(16), nullable=False, default="draft")
    note = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           nullable=False)
    reviewed_by = db.Column(db.Integer,
                            db.ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at = db.Column(db.DateTime(timezone=True))

    reviewer = db.relationship("User")


def publish_generated(draft, reviewer):
    """Copy an approved draft into the real Problem tables."""
    if db.session.execute(
       db.select(Problem.id).filter_by(slug=draft.slug)
    ).scalar_one_or_none() is not None:
        return None                       # slug taken; reviewer renames first

    problem = Problem(
        slug=draft.slug, title=draft.title, statement_md=draft.statement_md,
        difficulty=draft.difficulty, topic=draft.topic, xp=draft.xp,
        time_limit_sec=draft.payload.get("time_limit_sec", 2.0),
        memory_mb=draft.payload.get("memory_mb", 256))
    db.session.add(problem)
    db.session.flush()

    for i, t in enumerate(draft.payload.get("tests", [])):
        db.session.add(ProblemTest(
            problem_id=problem.id, position=i,
            stdin=t["stdin"], expected_stdout=t["expected_stdout"],
            is_sample=bool(t.get("is_sample"))))

    for i, h in enumerate(draft.payload.get("hints", [])):
        db.session.add(ProblemHint(
            problem_id=problem.id, position=i,
            body_md=h["body"], cost_xp=int(h.get("cost_xp", 3))))

    draft.status = "approved"
    draft.reviewed_by = reviewer.id
    draft.reviewed_at = _utcnow()
    db.session.commit()
    return problem

class WebAuthnCredential(db.Model):
    __tablename__ = "webauthn_credentials"
    __table_args__ = (
        UniqueConstraint("credential_id", name="uq_credential_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    credential_id = db.Column(db.LargeBinary, nullable=False)
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.BigInteger, nullable=False, default=0)
    transports = db.Column(db.String(120), nullable=False, default="")
    aaguid = db.Column(db.String(64), nullable=False, default="")
    name = db.Column(db.String(80), nullable=False, default="Security key")
    admin_capable = db.Column(db.Boolean, nullable=False, default=False,
                              server_default="false")
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           nullable=False)
    last_used_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User")


def credentials_for(user):
    return db.session.execute(
        db.select(WebAuthnCredential)
        .where(WebAuthnCredential.user_id == user.id)
        .order_by(WebAuthnCredential.created_at)
    ).scalars().all()


def credential_by_raw_id(raw_id):
    return db.session.execute(
        db.select(WebAuthnCredential).filter_by(credential_id=raw_id)
    ).scalar_one_or_none()


def has_security_key(user):
    return db.session.execute(
        db.select(WebAuthnCredential.id)
        .where(WebAuthnCredential.user_id == user.id).limit(1)
    ).scalar_one_or_none() is not None


class AdminLoginCode(db.Model):
    __tablename__ = "admin_login_codes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    code_hash = db.Column(db.String(255), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True))

class AuthorInvite(db.Model):
    __tablename__ = "author_invites"

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(255))           # null = anyone with the link
    note = db.Column(db.String(200), nullable=False, default="", server_default="")
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    max_uses = db.Column(db.Integer, nullable=False, default=1)
    uses = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    invited_by = db.relationship("User", foreign_keys=[invited_by_id])

    @property
    def is_live(self):
        return (self.revoked_at is None
            and self.uses < self.max_uses
            and self.expires_at > _utcnow())

class AuthorInviteUse(db.Model):
    __tablename__ = "author_invite_uses"
    __table_args__ = (UniqueConstraint("invite_id", "user_id", name="uq_invite_use"),)

    id = db.Column(db.Integer, primary_key=True)
    invite_id = db.Column(db.Integer, db.ForeignKey("author_invites.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    used_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    invite = db.relationship("AuthorInvite")
    user = db.relationship("User")

SUB_GRANTING = ("active","trialing")

class Subscription(db.Model):
    __tablename__ = "subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    polar_subscription_id = db.Column(db.String(64), unique=True, nullable=False)
    polar_customer_id = db.Column(db.String(64), nullable=False, default="",
                                  server_default="")
    polar_product_id = db.Column(db.String(64), nullable=False, default="",
                                 server_default="")
    plan = db.Column(db.String(32), nullable=False, default="", server_default="")
    status = db.Column(db.String(32), nullable=False, default="incomplete",
                       server_default="incomplete", index=True)
    cancel_at_period_end = db.Column(db.Boolean, nullable=False, default=False,
                                     server_default="false")
    current_period_start = db.Column(db.DateTime(timezone=True))
    current_period_end = db.Column(db.DateTime(timezone=True))
    started_at = db.Column(db.DateTime(timezone=True))
    ends_at = db.Column(db.DateTime(timezone=True))
    canceled_at = db.Column(db.DateTime(timezone=True))
    event_at = db.Column(db.DateTime(timezone=True))
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                           onupdate=_utcnow, nullable=False)
    amount = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    currency = db.Column(db.String(8), nullable=False, default="usd",
                         server_default="usd")
    recurring_interval = db.Column(db.String(16), nullable=False, default="month",
                                   server_default="month")
    recurring_interval_count = db.Column(db.Integer, nullable=False, default=1,
                                         server_default="1")
    source = db.Column(db.String(16), nullable=False, default="polar",
                       server_default="polar", index=True)
    note = db.Column(db.Text, nullable=False, default="", server_default="")
    granted_by_id = db.Column(db.Integer,
                              db.ForeignKey("users.id", ondelete="SET NULL"))

    granted_by = db.relationship("User", foreign_keys=[granted_by_id])

    @property
    def is_manual(self):
        return self.source == "manual"

    user = db.relationship("User", foreign_keys=[user_id])

    @property
    def grants_access(self):
        return self.status in SUB_GRANTING


class WebhookEvent(db.Model):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("source", "event_id",
                                       name="webhook_events_source_event_id_key"),)

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(32), nullable=False, default="polar",
                       server_default="polar")
    event_id = db.Column(db.String(128), nullable=False)
    event_type = db.Column(db.String(64), nullable=False, default="",
                           server_default="")
    received_at = db.Column(db.DateTime(timezone=True), default=_utcnow,
                            nullable=False)

def active_subscription(user):
    """The row granting paid access right now, if any.

    The period end is checked as well as the status. Polar pushes
    current_period_end forward on every subscription.cycled, so a live
    subscription always sits in the future - but a complimentary grant has no
    provider behind it to renew, and without this it would never expire.
    A webhook we never receive therefore costs access at period end rather
    than granting it for ever, which is the right way round.
    """
    if user is None:
        return None
    now = _utcnow()
    return db.session.execute(
        db.select(Subscription)
        .where(Subscription.user_id == user.id,
               Subscription.status.in_(SUB_GRANTING),
               db.or_(Subscription.current_period_end.is_(None),
                      Subscription.current_period_end > now))
        .order_by(Subscription.created_at.desc()).limit(1)
    ).scalar_one_or_none()
