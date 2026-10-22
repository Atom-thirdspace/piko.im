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

SCOPES = ["catalog:read", "me:read", "submissions:read", "submissions:write",
          "progress:read", "progress:write",
          "notifications:read", "notifications:write"]

BANDS = {"mastered": green, "strong": green, "solid": amber,
         "learning": amber, "touched": dim}


def _bar(fraction, width=22):
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    return "[" + "#" * filled + dim("." * (width - filled)) + "]"

def _signed_in():
    who = api.whoami()
    print(green("Signed in as ") + bold(who.get("username") or "?")
          + dim("  (%s)" % config.masked()))
    scopes = (who.get("key") or {}).get("scopes") or []
    output.note("scopes: " + (", ".join(scopes) or "none"))
    if "submissions:write" not in scopes:
        output.note("This key cannot submit.")
    return 0


def cmd_login(args):
    """Sign in through the browser, or take a pasted key with --token."""
    if args.token:
        if not args.token.startswith("piko_sk_"):
            raise Fail("That doesn't look like a Piko key (they start piko_sk_).")
        config.save_token(args.token, api=args.api)
        return _signed_in()

    from urllib.parse import urlencode

    from . import oauth

    verifier, challenge = oauth.make_pkce()
    state = oauth.make_pkce()[0][:32]

    # The socket is bound before we ask for a code, so the redirect can
    # never arrive at a port nothing is listening on.
    server, port = oauth.listen()
    redirect_uri = "http://127.0.0.1:%d/callback" % port

    url = config.site() + "/oauth/authorize?" + urlencode({
        "response_type": "code",
        "client_id": api.CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    print("Opening your browser to approve this sign-in...")
    if not oauth.open_browser(url):
        print("Couldn't open a browser. Go to:")
        print("  " + bold(url))
    output.note("Waiting... press Ctrl-C to stop.")

    code = oauth.wait_for_code(server, state)
    body = api.exchange_code(code, verifier, redirect_uri)
    config.save_oauth(body["access_token"], body.get("refresh_token", ""),
                      body.get("expires_in", 3600), api=args.api)
    return _signed_in()


def cmd_logout(_args):
    # Tell the server first - clearing the file alone leaves a live key.
    if api.revoke_token():
        print("Signed out and the key was revoked.")
    else:
        print("Key removed from %s" % config.CONFIG)
        output.note("Nothing to revoke on the server.")
    config.clear_token()
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
            output.side_by_side(runner.normalise(expected),
                                runner.normalise(got))
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

    if body.get("status") == "pending":
        print(amber("  " + label) + "  not judged yet")
        output.note("Check again with `piko submit --check %s`."
                    % body.get("submission_id"))
        return 0

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


def cmd_editorial(args):
    data = api.problem(args.slug, fresh=True)
    text = data.get("editorial_md")
    if text:
        output.header("%s - editorial" % data["title"])
        print()
        print(text)
        return 0

    output.header(data["title"])
    if data.get("has_editorial"):
        output.note("There is one, but you have to solve it first.")
    else:
        output.note("No editorial for this problem yet.")
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
    url = site + ("/problems/%s/" % args.slug if args.slug else "/problems/")
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

    p = subs.add_parser("editorial", help="read the explanation")
    p.add_argument("slug")
    p.set_defaults(fn=cmd_editorial)

    p = subs.add_parser("lesson", help="read a lesson here")
    p.add_argument("path", help="track/unit/lesson")
    p.set_defaults(fn=cmd_lesson)

    p = subs.add_parser("open", help="open Piko in a browser")
    p.add_argument("slug", nargs="?")
    p.set_defaults(fn=cmd_open)

    p = subs.add_parser("config", help="see or change saved settings")
    p.add_argument("action", choices=("list", "get", "set", "path"),
                   nargs="?", default="list")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)

    p = subs.add_parser("cache", help="inspect the offline cache")
    p.add_argument("--clear", action="store_true")
    p.set_defaults(fn=cmd_cache)

    p = subs.add_parser("completion", help="print a shell completion script")
    p.add_argument("shell", choices=("bash", "zsh", "fish"))
    p.set_defaults(fn=cmd_completion)

    p = subs.add_parser("__complete")
    p.add_argument("words", nargs="*")
    p.set_defaults(fn=cmd__complete)

    p = subs.add_parser("run", help="run your code on input you give it")
    p.add_argument("folder", nargs="?")
    p.add_argument("--lang", choices=tuple(runner.LANGUAGES))
    p.add_argument("--input", metavar="FILE")
    p.set_defaults(fn=cmd_run)

    p = subs.add_parser("diff", help="expected vs got, side by side")
    p.add_argument("case", nargs="?", help="a sample stem like 01")
    p.add_argument("--folder")
    p.add_argument("--lang", choices=tuple(runner.LANGUAGES))
    p.set_defaults(fn=cmd_diff)

    p = subs.add_parser("case", help="add a sample case of your own")
    p.add_argument("--folder")
    p.add_argument("--stdin", metavar="FILE")
    p.add_argument("--expected", metavar="FILE")
    p.set_defaults(fn=cmd_case)

    subs.add_parser("mastery", help="your topic mastery, with decay"
                    ).set_defaults(fn=cmd_mastery)
    subs.add_parser("badges", help="achievements earned and locked"
                    ).set_defaults(fn=cmd_badges)
    subs.add_parser("coins", help="balance and recent ledger"
                    ).set_defaults(fn=cmd_coins)
    subs.add_parser("stats", help="your submission numbers"
                    ).set_defaults(fn=cmd_stats)

    p = subs.add_parser("top", help="the leaderboard")
    p.add_argument("scope", nargs="?", default="week",
                   choices=("week", "season", "all"))
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(fn=cmd_top)

    p = subs.add_parser("inbox", help="your notifications")
    p.add_argument("--unread", action="store_true")
    p.add_argument("--read", action="store_true", help="mark them all read")
    p.set_defaults(fn=cmd_inbox)

    p = subs.add_parser("search", help="search problems and lessons")
    p.add_argument("query")
    p.set_defaults(fn=cmd_search)

    p = subs.add_parser("hint", help="read a hint (costs coins)")
    p.add_argument("slug")
    p.add_argument("number", nargs="?", type=int)
    p.add_argument("--yes", action="store_true", help="skip the price prompt")
    p.set_defaults(fn=cmd_hint)

    p = subs.add_parser("init", help="make this folder a Piko workspace")
    p.add_argument("folder", nargs="?")
    p.add_argument("--lang", default="python", choices=tuple(runner.LANGUAGES))
    p.add_argument("--track")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = subs.add_parser("sync", help="scaffold every problem on your track")
    p.add_argument("--track")
    p.add_argument("--lang", choices=tuple(runner.LANGUAGES))
    p.add_argument("--difficulty", choices=("easy", "medium", "hard"))
    p.set_defaults(fn=cmd_sync)

    subs.add_parser("status", help="what's solved across the workspace"
                    ).set_defaults(fn=cmd_status)


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
        code = args.fn(args)
        if api.STALE:
            print(dim("  (offline - showing a cached copy)"), file=sys.stderr)
        return code
    except Fail as exc:
        print(red("error: ") + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    
def cmd_completion(args):
    from .completion import SHELLS

    script = SHELLS.get(args.shell)
    if script is None:
        raise Fail("No completion for %r. Try: %s"
                   % (args.shell, ", ".join(sorted(SHELLS))))
    print(script)
    return 0


def cmd__complete(args):
    from .completion import candidates

    parser = build_parser()
    commands = set(parser._subparsers._group_actions[0].choices)
    commands.discard("__complete")
    for name in candidates(args.words or [], commands, runner.LANGUAGES):
        print(name)
    return 0

CONFIG_KEYS = ("api","token")

def cmd_config(args):
    if args.action == "path":
        print(config.CONFIG)
        return 0

    data = config._read()
    if args.action == "list":
        output.header("Config  %s" % dim(str(config.CONFIG)))
        output.row("api".ljust(10), config.api_base())
        output.row("token".ljust(10), config.masked())
        expires = data.get("expires_at")
        if expires:
            left = int(expires - time.time())
            output.row("expires".ljust(10),
                       "in %dm" % (left // 60) if left > 0 else amber("expired"))
        output.row("cache".ljust(10), str(config.CACHE))
        return 0
    if args.key not in CONFIG_KEYS:
        raise Fail("Unknown key %r. Try: %s" % (args.key,
                                                ", ".join(CONFIG_KEYS)))
    if args.action == "get":
        print(config.masked() if args.key == "token"
              else data.get(args.key, ""))
        return 0

    if args.key == "api":
        config.set_api(args.value)
    else:
        config.save_token(args.value)
    output.ok("%s set" % args.key)
    return 0


def cmd_cache(args):
    import shutil as _shutil

    if args.clear:
        if config.CACHE.is_dir():
            _shutil.rmtree(config.CACHE, ignore_errors=True)
        output.ok("cache cleared")
        return 0
    files = list(config.CACHE.glob("*.json")) if config.CACHE.is_dir() else []
    size = sum(f.stat().st_size for f in files)
    output.header("Cache")
    output.row("path", str(config.CACHE))
    output.row("entries", str(len(files)))
    output.row("size", "%.1f KB" % (size / 1024.0))
    return 0

def cmd_run(args):
    folder = Path(args.folder or ".")
    meta = _load_meta(folder)
    language = _resolve_language(folder, meta, args.lang)

    if args.input:
        stdin_text = Path(args.input).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
            stdin_text = sys.stdin.read()
    else:
        print(dim("Type the input, then Ctrl-D (Ctrl-Z Enter on Windows):"))
        stdin_text = sys.stdin.read()

    runner.compile_if_needed(folder, language)
    started = time.time()
    ran, got, why = runner.run_case(folder, language, stdin_text)
    elapsed = int((time.time() - started) * 1000)

    print()
    print(got, end="" if got.endswith("\n") else "\n")
    print()
    if ran:
        output.note("exit 0  ·  %d ms" % elapsed)
        return 0
    output.bad(why or "it failed")
    return 1


def cmd_diff(args):
    folder = Path(args.folder or ".")
    meta = _load_meta(folder)
    language = _resolve_language(folder, meta, args.lang)

    cases = _sample_cases(folder)
    if not cases:
        raise Fail("No sample cases in %s/samples." % folder)
    if args.case:
        cases = [c for c in cases if c.stem == args.case
                 or c.stem == "%02d" % int(args.case or 0)]
        if not cases:
            raise Fail("No sample %r here." % args.case)

    runner.compile_if_needed(folder, language)
    bad = 0
    for case in cases:
        expected_file = case.with_suffix(".out")
        expected = (expected_file.read_text(encoding="utf-8")
                    if expected_file.exists() else "")
        ran, got, why = runner.run_case(
            folder, language, case.read_text(encoding="utf-8"))

        if ran and runner.normalise(got) == runner.normalise(expected):
            output.ok(case.stem)
            continue
        bad += 1
        output.bad(case.stem + (("  " + why) if why else ""))
        if ran:
            output.side_by_side(runner.normalise(expected), runner.normalise(got))

        return 1 if bad else 0

def cmd_case(args):
    folder = Path(args.folder or ".")
    box = folder / "samples"
    box.mkdir(parents=True, exist_ok=True)

    taken = {p.item for p in box.glob("*.in")}
    n = 1
    while "%02d" % n in taken:
        n += 1
    stem = "%02d" % n

    if args.stdin and args.expected:
        text_in = Path(args.stdin).read_text(encoding="utf-8")
        text_out = Path(args.expected).read_text(encoding="utf-8")
    else:
        print(dim("Input, then Ctrl-D:"))
        text_in = sys.stdin.read()
        print(dim("Expected output, then Ctrl-D:"))
        text_out = sys.stdin.read()
    (box / (stem + ".in")).write_text(text_in, encoding="utf-8")
    (box / (stem + ".out")).write_text(text_out, encoding="utf-8")
    output.ok("added sample %s" % stem)
    output.note("`piko test` runs it alongside the official ones.")
    return 0

def cmd_mastery(_args):
    data = api.master()
    items = data.get("items") or []
    output.header("Topic Mastery")
    if not items:
        output.note("Nothing tracked yet. Solve something and it fills in.")
        return 0

    for row in items:
        paint = BANDS.get(row["band"], dim)
        flag = red(" fading") if row.get("faded") else ""
        output.row(row["topic"].ljust(18),
                   _bar(row.get("fraction", 0)),
                   paint(row["band"].ljust(9)),
                   dim("%.0f / %.0f" % (row["value"], row["peak"])) + flag)

    output.note("Mastery halves every %.0f days without practice."
                % data.get("half_life_days", 45))
    if data.get("rusty"):
        output.note("going cold: " + ", ".join(data["rusty"]))
    return 0

def cmd_top(args):
    data = api.leaderboard(scopes=args.scope, limit= args.limit)
    output.header(data.get("label") or args.scope)
    for row in data.get("items") or []:
        delta = row.get("delta")
        move = ""
        if delta:
            move = (green(" +%d" % delta) if delta > 0
                    else red(" %d" % delta))
        output.row(dim("%3d." % row["rank"]),
                   bold(row["username"].ljust(18)),
                   ("%d XP" % row["score"]).ljust(12),
                   dim("lvl %d" % row.get("level", 0)) + move)

    you = data.get("you")
    if you and not you.get("hidden"):
        print()
        output.row(dim("you"), bold("#%s" % you.get("rank", "?")),
                   "%d XP" % you.get("score", 0))
    elif you and you.get("hidden"):
        output.note("You're hidden from the leaderboard.")
    return 0


def cmd_inbox(args):
    if args.read:
        body = api.mark_read()
        output.ok("marked %d read" % body.get("marked", 0))
        return 0

    data = api.notifications(unread=args.unread)
    unread = data.get("unread", 0)
    output.header("Inbox  %s" % dim("%d unread" % unread))
    items = data.get("items") or []
    if not items:
        output.note("Nothing here.")
        return 0

    for row in items:
        dot = amber("*") if not row.get("read") else dim(" ")
        output.row(dot, bold(row["title"]))
        if row.get("body"):
            output.note("  " + row["body"])
        if row.get("url"):
            output.note("  " + config.site() + row["url"])
    output.note("`piko inbox --read` marks them all read.")
    return 0

def cmd_badges(_args):
    data = api.achievements()
    earned = data.get("earned") or []
    output.header("Badges  %s" % dim("%d / %d" % (len(earned),
                                                  data.get("total", 0))))
    for row in earned:
        output.row(green("*"), bold(row["title"].ljust(24)),
                   dim(row["description"]))
    locked = data.get("locked") or []
    if locked:
        print()
        print(dim(" still locked"))
        for row in locked:
            output.row(dim(" "), row["title"].ljust(24),
                       dim(row["description"]))
    return 0


def cmd_coins(_args):
    data = api.coins()
    output.header("Coins")
    output.row("balance", bold(str(data.get("balance", 0))))
    costs = data.get("costs") or {}
    output.row("costs", "  ".join("%s %d" % (k.replace("_", " "), v)
                                  for k, v in sorted(costs.items())))
    rows = data.get("recent") or []
    if rows:
        print()
        print(dim(" recent"))
        for row in rows:
            amount = row["amount"]
            paint = green if amount > 0 else red
            output.row(paint("%+d" % amount).ljust(14),
                       row.get("label") or row["reason"])
    return 0

def cmd_stats(_args):
    data = api.stats()
    total = data.get("submissions", 0)
    output.header("Your numbers")
    if not total:
        output.note("No submissions yet.")
        return 0

    accuracy = data.get("accuracy")
    output.row("submissions", str(total))
    output.row("solved", str(data.get("solved", 0)))
    output.row("accuracy", "%.0f%%" % (accuracy * 100) if accuracy else "-")

    print()
    print(dim("  by verdict"))
    for row in data.get("verdicts") or []:
        paint = green if row["verdict"] == "accepted" else red
        output.row(paint(row["label"].ljust(22)),
                   _bar(row["count"] / float(total), 18),
                   dim(str(row["count"])))

    print()
    print(dim(" by language"))
    for row in data.get("languages") or []:
         output.row(row["language"].ljust(10),
                   ("%d sent" % row["submissions"]).ljust(12),
                   dim("%d solved" % row["solved"]))
    difficulty = data.get("difficulty") or {}
    if difficulty:
        print()
        print(dim("  solved by difficulty"))
        for name in ("easy", "medium", "hard"):
            if name in difficulty:
                output.row(output.difficulty(name).ljust(16),
                           str(difficulty[name]))
    return 0

def cmd_search(args):
    data = api.search(args.query)
    total = data.get("total" , 0)
    output.header('Search  "%s"  %s' % (args.query, dim("%d hits" % total)))
    if not total:
        output.note("Nothing matched.")
        return 0
    
    labels = {"problem": "Problems", "lesson": "Lessons",
              "track": "Paths", "person": "People"}
    for kind, rows in (data.get("groups") or {}).items():
        if not rows:
            continue
        print()
        print(dim("  " + labels.get(kind, kind)))
        for row in rows:
            output.row(bold((row.get("slug") or "").ljust(26)),
                       row.get("title") or "")
    return 0

def cmd_hint(args):
    data = api.hints(args.slug)
    items = data.get("items") or []
    if not items:
        output.header(args.slug)
        output.note("No hints for this problem.")
        return 0
    if args.number is None:
        output.header("Hints for %s  %s"
                      % (args.slug, dim("%d coins" % data.get("balance", 0))))
        for i, row in enumerate(items, 1):
            if row.get("revealed"):
                output.row(green("%d." % i), dim("revealed"))
                print()
                print(row.get("body_md") or "")
            else:
                price = "free" if row.get("free") else "%d coins" % data["cost"]
                output.row(dim("%d." % i), dim("locked  (%s)" % price))
        output.note("`piko hint %s 1` reveals the first one." % args.slug)
        return 0

    if not 1 <= args.number <= len(items):
        raise Fail("There are %d hints on %s." % (len(items), args.slug))

    target = items[args.number - 1]
    if not target.get("revealed") and not target.get("free") and not args.yes:
        print("Hint %d costs %s coins. You have %s."
              % (args.number, data["cost"], data.get("balance", 0)))
        if input("  Reveal it? [y/N] ").strip().lower() not in ("y", "yes"):
            return 0

    body = api.reveal_hint(args.slug, target["id"])
    output.header("Hint %d" % args.number)
    print()
    print(body.get("body_md") or "")
    output.note("%d coins left." % body.get("balance", 0))
    return 0

def cmd_init(args):
    from . import workspace

    root = Path(args.folder or ".").resolve()
    existing = workspace.find(root)
    if existing is not None and not args.force:
        raise Fail("Already a workspace: %s" % existing)

    data = {"problems": {}, "language": args.lang, "track": args.track}
    workspace.write(root, data)
    ignore = root / workspace.MARKER / ".gitignore"
    if not ignore.exists():
        ignore.write_text(workspace.GITIGNORE, encoding="utf-8")

    print(green("Workspace ready in ") + bold(str(root)))
    output.note("`piko sync` pulls your track's problems down here.")
    return 0


def cmd_sync(args):
    from . import workspace
    root = workspace.require()
    data = workspace.read(root)
    track_slug = args.track or data.get("track")
    language = args.lang or data.get("language") or "python"

    if track_slug:
        slugs = []
        for unit in api.track(track_slug).get("units") or []:
            slugs += [l["problem"] for l in unit.get("lessons") or []
                      if l.get("problem")]
    else:
        page, slugs = 1, []
        while True:
            body = api.problems(difficulty=args.difficulty, page=page,
                                per_page=100)
            slugs += [r["slug"] for r in body.get("items") or []]
            if page >= body.get("pages", 1) or page > 20:
                break
            page += 1

    seen, ordered = set(), []
    for slug in slugs:
        if slug not in seen:
            seen.add(slug)
            ordered.append(slug)

    output.header("Syncing %d problem%s" % (len(ordered),
                                            "" if len(ordered) == 1 else "s"))

    added = 0
    for slug in ordered:
        folder = root / slug
        if folder.exists():
            output.note("have %s" % slug)
            continue
        cmd_get(argparse.Namespace(slug=slug, lang=language,
                                   into=str(folder)))
        data.setdefault("problems", {})[slug] = {"language": language}
        added += 1

    data["track"], data["language"] = track_slug, language
    workspace.write(root, data)
    print()
    print(green("  %d new, %d already here." % (added, len(ordered) - added)))
    return 0

def cmd_status(_args):
    from . import workspace

    root = workspace.require()
    folders = sorted(p for p in root.iterdir()
                     if p.is_dir() and (p / "piko.json").exists())
    if not folders:
        output.note("Nothing scaffolded yet. Run `piko sync`.")
        return 0

    solved = set()
    try:
        page = 1
        while True:
            body = api.get("/me/submissions", params={"page": page, "per_page": 100, "verdict": "accepted"})
            solved |= {r["problem"] for r in body.get("items") or []
                       if r.get("problem")}
            if page >= body.get("pages", 1) or page > 10:
                break
            page += 1
    except Fail:
        output.note("Couldn't reach Piko - showing local state only.")

    output.header("Workspace  %s" % dim(str(root)))
    for folder in folders:
        meta = _load_meta(folder)
        slug = meta.get("slug") or folder.name
        spec = runner.LANGUAGES.get(meta.get("language") or "python")
        source = folder / spec["source"] if spec else None

        if slug in solved:
            state = green("solved ")
        elif source is not None and source.exists() and (
                source.read_text(encoding="utf-8").strip()
                != (spec["stub"] or "").strip()):
            state = amber("started ")
        else:
            state = dim("untouched")

        output.row(state, bold(slug.ljust(28)),
                   dim(meta.get("title") or ""))
    return 0