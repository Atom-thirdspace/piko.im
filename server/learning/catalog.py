from dataclasses import dataclass, field
from typing import List, Optional, Tuple

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
class QuizQuestion:
    """Same shape as the placement bank, minus the tier - lesson quizzes are
    not scored for level, they only gate completion."""
    id: str
    prompt: str
    choices: Tuple[Tuple[str, str], ...]
    answer: str

    def public(self):
        return {"id": self.id, "prompt": self.prompt,
                "choices": [{"id": c, "text": text} for c, text in self.choices]}


@dataclass(frozen=True)
class LessonDef:
    slug: str
    title: str
    kind: str
    xp: int
    problem_slug: Optional[str] = None
    body: str = ""
    quiz: Tuple[QuizQuestion, ...] = ()


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
                LessonDef("why-speed-matters", "Why speed matters", "reading", 10, body="""
## The question Big-O actually answers

Big-O is not about seconds. A fast laptop and a slow phone disagree about
seconds. Big-O asks something machines agree on:

> When the input gets 10x bigger, how much more work does this do?

## Three shapes worth recognising

- **O(1)** - the work does not change with `n`. Reading `arr[i]`.
- **O(n)** - 10x the input, 10x the work. Scanning a list once.
- **O(n^2)** - 10x the input, 100x the work. A loop inside a loop.

## Why the difference bites

At `n = 1,000,000`, an O(n) pass does a million steps - a blink. An O(n^2)
pass does a trillion. Same laptop, same language. That gap is why the shape
matters more than the micro-optimisation.

## Reading a loop

```
total = 0
for x in arr:      # runs n times
    total += x     # O(1) each
```

One loop over `n` items, constant work inside: **O(n)**.

```
for a in arr:          # n times
    for b in arr:      # n times, for each a
        check(a, b)    # O(1)
```

`n` times `n`: **O(n^2)**.

## The rule for dropping terms

Big-O keeps the fastest-growing term and drops constants. `O(3n + 50)` is
`O(n)`; at large `n` the `3` and the `50` stop mattering. That is the whole
trick - it tells you which algorithm wins eventually, not which wins on ten
items.
"""),
                LessonDef("count-the-steps", "Count the steps", "quiz", 15, body="""
Four loops, four shapes. Read the loop bounds, not the body - the body here
is always O(1).
""", quiz=(
                    QuizQuestion(
                        "single-loop",
                        "for x in arr: total += x  -  over n items, what is this?",
                        (("a", "O(1)"), ("b", "O(n)"), ("c", "O(n^2)"), ("d", "O(log n)")),
                        "b"),
                    QuizQuestion(
                        "nested-loop",
                        "A loop over n items, with another loop over n items inside it?",
                        (("a", "O(n)"), ("b", "O(2n)"), ("c", "O(n^2)"), ("d", "O(n log n)")),
                        "c"),
                    QuizQuestion(
                        "halving",
                        "Each step throws away half the remaining items. How many steps to finish?",
                        (("a", "About n"), ("b", "About n / 2"), ("c", "About log2 n"),
                         ("d", "About sqrt n")),
                        "c"),
                    QuizQuestion(
                        "drop-constants",
                        "An algorithm does 3n + 50 steps. In Big-O that is...",
                        (("a", "O(3n + 50)"), ("b", "O(n)"), ("c", "O(50n)"), ("d", "O(1)")),
                        "b"),
                )),
            ]),
            UnitDef("arrays-basics", "Arrays & Strings", "beginner", "arrays", [
                LessonDef("what-is-an-array", "What an array really is", "reading", 10, body="""
## One block, evenly spaced

An array is a single run of memory split into equal-sized slots. That one
fact explains every array trade-off you will meet.

Because the slots are equal and adjacent, the machine finds item `i` with
arithmetic, not searching:

```
address = start + i * slot_size
```

One multiply, one add. That is why `arr[i]` is **O(1)** no matter how big
the array is or how large `i` is.

## What the same fact costs you

Inserting at the front means every later item has to shift up one slot to
keep the run contiguous - **O(n)**. Deleting from the front is the same
story in reverse. Appending at the end is usually O(1), because there is
often spare room already.

| Operation | Cost |
|---|---|
| Read `arr[i]` | O(1) |
| Append at the end | O(1) amortised |
| Insert/remove at front | O(n) |
| Search unsorted | O(n) |

## Strings are arrays with opinions

A string is an array of characters. In Python and Java they are also
*immutable* - "changing" one builds a whole new array. So this is a trap:

```
out = ""
for ch in text:
    out += ch      # builds a new string every pass: O(n^2) overall
```

Collect into a list and join once instead - O(n):

```
out = "".join(ch for ch in text)
```
"""),
                LessonDef("sum-of-array", "Sum of an array", "code", 25, "sum-of-array", body="""
Read the numbers, add them, print the total. One pass, O(n).

Read `n` on the first line, then `n` integers on the second.
"""),
            ]),
            UnitDef("hashing-basics", "Hash Maps & Sets", "beginner", "hashing", [
                LessonDef("seen-before", "Have I seen this before?", "reading", 10, body="""
## The question that defines the structure

"Have I seen this value before?" Ask it once and a scan is fine. Ask it
once per item, and the scan turns your O(n) loop into O(n^2).

A **hash set** answers it in O(1) average. It runs the value through a hash
function to get a slot number, then looks straight at that slot - no
scanning.

## Set or map?

- **Set** - membership only. *Have I seen `x`?*
- **Map / dict** - membership plus a payload. *Where did I see `x`?*

## The trade you are making

Speed for memory, and order for speed. A hash set stores the values and
some spare slots, and it does not keep them in order. If you need sorted
output, sort at the end or reach for a tree structure.

The O(1) is *average*, not worst case: adversarial keys can collide into
one slot and degrade to O(n). Fine in interviews, occasionally real in
contests.

## The pattern to memorise

```
seen = set()
for x in arr:
    if x in seen:       # O(1) average
        return True     # duplicate found
    seen.add(x)
return False
```

One pass, O(n) time, O(n) space. Trading memory for time is the entire
move, and the next lesson is the most famous example of it.
"""),
                LessonDef("two-sum", "Two Sum", "code", 30, "two-sum", body="""
Given `n` integers and a target, print the **1-based indices** of the two
numbers that add to it.

The O(n^2) answer is every pair. The O(n) answer: for each `x`, you are
looking for `target - x`. Keep a map of value to index as you scan, and
check for the complement *before* you insert.
"""),
            ]),
            UnitDef("recursion", "Recursion", "intermediate", None, [
                LessonDef("functions-calling-themselves", "Functions that call themselves",
                          "reading", 10, body="""
## Two parts, always

Every correct recursive function has exactly two:

1. A **base case** that returns without recursing.
2. A **recursive case** that calls itself on a *strictly smaller* input.

Miss the base case and you recurse forever. Fail to shrink the input and
you also recurse forever - just less obviously.

```
def factorial(n):
    if n <= 1:                    # base case
        return 1
    return n * factorial(n - 1)   # smaller every call
```

## What the machine is doing

Each call gets its own stack frame holding its own `n`. `factorial(4)`
stacks four frames, hits the base case, then multiplies back up as the
frames return: `1 -> 1 -> 2 -> 6 -> 24`.

That stack is finite. Python stops near 1000 frames - deep recursion on a
linked list of 100,000 nodes will overflow where a loop would not.

## Trusting the recursion

The hardest habit is refusing to trace every level in your head. Assume the
recursive call is already correct, and ask only: given the right answer for
`n - 1`, do I build the right answer for `n`?

That is the whole proof, and it is the same shape as induction.
"""),
                LessonDef("factorial", "Factorial", "code", 25, "factorial", body="""
Read `n`, print `n!`.

Base case at `n <= 1`. Recursion or a loop both work here - the loop never
overflows the stack, which is the point worth noticing.
"""),
            ]),
        ],
    ),
    TrackDef(
        slug="interview-core",
        title="Interview Core",
        description="The patterns interviews lean on most, in the order they build on each other.",
        units=[
            UnitDef("two-pointers", "Two Pointers", "intermediate", "arrays", [
                LessonDef("two-pointers-intro", "Two pointers, one pass", "reading", 10, body="""
## Replacing a nested loop with two indices

Two pointers turns many O(n^2) scans into O(n). Two indices walk the array
and each one only ever moves forward, so together they take at most 2n
steps.

## The converging form

On a **sorted** array, looking for a pair summing to `target`:

```
lo, hi = 0, len(arr) - 1
while lo < hi:
    total = arr[lo] + arr[hi]
    if total == target:
        return lo, hi
    if total < target:
        lo += 1      # need more: only the left can grow it
    else:
        hi -= 1      # need less: only the right can shrink it
```

Sortedness is what makes each move safe: if the sum is too small, no
smaller right-hand value can help, so that column is gone for good.

## The same-direction form

A slow pointer writes, a fast pointer reads - the standard in-place filter:

```
w = 0
for r in range(len(arr)):
    if keep(arr[r]):
        arr[w] = arr[r]
        w += 1
return w        # the first w items are the kept ones
```

## When to reach for it

Sorted input, a pair or triple to find, a subarray to grow and shrink, or
an in-place rewrite. If the array is unsorted and you only need membership,
a hash set is usually the better tool.
"""),
            ]),
            UnitDef("hash-patterns", "Hashing Patterns", "intermediate", "hashing", [
                LessonDef("frequency-maps", "Frequency maps", "reading", 10, body="""
## Counting is a one-liner, and it solves a lot

```
from collections import Counter
freq = Counter(arr)      # value -> how many times
```

## Anagrams

Two strings are anagrams exactly when their frequency maps match - O(n)
instead of O(n log n) for sort-and-compare:

```
Counter(a) == Counter(b)
```

## Grouping by a signature

Build a key that is equal for everything that belongs together, then use it
as a dict key. For anagram groups, the sorted letters work:

```
groups = {}
for word in words:
    groups.setdefault("".join(sorted(word)), []).append(word)
```

## Prefix-sum counting

The one that unlocks "how many subarrays sum to k". Keep a map of each
prefix sum you have seen and how often:

```
count = {0: 1}
total = answer = 0
for x in arr:
    total += x
    answer += count.get(total - k, 0)
    count[total] = count.get(total, 0) + 1
```

O(n), and it handles negative numbers - which is where the sliding-window
version breaks.
"""),
            ]),
            UnitDef("linked-lists", "Linked Lists", "intermediate", "linked-lists", [
                LessonDef("pointers-not-indexes", "Pointers, not indexes", "reading", 10, body="""
## No arithmetic, no random access

Nodes sit anywhere in memory; each one holds a value and a reference to the
next. There is no `start + i * size` trick, so reaching item `i` means
walking `i` links - **O(n)**.

What you buy: inserting or deleting *given the node* costs **O(1)**, with
no shifting. Arrays are the opposite trade.

## The two techniques that cover most problems

**Dummy head** - removes the "what if it is the first node" special case:

```
dummy = Node(0, head)
prev = dummy
while prev.next:
    if prev.next.val == target:
        prev.next = prev.next.next   # works even at the front
    else:
        prev = prev.next
return dummy.next
```

**Fast and slow pointers** - one moves two steps per one of the other. When
fast reaches the end, slow is at the middle. If the list has a cycle, they
eventually land on the same node - that is Floyd's algorithm, and it uses
O(1) memory where a hash set would use O(n).

## Reversing, the interview staple

```
prev, cur = None, head
while cur:
    cur.next, prev, cur = prev, cur, cur.next
return prev
```

Three pointers, one pass. Draw it once on paper - it stops being magic.
"""),
            ]),
            UnitDef("trees", "Trees & BFS/DFS", "intermediate", "trees", [
                LessonDef("tree-traversals", "Tree traversals", "reading", 10, body="""
## Depth first: three orders, one recursion

The only difference is *when* you touch the node relative to its children.

```
def walk(node):
    if node is None:
        return
    # pre-order: visit here - roots before children, good for copying
    walk(node.left)
    # in-order: visit here - sorted order in a BST
    walk(node.right)
    # post-order: visit here - children before parents, good for deleting
```

**In-order on a binary search tree yields sorted values.** That single fact
answers a surprising number of BST questions.

## Breadth first: a queue, level by level

```
from collections import deque
q = deque([root])
while q:
    for _ in range(len(q)):     # this snapshot is one full level
        node = q.popleft()
        for child in (node.left, node.right):
            if child:
                q.append(child)
```

Taking `len(q)` before the inner loop is what separates the levels - keep
it if the question mentions levels, depth, or "shortest".

## Choosing

Paths, subtree sums, or anything naturally recursive: DFS. Level order,
minimum depth, or shortest hops: BFS. Both are O(n) in time; DFS costs
O(height) in stack, BFS costs O(width) in queue.
"""),
            ]),
            UnitDef("graphs", "Graphs", "advanced", "graphs", [
                LessonDef("graphs-are-everywhere", "Graphs are everywhere", "reading", 10, body="""
## A tree is a graph that promised to behave

Nodes and edges, but now with cycles allowed and no root. Which means one
new obligation: **track what you have visited, or you will loop forever.**

## Representation

Adjacency list, nearly always:

```
from collections import defaultdict
g = defaultdict(list)
for u, v in edges:
    g[u].append(v)
    g[v].append(u)      # drop this line if the graph is directed
```

O(V + E) space. The matrix form costs O(V^2) and only pays off on dense
graphs.

## The traversal, with the guard that matters

```
seen = {start}
q = deque([start])
while q:
    node = q.popleft()
    for nxt in g[node]:
        if nxt not in seen:
            seen.add(nxt)      # mark on ENQUEUE, not on dequeue
            q.append(nxt)
```

Marking on dequeue lets a node get queued several times before it is ever
processed. Same answer, much worse constant.

## What BFS gives you free

On an **unweighted** graph, BFS from `s` finds the fewest-edges path to
every reachable node. Add weights and that breaks - you need Dijkstra,
which is the same walk with a priority queue instead of a plain one.

Grids are graphs too: each cell is a node, neighbours are the four
directions. Most "shortest path in a maze" problems are BFS in disguise.
"""),
            ]),
            UnitDef("dp-intro", "Dynamic Programming", "advanced", "dp", [
                LessonDef("remember-dont-recompute", "Remember, don't recompute",
                          "reading", 10, body="""
## Where the waste comes from

Naive `fib(n)` recomputes `fib(n-2)` twice, `fib(n-3)` three times, and so
on - O(2^n). But there are only `n` distinct questions being asked. Answer
each once and the whole thing collapses to O(n).

## Memoisation: same recursion, plus a cache

```
from functools import cache

@cache
def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)
```

Top-down, minimal edit, and it only computes states you actually reach.

## Tabulation: fill a table bottom-up

```
dp = [0] * (n + 1)
dp[1] = 1
for i in range(2, n + 1):
    dp[i] = dp[i - 1] + dp[i - 2]
```

No recursion limit, and you can often drop the array for two variables -
O(1) space.

## The part that is actually hard

Not the caching. It is naming the state: *what does `dp[i]` mean?* Write
that sentence down before writing code.

> `dp[i]` = the best total using the first `i` items.

Then the transition usually follows: for each item, take it or skip it,
keep the better. A problem is DP-shaped when it asks for a max, min, or
count over choices, and the same subproblem keeps reappearing.
"""),
            ]),
        ],
    ),
    TrackDef(
        slug="competitive",
        title="Competitive Programming",
        description="Contest techniques: prefix sums, greedy proofs, graph algorithms, DP tricks.",
        units=[
            UnitDef("prefix-sums", "Prefix Sums", "advanced", "arrays", [
                LessonDef("range-queries", "Range queries in O(1)", "reading", 10, body="""
## Pay once, answer forever

Summing `arr[l..r]` costs O(n) per query. With `q` queries that is O(nq) -
too slow at contest sizes. Precompute once instead:

```
pre = [0] * (n + 1)
for i, x in enumerate(arr):
    pre[i + 1] = pre[i] + x       # pre[i] = sum of the first i items
```

Then every range sum is one subtraction:

```
def range_sum(l, r):      # inclusive, 0-based
    return pre[r + 1] - pre[l]
```

O(n) to build, **O(1) per query**. The off-by-one trap is why `pre` has
`n + 1` entries and starts at 0 - that leading zero removes the special
case for `l == 0`.

## The trick going the other way: difference arrays

For many *range updates* and one read at the end, invert it. To add `v` to
everything in `[l, r]`:

```
diff[l] += v
diff[r + 1] -= v
```

Prefix-sum `diff` at the end and you have the final array. O(1) per update
instead of O(n).

## Extensions worth knowing

2D prefix sums answer submatrix queries with four lookups
(inclusion-exclusion). And if the array *changes* between queries, prefix
sums stop working - that is where a Fenwick tree earns its keep, at
O(log n) for both update and query.
"""),
            ]),
            UnitDef("greedy", "Greedy", "advanced", "greedy", [
                LessonDef("exchange-argument", "The exchange argument", "reading", 10, body="""
## Greedy is easy to write and easy to get wrong

Take the best-looking option at every step and never reconsider. When it
works it is short and fast. The risk is that it is *confidently wrong* on
inputs you did not try.

## Proving it, the standard way

The exchange argument. Assume an optimal solution differs from the greedy
one; look at the first place they diverge; show you can swap the optimal
choice for the greedy choice without making the answer worse. Repeat, and
the optimal solution turns into the greedy one - so greedy was optimal too.

## Interval scheduling, the clean example

Maximum number of non-overlapping intervals: **sort by end time**, take any
interval that starts after the last one you took.

```
intervals.sort(key=lambda iv: iv[1])
count, last_end = 0, float("-inf")
for start, end in intervals:
    if start >= last_end:
        count += 1
        last_end = end
```

Why earliest end? It leaves the most room for everything after it. Swap in
a longer-but-earlier-ending interval and you never lose - that is the
exchange.

## Sorting by the wrong key

Sorting by *start* time fails: one long early interval blocks several short
ones. Sorting by *length* fails too. The choice of key is the whole
algorithm, and "it passed my three examples" is not a proof.

When no exchange argument works, you usually need DP.
"""),
            ]),
            UnitDef("graph-algorithms", "Graph Algorithms", "advanced", "graphs", [
                LessonDef("dijkstra", "Dijkstra", "reading", 10, body="""
## BFS with a priority queue

On a weighted graph, fewest *edges* stops meaning cheapest *path*. Dijkstra
fixes that by always expanding the closest unfinalised node.

```
import heapq

dist = {start: 0}
pq = [(0, start)]
while pq:
    d, node = heapq.heappop(pq)
    if d > dist.get(node, float("inf")):
        continue                       # stale entry, already improved
    for nxt, w in g[node]:
        nd = d + w
        if nd < dist.get(nxt, float("inf")):
            dist[nxt] = nd
            heapq.heappush(pq, (nd, nxt))
```

O((V + E) log V). The `continue` on a stale pop is what makes the lazy
version correct - Python's heap has no decrease-key.

## The precondition people forget

**No negative edge weights.** Dijkstra finalises a node the moment it pops
it; a later negative edge could have made it cheaper, and it will never
look again. For negative weights use Bellman-Ford, O(VE), which also
detects negative cycles.

## Picking the right one

| Situation | Algorithm |
|---|---|
| Unweighted | BFS, O(V + E) |
| Weights all 0 or 1 | 0-1 BFS with a deque |
| Non-negative weights | Dijkstra |
| Negative weights | Bellman-Ford |
| All pairs, small V | Floyd-Warshall, O(V^3) |
"""),
            ]),
            UnitDef("dp-optimizations", "DP Optimizations", "advanced", "dp", [
                LessonDef("state-compression", "State compression", "reading", 10, body="""
## Dropping a dimension you never read

If `dp[i]` only ever reads `dp[i-1]`, you do not need the whole table:

```
prev = [0] * (W + 1)
for item in items:
    cur = [0] * (W + 1)
    for w in range(W + 1):
        if w >= item.wt:
            cur[w] = max(prev[w], prev[w - item.wt] + item.val)
        else:
            cur[w] = prev[w]
    prev = cur
```

O(nW) time, O(W) memory instead of O(nW). For 0/1 knapsack you can go
further - one array iterated **backwards**, so each item is used at most
once:

```
for item in items:
    for w in range(W, item.wt - 1, -1):
        dp[w] = max(dp[w], dp[w - item.wt] + item.val)
```

Iterate forwards instead and you get unbounded knapsack - each item reused
freely. The loop direction *is* the semantics.

## Bitmask DP

When the state is "which subset have I used" and `n` is small (about 20),
encode the subset as an integer:

```
for mask in range(1 << n):
    for i in range(n):
        if mask & (1 << i):            # i is in the set
            prev = mask ^ (1 << i)     # the set without i
            dp[mask] = min(dp[mask], dp[prev] + cost(prev, i))
```

O(2^n * n). That is how travelling-salesman problems get solved at n = 18,
and why they stop at about n = 22.
"""),
            ]),
        ],
    ),
]
TRACKS_BY_SLUG = {track.slug: track for track in TRACKS}

LESSON_DEFS = {
    (track.slug, unit.slug, lesson.slug): lesson
    for track in TRACKS
    for unit in track.units
    for lesson in unit.lessons
}


def quiz_for(track_slug, unit_slug, lesson_slug):
    """Quiz questions live in the catalog, not the database - the answers must
    never reach the browser."""
    lesson = LESSON_DEFS.get((track_slug, unit_slug, lesson_slug))
    return lesson.quiz if lesson else ()
