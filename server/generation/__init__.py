import random

import click

from ..models import db

from .base import REGISTRY, Draft            # noqa: F401  (re-exported)
from .verify import Rejected, verify
from . import templates                      # noqa: F401  (registers them)


def save_draft(draft, source):
    from ..models import GeneratedProblem, db

    clash = db.session.execute(
        db.select(GeneratedProblem.id).filter_by(slug=draft.slug)
    ).scalar_one_or_none()
    if clash is not None:
        raise Rejected("a draft with slug %r already exists" % draft.slug)

    payload = verify(draft)                  # runs the reference for real
    row = GeneratedProblem(
        source=source, slug=draft.slug, title=draft.title, topic=draft.topic,
        difficulty=draft.difficulty, xp=draft.xp,
        statement_md=draft.statement.strip(), payload=payload)
    db.session.add(row)
    db.session.commit()
    return row


LLM_PLAN = [
    ("arrays", "easy", "a single pass with two pointers"),
    ("hashing", "easy", "counting with a dictionary"),
    ("searching", "medium", "binary searching an answer range"),
    ("stacks-queues", "easy", "using a stack to match pairs"),
]


def register_cli(app):
    @app.cli.command("gen-template")
    def _gen_template():
        """Run every registered template generator once."""
        made, failed = 0, 0
        for name, fn in sorted(REGISTRY.items()):
            seed = random.randrange(1 << 30)
            try:
                row = save_draft(fn(seed), "template:%s" % name)
                print("drafted %s (%d tests)"
                      % (row.slug, len(row.payload["tests"])))
                made += 1
            except Rejected as exc:
                print("REJECTED %s: %s" % (name, exc))
                failed += 1
        print("%d drafted, %d rejected - review at /admin/generated/"
              % (made, failed))

    @app.cli.command("gen-llm")
    def _gen_llm():
        """Draft one problem per topic with an LLM, then verify it."""
        from .llm import DraftError, draft_problem

        made, failed = 0, 0
        for topic, difficulty, skill in LLM_PLAN:
            seed = random.randrange(1 << 30)
            try:
                row = save_draft(
                    draft_problem(topic, difficulty, skill, seed), "llm")
                print("drafted %s (%d tests)"
                      % (row.slug, len(row.payload["tests"])))
                made += 1
            except (DraftError, Rejected) as exc:
                print("REJECTED %s/%s: %s" % (topic, skill, exc))
                failed += 1
        print("%d drafted, %d rejected - review at /admin/generated/"
              % (made, failed))

    @app.cli.command("gen-bulk")
    @click.option("--rounds", default=5, show_default=True,
              help="how many seeds per generator")
    @click.option("--publish", is_flag=True,
              help="publish immediately instead of parking for review")
    def _gen_bulk(rounds, publish):
        """Draft every template generator over several seeds."""
        from ..models import User, publish_generated

        reviewer = None
        if publish:
            from ..admin_gate import admin_emails
            emails = admin_emails()
            reviewer = db.session.execute(
                db.select(User).where(User.email.in_(emails)).limit(1)
            ).scalar_one_or_none() if emails else None
            if reviewer is None:
                print("no admin user found - drafting for review instead")
                publish = False
        made, live, failed = 0, 0, 0
        for name, fn in sorted(REGISTRY.items()):
            for _ in range(rounds):
                seed = random.randrange(1 << 30)
                try:
                    row = save_draft(fn(seed), "template:%s" % name)
                except Rejected as exc:
                    print("REJECTED %s: %s" % (name, exc))
                    failed += 1
                    continue
                made += 1
                if publish and publish_generated(row, reviewer) is not None:
                    live += 1
                print("drafted %s (%d tests)%s"
                      % (row.slug, len(row.payload["tests"]),
                         " - published" if publish else ""))

        print("%d drafted, %d published, %d rejected" % (made, live, failed))