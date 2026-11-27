"""Things a learner can add to the town with coins. Bought once, kept forever, shown only in their own town.

Each item is drawn from the same Kenney tiles as the map (or, for lights and flags, drawn by the game) at fixed
places that never block a path: journey.tests checks that every door stays reachable with all of them in place.
Coins only come from real progress (finished lessons, quests, achievements, levels), so this is a way to show
progress, not to buy it.
"""
from django.db import transaction

from . import game
from .models import LearnerProfile, RewardEvent

POTTED, POTTED_AUTUMN, BENCH, PARK_LAMP = 286, 367, (270, 271), (169, 196)
CRATES = (301, 302, 276, 303)

# code: name, what it is, price, level needed, tiles [(x, y, tile, layer, solid)], effect drawn by the game
DECOR = {
    'street_trees': ('Street trees', 'Trees in planters at the ends of the streets.', 40, 1,
                     [(0, 8, POTTED, 'decor', True), (0, 13, POTTED_AUTUMN, 'decor', True),
                      (39, 8, POTTED_AUTUMN, 'decor', True), (39, 14, POTTED, 'decor', True)], None),
    'park_benches': ('Park benches', 'Two more places to sit by the pond.', 30, 1,
                     [(12, 22, BENCH[0], 'decor', True), (13, 22, BENCH[1], 'decor', True)], None),
    'park_lamps': ('Park lamps', 'Lamps that light the park after dark.', 60, 2,
                   [(1, 23, PARK_LAMP[0], 'above', False), (1, 24, PARK_LAMP[1], 'decor', True),
                    (15, 23, PARK_LAMP[0], 'above', False), (15, 24, PARK_LAMP[1], 'decor', True)], None),
    'fairy_lights': ('Fairy lights', 'Strings of small lights on the café and the bakery.', 100, 3, [], 'lights'),
    'market_stall': ('Market stall', 'A third row of crates at the market.', 80, 4,
                     [(x, 16, CRATES[i % len(CRATES)], 'decor', True) for i, x in enumerate((28, 29, 30, 31, 33, 34, 35))], None),
    'flags': ('Flags', 'Finnish flags on the academy roof.', 120, 5, [], 'flags'),
}


def owned(user):
    town = LearnerProfile.for_user(user).town
    town = town if isinstance(town, dict) else {}
    return [c for c in town.get('town_owned', []) if c in DECOR]


def shop(user, status=None):
    status = status or game.status(user)
    have = set(owned(user))
    return [{'code': c, 'name': n, 'desc': d, 'price': p, 'level': lv, 'owned': c in have, 'locked': status['level'] < lv,
             'afford': status['coins'] >= p} for c, (n, d, p, lv, _, _) in DECOR.items()]


def placed(user):
    """What the game draws for this learner: tiles to put down and effects to switch on."""
    tiles, fx = [], []
    for code in owned(user):
        _, _, _, _, t, effect = DECOR[code]
        tiles += [{'x': x, 'y': y, 'tile': tile, 'layer': layer, 'solid': solid} for x, y, tile, layer, solid in t]
        if effect:
            fx.append(effect)
    return {'tiles': tiles, 'fx': fx}


def buy(user, code):
    """Spend coins on a decoration. Returns (ok, message). Safe against double clicks and races."""
    if code not in DECOR:
        return False, 'That item does not exist.'
    name, _, price, level, _, _ = DECOR[code]
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
