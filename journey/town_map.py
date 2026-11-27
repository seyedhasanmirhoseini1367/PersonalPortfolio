"""The town map for the language world, written as a Tiled map (JSON) so it can be opened and edited in Tiled.

Built from Kenney's RPG Urban Pack (CC0, 16 x 16 tiles, static/journey/town/tiles.png). Run
`python manage.py build_town_map` after changing this file; it writes static/journey/town/town.json.

Layers, bottom to top:
  ground   pavement, roads, grass, water
  marks    road markings and curbs drawn over the ground
  build    buildings: roofs and fronts (collide)
  decor    things standing on the ground: trees, lamps, benches, doors (collide where marked)
  above    things drawn over the walker: tree tops, lamp heads
  objects  spawn point, places to visit, walking routes
"""
import json
from pathlib import Path

W, H = 40, 28
TILE = 16
COLUMNS = 27   # in the packed tilesheet

# ── tiles (index in the packed sheet) ──
PAVE = (8, 9, 10, 35, 36, 37, 62, 63, 64)
GRASS = (0, 1, 2, 27, 28, 29, 54, 55, 56)
WATER = (170, 171, 172, 197, 198, 199, 224, 225, 226)
PLAZA = (89, 90, 91, 116, 117, 118, 143, 144, 145)
ROOF = (81, 82, 83, 108, 109, 110, 135, 136, 137)
ROOF_GREY = (89, 90, 91, 116, 117, 118, 143, 144, 145)
FRONT = {   # top, ledge, middle, bottom rows: (left, middle, right)
    'red': ((17, 18, 19), (44, 45, 46), (71, 72, 73), (98, 99, 100)),
    'orange': ((125, 126, 127), (152, 153, 154), (179, 180, 181), (206, 207, 208)),
}
ASPHALT, DASH_V, CROSS = 441, 461, 435
WINDOW, WINDOW_GREY = 390, 444
DOOR, DOOR_GLASS, DOOR_RED = 284, 285, 309
SHOP_TOP, SHOP_BOTTOM = (359, 360, 361), (386, 387, 388)
TREE = (232, 259)          # tall tree: crown, trunk
TREE_SLIM = (233, 260)
TREE_AUTUMN = (313, 340)
TREE_AUTUMN_SLIM = (314, 341)
SMALL_TREES = (238, 265, 292)            # one tile each
SMALL_AUTUMN = (319, 346, 373)
GROVE = ((234, 235, 236), (261, 262, 263), (288, 289, 290))      # four trees, 3 x 3 tiles
GROVE_AUTUMN = ((315, 316, 317), (342, 343, 344), (369, 370, 371))
POTTED, POTTED_AUTUMN = 286, 367
LAMP = (164, 191)
PARK_LAMP = (169, 196)
BENCH = (270, 271)
BIN, HYDRANT, MAILBOX = 280, 278, 305
CRATES = (301, 302, 276, 303)
BOARD = 250
HEDGE = (328, 329, 330)
BUS_SIGN = (168, 195)     # sign, pole


