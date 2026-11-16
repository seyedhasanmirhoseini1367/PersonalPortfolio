"""Motion graphics for the "How Models Work" notebooks.

A Scene is a list of SVG primitives plus keyframes, computed in Python from the
same numbers the notebook prints, and rendered in the browser by
static/js/hmw-motion.js. Nothing is drawn in Python: displaying a Scene emits a
JSON spec under its own mime type, which the importer stores as a `motion`
block.

    s = Scene(720, 360, dur=8, caption="RoPE keeps the angle between q and k")
    dot = s.circle(cx=100, cy=180, r=8, fill="cyan", opacity=0)
    dot.to(0.0, 0.6, opacity=1)              # fade in over 0.0 -> 0.6 s
    dot.to(1.0, 3.0, cx=600, ease="inout")   # then slide
    s.beat(0, "First, ...")                  # caption line under the stage
    s                                         # last expression -> displayed

Each element remembers its current state, so `to(t0, t1, ...)` emits a hold
keyframe at t0 and the target at t1: the element does not move before t0.
Numbers tween, colours tween, lists of numbers (`pts`) tween element-wise,
anything else switches at the keyframe.
"""
import json
import math

MIME = 'application/vnd.hmw.motion+json'

# Named colours, resolved here so the JSON is self-contained. Tuned for the
# dark stage the player draws on.
PALETTE = {
    'bg':     '#0f1226',
    'panel':  '#171b36',
    'grid':   '#262b4d',
    'muted':  '#7c84b0',
    'text':   '#e6e9ff',
    'cyan':   '#22d3ee',
    'violet': '#a78bfa',
    'pink':   '#f472b6',
    'amber':  '#fbbf24',
    'green':  '#34d399',
    'red':    '#f87171',
    'blue':   '#60a5fa',
    'white':  '#ffffff',
}

_COLOUR_KEYS = {'fill', 'stroke'}


def colour(c):
    return PALETTE.get(c, c) if isinstance(c, str) else c


def mix(c1, c2, t):
    """Blend two colours (names or #rrggbb); t=0 gives c1."""
    a, b = colour(c1).lstrip('#'), colour(c2).lstrip('#')
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (0, 2, 4))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (0, 2, 4))
    t = min(max(t, 0.0), 1.0)
    return '#%02x%02x%02x' % (round(ra + (rb - ra) * t), round(ga + (gb - ga) * t),
                              round(ba + (bb - ba) * t))


def ramp(v, lo='bg', hi='cyan', vmin=0.0, vmax=1.0):
    """Map a value onto a two-colour ramp."""
    t = 0.0 if vmax == vmin else (v - vmin) / (vmax - vmin)
    return mix(lo, hi, t)


def diverge(v, vmax=1.0, neg='pink', mid='panel', pos='cyan'):
    """Map a signed value onto neg-mid-pos."""
    t = 0.0 if vmax == 0 else max(-1.0, min(1.0, v / vmax))
    return mix(mid, pos, t) if t >= 0 else mix(mid, neg, -t)


def _clean(v):
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError('non-finite value in scene')
        return round(v, 3)
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if hasattr(v, 'item'):            # numpy scalar
        return _clean(v.item())
    if hasattr(v, 'tolist'):          # numpy array
        return _clean(v.tolist())
    return v


def _norm(attrs):
    out = {}
    for k, v in attrs.items():
        if k in _COLOUR_KEYS:
            v = colour(v)
        out[k] = _clean(v)
    return out


class El:
    def __init__(self, scene, kind, attrs):
        self.scene = scene
        self.kind = kind
        self.base = _norm(attrs)
        self.state = dict(self.base)
        self.keys = []                     # [t, {attr: value}, ease]

    def _key(self, t, attrs, ease):
        self.keys.append([_clean(float(t)), attrs, ease])

    def to(self, t0, t1, ease='inout', **attrs):
        """Hold the current value until t0, then tween to `attrs` by t1."""
        attrs = _norm(attrs)
        hold = {k: self.state.get(k, attrs[k]) for k in attrs}
        if t1 <= t0:
            self._key(t0, attrs, 'step')
        else:
            self._key(t0, hold, 'step')
            self._key(t1, attrs, ease)
        self.state.update(attrs)
        return self

    def set(self, t, **attrs):
        """Jump to `attrs` at time t."""
        attrs = _norm(attrs)
        self._key(t, attrs, 'step')
        self.state.update(attrs)
        return self

    def fade_in(self, t0, d=0.4):
        return self.to(t0, t0 + d, opacity=1, ease='out')

    def fade_out(self, t0, d=0.4):
        return self.to(t0, t0 + d, opacity=0, ease='in')

    def pulse(self, t0, d=0.5, attr='r', scale=1.6):
        v = self.state[attr]
        self.to(t0, t0 + d / 2, ease='out', **{attr: v * scale})
        self.to(t0 + d / 2, t0 + d, ease='in', **{attr: v})
        return self

    def spec(self):
        keys = sorted(self.keys, key=lambda k: k[0])
        d = {'t': self.kind, 'a': self.base}
        if keys:
            d['k'] = keys
        return d


