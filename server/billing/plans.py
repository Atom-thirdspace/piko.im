import os

PLANS = {
    "monthly" : {
        "key": "monthly",
        "name": "Piko Pro",
        "cadence": "per month",
        "price": "$6",
        "env": "POLAR_PRODUCT_MONTHLY",
        "blurb": "Billed monthly. Cancel whenever.",
    },
    "yearly" : {
        "key" : "yearly",
        "name": "Piko Pro",
        "cadence": "per year",
        "price": "$48",
        "env": "POLAR_PRODUCT_YEARLY",
        "blurb": "Two months free against the monthly price.",
        "highlight": True,
    },
    "classroom": {
        "key": "classroom",
        "name": "Classroom",
        "cadence": "per seat / year",
        "price": "$18",
        "env": "POLAR_PRODUCT_CLASSROOM",
        "blurb": "For teachers and bootcamps. One payer, a join code for "
                 "students, and everyone gets Pro.",
        "seats": True,
        "min_seats": 5,
        "max_seats": 500,
    },
}

PERKS = [
    "Unlimited runs against your own input",
    "The AI tutor without the hourly cap",
    "Full solutions and editorials on every problem",
    "Priority in the judge queue",
]

def product_id(plan_key):
    plan = PLANS.get(plan_key)
    if plan is None:
        return None
    return (os.environ.get(plan["env"]) or "").strip() or None

def plan_for_product(pid):
    for key in PLANS:
        if product_id(key) == pid:
            return key
    return ""

def available():
    return [dict(p, product_id=product_id(k)) for k, p in PLANS.items()
            if product_id(k)]

def is_configured():
    return bool((os.environ.get("POLAR_ACCESS_TOKEN") or "").strip()
            and available())

