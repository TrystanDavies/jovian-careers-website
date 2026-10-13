"""Scene pictures, painted in oils in the manner of L. S. Lowry.

Lowry famously worked with only five pigments: flake white, ivory black,
vermilion, Prussian blue and yellow ochre. Everything else on his canvases
(the creamy grey-white skies, the brick reds, the muddy umbers, the odd
green) was mixed from those five. These pictures follow the same rule:
every colour is one of the five pigments or a mixture of them made by mix()
below, and tests/test_art_map.py checks that nothing else creeps in.

Each picture is built from flat shapes, worked over with brushstrokes, and
finished with an "oil" filter that wobbles the edges like a loaded brush and
raises an impasto texture. Cave scenes are assembled from the room's real
exits (painted as openings in the rock, so the picture agrees with the map),
its features, what's lying about, and a Lowry matchstick figure: you.
"""

import math
import random

from .world import ROOMS

# The five pigments --------------------------------------------------------

W = "#F3EFE2"   # flake white
K = "#1F1C19"   # ivory black
V = "#D2381F"   # vermilion
P = "#003153"   # Prussian blue
O = "#C99A2E"   # yellow ochre
PALETTE = (W, K, V, P, O)

MIXES = {}      # every mixed colour, with its recipe


def mix(*parts):
    """Mix pigments: mix((W, 6), (K, 1)) is six parts white to one of black."""
    total = float(sum(w for _c, w in parts))
    rgb = [0.0, 0.0, 0.0]
    for colour, weight in parts:
        if colour not in PALETTE:
            raise ValueError("%s is not one of Lowry's pigments" % colour)
        for i in range(3):
            rgb[i] += int(colour[1 + 2 * i:3 + 2 * i], 16) * weight / total
    hexed = "#%02X%02X%02X" % tuple(int(round(c)) for c in rgb)
    MIXES[hexed] = tuple(parts)
    return hexed


def allowed_colours():
    return set(c.upper() for c in PALETTE) | set(MIXES)


# Lowry's mixtures
SKY = mix((W, 14), (K, 1), (P, 0.4))            # his grey-white sky
SKY_WARM = mix((W, 14), (O, 1), (K, 0.5))
SKY_COOL = mix((W, 10), (P, 1), (K, 0.6))
GROUND = mix((W, 7), (O, 1), (K, 0.8))          # pale, trodden ground
GROUND_DK = mix((W, 3), (O, 1), (K, 1))
FIELD = mix((O, 3), (W, 2), (K, 0.5))
GREY = mix((W, 3), (K, 1))
GREY_DK = mix((W, 1), (K, 2))
SLATE = mix((K, 3), (P, 1), (W, 1))
BRICK = mix((V, 4), (K, 1.4), (O, 0.6))         # mill-brick red
BRICK_DK = mix((V, 2), (K, 2.2))
BRICK_LT = mix((V, 3), (O, 1), (W, 0.6))
SOOT = mix((K, 6), (V, 0.4), (O, 0.4))
UMBER = mix((O, 2), (K, 1.2), (V, 0.25))        # lamplit rock
UMBER_DK = mix((O, 1), (K, 2.6), (V, 0.2))
UMBER_LT = mix((O, 3), (W, 1), (K, 0.4))
CAVE = mix((K, 5), (O, 0.5), (V, 0.15))
FLOOR = mix((O, 3), (W, 0.8), (K, 0.9))
FLOOR_LT = mix((O, 2), (W, 1.4), (K, 0.3))
WATER = mix((P, 3), (W, 1), (K, 0.3))
WATER_LT = mix((P, 1), (W, 2.5))
WATER_DK = mix((P, 2), (K, 1))
GREEN = mix((P, 2), (O, 3), (K, 0.4))           # Prussian blue + ochre
GREEN_DK = mix((P, 2), (O, 1.5), (K, 1))
GREEN_LT = mix((P, 1), (O, 3), (W, 1))
LAVA = mix((V, 2), (O, 1))
EMBER = mix((V, 3), (K, 1))
GOLD = mix((O, 4), (W, 1))
FLESH = mix((W, 4), (V, 0.6), (O, 0.6))
COAT = mix((K, 8), (P, 1))
BEAR = mix((K, 3), (V, 0.7), (O, 1))
TROLL = mix((O, 2), (P, 1), (K, 1))
LIMESTONE = mix((W, 6), (O, 1), (K, 0.4))

WIDTH, HEIGHT = 320, 200
L, T, R, B = -10, -10, WIDTH + 10, HEIGHT + 10     # paint past the edges


class Svg(object):
    """A small SVG builder."""

    def __init__(self, width=WIDTH, height=HEIGHT, prefix="sc", extra="", crisp=False):
        self.width = width
        self.height = height
        self.prefix = prefix
        self.extra = extra
        self.crisp = crisp
        self.parts = []
        self.defs = {}
        self.n = 0

    @staticmethod
    def _attrs(kw):
        out = []
        for k, v in kw.items():
            if v is None:
                continue
            k = k.rstrip("_").replace("_", "-")
            if isinstance(v, float):
                v = ("%.2f" % v).rstrip("0").rstrip(".")
            out.append('%s="%s"' % (k, v))
        return " ".join(out)

    def el(self, tag, **kw):
        self.parts.append("<%s %s/>" % (tag, self._attrs(kw)))

    def rect(self, x, y, w, h, fill, **kw):
        self.el("rect", x=x, y=y, width=w, height=h, fill=fill, **kw)

    def poly(self, pts, fill, **kw):
        self.el("polygon", points=" ".join("%g,%g" % (round(a, 1), round(b, 1)) for a, b in pts),
                fill=fill, **kw)

    def circle(self, cx, cy, r, fill, **kw):
        self.el("circle", cx=cx, cy=cy, r=r, fill=fill, **kw)

    def ellipse(self, cx, cy, rx, ry, fill, **kw):
        self.el("ellipse", cx=cx, cy=cy, rx=rx, ry=ry, fill=fill, **kw)

    def line(self, x1, y1, x2, y2, stroke, width=1, **kw):
        kw.setdefault("stroke_linecap", "round")
        self.el("line", x1=round(x1, 1), y1=round(y1, 1), x2=round(x2, 1), y2=round(y2, 1),
                stroke=stroke, stroke_width=width, **kw)

    def path(self, d, fill="none", stroke=None, width=1, **kw):
        if stroke:
            kw.setdefault("stroke_linecap", "round")
            kw.setdefault("stroke_linejoin", "round")
        self.el("path", d=d, fill=fill, stroke=stroke, stroke_width=width if stroke else None, **kw)

    def text(self, x, y, s, fill, size=8, anchor="start", family=None, **kw):
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.parts.append('<text %s>%s</text>' % (self._attrs(dict(
            x=x, y=y, fill=fill, font_size=size, text_anchor=anchor,
            font_family=family or "'VT323', 'Courier New', monospace", **kw)), s))

    def raw(self, s):
        self.parts.append(s)

    def uid(self, stem):
        self.n += 1
        return "%s-%s%d" % (self.prefix, stem, self.n)

    def clip(self, pts):
        cid = self.uid("c")
        self.defs[cid] = '<clipPath id="%s"><polygon points="%s"/></clipPath>' % (
            cid, " ".join("%g,%g" % (round(a, 1), round(b, 1)) for a, b in pts))
        return "url(#%s)" % cid

    def glow(self, colour, inner=0.8):
        """A radial glaze: colour at the centre, thinning to nothing."""
        gid = self.uid("g")
        self.defs[gid] = ('<radialGradient id="%s"><stop offset="0" stop-color="%s" stop-opacity="%.2f"/>'
                          '<stop offset="1" stop-color="%s" stop-opacity="0"/></radialGradient>'
                          % (gid, colour, inner, colour))
        return "url(#%s)" % gid

    def soften(self, amount=2.0):
        fid = "%s-soft%d" % (self.prefix, int(amount * 10))
        self.defs[fid] = ('<filter id="%s" x="-30%%" y="-30%%" width="160%%" height="160%%">'
                          '<feGaussianBlur stdDeviation="%.1f"/></filter>' % (fid, amount))
        return "url(#%s)" % fid

    def oil(self, seed):
        """Loaded-brush edges and an impasto canvas texture."""
        fid = "%s-oil" % self.prefix
        self.defs[fid] = (
            '<filter id="%s" x="-2%%" y="-2%%" width="104%%" height="104%%" color-interpolation-filters="sRGB">'
            '<feTurbulence type="fractalNoise" baseFrequency="0.04 0.055" numOctaves="2" seed="%d" result="warp"/>'
            '<feDisplacementMap in="SourceGraphic" in2="warp" scale="5" xChannelSelector="R" '
            'yChannelSelector="G" result="paint"/>'
            '<feTurbulence type="fractalNoise" baseFrequency="0.07 0.16" numOctaves="3" seed="%d" result="strokes"/>'
            '<feDiffuseLighting in="strokes" surfaceScale="1.3" diffuseConstant="1.05" lighting-color="%s" '
            'result="impasto"><feDistantLight azimuth="225" elevation="58"/></feDiffuseLighting>'
            '<feComposite in="paint" in2="impasto" operator="arithmetic" k1="0.42" k2="0.66" k3="0" k4="0"/>'
            '</filter>' % (fid, seed, seed + 11, W))
        return "url(#%s)" % fid

    def render(self):
        defs = "<defs>%s</defs>" % "".join(self.defs.values()) if self.defs else ""
        rendering = "crispEdges" if self.crisp else "geometricPrecision"
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
                'shape-rendering="%s" %s>%s%s</svg>'
                % (self.width, self.height, rendering, self.extra, defs, "".join(self.parts)))