class Scene:
    def __init__(self, w=720, h=380, dur=8.0, caption='', loop=True, poster=None):
        self.w, self.h, self.dur = w, h, float(dur)
        self.caption = caption
        self.loop = loop
        self.poster = poster       # time shown when motion is reduced
        self.els = []
        self.beats = []

    # ── primitives ────────────────────────────────────────────────
    def _add(self, kind, **attrs):
        attrs.setdefault('opacity', 1)
        el = El(self, kind, attrs)
        self.els.append(el)
        return el

    def circle(self, cx, cy, r=6, fill='cyan', **kw):
        return self._add('circle', cx=cx, cy=cy, r=r, fill=fill, **kw)

    def rect(self, x, y, w, h, fill='panel', rx=4, **kw):
        return self._add('rect', x=x, y=y, w=w, h=h, fill=fill, rx=rx, **kw)

    def line(self, x1, y1, x2, y2, stroke='muted', sw=2, **kw):
        return self._add('line', x1=x1, y1=y1, x2=x2, y2=y2, stroke=stroke, sw=sw, **kw)

    def arrow(self, x1, y1, x2, y2, stroke='cyan', sw=3, head=10, **kw):
        return self._add('arrow', x1=x1, y1=y1, x2=x2, y2=y2, stroke=stroke, sw=sw,
                         head=head, **kw)

    def polar(self, cx, cy, length, ang, stroke='cyan', sw=3, head=10, **kw):
        """Arrow from (cx, cy) with a length and an angle in degrees (counter-
        clockwise, maths convention). Tweening `ang` rotates it rigidly."""
        return self._add('polar', cx=cx, cy=cy, len=length, ang=ang, stroke=stroke,
                         sw=sw, head=head, **kw)

    def poly(self, pts, stroke='cyan', sw=2, fill='none', closed=False, **kw):
        """Polyline through a flat list [x0, y0, x1, y1, ...]."""
        flat = []
        for p in pts:
            if isinstance(p, (list, tuple)):
                flat.extend(p)
            else:
                flat.append(p)
        return self._add('poly', pts=flat, stroke=stroke, sw=sw, fill=fill,
                         closed=1 if closed else 0, **kw)

    def text(self, x, y, s, size=14, fill='text', anchor='middle', weight=400,
             mono=False, **kw):
        return self._add('text', x=x, y=y, s=str(s), size=size, fill=fill,
                         anchor=anchor, weight=weight, mono=1 if mono else 0, **kw)

    def num(self, x, y, v, dec=2, pre='', post='', size=14, fill='text',
            anchor='middle', weight=600, mono=True, sep=False, **kw):
        """A number that counts smoothly when `v` is tweened. sep=True adds
        thousands separators."""
        if sep:
            kw['sep'] = 1
        return self._add('num', x=x, y=y, v=float(v), dec=dec, pre=pre, post=post,
                         size=size, fill=fill, anchor=anchor, weight=weight,
                         mono=1 if mono else 0, **kw)

    def arc(self, cx, cy, r, a0, a1, stroke='amber', sw=2, **kw):
        """Arc between two angles (degrees, CCW). Both ends tween."""
        return self._add('arc', cx=cx, cy=cy, r=r, a0=a0, a1=a1, stroke=stroke, sw=sw,
                         **kw)

    # ── helpers ───────────────────────────────────────────────────
    def beat(self, t, s):
        """Caption line shown under the stage from time t."""
        self.beats.append([_clean(float(t)), s])

    def grid(self, x0, y0, x1, y1, step, stroke='grid', sw=1, **kw):
        out = []
        x = x0
        while x <= x1 + 1e-9:
            out.append(self.line(x, y0, x, y1, stroke=stroke, sw=sw, **kw))
            x += step
        y = y0
        while y <= y1 + 1e-9:
            out.append(self.line(x0, y, x1, y, stroke=stroke, sw=sw, **kw))
            y += step
        return out

    def spec(self):
        d = {'v': 1, 'w': self.w, 'h': self.h, 'dur': self.dur, 'loop': self.loop,
             'caption': self.caption, 'els': [e.spec() for e in self.els],
             'beats': sorted(self.beats, key=lambda b: b[0])}
        if self.poster is not None:
            d['poster'] = self.poster
        return d

    def _repr_mimebundle_(self, include=None, exclude=None):
        spec = self.spec()
        return {MIME: spec,
                'text/plain': f'<motion scene: {self.caption or "untitled"} '
                              f'({len(self.els)} elements, {self.dur:g}s)>'}

    def to_json(self):
        return json.dumps(self.spec(), separators=(',', ':'))
