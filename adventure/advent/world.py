"""The world of Colossal Cave: rooms, items and map regions.

Every room sits on a grid cell (x, y) inside a map region.  x grows to the
east and y grows to the south, so "north" is straight up the page.  Exits use
only the ten real directions (n s e w ne nw se sw u d); words such as "in",
"out", "upstream" or "cross" are per-room aliases onto those directions.  The
tests in tests/test_world.py hold the layout to a few rules that keep the map
honest: compass exits point the way they say, every passage can be walked
back, and no drawn passage runs through another room.

Exit values are either a room id or a (room id, gate) pair.  Gates are
checked by the engine; see Game.gate().

The prose is written afresh in the spirit of Will Crowther and Don Woods'
original Colossal Cave Adventure (1976-77).
"""

DIRECTIONS = ("n", "ne", "e", "se", "s", "sw", "w", "nw", "u", "d")

DIR_NAMES = {
    "n": "north", "ne": "north-east", "e": "east", "se": "south-east",
    "s": "south", "sw": "south-west", "w": "west", "nw": "north-west",
    "u": "up", "d": "down",
}

OPPOSITE = {
    "n": "s", "s": "n", "e": "w", "w": "e", "ne": "sw", "sw": "ne",
    "nw": "se", "se": "nw", "u": "d", "d": "u",
}

VECTORS = {
    "n": (0, -1), "ne": (1, -1), "e": (1, 0), "se": (1, 1),
    "s": (0, 1), "sw": (-1, 1), "w": (-1, 0), "nw": (-1, -1),
}

REGIONS = [
    ("surface", "The Surface"),
    ("upper", "Upper Cave"),
    ("middle", "Middle Cave"),
    ("deep", "Deep Cave"),
    ("mazes", "The Mazes"),
    ("far", "Beyond the Chasm"),
    ("repo", "The Repository"),
]
REGION_NAMES = dict(REGIONS)

# Gates whose exits are not even mentioned until they open.
HIDDEN_GATES = {"beanstalk"}

ROOMS = {}


def room(rid, name, region, x, y, long, short=None, exits=None, aliases=None,
         lit=None, water=False, oil=False, scene="cave", feats=(), label=None,
         scenery=None, nogo=None, no_dwarf=False):
    if rid in ROOMS:
        raise ValueError("duplicate room id %r" % rid)
    norm = {}
    for d, ex in (exits or {}).items():
        if d not in DIRECTIONS:
            raise ValueError("%s: bad direction %r" % (rid, d))
        norm[d] = ex if isinstance(ex, tuple) else (ex, None)
    ROOMS[rid] = {
        "id": rid,
        "name": name,
        "region": region,
        "x": x,
        "y": y,
        "long": long,
        "short": short or ("You're in the %s." % name),
        "exits": norm,
        "aliases": aliases or {},
        "lit": (region in ("surface", "repo")) if lit is None else lit,
        "water": water,
        "oil": oil,
        "scene": scene,
        "feats": tuple(feats),
        "label": label or name,
        "scenery": scenery or {},
        "nogo": nogo,
        "no_dwarf": no_dwarf or region in ("surface", "repo"),
    }


# --------------------------------------------------------------------------
# The Surface
#
#            x=1          x=2          x=3
#   y=0   Hilltop ---- Forest
#            |            |
#   y=1   Hill ------- End of Road -- Well House
#            |            |
#   y=2   W.Forest --- Valley ------ E.Forest
#              \          |          /
#   y=3         \       Slit        /
#                \        |        /
#   y=4           `--- Grate -----'
# --------------------------------------------------------------------------

room("road", "End of Road", "surface", 2, 1,
     "You are standing at the end of a road before a small brick well house. "
     "All around is forest. A small stream flows out of the building and down "
     "a gully to the south. The road climbs west towards a hill, and the trees "
     "thicken to the north.",
     short="You're at the end of the road, by the well house.",
     exits={"n": "forest_n", "e": "building", "w": "hill", "s": "valley"},
     aliases={"in": "e", "inside": "e", "building": "e", "house": "e",
              "enter": "e", "downstream": "s", "gully": "s", "valley": "s",
              "forest": "n", "hill": "w", "road": "w"},
     water=True, scene="road", label="End of Road",
     scenery={"stream brook water gully": "A clear little stream runs out of the well house and away down the gully.",
              "building house well": "A small brick well house, solidly built, with a door facing you.",
              "road": "The road is dusty and empty. It climbs away west over a hill.",
              "forest trees tree woods": "Dark, tall trees on every side."})

room("building", "Well House", "surface", 3, 1,
     "You are inside a small brick building, the well house for a large spring "
     "that bubbles up through an iron grating in the floor. Shelves line the "
     "walls. The only door leads west, back out to the road.",
     short="You're inside the well house.",
     exits={"w": "road"},
     aliases={"out": "w", "outside": "w", "exit": "w", "road": "w", "leave": "w"},
     water=True, scene="wellhouse", label="Well House", no_dwarf=True,
     scenery={"spring well grating water": "Clear, cold water wells up through an iron grating in the floor. You could fill a bottle here.",
              "shelves shelf walls": "Plain wooden shelves. This is where you'll want to keep any treasure you bring back."})

room("hill", "Hill in Road", "surface", 1, 1,
     "You have walked up a hill, still in the forest. The road slopes back "
     "down to the east towards the well house. A rough path climbs on up to "
     "the bare top of the hill, and the trees thin out to the south.",
     short="You're on the hill in the road.",
     exits={"e": "road", "u": "hilltop", "s": "forest_w"},
     aliases={"road": "e", "path": "u", "top": "u", "forest": "s"},
     scene="hill", label="Hill",
     scenery={"path": "A rough path of trodden earth climbs to the hilltop.",
              "road": "The road runs down to the east."})

room("hilltop", "Top of the Hill", "surface", 1, 0,
     "You stand on the bald top of the hill. The whole country lies below "
     "you: the road winding east to a tiny brick well house, dark forest on "
     "every side, and a valley cutting south where the stream runs. Far to "
     "the south a hollow is just visible among the trees. A path leads back "
     "down, and the forest begins to the east.",
     short="You're on top of the hill.",
     exits={"d": "hill", "e": "forest_n"},
     aliases={"path": "d", "forest": "e"},
     scene="hilltop", label="Hilltop",
     scenery={"hollow depression": "A shallow hollow in the forest, south of the valley. Something metal glints there.",
              "valley": "The valley runs south from the road, following the stream."})

room("forest_n", "Forest", "surface", 2, 0,
     "You are in open forest, with a deep wood stretching away to the north. "
     "The trees stand tall and black against a white sky. The road lies just "
     "to the south, and the land rises to a hilltop in the west.",
     short="You're in the forest north of the road.",
     exits={"s": "road", "w": "hilltop"},
     aliases={"road": "s", "hill": "w"},
     scene="forest", label="Forest",
     scenery={"trees tree forest wood woods": "Tall, straight and black, like chimneys.",
              "sky": "A flat white sky, the colour of a primed canvas."},
     nogo="The wood to the north is far too thick to walk through.")

room("valley", "Valley", "surface", 2, 2,
     "You are in a valley in the forest beside a stream tumbling along a "
     "rocky bed. Upstream, to the north, is the road; downstream the stream "
     "runs south. The forest closes in to the east and west.",
     short="You're in the valley.",
     exits={"n": "road", "s": "slit", "e": "forest_e", "w": "forest_w"},
     aliases={"upstream": "n", "downstream": "s", "road": "n"},
     water=True, scene="valley", label="Valley",
     scenery={"stream water bed streambed": "The stream chatters over stones, cold and clear."})

