"""Free, context-sensitive hints (the original charged points for these)."""

from .world import ROOMS, TREASURES


def hints(g):
    s = g.state
    rid = s["room"]
    region = ROOMS[rid]["region"]
    out = []

    if s["closed"]:
        out.append("Fetch one of the black rods with rusty marks from the south-west end, "
                   "leave it at the north-east end, go back south-west and say BLAST.")
        return out
    if s["closing"] is not None:
        out.append("The cave is closing. Just WAIT a few turns.")
        return out
    if not g.lit():
        out.append("It's dark. LIGHT LAMP if you have it; otherwise go BACK the way you came.")
    if region == "surface" and not g.carried("lamp") and g.loc("lamp") == "building":
        out.append("The well house is worth a visit. Take everything: a lamp will be essential underground.")
    if rid in ("depression", "below_grate") and g.istate("grate") != "open":
        out.append("UNLOCK GRATE, if you have the keys from the well house.")
    if region == "surface" and not s["visited"].get("depression") and "depression" not in s["visited"]:
        out.append("Follow the stream south from the road: valley, then the slit, then a hollow with a grate.")
    if rid == "bird_ch" and g.loc("bird") == "bird_ch":
        if g.carried("rod"):
            out.append("The bird is frightened of the black rod. Drop the rod, catch the bird, then fetch the rod again.")
        elif not g.carried("cage"):
            out.append("You'll need something to carry the bird in. There was a wicker cage in the cobble crawl.")
        else:
            out.append("CATCH BIRD. It goes into the cage.")
    if rid == "mtking" and g.loc("snake") == "mtking":
        out.append("Snakes are terrified of little birds, oddly. Bring the bird in its cage and RELEASE BIRD.")
    if rid in ("fissure_e", "fissure_w") and not g.flag("bridge"):
        out.append("Try WAVE ROD (the black rod with the rusty star, from the debris room).")
    if g.carried("nugget") and rid in ("hall_mists", "nugget_rm"):
        out.append("The nugget won't go up the steps. Go DOWN to the jumble of rock, WEST to Y2, then say PLUGH.")
    if rid == "y2":
        out.append("Say PLUGH to return to the well house. And there's another word for this room "
                   "that has to do with a bird: PLOVER.")
    if rid in ("alcove", "plover"):
        out.append("Only the emerald will fit through the tunnel with you. Drop everything else. "
                   "PLOVER, said at Y2 or in the Plover Room, carries you (and your lamp) between them.")
    if rid == "plover" and g.loc("pyramid") == "dark":
        out.append("The Dark Room to the south needs a lit lamp.")
    if g.at_room("plant") and g.istate("plant") < 2:
        out.append("The plant wants water. Fill your bottle at a stream or the reservoir and POUR WATER. "
                   "It needs two drinks.")
    if rid == "twopit_w" and g.istate("plant") < 2:
        out.append("There's a hole in the ceiling here. If only something could grow tall enough to reach it.")
    if rid in ("immense", "waterfall") and g.istate("door") == "rusty":
        out.append("Those hinges need oil. There's a pool of oil in the east pit of the Twopit Room. "
                   "Fill your bottle there, then POUR OIL.")
    if rid == "shell" and g.istate("clam") == "closed":
        out.append("You'll need something strong and pointed to prise the clam open. A trident, perhaps? "
                   "Try OPEN CLAM.")
    if g.present("vase") and not g.broken("vase") and g.loc("pillow") != "building":
        out.append("The vase is fragile. Put the velvet pillow down in the well house before you drop the vase there.")
    if g.at_room("dragon") and g.istate("dragon") == "alive":
        out.append("ATTACK DRAGON, and when asked, answer YES. Really.")
    if g.at_room("troll"):
        out.append("The troll wants a treasure. Throw him the golden eggs, then say FEE FIE FOE FOO "
                   "to summon them back to the Giant Room.")
    if g.at_room("bear") and g.istate("bear") == "chained":
        out.append("Bears like food. FEED BEAR, then UNLOCK CHAIN with the keys.")
    if region == "mazes":
        out.append("Every passage here can be walked back. Watch the map window. "
                   "The pirate's chest is said to lie in a dead end of the twisty maze.")
    if rid == "witts":
        out.append("The way out of Witt's End is west.")
    if rid == "d5":
        out.append("PUT COINS IN MACHINE for fresh batteries.")
    if g.present("lamp") and 0 < s["lamp"] < 150:
        out.append("Your lamp is fading. There's a vending machine at the end of the maze of passages "
                   "all different (via the long hall west of the Hall of Mists).")
    if g.carried("magazine") and rid != "witts":
        out.append("Some say it's good luck to leave the magazine at Witt's End.")

    if not out:
        stored = sum(1 for t in TREASURES if g.stored(t))
        out.append("You've stored %d of 15 treasures. Bring treasure back to the well house and drop it there." % stored)
        out.append("Dashed stubs on the map are exits you haven't tried yet.")
    return out
