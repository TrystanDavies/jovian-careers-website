"""The auto-map: drawn as you explore, one sheet per region.

Only rooms you have visited appear. Exits you've seen but not taken are
short dashed stubs; passages leading to another region end in a labelled
stub; up and down are shown as little triangles on the room's box.
"""

from .art import K, O, P, V, W, Svg
from .world import DIR_NAMES, DIRECTIONS, HIDDEN_GATES, REGION_NAMES, ROOMS, VECTORS

CELL_W, CELL_H = 114, 62
BOX_W, BOX_H = 102, 30
MARGIN = 50


def _known(g, region):
    visited = [r for r in g.state["visited"] if r in ROOMS and ROOMS[r]["region"] == region]
    return visited


def _exits(g, rid):
    for d in DIRECTIONS:
        ex = ROOMS[rid]["exits"].get(d)
        if not ex:
            continue
        target, gate = ex
        if gate in HIDDEN_GATES and not g.gate(gate, target, rid=rid)[0]:
            continue
        open_ = True
        if gate and gate != "dragon":
            open_ = g.gate(gate, target, rid=rid)[0]
        elif gate == "dragon":
            open_ = g.istate("dragon") == "dead"
        yield d, target, open_


def _center(r, x0, y0):
    return (MARGIN + (r["x"] - x0) * CELL_W + BOX_W / 2.0,
            MARGIN + (r["y"] - y0) * CELL_H + BOX_H / 2.0)


def _edge(cx, cy, dx, dy):
    """Where a line from a box centre heading (dx, dy) leaves the box."""
    if dx == 0 and dy == 0:
        return cx, cy
    tx = (BOX_W / 2.0) / abs(dx) if dx else float("inf")
    ty = (BOX_H / 2.0) / abs(dy) if dy else float("inf")
    t = min(tx, ty)
    return cx + dx * t, cy + dy * t


def _treasure_rooms(g):
    rooms = set()
    for iid, where in g.state["seen"].items():
        if g.state["items"][iid]["loc"] == where and where != "building":
            from .world import ITEMS
            if ITEMS[iid]["treasure"] and not g.broken(iid):
                rooms.add(where)
    return rooms


def region_svg(g, region):
    rooms = _known(g, region)
    cv = Svg(prefix="mp", extra='class="automap"')
    if not rooms:
        cv.width, cv.height = 300, 160
        cv.rect(0, 0, 300, 160, W)
        return cv.render()
    xs = [ROOMS[r]["x"] for r in rooms]
    ys = [ROOMS[r]["y"] for r in rooms]
    x0, y0 = min(xs), min(ys)
    cols = max(xs) - x0 + 1
    rows = max(ys) - y0 + 1
    cols, rows = max(cols, 3), max(rows, 2)
    width = MARGIN * 2 + (cols - 1) * CELL_W + BOX_W
    height = MARGIN * 2 + (rows - 1) * CELL_H + BOX_H
    cv.width, cv.height = width, height
    cv.rect(0, 0, width, height, W)
    for i in range(cols):
        for j in range(rows):
            cv.rect(MARGIN + i * CELL_W + BOX_W / 2.0, MARGIN + j * CELL_H + BOX_H / 2.0, 1.5, 1.5, P)

    here = g.state["room"]
    visited = set(g.state["visited"])
    treasure_rooms = _treasure_rooms(g)
    drawn = set()
    stubs = []
    markers = []

    for rid in rooms:
        r = ROOMS[rid]
        cx, cy = _center(r, x0, y0)
        for d, target, open_ in _exits(g, rid):
            t = ROOMS[target]
            dash = None if open_ else "4 3"
            if d in ("u", "d"):
                markers.append((rid, d))
            if t["region"] != region:
                vx, vy = VECTORS.get(d, (0, -1) if d == "u" else (0, 1))
                if d in ("u", "d"):
                    vx, vy = (0.9, -1) if d == "u" else (0.9, 1)
                sx, sy = _edge(cx, cy, vx, vy)
                ex, ey = sx + vx * 16, sy + vy * 16
                cv.line(sx, sy, ex, ey, P, 1.6)
                cv.circle(ex, ey, 2.6, P)
                label = REGION_NAMES[t["region"]]
                anchor = "start" if vx > 0 else ("end" if vx < 0 else "middle")
                ly = ey + (12 if vy > 0 else -5 if vy < 0 else 4)
                lx = ex + (4 if vx > 0 else -4 if vx < 0 else 0)
                stubs.append('<g class="portal" data-region="%s">' % t["region"])
                stubs.append('<text x="%.1f" y="%.1f" fill="%s" font-size="15" text-anchor="%s" '
                             'font-family="\'VT323\', monospace">%s</text></g>' % (lx, ly, P, anchor, label))
                continue
            if target not in visited:
                vx, vy = VECTORS.get(d, (0.0, 0.0))
                if d in ("u", "d"):
                    tx, ty = _center(t, x0, y0)
                    vx, vy = (tx - cx), (ty - cy)
                    n = max(abs(vx), abs(vy)) or 1
                    vx, vy = vx / n, vy / n
                sx, sy = _edge(cx, cy, vx, vy)
                cv.line(sx, sy, sx + vx * 16, sy + vy * 16, K, 1.4, stroke_dasharray="3 2")
                continue
            key = tuple(sorted((rid, target)))
            if key in drawn:
                continue
            drawn.add(key)
            tx, ty = _center(t, x0, y0)
            dx, dy = tx - cx, ty - cy
            sx, sy = _edge(cx, cy, dx, dy)
            ex, ey = _edge(tx, ty, -dx, -dy)
            cv.line(sx, sy, ex, ey, K, 2, stroke_dasharray=dash)

    for rid in rooms:
        r = ROOMS[rid]
        cx, cy = _center(r, x0, y0)
        fill, ink = W, K
        if rid == here:
            fill, ink = V, W
        elif rid in treasure_rooms:
            fill, ink = O, K
        bx, by = cx - BOX_W / 2.0, cy - BOX_H / 2.0
        cv.raw('<g class="room" data-room="%s" data-label="%s"><title>%s</title>' % (
            rid, r["label"].replace('"', "'"), r["name"].replace("&", "and")))
        cv.rect(bx, by, BOX_W, BOX_H, fill, stroke=K, stroke_width=1.6)
        label = r["label"] if len(r["label"]) <= 13 else r["label"][:12] + "."
        cv.text(cx, cy + 5, label, ink, size=17, anchor="middle")
        cv.raw("</g>")
    for rid, d in markers:
        cx, cy = _center(ROOMS[rid], x0, y0)
        bx, by = cx + BOX_W / 2.0 - 7, cy - BOX_H / 2.0
        col = W if rid == here else P
        if d == "u":
            cv.poly([(bx - 4, by + 8), (bx + 4, by + 8), (bx, by + 2)], col)
        else:
            cv.poly([(bx - 4, by + BOX_H - 8), (bx + 4, by + BOX_H - 8), (bx, by + BOX_H - 2)], col)
    for s in stubs:
        cv.raw(s)
    return cv.render()


