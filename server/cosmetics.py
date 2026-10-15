"""Cosmetics: the coin sink, and the reward that cannot inflate the economy.

The catalogue is code, not rows - it needs no admin CRUD, it diffs in review,
and an unlock is a key rather than a foreign key to something editable.
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from . import economy
from .models import UserCosmetic, db

SLOTS = ("theme", "frame", "title", "sigil", "pet")


@dataclass(frozen=True)
class Cosmetic:
    key: str
    slot: str
    label: str
    cost: int               
    earn: str = ""       
    value: str = ""         


CATALOGUE = (
    # Editor themes
    Cosmetic("theme-default", "theme", "Piko", 0, value="theme-default"),
    Cosmetic("theme-paper", "theme", "Paper", 150, value="theme-paper"),
    Cosmetic("theme-dusk", "theme", "Dusk", 150, value="theme-dusk"),
    Cosmetic("theme-ember", "theme", "Ember", 400, value="theme-ember"),
    Cosmetic("theme-abyss", "theme", "Abyss", 0, earn="solve_50",
             value="theme-abyss"),

    # Avatar frames
    Cosmetic("frame-none", "frame", "No frame", 0, value=""),
    Cosmetic("frame-brass", "frame", "Brass", 120, value="frame-brass"),
    Cosmetic("frame-jade", "frame", "Jade", 300, value="frame-jade"),
    Cosmetic("frame-gold", "frame", "Gold", 0, earn="streak_30",
             value="frame-gold"),

    # Titles
    Cosmetic("title-none", "title", "No title", 0, value=""),
    Cosmetic("title-grinder", "title", "The Grinder", 200, value="The Grinder"),
    Cosmetic("title-nocturnal", "title", "Nocturnal", 200, value="Nocturnal"),
    Cosmetic("title-unbroken", "title", "Unbroken", 0, earn="combo_15",
             value="Unbroken"),
    Cosmetic("title-slayer", "title", "Titan Slayer", 0, earn="boss_10",
             value="Titan Slayer"),
    Cosmetic("title-polyglot", "title", "Polyglot", 0, earn="polyglot_3",
             value="Polyglot"),

    # Arena sigils
    Cosmetic("sigil-blade", "sigil", "Blade", 100, value="\u2694"),
    Cosmetic("sigil-bolt", "sigil", "Bolt", 100, value="\u26a1"),
    Cosmetic("sigil-crown", "sigil", "Crown", 0, earn="boss_first",
             value="\U0001F451"),

    # Companion species - see companion.py for the stages
    Cosmetic("pet-byte", "pet", "Byte", 0, value="byte"),
    Cosmetic("pet-nibble", "pet", "Nibble", 250, value="nibble"),
    Cosmetic("pet-sprite", "pet", "Sprite", 500, value="sprite"),
    Cosmetic("pet-wyrmling", "pet", "Wyrmling", 0, earn="boss_10",
             value="wyrmling"),
)

BY_KEY = {c.key: c for c in CATALOGUE}
FREE = {c.key for c in CATALOGUE if c.cost == 0 and not c.earn}
BUYABLE = {c.key for c in CATALOGUE if c.cost > 0}


def owned_keys(user):
    if user is None:
        return set(FREE)
    held = set(db.session.execute(
        db.select(UserCosmetic.key)
        .where(UserCosmetic.user_id == user.id)).scalars())
    return held | FREE


def grant(user, key, source="earned"):
    if key not in BY_KEY:
        return False
    try:
        with db.session.begin_nested():
            db.session.add(UserCosmetic(user_id=user.id, key=key,
                                        source=source))
    except IntegrityError:
        return False
    db.session.commit()
    return True


def buy(user, key):
    item = BY_KEY.get(key)
    if item is None:
        return False, "No such thing."
    if key in owned_keys(user):
        return False, "You already have that."
    if item.cost <= 0:
        return False, "That one is earned, not bought."
    if not economy.spend(user, item.cost, "cosmetic", key):
        return False, "Not enough coins."
    grant(user, key, source="bought")
    return True, "Unlocked %s." % item.label


def grant_for_achievements(user, keys):
    earned = {c.key for c in CATALOGUE if c.earn and c.earn in set(keys)}
    return [k for k in earned if grant(user, k, source="achievement")]


def equip(user, slot, key):
    if slot not in SLOTS:
        return False, "Unknown slot."
    item = BY_KEY.get(key)
    if item is None or item.slot != slot:
        return False, "That does not go there."
    if key not in owned_keys(user):
        return False, "You have not unlocked that."

    user.equipped = {**(user.equipped or {}), slot: key}
    if slot == "pet":
        user.companion = item.value
    db.session.commit()
    return True, "Equipped."


def equipped_value(user, slot, default=""):
    if user is None:
        return default
    key = (user.equipped or {}).get(slot)
    item = BY_KEY.get(key)
    return item.value if item else default


def wardrobe(user):
    held = owned_keys(user)
    chosen = user.equipped or {}
    out = {}
    for slot in SLOTS:
        out[slot] = [{
            "key": c.key, "label": c.label, "cost": c.cost,
            "value": c.value, "earn": c.earn,
            "owned": c.key in held,
            "equipped": chosen.get(slot) == c.key,
            "affordable": c.cost > 0 and economy.balance(user) >= c.cost,
        } for c in CATALOGUE if c.slot == slot]
    return out
