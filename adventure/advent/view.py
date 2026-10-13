"""Everything the windows need to draw themselves after a command."""

from .art import scene_svg
from .mapview import region_svg
from .world import DIR_NAMES, ITEMS, REGION_NAMES, ROOMS, TREASURE_ORDER


def build_view(g):
    s = g.state
    r = g.room
    lit = g.lit()

    exits = []
    for d in g.exit_dirs(for_dark=not lit):
        target, _gate = r["exits"][d]
        exits.append({"dir": d, "name": DIR_NAMES[d],
                      "to": ROOMS[target]["name"] if target in s["visited"] else None})

    inventory = []
    for iid in g.inventory_ids():
        label = g.name(iid)
        if iid == "lamp":
            label += " (lit)" if g.istate("lamp") == "on" else " (off)"
        if iid == "cage" and g.loc("bird") == "in:cage":
            label += " with a little bird"
        inventory.append({"id": iid, "name": label[0].upper() + label[1:],
                          "noun": ITEMS[iid]["nouns"][0],
                          "treasure": bool(ITEMS[iid]["treasure"])})

    treasures = []
    for t in TREASURE_ORDER:
        status = g.treasure_status(t)
        treasures.append({"id": t, "status": status, "points": ITEMS[t]["treasure"],
                          "name": "???" if status == "unknown" else g.name(t)})

    regions = g.regions_visited()
    return {
        "room": {"id": r["id"], "name": r["name"] if lit else "Darkness",
                 "region": r["region"], "region_name": REGION_NAMES[r["region"]]},
        "lit": lit,
        "scene": scene_svg(g),
        "map": {
            "region": r["region"],
            "regions": [{"id": reg, "name": REGION_NAMES[reg]} for reg in regions],
            "svg": {reg: region_svg(g, reg) for reg in regions},
        },
        "exits": exits,
        "inventory": inventory,
        "log": s["log"][-120:],
        "treasures": treasures,
        "stored": sum(1 for t in TREASURE_ORDER if g.stored(t)),
        "score": g.score(),
        "max_score": 350,
        "turns": s["turns"],
        "lamp": {"present": g.present("lamp"), "on": g.istate("lamp") == "on",
                 "power": s["lamp"]},
        "baud": s["baud"],
        "lives": max(0, 3 - s["deaths"]),
        "game_over": s["game_over"],
        "won": s["won"],
        "pending": s["pending"],
    }
