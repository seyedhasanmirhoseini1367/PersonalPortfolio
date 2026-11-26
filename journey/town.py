"""The town: a small top-down world where lesson scenes become people to talk to.

Each place has a character. When one of the learner's published lessons has a scene
for that kind of place, the character uses it; otherwise a short built-in starter
conversation (A1 Finnish) is used, so the town is never empty. Lesson scenes for
other places go to people standing around the square.
"""
import random

from .models import LessonPack, Scene

# Sprite frames from static/journey/game/tiny_dungeon.png
PEOPLE = {'woman': 99, 'man': 86, 'elder': 100, 'grandpa': 111, 'boy': 85, 'girl': 88, 'ranger': 112, 'guard': 98}
PLAYER_CHOICES = [85, 88, 99, 112, 86, 98]


def _step(who, fi, en, wrong=()):
    s = {'who': who, 'fi': fi, 'en': en}
    if who == 'you':
        options = [fi, *wrong]
        random.Random(fi).shuffle(options)
        s.update(options=options, answer=options.index(fi))
    return s


STARTERS = {
    'cafe': dict(title='Ordering a coffee', npc_name='Aino', npc_role='barista', you_role='customer', steps=[
        _step('npc', 'Hei! Tervetuloa. Mitä saisi olla?', 'Hi! Welcome. What would you like?'),
        _step('you', 'Yksi kahvi, kiitos.', 'One coffee, please.', ['Yksi kahvia, kiitos olen.', 'Minä olen kahvi.']),
        _step('npc', 'Maitoa tai sokeria?', 'Milk or sugar?'),
        _step('you', 'Vähän maitoa, kiitos.', 'A little milk, please.', ['Vähän maito, kiitos.', 'Ei, minä asun maitoa.']),
        _step('npc', 'Se tekee kolme euroa.', 'That will be three euros.'),
        _step('you', 'Tässä, ole hyvä.', 'Here you are.', ['Tässä olen hyvä.', 'Kolme euroa on minä.']),
        _step('npc', 'Kiitos! Hyvää päivänjatkoa!', 'Thank you! Have a nice day!'),
    ]),
    'market': dict(title='Buying apples', npc_name='Pekka', npc_role='market seller', you_role='customer', steps=[
        _step('npc', 'Päivää! Mitä teille?', 'Good day! What can I get you?'),
        _step('you', 'Paljonko omenat maksavat?', 'How much are the apples?',
              ['Paljonko omena maksaa sinä?', 'Missä omenat asuvat?']),
        _step('npc', 'Kilo maksaa kaksi euroa.', 'A kilo costs two euros.'),
        _step('you', 'Otan kaksi kiloa, kiitos.', 'I will take two kilos, please.',
              ['Otan kaksi kilo, kiitos.', 'Ota minä kaksi kiloa.']),
        _step('npc', 'Neljä euroa, kiitos.', 'Four euros, please.'),
        _step('you', 'Tässä. Kiitos ja hei hei!', 'Here. Thanks and bye!', ['Tässä on neljä kilo.', 'Hei hei on neljä euroa.']),
    ]),
    'station': dict(title='A ticket to Helsinki', npc_name='Liisa', npc_role='ticket clerk', you_role='traveller', steps=[
        _step('npc', 'Hei! Miten voin auttaa?', 'Hi! How can I help?'),
        _step('you', 'Yksi lippu Helsinkiin, kiitos.', 'One ticket to Helsinki, please.',
              ['Yksi lippu Helsinki, kiitos.', 'Yksi lippu Helsingissä, kiitos.']),
        _step('npc', 'Meno vai meno-paluu?', 'One way or return?'),
        _step('you', 'Meno-paluu, kiitos.', 'Return, please.', ['Menen paluu, kiitos.', 'Meno ja paluu ja meno.']),
        _step('npc', 'Juna lähtee raiteelta kolme.', 'The train leaves from track three.'),
        _step('you', 'Kiitos paljon!', 'Thank you very much!', ['Kiitos paljo!', 'Paljon kiitos minä.']),
    ]),
    'home': dict(title='Meeting a neighbour', npc_name='Matti', npc_role='neighbour', you_role='new neighbour', steps=[
        _step('npc', 'Hei! Oletko uusi täällä?', 'Hi! Are you new here?'),
        _step('you', 'Olen. Minun nimeni on Alex.', 'I am. My name is Alex.', ['Olen. Minä nimi on Alex.', 'Olet. Sinun nimi Alex.']),
        _step('npc', 'Hauska tutustua! Mistä sinä olet kotoisin?', 'Nice to meet you! Where are you from?'),
        _step('you', 'Olen kotoisin Iranista.', 'I am from Iran.', ['Olen kotoisin Iran.', 'Olen kotoisin Iranissa.']),
        _step('npc', 'Tervetuloa Suomeen!', 'Welcome to Finland!'),
        _step('you', 'Kiitos! Nähdään!', 'Thanks! See you!', ['Kiitos! Näen!', 'Kiitos! Nähdä!']),
    ]),
}

PLACES = [
    # key, Finnish name, English name, building style, person
    {'key': 'cafe', 'fi': 'Kahvila', 'en': 'Café', 'person': 'woman'},
    {'key': 'market', 'fi': 'Tori', 'en': 'Market', 'person': 'man'},
    {'key': 'station', 'fi': 'Rautatieasema', 'en': 'Station', 'person': 'elder'},
    {'key': 'home', 'fi': 'Koti', 'en': 'Home', 'person': 'grandpa'},
]
SQUARE_PEOPLE = ['ranger', 'girl', 'boy', 'guard']


def _scene_json(scene):
    return {'id': scene.pk, 'title': scene.title, 'npc_name': scene.npc_name, 'npc_role': scene.npc_role,
            'you_role': scene.you_role, 'steps': scene.steps, 'max': scene.max_score, 'lesson': scene.pack.title}


def build(user):
    """Places and people for this learner's town, from their newest published lesson scenes."""
    scenes = list(Scene.objects.filter(pack__status=LessonPack.PUBLISHED, pack__group__memberships__user=user)
                  .select_related('pack').order_by('-pack__published_at', 'order')[:12])
    by_setting = {}
    for sc in scenes:
        by_setting.setdefault(sc.setting, []).append(sc)

    used, places = set(), []
    for p in PLACES:
        own = by_setting.get(p['key'], [])
        scene = own[0] if own else None
        if scene:
            used.add(scene.pk)
        data = _scene_json(scene) if scene else dict(STARTERS[p['key']], id=None, lesson='', max=0)
        places.append({**p, 'frame': PEOPLE[p['person']], 'scene': data, 'from_lesson': bool(scene)})

    square = []
    for n, sc in enumerate(s for s in scenes if s.pk not in used):
        if n >= len(SQUARE_PEOPLE):
            break
        person = SQUARE_PEOPLE[n]
        square.append({'key': f'square{n}', 'fi': sc.setting_info['label'], 'en': sc.setting_info['label'],
                       'person': person, 'frame': PEOPLE[person], 'scene': _scene_json(sc), 'from_lesson': True})
    return {'places': places, 'square': square, 'player_choices': PLAYER_CHOICES}