room("forest_e", "Eastern Forest", "surface", 3, 2,
     "You are in thick forest east of the valley. A faint path runs back west "
     "to the stream, and another threads south-west between the trees "
     "towards a hollow in the ground.",
     short="You're in the eastern forest.",
     exits={"w": "valley", "sw": "depression"},
     aliases={"valley": "w", "hollow": "sw"},
     scene="forest", label="E. Forest",
     nogo="The trees crowd too close that way.")

room("forest_w", "Western Forest", "surface", 1, 2,
     "You are in forest west of the valley. The hill rises to the north, the "
     "valley lies east, and a path leads south-east towards a hollow.",
     short="You're in the western forest.",
     exits={"n": "hill", "e": "valley", "se": "depression"},
     aliases={"hill": "n", "valley": "e", "hollow": "se"},
     scene="forest", label="W. Forest",
     nogo="The trees crowd too close that way.")

room("slit", "Slit in Streambed", "surface", 2, 3,
     "At your feet all the water of the stream splashes into a two-inch slit "
     "in the rock. The streambed carries on south, dry, towards a hollow. "
     "Upstream is the valley.",
     short="You're at the slit in the streambed.",
     exits={"n": "valley", "s": "depression"},
     aliases={"upstream": "n", "downstream": "s", "valley": "n"},
     water=True, scene="slit", label="Slit",
     scenery={"slit crack": "The slit is far too narrow to squeeze into. The water vanishes down it with a gurgle.",
              "stream water streambed": "The stream disappears into the slit; beyond it the bed is dry."})

room("depression", "Outside Grate", "surface", 2, 4,
     "You are in a twenty-foot depression floored with bare dirt. Set into "
     "the dirt is a strong steel grate mounted in concrete. A dry streambed "
     "leads north out of the depression, and paths wander off through the "
     "forest to the north-east and north-west.",
     short="You're outside the grate.",
     exits={"n": "slit", "ne": "forest_e", "nw": "forest_w",
            "d": ("below_grate", "grate")},
     aliases={"in": "d", "inside": "d", "enter": "d", "upstream": "n",
              "streambed": "n"},
     scene="grate", label="Grate",
     scenery={"depression dirt hollow": "A bowl of bare dirt in the forest floor.",
              "concrete": "Old, cracked concrete holds the grate firmly."})

# --------------------------------------------------------------------------
# Upper Cave
#
#  x: -3        -1      0      1      2      3      4      5      6      7      8
# y0                                       SmPit--Bird--Canyon-Debris-Cobble-Grate
#                                            |
# y1 LongW ----LongE--MistsW-FissW=FissE--HallMists--Low Room
#                                          |    \
# y2                                       |      \
# y3                              WestCh--MtKing--LowPass--Y2--Jumble
#                                       /    |           |
# y4                         Dragon--SecretEW  SouthCh   Window
# --------------------------------------------------------------------------

room("below_grate", "Below the Grate", "upper", 8, 0,
     "You are in a small chamber beneath a steel grate that opens to the "
     "surface. Daylight filters down between the bars. A low crawl over "
     "cobbles leads inward to the west.",
     short="You're below the grate.",
     exits={"u": ("depression", "grate"), "w": "cobble"},
     aliases={"out": "u", "outside": "u", "surface": "u", "crawl": "w",
              "climb": "u"},
     lit=True, feats=("grate_above",), label="Below Grate", no_dwarf=True)

room("cobble", "Cobble Crawl", "upper", 7, 0,
     "You are crawling over cobbles in a low passage. There is a dim light "
     "at the east end of the passage; westward the crawl leads into "
     "darkness.",
     short="You're in the cobble crawl.",
     exits={"e": "below_grate", "w": "debris"},
     lit=True, feats=("low", "cobbles"), label="Cobbles", no_dwarf=True)

room("debris", "Debris Room", "upper", 6, 0,
     "You are in a debris room, choked with mud and stuff washed in from the "
     "surface. The cobble crawl leaves to the east, and an awkward canyon "
     "leads west. Daubed on the wall in faded paint are the words 'MAGIC "
     "WORD XYZZY'.",
     short="You're in the debris room.",
     exits={"e": "cobble", "w": "canyon"},
     feats=("rubble", "writing:XYZZY"), label="Debris", no_dwarf=True,
     scenery={"wall writing words paint message": "The faded paint reads: 'MAGIC WORD XYZZY'.",
              "debris mud stuff": "Mud, twigs and leaves washed down from the surface."})

room("canyon", "Sloping Canyon", "upper", 5, 0,
     "You are in an awkward sloping east/west canyon. Its walls lean in so "
     "close overhead that you have to stoop.",
     short="You're in the awkward sloping canyon.",
     exits={"e": "debris", "w": "bird_ch"},
     feats=("canyon",), label="Canyon", no_dwarf=True)

room("bird_ch", "Orange River Chamber", "upper", 4, 0,
     "You are in a splendid chamber thirty feet high. The walls are frozen "
     "rivers of orange stone, rippled and glossy. The awkward canyon leaves "
     "to the east; a good passage heads west.",
     short="You're in the Orange River Chamber.",
     exits={"e": "canyon", "w": "small_pit"},
     feats=("orange_river",), label="Bird Room", no_dwarf=True,
     scenery={"walls stone rivers orange": "Flowstone, the colour of marmalade, poured and set in ripples."})

room("small_pit", "Top of Small Pit", "upper", 3, 0,
     "At your feet is a small pit breathing traces of white mist. Rough "
     "stone steps lead down into it. A passage runs east, back towards the "
     "orange chamber.",
     short="You're at the top of the small pit.",
     exits={"e": "bird_ch", "d": "hall_mists"},
     aliases={"steps": "d", "pit": "d", "stairs": "d"},
     feats=("pit", "mist"), label="Small Pit", no_dwarf=True,
     scenery={"pit mist": "Wisps of white mist curl up out of the pit.",
              "steps stairs": "Rough steps, worn smooth in the middle, lead down."})

room("hall_mists", "Hall of Mists", "upper", 3, 1,
     "You are at one end of a vast hall stretching away out of sight to the "
     "west. Wisps of white mist hang in the air and sway as if alive. Rough "
     "stone steps climb up to a dome overhead. Wide stairs lead south, a low "
     "passage runs east, and a jumble of rock falls away below.",
     short="You're in the Hall of Mists.",
     exits={"u": ("small_pit", "steps"), "w": "fissure_e", "e": "nugget_rm",
            "s": "mtking", "d": "jumble"},
     aliases={"steps": "u", "dome": "u", "stairs": "s", "climb": "u"},
     feats=("mist", "steps"), label="Hall of Mists",
     scenery={"mist wisps": "The mist seems to breathe.",
              "steps dome": "The steps climb, slick with mist, to the dome above."})

room("nugget_rm", "Low Room", "upper", 4, 1,
     "This is a low room with a warning scratched crudely on the wall: "
     "'TOO HEAVY FOR THE STEPS!' The only way out is west.",
     short="You're in the low room.",
     exits={"w": "hall_mists"},
     feats=("low", "writing:TOO HEAVY!"), label="Low Room",
     scenery={"wall warning note writing": "Someone has scratched: 'TOO HEAVY FOR THE STEPS!'"})

