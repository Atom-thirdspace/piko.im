import math

NOISE_FLOOR_MS = 8.0

LABELS = ((0.45, "flat"), (1.30, "linear"), (1.70, "n log n"),
          (2.40, "quadratic"), (3.40, "cubic"))

def sizes_for(start, cap, steps):
    out, n = [], max(int(start), 1)
    while n <= cap and len(out) < steps:
        out.append(n)
        n *= 2
    if out and out[-1] != cap and len(out) < steps:
        out.append(cap)
    return out

def exponent(n1, t1, n2, t2):
    if t1 < NOISE_FLOOR_MS or n2 <= n1 or t1 <= 0 or t2 <= 0:
        return None
    return math.log(t2 / t1) / math.log(float(n2) / n1)

def label(k):
    if k is None:
        return "too fast to tell"
    for ceiling, name in LABELS:
        if k < ceiling:
            return name
    return "worse than cubic"

def verdict(points):
    usable = [(n, t) for n, t in points if t >= NOISE_FLOOR_MS]
    if len(usable) < 2:
        return None, "every run was too fast to measure"
    (n1, t1), (n2, t2) = usable[-2], usable[-1]
    k = exponent(n1, t1, n2, t2)
    return k, label(k)