# ----------------------------------------------------------------------------
# Brushwork
# ----------------------------------------------------------------------------

def strokes(cv, rnd, box, tones, n, width=(2.0, 5.0), length=(8, 26), angle=0.0,
            spread=10.0, alpha=(0.45, 0.9)):
    """Scumble n short brushstrokes of the given tones across a box."""
    x0, y0, x1, y1 = box
    for _ in range(n):
        x = rnd.uniform(x0, x1)
        y = rnd.uniform(y0, y1)
        ln = rnd.uniform(*length)
        a = math.radians(angle + rnd.uniform(-spread, spread))
        dx, dy = math.cos(a) * ln / 2, math.sin(a) * ln / 2
        bend = rnd.uniform(-2, 2)
        cv.path("M%.1f %.1f Q %.1f %.1f %.1f %.1f" % (
            x - dx, y - dy, x - dy * 0.1 + bend, y + dx * 0.1 + bend, x + dx, y + dy),
            stroke=rnd.choice(tones), width=round(rnd.uniform(*width), 1),
            opacity=round(rnd.uniform(*alpha), 2))


def paint(cv, rnd, pts, base, tones, n=40, **kw):
    """Fill a shape, then work brushstrokes into it, kept inside its edges."""
    cv.poly(pts, base)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cv.raw('<g clip-path="%s">' % cv.clip(pts))
    strokes(cv, rnd, (min(xs), min(ys), max(xs), max(ys)), tones, n, **kw)
    cv.raw("</g>")


# ----------------------------------------------------------------------------
# Context for one picture
# ----------------------------------------------------------------------------

class Ctx(object):
    def __init__(self, g):
        self.g = g
        self.rid = g.state["room"]
        self.room = ROOMS[self.rid]
        self.rnd = random.Random(self.rid)
        self.feats = set(f.split(":")[0] for f in self.room["feats"])
        self.args = dict(f.split(":", 1) for f in self.room["feats"] if ":" in f)
        self.exits = set(g.exit_dirs())
        self.floor = 182          # where feet stand
        self.slots = [222, 252, 282, 196, 62, 36, 300, 168]
        self.slot_y = None
        self.figure_x = 120
        self.inside = self.room["scene"] == "wellhouse"
        self.ceil, self.fl, self.inset = 34, 138, 54


# ----------------------------------------------------------------------------
# The explorer: a Lowry matchstick figure in a long dark coat
# ----------------------------------------------------------------------------

def figure(cv, x, foot, scale=1.0, lamp=False, facing=1, shadow=True):
    s = scale
    head = foot - 33 * s
    if shadow:
        cv.ellipse(x + 3 * s, foot + 1, 9 * s, 2.2 * s, GREY_DK, opacity=0.45)
    # legs mid-stride, Lowry-thin
    cv.line(x - 2 * s, foot - 13 * s, x - 6 * s, foot, K, 1.6 * s)
    cv.line(x + 2 * s, foot - 13 * s, x + 4 * s, foot, K, 1.6 * s)
    # a long coat, leaning into the walk
    cv.path("M%.1f %.1f L %.1f %.1f L %.1f %.1f L %.1f %.1f Z" % (
        x - 3.5 * s + facing * 1.5 * s, head + 6 * s, x + 3.5 * s + facing * 1.5 * s, head + 6 * s,
        x + 6.5 * s, foot - 11 * s, x - 6.5 * s, foot - 11 * s), fill=COAT)
    cv.line(x - 4 * s + facing * s, head + 9 * s, x + 4 * s + facing * s, head + 8 * s, V, 1.4 * s)
    cv.circle(x + facing * 1.6 * s, head + 2.6 * s, 3.1 * s, FLESH)
    cv.path("M%.1f %.1f q %.1f %.1f %.1f 0 l %.1f 0" % (
        x + facing * 1.6 * s - 3.4 * s, head + 1.8 * s, 3.4 * s, -3.6 * s, 6.8 * s, facing * 2 * s),
        stroke=K, width=1.6 * s, fill=K)                                    # flat cap
    hx, hy = x + facing * 9 * s, foot - 17 * s
    cv.line(x + facing * 3 * s, head + 9 * s, hx, hy, COAT, 1.6 * s)
    if lamp:
        cv.circle(hx, hy + 3 * s, 22 * s, cv.glow(GOLD, 0.55))
        cv.rect(hx - 2.5 * s, hy, 5 * s, 6.5 * s, O)
        cv.rect(hx - 1.5 * s, hy + 1.5 * s, 3 * s, 3.2 * s, W)


# ----------------------------------------------------------------------------
# Out of doors
# ----------------------------------------------------------------------------

def sky(cv, c, bottom=120, tones=(SKY, SKY_WARM, W, SKY_COOL)):
    paint(cv, c.rnd, [(L, T), (R, T), (R, bottom), (L, bottom)], SKY, tones,
          n=70, width=(3, 7), length=(20, 50), spread=4, alpha=(0.35, 0.8))


def ground(cv, c, top, tones=(GROUND, GROUND_DK, SKY_WARM, FIELD), base=GROUND, n=60):
    paint(cv, c.rnd, [(L, top), (R, top), (R, B), (L, B)], base, tones,
          n=n, width=(3, 6), length=(14, 40), spread=6)


def tree(cv, x, base, h, rnd):
    """A spindly, leafless Lowry tree."""
    cv.path("M%.1f %.1f q %.1f %.1f %.1f %.1f" % (x, base, rnd.uniform(-3, 3), -h / 2, rnd.uniform(-2, 2), -h),
            stroke=K, width=2.4)
    for i in range(5):
        by = base - h * (0.35 + 0.12 * i)
        d = rnd.choice((-1, 1))
        ln = h * (0.32 - 0.04 * i)
        cv.path("M%.1f %.1f q %.1f %.1f %.1f %.1f" % (x, by, d * ln * 0.5, -ln * 0.2, d * ln, -ln * 0.65),
                stroke=K, width=1.1)


def far_hills(cv, c, y, tone=SKY_COOL):
    pts = [(L, B), (L, y)]
    for x in range(-10, WIDTH + 30, 22):
        pts.append((x, y - c.rnd.randint(0, 10)))
    pts.append((R, B))
    cv.poly(pts, tone)


def mill_house(cv, c, x, y, w, h, smoke=True):
    """The well house, painted like one of Lowry's red-brick buildings."""
    paint(cv, c.rnd, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], BRICK,
          (BRICK, BRICK_DK, BRICK_LT), n=18, width=(2, 4), length=(6, 14), spread=3)
    cv.poly([(x + w * 0.72, y), (x + w, y), (x + w, y + h), (x + w * 0.72, y + h)], BRICK_DK, opacity=0.6)
    cv.poly([(x - 5, y + 2), (x + w / 2.0, y - h * 0.48), (x + w + 5, y + 2)], SOOT)
    cv.rect(x + w * 0.70, y - h * 0.62, w * 0.12, h * 0.52, SOOT)
    cv.rect(x + w * 0.40, y + h * 0.45, w * 0.2, h * 0.55, SOOT)
    cv.rect(x + w * 0.10, y + h * 0.28, w * 0.18, h * 0.22, SKY_COOL)
    cv.line(x + w * 0.19, y + h * 0.28, x + w * 0.19, y + h * 0.5, SOOT, 1.2)
    if smoke:
        sx, sy = x + w * 0.76, y - h * 0.66
        soft = cv.soften(2.2)
        for i in range(5):
            cv.ellipse(sx + i * 6, sy - i * 7, 4 + i * 1.6, 3 + i, GREY, opacity=round(0.55 - i * 0.07, 2),
                       filter=soft)


def s_road(cv, c):
    sky(cv, c, 118)
    far_hills(cv, c, 104)
    ground(cv, c, 110)
    paint(cv, c.rnd, [(146, 110), (160, 110), (236, B), (56, B)], GREY, (GREY, GREY_DK, GROUND_DK, SKY),
          n=40, width=(2, 5), length=(10, 30), angle=90, spread=25)
    mill_house(cv, c, 222, 84, 64, 44)
    cv.path("M254 128 C 262 150 236 160 262 182 S 282 196 300 206", stroke=WATER, width=4)
    cv.path("M256 134 C 262 150 240 160 262 180", stroke=WATER_LT, width=1.2, opacity=0.8)
    for i, x in enumerate((12, 30, 50, 92, 118, 300)):
        tree(cv, x, 116 + (i % 2) * 5, 44 + (i * 7) % 18, c.rnd)
    c.figure_x, c.floor = 150, 172


