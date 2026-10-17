import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path

from . import api, config, output, runner
from .output import Fail, amber, bold, dim, green, red

POLL_EVERY = 1.0
POLL_LIMIT = 120

def cmd_login(args):
    print("Make a key at %s/settings/#api"
          % config.api_base().replace("/api/v1", ""))
    print(dim("catalog:read and me:read to browse; add submissions:write "
              "to submit from here."))
    raw = args.token or input("Paste your key: ").strip()
    if not raw.startswith("piko_sk_"):
        raise Fail("That doesn't look like a Piko key (they start piko_sk_).")

    config.save_token(raw, api=args.api)
    who = api.whoami()
    print(green("Signed in as ") + bold(who.get("username") or "?")
          + dim("  (%s)" % config.masked()))
    scopes = (who.get("key") or {}).get("scopes") or []
    if "submissions:write" not in scopes:
        output.note("This key cannot submit. Add submissions:write to use "
                    "`piko submit`.")
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

def _load_meta(folder):
    path = folder / "piko.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise Fail("piko.json in %s is not valid JSON." % folder)


def _sample_cases(folder):
    box = folder / "samples"
    return sorted(box.glob("*.in")) if box.is_dir() else []

def _resolve_language(folder, meta, override):
    language = override or meta.get("language") or runner.detect(folder)
    if language is None:
        raise Fail("No solution file here. Run `piko get <problem>` first.")
    if language not in runner.LANGUAGES:
        raise Fail("This CLI can't run %r locally." % language)
    return language

def _run_samples(folder, language, cases, quiet=False):
    runner.compile_if_needed(folder, language)
    passed = 0
    for case in cases:
        expected_file = case.with_suffix(".out")
        expected = (expected_file.read_text(encoding="utf-8")
                    if expected_file.exists() else "")
        ran, got, why = runner.run_case(
            folder, language, case.read_text(encoding="utf-8"))

        if ran and runner.normalise(got) == runner.normalise(expected):
            passed += 1
            if not quiet:
                output.ok(case.stem)
            continue
        if quiet:
            continue

        output.bad(case.stem + (("  " + why) if why else ""))
        if ran:
            print(dim("    expected"))
            print(_indent(runner.normalise(expected)))
            print(dim("    got"))
            print(_indent(runner.normalise(got)))
    return passed


def cmd_test(args):
    folder = Path(args.folder or ".")
    meta = _load_meta(folder)
    language = _resolve_language(folder, meta, args.lang)

    cases = _sample_cases(folder)
    if not cases:
        raise Fail("No sample cases in %s/samples." % folder)

    output.header("%s  (%s, %d sample%s)"
                  % (meta.get("title") or folder.name,
                     runner.LANGUAGES[language]["label"],
                     len(cases), "" if len(cases) == 1 else "s"))

    passed = _run_samples(folder, language, cases)
    print()
    if passed == len(cases):
        print(green("  %d/%d samples pass." % (passed, len(cases))))
        output.note("Samples only. `piko submit` runs the hidden tests.")
        return 0
    print(red("  %d/%d samples pass." % (passed, len(cases))))
    return 1


def _await_verdict(sub_id):
    frames = "|/-\\"
    waited, i = 0.0, 0
    while waited < POLL_LIMIT:
        body = api.submission(sub_id)
        if body.get("status") == "done":
            if sys.stdout.isatty():
                sys.stdout.write("\r" + " " * 32 + "\r")
            return body
        if sys.stdout.isatty():
            sys.stdout.write("\r  judging %s " % frames[i % 4])
            sys.stdout.flush()
        i += 1
        time.sleep(POLL_EVERY)
        waited += POLL_EVERY
    raise Fail("Still judging after %ds. Check it later with "
               "`piko submit --check %d`." % (POLL_LIMIT, sub_id))

