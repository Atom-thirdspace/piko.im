"""Give the three orphan code lessons a problem to point at.

Without this the Foundations map stops at area 2: a code lesson with no
problem can never be completed, so nothing past it ever unlocks.

Idempotent - re-running updates the rows in place.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app
from server.models import (PUBLISHED, Lesson, Problem, ProblemHint,
                           ProblemTest, _utcnow, db)

SEEDS = [
    {
        "lesson": "sum-of-array",
        "slug": "sum-of-an-array",
        "title": "Sum of an array",
        "topic": "arrays",
        "difficulty": "easy",
        "statement": """
Read a list of integers and print their sum.

## Input
```
line 1: n, the count (0 <= n <= 1000)
line 2: n integers, space separated (absent when n is 0)
```

## Output
One integer: the total. The sum of no numbers is `0`.
""",
        "reference": """
import sys
data = sys.stdin.read().split()
n = int(data[0]) if data else 0
print(sum(int(x) for x in data[1:1 + n]))
""",
        "tests": [
            ("5\n1 2 3 4 5\n", "15\n", True),
            ("3\n-1 -2 -3\n", "-6\n", True),
            ("0\n", "0\n", False),
            ("1\n0\n", "0\n", False),
            ("4\n1000000 1000000 1000000 1000000\n", "4000000\n", False),
            ("6\n-5 5 -5 5 -5 5\n", "0\n", False),
        ],
        "hints": [
            ("The count on line 1 tells you how many to read - but reading "
             "every token after it works just as well.", 3),
            ("n can be 0, and then line 2 is not there at all. Make sure "
             "that prints 0 rather than crashing.", 4),
        ],
    },
    {
        "lesson": "two-sum",
        "slug": "two-sum-indices",
        "title": "Two numbers that add up",
        "topic": "hashing",
        "difficulty": "easy",
        "statement": """
Find the two numbers that add up to the target and print their positions.

## Input
```
line 1: n and target
line 2: n integers, space separated
```

## Output
Two 0-based indices, ascending, space separated. Exactly one pair works.

## Why not two loops
Checking every pair is O(n^2). Remembering what you have already seen in a
dictionary gets you the answer in one pass.
""",
        "reference": """
import sys
data = sys.stdin.read().split()
n, target = int(data[0]), int(data[1])
arr = [int(x) for x in data[2:2 + n]]
seen = {}
for i, x in enumerate(arr):
    if target - x in seen:
        print(seen[target - x], i)
        break
    seen[x] = i
""",
        "tests": [
            ("4 9\n2 7 11 15\n", "0 1\n", True),
            ("3 6\n3 2 4\n", "1 2\n", True),
            ("2 6\n3 3\n", "0 1\n", False),
            ("5 -8\n-3 4 -5 1 7\n", "0 2\n", False),
            ("5 0\n-1 -2 3 1 8\n", "0 3\n", False),
            ("6 100\n1 2 3 97 50 4\n", "2 3\n", False),
        ],
        "hints": [
            ("As you walk the array, ask what number would complete the "
             "pair: target - x. Have you seen it already?", 3),
            ("Store value -> index as you go, and check before you insert. "
             "That handles the two-equal-numbers case for free.", 4),
        ],
    },
    {
        "lesson": "factorial",
        "slug": "factorial-recursive",
        "title": "Factorial",
        "topic": "recursion",
        "difficulty": "easy",
        "statement": """
Print `n!` - the product of every integer from 1 to n.

## Input
One integer `n` (0 <= n <= 20).

## Output
One integer. `0!` is `1`, by definition and not by accident: it is the
empty product, the same reason an empty sum is 0.
""",
        "reference": """
import sys
n = int(sys.stdin.read().strip())
result = 1
for i in range(2, n + 1):
    result *= i
print(result)
""",
        "tests": [
            ("5\n", "120\n", True),
            ("0\n", "1\n", True),
            ("1\n", "1\n", False),
            ("10\n", "3628800\n", False),
            ("20\n", "2432902008176640000\n", False),
            ("13\n", "6227020800\n", False),
        ],
        "hints": [
            ("The base case is n <= 1, and it returns 1 - not 0. Returning "
             "0 makes every answer 0.", 3),
            ("20! is about 2.4 x 10^18. That fits in a 64-bit integer, but "
             "only just - in C++ use unsigned long long or long long.", 4),
        ],
    },
]


def upsert(seed):
    problem = db.session.execute(
        db.select(Problem).filter_by(slug=seed["slug"])).scalar_one_or_none()
    fresh = problem is None
    if fresh:
        problem = Problem(slug=seed["slug"], status=PUBLISHED,
                          published_at=_utcnow())
        db.session.add(problem)

    problem.title = seed["title"]
    problem.statement_md = seed["statement"].strip()
    problem.difficulty = seed["difficulty"]
    problem.topic = seed["topic"]
    problem.time_limit_sec = 2.0
    problem.memory_mb = 256
    problem.reference_source = seed["reference"].lstrip()
    problem.reference_language = "python"
    db.session.flush()

    problem.tests.clear()
    for i, (stdin, expected, is_sample) in enumerate(seed["tests"]):
        problem.tests.append(ProblemTest(position=i, stdin=stdin,
                                         expected_stdout=expected,
                                         is_sample=is_sample))
    problem.hints.clear()
    for i, (body, cost) in enumerate(seed["hints"]):
        problem.hints.append(ProblemHint(position=i, body_md=body,
                                         cost_xp=cost))
    return problem, fresh


def main():
    with app.app_context():
        for seed in SEEDS:
            problem, fresh = upsert(seed)
            db.session.flush()

            lesson = db.session.execute(
                db.select(Lesson).filter_by(slug=seed["lesson"], kind="code")
            ).scalar_one_or_none()

            if lesson is None:
                print("%-22s %s - no code lesson %r to link"
                      % (problem.slug, "created" if fresh else "updated",
                         seed["lesson"]))
                continue

            lesson.problem_id = problem.id
            print("%-22s %s -> lesson %-14s %d tests, %d hints"
                  % (problem.slug, "created" if fresh else "updated",
                     lesson.slug, len(problem.tests), len(problem.hints)))

        db.session.commit()

        orphans = db.session.execute(
            db.select(db.func.count()).select_from(Lesson)
            .where(Lesson.kind == "code", Lesson.problem_id.is_(None))
        ).scalar() or 0
        print("done - %d code lesson%s still without a problem"
              % (orphans, "" if orphans == 1 else "s"))


if __name__ == "__main__":
    main()
