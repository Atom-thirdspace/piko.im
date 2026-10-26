import json
import re
from pathlib import Path

import click

from .models import (DRAFT, PUBLISHED, Problem, ProblemHint, ProblemTest,
                     _utcnow, db)

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIFFICULTIES = ("easy", "medium", "hard")

SOURCE_SUFFIX = {".py": "python", ".cpp": "cpp", ".c": "c", ".java": "java",
                 ".js": "javascript", ".go": "go", ".rs": "rust"}

class ImportError_(Exception):
    """Something about the folder is wrong. The message names the file."""

def _read(path, required=True):
    if not path.exists():
        if required:
            raise ImportError_("missing %s" % path.name)
        return ""
    return path.read_text(encoding="utf-8")

def _cases(folder, sample):
    if not folder.is_dir():
        return []
    out = []

    for stdin_path in sorted(folder.glob("*.in")):
        expected = stdin_path.with_suffix(".out")
        if not expected.exists():
            raise ImportError_("%s has no matching .out"
                               % stdin_path.relative_to(folder.parent))
        out.append({"stdin": stdin_path.read_text(encoding="utf-8"),
                    "expected_stdout": expected.read_text(encoding="utf-8"),
                    "is_sample": sample})
    return out

def read_folder(path):
    path = Path(path)
    if not path.is_dir():
        raise ImportError_("%s is not a folder" % path)

    try:
        meta = json.loads()
    except ValueError as exc:
        raise ImportError_("meta.json is not valid JSON: %s" % exc)

    slug = (meta.get("slug") or path.name).strip().lower()
    if not SLUG.match(slug):
        raise ImportError_("%r is not a usable slug (lowercase, digits, "
                           "hyphens)" % slug)

    difficulty = (meta.get("difficulty") or "easy").lower()
    if difficulty not in DIFFICULTIES:
        raise ImportError_("difficulty must be one of %s"
                           % ", ".join(DIFFICULTIES))

    samples = _cases(path / "samples", True)
    hidden = _cases(path / "tests", False)
    if not samples and not hidden:
        raise ImportError_("no test cases in samples/ or tests/")
    if not samples:
        raise ImportError_("at least one sample is needed - people cannot "
                           "solve what they cannot see an example of")

    reference, language = "", meta.get("reference_language") or "python"
    for candidate in sorted(path.glob("solution.*")):
        key = SOURCE_SUFFIX.get(candidate.suffix)
        if key:
            reference, language = candidate.read_text(encoding="utf-8"), key
            break

    hints = []
    hint_dir = path / "hints"
    if hint_dir.is_dir():
        hints = [h.read_text(encoding="utf-8")
                 for h in sorted(hint_dir.glob("*.md"))]


    return {
        "slug": slug,
        "title": (meta.get("title") or slug.replace("-", " ").title()).strip(),
        "statement_md": _read(path / "statement.md"),
        "editorial_md": _read(path / "editorial.md", required=False),
        "difficulty": difficulty,
        "topic": (meta.get("topic") or "").strip() or None,
        "xp_override": meta.get("xp"),
        "time_limit_sec": float(meta.get("time_limit_sec") or 2.0),
        "memory_mb": int(meta.get("memory_mb") or 256),
        "reference_source": reference,
        "reference_language": language,
        "hints": hints,
        "tests": samples + hidden,
    }

def apply(data, publish=False, replace=False):
    existing = db.session.execute(
        db.select(Problem).filter_by(slug=data["slug"])).scalar_one_or_none()

    if existing is not None and not replace:
        raise ImportError_("%s already exists - pass --replace to overwrite"
                           % data["slug"])

    problem = existing or Problem(slug=data["slug"])
    problem.title = data["title"]
    problem.statement_md = data["statement_md"]
    problem.editorial_md = data["editorial_md"]
    problem.difficulty = data["difficulty"]
    problem.topic = data["topic"]
    problem.xp_override = data["xp_override"]
    problem.time_limit_sec = data["time_limit_sec"]
    problem.memory_mb = data["memory_mb"]
    problem.reference_source = data["reference_source"]
    problem.reference_language = data["reference_language"]
    problem.status = PUBLISHED if publish else (problem.status or DRAFT)
    if publish and not problem.published_at:
        problem.published_at = _utcnow()

    if existing is None:
        db.session.add(problem)
    db.session.flush()

    problem.tests.clear()
    problem.hints.clear()
    db.session.flush()

    for i, case in enumerate(data["tests"]):
        db.session.add(ProblemTest(problem_id=problem.id, position=i,
                                   stdin=case["stdin"],
                                   expected_stdout=case["expected_stdout"],
                                   is_sample=case["is_sample"]))
    for i, body in enumerate(data["hints"]):
        db.session.add(ProblemHint(problem_id=problem.id, position=i,
                                   body_md=body, cost_xp=2))

    db.session.commit()
    return problem, existing is None


