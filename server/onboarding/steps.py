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