"""Dwarves and the pirate: present, but gentler than in the original.

They only stir once you have reached the Hall of Mists, never follow you to
the surface, and are switched off entirely in peaceful mode.
"""

from .world import TREASURES

KNIFE_HIT = 0.10        # chance an armed dwarf's knife finds its mark
FOLLOW = 0.70           # chance a dwarf keeps after you when you move
DWARF_APPEARS = 0.05
FIRST_DWARF = 0.15
PIRATE_STRIKES = 0.02
RUSTLE = 0.008


def step(g):
    s = g.state
    if s["peaceful"] or s["closed"] or s["game_over"] or not g.flag("dwarves"):
        return
    d = s["dwarf"]
    if g.room["no_dwarf"]:
        d["here"] = None
        return
    rng = g.rng("dwarf")

    if d["here"] is not None:
        if d["here"] != s["room"]:
            if rng.random() >= FOLLOW:
                d["here"] = None
                return
            d["here"] = s["room"]
        if d["armed"]:
            if rng.random() < KNIFE_HIT:
                g.die("A little dwarf throws a sharp, nasty knife at you. It gets you!")
            else:
                g.say("There is a threatening little dwarf in the room with you! "
                      "One sharp, nasty knife is thrown at you. It misses!")
        else:
            d["armed"] = True
        return

    if not d["first"]:
        if s["turns"] > (g.flag("dwarves_turn") or 0) + 2 and rng.random() < FIRST_DWARF:
            d["first"] = True
            g.set_loc("axe", s["room"])
            g.say("A little dwarf just walked around a corner, saw you, threw a little "
                  "axe at you (which missed), cursed, and ran away.")
            g.log("A dwarf threw an axe at you, and missed.", "event")
        return

    if d["remaining"] > 0 and rng.random() < DWARF_APPEARS:
        d["here"] = s["room"]
        d["armed"] = False
        g.say("There is a threatening little dwarf in the room with you!")
        return

    pirate(g, rng)


def pirate(g, rng):
    s = g.state
    p = s["pirate"]
    if p["done"] or g.room["region"] in ("surface", "repo"):
        return
    loot = [t for t in TREASURES if g.carried(t)]
    if loot and rng.random() < PIRATE_STRIKES:
        for t in loot:
            g.set_loc(t, "a7")
        p["done"] = True
        g.say("Out from the shadows behind you pounces a bearded pirate! 'Har, har,' he "
              "chortles, 'I'll just take all this booty and hide it away with me chest "
              "deep in the maze!' He snatches your treasure and vanishes into the gloom.")
        g.log("A pirate stole your treasure and hid it in the maze.", "loss")
    elif rng.random() < RUSTLE:
        g.say("There are faint rustling noises from the darkness behind you.")


def attack_dwarf(g, thrown):
    s = g.state
    d = s["dwarf"]
    if d["here"] != s["room"]:
        g.say("There's no dwarf here.")
        return False
    if thrown and g.carried("axe"):
        g.set_loc("axe", s["room"])
        if g.rng("kill").random() < 0.7:
            d["here"] = None
            d["remaining"] -= 1
            g.say("You killed a little dwarf. The body vanishes in a cloud of greasy black smoke.")
            g.log("Killed a dwarf.", "event")
        else:
            g.say("You attack a little dwarf, but he dodges out of the way.")
    else:
        g.say("You lunge at the dwarf with your bare hands, but he skips nimbly out of reach. "
              "(An axe would help.)")
    return True