room("fissure_e", "East Bank of Fissure", "upper", 2, 1,
     "You are on the east bank of a fissure slicing clear across the hall. "
     "The mist is thick here, and the fissure is far too wide to jump. The "
     "hall runs back east.",
     short="You're on the east bank of the fissure.",
     exits={"e": "hall_mists", "w": ("fissure_w", "bridge")},
     aliases={"cross": "w", "bridge": "w", "over": "w"},
     feats=("mist", "fissure"), label="Fissure E",
     scenery={"fissure crack chasm": "A sheer crack, too wide to jump. You can't see the bottom."})

room("fissure_w", "West Side of Fissure", "upper", 1, 1,
     "You are on the west side of the fissure in the Hall of Mists. The hall "
     "continues west into the gloom.",
     short="You're on the west side of the fissure.",
     exits={"e": ("fissure_e", "bridge"), "w": "mists_w"},
     aliases={"cross": "e", "bridge": "e", "over": "e"},
     feats=("mist", "fissure"), label="Fissure W",
     scenery={"fissure crack chasm": "A sheer crack, too wide to jump. You can't see the bottom."})

room("mists_w", "West End of Hall of Mists", "upper", 0, 1,
     "You are at the west end of the Hall of Mists. A low wide crawl "
     "continues west towards a long hall, and a narrow passage drops away "
     "south into a maze. The fissure lies back to the east.",
     short="You're at the west end of the Hall of Mists.",
     exits={"e": "fissure_w", "w": "long_hall_e", "s": "a1"},
     aliases={"maze": "s", "crawl": "w"},
     feats=("mist",), label="Mists West")

room("long_hall_e", "East End of Long Hall", "upper", -1, 1,
     "You are at the east end of a very long hall, apparently without side "
     "chambers. It stretches west far beyond your light. A low crawl leads "
     "back east to the Hall of Mists.",
     short="You're at the east end of the long hall.",
     exits={"e": "mists_w", "w": "long_hall_w"},
     feats=("long_hall",), label="Long Hall E")

room("long_hall_w", "West End of Long Hall", "upper", -3, 1,
     "You are at the west end of a very long, featureless hall. A narrow "
     "passage leads south into a maze of passages that all look quite "
     "different.",
     short="You're at the west end of the long hall.",
     exits={"e": "long_hall_e", "s": "d1"},
     aliases={"maze": "s"},
     feats=("long_hall",), label="Long Hall W")

room("mtking", "Hall of the Mountain King", "upper", 3, 3,
     "You are in the Hall of the Mountain King, a vast chamber with passages "
     "leading off west, south, east and south-west. Wide stairs climb north "
     "to the Hall of Mists.",
     short="You're in the Hall of the Mountain King.",
     exits={"n": "hall_mists", "w": ("west_ch", "snake"),
            "s": ("south_ch", "snake"), "e": ("low_ns", "snake"),
            "sw": ("secret_ew", "snake")},
     aliases={"stairs": "n"},
     feats=("pillars",), label="Mt King")

room("west_ch", "West Side Chamber", "upper", 2, 3,
     "You are in the west side chamber of the Hall of the Mountain King. "
     "The walls are crusted with crystals. The only way out is east.",
     short="You're in the west side chamber.",
     exits={"e": "mtking"},
     feats=("crystals",), label="West Chamber")

room("south_ch", "South Side Chamber", "upper", 3, 4,
     "You are in the south side chamber, a small vaulted room off the Hall "
     "of the Mountain King, which lies back to the north.",
     short="You're in the south side chamber.",
     exits={"n": "mtking"},
     feats=("vault",), label="South Chamber")

room("low_ns", "Low Passage", "upper", 4, 3,
     "You are in a low east/west passage. A hole in the floor drops down "
     "into a dirty passage below. The Hall of the Mountain King lies west.",
     short="You're in the low passage.",
     exits={"w": "mtking", "e": "y2", "d": "dirty"},
     aliases={"hole": "d"},
     feats=("low",), label="Low Passage")

room("y2", "Y2", "upper", 5, 3,
     "You are in a large room, with a passage to the west, a wall of broken "
     "rock to the east, and a narrow passage leading south. A large 'Y2' is "
     "painted on a rock in the middle of the floor.",
     short="You're at Y2.",
     exits={"w": "low_ns", "e": "jumble", "s": "window_pit"},
     feats=("y2",), label="Y2",
     scenery={"y2 rock paint": "Big white letters on a boulder: 'Y2'. Nobody knows quite why."})

room("jumble", "Jumble of Rock", "upper", 6, 3,
     "You are in a jumble of rock, cracked everywhere, with boulders tilted "
     "at crazy angles. A way scrambles up towards the Hall of Mists; the "
     "room called Y2 is west.",
     short="You're in the jumble of rock.",
     exits={"w": "y2", "u": "hall_mists"},
     aliases={"climb": "u"},
     feats=("boulders",), label="Jumble")

room("window_pit", "Window on Pit", "upper", 5, 4,
     "You are at a low window overlooking an enormous pit whose floor is "
     "lost in white mist far below. Across the void, some twenty-five feet "
     "away, is a second window opening into a lighted room, and in it a "
     "shadowy figure peers back at you. The way back is north.",
     short="You're at the window on the pit.",
     exits={"n": "y2"},
     feats=("window",), label="Window",
     scenery={"figure shadow shadowy": "The shadowy figure waves when you wave, and stops when you stop. Curious.",
              "window pit": "A sheer drop into mist. Best not lean out too far."},
     nogo="The only safe way is north. The pit is a very long way down.")

room("secret_ew", "Secret E/W Canyon", "upper", 2, 4,
     "You are in a secret canyon running east and west. It opens north-east "
     "into the Hall of the Mountain King and carries on west, where the "
     "rock is scorched black.",
     short="You're in the secret east/west canyon.",
     exits={"ne": "mtking", "w": "lair"},
     feats=("canyon",), label="Secret E/W")

room("lair", "Dragon's Lair", "upper", 1, 4,
     "You are in a secret canyon that bends sharply here. One branch runs "
     "east; the other heads west, deeper into the rock. The walls are "
     "scorched black and the air smells of smoke.",
     short="You're in the dragon's lair.",
     exits={"e": ("secret_ew", "dragon"), "w": ("secret_ns", "dragon")},
     feats=("scorched",), label="Dragon's Lair")

# --------------------------------------------------------------------------
# Middle Cave
#
#   x:   0        1         2         3        4         5         6
# y0  Plover -- Alcove -- Misty
#       |                   |
# y1  Dark     LowRoom -- Oriental                     Dusty --- Dirty
#                 |            \                         |        |
# y2           Sloping           Swiss -- Bedquilt -- Complex   Brink
#                              /                         |
# y3                       Soft                       Anteroom -- Witt's
# --------------------------------------------------------------------------

room("dirty", "Dirty Passage", "middle", 6, 1,
     "You are in a dirty, broken passage. A large hole in the ceiling leads "
     "up to the low passage above. Westward is a dusty room, and to the "
     "south the passage ends at the brink of a pit.",
     short="You're in the dirty passage.",
     exits={"u": "low_ns", "w": "dusty", "s": "brink"},
     aliases={"hole": "u", "climb": "u"},
     feats=("rubble",), label="Dirty Passage")