def s_wellhouse(cv, c):
    paint(cv, c.rnd, [(L, T), (R, T), (R, 134), (L, 134)], SKY_WARM, (SKY_WARM, SKY, GROUND, W),
          n=70, width=(3, 7), length=(12, 30), angle=90, spread=6)
    cv.rect(L, T, R - L, 24, SOOT)
    paint(cv, c.rnd, [(L, 134), (R, 134), (R, B), (L, B)], UMBER, (UMBER, UMBER_LT, UMBER_DK),
          n=50, width=(2, 4), length=(20, 60), spread=2)
    for y in (150, 166, 184):
        cv.line(L, y, R, y + 1, UMBER_DK, 1)
    cv.rect(L, 130, R - L, 5, SOOT)
    cv.rect(16, 54, 50, 84, SOOT)
    paint(cv, c.rnd, [(21, 59), (61, 59), (61, 116), (21, 116)], SKY, (SKY, W), n=10, width=(3, 5))
    cv.rect(21, 116, 40, 22, FIELD)
    cv.ellipse(150, 170, 46, 13, WATER)
    cv.ellipse(146, 167, 30, 6, WATER_LT, opacity=0.5)
    for x in range(112, 190, 8):
        cv.line(x, 160, x, 180, SOOT, 1.4)
    cv.ellipse(150, 170, 46, 13, "none", stroke=SOOT, stroke_width=2.4)
    for y in (64, 100):
        cv.rect(210, y, 96, 4, SOOT)
        cv.rect(212, y + 4, 3, 10, SOOT)
        cv.rect(300, y + 4, 3, 10, SOOT)
    c.slots = [228, 252, 276, 296, 228, 252, 276, 296]
    c.slot_y = [64, 64, 64, 64, 100, 100, 100, 100]
    c.figure_x, c.floor = 88, 178


def s_hill(cv, c):
    sky(cv, c, 120)
    far_hills(cv, c, 118)
    paint(cv, c.rnd, [(L, 92), (120, 56), (220, 70), (R, 120), (R, B), (L, B)], FIELD,
          (FIELD, GROUND, GROUND_DK, UMBER_LT), n=70, width=(3, 6), length=(14, 36), angle=-10, spread=15)
    cv.path("M160 210 C 150 160 230 140 330 116", stroke=GREY_DK, width=11)
    cv.path("M160 210 C 150 160 230 140 330 116", stroke=GREY, width=8)
    cv.path("M110 60 L 118 80 L 104 100", stroke=GROUND_DK, width=2.5)
    for i, x in enumerate((18, 38, 270, 296)):
        tree(cv, x, 150 + (i % 2) * 10, 40, c.rnd)
    c.figure_x, c.floor = 168, 176


def s_hilltop(cv, c):
    sky(cv, c, 130)
    for x in range(-10, WIDTH + 10, 8):
        cv.ellipse(x, 124 + (x * 7) % 5, 6, 6, SLATE)
    ground(cv, c, 128, tones=(GROUND, GROUND_DK, SKY_COOL), n=30)
    cv.path("M60 150 C 120 138 180 146 250 132", stroke=GREY, width=3)
    cv.path("M200 152 L 210 138 L 196 126", stroke=WATER, width=2.5)
    mill_house(cv, c, 246, 118, 18, 12, smoke=False)
    paint(cv, c.rnd, [(L, B), (L, 172), (90, 154), (200, 152), (R, 170), (R, B)], FIELD,
          (FIELD, GROUND, UMBER_LT), n=30, width=(3, 6), length=(14, 30))
    c.figure_x, c.floor = 150, 170


def s_forest(cv, c):
    sky(cv, c, 150)
    ground(cv, c, 140)
    rnd = c.rnd
    for _ in range(17):
        tree(cv, rnd.randint(-5, WIDTH + 5), rnd.randint(140, 198), rnd.randint(70, 130), rnd)
    c.figure_x, c.floor = 150, 186


def s_valley(cv, c):
    sky(cv, c, 120)
    paint(cv, c.rnd, [(L, 40), (150, 122), (170, 122), (R, 40), (R, B), (L, B)], FIELD,
          (FIELD, GROUND, UMBER_LT), n=60, width=(3, 6), length=(14, 34))
    cv.poly([(L, 40), (150, 122), (L, B)], GROUND_DK, opacity=0.45)
    paint(cv, c.rnd, [(150, 120), (170, 120), (244, B), (86, B)], WATER, (WATER, WATER_LT, WATER_DK),
          n=40, width=(1.5, 3.5), length=(6, 16), angle=75, spread=20)
    for x, y in ((30, 70), (60, 86), (270, 62), (300, 52), (244, 80)):
        tree(cv, x, y + 30, 34, c.rnd)
    c.figure_x, c.floor = 70, 186


def s_slit(cv, c):
    sky(cv, c, 72)
    ground(cv, c, 66, tones=(GROUND, GROUND_DK, FIELD, GREY))
    paint(cv, c.rnd, [(150, 64), (170, 64), (176, 128), (144, 128)], WATER, (WATER, WATER_LT),
          n=14, width=(1.5, 3), length=(8, 16), angle=90)
    cv.path("M140 129 q 20 4 40 0", stroke=SOOT, width=3.5)
    for x, y, r in ((60, 120, 14), (98, 150, 10), (230, 112, 16), (262, 158, 12), (40, 172, 9)):
        cv.ellipse(x, y, r, r * 0.6, GREY_DK)
        cv.ellipse(x - r * 0.2, y - r * 0.2, r * 0.6, r * 0.3, GREY, opacity=0.8)
    c.figure_x, c.floor = 120, 182


def s_grate(cv, c):
    sky(cv, c, 44)
    paint(cv, c.rnd, [(L, 32), (R, 32), (282, 94), (38, 94)], FIELD, (FIELD, GROUND_DK, UMBER_LT),
          n=40, width=(3, 5), length=(10, 26), angle=-20, spread=40)
    cv.poly([(L, 32), (38, 94), (L, B)], UMBER_DK, opacity=0.5)
    cv.poly([(R, 32), (282, 94), (R, B)], UMBER_DK, opacity=0.5)
    ground(cv, c, 92, tones=(GROUND_DK, UMBER_LT, GROUND), base=GROUND_DK, n=40)
    cv.rect(108, 138, 104, 40, GREY)
    cv.rect(120, 146, 80, 24, SOOT)
    if c.g.istate("grate") == "open":
        for x in range(130, 196, 10):
            cv.line(x, 146, x + (x - 160) * 0.12, 112, K, 1.8)
        cv.line(126, 112, 194, 112, K, 2)
    else:
        for x in range(124, 200, 8):
            cv.line(x, 146, x, 170, UMBER_LT, 2)
        cv.line(120, 158, 200, 158, UMBER_LT, 2)
        cv.rect(156, 154, 8, 8, V)
    for x in (24, 52, 268, 296):
        tree(cv, x, 36, 26, c.rnd)
    c.figure_x, c.floor = 80, 188


def s_volcano(cv, c):
    paint(cv, c.rnd, [(L, T), (R, T), (R, B), (L, B)], EMBER, (EMBER, V, LAVA, BRICK_DK, SOOT),
          n=110, width=(3, 7), length=(16, 40), angle=-60, spread=50)
    cv.ellipse(160, 120, 160, 70, cv.glow(LAVA, 0.6))
    cv.poly([(104, B), (150, 92), (176, 92), (236, B)], SOOT)
    cv.poly([(150, 92), (176, 92), (170, 80), (156, 80)], LAVA)
    for d in ("M158 84 C 140 40 120 30 96 60", "M168 84 C 190 30 220 28 240 70",
              "M163 84 C 160 30 170 10 180 20"):
        cv.path(d, stroke=V, width=5)
        cv.path(d, stroke=GOLD, width=1.8)
    cv.path("M158 100 L 150 140 L 160 210", stroke=GOLD, width=3)
    cv.path("M168 100 L 180 150 L 172 210", stroke=V, width=3)
    paint(cv, c.rnd, [(36, T), (48, T), (48, B), (36, B)], SKY, (W, SKY_COOL), n=20,
          width=(1, 2.5), length=(10, 30), angle=90, spread=3)
    cv.poly([(L, 170), (130, 166), (152, B), (L, B)], SOOT)
    cv.path("M-10 170 L 130 166", stroke=LAVA, width=1.5)
    c.figure_x, c.floor = 80, 172


