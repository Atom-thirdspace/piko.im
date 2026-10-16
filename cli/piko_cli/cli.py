import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import api, config, output, runner
from .output import Fail, bold, dim, green, red

def cmd_login(args):
    print("Make a key at %s/settings/#api"
          % config.api_base().replace("/api/v1", ""))
    print(dim("Give it catalog:read and me:read."))
    raw = args.token or input("Paste your key: ").strip()
    if not raw.startswith("piko_sk_"):
        raise Fail("That doesn't look like a Piko key (they start piko_sk_).")

    config.save_token(raw, api=args.api)
    who = api.whoami()
    print(green("Signed in as ") + bold(who.get("username") or "?")
          + dim("  (%s)" % config.masked()))
    return 0

def cmd_logout(args):
    print("Make a key at %s/settings/#api"
          % config.api_base().replace("/api/v1", ""))
    print(dim("Give it catalog:read and me:read."))
    raw = args.token or input("Paste your key: ").strip()
    if not raw.startswith("piko_sk_"):
        raise Fail("That doesn't look like a Piko key (they start piko_sk_).")

    config.save_token(raw, api=args.api)
    who = api.whoami()
    print(green("Signed in as ") + bold(who.get("username") or "?")
          + dim("  (%s)" % config.masked()))
    return 0

def cmd_logout(_args):
    config.clear_token()
    print("Key removed from %s" % config.CONFIG)
    return 0


def cmd_whoami(_args):
    who = api.whoami()
    output.header(who.get("username") or "you")
    output.row("xp", str(who.get("xp_total", 0)))
    output.row("streak", "%s days (best %s)"
               % (who.get("streak_days", 0), who.get("streak_best", 0)))
    output.row("pro", "yes" if who.get("pro") else "no")
    key = who.get("key") or {}
    output.row("key", "%s  %s" % (key.get("name") or "-",
                                  ", ".join(key.get("scopes") or [])))
    return 0

def cmd_tracks(_args):
    data = api.tracks()
    output.header("Course Paths")
    for row in data.get("items", []):
        output.row(bold(row["slug"].ljust(18)), row["title"],
                   dim("%d units" % row.get("units", 0)))
    return 0


def cmd_track(args):
    data = api.track(args.slug)
    output.header(data["title"])
    if data.get("description"):
        output.note(data["description"])
    for unit in data.get("units", []):
        print()
        print("  " + bold(unit["title"]) + dim("  [%s]" % (unit.get("level") or "")))
        for lesson in unit.get("lessons", []):
            mark = {"code": "</>", "quiz": "?", "reading": "-"}.get(
                lesson["kind"], "-")
            output.row(dim(mark), lesson["title"].ljust(38),
                       dim("%s xp" % lesson.get("xp", 0)))
    return 0

def cmd_problems(args):
    data = api.problems(topic=args.topic, difficulty=args.difficulty,
                        q=args.search, page=args.page)
    items = data.get("items", [])
    output.header("Problems  (page %s of %s, %s total)"
                  % (data.get("page", 1), data.get("pages", 1),
                     data.get("total", 0)))
    if not items:
        output.note("Nothing matched. The catalogue may still be empty.")
        return 0
    for row in items:
        output.row(bold(row["slug"].ljust(26)),
                   output.difficulty(row.get("difficulty")).ljust(16),
                   dim((row.get("topic") or "-").ljust(14)),
                   row["title"])
    return 0

def cmd_show(args):
    data = api.problem(args.slug)
    output.header("%s  (%s, %s xp)"
                  % (data["title"], data.get("difficulty"), data.get("xp")))
    print()
    print(data.get("statement_md") or "(no statement)")
    samples = data.get("samples") or []
    if samples:
        output.header("Samples")
        for i, case in enumerate(samples, 1):
            print(dim("  case %d input" % i))
            print(_indent(case.get("stdin", "")))
            print(dim("  expected"))
            print(_indent(case.get("expected_stdout", "")))
    output.note("%d tests in total; the rest are hidden."
                % data.get("total_tests", len(samples)))
    return 0


def _indent(text):
    return "\n".join("    " + line for line in (text or "").splitlines()) or "    "

