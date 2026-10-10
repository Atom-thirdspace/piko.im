BASE_DAMAGE = {"easy": 8, "medium": 14, "hard": 22}
FALLBACK_DAMAGE = 10

SPEED_MAX_BONUS = 0.5 
COMBO_STEP = 0.1
COMBO_CAP = 10 
PLAYER_HP = 100
GRACE_SECONDS = 1.5 

WIN_XP = {1: 40, 2: 70, 3: 110}
PERFECT_BONUS = 25
CONSOLATION_XP = 10
PAID_RUNS_PER_DAY = 3

POOL_SIZE = 40
MIN_POOL = 8          # below this a fight ends in an anticlimax

def damage_for(difficulty, seconds_left, window, combo):
    base = BASE_DAMAGE.get(difficulty, FALLBACK_DAMAGE)
    fraction = 0.0 if window <= 0 else max(0.0, min(1.0, seconds_left / window))
    speed = 1.0 + SPEED_MAX_BONUS * fraction
    chain = 1.0 + COMBO_STEP * min(max(combo, 0), COMBO_CAP)
    return max(1, int(round(base * speed * chain)))

def win_xp(tier, perfect):
    return WIN_XP.get(tier, 40) + (PERFECT_BONUS if perfect else 0)