def s_repository(cv, c):
    paint(cv, c.rnd, [(L, T), (R, T), (R, 142), (L, 142)], UMBER_DK, (UMBER_DK, UMBER, CAVE),
          n=80, width=(3, 7), length=(16, 40))
    ground(cv, c, 140, tones=(FLOOR, FLOOR_LT, UMBER), base=FLOOR)
    for x in (30, 120, 210, 300):
        cv.rect(x - 2, 20, 4, 40, SOOT)
        cv.ellipse(x, 18, 30, 26, cv.glow(LAVA, 0.5))
        cv.path("M%d 22 q -6 -8 0 -18 q 6 10 0 18 z" % x, fill=V)
        cv.path("M%d 20 q -3 -4 0 -10 q 3 5 0 10 z" % x, fill=GOLD)
    paint(cv, c.rnd, [(L, 70), (R, 70), (R, 100), (L, 100)], SKY_COOL, (SKY_COOL, W, WATER_LT),
          n=40, width=(2, 5), length=(20, 50), spread=2)
    cv.line(L, 70, R, 70, SOOT, 2)
    cv.line(L, 100, R, 100, SOOT, 2)
    if c.rid == "repo_ne":
        for i in range(9):
            x = 170 + i * 16
            y = 150 + (i % 3) * 8
            cv.ellipse(x, y, 7, 4, COAT)
            cv.poly([(x - 4, y - 2), (x + 2, y - 2), (x - 1, y - 10)], V)
            cv.circle(x + 5, y - 1, 2, W)
        for i in range(6):
            cv.rect(20 + i * 12, 120, 6, 18, WATER_LT, stroke=SOOT, stroke_width=1)
        for i in range(4):
            cv.line(100 + i * 9, 138, 100 + i * 9, 118, GREEN, 2.2)
    else:
        cv.ellipse(70, 160, 46, 12, SOOT)
        for i in range(6):
            cv.path("M%d 160 q 5 -6 10 0 t 10 0" % (36 + i * 10), stroke=GREEN, width=2.4)
        for i in range(5):
            x = 180 + i * 24
            cv.path("M%d 140 q 9 -18 18 0 z" % x, stroke=O, width=1.5)
            cv.circle(x + 9, 134, 3, K)
        cv.rect(132, 172, 56, 14, SOOT)
        for x in range(136, 188, 6):
            cv.line(x, 172, x, 186, UMBER_LT, 1.2)
    c.figure_x, c.floor = (120 if c.rid == "repo_sw" else 90), 186


SURFACE = {"road": s_road, "wellhouse": s_wellhouse, "hill": s_hill,
           "hilltop": s_hilltop, "forest": s_forest, "valley": s_valley,
           "slit": s_slit, "grate": s_grate, "volcano": s_volcano,
           "repository": s_repository}


# ----------------------------------------------------------------------------
# Underground
# ----------------------------------------------------------------------------

SHAPES = {
    #           ceiling, floor line, side inset
    "chamber": (34, 138, 54),
    "low": (78, 140, 30),
    "canyon": (8, 150, 116),
    "tall": (4, 146, 96),
    "vast": (0, 118, 16),
    "tunnel": (60, 132, 104),
}


def cave_shape(c):
    f = c.feats
    for key in ("low", "canyon", "vast", "tall"):
        if key in f:
            return key
    if f & {"tunnel", "long_hall", "maze", "deadend"}:
        return "tunnel"
    return "chamber"


def cave(cv, c):
    shape = cave_shape(c)
    ceil, fl, inset = SHAPES[shape]
    rnd = c.rnd
    wall, wall_tones = UMBER, (UMBER, UMBER_DK, FLOOR, UMBER_LT, UMBER_DK)
    side, side_tones = UMBER_DK, (UMBER_DK, CAVE, UMBER)
    floor, floor_tones = FLOOR, (FLOOR, FLOOR_LT, UMBER, GROUND_DK)
    if "limestone" in c.feats:
        wall, wall_tones = LIMESTONE, (LIMESTONE, W, GROUND, UMBER_LT)
    if "warm" in c.feats:
        side, side_tones = EMBER, (EMBER, BRICK_DK, V, CAVE)
        floor, floor_tones = BRICK_LT, (BRICK_LT, FLOOR, LAVA)
    cv.rect(L, T, R - L, B - T, CAVE)
    strokes(cv, rnd, (L, T, R, ceil + 20), (CAVE, SOOT, UMBER_DK), 30, width=(3, 7), length=(20, 50))
    top = [(inset, fl)]
    x = inset
    while x < WIDTH - inset:
        top.append((x, ceil + rnd.randint(0, 10)))
        x += rnd.randint(14, 26)
    top.append((WIDTH - inset, ceil + rnd.randint(0, 8)))
    top.append((WIDTH - inset, fl))
    paint(cv, rnd, top, wall, wall_tones, n=60, width=(3, 7), length=(10, 28), angle=80, spread=30,
          alpha=(0.25, 0.55))
    paint(cv, rnd, [(L, T), (inset, ceil + 6), (inset, fl), (L, B)], side, side_tones,
          n=30, width=(3, 6), length=(10, 30), angle=60, spread=30)
    paint(cv, rnd, [(R, T), (WIDTH - inset, ceil + 6), (WIDTH - inset, fl), (R, B)], side, side_tones,
          n=30, width=(3, 6), length=(10, 30), angle=120, spread=30)
    paint(cv, rnd, [(inset, fl), (WIDTH - inset, fl), (R, B), (L, B)], floor, floor_tones,
          n=50, width=(3, 7), length=(14, 44), spread=5, alpha=(0.3, 0.65))
    for _ in range(rnd.randint(3, 7)):
        sx = rnd.randint(inset + 4, WIDTH - inset - 4)
        cv.poly([(sx - 4, ceil + 4), (sx + 4, ceil + 4), (sx, ceil + 12 + rnd.randint(0, 14))], CAVE)
    c.ceil, c.fl, c.inset = ceil, fl, inset
    openings(cv, c)
    return shape


def arch(cv, cx, base, w, h, fill=CAVE):
    cv.path("M%g %g L %g %g Q %g %g %g %g L %g %g Z" % (
        cx - w / 2.0, base, cx - w / 2.0, base - h * 0.6, cx, base - h * 1.25,
        cx + w / 2.0, base - h * 0.6, cx + w / 2.0, base), fill=fill)


def openings(cv, c):
    ceil, fl, inset = c.ceil, c.fl, c.inset
    ex = c.exits
    back_h = fl - ceil
    if "n" in ex:
        arch(cv, WIDTH / 2.0, fl, min(48, WIDTH - 2 * inset - 20), min(70, back_h * 0.7))
    if "nw" in ex:
        arch(cv, inset + (WIDTH / 2.0 - inset) * 0.4, fl, 26, min(44, back_h * 0.5))
    if "ne" in ex:
        arch(cv, WIDTH - inset - (WIDTH / 2.0 - inset) * 0.4, fl, 26, min(44, back_h * 0.5))
    if "w" in ex:
        mid = inset * 0.55
        cv.poly([(mid - 14, fl - back_h * 0.55 - 6), (mid + 10, fl - back_h * 0.5),
                 (mid + 10, fl + 6), (mid - 14, fl + 22)], CAVE)
    if "e" in ex:
        mid = WIDTH - inset * 0.55
        cv.poly([(mid + 14, fl - back_h * 0.55 - 6), (mid - 10, fl - back_h * 0.5),
                 (mid - 10, fl + 6), (mid + 14, fl + 22)], CAVE)
    if "sw" in ex:
        cv.poly([(L, 150), (26, 156), (30, B), (L, B)], CAVE)
    if "se" in ex:
        cv.poly([(R, 150), (WIDTH - 26, 156), (WIDTH - 30, B), (R, B)], CAVE)
    if "u" in ex and not c.feats & {"grate_above", "pit_bottom", "hole_above"}:
        cv.ellipse(200, max(10, ceil + 6), 22, 7, UMBER_LT)
        cv.ellipse(200, max(10, ceil + 6), 18, 5, CAVE)
    if "d" in ex and not c.feats & {"pit"}:
        cv.ellipse(70, 172, 26, 8, UMBER_LT)
        cv.ellipse(70, 172, 22, 6, CAVE)


# Features -----------------------------------------------------------------

def f_grate_above(cv, c):
    cv.poly([(130, T), (190, T), (220, 162), (100, 162)], cv.glow(SKY_WARM, 0.85))
    cv.poly([(140, T), (180, T), (200, 160), (120, 160)], SKY_WARM, opacity=0.35)
    cv.rect(126, T, 68, 18, SOOT)
    for x in range(130, 192, 8):
        cv.rect(x, 0, 3, 8, SKY if c.g.istate("grate") == "open" else W)


def f_cobbles(cv, c):
    for _ in range(30):
        x = c.rnd.randint(0, WIDTH)
        y = c.rnd.randint(c.fl + 6, HEIGHT - 2)
        r = 2 + (y - c.fl) * 0.06
        cv.ellipse(x, y, r * 1.6, r, FLOOR_LT, stroke=UMBER_DK, stroke_width=0.9)


