from .progress import level_for_xp

STAGES = (
    (0,  "egg",      "\U0001F95A"),
    (3,  "hatchling", "\U0001F423"),
    (8,  "fledgling", "\U0001F424"),
    (15, "grown",     "\U0001F426"),
    (25, "elder",     "\U0001F985"),
)

SPECIES = {
    "byte":     {"label": "Byte",     "art": ("\U0001F95A", "\U0001F423",
                                              "\U0001F424", "\U0001F426",
                                              "\U0001F985")},
    "nibble":   {"label": "Nibble",   "art": ("\U0001F95A", "\U0001F42D",
                                              "\U0001F439", "\U0001F43F",
                                              "\U0001F98A")},
    "sprite":   {"label": "Sprite",   "art": ("\u2728", "\U0001FAB2",
                                              "\U0001F99B", "\U0001F98B",
                                              "\U0001F409")},
    "wyrmling": {"label": "Wyrmling", "art": ("\U0001F95A", "\U0001F98E",
                                              "\U0001F40D", "\U0001F432",
                                              "\U0001F409")},
}

MOODS = (
    ("asleep", "Your streak has lapsed. It is napping."),
    ("hungry", "Nothing yet today."),
    ("content", "Fed today."),
    ("thriving", "Well past your goal."),
)

def stage_index(level):
    index = 0
    for i, (needed, _name, _art) in enumerate(STAGES):
        if level >= needed:
            index = i
    return index

def mood(user, today_xp, streak_days):
    goal = user.daily_goal_xp or 0
    if streak_days <= 0:
        return MOODS[0]
    if today_xp <= 0:
        return MOODS[1]
    if goal and today_xp >= goal * 2:
        return MOODS[3]
    return MOODS[2]

def state(user, today_xp=0, streak_days=0):
    species = SPECIES.get(user.companion or "byte", SPECIES["byte"])
    level = level_for_xp(user.xp_total or 0)
    index = stage_index(level)
    _, stage_name, _ = STAGES[index]
    key, line = mood(user, today_xp, streak_days)

    nxt = STAGES[index + 1][0] if index + 1 < len(STAGES) else None
    return {
        "species": species["label"],
        "art": species["art"][index],
        "stage": stage_name,
        "mood": key,
        "line": line,
        "level": level,
        "next_level": nxt,
        "levels_to_go": (nxt - level) if nxt else None,
    }

