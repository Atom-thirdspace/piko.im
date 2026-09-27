"""Parametric generators: same skill, fresh numbers.

The statement is fixed and the data varies, which is exactly what drill
practice wants. Each generator takes a seed so a draft can be reproduced.

Reference solutions are triple-quoted rather than built from escaped
fragments - they are programs, and they should be readable as programs.
"""

import random

from .base import Draft, generator


def _arr(rng, n, lo=-50, hi=50, sort=False):
    xs = [rng.randint(lo, hi) for _ in range(n)]
    return sorted(xs) if sort else xs


def _line(xs):
    return " ".join(str(x) for x in xs)


@generator("lower-bound")
def lower_bound(seed):
    rng = random.Random(seed)
    inputs = []
    for _ in range(8):
        n = rng.randint(0, 12)
        arr = _arr(rng, n, 0, 30, sort=True)
        target = rng.randint(-2, 32)
        inputs.append("%s\n%d\n" % (_line(arr), target))
    # Guaranteed edges, not left to chance.
    inputs += ["\n5\n", "7\n7\n", "2 2 2 2\n2\n"]

    return Draft(
        slug="drill-lower-bound-%04x" % (seed & 0xFFFF),
        title="First index at least the target",
        topic="searching", difficulty="easy", xp=15,
        statement="""
Given a sorted array, print the index of the **first** element greater than
or equal to the target. If every element is smaller, print the array's
length.

## Input
```
line 1: the array, ascending, space separated (may be empty)
line 2: the target
```

## Output
One integer.
""",
        inputs=tuple(inputs),
        reference_source='''
import sys
data = sys.stdin.read().split("\\n")
arr = [int(x) for x in data[0].split()]
t = int(data[1])
lo, hi = 0, len(arr)
while lo < hi:
    mid = (lo + hi) // 2
    if arr[mid] >= t:
        hi = mid
    else:
        lo = mid + 1
print(lo)
'''.lstrip(),
        hints=(("Use a half-open range [lo, hi) with hi = n, not n - 1. "
                "The answer can legitimately be n.", 3),
               ("When arr[mid] >= target, mid is still a candidate, so set "
                "hi = mid rather than mid - 1.", 4)),
    )


@generator("balanced-brackets")
def balanced_brackets(seed):
    rng = random.Random(seed)
    pairs = [("(", ")"), ("[", "]"), ("{", "}")]

    def build(depth):
        if depth <= 0:
            return ""
        o, c = rng.choice(pairs)
        tail = "" if rng.random() < 0.5 else build(depth - 2)
        return o + build(depth - 1) + c + tail

    inputs = []
    for _ in range(6):
        inputs.append((build(rng.randint(1, 5)) or "()") + "\n")
    for _ in range(4):                       # deliberately broken ones
        s = list(build(rng.randint(2, 5)) or "()")
        s[rng.randrange(len(s))] = rng.choice("([{)]}")
        inputs.append("".join(s) + "\n")
    inputs.append("\n")

    return Draft(
        slug="drill-brackets-%04x" % (seed & 0xFFFF),
        title="Balanced brackets",
        topic="stacks-queues", difficulty="easy", xp=15,
        statement="""
Decide whether a line of brackets is balanced. Brackets are `()`, `[]` and
`{}`; every opener must be closed by its own kind, in the right order.

## Input
One line, possibly empty.

## Output
`true` or `false`. An empty line is balanced.
""",
        inputs=tuple(inputs),
        reference_source='''
import sys
s = sys.stdin.readline().rstrip("\\n")
pairs = {")": "(", "]": "[", "}": "{"}
stack = []
ok = True
for ch in s:
    if ch in "([{":
        stack.append(ch)
    elif ch in pairs:
        if not stack or stack.pop() != pairs[ch]:
            ok = False
            break
print("true" if ok and not stack else "false")
'''.lstrip(),
        hints=(("A stack is the whole answer: push openers, and on a closer "
                "check the top matches.", 3),
               ("Two ways to fail: a closer with the wrong thing on top, and "
                "leftovers on the stack at the end.", 4)),
    )


@generator("prefix-sum-queries")
def prefix_sum_queries(seed):
    rng = random.Random(seed)
    inputs = []
    for _ in range(7):
        n = rng.randint(1, 10)
        arr = _arr(rng, n, -20, 20)
        q = rng.randint(1, 5)
        lines = [_line(arr), str(q)]
        for _ in range(q):
            i = rng.randrange(n)
            j = rng.randrange(i, n)
            lines.append("%d %d" % (i, j))
        inputs.append("\n".join(lines) + "\n")
    inputs.append("5\n1\n0 0\n")

    return Draft(
        slug="drill-prefix-sums-%04x" % (seed & 0xFFFF),
        title="Range sums",
        topic="arrays", difficulty="easy", xp=20,
        statement="""
Answer range-sum queries over a fixed array.

## Input
```
line 1: the array, space separated
line 2: q, the number of queries
next q lines: i j  (0-based, inclusive both ends)
```

## Output
One line per query: the sum of `arr[i..j]`.

Summing each range directly is O(n) per query. Precomputing once makes each
query O(1) - that is the point of the exercise.
""",
        inputs=tuple(inputs),
        reference_source='''
import sys
data = sys.stdin.read().split("\\n")
arr = [int(x) for x in data[0].split()]
pre = [0]
for x in arr:
    pre.append(pre[-1] + x)
q = int(data[1])
out = []
for k in range(q):
    i, j = (int(v) for v in data[2 + k].split())
    out.append(str(pre[j + 1] - pre[i]))
print("\\n".join(out))
'''.lstrip(),
        hints=(("Build an array where pre[k] is the sum of the first k "
                "items. Then any range is one subtraction.", 3),
               ("Watch the off-by-one: the sum of arr[i..j] inclusive is "
                "pre[j+1] - pre[i].", 4)),
    )


@generator("gcd-lcm")
def gcd_lcm(seed):
    rng = random.Random(seed)
    inputs = ["%d %d\n" % (rng.randint(1, 10000), rng.randint(1, 10000))
              for _ in range(8)]
    inputs += ["1 1\n", "9973 9973\n", "1 999983\n"]

    return Draft(
        slug="drill-gcd-lcm-%04x" % (seed & 0xFFFF),
        title="GCD and LCM",
        topic="math", difficulty="easy", xp=15,
        statement="""
Print the greatest common divisor and the least common multiple of two
positive integers.

## Input
One line: `a b`, both at least 1.

## Output
One line: `gcd lcm`, space separated.
""",
        inputs=tuple(inputs),
        reference_source='''
import sys
a, b = (int(v) for v in sys.stdin.readline().split())
x, y = a, b
while y:
    x, y = y, x % y
print(x, a // x * b)
'''.lstrip(),
        hints=(("Euclid: gcd(a, b) == gcd(b, a mod b), until the second is "
                "zero.", 3),
               ("lcm = a * b / gcd, but divide before multiplying or you "
                "overflow in languages that can.", 4)),
    )