room("brink", "Brink of Pit", "middle", 6, 2,
     "You are on the brink of a thirty-foot pit with a massive orange column "
     "down one wall. You could climb down the column into a maze below. The "
     "dirty passage leads north.",
     short="You're at the brink of the pit.",
     exits={"n": "dirty", "d": "a6"},
     aliases={"climb": "d", "column": "d", "maze": "d"},
     feats=("pit", "column"), label="Brink",
     scenery={"column orange": "A thick column of orange flowstone runs down into the pit. It looks easy to climb.",
              "pit": "Thirty feet down, a maze of passages."})

room("dusty", "Dusty Rock Room", "middle", 5, 1,
     "You are in a large room full of dusty rocks. A big hole in the floor "
     "drops south into a junction below, and a passage leads east.",
     short="You're in the dusty rock room.",
     exits={"e": "dirty", "s": "complex"},
     aliases={"hole": "s"},
     feats=("boulders",), label="Dusty Rocks")

room("complex", "Complex Junction", "middle", 5, 2,
     "You are at a complex junction. A crawl from the north meets a walking "
     "passage heading west, and another passage runs south. Above you, a "
     "hole in the ceiling opens into a large room. The air is damp.",
     short="You're at the complex junction.",
     exits={"n": "dusty", "w": "bedquilt", "s": "anteroom", "u": "shell"},
     aliases={"hole": "u", "climb": "u"},
     feats=("junction",), label="Junction")

room("anteroom", "Anteroom", "middle", 5, 3,
     "You are in an anteroom. Remnants of recent digging are scattered "
     "about. A large passage leads east, and the junction is back to the "
     "north.",
     short="You're in the anteroom.",
     exits={"n": "complex", "e": "witts"},
     feats=("digging",), label="Anteroom",
     scenery={"digging remnants tools": "Broken picks, a bent shovel and a lot of loose dirt. Somebody's been busy."})

room("witts", "Witt's End", "middle", 6, 3,
     "You are at Witt's End. Passages lead off in *all* directions, or so it "
     "seems; most are just little holes that wind back here. The real way "
     "out is west.",
     short="You're at Witt's End.",
     exits={"w": "anteroom"},
     feats=("holes",), label="Witt's End",
     nogo="You crawl around in some little holes and wind up back at Witt's End.")

room("bedquilt", "Bedquilt", "middle", 4, 2,
     "You are in Bedquilt, a long east/west passage with holes everywhere. "
     "Most are too small to enter, but one larger hole in the floor drops "
     "down to a slab room below.",
     short="You're in Bedquilt.",
     exits={"e": "complex", "w": "swiss", "d": "slab"},
     aliases={"hole": "d"},
     feats=("holes",), label="Bedquilt",
     nogo="You poke your head into a few of the holes, but they're all far too small.")

room("swiss", "Swiss Cheese Room", "middle", 3, 2,
     "You are in a room whose walls are riddled with holes like Swiss "
     "cheese. Passages lead east, west, north-west and south-west. A large "
     "bedrock block takes up part of the floor.",
     short="You're in the Swiss Cheese Room.",
     exits={"e": "bedquilt", "w": "twopit_e", "nw": "oriental", "sw": "soft"},
     feats=("cheese",), label="Swiss Cheese")

room("soft", "Soft Room", "middle", 2, 3,
     "You are in the Soft Room. The walls are hung with heavy curtains, the "
     "floor is laid with thick carpet, and moss covers the ceiling. "
     "Everything is hushed. The way out is north-east.",
     short="You're in the Soft Room.",
     exits={"ne": "swiss"},
     feats=("curtains",), label="Soft Room",
     scenery={"curtains carpet moss": "Remarkably comfortable, for a cave."})

room("oriental", "Oriental Room", "middle", 2, 1,
     "This is the Oriental Room. Ancient drawings of figures and animals "
     "cover the walls. A gently sloping passage leads north, another leads "
     "south-east, and a hands-and-knees crawl leads west.",
     short="You're in the Oriental Room.",
     exits={"n": "misty", "se": "swiss", "w": "low_room"},
     feats=("drawings",), label="Oriental",
     scenery={"drawings walls figures animals": "Little figures and long-necked creatures, painted in ochre and red."})

room("misty", "Misty Cavern", "middle", 2, 0,
     "You are on a wide path running round the rim of a large cavern. Far "
     "below, hidden by a heavy white mist, something splashes. A faint "
     "phosphorescence lights the mist. The path leads south to the Oriental "
     "Room and west to an alcove.",
     short="You're in the misty cavern.",
     exits={"s": "oriental", "w": "alcove"},
     lit=True, feats=("mist", "rim"), label="Misty Cavern")

room("alcove", "Alcove", "middle", 1, 0,
     "You are in an alcove, faintly lit by the mist. A very tight tunnel "
     "leads west to another room; you could only squeeze through it carrying "
     "next to nothing. The cavern is back to the east.",
     short="You're in the alcove.",
     exits={"e": "misty", "w": ("plover", "tunnel")},
     aliases={"tunnel": "w"},
     lit=True, feats=("tunnel_w",), label="Alcove",
     scenery={"tunnel": "Very, very tight. You'd have to leave almost everything behind."})

room("plover", "Plover Room", "middle", 0, 0,
     "You're in a small chamber lit by an eerie glow. An extremely narrow "
     "tunnel leaves to the east, and a passage leads south into darkness.",
     short="You're in the Plover Room.",
     exits={"e": ("alcove", "tunnel"), "s": "dark"},
     aliases={"tunnel": "e"},
     lit=True, feats=("glow",), label="Plover Room",
     scenery={"tunnel": "Very, very tight. You'd have to leave almost everything behind."})

room("dark", "Dark Room", "middle", 0, 1,
     "You're in the Dark Room, a low chamber whose walls seem to swallow "
     "light. A stone tablet is set into one wall. The only exit is north.",
     short="You're in the Dark Room.",
     exits={"n": "plover"},
     feats=("tablet",), label="Dark Room",
     scenery={"tablet stone": "The tablet reads: 'WELL DONE, BRAVE SOUL, FOR BRINGING LIGHT INTO THE DARK ROOM.'"})

room("low_room", "Large Low Room", "middle", 1, 1,
     "You are in a large low room. Crawls lead off east and south, and a "
     "steep incline rises above you with a knotted rope dangling down it.",
     short="You're in the large low room.",
     exits={"e": "oriental", "s": "sloping", "u": "incline"},
     aliases={"rope": "u", "incline": "u", "climb": "u"},
     feats=("low", "rope"), label="Large Low Rm",
     scenery={"rope": "A stout, knotted rope. Someone thoughtful left it here.",
              "incline": "Steep, but with the rope you could climb it."})

room("sloping", "Sloping Corridor", "middle", 1, 2,
     "You are in a long winding corridor sloping out of sight. Downward it "
     "leads towards the moan of wind in a chasm; north lies the large low "
     "room.",
     short="You're in the sloping corridor.",
     exits={"n": "low_room", "d": "chasm_sw"},
     feats=("tunnel",), label="Sloping")

# --------------------------------------------------------------------------
# Deep Cave
#
#   x:   0          1          2      ...    4
# y0  Waterfall -- Incline                  Shell
#       |                                     |
# y1  Immense                               Ragged
#       |                                     |
# y2  Giant ------ Narrow                   Cul-de-sac
#                    |
# y3              TwopitW --- TwopitE
#                /   |           |
# y4         Slab  WestPit    EastPit
#              |
# y5         SecretN/S
#              |
# y6         Mirror
#              |
# y7         Reservoir
# --------------------------------------------------------------------------