def write_folder(problem, path):
    path = Path(path) / problem.slug
    (path / "samples").mkdir(parents=True, exist_ok=True)
    (path / "tests").mkdir(parents=True, exist_ok=True)

    (path / "meta.json").write_text(json.dumps({
        "slug": problem.slug,
        "title": problem.title,
        "difficulty": problem.difficulty,
        "topic": problem.topic,
        "xp": problem.xp_override,
        "time_limit_sec": problem.time_limit_sec,
        "memory_mb": problem.memory_mb,
        "reference_language": problem.reference_language,
    }, indent=2, sort_keys=True), encoding="utf-8")

    (path / "statement.md").write_text(problem.statement_md or "",
                                       encoding="utf-8")
    if problem.editorial_md:
        (path / "editorial.md").write_text(problem.editorial_md,
                                           encoding="utf-8")
    if problem.reference_source:
        suffix = next((s for s, k in SOURCE_SUFFIX.items()
                       if k == problem.reference_language), ".txt")
        (path / ("solution" + suffix)).write_text(problem.reference_source,
                                                  encoding="utf-8")

    for group, rows in (("samples", [t for t in problem.tests if t.is_sample]),
                        ("tests", [t for t in problem.tests
                                   if not t.is_sample])):
        for i, case in enumerate(rows, 1):
            stem = path / group / ("%02d" % i)
            stem.with_suffix(".in").write_text(case.stdin, encoding="utf-8")
            stem.with_suffix(".out").write_text(case.expected_stdout,
                                                encoding="utf-8")

    if problem.hints:
        (path / "hints").mkdir(exist_ok=True)
        for i, hint in enumerate(problem.hints, 1):
            (path / "hints" / ("%02d.md" % i)).write_text(hint.body_md,
                                                          encoding="utf-8")
    return path


def register_cli(app):
    @app.cli.command("import-problem")
    @click.argument("folder", type=click.Path(exists=True))
    @click.option("--publish", is_flag=True, help="publish, not draft")
    @click.option("--replace", is_flag=True, help="overwrite an existing slug")
    @click.option("--dry-run", is_flag=True, help="parse and report only")
    def _one(folder, publish, replace, dry_run):
        """Import one problem folder."""
        try:
            data = read_folder(folder)
        except ImportError_ as exc:
            raise click.ClickException("%s: %s" % (folder, exc))

        samples = sum(1 for t in data["tests"] if t["is_sample"])
        click.echo("%s  %s  %s  %d samples, %d hidden, %d hints"
                   % (data["slug"], data["difficulty"],
                      data["topic"] or "-", samples,
                      len(data["tests"]) - samples, len(data["hints"])))
        if dry_run:
            return

        problem, created = apply(data, publish=publish, replace=replace)
        click.echo("%s %s (%s)" % ("created" if created else "updated",
                                   problem.slug, problem.status))

    @app.cli.command("import-problems")
    @click.argument("root", type=click.Path(exists=True))
    @click.option("--publish", is_flag=True)
    @click.option("--replace", is_flag=True)
    @click.option("--dry-run", is_flag=True)
    def _many(root, publish, replace, dry_run):
        folders = sorted(p for p in Path(root).iterdir()
                         if (p / "meta.json").exists())
        if not folders:
            raise click.ClickException("no folders with a meta.json under %s"
                                       % root)

        done, failed = 0, []
        for folder in folders:
            try:
                data = read_folder(folder)
                if not dry_run:
                    apply(data, publish=publish, replace=replace)
                
                done += 1
                click.echo("  ok    %s" % data["slug"])
            except ImportError_ as exc:
                failed.append((folder.name, str(exc)))
                click.echo("  skip  %s - %s" % (folder.name, exc))

        click.echo("%d imported, %d skipped" % (done, len(failed)))
        if failed and not dry_run:
            raise click.ClickException("some folders did not import")

    @app.cli.command("export-problem")
    @click.argument("slug")
    @click.argument("into", type= click.Path(), default="problems")
    def _export(slug, into):
        problem = db.session.execute(
            db.select(Problem).filter_by(slug=slug)).scalar_one_or_none()
        if problem is None:
            raise click.ClickException("no problem %r" % slug)
        click.echo("wrote %s" % write_folder(problem, into))