def f_rubble(cv, c):
    for x, w in ((40, 50), (250, 60), (180, 36)):
        y = c.fl + 8
        cv.poly([(x, y + 20), (x + w * 0.3, y), (x + w * 0.6, y + 6), (x + w, y + 22)], UMBER_DK)
        cv.poly([(x + w * 0.3, y), (x + w * 0.6, y + 6), (x + w * 0.5, y + 14)], UMBER_LT, opacity=0.7)


def f_writing(cv, c):
    txt = c.args.get("writing", "")
    size = 24 if len(txt) < 10 else 17
    cv.text(WIDTH / 2.0, c.ceil + 32, txt, W, size=size, anchor="middle",
            family="Georgia, 'Times New Roman', serif", font_weight="bold", letter_spacing="2")


def f_orange_river(cv, c):
    for i in range(7):
        y = c.ceil + 12 + i * 15
        col = (LAVA, GOLD, BRICK_LT, O)[i % 4]
        cv.path("M%d %d C %d %d %d %d %d %d" % (c.inset, y, 110, y - 14, 210, y + 14, WIDTH - c.inset, y),
                stroke=col, width=7, opacity=0.85)


def f_pit(cv, c):
    cv.ellipse(180, 168, 52, 14, UMBER_LT)
    cv.ellipse(180, 169, 46, 11, CAVE)
    c.figure_x = 90


def f_mist(cv, c):
    rnd = c.rnd
    cv.raw('<g filter="%s">' % cv.soften(2.4))
    for _ in range(8):
        y = rnd.randint(30, 170)
        x = rnd.randint(-30, 200)
        cv.path("M%d %d c 20 -8 40 8 60 0 s 40 -8 60 0" % (x, y), stroke=W, width=round(rnd.uniform(4, 9), 1),
                opacity=round(rnd.uniform(0.25, 0.5), 2))
    cv.raw("</g>")


def f_steps(cv, c):
    for i in range(6):
        x = 232 + i * 9
        y = c.fl - i * 14
        cv.rect(x, y - 12, 34, 12, UMBER_LT, stroke=UMBER_DK, stroke_width=1.2)


def f_fissure(cv, c):
    cv.poly([(150, c.fl), (170, c.fl), (196, B), (126, B)], CAVE)
    cv.path("M150 %d l -4 18 l 6 12 l -8 22" % c.fl, stroke=UMBER_LT, width=1.2)
    if c.g.flag("bridge"):
        cv.path("M108 186 Q 160 120 212 186", stroke=WATER_LT, width=8, opacity=0.85)
        cv.path("M108 186 Q 160 120 212 186", stroke=W, width=3)
        for x in (128, 148, 172, 192):
            cv.line(x, 170 - abs(160 - x) * 0.2, x + 3, 160 - abs(160 - x) * 0.2, W, 1.2)


def f_pillars(cv, c):
    for x in (80, 130, 190, 240):
        paint(cv, c.rnd, [(x - 7, c.ceil + 10), (x + 7, c.ceil + 10), (x + 7, c.fl), (x - 7, c.fl)],
              UMBER_DK, (UMBER_DK, UMBER), n=6, width=(2, 4), angle=90)
        cv.rect(x - 10, c.ceil + 6, 20, 6, UMBER_LT)
        cv.rect(x - 10, c.fl - 6, 20, 6, UMBER_LT)


def f_crystals(cv, c):
    for _ in range(14):
        x = c.rnd.randint(c.inset, WIDTH - c.inset)
        y = c.rnd.randint(c.ceil + 10, c.fl - 10)
        cv.poly([(x, y), (x + 3, y - 9), (x + 6, y)], W, stroke=WATER_LT, stroke_width=0.6)


def f_vault(cv, c):
    for r in (60, 80, 100):
        cv.path("M%d %d Q 160 %d %d %d" % (160 - r, c.fl, c.ceil - r * 0.3, 160 + r, c.fl),
                stroke=UMBER_DK, width=2)


def f_y2(cv, c):
    cv.ellipse(160, 168, 34, 16, GREY_DK)
    cv.ellipse(154, 162, 22, 8, GREY, opacity=0.8)
    cv.text(160, 173, "Y2", W, size=18, anchor="middle", family="Georgia, serif", font_weight="bold")


def f_boulders(cv, c):
    for _ in range(6):
        x = c.rnd.randint(20, 300)
        y = c.rnd.randint(c.fl - 6, 190)
        r = c.rnd.randint(8, 18)
        cv.ellipse(x, y, r * 1.2, r, UMBER_DK)
        cv.ellipse(x - r * 0.3, y - r * 0.3, r * 0.6, r * 0.4, UMBER_LT, opacity=0.7)


def f_window(cv, c):
    cv.rect(110, c.ceil + 20, 100, 70, CAVE)
    cv.rect(110, c.ceil + 60, 100, 30, cv.glow(W, 0.6))
    cv.rect(178, c.ceil + 30, 20, 26, GOLD, opacity=0.8)
    figure(cv, 188, c.ceil + 56, scale=0.5, facing=-1, shadow=False)
    cv.rect(106, c.ceil + 16, 108, 78, "none", stroke=UMBER_LT, stroke_width=3)


def f_scorched(cv, c):
    soft = cv.soften(3)
    for _ in range(5):
        x = c.rnd.randint(c.inset, WIDTH - c.inset - 30)
        y = c.rnd.randint(c.ceil + 10, c.fl - 30)
        cv.ellipse(x, y, 22, 12, SOOT, opacity=0.7, filter=soft)


def f_column(cv, c):
    paint(cv, c.rnd, [(c.inset + 8, c.ceil), (c.inset + 28, c.ceil), (c.inset + 30, c.fl + 30),
                      (c.inset + 6, c.fl + 30)],
          LAVA, (LAVA, GOLD, BRICK_LT, V), n=16, width=(2, 4), length=(8, 20), angle=90)


def f_holes(cv, c):
    for _ in range(26):
        x = c.rnd.randint(4, WIDTH - 4)
        y = c.rnd.randint(c.ceil + 6, c.fl - 4)
        r = c.rnd.randint(2, 6)
        cv.ellipse(x, y, r * 1.3, r, CAVE)


def f_cheese(cv, c):
    for _ in range(18):
        x = c.rnd.randint(4, WIDTH - 4)
        y = c.rnd.randint(c.ceil + 6, c.fl - 4)
        r = c.rnd.randint(3, 11)
        cv.circle(x, y, r, CAVE)
        cv.path("M%d %d a %d %d 0 0 1 %d 0" % (x - r, y, r, r, 2 * r), stroke=UMBER_LT, width=1.2)
    cv.rect(190, c.fl - 30, 70, 40, UMBER_DK, stroke=CAVE, stroke_width=1)


def f_curtains(cv, c):
    for x in range(c.inset, WIDTH - c.inset, 12):
        cv.rect(x, c.ceil, 7, c.fl - c.ceil, V)
        cv.rect(x + 7, c.ceil, 5, c.fl - c.ceil, BRICK_DK)
    paint(cv, c.rnd, [(c.inset, c.fl), (WIDTH - c.inset, c.fl), (R, B), (L, B)], BRICK, (BRICK, V, BRICK_LT),
          n=40, width=(3, 6), length=(10, 30))
    paint(cv, c.rnd, [(L, T), (R, T), (R, c.ceil + 4), (L, c.ceil + 4)], GREEN_DK, (GREEN_DK, GREEN),
          n=24, width=(3, 6))


def f_drawings(cv, c):
    y = c.ceil + 40
    for i, x in enumerate(range(c.inset + 20, WIDTH - c.inset - 20, 34)):
        col = V if i % 2 else SOOT
        if i % 3 == 2:
            cv.path("M%d %d l 10 -6 l 10 6 m -16 0 v 8 m 12 -8 v 8 m 2 -14 l 6 -8" % (x, y), stroke=col, width=1.6)
        else:
            cv.circle(x + 6, y - 10, 3, col)
            cv.path("M%d %d v 10 m -6 -6 h 12 m -6 6 l -5 8 m 5 -8 l 5 8" % (x + 6, y - 7), stroke=col, width=1.6)


def f_rim(cv, c):
    cv.poly([(L, 130), (R, 120), (R, B), (L, B)], CAVE)
    cv.rect(L, 140, R - L, 70, cv.glow(W, 0.45))
    paint(cv, c.rnd, [(L, 150), (R, 140), (R, 160), (L, 172)], FLOOR, (FLOOR, FLOOR_LT), n=20)
    c.floor = 168


def f_glow(cv, c):
    cv.ellipse(160, 110, 110, 70, cv.glow(GREEN_LT, 0.7))
    cv.ellipse(160, 110, 40, 24, cv.glow(W, 0.6))


