"""Things a learner can add to the town with coins. Bought once, kept forever, shown only in their own town.

Where each one stands is decided by the town page (static/journey/town3d/town3d.js, DECOR), on spots that never
block a path. Coins only come from real progress (finished lessons, quests, achievements, levels), so this is a
way to show progress, not to buy it.
"""
from django.db import transaction

from . import game
from .models import LearnerProfile, RewardEvent

# code: name, what it is, price, level needed
DECOR = {
    'street_trees': ('Street trees', 'Trees in planters along the shops.', 40, 1),
    'park_benches': ('Park benches', 'Benches by the pond and under the trees.', 30, 1),
    'park_lamps': ('Park lamps', 'Lamps along the park paths, lit in the evening.', 60, 2),
    'fairy_lights': ('Fairy lights', 'A string of small lights over the café terrace.', 100, 3),
    'market_stall': ('Market stall', 'A third stall at the market.', 80, 4),
    'flags': ('Flags', 'Finnish flags on the academy roof.', 120, 5),
}


def owned(user):
    town = LearnerProfile.for_user(user).town
    town = town if isinstance(town, dict) else {}
    return [c for c in town.get('town_owned', []) if c in DECOR]


def shop(user, status=None):
    status = status or game.status(user)
    have = set(owned(user))
    return [{'code': c, 'name': n, 'desc': d, 'price': p, 'level': lv, 'owned': c in have, 'locked': status['level'] < lv,
             'afford': status['coins'] >= p} for c, (n, d, p, lv) in DECOR.items()]


def buy(user, code):
    """Spend coins on a decoration. Returns (ok, message). Safe against double clicks and races."""
    if code not in DECOR:
        return False, 'That item does not exist.'
    name, _, price, level = DECOR[code]
    with transaction.atomic():
        profile = LearnerProfile.objects.select_for_update().get(pk=LearnerProfile.for_user(user).pk)
        town = profile.town if isinstance(profile.town, dict) else {}
        have = [c for c in town.get('town_owned', []) if c in DECOR]
        if code in have:
            return False, f'You already have the {name.lower()}.'
        xp, coins = game.totals(user)
        if game.level_for(xp) < level:
            return False, f'{name} open at level {level}.'
        if coins < price:
            return False, f'You need {price - coins} more coins.'
        if not game.grant(user, RewardEvent.PURCHASE, f'buy:town:{code}', 0, -price, name):
            return False, f'You already have the {name.lower()}.'
        profile.town = {**town, 'town_owned': have + [code]}
        profile.save(update_fields=['town'])
    return True, f'{name} added to your town.'