room("twopit_e", "East End of Twopit Room", "deep", 2, 3,
     "You are at the east end of the Twopit Room. Thin slabs of rock litter "
     "the floor and make it easy to climb down into the pit at your feet. A "
     "path runs west along the floor, and an exit leads east to the Swiss "
     "Cheese Room.",
     short="You're at the east end of the Twopit Room.",
     exits={"e": "swiss", "w": "twopit_w", "d": "east_pit"},
     aliases={"pit": "d"},
     feats=("pit",), label="Twopit E")

room("twopit_w", "West End of Twopit Room", "deep", 1, 3,
     "You are at the west end of the Twopit Room. There is a large hole in "
     "the ceiling above the pit at this end. A path leads east along the "
     "floor, a crack runs south-west, and the pit opens at your feet.",
     short="You're at the west end of the Twopit Room.",
     exits={"e": "twopit_e", "sw": "slab", "d": "west_pit",
            "u": ("narrow_corr", "beanstalk")},
     aliases={"pit": "d", "climb": "u", "beanstalk": "u", "plant": "u",
              "crack": "sw"},
     feats=("pit", "hole_above"), label="Twopit W")

room("west_pit", "Bottom of West Pit", "deep", 1, 4,
     "You are at the bottom of the western pit in the Twopit Room. There is "
     "a large hole in the ceiling high above.",
     short="You're in the west pit.",
     exits={"u": "twopit_w"},
     aliases={"climb": "u", "out": "u"},
     feats=("pit_bottom",), label="West Pit")

room("east_pit", "Bottom of East Pit", "deep", 2, 4,
     "You are at the bottom of the eastern pit in the Twopit Room. A small "
     "pool of oil has collected in one corner.",
     short="You're in the east pit.",
     exits={"u": "twopit_e"},
     aliases={"climb": "u", "out": "u"},
     oil=True, feats=("pit_bottom", "oil_pool"), label="East Pit",
     scenery={"pool oil": "Thick, black, slippery oil. Good for squeaky hinges."})

room("narrow_corr", "Narrow Corridor", "deep", 1, 2,
     "You are in a long, narrow corridor running west out of sight. Leaves "
     "crowd up through a hole in the floor here: the top of the beanstalk.",
     short="You're in the narrow corridor.",
     exits={"w": "giant", "d": "twopit_w"},
     aliases={"beanstalk": "d", "climb": "d", "plant": "d"},
     feats=("tunnel", "leaves"), label="Narrow Corr.")

room("giant", "Giant Room", "deep", 0, 2,
     "You are in the Giant Room. The ceiling is too high for your light to "
     "reach. Cavernous passages lead north and east; to the south a cave-in "
     "blocks the way. Scrawled on the west wall in enormous letters is the "
     "inscription 'FEE FIE FOE FOO' [sic].",
     short="You're in the Giant Room.",
     exits={"n": "immense", "e": "narrow_corr"},
     feats=("vast", "writing:FEE FIE FOE FOO"), label="Giant Room",
     scenery={"inscription writing wall letters": "In letters six feet high: 'FEE FIE FOE FOO'.",
              "cave-in cavein rubble": "Tons of rock. Nobody is getting through there."},
     nogo="The way south is blocked by a cave-in.")

room("immense", "Immense N/S Passage", "deep", 0, 1,
     "You are at one end of an immense north/south passage. The Giant Room "
     "lies to the south.",
     short="You're in the immense passage.",
     exits={"s": "giant", "n": ("waterfall", "door")},
     feats=("tall", "door_n"), label="Immense Pass.")

room("waterfall", "Cavern with Waterfall", "deep", 0, 0,
     "You are in a magnificent cavern. A rushing stream pours over a "
     "sparkling waterfall and vanishes, roaring, into a whirlpool in the "
     "floor. A great iron door lies south, and a passage leads east.",
     short="You're in the cavern with the waterfall.",
     exits={"s": ("immense", "door"), "e": "incline"},
     water=True, feats=("waterfall",), label="Waterfall",
     scenery={"waterfall stream whirlpool": "Beautiful, and very loud."})

room("incline", "Top of Steep Incline", "deep", 1, 0,
     "You are at the top of a steep incline above a large room. Someone has "
     "anchored a knotted rope here, so you can climb down, and back up "
     "again. A passage leads west.",
     short="You're at the top of the steep incline.",
     exits={"w": "waterfall", "d": "low_room"},
     aliases={"rope": "d", "climb": "d", "incline": "d"},
     feats=("rope", "incline"), label="Incline",
     scenery={"rope": "Securely anchored to an iron ring."})

room("slab", "Slab Room", "deep", 0, 4,
     "You are in a large, low, circular chamber whose floor is an immense "
     "slab fallen from the ceiling. A hole above leads up to Bedquilt. A "
     "crack runs north-east towards the Twopit Room, and a narrow passage "
     "leads south.",
     short="You're in the Slab Room.",
     exits={"u": "bedquilt", "ne": "twopit_w", "s": "secret_ns"},
     aliases={"hole": "u", "climb": "u", "crack": "ne"},
     feats=("slab",), label="Slab Room")

room("secret_ns", "Secret N/S Canyon", "deep", 0, 5,
     "You are in a secret canyon running north and south. A side passage, "
     "smelling faintly of smoke, leads east.",
     short="You're in the secret north/south canyon.",
     exits={"n": "slab", "s": "mirror", "e": ("lair", "dragon")},
     feats=("canyon",), label="Secret N/S")

room("mirror", "Mirror Canyon", "deep", 0, 6,
     "You are in a north/south canyon about twenty-five feet across, its "
     "floor hidden by mist creeping in from the south. High overhead, an "
     "enormous two-sided mirror hangs between the walls. No doubt it is for "
     "the dwarves, who are famously vain.",
     short="You're in Mirror Canyon.",
     exits={"n": "secret_ns", "s": "reservoir"},
     feats=("canyon", "mirror"), label="Mirror Canyon",
     scenery={"mirror": "You can just make out a tiny figure with a lamp, peering up. It's you."})

room("reservoir", "Edge of Reservoir", "deep", 0, 7,
     "You are at the edge of a large underground reservoir. White mist "
     "boils off its dark surface. A stream tumbles out of a hole high in "
     "the wall and splashes into the water somewhere out in the mist. The "
     "only way back is north.",
     short="You're at the edge of the reservoir.",
     exits={"n": "mirror"},
     water=True, feats=("lake", "mist"), label="Reservoir",
     scenery={"reservoir lake water": "Deep, dark and very cold. Far too deep to wade."},
     nogo="The water is far too deep and cold to cross.")

room("shell", "Shell Room", "deep", 4, 0,
     "You're in a large room carved out of sedimentary rock. Fragments of "
     "ancient shells are embedded in the floor and walls. A hole leads down "
     "to the complex junction, and a low passage heads south.",
     short="You're in the Shell Room.",
     exits={"d": "complex", "s": "ragged"},
     aliases={"hole": "d"},
     feats=("shells",), label="Shell Room",
     scenery={"shells fragments fossils": "Tiny fossil shells, millions of years old."})

