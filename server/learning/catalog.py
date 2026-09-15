from dataclasses import dataclass, field
from typing import List, Optional

LEVELS = ("beginner", "intermediate", "advanced")


def level_rank(level):
    return LEVELS.index(level)


TOPICS = [
    ("arrays", "Arrays & Strings"),
    ("hashing", "Hash Maps & Sets"),
    ("linked-lists", "Linked Lists"),
    ("trees", "Trees"),
    ("graphs", "Graphs"),
    ("dp", "Dynamic Programming"),
    ("greedy", "Greedy"),
]
TOPIC_KEYS = {key for key, _ in TOPICS}


@dataclass(frozen=True)
class LessonDef:
    slug: str
    title: str
    kind: str                         
    xp: int
    problem_slug: Optional[str] = None


@dataclass(frozen=True)
class UnitDef:
    slug: str
    title: str
    level: str
    topic: Optional[str]
    lessons: List[LessonDef] = field(default_factory=list)


@dataclass(frozen=True)
class TrackDef:
    slug: str
    title: str
    description: str
    units: List[UnitDef] = field(default_factory=list)


TRACKS = [
    TrackDef(
        slug="foundations",
        title="DSA Foundations",
        description="Big-O, arrays, hashing and recursion - the toolkit every later topic assumes.",
        units=[
            UnitDef("big-o", "Big-O Without the Math Anxiety", "beginner", None, [
                LessonDef("why-speed-matters", "Why speed matters", "reading", 10),
                LessonDef("count-the-steps", "Count the steps", "quiz", 15),
            ]),
            UnitDef("arrays-basics", "Arrays & Strings", "beginner", "arrays", [
                LessonDef("what-is-an-array", "What an array really is", "reading", 10),
                LessonDef("sum-of-array", "Sum of an array", "code", 25, "sum-of-array"),
            ]),
            UnitDef("hashing-basics", "Hash Maps & Sets", "beginner", "hashing", [
                LessonDef("seen-before", "Have I seen this before?", "reading", 10),
                LessonDef("two-sum", "Two Sum", "code", 30, "two-sum"),
            ]),
            UnitDef("recursion", "Recursion", "intermediate", None, [
                LessonDef("functions-calling-themselves", "Functions that call themselves", "reading", 10),
                LessonDef("factorial", "Factorial", "code", 25, "factorial"),
            ]),
        ],
    ),
    TrackDef(
        slug="interview-core",
        title="Interview Core",
        description="The patterns interviews lean on most, in the order they build on each other.",
        units=[
            UnitDef("two-pointers", "Two Pointers", "intermediate", "arrays", [
                LessonDef("two-pointers-intro", "Two pointers, one pass", "reading", 10),
            ]),
            UnitDef("hash-patterns", "Hashing Patterns", "intermediate", "hashing", [
                LessonDef("frequency-maps", "Frequency maps", "reading", 10),
            ]),
            UnitDef("linked-lists", "Linked Lists", "intermediate", "linked-lists", [
                LessonDef("pointers-not-indexes", "Pointers, not indexes", "reading", 10),
            ]),
            UnitDef("trees", "Trees & BFS/DFS", "intermediate", "trees", [
                LessonDef("tree-traversals", "Tree traversals", "reading", 10),
            ]),
            UnitDef("graphs", "Graphs", "advanced", "graphs", [
                LessonDef("graphs-are-everywhere", "Graphs are everywhere", "reading", 10),
            ]),
            UnitDef("dp-intro", "Dynamic Programming", "advanced", "dp", [
                LessonDef("remember-dont-recompute", "Remember, don't recompute", "reading", 10),
            ]),
        ],
    ),
    TrackDef(
        slug="competitive",
        title="Competitive Programming",
        description="Contest techniques: prefix sums, greedy proofs, graph algorithms, DP tricks.",
        units=[
            UnitDef("prefix-sums", "Prefix Sums", "advanced", "arrays", [
                LessonDef("range-queries", "Range queries in O(1)", "reading", 10),
            ]),
            UnitDef("greedy", "Greedy", "advanced", "greedy", [
                LessonDef("exchange-argument", "The exchange argument", "reading", 10),
            ]),
            UnitDef("graph-algorithms", "Graph Algorithms", "advanced", "graphs", [
                LessonDef("dijkstra", "Dijkstra", "reading", 10),
            ]),
            UnitDef("dp-optimizations", "DP Optimizations", "advanced", "dp", [
                LessonDef("state-compression", "State compression", "reading", 10),
            ]),
        ],
    ),
]
TRACKS_BY_SLUG = {track.slug: track for track in TRACKS}
