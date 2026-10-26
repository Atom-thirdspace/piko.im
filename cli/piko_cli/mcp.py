import json
import sys
import traceback
from pathlib import Path

from . import api, config, runner
from .output import Fail

PROTOCOL = "2024-11-05"
SERVER = {"name": "piko", "version": "0.1.0"}

def log(message):
    print("[piko-mcp] " + str(message), file=sys.stderr, flush=True)

TOOLS = [
    {
        "name": "list_problems",
        "description": "Browse the Piko problem catalogue. Returns slugs, "
                       "titles, topics and difficulty.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "difficulty": {"type": "string",
                               "enum": ["easy", "medium", "hard"]},
                "query": {"type": "string",
                          "description": "Free text to match in the title"},
                "page": {"type": "integer", "default": 1},
            },
        },
    },
    {
        "name": "get_problem",
        "description": "Read one problem: the full statement, its sample "
                       "cases, limits and how many tests it has.",
        "inputSchema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "scaffold_problem",
        "description": "Write a problem into a local folder: a starter file, "
                       "the statement, the sample cases and piko.json. Use "
                       "this before editing a solution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "language": {"type": "string",
                             "enum": sorted(runner.LANGUAGES)},
                "into": {"type": "string",
                         "description": "Folder to write to. Defaults to the "
                                        "slug in the working directory."},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "run_samples",
        "description": "Run the solution in a scaffolded folder against its "
                       "sample cases, locally. Returns which passed and the "
                       "first mismatch. Does not touch the judge.",
        "inputSchema": {
            "type": "object",
            "properties": {"folder": {"type": "string"}},
        },
    },
    {
        "name": "submit",
        "description": "Send a scaffolded folder's solution to the real "
                       "judge and wait for the verdict. This is scored and "
                       "counts against the user's submission history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string"},
                "force": {"type": "boolean",
                          "description": "Submit even when samples fail.",
                          "default": False},
            },
            },
    },
    {
        "name": "my_progress",
        "description": "The signed-in user's XP, level, streak, solve counts "
                       "and topic mastery.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

def _text(body):
    return {"content": [{"type": "text", "text": body}]}

def _json_text(payload):
    return _text(json.dumps(payload, indent=2, default=str))

def tool_list_problems(args):
    body = api.problems(topic=args.get("topic"),
                        difficulty=args.get("difficulty"),
                        q=args.get("query"),
                        page=int(args.get("page") or 1))
    rows = [{"slug": r["slug"], "title": r["title"],
             "difficulty": r.get("difficulty"), "topic": r.get("topic"),
             "xp": r.get("xp")} for r in body.get("items") or []]
    return _json_text({"total": body.get("total", len(rows)),
                       "page": body.get("page", 1),
                       "pages": body.get("pages", 1),
                       "items": rows})

def tool_get_problem(args):
    data = api.problem(args["slug"])
    return _json_text({
        "slug": data["slug"],
        "title": data["title"],
        "difficulty": data.get("difficulty"),
        "topic": data.get("topic"),
        "xp": data.get("xp"),
        "statement": data.get("statement_md"),
        "time_limit_sec": data.get("time_limit_sec"),
        "memory_mb": data.get("memory_mb"),
        "total_tests": data.get("total_tests"),
        "samples": data.get("samples") or [],
    })


def tool_scaffold(args):
    from .cli import cmd_get
    import argparse as _argparse

    slug = args["slug"]
    language = args.get("language") or "python"
    folder = args.get("into") or slug

    cmd_get(_argparse.Namespace(slug=slug, lang=language, into=folder,edit=False, template=None))
    spec = runner.LANGUAGES[language]
    return _text(
        "Scaffolded %s into %s/\n"
        "  edit %s/%s, then call run_samples with folder=%s"
        % (slug, folder, folder, spec["source"], folder))


def tool_run_samples(args):
    from .cli import _load_meta, _resolve_language, _sample_cases

    folder = Path(args.get("folder") or ".")
    meta = _load_meta(folder)
    language = _resolve_language(folder, meta, None)
    cases = _sample_cases(folder)
    if not cases:
        return _text("No sample cases in %s/samples." % folder)

    runner.compile_if_needed(folder, language, meta)
    verify = runner.checker_for(folder, meta)

    results, failure = [], None
    for case in cases:
        out_file = case.with_suffix(".out")
        expected = (out_file.read_text(encoding="utf-8")
                    if out_file.exists() else "")
        stdin_text = case.read_text(encoding="utf-8")
        ran, got, why = runner.run_case(folder, language, stdin_text)
        good, note = verify(stdin_text, expected, got) if ran else (False, why)

        results.append({"case": case.stem, "pass": bool(good),
                        "note": note or ""})
        if not good and failure is None:
            failure = {"case": case.stem, "stdin": stdin_text,
                       "expected": runner.normalise(expected),
                       "actual": runner.normalise(got), "note": note or ""}

    passed = sum(1 for r in results if r["pass"])
    return _json_text({"passed": passed, "total": len(results),
                       "results": results, "first_failure": failure})

def tool_submit(args):
    from .cli import _await_verdict, _load_meta, _resolve_language, \
        _run_samples, _sample_cases

    folder = Path(args.get("folder") or ".")
    meta = _load_meta(folder)
    slug = meta.get("slug")
    if not slug:
        return _text("No piko.json in %s - scaffold the problem first."
                     % folder)
    language = _resolve_language(folder, meta, None)
    source_file = folder / runner.LANGUAGES[language]["source"]
    if not source_file.exists():
        return _text("No %s in %s." % (source_file.name, folder))
    source = source_file.read_text(encoding="utf-8")

    cases = _sample_cases(folder)
    if cases and not args.get("force"):
        if _run_samples(folder, language, cases, quiet=True,
                        meta=meta) != len(cases):
            return _text("Samples fail, so nothing was submitted. Call "
                         "run_samples to see why, or pass force=true.")

    body = api.submit(slug, language, source)
    if body.get("status") != "done" and not body.get("cached"):
        body = _await_verdict(body["submission_id"])

    return _json_text({
        "verdict": body.get("verdict"),
        "label": body.get("label"),
        "passed": body.get("passed"),
        "total": body.get("total"),
        "max_time_ms": body.get("max_time_ms"),
        "compile_output": body.get("compile_output") or "",
        "first_failure": body.get("first_failure"),
    })

def tool_my_progress(args):
    who = api.whoami()
    streak = api.streak()
    try:
        stats = api.stats()
    except Fail:
        status = {}
    try:
        mastery = api.mastery()
    except Fail:
        mastery = {}

    return _json_text({
        "username": who.get("username"),
        "xp_total": who.get("xp_total"),
        "streak_days": streak.get("streak_days"),
        "today_xp": streak.get("today_xp"),
        "goal_xp": streak.get("goal_xp"),
        "solved": stats.get("solved"),
        "submissions": stats.get("submissions"),
        "accuracy": stats.get("accuracy"),
        "going_cold": mastery.get("rusty") or [],
    })


HANDLERS = {
    "list_problems": tool_list_problems,
    "get_problem": tool_get_problem,
    "scaffold_problem": tool_scaffold,
    "run_samples": tool_run_samples,
    "submit": tool_submit,
    "my_progress": tool_my_progress,
}

def handle(message):
    method = message.get("method")
    mid = message.get("id")

    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        return {
            "protocolVersion": asked or PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER,
        }

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return {}

    if method == "tools/list":
        return {"tools": TOOLS}

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            raise LookupError("no tool named %r" % name)
        try:
            return handler(params.get("arguments") or {})
        except Fail as exc:
            # A Piko-level problem is a tool result the model can act on,
            # not a protocol error.
            return dict(_text("Piko said: %s" % exc), isError=True)

    raise LookupError("unknown method %r" % method)

def serve():
    log("ready, talking to %s" % config.api_base())

    for line in sys.stdin:
        line= line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue

        mid = message.get("id")
        try:
            result = handle(message)
        except LookupError as exc:
            reply = {"jsonrpc": "2.0", "id": mid,
                     "error": {"code": -32601, "message": str(exc)}}
        except Exception as exc:
            log(traceback.format_exc())
            reply = {"jsonrpc": "2.0", "id": mid,
                     "error": {"code": -32603, "message": str(exc)}}
        else:
            if result is None:
                continue                 # a notification: say nothing
            reply = {"jsonrpc": "2.0", "id": mid, "result": result}

        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0
    