def f_tablet(cv, c):
    cv.rect(130, c.ceil + 12, 60, 40, GREY, stroke=SOOT, stroke_width=1.5)
    for i in range(4):
        cv.line(138, c.ceil + 22 + i * 8, 182, c.ceil + 22 + i * 8, SOOT, 1)


def f_rope(cv, c):
    x = 248
    cv.path("M%d -10 q 4 80 0 170" % x, stroke=UMBER_LT, width=2.2)
    for y in range(20, 160, 18):
        cv.circle(x + 1, y, 2.4, UMBER_LT)


def f_pit_bottom(cv, c):
    cv.ellipse(160, 10, 70, 14, cv.glow(SKY, 0.7))
    cv.ellipse(160, 10, 70, 14, "none", stroke=UMBER_LT, stroke_width=1)


def f_oil_pool(cv, c):
    cv.ellipse(250, 176, 40, 9, SOOT)
    cv.path("M226 175 q 12 -3 24 0", stroke=GOLD, width=1.2)


def f_hole_above(cv, c):
    cv.ellipse(110, max(12, c.ceil + 6), 26, 8, UMBER_LT)
    cv.ellipse(110, max(12, c.ceil + 6), 22, 6, CAVE)


def f_leaves(cv, c):
    for _ in range(12):
        x = 60 + c.rnd.randint(-24, 24)
        y = 170 + c.rnd.randint(-14, 8)
        cv.ellipse(x, y, 7, 3.5, c.rnd.choice((GREEN, GREEN_DK, GREEN_LT)),
                   transform="rotate(%d %d %d)" % (c.rnd.randint(-40, 40), x, y))


def f_door_n(cv, c):
    x, w, top = 120, 80, c.ceil + 20
    if c.g.istate("door") == "oiled":
        cv.rect(x, top, w, c.fl - top, CAVE)
        cv.poly([(x + w, top), (x + w + 26, top + 10), (x + w + 26, c.fl + 8), (x + w, c.fl)], BRICK_DK)
    else:
        paint(cv, c.rnd, [(x, top), (x + w, top), (x + w, c.fl), (x, c.fl)], BRICK_DK,
              (BRICK_DK, BRICK, LAVA, SOOT), n=30, width=(2, 4), length=(4, 12), spread=90)
        cv.rect(x, top, w, c.fl - top, "none", stroke=SOOT, stroke_width=3)
        for yy in range(int(top) + 10, int(c.fl), 18):
            for xx in (x + 8, x + w - 8):
                cv.circle(xx, yy, 2, UMBER_LT)


def f_waterfall(cv, c):
    paint(cv, c.rnd, [(180, T), (220, T), (222, c.fl + 10), (178, c.fl + 10)], WATER_LT,
          (W, WATER_LT, WATER), n=40, width=(1.5, 3.5), length=(14, 34), angle=90, spread=3)
    cv.ellipse(200, c.fl + 22, 60, 14, WATER)
    cv.path("M160 %d a 40 9 0 1 1 80 0 a 30 6 0 1 1 -60 0 a 20 4 0 1 1 40 0" % (c.fl + 22),
            stroke=WATER_LT, width=1.4)


def f_incline(cv, c):
    paint(cv, c.rnd, [(L, 150), (R, 120), (R, B), (L, B)], UMBER, (UMBER, UMBER_DK, FLOOR), n=30, angle=-6)
    cv.line(L, 150, R, 120, CAVE, 2)


def f_slab(cv, c):
    paint(cv, c.rnd, [(30, 170), (150, 140), (300, 158), (190, 196)], GREY_DK, (GREY_DK, GREY, UMBER_DK),
          n=24, angle=-10)


def f_mirror(cv, c):
    cv.line(150, T, 140, 30, SOOT, 1)
    cv.line(170, T, 180, 30, SOOT, 1)
    paint(cv, c.rnd, [(120, 30), (200, 30), (200, 64), (120, 64)], SKY_COOL, (W, SKY_COOL, WATER_LT),
          n=14, width=(2, 4))
    cv.rect(120, 30, 80, 34, "none", stroke=GOLD, stroke_width=2)
    figure(cv, 160, 60, scale=0.4, lamp=True, shadow=False)


def f_lake(cv, c):
    paint(cv, c.rnd, [(L, 150), (R, 136), (R, B), (L, B)], WATER, (WATER, WATER_DK, WATER_LT),
          n=50, width=(1.5, 4), length=(14, 40), spread=3)
    paint(cv, c.rnd, [(L, 186), (110, 178), (130, B), (L, B)], FLOOR, (FLOOR, FLOOR_LT), n=10)
    c.floor = 194
    c.figure_x = 60


def f_shells(cv, c):
    for _ in range(16):
        x = c.rnd.randint(c.inset, WIDTH - c.inset)
        y = c.rnd.randint(c.ceil + 8, c.fl - 8)
        cv.path("M%d %d a 4 4 0 1 1 4 4 a 2 2 0 1 1 -2 -2" % (x, y), stroke=LIMESTONE, width=1.2)


def f_maze(cv, c):
    for x in (90, 230):
        cv.path("M%d %d c -12 20 12 40 0 70" % (x, c.ceil), stroke=CAVE, width=7)


def f_chasm(cv, c):
    flip = c.rid != "chasm_sw"           # on the far side the chasm is to the west

    def fx(x):
        return WIDTH - x if flip else x
    cv.poly([(fx(140), T), (fx(R), T), (fx(R), B), (fx(170), B)], CAVE)
    cv.poly([(fx(140), 40), (fx(R), 30), (fx(R), 120), (fx(150), 130)], cv.glow(W, 0.5))
    x0, y0 = 150, 170
    cv.line(fx(x0), y0 - 18, fx(300), 70, SOOT, 1.5)
    cv.line(fx(x0), y0, fx(300), 80, SOOT, 1.5)
    for i in range(12):
        t = i / 12.0
        x = x0 + (300 - x0) * t
        y = y0 + (78 - y0) * t
        cv.line(fx(x), y, fx(x - 4 + 4 * t), y - 14 + 6 * t, UMBER_LT, round(3 - 2 * t, 2))
    c.figure_x = 70 if not flip else 250


def f_warm(cv, c):
    cv.rect(c.inset, c.ceil + 20, WIDTH - 2 * c.inset, 60, cv.glow(LAVA, 0.6))


def f_sign(cv, c):
    cv.rect(128, c.ceil + 6, 64, 24, UMBER_LT, stroke=SOOT, stroke_width=1.5)
    cv.text(160, c.ceil + 24, "BEAR!", V, size=14, anchor="middle", family="Georgia, serif", font_weight="bold")


def f_dust(cv, c):
    strokes(cv, c.rnd, (0, c.fl + 4, WIDTH, HEIGHT), (GROUND, SKY_WARM), 20, width=(1, 2), length=(3, 8))


def f_digging(cv, c):
    cv.poly([(220, 186), (250, 160), (290, 186)], UMBER_DK)
    cv.line(60, 150, 90, 186, SOOT, 2.2)
    cv.path("M52 152 q 10 -10 20 0", stroke=GREY, width=2.2)


def f_tunnel_w(cv, c):
    cv.ellipse(c.inset * 0.5, c.fl - 8, 8, 6, CAVE)


def f_long_hall(cv, c):
    paint(cv, c.rnd, [(L, B), (150, 110), (170, 110), (R, B)], FLOOR, (FLOOR, FLOOR_LT, UMBER), n=24,
          angle=90, spread=40)
    cv.rect(150, 90, 20, 20, CAVE)


def f_canyon(cv, c):
    cv.path("M%d -10 L %d %d" % (c.inset - 20, c.inset, c.fl), stroke=UMBER_LT, width=1.2, opacity=0.6)
    cv.path("M%d -10 L %d %d" % (WIDTH - c.inset + 20, WIDTH - c.inset, c.fl), stroke=UMBER_LT, width=1.2,
            opacity=0.6)


def f_limestone(cv, c):
    for _ in range(10):
        x = c.rnd.randint(c.inset, WIDTH - c.inset)
        y = c.rnd.randint(c.ceil + 8, c.fl - 8)
        cv.path("M%d %d a 3 3 0 1 1 3 3" % (x, y), stroke=UMBER_DK, width=0.9)


FEATURES = {name[2:]: fn for name, fn in list(globals().items()) if name.startswith("f_")}


# ----------------------------------------------------------------------------
# Things lying about
# ----------------------------------------------------------------------------

def p_lamp(cv, x, y, g):
    if g.istate("lamp") == "on" and g.state["lamp"] > 0:
        cv.circle(x, y - 6, 16, cv.glow(GOLD, 0.6))
    cv.rect(x - 4, y - 10, 8, 10, O, stroke=SOOT, stroke_width=0.8)
    cv.rect(x - 2, y - 8, 4, 5, W)
    cv.path("M%g %g q 4 -6 8 0" % (x - 4, y - 10), stroke=SOOT, width=1)