# ----------------------------------------------------------------------------
# ASCII version for the terminal and the MAP command
# ----------------------------------------------------------------------------

AW = 15     # characters per cell
BOXW = 13   # "[label....^v]"


def ascii_map(g, region):
    rooms = _known(g, region)
    if not rooms:
        return "(nothing mapped here yet)"
    xs = [ROOMS[r]["x"] for r in rooms]
    ys = [ROOMS[r]["y"] for r in rooms]
    x0, y0 = min(xs), min(ys)
    cols = max(xs) - x0 + 1
    rows = max(ys) - y0 + 1
    grid = [[" "] * (cols * AW) for _ in range(rows * 2)]
    visited = set(g.state["visited"])
    here = g.state["room"]
    portals = []

    def put(row, col, ch):
        if 0 <= row < len(grid) and 0 <= col < len(grid[0]) and grid[row][col] == " ":
            grid[row][col] = ch

    for rid in rooms:
        r = ROOMS[rid]
        cx, cy = r["x"] - x0, r["y"] - y0
        for d, target, open_ in _exits(g, rid):
            t = ROOMS[target]
            if t["region"] != region:
                portals.append("%s: %s to %s" % (r["label"], DIR_NAMES[d], REGION_NAMES[t["region"]]))
                continue
            if target not in visited:
                continue
            tx, ty = t["x"] - x0, t["y"] - y0
            dx, dy = tx - cx, ty - cy
            ch_h = "-" if open_ else "."
            ch_v = "|" if open_ else ":"
            if dy == 0 and dx > 0:
                for col in range(cx * AW + BOXW, tx * AW):
                    put(cy * 2, col, ch_h)
            elif dx == 0 and dy > 0:
                for row in range(cy * 2 + 1, ty * 2):
                    put(row, cx * AW + BOXW // 2, ch_v)
            elif abs(dx) == abs(dy) and dy > 0:
                step = 1 if dx > 0 else -1
                for i in range(abs(dy)):
                    col = (cx + i * step) * AW + (BOXW + 1 if step > 0 else -2)
                    put((cy + i) * 2 + 1, col, "\\" if step > 0 else "/")

    for rid in rooms:
        r = ROOMS[rid]
        cx, cy = r["x"] - x0, r["y"] - y0
        dirs = [d for d, _t, _o in _exits(g, rid)]
        marks = ("^" if "u" in dirs else " ") + ("v" if "d" in dirs else " ")
        label = r["label"][:9].ljust(9)
        box = ("<%s%s>" if rid == here else "[%s%s]") % (label, marks)
        for i, ch in enumerate(box):
            grid[cy * 2][cx * AW + i] = ch

    lines = ["".join(row).rstrip() for row in grid]
    while lines and not lines[-1]:
        lines.pop()
    out = ["MAP: %s   (<you are here>  ^ up  v down)" % REGION_NAMES[region]]
    out.extend(lines)
    if portals:
        out.append("Ways to other regions: " + "; ".join(sorted(set(portals))) + ".")
    return "\n".join(out)
