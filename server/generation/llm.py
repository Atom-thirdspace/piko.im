import json
import re
from .base import Draft
from ..tutor.client import TutorError, ask


SYSTEM = """You write programming exercises for people learning data \
structures and algorithms. You reply with one JSON object and nothing else.

Schema:
{
  "title": "short title",
  "statement": "markdown; must state the exact stdin format and stdout format",
  "inputs": ["full stdin text for case 1", "..."],
  "reference_python": "a complete Python 3 program reading stdin, printing stdout",
  "hints": [{"body": "a nudge, not the answer", "cost_xp": 3}]
}

Rules:
- Between 8 and 14 inputs. Include the edge cases: empty, single item, \
duplicates, the largest allowed value.
- Do NOT include expected outputs. They are computed by running your \
reference program.
- The reference program must be deterministic: no randomness, no reliance \
on set or dict ordering.
- The statement must be solvable from the statement alone.
- Line-oriented IO. An array is one line of space-separated integers.
"""

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

class DraftError(Exception):
    pass

def _parse(text):
    try:
        return json.loads(FENCE.sub("", text).strip())
    except ValueError as exc:
        raise DraftError("model did not return JSON: %s" % exc)

def draft_problem(topic, difficulty, skill, seed=0, xp=20):
    """Ask for one draft. Raises DraftError; never returns something unchecked.

    Note what this does NOT take from the model: expected outputs. Those
    come from running the reference in the sandbox, so a model that is
    confidently wrong about the algorithm produces a draft that fails
    verification rather than a broken problem.
    """
    prompt = ("Topic: %s\nDifficulty: %s\nThe exercise should make the "
              "learner practise: %s\n" % (topic, difficulty, skill))
    try:
        text, _model = ask(SYSTEM, prompt, max_tokens=2000)
    except TutorError as exc:
        raise DraftError(str(exc))

    data = _parse(text)
    if not isinstance(data, dict):
        raise DraftError("model returned %s, not an object"
                         % type(data).__name__)
    for key in ("title", "statement", "inputs", "reference_python"):
        if not data.get(key):
            raise DraftError("missing %r in the model's reply" % key)

    inputs = data["inputs"]
    if not isinstance(inputs, list) or not all(isinstance(s, str)
                                               for s in inputs):
        raise DraftError("inputs must be a list of strings")
    if not 1 <= len(inputs) <= 30:
        raise DraftError("expected between 1 and 30 inputs, got %d"
                         % len(inputs))

    hints = []
    for h in (data.get("hints") or [])[:3]:
        if isinstance(h, dict) and h.get("body"):
            try:
                cost = int(h.get("cost_xp", 3))
            except (TypeError, ValueError):
                cost = 3
            hints.append((str(h["body"])[:500], max(cost, 0)))

    # Hint costs no longer subtract from the payout - opening any hint simply
    # gives up the flat no-hints bonus - so there is nothing left to trim.

    slug = re.sub(r"[^a-z0-9]+", "-",
                  str(data["title"]).lower()).strip("-")[:60] or "generated"

    return Draft(
        slug="gen-%s-%04x" % (slug, seed & 0xFFFF),
        title=str(data["title"])[:200],
        topic=topic, difficulty=difficulty, xp=xp,
        statement=str(data["statement"]),
        inputs=tuple(s if s.endswith("\n") else s + "\n" for s in inputs),
        reference_source=str(data["reference_python"]),
        reference_language="python",
        hints=tuple(hints),
    )