def p_keys(cv, x, y, g):
    cv.circle(x, y - 5, 4, "none", stroke=GOLD, stroke_width=1.6)
    cv.line(x + 3, y - 3, x + 10, y, GOLD, 1.6)
    cv.line(x - 3, y - 3, x - 8, y, GOLD, 1.6)


def p_food(cv, x, y, g):
    cv.rect(x - 7, y - 7, 14, 7, W, stroke=SOOT, stroke_width=0.8)
    cv.line(x, y - 7, x, y, V, 1.2)


def p_bottle(cv, x, y, g):
    st = g.istate("bottle")
    cv.rect(x - 4, y - 12, 8, 12, SKY_COOL, stroke=SOOT, stroke_width=0.8)
    cv.rect(x - 2, y - 16, 4, 4, SKY_COOL, stroke=SOOT, stroke_width=0.8)
    if st != "empty":
        cv.rect(x - 3, y - 8, 6, 7, WATER if st == "water" else SOOT)


def p_cage(cv, x, y, g):
    if g.loc("bird") == "in:cage":
        p_birdie(cv, x, y - 4)
    cv.path("M%g %g v -10 q 9 -10 18 0 v 10 z" % (x - 9, y), stroke=GOLD, width=1.2)
    for dx in (-4, 0, 4):
        cv.line(x + dx, y, x + dx, y - 14, GOLD, 0.8)


def p_birdie(cv, x, y):
    cv.ellipse(x, y - 3, 4, 3, BEAR)
    cv.circle(x + 3, y - 6, 2, BEAR)
    cv.ellipse(x + 1, y - 2, 2.2, 1.7, V)
    cv.poly([(x + 5, y - 6), (x + 8, y - 5.5), (x + 5, y - 5)], O)


def p_bird(cv, x, y, g):
    if g.loc("bird") == "in:cage":
        return
    cv.line(x - 10, y - 14, x + 12, y - 14, BEAR, 1.5)
    p_birdie(cv, x, y - 14)


def p_rod(cv, x, y, g):
    cv.line(x - 14, y - 2, x + 12, y - 6, K, 2)
    cv.poly([(x + 12, y - 11), (x + 14, y - 7), (x + 18, y - 6), (x + 14, y - 5),
             (x + 12, y - 1), (x + 10, y - 5), (x + 6, y - 6), (x + 10, y - 7)], EMBER)


def p_dynamite(cv, x, y, g):
    cv.line(x - 14, y - 2, x + 12, y - 6, K, 2.5)
    for dx in (4, 8, 12):
        cv.line(x + dx, y - 9, x + dx, y - 1, EMBER, 1.5)


def p_nugget(cv, x, y, g):
    cv.poly([(x - 8, y), (x - 6, y - 7), (x, y - 10), (x + 7, y - 6), (x + 8, y)], O,
            stroke=UMBER_DK, stroke_width=0.8)
    cv.rect(x - 2, y - 7, 2, 2, W)


def p_diamonds(cv, x, y, g):
    for dx in (-6, 0, 6):
        cv.poly([(x + dx, y - 9), (x + dx + 3, y - 4), (x + dx, y), (x + dx - 3, y - 4)], W,
                stroke=WATER_LT, stroke_width=0.8)


def p_silver(cv, x, y, g):
    for dx, dy in ((-8, 0), (0, 0), (-4, -5)):
        cv.rect(x + dx, y + dy - 5, 9, 5, SKY_COOL, stroke=GREY_DK, stroke_width=0.8)


def p_jewelry(cv, x, y, g):
    cv.path("M%g %g q 9 12 18 0" % (x - 9, y - 10), stroke=GOLD, width=1.5)
    for dx in (-6, 0, 6):
        cv.circle(x + dx, y - 4 + abs(dx) * -0.3, 2, V)


def p_coins(cv, x, y, g):
    for i in range(4):
        cv.ellipse(x - 4 + (i % 2) * 7, y - 2 - i * 2, 4, 1.8, GOLD, stroke=UMBER_DK, stroke_width=0.6)


def p_chest(cv, x, y, g):
    cv.rect(x - 11, y - 12, 22, 12, BRICK, stroke=SOOT, stroke_width=1)
    cv.path("M%g %g q 11 -8 22 0" % (x - 11, y - 12), fill=BRICK, stroke=SOOT, width=1)
    cv.line(x - 11, y - 6, x + 11, y - 6, GOLD, 1.5)
    cv.rect(x - 2, y - 9, 4, 4, GOLD)


def p_eggs(cv, x, y, g):
    cv.ellipse(x, y - 3, 13, 4, UMBER_DK)
    for dx in (-6, 0, 6):
        cv.ellipse(x + dx, y - 6, 3.5, 4.5, GOLD, stroke=UMBER_DK, stroke_width=0.6)


def p_trident(cv, x, y, g):
    cv.line(x - 10, y, x + 10, y - 18, GOLD, 2)
    cv.path("M%g %g l 4 -4 m -4 4 l 6 1 m -6 -1 l 1 -6" % (x + 10, y - 18), stroke=GOLD, width=1.5)
    cv.circle(x + 4, y - 12, 1.6, V)


def p_vase(cv, x, y, g):
    if g.broken("vase"):
        for dx in (-8, -2, 5):
            cv.poly([(x + dx, y), (x + dx + 3, y - 3), (x + dx + 5, y)], WATER)
        return
    cv.path("M%g %g q -8 -8 -2 -16 h 4 q 6 8 -2 16 z" % (x - 1, y), fill=W, stroke=P, width=1.5)
    cv.line(x - 5, y - 9, x + 5, y - 9, P, 1.5)


def p_emerald(cv, x, y, g):
    cv.ellipse(x, y - 6, 9, 8, cv.glow(GREEN_LT, 0.8))
    cv.ellipse(x, y - 6, 5, 4.5, GREEN)
    cv.rect(x - 2, y - 9, 2, 2, W)


def p_pyramid(cv, x, y, g):
    cv.poly([(x - 9, y), (x, y - 14), (x + 9, y)], SKY_COOL, stroke=GREY_DK, stroke_width=0.8)
    cv.poly([(x, y - 14), (x + 9, y), (x + 3, y)], GREY)


def p_pearl(cv, x, y, g):
    cv.circle(x, y - 4, 4, W, stroke=GREY, stroke_width=0.8)


def p_rug(cv, x, y, g):
    cv.poly([(x - 22, y), (x + 22, y), (x + 16, y - 10), (x - 16, y - 10)], V, stroke=GOLD, stroke_width=1.5)
    cv.poly([(x - 8, y - 2), (x + 8, y - 2), (x + 5, y - 8), (x - 5, y - 8)], P)


def p_spices(cv, x, y, g):
    cv.rect(x - 9, y - 9, 7, 9, BRICK, stroke=SOOT, stroke_width=0.6)
    cv.rect(x + 1, y - 7, 7, 7, O, stroke=SOOT, stroke_width=0.6)


def p_chain(cv, x, y, g):
    if g.istate("chain") == "locked":
        return
    for i in range(5):
        cv.ellipse(x - 10 + i * 5, y - 3, 3, 2, "none", stroke=GOLD, stroke_width=1.3)


def p_pillow(cv, x, y, g):
    cv.ellipse(x, y - 4, 11, 4.5, V, stroke=BRICK_DK, stroke_width=0.8)


def p_magazine(cv, x, y, g):
    cv.rect(x - 6, y - 10, 12, 10, W, stroke=SOOT, stroke_width=0.8)
    cv.rect(x - 6, y - 10, 12, 3, V)


def p_axe(cv, x, y, g):
    cv.line(x - 8, y, x + 6, y - 12, UMBER_DK, 1.6)
    cv.poly([(x + 3, y - 14), (x + 10, y - 13), (x + 7, y - 8)], GREY, stroke=SOOT, stroke_width=0.6)


def p_batteries(cv, x, y, g):
    for dx in (-5, 1):
        cv.rect(x + dx, y - 9, 5, 9, V if g.istate("batteries") == "fresh" else GREY_DK,
                stroke=SOOT, stroke_width=0.6)


SMALL = {name[2:]: fn for name, fn in list(globals().items()) if name.startswith("p_") and name != "p_birdie"}


# Creatures and fixtures ------------------------------------------------------

def big_snake(cv, c):
    body = "M70 186 C 110 160 140 200 180 176 S 240 160 262 178"
    cv.path(body, stroke=GREEN_DK, width=12)
    cv.path(body, stroke=GREEN, width=8)
    cv.path("M76 182 C 110 160 140 196 180 172", stroke=GREEN_LT, width=1.5, stroke_dasharray="3 5")
    cv.ellipse(266, 176, 10, 7, GREEN, stroke=GREEN_DK, stroke_width=1.5)
    cv.circle(270, 173, 1.6, V)
    cv.path("M276 178 l 8 -2 m -8 2 l 8 3", stroke=V, width=1.2)
    c.figure_x = 46


