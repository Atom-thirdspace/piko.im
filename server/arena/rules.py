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
MIN_POOL = 8  

STAKES = {
    "safe":     {"label": "Measured",  "damage": 1.0, "taken": 1.0, "xp": 1.0},
    "bold":     {"label": "Bold",      "damage": 1.5, "taken": 1.4, "xp": 1.3},
    "reckless": {"label": "Reckless",  "damage": 2.0, "taken": 2.0, "xp": 1.7},
}

DEFAULT_STAKE = "safe"


def damage_for(difficulty, seconds_left, window, combo):
    base = BASE_DAMAGE.get(difficulty, FALLBACK_DAMAGE)
    fraction = 0.0 if window <= 0 else max(0.0, min(1.0, seconds_left / window))
    speed = 1.0 + SPEED_MAX_BONUS * fraction
    chain = 1.0 + COMBO_STEP * min(max(combo, 0), COMBO_CAP)
    return max(1, int(round(base * speed * chain)))

def win_xp(tier, perfect):
    return WIN_XP.get(tier, 40) + (PERFECT_BONUS if perfect else 0)

def stake(name):
    return STAKES.get(name, STAKES[DEFAULT_STAKE])

def staked_damage(base, stake_name):
    return max(1, int(round(base * stake(stake_name)["damage"])))

def staked_hit(attack, stake_name):
    return max(1, int(round(attack * stake(stake_name)["taken"])))


def staked_xp(amount, stake_name):
    return int(round(amount * stake(stake_name)["xp"]))

ENDLESS_LIVES = 3
ENDLESS_POINTS = {"easy": 10, "medium": 18, "hard": 28}

def endless_points(difficulty, seconds_left, window, combo):
    base = ENDLESS_POINTS.get(difficulty, 12)
    fraction = 0.0 if window <= 0 else max(0.0, min(1.0, seconds_left / window))
    speed = 1.0 + SPEED_MAX_BONUS * fraction
    chain = 1.0 + COMBO_STEP * min(max(combo, 0), COMBO_CAP)
    return max(1, int(round(base * speed * chain)))