def cmd_get(args):
    data = api.problem(args.slug)
    language = args.lang
    spec = runner.LANGUAGES[language]

    folder = Path(args.into or data["slug"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "samples").mkdir(exist_ok=True)

    (folder / "statement.md").write_text(
        "# %s\n\n%s\n" % (data["title"], data.get("statement_md") or ""),
        encoding="utf-8")

    for i, case in enumerate(data.get("samples") or [],1):
        (folder / "samples" / ("%02d.in" % i)).write_text(
            case.get("stdin", ""), encoding="utf-8")
        (folder / "samples" / ("%02d.out" % i)).write_text(
            case.get("expected_stdout", ""), encoding="utf-8")

    source = folder / spec["source"]
    if source.exists():
        output.note("kept your existing %s" % spec["source"])
    else:
        source.write_text(spec["stub"], encoding="utf-8")

    (folder / "piko.json").write_text(json.dumps({
        "slug": data["slug"], "title": data["title"],
        "language": language,
        "time_limit_sec": data.get("time_limit_sec"),
        "total_tests": data.get("total_tests"),
    }, indent=2), encoding="utf-8")

    print(green("Ready in ") + bold(str(folder)))
    output.note("edit %s, then run `piko test` inside it" % spec["source"])
    return 0

def cmd_test(args):
    folder = Path(args.folder or ".")
    meta = {}
    if (folder / "piko.json").exists():
        meta = json.loads((folder / "piko.json").read_text(encoding="utf-8"))

    language = args.lang or meta.get("language") or runner.detect(folder)
    if language is None:
        raise Fail("No solution file here. Run `piko get <problem>` first.")

    cases = sorted((folder / "samples").glob("*.in")) \
        if (folder / "samples").is_dir() else []
    if not cases:
        raise Fail("No sample cases in %s/samples." % folder)

    runner.compile_if_needed(folder, language)

    output.header("%s  (%s, %d sample%s)"
                  % (meta.get("title") or folder.name,
                     runner.LANGUAGES[language]["label"],
                     len(cases), "" if len(cases) == 1 else "s"))

    passed = 0
    for case in cases:
        expected_file = case.with_suffix(".out")
        expected = expected_file.read_text(encoding="utf-8") \
            if expected_file.exists() else ""
        ran, got, why = runner.run_case(
            folder, language, case.read_text(encoding="utf-8"))

        if ran and runner.normalise(got) == runner.normalise(expected):
            output.ok(case.stem)
            passed += 1
            continue

        output.bad(case.stem + (("  " + why) if why else ""))
        if ran:
            print(dim("    expected"))
            print(_indent(runner.normalise(expected)))
            print(dim("    got"))
            print(_indent(runner.normalise(got)))

    print()
    if passed == len(cases):
        print(green("  %d/%d samples pass." % (passed, len(cases))))
        output.note("Samples only. The hidden tests decide the real verdict.")
        return 0
    print(red("  %d/%d samples pass." % (passed, len(cases))))
    return 1


def cmd_open(args):
    site = config.api_base().replace("/api/v1", "")
    url = site + ("/problems/%s/" % args.slug if args.slug else "/")
    print("Opening " + url)
    webbrowser.open(url)
    return 0

def build_parser():
    parser = argparse.ArgumentParser(
         prog="piko", description="Work on Piko from your own machine.")
    parser.add_argument("--api", help="override the API base url")
    subs = parser.add_subparsers(dest="command")

    p = subs.add_parser("login", help="save an API key")
    p.add_argument("--token")
    p.set_defaults(fn=cmd_login)

    subs.add_parser("logout", help="forget the saved key").set_defaults(fn=cmd_logout)
    subs.add_parser("whoami", help="who the saved key belongs to").set_defaults(fn=cmd_whoami)
    subs.add_parser("tracks", help="list course paths").set_defaults(fn=cmd_tracks)

    p = subs.add_parser("track", help="one path, unit by unit")
    p.add_argument("slug")
    p.set_defaults(fn=cmd_track)

    p = subs.add_parser("problems", help="browse problems")
    p.add_argument("--topic")
    p.add_argument("--difficulty", choices=("easy", "medium", "hard"))
    p.add_argument("--search")
    p.add_argument("--page", type=int, default=1)
    p.set_defaults(fn=cmd_problems)

    p = subs.add_parser("show", help="read a problem")
    p.add_argument("slug")
    p.set_defaults(fn=cmd_show)

    p = subs.add_parser("get", help="scaffold a problem locally")
    p.add_argument("slug")
    p.add_argument("--lang", default="python", choices=tuple(runner.LANGUAGES))
    p.add_argument("--into")
    p.set_defaults(fn=cmd_get)

    p = subs.add_parser("test", help="run the sample cases")
    p.add_argument("folder", nargs="?")
    p.add_argument("--lang", choices=tuple(runner.LANGUAGES))
    p.set_defaults(fn=cmd_test)

    p = subs.add_parser("open", help="open Piko in a browser")
    p.add_argument("slug", nargs="?")
    p.set_defaults(fn=cmd_open)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return 0
    if args.api:
        config.save_token(config.token(), api=args.api)
    try:
        return args.fn(args)
    except Fail as exc:
        print(red("error: ") + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130