room("ragged", "Ragged Corridor", "deep", 4, 1,
     "You are in a long sloping corridor with ragged, sharp walls. It runs "
     "north and south.",
     short="You're in the ragged corridor.",
     exits={"n": "shell", "s": "cul"},
     feats=("tunnel",), label="Ragged")

room("cul", "Cul-de-Sac", "deep", 4, 2,
     "You are in a cul-de-sac about eight feet across. The only way out is "
     "north.",
     short="You're in the cul-de-sac.",
     exits={"n": "ragged"},
     feats=("deadend",), label="Cul-de-Sac")

# --------------------------------------------------------------------------
# The Mazes.  Descriptions are all alike (or all different), as tradition
# demands; the map labels are your chalk marks.
#
#   x:  0      1      2              5      6
# y0  T1 --- T2 --- T3            D1 --- D2
#      |      \      |             |      |
# y1  T4 --- T5 --- T6            D3 --- D4
#      |      |                    |
# y2  End   End                   D5
# --------------------------------------------------------------------------

ALIKE = "You are in a maze of twisty little passages, all alike."

room("a1", "Twisty Passages", "mazes", 0, 0, ALIKE, short=ALIKE,
     exits={"n": "mists_w", "e": "a2", "s": "a4"},
     feats=("maze",), label="Twisty 1")
room("a2", "Twisty Passages", "mazes", 1, 0, ALIKE, short=ALIKE,
     exits={"w": "a1", "e": "a3", "se": "a6"},
     feats=("maze",), label="Twisty 2")
room("a3", "Twisty Passages", "mazes", 2, 0, ALIKE, short=ALIKE,
     exits={"w": "a2", "s": "a6"},
     feats=("maze",), label="Twisty 3")
room("a4", "Twisty Passages", "mazes", 0, 1, ALIKE, short=ALIKE,
     exits={"n": "a1", "e": "a5", "s": "a7"},
     feats=("maze",), label="Twisty 4")
room("a5", "Twisty Passages", "mazes", 1, 1, ALIKE, short=ALIKE,
     exits={"w": "a4", "e": "a6", "s": "a8"},
     feats=("maze",), label="Twisty 5")
room("a6", "Twisty Passages", "mazes", 2, 1, ALIKE, short=ALIKE,
     exits={"n": "a3", "w": "a5", "nw": "a2", "u": "brink"},
     aliases={"column": "u", "climb": "u"},
     feats=("maze", "column"), label="Twisty 6",
     scenery={"column orange": "An orange column climbs up to the brink of the pit."})
room("a7", "Dead End", "mazes", 0, 2, "Dead end.", short="Dead end.",
     exits={"n": "a4"}, feats=("deadend",), label="Dead End")
room("a8", "Dead End", "mazes", 1, 2, "Dead end.", short="Dead end.",
     exits={"n": "a5"}, feats=("deadend",), label="Dead End")

room("d1", "Maze, All Different", "mazes", 5, 0,
     "You are in a maze of twisting little passages, all different.",
     exits={"n": "long_hall_w", "e": "d2", "s": "d3"},
     feats=("maze",), label="Twisting")
room("d2", "Maze, All Different", "mazes", 6, 0,
     "You are in a little maze of twisty passages, all different.",
     exits={"w": "d1", "s": "d4"},
     feats=("maze",), label="Little Maze")
room("d3", "Maze, All Different", "mazes", 5, 1,
     "You are in a twisting maze of little passages, all different.",
     exits={"n": "d1", "e": "d4", "s": "d5"},
     feats=("maze",), label="Twisting Maze")
room("d4", "Maze, All Different", "mazes", 6, 1,
     "You are in a twisty little maze of passages, all different.",
     exits={"n": "d2", "w": "d3"},
     feats=("maze",), label="Twisty Maze")
room("d5", "Maze, All Different", "mazes", 5, 2,
     "You are in a little twisty maze of passages, all different. This "
     "branch ends in a small chamber.",
     exits={"n": "d3"},
     feats=("deadend",), label="Vending")

for _rid in ("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8",
             "d1", "d2", "d3", "d4", "d5"):
    ROOMS[_rid]["short"] = ROOMS[_rid]["long"]

# --------------------------------------------------------------------------
# Beyond the Chasm
#
#   x:  -1        0          1         2         3         4         5
# y-1                                         View
#                                               |
# y0                                          Warm ---- Boulders
#                                            /
# y1           ChasmNE -- Corridor -- Fork
#             /                          \
# y2  ChasmSW                            Limestone -- Barren F. -- Barren
# --------------------------------------------------------------------------

room("chasm_sw", "SW Side of Chasm", "far", -1, 2,
     "You are on one side of a large, deep chasm. A heavy white mist rising "
     "from below hides the far side. A rickety wooden bridge stretches "
     "north-east across the chasm into the mist. A sloping corridor leads "
     "up and away.",
     short="You're on the south-west side of the chasm.",
     exits={"u": "sloping", "ne": ("chasm_ne", "troll")},
     aliases={"cross": "ne", "bridge": "ne", "over": "ne", "corridor": "u"},
     feats=("chasm",), label="Chasm SW",
     scenery={"bridge": "Planks and fraying rope. It sways alarmingly in the updraught.",
              "chasm mist": "Bottomless, as far as you can tell."})

room("chasm_ne", "NE Side of Chasm", "far", 0, 1,
     "You are on the far side of the chasm. The rickety bridge leads back "
     "south-west across it. A corridor leads east, and the air is noticeably "
     "warmer.",
     short="You're on the north-east side of the chasm.",
     exits={"sw": "chasm_sw", "e": "corridor"},
     aliases={"cross": "sw", "bridge": "sw", "over": "sw"},
     feats=("chasm",), label="Chasm NE",
     scenery={"bridge": "Planks and fraying rope. It sways alarmingly in the updraught."})

room("corridor", "Long Corridor", "far", 1, 1,
     "You're in a long east/west corridor. A faint rumbling can be heard in "
     "the distance.",
     short="You're in the long corridor.",
     exits={"w": "chasm_ne", "e": "fork"},
     feats=("tunnel",), label="Corridor")

room("fork", "Fork in Path", "far", 2, 1,
     "The path forks here. The left fork climbs north-east, towards a dull "
     "rumbling; the right fork runs south-east down a gentle slope. The "
     "main corridor leads west.",
     short="You're at the fork in the path.",
     exits={"w": "corridor", "ne": "warm", "se": "limestone"},
     aliases={"left": "ne", "right": "se"},
     feats=("junction",), label="Fork")

room("warm", "Junction with Warm Walls", "far", 3, 0,
     "The walls are warm here, and glow a dull red. From the north comes a "
     "steady roar, so loud the whole cave seems to tremble. Another passage "
     "leads east, and the fork is back to the south-west.",
     short="You're at the junction with warm walls.",
     exits={"sw": "fork", "n": "view", "e": "boulders"},
     lit=True, feats=("warm",), label="Warm Walls")

room("view", "Breath-taking View", "far", 3, -1,
     "You stand on a ledge overlooking an immense cavern. Far below, an "
     "active volcano heaves molten rock into the air; the lava falls back in "
     "glowing curtains and lights the whole vault blood-red. The heat is "
     "fierce. Across the gulf, a waterfall plunges into the glare and boils "
     "away as steam. The only way back is south.",
     short="You're at the breath-taking view.",
     exits={"s": "warm"},
     lit=True, scene="volcano", label="The View",
     scenery={"volcano lava": "Hypnotic, terrifying and very, very hot.",
              "waterfall steam": "It never reaches the bottom."},
     nogo="Don't be ridiculous! It's a very long way down.")