def _print_verdict(body):
    label = body.get("label") or body.get("verdict") or "?"
    passed, total = body.get("passed" , 0), body.get("total", 0)
    tally = "  %d/%d tests" % (passed, total)

    if body.get("verdict") == "accepted":
        print(green("  Accepted") + tally)
        if body.get("max_time_ms"):
            output.note("slowest case %d ms" % body["max_time_ms"])
        return 0

    print(red("  " + label) + tally)
    if body.get("compile_output"):
        print(dim("  the compiler said"))
        print(_indent(body["compile_output"]))

    first = body.get("first_failure")
    if first:
        n = first.get("index", 0) + 1
        where = "sample %d" % n if first.get("is_sample") else "hidden case %d" % n
        print(dim("  first failure: %s  (%s)" % (where, first.get("label"))))
        if first.get("is_sample"):
            print(dim("    input"))
            print(_indent(first.get("stdin", "")))
            print(dim("    expected"))
            print(_indent(first.get("expected", "")))
            print(dim("    got"))
            print(_indent(first.get("actual", "")))
        else:
            output.note("Hidden cases report pass or fail only.")
    return 1

def cmd_submit(args):
    if args.check:
        return _print_verdict(api.submission(args.check))
    folder = Path(args.folder or ".")
    meta = _load_meta(folder)
    slug = args.slug or meta.get("slug")
    if not slug:
        raise Fail("Which problem? Run this inside a `piko get` folder, "
                   "or pass the slug.")

    language = _resolve_language(folder, meta, args.lang)
    source_file = folder / runner.LANGUAGES[language]["source"]
    if not source_file.exists():
        raise Fail("No %s in %s." % (source_file.name, folder))
    source = source_file.read_text(encoding="utf-8")
    if not source.strip():
        raise Fail("%s is empty." % source_file.name)

    cases = _sample_cases(folder)
    if cases and not args.force:
        print(dim("Checking samples first..."))
        if _run_samples(folder, language, cases, quiet=True) != len(cases):
            print(red("  Samples fail.") + "  Run `piko test` to see why.")
            output.note("Pass --force to submit anyway.")
            return 1
    
    output.header("Submitting %s" % slug)
    output.row(dim(runner.LANGUAGES[language]["label"]),
               dim("%d bytes" % len(source.encode("utf-8"))))

    body = api.submit(slug, language, source)
    if body.get("cached"):
        output.note("Identical code, unchanged tests - reusing the verdict.")
        return _print_verdict(body)

    if body.get("status") == "done":
        return _print_verdict(body)
    return _print_verdict(_await_verdict(body["submission_id"]))

def cmd_next(_args):
    data = api.next_up()
    lesson_row, problem_row = data.get("lesson"), data.get("problem")
    site = config.api_base().replace("/api/v1", "")

    if not lesson_row and not problem_row:
        output.header("Nothing queued")
        output.note("Enrol in a path at %s/learn/ and this will fill up." % site)
        return 0

    if lesson_row:
        output.header("Next Lesson")
        mark = {"code": "</>", "quiz": "?", "reading": "-"}.get(
            lesson_row["kind"], "-")
        output.row(dim(mark), bold(lesson_row["title"]),
                   dim("%s xp" % lesson_row.get("xp", 0)))
        output.note(lesson_row["url"])
        if lesson_row.get("problem"):
            output.note("piko get %s" % lesson_row["problem"])


    if problem_row:
        output.header("Or try this problem")
        output.row(bold(problem_row["slug"]),
                   output.difficulty(problem_row.get("difficulty")),
                   problem_row["title"])
        if data.get("reason"):
            output.note(data["reason"])
        output.note("piko get %s" % problem_row["slug"])
    return 0


def cmd_streak(_args):
    data = api.streak()
    state = data.get("state") or {}
    output.header("Streak")
    output.row("days", "%s  (best %s)" % (data.get("streak_days", 0),
                                          data.get("streak_best", 0)))

    status = state.get("status","none")
    painted = {"safe": green, "frozen": amber,
               "at_risk": amber, "broken": red}.get(status, dim)
    output.row("status", painted(status))

    goal, earned = data.get("goal_xp", 0), data.get("today_xp", 0)
    if goal:
        left = data.get("remaining_xp", 0)
        output.row("today", "%d / %d XP%s"
                   % (earned, goal, "" if not left else "  (%d to go)" % left))
    else:
        output.row("today", "%d XP" % earned)

    if state.get("freezes"):
        output.row("freezes", str(state["freezes"]))
    if status == "at_risk":
        output.note("Nothing earned today yet. One lesson keeps it alive.")
    return 0