class Town:
    def __init__(self):
        self.layers = {name: [0] * (W * H) for name in ('ground', 'marks', 'build', 'decor', 'above')}
        self.solid = set()       # (x, y) the walker cannot enter
        self.objects = []

    def put(self, layer, x, y, tile, solid=False):
        if 0 <= x < W and 0 <= y < H:
            self.layers[layer][y * W + x] = tile + 1
            if solid:
                self.solid.add((x, y))

    def fill(self, layer, x0, y0, w, h, tile, solid=False):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                self.put(layer, x, y, tile, solid)

    def nine(self, layer, x0, y0, w, h, t, solid=False):
        for y in range(y0, y0 + h):
            for x in range(x0, x0 + w):
                row = 0 if y == y0 else 2 if y == y0 + h - 1 else 1
                col = 0 if x == x0 else 2 if x == x0 + w - 1 else 1
                self.put(layer, x, y, t[row * 3 + col], solid)

    def obj(self, name, kind, x, y, w=1, h=1, **props):
        self.objects.append({'name': name, 'type': kind, 'x': x * TILE, 'y': y * TILE, 'width': w * TILE,
                             'height': h * TILE, 'props': props})

    # ── pieces ──
    def building(self, x0, y0, w, roof_h, style='red', roof=ROOF):
        """A roof seen from above, then a three-row front. Returns the row of the doorstep."""
        self.nine('build', x0, y0, w, roof_h, roof, solid=True)
        top, _ledge, mid, bottom = FRONT[style]
        fy = y0 + roof_h
        for i, row in enumerate((top, mid, bottom)):
            for x in range(x0, x0 + w):
                t = row[0] if x == x0 else row[2] if x == x0 + w - 1 else row[1]
                self.put('build', x, fy + i, t, solid=True)
        return fy + 3

    def tree(self, x, y, kind=TREE):
        self.put('above', x, y - 1, kind[0])
        self.put('decor', x, y, kind[1], solid=True)

    def grove(self, x, y, kind=GROVE):
        """Four trees in a 3 x 3 block whose trunks stand on row y."""
        for dy, row in enumerate(kind):
            for dx, tile in enumerate(row):
                if dy < 2:
                    self.put('above', x + dx, y - 2 + dy, tile)
                else:
                    self.put('decor', x + dx, y, tile, solid=True)

    def small(self, x, y, tile):
        self.put('decor', x, y, tile, solid=True)

    def lamp(self, x, y, kind=LAMP):
        self.put('above', x, y - 1, kind[0])
        self.put('decor', x, y, kind[1], solid=True)