room("boulders", "Chamber of Boulders", "far", 4, 0,
     "You are in a small chamber crammed with large boulders. The walls "
     "are so warm that the air is almost stifling. The only exit is a crawl "
     "to the west, through which comes a low rumbling.",
     short="You're in the chamber of boulders.",
     exits={"w": "warm"},
     feats=("boulders", "warm"), label="Boulders")

room("limestone", "Limestone Passage", "far", 3, 2,
     "You are walking along a gently sloping passage of white limestone, "
     "rich with fossils. It climbs north-west to the fork and runs east "
     "towards a barren room.",
     short="You're in the limestone passage.",
     exits={"nw": "fork", "e": "barren_front"},
     feats=("tunnel", "limestone"), label="Limestone")

room("barren_front", "Front of Barren Room", "far", 4, 2,
     "You are standing at the entrance to a large, barren room. A sign "
     "posted above the entrance reads: 'CAUTION! BEAR IN ROOM!'",
     short="You're at the front of the barren room.",
     exits={"w": "limestone", "e": "barren"},
     aliases={"in": "e", "enter": "e"},
     feats=("sign",), label="Barren Front",
     scenery={"sign": "'CAUTION! BEAR IN ROOM!' Somebody has underlined 'BEAR' twice."})

room("barren", "Barren Room", "far", 5, 2,
     "You are inside a barren room. The middle of the room is empty except "
     "for dust, and marks in the dust lead to the far end. The only way out "
     "is back west.",
     short="You're in the barren room.",
     exits={"w": "barren_front"},
     aliases={"out": "w"},
     feats=("dust",), label="Barren Room")

# --------------------------------------------------------------------------
# The Repository: reached only when the cave closes.
# --------------------------------------------------------------------------

room("repo_ne", "NE End of Repository", "repo", 1, 0,
     "You are at the north-east end of an immense room, larger even than "
     "the Giant Room. It seems to be a storeroom for the whole adventure. "
     "Smoky torches far overhead light piles of empty bottles, a nursery of "
     "young beanstalks murmuring 'water', a bed of oysters, and a heap of "
     "brass lanterns. Off to one side, a great many dwarves lie snoring on "
     "the floor. A notice reads: 'DO NOT DISTURB THE DWARVES!' An enormous "
     "mirror runs the length of the room to the south-west end.",
     short="You're at the north-east end of the repository.",
     exits={"sw": "repo_sw"},
     scene="repository", label="Repository NE",
     scenery={"dwarves dwarf": "Dozens of them, snoring. Best let sleeping dwarves lie.",
              "bottles lanterns lamps beanstalks oysters plants": "Exhibits, every one. You can look but you'd better not touch.",
              "notice sign": "'DO NOT DISTURB THE DWARVES!'",
              "mirror": "It runs the whole length of the room."})

room("repo_sw", "SW End of Repository", "repo", 0, 1,
     "You are at the south-west end of the repository. To one side is a pit "
     "full of fierce green snakes; on the other, a row of wicker cages, each "
     "holding a sulky little bird. A great many velvet pillows are scattered "
     "about. Set into the floor is a steel grate with a sign beside it: "
     "'TREASURE VAULT. KEYS IN MAIN OFFICE.'",
     short="You're at the south-west end of the repository.",
     exits={"ne": "repo_ne"},
     scene="repository", label="Repository SW",
     scenery={"snakes pit": "A writhing pit of snakes. No thank you.",
              "cages birds": "Each little bird glares at you.",
              "pillows": "Velvet pillows, all exactly like the one in the Soft Room.",
              "grate sign": "'TREASURE VAULT. KEYS IN MAIN OFFICE.' You don't have the keys.",
              "mirror": "It runs the whole length of the room."})


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------

ITEMS = {}


def item(iid, name, nouns, start, here, adjectives=(), examine=None,
         portable=True, treasure=0, initial=None, state=None, also=(),
         read=None):
    if iid in ITEMS:
        raise ValueError("duplicate item id %r" % iid)
    ITEMS[iid] = {
        "id": iid,
        "name": name,
        "nouns": tuple(nouns),
        "adjectives": tuple(adjectives),
        "start": start,
        "here": here,
        "initial": initial,
        "examine": examine,
        "portable": portable,
        "treasure": treasure,
        "state": state,
        "also": tuple(also),
        "read": read,
    }


# Tools and supplies ------------------------------------------------------

item("keys", "set of keys", ("keys", "key", "keyring"), "building",
     "There are some keys on the ground here.",
     adjectives=("set", "of", "brass", "iron"),
     examine="An iron ring of keys. One of them looks just right for a grate.")
item("lamp", "brass lantern", ("lamp", "lantern", "light", "torch"), "building",
     {"off": "There is a shiny brass lamp nearby.",
      "on": "There is a lamp shining nearby."},
     adjectives=("brass", "shiny"), state="off",
     examine="A sturdy brass lantern with a battery compartment.")
item("food", "tasty food", ("food", "rations", "ration", "snack", "packet", "lunch"),
     "building", "There is food here.",
     adjectives=("tasty",),
     examine="Sandwiches and a slab of fruit cake, wrapped in greaseproof paper.")
item("bottle", "small bottle", ("bottle", "jar", "flask"), "building",
     {"water": "There is a bottle of water here.",
      "oil": "There is a bottle of oil here.",
      "empty": "There is an empty bottle here."},
     adjectives=("small", "glass"), state="water")
item("cage", "wicker cage", ("cage",), "cobble",
     "There is a small wicker cage discarded nearby.",
     adjectives=("wicker", "small"),
     examine="A little wicker cage with a hinged door. Just right for a bird.")
item("rod", "black rod", ("rod", "stick", "wand"), "debris",
     "A three-foot black rod with a rusty star on one end lies nearby.",
     adjectives=("black", "rusty", "star", "three-foot"),
     examine="A three-foot black rod with a rusty star on one end. It hums very faintly.")
item("bird", "little bird", ("bird", "songbird"), "bird_ch",
     "A cheerful little bird is sitting here singing.",
     adjectives=("little", "cheerful", "small"),
     examine="A cheerful little songbird. It eyes you warily.")
item("pillow", "velvet pillow", ("pillow", "cushion"), "soft",
     "A small velvet pillow lies on the floor.",
     adjectives=("velvet", "small", "soft"),
     examine="Plump, soft and red. Just the thing to cushion something fragile.")
item("magazine", "'Spelunker Today'", ("magazine", "magazines", "issue", "issues", "spelunker"),
     "anteroom", "There are a few recent issues of 'Spelunker Today' magazine here.",
     adjectives=("spelunker", "today", "recent"),
     examine="Several back issues of 'Spelunker Today'.",
     read="The articles are all written in Dwarvish runes. You can't make out a word, but the cover picture is nice.")
item("axe", "dwarvish axe", ("axe", "ax", "hatchet"), "void",
     "There is a little axe here.",
     adjectives=("little", "dwarvish", "dwarf's"),
     examine="A small but wickedly sharp throwing axe.")
item("batteries", "fresh batteries", ("batteries", "battery", "pack"), "void",
     {"fresh": "There are fresh batteries here.",
      "worn": "Some worn-out batteries have been discarded nearby."},
     adjectives=("fresh", "worn", "worn-out"), state="fresh",
     examine="A pack of lamp batteries.")
