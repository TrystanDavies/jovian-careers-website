"""Words the game understands."""

from .world import ITEMS, ROOMS

DIR_WORDS = {
    "n": "n", "north": "n",
    "s": "s", "south": "s",
    "e": "e", "east": "e",
    "w": "w", "west": "w",
    "ne": "ne", "northeast": "ne", "north-east": "ne",
    "nw": "nw", "northwest": "nw", "north-west": "nw",
    "se": "se", "southeast": "se", "south-east": "se",
    "sw": "sw", "southwest": "sw", "south-west": "sw",
    "u": "u", "up": "u", "upward": "u", "upwards": "u", "upstairs": "u",
    "ascend": "u",
    "d": "d", "down": "d", "downward": "d", "downwards": "d",
    "downstairs": "d", "descend": "d",
}

# Words that mean "go somewhere" but depend on where you are.
GENERIC_MOVES = {"in", "inside", "out", "outside", "enter", "exit", "leave",
                 "cross", "over", "climb"}
ALIAS_WORDS = set(GENERIC_MOVES)
for _r in ROOMS.values():
    ALIAS_WORDS.update(_r["aliases"])

MAGIC_WORDS = {"xyzzy", "plugh", "plover", "fee", "fie", "foe", "foo"}

VERBS = {
    "go": ["go", "walk", "run", "travel", "head", "proceed", "move"],
    "goto": ["goto"],
    "back": ["back", "retreat", "return", "retrace", "backtrack"],
    "look": ["look", "l", "describe", "redescribe"],
    "examine": ["examine", "x", "inspect", "check", "study", "search", "view"],
    "read": ["read", "peruse"],
    "take": ["take", "get", "grab", "carry", "catch", "keep", "pick", "collect", "steal"],
    "drop": ["drop", "discard", "release", "free", "dump"],
    "put": ["put", "place", "insert", "set", "stow"],
    "give": ["give", "offer", "pay", "hand", "bribe"],
    "throw": ["throw", "toss", "hurl", "chuck", "fling"],
    "inventory": ["inventory", "i", "inv", "invent"],
    "open": ["open", "pry", "prise"],
    "close": ["close", "shut"],
    "lock": ["lock"],
    "unlock": ["unlock", "unchain"],
    "light": ["light", "ignite", "illuminate", "on"],
    "extinguish": ["extinguish", "douse", "unlight", "off"],
    "fill": ["fill", "refill"],
    "pour": ["pour", "empty", "spill", "tip"],
    "water": ["water", "irrigate"],
    "oil": ["oil", "lubricate", "grease"],
    "drink": ["drink", "sip", "quaff", "slurp"],
    "eat": ["eat", "consume", "devour", "munch"],
    "wave": ["wave", "shake", "swing", "brandish", "flourish"],
    "feed": ["feed"],
    "attack": ["attack", "kill", "fight", "hit", "strike", "slay", "punch",
               "kick", "stab", "murder", "smite"],
    "break": ["break", "smash", "shatter", "destroy"],
    "wake": ["wake", "awaken", "disturb", "rouse", "prod"],
    "climb": ["climb", "scale", "clamber", "shin"],
    "cross": ["cross"],
    "jump": ["jump", "leap", "hop"],
    "say": ["say", "speak", "shout", "yell", "chant", "utter", "whisper", "call"],
    "blast": ["blast", "detonate", "explode", "ignite-dynamite"],
    "find": ["find", "where", "locate", "seek"],
    "exits": ["exits", "directions", "ways", "routes"],
    "map": ["map"],
    "itinerary": ["itinerary", "journal", "log", "journey", "diary", "history"],
    "score": ["score", "points"],
    "hint": ["hint", "hints", "clue", "clues"],
    "help": ["help", "?", "commands", "instructions"],
    "verbose": ["verbose", "long"],
    "brief": ["brief", "short", "terse"],
    "save": ["save"],
    "restore": ["restore", "load", "resume"],
    "restart": ["restart", "reset", "new"],
    "undo": ["undo", "oops"],
    "again": ["again", "g", "repeat"],
    "wait": ["wait", "z", "rest", "pause", "sleep"],
    "quit": ["quit", "q"],
    "about": ["about", "credits", "version", "info"],
    "baud": ["baud", "speed", "modem"],
    "yes": ["yes", "y", "yep", "sure", "ok", "okay", "certainly", "aye"],
    "no": ["no", "nope", "nah"],
    "listen": ["listen", "hear"],
    "smell": ["smell", "sniff"],
    "swim": ["swim", "wade", "dive"],
    "sing": ["sing", "hum", "whistle", "dance"],
    "replace": ["replace", "change", "recharge"],
    "out": ["exit", "leave", "out", "outside"],
    "enter": ["enter", "in", "inside"],
}

VERB_OF = {}
for _canon, _words in VERBS.items():
    for _w in _words:
        VERB_OF.setdefault(_w, _canon)

# Verbs that never take a turn.
META_VERBS = {"inventory", "look", "exits", "map", "itinerary", "score", "hint",
              "help", "verbose", "brief", "save", "restore", "restart", "undo",
              "again", "quit", "about", "baud", "find", "yes", "no"}

PREPOSITIONS = {"with", "using", "in", "into", "inside", "on", "onto", "at",
                "to", "from", "under", "upon"}

ARTICLES = {"the", "a", "an", "some", "my", "this", "that", "these", "those",
            "please", "carefully", "quickly"}

NOUN_WORDS = set()
for _it in ITEMS.values():
    NOUN_WORDS.update(_it["nouns"])
    NOUN_WORDS.update(_it["adjectives"])
for _r in ROOMS.values():
    for _key in _r["scenery"]:
        NOUN_WORDS.update(_key.split())
NOUN_WORDS.update({"water", "oil", "all", "everything", "it", "them", "dwarf",
                   "dwarves", "treasure", "treasures", "wall", "walls", "ceiling",
                   "floor", "ground", "rock", "rocks", "cave", "passage"})


def completion_words():
    """Words worth offering for tab completion in the UI."""
    words = set(VERB_OF) | set(DIR_WORDS) | MAGIC_WORDS | NOUN_WORDS
    return sorted(w for w in words if len(w) > 2 and w.isalpha())
