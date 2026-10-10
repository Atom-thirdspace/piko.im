import json

import click

from ..models import DRAFT, PUBLISHED, Boss, BossQuestion, db

BOSSES = (
    {"slug": "big-o-wyrm", "name": "The Big-O Wyrm", "sigil": "\U0001F409",
     "tier": 1, "hp": 240, "attack": 12, "difficulty": "easy", "position": 1,
     "blurb": "It only asks what things cost. That is the whole trick."},
    {"slug": "hash-hydra", "name": "The Hash Hydra", "sigil": "\U0001F40D",
     "tier": 2, "hp": 400, "attack": 16, "difficulty": "medium", "position": 2,
     "blurb": "Collisions, load factors, and why your average case lied."},
    {"slug": "graph-titan", "name": "The Graph Titan", "sigil": "\U0001F578",
     "tier": 3, "hp": 600, "attack": 20, "difficulty": "hard", "position": 3,
     "blurb": "Traversals, shortest paths, and the edge cases between."},
)

REQUIRED = ("prompt", "answer")


def _validate(row, index):
    for field in REQUIRED:
        if not (row.get(field) or "").strip():
            return "row %d has no %s" % (index, field)

    kind = row.get("kind", "choice")
    if kind not in ("choice", "short"):
        return "row %d has kind %r" % (index, kind)

    if kind == "choice":
        choices = row.get("choices") or []
        if len(choices) < 2:
            return "row %d is multiple choice with %d options" % (index,
                                                                  len(choices))
        if row["answer"] not in choices:
            return ("row %d: the answer %r is not one of its own choices"
                    % (index, row["answer"]))
        if len(set(choices)) != len(choices):
            return "row %d has a duplicate choice" % index

    if row.get("difficulty", "easy") not in ("easy", "medium", "hard"):
        return "row %d has difficulty %r" % (index, row.get("difficulty"))

    seconds = row.get("seconds", 20)
    if not isinstance(seconds, int) or not 5 <= seconds <= 120:
        return "row %d has seconds %r" % (index, seconds)
    return None


def load_questions(rows, publish=False):
    complaints = [c for c in
                  (_validate(row, i + 1) for i, row in enumerate(rows))
                  if c]
    if complaints:
        return 0, 0, complaints

    # The prompt is the natural key - nobody writes the same question twice on
    # purpose, and it means an edited file can be re-loaded.
    seen = set(db.session.execute(db.select(BossQuestion.prompt)).scalars())

    added = skipped = 0
    for row in rows:
        if row["prompt"] in seen:
            skipped += 1
            continue
        seen.add(row["prompt"])
        db.session.add(BossQuestion(
            kind=row.get("kind", "choice"),
            prompt=row["prompt"],
            answer=row["answer"],
            alternates=row.get("alternates", []),
            choices=row.get("choices", []),
            explain_md=row.get("explain", ""),
            topic=row.get("topic"),
            difficulty=row.get("difficulty", "easy"),
            seconds=row.get("seconds", 20),
            status=PUBLISHED if publish else DRAFT))
        added += 1

    db.session.commit()
    return added, skipped, []


def load_bosses():
    existing = set(db.session.execute(db.select(Boss.slug)).scalars())
    added = 0
    for row in BOSSES:
        if row["slug"] in existing:
            continue
        db.session.add(Boss(**row))
        added += 1
    db.session.commit()
    return added


def register_cli(app):
    @app.cli.command("arena-import")
    @click.argument("path")
    @click.option("--publish", is_flag=True,
                  help="Publish straight away instead of leaving drafts.")
    def _import(path, publish):
        with open(path, encoding="utf-8") as handle:
            rows = json.load(handle)

        added, skipped, complaints = load_questions(rows, publish=publish)
        if complaints:
            print("nothing was loaded:")
            for line in complaints:
                print("  " + line)
            raise SystemExit(1)
        print("added %d, skipped %d already there" % (added, skipped))

    @app.cli.command("arena-bosses")
    def _bosses():
        print("added %d bosses" % load_bosses())

    @app.cli.command("arena-pools")
    def _pools():
        bosses = db.session.execute(
            db.select(Boss).order_by(Boss.tier, Boss.position)).scalars().all()
        for boss in bosses:
            stmt = (db.select(db.func.count()).select_from(BossQuestion)
                    .where(BossQuestion.status == PUBLISHED))
            if boss.topic:
                stmt = stmt.where(BossQuestion.topic == boss.topic)
            if boss.difficulty:
                stmt = stmt.where(BossQuestion.difficulty == boss.difficulty)
            size = db.session.execute(stmt).scalar() or 0
            flag = "" if size >= 8 else "   <-- too thin to fight"
            print("%-14s %-8s %3d%s" % (boss.slug, boss.difficulty, size, flag))