item("dynamite", "black rod with rusty marks", ("rod", "dynamite", "marks"), "void",
     "A black rod with rusty marks on its end lies here.",
     adjectives=("black", "rusty", "marked"),
     examine="It's not quite the same as the rod with the star. The 'rust' smells of gunpowder.")

# Fixtures ------------------------------------------------------------------

item("grate", "steel grate", ("grate", "grating", "bars"), "depression",
     {"locked": "The grate is locked.", "open": "The grate is open."},
     adjectives=("steel", "strong"), portable=False, state="locked",
     also=("below_grate",),
     examine="A strong steel grate set in concrete, with a heavy lock.")
item("snake", "huge snake", ("snake", "serpent"), "mtking",
     "A huge snake coils across the floor, barring the way!",
     adjectives=("huge", "fierce", "green"), portable=False,
     examine="It's enormous, and it doesn't care for you at all.")
item("dragon", "dragon", ("dragon", "body", "corpse"), "lair",
     {"alive": "A huge, fierce dragon bars the way! It is sprawled across a magnificent Persian rug.",
      "dead": "The body of the slain dragon lies off to one side."},
     adjectives=("huge", "fierce", "green", "dead"), portable=False, state="alive",
     examine="Scales like roof slates and breath like a foundry.")
item("troll", "burly troll", ("troll",), "chasm_sw",
     "A burly troll stands by the bridge and insists you throw him a treasure before you may cross.",
     adjectives=("burly",), portable=False,
     examine="He's large, warty and businesslike. 'Treasure,' he says, holding out a hand.")
item("bear", "cave bear", ("bear",), "barren",
     {"chained": "There is a ferocious cave bear eyeing you from the far end of the room!",
      "fed": "There is a gentle cave bear sitting placidly in one corner.",
      "free": "There is a contented-looking bear wandering about nearby.",
      "left": "A contented-looking bear sits here, unwilling to go any further."},
     adjectives=("cave", "ferocious", "gentle", "friendly"), portable=False, state="chained",
     examine="A big brown cave bear.")
item("plant", "plant", ("plant", "beanstalk", "stalk"), "west_pit",
     {0: "A tiny plant grows in the pit, murmuring 'Water, water...'",
      1: "A twelve-foot beanstalk sprouts from the pit floor, bellowing 'WATER! WATER!'",
      2: "A gigantic beanstalk climbs all the way up to the hole in the ceiling."},
     adjectives=("tiny", "little", "giant", "gigantic", "bean"), portable=False, state=0)
item("clam", "giant clam", ("clam", "oyster", "shell"), "shell",
     {"closed": "There is an enormous clam here with its shell tightly closed.",
      "open": "There is an enormous oyster here with its shell gaping open."},
     adjectives=("giant", "enormous", "huge"), portable=False, state="closed",
     examine="It must be four feet across.")
item("door", "iron door", ("door", "hinges"), "immense",
     {"rusty": "A massive, rusty iron door blocks the way.",
      "oiled": "A massive iron door stands open."},
     adjectives=("massive", "rusty", "iron"), portable=False, state="rusty",
     also=("waterfall",),
     examine="Massive, iron, and rusted almost solid. Its hinges are thick with rust.")
item("machine", "vending machine", ("machine", "vending", "slot", "instructions"), "d5",
     "There is a massive vending machine here. The instructions read: 'Insert coins to receive fresh batteries.'",
     adjectives=("vending", "massive"), portable=False,
     read="'Insert coins to receive fresh batteries.'",
     examine="A battered vending machine with a coin slot and a delivery tray.")

# Treasures (15) ---------------------------------------------------------------

item("nugget", "large gold nugget", ("nugget", "gold"), "nugget_rm",
     "There is a large gold nugget here.",
     initial="There is a large sparkling nugget of gold here!",
     adjectives=("large", "gold", "sparkling"), treasure=10,
     examine="It's the size of a fist and very, very heavy.")
item("diamonds", "several diamonds", ("diamonds", "diamond", "gems"), "fissure_w",
     "There are diamonds here!", adjectives=("several",), treasure=10,
     examine="Half a dozen fine diamonds, each as big as a fingernail.")
item("silver", "bars of silver", ("silver", "bars", "bar", "ingots"), "low_ns",
     "There are bars of silver here!", adjectives=("silver",), treasure=10)
item("jewelry", "precious jewellery", ("jewellery", "jewelry", "jewels", "jewel"), "south_ch",
     "There is precious jewellery here!", adjectives=("precious",), treasure=10)
item("coins", "rare coins", ("coins", "coin", "money"), "west_ch",
     "There are many coins here!", adjectives=("rare", "many"), treasure=10,
     examine="Old gold and silver coins, stamped with the heads of forgotten kings.")
item("chest", "treasure chest", ("chest", "box"), "a7",
     "The pirate's treasure chest is here!", adjectives=("treasure", "pirate's", "pirate"),
     treasure=12, examine="A heavy iron-bound chest. Inside, it's full of more treasure.")
item("eggs", "nest of golden eggs", ("eggs", "egg", "nest"), "giant",
     "There is a large nest here, full of golden eggs!",
     adjectives=("golden", "gold"), treasure=14)
item("trident", "jewelled trident", ("trident",), "waterfall",
     "There is a jewel-encrusted trident here!", adjectives=("jewelled", "jeweled"),
     treasure=14, examine="Three gilded prongs, studded with gems. The points look strong.")
item("vase", "Ming vase", ("vase", "ming", "urn", "shards", "pottery"), "oriental",
     {"ok": "There is a delicate, precious Ming vase here!",
      "broken": "The floor is littered with worthless shards of pottery."},
     adjectives=("ming", "delicate", "precious"), treasure=14, state="ok",
     examine="Very old, very fine and very fragile.")
item("emerald", "egg-sized emerald", ("emerald", "gem"), "plover",
     "There is an emerald here the size of a plover's egg!",
     adjectives=("egg-sized", "plover's"), treasure=14)
item("pyramid", "platinum pyramid", ("pyramid", "platinum"), "dark",
     "There is a platinum pyramid here, eight inches on a side!",
     adjectives=("platinum",), treasure=14)
item("pearl", "glistening pearl", ("pearl",), "void",
     "Off to one side lies a glistening pearl!", adjectives=("glistening",), treasure=14)
item("rug", "Persian rug", ("rug", "carpet"), "lair",
     "There is a Persian rug spread out on the floor!",
     adjectives=("persian", "magnificent"), treasure=14)
item("spices", "rare spices", ("spices", "spice"), "boulders",
     "There are rare spices here!", adjectives=("rare",), treasure=14,
     examine="Cinnamon, saffron and something you can't name. They smell wonderful.")
item("chain", "golden chain", ("chain",), "barren",
     {"locked": "The bear is held back by a solid gold chain.",
      "unlocked": "There is a golden chain lying in a heap on the floor!"},
     adjectives=("golden", "gold", "solid"), treasure=14, state="locked")

TREASURES = [i for i in ITEMS if ITEMS[i]["treasure"]]

# The order in which the itinerary lists treasures.
TREASURE_ORDER = ["nugget", "diamonds", "silver", "jewelry", "coins", "chest",
                  "eggs", "trident", "vase", "emerald", "pyramid", "pearl",
                  "rug", "spices", "chain"]

START_ROOM = "road"
STORE_ROOM = "building"