def build():
    t = Town()
    # pavement everywhere, then the main road north to south with curbs and a zebra crossing
    t.fill('ground', 0, 0, W, H, PAVE[4])
    rx = 18                                    # road: columns rx .. rx+4, dashes in the middle
    t.fill('ground', rx, 0, 5, H, ASPHALT)
    t.fill('marks', rx + 2, 0, 1, H, DASH_V)
    t.fill('ground', rx - 1, 0, 1, H, PAVE[5])   # curb on the west side
    t.fill('ground', rx + 5, 0, 1, H, PAVE[3])   # curb on the east side
    t.fill('marks', rx, 12, 5, 2, CROSS)
    for y in (12, 13):
        t.put('marks', rx + 2, y, CROSS)

    # ── west: the café, a bakery-to-be, the quest board, the park ──
    door_y = t.building(2, 1, 9, 4, 'red')       # Kahvila
    for x, top, bottom in zip((3, 4, 5), SHOP_TOP, SHOP_BOTTOM):
        t.put('decor', x, door_y - 2, top)
        t.put('decor', x, door_y - 1, bottom)
    t.put('decor', 7, door_y - 1, DOOR_GLASS)
    for x in (8, 9):
        t.put('decor', x, door_y - 2, WINDOW)
    t.put('decor', 3, door_y - 3, WINDOW)
    t.obj('cafe', 'place', 7, door_y, 1, 1, title='Kahvila', subtitle='Café: order a coffee', scene='cafe', door_x=7,
          door_y=door_y - 1)
    t.put('decor', 2, door_y, POTTED, solid=True)
    t.put('decor', 10, door_y, POTTED, solid=True)
    t.put('decor', 5, door_y + 1, BENCH[0], solid=True)
    t.put('decor', 6, door_y + 1, BENCH[1], solid=True)

    door2 = t.building(12, 2, 5, 3, 'orange')    # Leipomo (bakery), opens later
    t.put('decor', 14, door2 - 1, DOOR)
    t.put('decor', 13, door2 - 2, WINDOW)
    t.put('decor', 15, door2 - 2, WINDOW)
    t.obj('bakery', 'place', 14, door2, title='Leipomo', subtitle='Bakery: buy bread', scene='bakery',
          door_x=14, door_y=door2 - 1)

    t.put('decor', 13, 11, BOARD, solid=True)    # quest board by the crossing
    t.obj('quests', 'place', 13, 12, title='Ilmoitustaulu', subtitle='Quest board: today’s goals', panel='quests', sign='low',
          door_x=13, door_y=11)
    t.lamp(16, 10)
    t.put('decor', 16, 13, BIN, solid=True)
    t.put('decor', 11, 9, HYDRANT, solid=True)

    # park with a pond
    t.nine('marks', 1, 15, 15, 12, GRASS)
    t.nine('build', 4, 19, 6, 4, WATER, solid=True)
    t.grove(1, 18, GROVE)
    t.grove(12, 26, GROVE_AUTUMN)
    t.tree(13, 18, TREE)
    t.tree(14, 21, TREE_AUTUMN_SLIM)
    t.tree(2, 22, TREE_AUTUMN)
    t.tree(2, 26, TREE_SLIM)
    for (x, y), tile in zip(((11, 20), (10, 24), (4, 25), (8, 26), (3, 20)), SMALL_TREES + SMALL_AUTUMN):
        t.small(x, y, tile)
    t.put('decor', 6, 24, BENCH[0], solid=True)
    t.put('decor', 7, 24, BENCH[1], solid=True)
    t.put('decor', 11, 16, BENCH[0], solid=True)
    t.put('decor', 12, 16, BENCH[1], solid=True)
    t.lamp(5, 17, PARK_LAMP)
    t.lamp(9, 17, PARK_LAMP)
    t.obj('spawn', 'spawn', 8, 14)

    # trees in planters and lamps along both sides of the road
    for y in (3, 8, 18, 23):
        t.small(rx - 2, y, POTTED if y % 2 else POTTED_AUTUMN)
        t.small(rx + 6, y, POTTED_AUTUMN if y % 2 else POTTED)
    for y in (6, 21):
        t.lamp(rx - 2, y)
        t.lamp(rx + 6, y)

    # ── east: the academy (opens later), the market square, homes ──
    door3 = t.building(26, 1, 12, 5, 'red', ROOF)    # Akatemia
    for x in (27, 29, 34, 36):
        t.put('decor', x, door3 - 2, WINDOW)
        t.put('decor', x, door3 - 3, WINDOW)
    t.put('decor', 31, door3 - 1, DOOR)
    t.put('decor', 32, door3 - 1, DOOR)
    t.obj('academy', 'place', 31, door3, 2, 1, title='Akatemia', subtitle='Academy: your lessons and cards', panel='lessons',
          door_x=31, door_y=door3 - 1)
    t.small(27, door3, POTTED)
    t.small(36, door3, POTTED)
    t.put('decor', 38, 11, MAILBOX, solid=True)
    t.put('decor', 29, 12, BENCH[0], solid=True)
    t.put('decor', 30, 12, BENCH[1], solid=True)

    t.nine('marks', 26, 15, 12, 7, PLAZA)            # Tori (market), opens later
    for row_y in (17, 19):
        for i, x in enumerate(range(28, 36)):
            if x != 32:
                t.put('decor', x, row_y, CRATES[(i + row_y) % len(CRATES)], solid=True)
    t.obj('market', 'place', 32, 18, title='Tori', subtitle='Market: buy fruit and vegetables', scene='market',
          door_x=32, door_y=17)
    t.tree(26, 16, TREE_AUTUMN)
    t.tree(37, 16, TREE_AUTUMN)
    t.small(26, 20, SMALL_TREES[0])
    t.small(37, 20, SMALL_TREES[2])
    door4 = t.building(25, 22, 14, 2, 'orange', ROOF_GREY)   # homes along the south edge: one of them is yours
    for x in (26, 28, 30, 35, 37):
        t.put('decor', x, door4 - 2, WINDOW_GREY)
    t.put('decor', 32, door4 - 1, DOOR_RED)
    t.put('decor', 33, door4 - 1, DOOR_RED)
    t.obj('home', 'place', 32, door4, 2, 1, title='Koti', subtitle='Home: your character and progress', panel='home',
          door_x=32, door_y=door4 - 1)

    # bus stop on the east side of the road
    t.put('above', rx + 6, 12, BUS_SIGN[0])
    t.put('decor', rx + 6, 13, BUS_SIGN[1], solid=True)
    t.put('decor', rx + 8, 13, BENCH[0], solid=True)
    t.put('decor', rx + 9, 13, BENCH[1], solid=True)
    t.obj('bus', 'place', rx + 6, 14, title='Bussipysäkki', subtitle='Bus stop: buy a ticket, ask the way', scene='bus', sign='low',
          door_x=rx + 6, door_y=13)

    for y in range(0, H):   # invisible walls on the left and right edges
        t.solid.add((-1, y))
        t.solid.add((W, y))

    # walking routes for townspeople (tile coordinates)
    t.objects.append({'name': 'route1', 'type': 'route', 'x': 0, 'y': 0, 'width': 0, 'height': 0,
                      'props': {'npc': 1, 'points': [[3, 11], [15, 11], [15, 13], [3, 13]]}})
    t.objects.append({'name': 'route2', 'type': 'route', 'x': 0, 'y': 0, 'width': 0, 'height': 0,
                      'props': {'npc': 4, 'points': [[25, 11], [37, 11], [37, 12], [25, 12]]}})
    t.objects.append({'name': 'route3', 'type': 'route', 'x': 0, 'y': 0, 'width': 0, 'height': 0,
                      'props': {'npc': 5, 'points': [[26, 20], [36, 20], [36, 21], [26, 21]]}})
    t.objects.append({'name': 'route4', 'type': 'route', 'x': 0, 'y': 0, 'width': 0, 'height': 0,
                      'props': {'npc': 2, 'points': [[25, 9], [25, 20]]}})
    t.objects.append({'name': 'route5', 'type': 'route', 'x': 0, 'y': 0, 'width': 0, 'height': 0,
                      'props': {'npc': 3, 'points': [[2, 15], [14, 15]]}})
    return t


