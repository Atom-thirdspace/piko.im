import hashlib
import re

K = 12          # tokens per k-gram
WINDOW = 8      # winnowing window; guarantees a match on any run of K+WINDOW-1
MIN_TOKENS = 60         # below this, similarity means nothing
FLAG_AT = 0.80          # containment above which a pair is worth a human

# Kept verbatim so structure survives renaming. The union across the three
# languages is fine - a Python file simply never contains 'template'.
KEYWORDS = frozenset("""
and as assert async await break case catch class const continue def default del
do elif else except extern final finally float for from global goto if import in
int is lambda let long namespace new nonlocal not or pass private protected public
raise return short signed sizeof static struct switch template this throw try
typedef union unsigned using virtual void volatile while with yield bool char
double enum export friend inline mutable operator register
""".split())

_STRINGS = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\])*"'
                      r"|'(?:\\.|[^'\\])*'")
_COMMENTS = re.compile(r'//[^\n]*|#[^\n]*|/\*[\s\S]*?\*/')
_TOKEN = re.compile(r'[A-Za-z_]\w*|\d+\.?\d*|[^\sA-Za-z_\d]')


def normalise(source):
    text = _COMMENTS.sub(" ", _STRINGS.sub(' "S" ', source or ""))
    tokens = []
    for tok in _TOKEN.findall(text):
        if tok[0].isdigit():
            tokens.append("N")
        elif tok[0].isalpha() or tok[0] == "_":
            tokens.append(tok if tok in KEYWORDS else "V")
        else:
            tokens.append(tok)
    return tokens


def _hash(gram):
    return int.from_bytes(
        hashlib.blake2b(" ".join(gram).encode("utf-8"), digest_size=8).digest(),
        "big", signed=False) >> 1        # keep it inside a signed bigint


def fingerprints(source, k=K, window=WINDOW):
    tokens = normalise(source)
    if len(tokens) < MIN_TOKENS:
        return set()

    grams = [_hash(tokens[i:i + k]) for i in range(len(tokens) - k + 1)]
    if len(grams) <= window:
        return set(grams)

    picked, last = set(), -1
    for i in range(len(grams) - window + 1):
        win = grams[i:i + window]
        low = min(win)
        # Rightmost minimum, which keeps the fingerprint set small and stable.
        j = i + max(idx for idx, v in enumerate(win) if v == low)
        if j != last:
            picked.add(grams[j])
            last = j
    return picked


def containment(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def index_submission(sub):
    from .models import SubmissionFingerprint, db

    fps = fingerprints(sub.source)
    if not fps:
        return set()

    # A re-judge runs this again for a submission already indexed.
    existing = set(db.session.execute(
        db.select(SubmissionFingerprint.hash)
        .where(SubmissionFingerprint.submission_id == sub.id)
    ).scalars())
    if existing:
        return existing

    for h in fps:
        db.session.add(SubmissionFingerprint(
            submission_id=sub.id, problem_id=sub.problem_id, hash=h))
    db.session.commit()
    return fps


def check_submission(sub, fps=None, limit=20):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import aliased

    from .models import SimilarityFlag, Submission, SubmissionFingerprint, db

    fps = fps if fps is not None else fingerprints(sub.source)
    if not fps:
        return []

    me = aliased(SubmissionFingerprint)
    them = aliased(SubmissionFingerprint)
    shared = db.func.count().label("shared")

    # Candidates first, by shared-hash count: cheap, indexed, and it keeps
    # the expensive set comparison to a handful of rows.
    candidates = db.session.execute(
        db.select(them.submission_id, shared)
        .select_from(me)
        .join(them, db.and_(them.hash == me.hash,
                            them.problem_id == me.problem_id))
        .join(Submission, Submission.id == them.submission_id)
        .where(me.submission_id == sub.id,
               them.submission_id != sub.id,
               Submission.user_id != sub.user_id)
        .group_by(them.submission_id)
        .order_by(shared.desc())
        .limit(limit)
    ).all()

    flagged = []
    for other_id, _shared in candidates:
        other_fps = set(db.session.execute(
            db.select(SubmissionFingerprint.hash)
            .where(SubmissionFingerprint.submission_id == other_id)
        ).scalars())

        score = containment(fps, other_fps)
        if score < FLAG_AT:
            continue

        db.session.add(SimilarityFlag(submission_id=sub.id,
                                      matched_id=other_id, score=score))
        flagged.append((other_id, score))

    if flagged:
        try:
            db.session.commit()
        except IntegrityError:          # already flagged by an earlier run
            db.session.rollback()
            return []
    return flagged


def register_cli(app):
    @app.cli.command("index-fingerprints")
    def _index():
        """Fingerprint every accepted submission. Safe to re-run."""
        from .models import Submission, SubmissionFingerprint, db

        done = set(db.session.execute(
            db.select(SubmissionFingerprint.submission_id).distinct()).scalars())
        subs = db.session.execute(
            db.select(Submission).where(Submission.verdict == "accepted")
        ).scalars().all()

        indexed = 0
        for s in subs:
            if s.id in done:
                continue
            if index_submission(s):
                indexed += 1
        print("indexed %d of %d accepted submissions" % (indexed, len(subs)))
