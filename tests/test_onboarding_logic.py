from server.learning.catalog import TRACKS
from server.onboarding import placement
from server.onboarding.recommend import daily_goal, recommend
from server.progress import level_for_xp, xp_for_level

def test_level_boundaries_are_exact():
    for level in range(1, 100):
        start = xp_for_level(level)
        assert level_for_xp(start) == level
        if level > 1:
            assert level_for_xp(start - 1) == level - 1 