def to_tiled(t):
    """A Tiled 1.10 map: orthogonal, CSV-free arrays, one tileset, object properties in Tiled's format."""
    def layer(i, name):
        return {'id': i, 'name': name, 'type': 'tilelayer', 'width': W, 'height': H, 'x': 0, 'y': 0,
                'opacity': 1, 'visible': True, 'data': t.layers[name]}
    objects = []
    for i, o in enumerate(t.objects, 1):
        props = [{'name': k, 'type': 'string' if not isinstance(v, bool) else 'bool',
                  'value': json.dumps(v) if isinstance(v, (list, dict)) else v} for k, v in o['props'].items()]
        objects.append({'id': i, 'name': o['name'], 'type': o['type'], 'x': o['x'], 'y': o['y'],
                        'width': o['width'], 'height': o['height'], 'rotation': 0, 'visible': True,
                        'properties': props})
    solid = sorted(p for p in t.solid if 0 <= p[0] < W and 0 <= p[1] < H)
    return {
        'compressionlevel': -1, 'type': 'map', 'version': '1.10', 'tiledversion': '1.10.2', 'orientation': 'orthogonal',
        'renderorder': 'right-down', 'infinite': False, 'width': W, 'height': H, 'tilewidth': TILE, 'tileheight': TILE,
        'nextlayerid': 7, 'nextobjectid': len(objects) + 1,
        'properties': [{'name': 'solid', 'type': 'string', 'value': json.dumps(solid)}],
        'tilesets': [{'firstgid': 1, 'name': 'urban', 'image': 'tiles.png', 'imagewidth': COLUMNS * TILE,
                      'imageheight': 18 * TILE, 'tilewidth': TILE, 'tileheight': TILE, 'tilecount': COLUMNS * 18,
                      'columns': COLUMNS, 'margin': 0, 'spacing': 0}],
        'layers': [layer(1, 'ground'), layer(2, 'marks'), layer(3, 'build'), layer(4, 'decor'), layer(5, 'above'),
                   {'id': 6, 'name': 'objects', 'type': 'objectgroup', 'x': 0, 'y': 0, 'opacity': 1, 'visible': True,
                    'draworder': 'topdown', 'objects': objects}],
    }


def write(path):
    data = to_tiled(build())
    Path(path).write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    return data


def render_preview(path, tiles_path, scale=2):
    """A picture of the whole town (for the Home page), drawn from the same layers as the game."""
    from PIL import Image
    sheet = Image.open(tiles_path).convert('RGBA')
    t = build()
    img = Image.new('RGBA', (W * TILE, H * TILE), (169, 171, 196, 255))
    for name in ('ground', 'marks', 'build', 'decor', 'above'):
        for i, gid in enumerate(t.layers[name]):
            if gid:
                idx = gid - 1
                tile = sheet.crop((idx % COLUMNS * TILE, idx // COLUMNS * TILE, idx % COLUMNS * TILE + TILE, idx // COLUMNS * TILE + TILE))
                img.alpha_composite(tile, (i % W * TILE, i // W * TILE))
    img = img.crop((0, 0, W * TILE, 15 * TILE))   # the streets with the shops: the part that reads at a glance
    img.resize((img.width * scale, img.height * scale), Image.NEAREST).convert('RGB').save(path, optimize=True)
