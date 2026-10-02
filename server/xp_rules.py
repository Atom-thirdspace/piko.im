# A code lesson pays nothing of its own - the problem behind it is the work,
# and PROBLEM_XP already prices that. Paying both would double-count.
LESSON_XP = {"reading": 5, "quiz": 15, "code": 0}
PROBLEM_XP = {"easy": 30, "medium": 60, "hard": 120}

BONUS_NO_HINTS = 20
BONUS_FIRST_TRY = 10
UNIT_COMPLETE = 100

FALLBACK_LESSON_XP = 5
FALLBACK_PROBLEM_XP = 30

LABELS = {
    "lesson": "Lesson",
    "problem": "Problem",
    "no_hints": "Solved without hints",
    "first_try": "First attempt correct",
    "unit": "Topic complete",
    "streak": "Streak bonus",
    "admin": "Adjustment",
}

BASE_REASON = "problem"


def lesson_base(lesson):
    if lesson.xp_override is not None:
        return max(0, lesson.xp_override)
    return LESSON_XP.get(lesson.kind, FALLBACK_LESSON_XP)


def problem_base(problem):
    if problem.xp_override is not None:
        return max(0, problem.xp_override)
    return PROBLEM_XP.get(problem.difficulty, FALLBACK_PROBLEM_XP)


def solve_award(problem, used_hints, attempt_number):
    """Itemised payout for a first accept.

    attempt_number counts the accepted submission itself, so 1 means they
    got it on the first submit. A submission that failed to compile still
    counts - they pressed submit.
    """
    parts = [(BASE_REASON, problem_base(problem))]
    if not used_hints:
        parts.append(("no_hints", BONUS_NO_HINTS))
    if attempt_number <= 1:
        parts.append(("first_try", BONUS_FIRST_TRY))
    return parts


def total(parts):
    return sum(amount for _, amount in parts)


def summarise(parts):
    names = {BASE_REASON: "base", "no_hints": "no hints", "first_try": "first try"}
    return " + ".join("%d %s" % (amount, names.get(reason, reason))
                      for reason, amount in parts)
