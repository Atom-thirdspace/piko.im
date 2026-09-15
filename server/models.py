import os
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

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
    interest = db.Column(db.String(64))
    avatar_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    welcome_email_sent_at = db.Column(db.DateTime(timezone=True), nullable =True)
    identities = db.relationship(
        "OAuthIdentity", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<User {self.id} {self.email}>"
    
    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)
    
    def check_password(self, raw):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw)
    
    @property
    def needs_onboarding(self):
        return not self.username or not self.interest


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
    user.last_login_at = _utcnow()

    db.session.commit()
    return user, is_new

def mark_welcome_sent(user_id):
    user = db.session.get(User, user_id)
    if user is not None:
        user.welcome_email_sent_at = _utcnow()
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

def create_email_user(email,username,name,interest,password):
    user = User(
        email=email.lower(),
        username=username.lower(),
        name=name,
        interest=interest,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user

def complete_profile(user, username, interest):
    user.username = username.lower()
    user.interest = interest
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

    user = db.relationship("User")
    problem = db.relationship("Problem")


def record_submission(user_id, problem, language, source, result):
    sub = Submission(
        user_id=user_id, problem_id=problem.id, language=language, source=source,
        verdict=result.verdict, passed=result.passed, total=result.total,
        max_time_ms=result.max_time_ms, compile_output=result.compile_output or None,
    )
    db.session.add(sub)
    db.session.commit()
    return sub


def first_accepted(user_id, problem_id):
    return db.session.execute(
        db.select(Submission.id).filter_by(
            user_id=user_id, problem_id=problem_id, verdict="accepted"
        ).limit(1)
    ).scalar_one_or_none() is None
