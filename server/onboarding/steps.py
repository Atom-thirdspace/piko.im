from dataclasses import dataclass
from typing import Callable, List, Tuple

from ..judge.languages import LANGUAGES
from ..learning.catalog import TOPICS

class AnswerError(ValueError):
    pass

@dataclass(frozen=True)
class Step:
    key:str
    kind: str
    prompt: str
    options: Tuple[Tuple[str, str], ...] = ()
    min_choices: int = 1
    max_choices: int = 1
    applies: Callable[[dict], bool] = lambda answers: True

    def public(self, answers=None):
        return{
            "key": self.key,
            "kind": self.kind,
            "prompt": self.prompt,
            "options": [{"id": key, "label": label} for key, label in self.options],
            "min_choices": self.min_choices,
            "max_choices": self.max_choices,
            "chosen": (answers or {}).get(self.key),
        }


STEPS: List[Step] = [
    Step("goal", "choice", "What brings you to Piko?", (
        ("interview", "Prepare for coding interviews"),
        ("cp", "Get better at competitive programming"),
        ("fundamentals", "Learn data structures and algorithms properly"),
        ("practice", "Keep my skills warm"),
    )),
    Step("experience", "choice", "How much have you coded before?", (
        ("none", "I'm just starting out"),
        ("some", "I can write loops and functions"),
        ("comfortable", "I've solved algorithm problems before"),
        ("professional", "I write code professionally"),
    )),
    Step("language", "choice", "Which language do you want to solve in?",
         tuple((key, lang.label) for key, lang in LANGUAGES.items())),
    Step("topics", "multi", "Anything you especially want to cover?",
         tuple(TOPICS), min_choices=0, max_choices=3),
    Step("weekly_minutes", "choice", "How much time can you give it each week?", (
        ("60", "About an hour"),
        ("90", "An hour and a half"),
        ("180", "Three hours"),
        ("300", "Five hours or more"),
    )),
    # Only worth asking someone who has actually written code before.
    Step("placement_opt_in", "choice", "Want a short quiz so we start you at the right level?", (
        ("yes", "Yes, place me"),
        ("no", "No, start me from the beginning"),
    ), applies=lambda answers: answers.get("experience") not in (None, "none")),
]

STEPS_BY_KEY = {step.key: step for step in STEPS}

def steps_for(answers):
    return [step for step in STEPS if step.applies(answers)]

def next_step(answers):
    for step in steps_for(answers):
        if step.key not in answers:
            return step
    return None

def is_complete(answers):
    return next_step(answers) is None

def validate(step, raw):
    valid = { key for key, _ in step.options}

    if step.kind == "multi":
        if raw is None:
            raw = []
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raise AnswerError("Expected a list of choices.")
        chosen, seen = [], set()
        for item in raw:
            if item not in valid:
                raise AnswerError("'%s' is not an option here." % item)
            if item not in seen:
                seen.add(item)
                chosen.append(item)
        if len(chosen) < step.min_choices:
            raise AnswerError("Pick at least %d." % step.min_choices)
        if len(chosen) > step.max_choices:
            raise AnswerError("Pick at most %d." % step.max_choices)
        return chosen

    if raw not in valid:
        raise AnswerError("Pick one of the options.")
    return raw
