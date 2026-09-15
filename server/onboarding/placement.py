import random
from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class Question:
    id: str
    tier: int
    prompt: str
    choics: Tuple[Tuple[str, str], ...]
    answer: str

    def public(self):
        return {"id":self.id, "prompt":self.prompt,
                "choices": [{"id": c, "text": text} for c, text in self.choices]}

BANK = [
    Question("arr-index", 1, "How long does reading arr[i] take in an array of n items?",
             (("a", "O(1)"), ("b", "O(log n)"), ("c", "O(n)"), ("d", "It depends on i")), "a"),
    Question("lifo", 1, "Which structure hands back the most recently added item first?",
             (("a", "Queue"), ("b", "Stack"), ("c", "Heap"), ("d", "Hash set")), "b"),
    Question("binary-search", 2,
             "Binary search on a sorted array of n items needs about how many comparisons in the worst case?",
             (("a", "n"), ("b", "n / 2"), ("c", "log2 n"), ("d", "sqrt n")), "c"),
    Question("seen-set", 2,
             "You need to check 'have I seen this number before?' millions of times. Best fit?",
             (("a", "Sorted array + linear scan"), ("b", "Linked list"), ("c", "Hash set"), ("d", "Stack")), "c"),
    Question("bfs", 3, "On an unweighted graph, BFS from node s finds...",
             (("a", "A minimum spanning tree"), ("b", "Shortest paths from s by edge count"),
              ("c", "Every cycle"), ("d", "A topological order")), "b"),
    Question("master", 3, "T(n) = 2T(n/2) + O(n) solves to...",
             (("a", "O(n)"), ("b", "O(n log n)"), ("c", "O(n^2)"), ("d", "O(log n)")), "b"),
]
BANK_BY_ID = {q.id: q for q in BANK}

def pick_questions(per_tier=2, rng=random):
    picked = []
    for tier in (1,2,3):
        pool = [q for q in BANK if q.tier == tier]
        picked.extend(rng.sample(pool, min(per_tier), len(pool)))
    return [q.id for q in picked]

def score(question_ids, responses):
    earned = possible = 0
    for qid in question_ids:
        q = BANK_BY_ID.get(qid)
        if q is None:
            continue
        possible += q.tier
        if responses.get(qid) == q.answer:
            earned += q.tier
    return earned,possible

def review(question_ids, responses):
    return [{"id": qid, "chosen": responses.get(qid), "correct": BANK_BY_ID[qid].answer}
            for qid in question_ids if qid in BANK_BY_ID]

def level_from_score(earned, possible):
    ratio = earned / possible if possible else 0
    if ratio >= 0.75:
        return "advanced"
    if ratio >= 0.35:
        return "intermediate"
    return "beginner"


def level_from_experience(experience):
    return {"comfortable": "intermediate", "professional": "intermediate"}.get(experience, "beginner")
