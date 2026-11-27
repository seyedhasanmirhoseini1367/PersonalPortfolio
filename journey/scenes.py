"""Conversations in the town: short, fixed scenes for real situations, per language. No AI calls.

A scene is a list of turns. In each turn someone in the town says a line and the learner picks the reply that
fits. The answers live only here, on the server: the page sends the choice and gets back right or wrong.
Each scene pays once a day (see journey.game), more for replies that were right the first time.

To add a language, add its scenes under the same keys. The town shows a scene in the language of the
learner's language subject.
"""
import random

XP_PER_TURN = 8
COINS = 10

SCENES = {
    ('cafe', 'finnish'): {
        'title': 'Kahvila',
        'goal': 'Order a coffee, say how you want it, and pay.',
        'npc': {'name': 'Aino', 'role': 'barista', 'sprite': 5},
        'speech': 'fi-FI',
        'turns': [
            {'say': 'Hei! Mitä saisi olla?', 'en': 'Hi! What can I get you?',
             'options': [('Saisinko kahvin, kiitos.', 'Could I have a coffee, please.'),
                         ('Minä olen kahvi.', 'I am a coffee.'),
                         ('Näkemiin!', 'Goodbye!')], 'answer': 0},
            {'say': 'Ison vai pienen?', 'en': 'A large one or a small one?',
             'options': [('Talo on pieni.', 'The house is small.'),
                         ('Ison, kiitos.', 'A large one, please.'),
                         ('Kyllä.', 'Yes.')], 'answer': 1},
            {'say': 'Tuleeko maitoa tai sokeria?', 'en': 'Any milk or sugar?',
             'options': [('Minulla on kissa.', 'I have a cat.'),
                         ('Huomenna.', 'Tomorrow.'),
                         ('Vähän maitoa, kiitos.', 'A little milk, please.')], 'answer': 2},
            {'say': 'Täällä vai mukaan?', 'en': 'For here or to take away?',
             'options': [('Täällä, kiitos.', 'For here, please.'),
                         ('Kahdeksan.', 'Eight.'),
                         ('Hyvää yötä.', 'Good night.')], 'answer': 0},
            {'say': 'Se tekee neljä euroa.', 'en': 'That comes to four euros.',
             'options': [('Ei kiitos.', 'No thank you.'),
                         ('Tässä, ole hyvä.', 'Here you are.'),
                         ('Neljä kissaa.', 'Four cats.')], 'answer': 1},
            {'say': 'Kiitos! Hyvää päivänjatkoa!', 'en': 'Thank you! Have a nice day!',
             'options': [('Anteeksi, missä?', 'Sorry, where?'),
                         ('Ison, kiitos.', 'A large one, please.'),
                         ('Kiitos, samoin!', 'Thanks, you too!')], 'answer': 2},
        ],
    },
    ('bakery', 'finnish'): {
        'title': 'Leipomo',
        'goal': 'Buy bread and buns, and pay by card.',
        'npc': {'name': 'Mikko', 'role': 'baker', 'sprite': 4},
        'speech': 'fi-FI',
        'turns': [
            {'say': 'Huomenta! Mitä teille saisi olla?', 'en': 'Good morning! What can I get you?',
             'options': [('Yksi ruisleipä, kiitos.', 'One rye bread, please.'),
                         ('Minä olen leipä.', 'I am bread.'),
                         ('Hyvää yötä.', 'Good night.')], 'answer': 0},
            {'say': 'Haluatteko sen viipaloituna?', 'en': 'Would you like it sliced?',
             'options': [('Kolme euroa.', 'Three euros.'),
                         ('Kyllä, kiitos.', 'Yes, please.'),
                         ('Se on sininen.', 'It is blue.')], 'answer': 1},
            {'say': 'Saako olla jotain muuta?', 'en': 'Anything else?',
             'options': [('Minulla on koira.', 'I have a dog.'),
                         ('Ei, minä asun täällä.', 'No, I live here.'),
                         ('Kaksi korvapuustia, kiitos.', 'Two cinnamon buns, please.')], 'answer': 2},
            {'say': 'Se on yhteensä seitsemän euroa.', 'en': 'That is seven euros in total.',
             'options': [('Voinko maksaa kortilla?', 'Can I pay by card?'),
                         ('Seitsemän koiraa.', 'Seven dogs.'),
                         ('Huomenna aamulla.', 'Tomorrow morning.')], 'answer': 0},
            {'say': 'Totta kai. Kuitti mukaan?', 'en': 'Of course. Do you want the receipt?',
             'options': [('Leipä on kuuma.', 'The bread is hot.'),
                         ('Ei kiitos.', 'No, thank you.'),
                         ('Missä on asema?', 'Where is the station?')], 'answer': 1},
            {'say': 'Kiitos ja tervetuloa uudelleen!', 'en': 'Thank you, and welcome back!',
             'options': [('Yksi kahvi.', 'One coffee.'),
                         ('Anteeksi, en ymmärrä.', 'Sorry, I do not understand.'),
                         ('Kiitos, hei hei!', 'Thanks, bye bye!')], 'answer': 2},
        ],
    },
    ('market', 'finnish'): {
        'title': 'Tori',
        'goal': 'Ask the price, buy apples, and say no to potatoes.',
        'npc': {'name': 'Pertti', 'role': 'market seller', 'sprite': 3},
        'speech': 'fi-FI',
        'turns': [
            {'say': 'Päivää! Tuoreita omenoita tänään!', 'en': 'Good day! Fresh apples today!',
             'options': [('Omena on auto.', 'An apple is a car.'),
                         ('Paljonko omenat maksavat?', 'How much do the apples cost?'),
                         ('Hyvää joulua!', 'Merry Christmas!')], 'answer': 1},
            {'say': 'Kaksi euroa kilo.', 'en': 'Two euros a kilo.',
             'options': [('Saisinko kilon, kiitos.', 'Could I have a kilo, please.'),
                         ('Kilo on iso talo.', 'A kilo is a big house.'),
                         ('Minä en ole omena.', 'I am not an apple.')], 'answer': 0},
            {'say': 'Tässä, ole hyvä. Entä perunoita?', 'en': 'Here you are. How about potatoes?',
             'options': [('Kyllä, minä olen peruna.', 'Yes, I am a potato.'),
                         ('Hyvää huomenta.', 'Good morning.'),
                         ('Ei kiitos, kotona on perunoita.', 'No thanks, there are potatoes at home.')], 'answer': 2},
            {'say': 'Selvä. Se tekee kaksi euroa.', 'en': 'All right. That comes to two euros.',
             'options': [('Tässä on kaksi euroa.', 'Here are two euros.'),
                         ('Kaksi kissaa, kiitos.', 'Two cats, please.'),
                         ('Missä bussi on?', 'Where is the bus?')], 'answer': 0},
            {'say': 'Kiitos! Mukavaa päivää!', 'en': 'Thank you! Have a nice day!',
             'options': [('Ison, kiitos.', 'A large one, please.'),
                         ('Kiitos, samoin!', 'Thanks, you too!'),
                         ('En tiedä.', 'I do not know.')], 'answer': 1},
        ],
    },
    ('bus', 'finnish'): {
        'title': 'Bussipysäkki',
        'goal': 'Ask where the bus goes, how to buy a ticket and how long the trip takes.',
        'npc': {'name': 'Leena', 'role': 'waiting for the bus', 'sprite': 2},
        'speech': 'fi-FI',
        'turns': [
            {'say': 'Anteeksi, odotatko sinäkin bussia?', 'en': 'Excuse me, are you waiting for the bus too?',
             'options': [('Ei, minä olen bussi.', 'No, I am a bus.'),
                         ('Hyvää ruokahalua!', 'Enjoy your meal!'),
                         ('Kyllä. Mihin tämä bussi menee?', 'Yes. Where does this bus go?')], 'answer': 2},
            {'say': 'Se menee keskustaan.', 'en': 'It goes to the city centre.',
             'options': [('Hyvä! Missä voin ostaa lipun?', 'Good! Where can I buy a ticket?'),
                         ('Keskusta on vihreä.', 'The centre is green.'),
                         ('Kiitos ruoasta.', 'Thanks for the food.')], 'answer': 0},
            {'say': 'Sovelluksella tai kuljettajalta.', 'en': 'With the app or from the driver.',
             'options': [('En ole nälkäinen.', 'I am not hungry.'),
                         ('Kiitos! Kauanko matka kestää?', 'Thanks! How long does the trip take?'),
                         ('Sovellus on koira.', 'The app is a dog.')], 'answer': 1},
            {'say': 'Noin kaksikymmentä minuuttia.', 'en': 'About twenty minutes.',
             'options': [('Selvä, kiitos paljon!', 'All right, thanks a lot!'),
                         ('Kaksikymmentä kahvia.', 'Twenty coffees.'),
                         ('Missä on leipä?', 'Where is the bread?')], 'answer': 0},
            {'say': 'Ole hyvä! Tuolla bussi jo tuleekin.', 'en': 'You are welcome! Here comes the bus already.',
             'options': [('Bussi on kissa.', 'The bus is a cat.'),
                         ('Hyvää yötä, bussi.', 'Good night, bus.'),
                         ('Hienoa, hyvää päivänjatkoa!', 'Great, have a nice day!')], 'answer': 2},
        ],
    },
}

