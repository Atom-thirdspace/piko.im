from dataclasses import dataclass, field
from typing import List
from ..learning.catalog import TRACKS_BY_SLUG, level_rank

XP_PER_MINTUE = 3
MIN_DAILY_GOAL = 20

_TRACK_REASONS = {
    "foundations": "Foundations first, so every later topic has something to stand on.",
    "interview-core": "Interview Core covers the patterns interviews lean on most.",
    "competitive": "Your placement says you're ready for contest-style problems.",
}

@dataclass
class Recommendation:
    track_slug:str
    unit_slug:str
    level:str
    daily_goal_xp: int
    focus_topics: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

def pick_track(goal,level):
    if level == "beginner":
        return "foundations"
    if goal == "cp" and level == "advanced":
        return "competitive"
    return "interview-core"

def pick_start_unit(track, level, topics):
    if level == "beginner" or not topics:
        return track.units[0]
    rank = level_rank(level)
    for unit in track.units:
        if unit.topic in topics and level_rank(unit.level) <= rank:
            return unit
    return track.units[0]

def daily_goal(weekly_minutes):
    raw = int(weekly_minutes) * XP_PER_MINTUE / 7
    return max(MIN_DAILY_GOAL, int(round(raw/10.0)) * 10)

def recommend(answers, level):
    goal = answers.get("goal")
    topics = answers.get("topics") or []
    track_slug = pick_track(goal, level)
    track = TRACKS_BY_SLUG[track_slug]
    unit = pick_start_unit(track, level, topics)

    reasons = [_TRACK_REASONS[track_slug]]
    if goal == "cp" and track_slug != "competitive":
        reasons.append("The Competitive track assumes these patterns - it's next once you're through.")
    if unit is not track.units[0]:
        reasons.append("Starting at %s because you picked it and you're ready for it." % unit.title)

    return Recommendation(
        track_slug=track_slug,
        unit_slug=unit.slug,
        level=level,
        daily_goal_xp=daily_goal(answers.get("weekly_minutes", "90")),
        focus_topics=list(topics),
        reasons=reasons

    )