def big_dragon(cv, c):
    p_rug(cv, 196, 186, c.g)
    if c.g.istate("dragon") == "dead":
        cv.ellipse(210, 186, 70, 12, GREEN_DK)
        cv.path("M150 186 l -20 4 l -6 -6", stroke=GREEN_DK, width=4)
        cv.path("M262 182 l 4 -3 m -4 0 l 4 3", stroke=W, width=1.2)
        return
    cv.ellipse(206, 168, 62, 20, GREEN, stroke=GREEN_DK, stroke_width=1.5)
    cv.poly([(170, 152), (200, 100), (214, 150)], GREEN_DK)
    cv.poly([(214, 150), (250, 96), (246, 152)], SOOT)
    cv.path("M262 160 Q 286 130 272 116", stroke=GREEN, width=12)
    cv.ellipse(266, 112, 14, 9, GREEN, stroke=GREEN_DK, stroke_width=1.5)
    cv.circle(262, 108, 2, V)
    for i in range(5):
        cv.poly([(170 + i * 16, 150 - (i % 2) * 2), (176 + i * 16, 140), (182 + i * 16, 150)], V)
    cv.ellipse(232, 118, 24, 12, cv.glow(LAVA, 0.7))
    cv.path("M252 116 q -14 -2 -22 6 q -6 -12 -18 -8", stroke=V, width=3)
    cv.path("M150 172 q -30 10 -40 -6", stroke=GREEN, width=6)
    c.figure_x = 70


def big_troll(cv, c):
    x = 128
    cv.ellipse(x, 150, 18, 26, TROLL, stroke=SOOT, stroke_width=1.5)
    cv.circle(x, 116, 12, TROLL, stroke=SOOT, stroke_width=1.5)
    cv.circle(x - 4, 114, 2, K)
    cv.circle(x + 4, 114, 2, K)
    cv.path("M%d 122 q 4 3 8 0" % (x - 4), stroke=K, width=1.2)
    cv.line(x - 8, 174, x - 10, 188, SOOT, 4)
    cv.line(x + 8, 174, x + 10, 188, SOOT, 4)
    cv.line(x + 16, 140, x + 30, 128, TROLL, 3)
    c.figure_x = 50


def big_bear(cv, c):
    st = c.g.istate("bear")
    x = 230 if st in ("chained", "fed") else 200
    cv.ellipse(x, 160, 34, 22, BEAR)
    cv.circle(x - 30, 142, 13, BEAR)
    cv.circle(x - 38, 132, 4, BEAR)
    cv.circle(x - 24, 130, 4, BEAR)
    cv.ellipse(x - 38, 146, 5, 4, UMBER_LT)
    cv.circle(x - 33, 140, 1.5, W if st != "chained" else V)
    for dx in (-22, -4, 14, 26):
        cv.rect(x + dx, 172, 7, 14, BEAR)
    if st in ("chained", "fed"):
        cv.path("M%d 150 Q %d 130 %d 120" % (x - 18, x + 30, WIDTH - c.inset), stroke=GOLD, width=2,
                stroke_dasharray="3 2")
    c.figure_x = 70


def big_plant(cv, c, x=150):
    if c.rid != "west_pit":
        return
    stage = c.g.istate("plant")
    top = {0: 160, 1: 70, 2: -10}[stage]
    cv.path("M%d 190 C %d %d %d %d %d %d" % (x, x - 20, (190 + top) / 2, x + 20, (190 + top) / 2 - 20, x, top),
            stroke=GREEN_DK, width=3 + 3 * stage)
    for i in range(3 + stage * 6):
        y = 186 - i * (186 - top) / float(3 + stage * 6)
        d = -1 if i % 2 else 1
        cv.ellipse(x + d * (8 + stage * 2), round(y, 1), 7 + stage, 3 + stage * 0.6, (GREEN, GREEN_LT)[i % 2],
                   transform="rotate(%d %d %d)" % (d * 25, x + d * 8, y))
    c.figure_x = 70


def big_clam(cv, c):
    x, y = 200, 182
    if c.g.istate("clam") == "open":
        cv.path("M%d %d q 34 -40 68 0 z" % (x - 34, y - 6), fill=LIMESTONE, stroke=GREY_DK, width=1.5)
        cv.path("M%d %d q 34 14 68 0 z" % (x - 34, y - 6), fill=LIMESTONE, stroke=GREY_DK, width=1.5)
        cv.ellipse(x, y - 8, 24, 5, SOOT)
    else:
        cv.path("M%d %d q 34 -44 68 0 q -34 12 -68 0 z" % (x - 34, y - 4), fill=LIMESTONE,
                stroke=GREY_DK, width=1.5)
        for dx in (-20, -8, 4, 16):
            cv.line(x + dx * 0.4, y - 26, x + dx, y - 6, GREY, 1)


def big_machine(cv, c):
    x = 214
    cv.rect(x, 96, 56, 86, V, stroke=SOOT, stroke_width=2)
    cv.rect(x + 46, 96, 10, 86, BRICK_DK, opacity=0.7)
    cv.rect(x + 8, 106, 36, 26, W, stroke=SOOT, stroke_width=1)
    for i in range(3):
        cv.line(x + 12, 112 + i * 7, x + 40, 112 + i * 7, P, 1.5)
    cv.rect(x + 34, 140, 10, 4, SOOT)
    cv.rect(x + 8, 160, 36, 12, SOOT)


def dwarf(cv, c):
    x, y = 250, c.floor
    cv.poly([(x - 8, y - 4), (x + 8, y - 4), (x + 5, y - 20), (x - 5, y - 20)], COAT)
    cv.circle(x, y - 24, 5, FLESH)
    cv.poly([(x - 6, y - 26), (x + 6, y - 26), (x + 2, y - 40)], V)
    cv.poly([(x - 4, y - 22), (x + 4, y - 22), (x, y - 12)], W)
    cv.line(x - 4, y - 4, x - 5, y, K, 2)
    cv.line(x + 4, y - 4, x + 5, y, K, 2)
    cv.line(x - 8, y - 16, x - 16, y - 26, UMBER_DK, 1.6)
    cv.poly([(x - 18, y - 28), (x - 12, y - 30), (x - 14, y - 24)], GREY)


BIG = {"snake": big_snake, "dragon": big_dragon, "troll": big_troll,
       "bear": big_bear, "plant": big_plant, "clam": big_clam,
       "machine": big_machine}


def things(cv, c):
    g = c.g
    small = []
    for iid in g.room_ids():
        if iid in ("grate", "door"):
            continue
        if iid in BIG:
            BIG[iid](cv, c)
        elif iid in SMALL:
            if iid == "rug" and g.at_room("dragon"):
                continue
            small.append(iid)
    scale = 1.0 if c.inside else 1.5
    for i, iid in enumerate(small[:len(c.slots)]):
        x = c.slots[i]
        y = c.slot_y[i] if c.slot_y else c.floor + (4 if i % 2 else -2)
        cv.raw('<g transform="translate(%g %g) scale(%g) translate(%g %g)">' % (x, y, scale, -x, -y))
        SMALL[iid](cv, x, y, g)
        cv.raw("</g>")
    if g.state["dwarf"]["here"] == c.rid:
        dwarf(cv, c)


# ----------------------------------------------------------------------------
# Putting it together
# ----------------------------------------------------------------------------

def dark_scene():
    cv = Svg(prefix="sc")
    rnd = random.Random("dark")
    cv.raw('<g filter="%s">' % cv.oil(3))
    cv.rect(L, T, R - L, B - T, CAVE)
    strokes(cv, rnd, (L, T, R, B), (CAVE, SOOT, UMBER_DK), 60, width=(4, 9), length=(20, 60), spread=40)
    cv.circle(150, 96, 1.8, GOLD)
    cv.circle(163, 96, 1.8, GOLD)
    cv.raw("</g>")
    cv.text(WIDTH / 2.0, 152, "IT IS PITCH DARK", UMBER_LT, size=13, anchor="middle")
    return cv.render()


def scene_svg(g):
    if not g.lit():
        return dark_scene()
    c = Ctx(g)
    cv = Svg(prefix="sc")
    seed = sum(ord(ch) for ch in c.rid) % 97 + 1
    cv.raw('<g filter="%s">' % cv.oil(seed))
    template = c.room["scene"]
    if template in SURFACE:
        SURFACE[template](cv, c)
    else:
        cave(cv, c)
        for f in c.room["feats"]:
            name = f.split(":")[0]
            fn = FEATURES.get(name)
            if fn and name not in ("low", "vast", "tall"):
                fn(cv, c)
    things(cv, c)
    lamp = g.carried("lamp") and g.lamp_on()
    if lamp and template not in SURFACE:
        cv.ellipse(c.figure_x + 8, c.floor - 14, 90, 70, cv.glow(SKY_WARM, 0.22))
    figure(cv, c.figure_x, c.floor, scale=1.15, lamp=lamp)
    cv.raw("</g>")
    return cv.render()