# Small talk from people walking around town: (what they say, what it means). No reward, just listening.
GREETINGS = {
    'finnish': [('Moi!', 'Hi!'), ('Hei, mitä kuuluu?', 'Hi, how are you?'), ('Huomenta!', 'Good morning!'),
                ('Kylmä tänään, eikö?', 'Cold today, isn’t it?'), ('Hyvää päivää!', 'Good day!'),
                ('Moikka, nähdään!', 'Bye, see you!'), ('Kaunis ilma!', 'Lovely weather!')],
}

LANGUAGE_SUBJECTS = ('finnish',)   # subjects that are languages, and so get a town


def get(key, language):
    return SCENES.get((key, language))


def shuffle(scene, rng=random):
    """A new order of the replies for every turn, so the right one is never learned by its place."""
    order = []
    for t in scene['turns']:
        o = list(range(len(t['options'])))
        rng.shuffle(o)
        order.append(o)
    return order


def public(scene, order=None):
    """What the page may see: every line and option (in the shown order), never which option is right."""
    order = order or [list(range(len(t['options']))) for t in scene['turns']]
    return {'title': scene['title'], 'goal': scene['goal'], 'npc': scene['npc'], 'speech': scene['speech'],
            'turns': [{'say': t['say'], 'en': t['en'], 'options': [t['options'][i][0] for i in order[n]]}
                      for n, t in enumerate(scene['turns'])]}


def check(scene, turn, choice, order=None):
    """(right, what the chosen reply means) for the option shown at place `choice`."""
    t = scene['turns'][turn]
    picked = order[turn][choice] if order else choice
    return picked == t['answer'], t['options'][picked][1]


def phrases(scene):
    """The right replies, to save as cards: (the phrase, its meaning, the line it answers)."""
    return [(t['options'][t['answer']][0], t['options'][t['answer']][1], t['say']) for t in scene['turns']]