def cmd_potd(_args):
    data = api.potd()
    row = data["problem"]
    output.header("Problem of the day  %s" % dim(data["day"]))
    output.row(bold(row["slug"]), output.difficulty(row.get("difficulty")),
               row["title"])
    output.row(dim("%d XP  +%d bonus  %d solved it today"
                   % (row.get("xp", 0), data.get("bonus", 0),
                      data.get("solvers", 0))))
    output.note("Already done." if data.get("solved")
                else "piko get %s" % row["slug"])
    return 0


def cmd_lesson(args):
    parts = args.path.strip("/").split("/")
    if len(parts) != 3:
        raise Fail("Give it track/unit/lesson, as `piko next` prints it.")
    data = api.lesson(*parts)

    output.header("%s  (%s, %s xp)"
                  % (data["title"], data.get("kind"), data.get("xp")))
    print()
    print(data.get("body_md") or "(no body)")

    for i, question in enumerate(data.get("quiz") or [], 1):
        print()
        print(bold("  %d. %s" % (i, question.get("prompt", ""))))
        for choice in question.get("choices") or []:
            print("     %s) %s" % (choice.get("id"), choice.get("text")))
    if data.get("quiz"):
        output.note("Answers are only checked on the site.")
    if data.get("problem"):
        output.note("piko get %s" % data["problem"])
    return 0


def cmd_watch(args):
    folder = Path(args.folder or ".")
    meta = _load_meta(folder)
    language = _resolve_language(folder, meta, args.lang)
    source = folder / runner.LANGUAGES[language]["source"]

    cases = _sample_cases(folder)
    if not cases:
        raise Fail("No sample cases in %s/samples." % folder)

    print("Watching %s - Ctrl-C to stop." % bold(str(source)))
    stamp = None
    while True:
        try:
            now = source.stat().st_mtime
        except OSError:
            now = None

        if now is not None and now != stamp:
            stamp = now
            if sys.stdout.isatty():
                sys.stdout.write("\033[2J\033[H")
            output.header("%s  (%d sample%s)"
                          % (meta.get("title") or folder.name, len(cases),
                             "" if len(cases) == 1 else "s"))
            passed = _run_samples(folder, language, cases)
            print()
            paint = green if passed == len(cases) else red
            print(paint("  %d/%d samples pass." % (passed, len(cases))))
            print(dim("  waiting for a change..."))
        time.sleep(0.4)


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

    p = subs.add_parser("submit", help="send it to the real judge")
    p.add_argument("slug", nargs="?")
    p.add_argument("--folder")
    p.add_argument("--lang", choices=tuple(runner.LANGUAGES))
    p.add_argument("--force", action="store_true",
                   help="submit even if the samples fail")
    p.add_argument("--check", type=int, metavar="ID",
                   help="print the verdict of an earlier submission")
    p.set_defaults(fn=cmd_submit)

    p = subs.add_parser("watch", help="re-run samples whenever you save")
    p.add_argument("folder", nargs="?")
    p.add_argument("--lang", choices=tuple(runner.LANGUAGES))
    p.set_defaults(fn=cmd_watch)

    subs.add_parser("next", help="what to do right now").set_defaults(fn=cmd_next)
    subs.add_parser("streak", help="your streak and today's goal").set_defaults(fn=cmd_streak)
    subs.add_parser("potd", help="the problem of the day").set_defaults(fn=cmd_potd)

    p = subs.add_parser("lesson", help="read a lesson here")
    p.add_argument("path", help="track/unit/lesson")
    p.set_defaults(fn=cmd_lesson)

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
    if args.api and args.fn is not cmd_login:
        config.set_api(args.api)
    try:
        return args.fn(args)
    except Fail as exc:
        print(red("error: ") + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130