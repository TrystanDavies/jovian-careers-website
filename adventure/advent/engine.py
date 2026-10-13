"""The game engine: state, commands, puzzles, scoring, undo and saving.

All game state lives in one JSON-friendly dict (Game.state) so that saving,
restoring and UNDO are just a matter of copying it.  Randomness is derived
from the game's seed and the turn number, which keeps everything
reproducible.
"""

import json
import os
import random
import re
from collections import deque

from . import hints as hint_mod
from . import npcs
from .parser import parse
from .vocab import DIR_WORDS, META_VERBS
from .world import (DIR_NAMES, DIRECTIONS, HIDDEN_GATES, ITEMS, REGIONS,
                    ROOMS, START_ROOM, STORE_ROOM, TREASURES)

MAX_CARRY = 10
LAMP_START = 1200
BATTERY_POWER = 2500
CLOSING_TURNS = 12
LIVES = 3
MAX_SCORE = 350
UNDO_DEPTH = 50
BAUD_RATES = (0, 110, 300, 1200, 2400, 4800, 9600, 19200)
DEFAULT_BAUD = 2400
SAVE_VERSION = 1

FEE_FIE = ("fee", "fie", "foe", "foo")

BANNER = (
    "COLOSSAL CAVE\n"
    "Somewhere nearby is Colossal Cave, where others have found fortunes in "
    "treasure and gold, though it is rumoured that some who enter are never "
    "seen again. Magic is said to work in the cave.\n"
    "Bring any treasure you find back to the well house. Type HELP for "
    "commands, HINT if you're stuck, and MAP to see where you've been."
)

RANKS = [
    (35, "You are obviously a rank amateur. Better luck next time."),
    (99, "Your score qualifies you as a novice class adventurer."),
    (129, "You have achieved the rating: 'Experienced Adventurer'."),
    (199, "You may now consider yourself a 'Seasoned Adventurer'."),
    (249, "You have reached 'Junior Master' status."),
    (299, "Your score puts you in Master Adventurer Class C."),
    (329, "Your score puts you in Master Adventurer Class B."),
    (349, "Your score puts you in Master Adventurer Class A."),
    (9999, "All of Adventuredom gives tribute to you, Adventurer Grandmaster!"),
]

HELP_TEXT = (
    "Type commands in plain English, e.g. TAKE LAMP, GO NORTH, UNLOCK GRATE "
    "WITH KEYS. Chain them: TAKE LAMP THEN EAST.\n"
    "Moving: N S E W NE NW SE SW UP DOWN, IN, OUT, CROSS, CLIMB, BACK, "
    "GO TO <place> (or click a room on the map), EXITS.\n"
    "Things: TAKE, DROP, PUT x IN/ON y, GIVE x TO y, THROW x AT y, EXAMINE "
    "(X), READ, OPEN, CLOSE, LOCK, UNLOCK, LIGHT, EXTINGUISH, FILL, POUR, "
    "WATER, OIL, DRINK, EAT, WAVE, FEED, ATTACK, BREAK, WAKE. TAKE ALL works, "
    "and so does DROP TREASURES.\n"
    "Information: LOOK (L), INVENTORY (I), ITINERARY, MAP, WHERE IS x, "
    "SCORE, HINT, VERBOSE/BRIEF.\n"
    "Game: SAVE [name], RESTORE [name], UNDO, AGAIN (G), WAIT (Z), RESTART, "
    "QUIT, BAUD 300/1200/2400/9600/0, ABOUT.\n"
    "Magic words are said simply by typing them."
)

ABOUT_TEXT = (
    "Colossal Cave, reworked. Inspired by Colossal Cave Adventure by Will "
    "Crowther (1976) and Don Woods (1977). This version keeps the cave, its "
    "treasures and its puzzles, but every passage now leads where it says "
    "and can be walked back, and the map draws itself as you go."
)


class Result(object):
    def __init__(self, lines, view):
        self.lines = lines
        self.view = view

    def to_dict(self):
        return {"lines": self.lines, "view": self.view}


class Ref(object):
    """Something a noun phrase referred to that isn't a plain item."""

    def __init__(self, kind, key=None, text=None):
        self.kind = kind     # 'scenery' | 'liquid' | 'dwarf' | 'global'
        self.key = key
        self.text = text


def _norm(text):
    text = text.lower().replace("'", "")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    words = [w for w in text.split() if w not in ("the", "a", "an", "of", "to", "at")]
    return " ".join(words)


class Game(object):

    def __init__(self, seed=None, peaceful=False, save_dir=None, baud=DEFAULT_BAUD):
        self.save_dir = save_dir
        self.peaceful = peaceful
        self.buf = []
        self.undo_stack = []
        self.last_text = None
        self.new_game(seed, baud=baud)

    # ------------------------------------------------------------------
    # Setting up
    # ------------------------------------------------------------------

    def new_game(self, seed=None, baud=None):
        if seed is None:
            seed = random.SystemRandom().randrange(1, 10 ** 9)
        items = {}
        for iid, it in ITEMS.items():
            items[iid] = {"loc": it["start"], "state": it["state"], "moved": False}
        self.state = {
            "version": SAVE_VERSION,
            "seed": seed,
            "peaceful": self.peaceful,
            "room": START_ROOM,
            "came_from": None,
            "turns": 0,
            "items": items,
            "visited": {START_ROOM: 0},
            "seen": {},
            "found": [],
            "flags": {},
            "lamp": LAMP_START,
            "deaths": 0,
            "log": [],
            "pending": None,
            "fee": 0,
            "verbose": False,
            "baud": DEFAULT_BAUD if baud is None else baud,
            "dwarf": {"here": None, "armed": False, "first": False, "remaining": 5},
            "pirate": {"done": False},
            "closing": None,
            "closed": False,
            "blast": 0,
            "game_over": False,
            "won": False,
            "quit": False,
            "last_noun": None,
        }
        self.undo_stack = []
        self.last_text = None
        self.buf = []
        self.log("Set out from the end of the road.", "start")
        self.say(BANNER)
        self.describe(full=True)
        self.state["last_output"] = list(self.buf)
        return self.buf

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    @property
    def s(self):
        return self.state

    def say(self, text):
        if text:
            self.buf.append(text)

    def group_since(self, mark):
        """Fold the messages said since `mark` into one paragraph."""
        if len(self.buf) - mark > 1:
            self.buf[mark:] = ["\n".join(self.buf[mark:])]

    def log(self, text, kind="event"):
        self.state["log"].append({"t": self.state["turns"], "text": text,
                                  "kind": kind, "room": self.state["room"]})
        del self.state["log"][:-300]

    def rng(self, salt):
        return random.Random("%s:%s:%s" % (self.state["seed"], self.state["turns"], salt))

    @property
    def room(self):
        return ROOMS[self.state["room"]]

    def flag(self, name):
        return self.state["flags"].get(name)

    def set_flag(self, name, value=True):
        self.state["flags"][name] = value

    # Items -------------------------------------------------------------

    def loc(self, iid):
        return self.state["items"][iid]["loc"]

    def set_loc(self, iid, where):
        self.state["items"][iid]["loc"] = where

    def istate(self, iid):
        return self.state["items"][iid]["state"]

    def set_istate(self, iid, value):
        self.state["items"][iid]["state"] = value

    def name(self, iid):
        if iid == "vase" and self.istate("vase") == "broken":
            return "shards of pottery"
        if iid == "bottle":
            return {"water": "bottle of water", "oil": "bottle of oil"}.get(
                self.istate("bottle"), "small bottle")
        if iid == "batteries" and self.istate("batteries") == "worn":
            return "worn-out batteries"
        return ITEMS[iid]["name"]

    def the(self, iid):
        return "the " + self.name(iid)

    def carried(self, iid):
        where = self.loc(iid)
        if where == "player":
            return True
        if where.startswith("in:"):
            return self.carried(where[3:])
        return False

    def at_room(self, iid, rid=None):
        rid = rid or self.state["room"]
        where = self.loc(iid)
        if where == rid:
            return True
        if where.startswith("in:"):
            return self.at_room(where[3:], rid)
        return where != "void" and rid in ITEMS[iid]["also"]

    def present(self, iid):
        return self.carried(iid) or self.at_room(iid)

    def inventory_ids(self):
        return [i for i in ITEMS if self.loc(i) == "player"]

    def room_ids(self):
        """Top-level items lying in the current room (not inside things)."""
        rid = self.state["room"]
        return [i for i in ITEMS if self.loc(i) == rid or
                (self.loc(i) != "void" and rid in ITEMS[i]["also"])]

    def contents(self, container):
        return [i for i in ITEMS if self.loc(i) == "in:" + container]

    def lamp_on(self):
        return self.istate("lamp") == "on" and self.state["lamp"] > 0

    def lit(self, rid=None):
        rid = rid or self.state["room"]
        if ROOMS[rid]["lit"]:
            return True
        return self.lamp_on() and (self.carried("lamp") or self.at_room("lamp", rid))

    def broken(self, iid):
        return iid == "vase" and self.istate("vase") == "broken"

    def stored(self, iid):
        return self.loc(iid) == STORE_ROOM and not self.broken(iid)

    def mark_found(self, iid):
        if ITEMS[iid]["treasure"] and iid not in self.state["found"]:
            self.state["found"].append(iid)
            self.log("Found the %s!" % self.name(iid), "treasure")

    # ------------------------------------------------------------------
    # The main entry point
    # ------------------------------------------------------------------

    def do(self, text):
        """Run one line of input. Returns a Result."""
        self.buf = []
        text = (text or "").strip()
        if not text:
            self.say("I beg your pardon?")
            return self.result()

        cmds = parse(text)
        if not cmds:
            self.say("I beg your pardon?")
            return self.result()

        first = cmds[0].verb
        if first == "undo" and len(cmds) == 1:
            self.undo()
            return self.result()
        if first == "again" and len(cmds) == 1:
            if not self.last_text:
                self.say("There's nothing to repeat yet.")
                return self.result()
            text = self.last_text
            cmds = parse(text)

        if any(c.verb not in META_VERBS for c in cmds):
            self.undo_stack.append(json.dumps(self.state))
            del self.undo_stack[:-UNDO_DEPTH]
        if cmds[0].verb not in ("again", "undo"):
            self.last_text = text

        for i, cmd in enumerate(cmds):
            if self.state["game_over"] and cmd.verb not in (
                    "restart", "restore", "score", "help", "about", "baud",
                    "itinerary", "map", "yes", "no", "save"):
                self.say("The game is over. Type RESTART to play again, or UNDO to take back that last move.")
                break
            before = len(self.buf)
            self.run(cmd)
            if self.state["game_over"]:
                break
            # A dramatic interruption ends a chain of commands.
            if i + 1 < len(cmds) and self.state["dwarf"]["here"] == self.state["room"] \
                    and len(self.buf) > before and cmd.verb not in META_VERBS:
                self.say("(You stop what you were doing.)")
                break
        return self.result()

    def result(self):
        self.state["last_output"] = list(self.buf)
        from .view import build_view
        return Result(list(self.buf), build_view(self))

    def run(self, cmd):
        if cmd.error:
            self.say(cmd.error)
            return
        pending = self.state["pending"]
        if pending and cmd.verb not in ("yes", "no"):
            self.state["pending"] = None
        handler = getattr(self, "v_" + cmd.verb.replace("-", "_"), None)
        if handler is None:
            self.say("I don't know how to do that.")
            return
        took_turn = handler(cmd)
        if took_turn is None:
            took_turn = cmd.verb not in META_VERBS
        if took_turn and not self.state["game_over"]:
            self.tick()

    # ------------------------------------------------------------------
    # Time passing
    # ------------------------------------------------------------------

    def tick(self):
        s = self.state
        s["turns"] += 1
        self.drain_lamp()
        npcs.step(self)
        if s["game_over"]:
            return
        self.check_closing()

    def drain_lamp(self):
        s = self.state
        if self.istate("lamp") != "on":
            return
        s["lamp"] -= 1
        near = self.carried("lamp") or self.at_room("lamp")
        if s["lamp"] in (100, 30) and near:
            if self.present("batteries") and self.istate("batteries") == "fresh":
                self.replace_batteries(auto=True)
                return
            self.say("Your lamp is getting dim. You'd best start wrapping this up, "
                     "unless you can find some fresh batteries.")
        if s["lamp"] <= 0:
            s["lamp"] = 0
            self.set_istate("lamp", "off")
            if near:
                self.say("Your lamp has run out of power.")
                if not self.lit():
                    self.say("It is now pitch dark.")

    def check_closing(self):
        s = self.state
        if s["closed"]:
            return
        if s["closing"] is None:
            if all(self.stored(t) for t in TREASURES):
                s["closing"] = CLOSING_TURNS
                self.say("A sepulchral voice reverberates through the cave: "
                         "'Cave closing soon. All adventurers exit immediately "
                         "through the main office.' (You have a feeling you "
                         "should simply wait.)")
                self.log("The cave began to close.", "event")
            return
        s["closing"] -= 1
        if s["closing"] <= 0:
            self.close_cave()

    def close_cave(self):
        s = self.state
        for iid in ITEMS:
            if self.carried(iid):
                self.set_loc(iid, "void")
        self.set_istate("lamp", "off")
        s["dwarf"]["here"] = None
        s["closed"] = True
        s["closing"] = 0
        self.set_loc("dynamite", "repo_sw")
        self.say("The sepulchral voice intones, 'The cave is now closed.' As "
                 "the echoes fade there is a blinding flash of light, and a "
                 "small puff of orange smoke. When your eyes refocus, you are "
                 "somewhere quite new, and your pockets are empty.")
        self.log("The cave closed around you.", "event")
        self.enter("repo_ne", teleport=True)

    # ------------------------------------------------------------------
    # Describing things
    # ------------------------------------------------------------------

    def exit_dirs(self, rid=None, for_dark=False):
        """Exit directions worth mentioning from a room."""
        rid = rid or self.state["room"]
        out = []
        for d in DIRECTIONS:
            ex = ROOMS[rid]["exits"].get(d)
            if not ex:
                continue
            target, gate = ex
            if gate in HIDDEN_GATES and not self.gate(gate, target, rid=rid)[0]:
                continue
            if for_dark and target != self.state["came_from"] and target not in self.state["visited"]:
                continue
            out.append(d)
        return out

    def exits_line(self):
        dirs = self.exit_dirs()
        if not dirs:
            return "There are no obvious exits."
        names = [DIR_NAMES[d] for d in dirs]
        return "Exits: " + ", ".join(names) + "."

    def item_text(self, iid):
        it = ITEMS[iid]
        st = self.state["items"][iid]
        if iid == "rug" and self.istate("dragon") == "alive" and self.at_room("dragon"):
            return None
        if iid == "chain" and st["state"] == "locked" and not self.at_room("bear"):
            return None
        if iid == "cage" and self.loc("bird") == "in:cage":
            return "There is a little bird in a wicker cage here."
        if it["initial"] and not st["moved"]:
            return it["initial"]
        here = it["here"]
        if isinstance(here, dict):
            return here.get(st["state"], here.get(str(st["state"])))
        return here

    def room_extras(self):
        s = self.state
        rid = s["room"]
        out = []
        if rid in ("fissure_e", "fissure_w") and self.flag("bridge"):
            out.append("A crystal bridge now spans the fissure.")
        if rid in ("twopit_w", "twopit_e"):
            stage = self.istate("plant")
            if stage == 1:
                out.append("The top of a twelve-foot beanstalk pokes up out of the west pit.")
            elif stage == 2:
                out.append("A gigantic beanstalk rises out of the west pit and disappears "
                           "through the hole in the ceiling.")
        if rid == "y2" and self.rng("plugh").random() < 0.3:
            out.append("A hollow voice says 'PLUGH'.")
        return out

    def describe(self, full=False):
        s = self.state
        r = self.room
        if not self.lit():
            msg = ("It is pitch dark. If you go on you'll probably bump into something. "
                   "You can feel your way back along a passage you know")
            if self.present("lamp"):
                msg += ", or light your lamp."
            else:
                msg += "."
            self.say(msg)
            return
        lines = [r["name"], r["long"] if (full or s["verbose"]) else r["short"]]
        lines.extend(self.room_extras())
        for iid in self.room_ids():
            text = self.item_text(iid)
            if text:
                lines.append(text)
            self.note_seen(iid)
        if s["dwarf"]["here"] == s["room"]:
            lines.append("There is a threatening little dwarf in the room with you!")
        lines.append(self.exits_line())
        self.say("\n".join(lines))

    def note_seen(self, iid):
        self.state["seen"][iid] = self.state["room"]
        for inner in self.contents(iid):
            self.state["seen"][inner] = self.state["room"]

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def gate(self, gate, target, rid=None):
        """(passable, message) for a gated exit."""
        s = self.state
        if gate == "grate":
            return self.istate("grate") == "open", "You can't go through a locked steel grate!"
        if gate == "bridge":
            return bool(self.flag("bridge")), "The fissure is far too wide to jump, and there's no way across."
        if gate == "snake":
            return self.loc("snake") != "mtking", "You can't get past the snake. It hisses at you menacingly."
        if gate == "dragon":
            ok = self.istate("dragon") == "dead" or target == s["came_from"]
            return ok, "The dragon looks rather nasty. You'd best not try to get by."
        if gate == "troll":
            return self.loc("troll") == "void", "The troll steps onto the bridge and refuses to let you cross."
        if gate == "door":
            return self.istate("door") == "oiled", "The iron door is rusted shut. It won't budge."
        if gate == "tunnel":
            extra = [i for i in self.inventory_ids() if i != "emerald"]
            return not extra, ("Something you're carrying won't fit through the tunnel with you. "
                               "You'd best take inventory and drop something.")
        if gate == "beanstalk":
            return self.istate("plant") == 2, "The hole in the ceiling is far out of reach."
        if gate == "steps":
            return not self.carried("nugget"), (
                "The dome is unclimbable while you're carrying that heavy nugget: the "
                "misty steps are just too treacherous. Perhaps there's another way out.")
        return True, ""

    def nogo(self):
        msg = self.room["nogo"] or "You can't go that way."
        self.say(msg + " " + self.exits_line())

    def move(self, d, quiet=False):
        s = self.state
        r = self.room
        ex = r["exits"].get(d)
        if not ex:
            self.nogo()
            return False
        target, gate = ex
        if gate in HIDDEN_GATES and not self.gate(gate, target)[0]:
            self.say(self.gate(gate, target)[1])
            return False
        if not self.lit() and target != s["came_from"] and target not in s["visited"]:
            self.say("You stumble about in the darkness but can't find a safe way forward. "
                     "You can feel your way back along a passage you know, or find some light.")
            return False
        if gate:
            ok, msg = self.gate(gate, target)
            if not ok:
                self.say(msg)
                return False
        self.enter(target, quiet=quiet)
        return True

    def enter(self, target, quiet=False, teleport=False):
        s = self.state
        prev = s["room"]
        s["came_from"] = None if teleport else prev
        s["room"] = target
        if self.istate("bear") == "free" and self.loc("bear") == prev:
            if prev == "chasm_ne" and target == "chasm_sw":
                self.set_istate("bear", "left")
                self.say("The bear lumbers after you but stops at the edge of the rickety "
                         "bridge, whimpering. It won't follow you across.")
            else:
                self.set_loc("bear", target)
        first = target not in s["visited"]
        if first:
            s["visited"][target] = s["turns"]
            self.log("Reached %s." % ROOMS[target]["name"], "visit")
        if target in ("hall_mists",) and not self.flag("hall"):
            self.set_flag("hall")
            self.set_flag("dwarves_turn", s["turns"])
            if not s["peaceful"]:
                self.set_flag("dwarves")
        if not quiet:
            self.describe(full=first)

    def alias_dir(self, word):
        r = self.room
        if word in r["aliases"]:
            return r["aliases"][word]
        if word in ("in", "inside", "enter") and "in" in r["aliases"]:
            return r["aliases"]["in"]
        if word in ("out", "outside", "exit", "leave"):
            for w in ("out", "outside", "exit", "leave"):
                if w in r["aliases"]:
                    return r["aliases"][w]
            # Out of a dead end: the only way there is.
            dirs = self.exit_dirs()
            if len(dirs) == 1:
                return dirs[0]
        return None

    def v_go(self, cmd):
        if cmd.direction:
            return self.move(cmd.direction)
        word = cmd.arg
        if word is None:
            self.say("Where do you want to go?")
            return False
        d = self.alias_dir(word)
        if d:
            return self.move(d)
        if word in ("in", "inside", "enter"):
            self.say("You'll have to say which way: " + self.exits_line())
        elif word in ("out", "outside", "exit", "leave"):
            self.say("You'll have to say which way out: " + self.exits_line())
        elif word in ("cross", "over"):
            self.say("There's nothing here to cross.")
        elif word == "climb":
            self.say("There's nothing here to climb.")
        else:
            self.say("I don't know how to get to the %s from here. %s" % (word, self.exits_line()))
        return False

    def v_climb(self, cmd):
        rid = self.state["room"]
        words = [w for g in cmd.objs for w in g]
        if any(w in ("plant", "beanstalk", "stalk") for w in words) or (not words and not cmd.direction and rid == "west_pit"):
            if rid == "west_pit":
                if self.istate("plant") == 0:
                    self.say("It's just a little plant. You can't climb that!")
                    return True
                self.say("You clamber up the plant and out of the pit.")
                return self.move("u")
            if rid == "twopit_w" and self.istate("plant") == 2:
                self.say("You clamber up the beanstalk and through the hole in the ceiling.")
                return self.move("u")
            if rid == "narrow_corr":
                return self.move("d")
        if cmd.direction:
            return self.move(cmd.direction)
        for w in words:
            if w in self.room["aliases"]:
                return self.move(self.room["aliases"][w])
        if "climb" in self.room["aliases"]:
            return self.move(self.room["aliases"]["climb"])
        self.say("There's nothing here to climb.")
        return False

    def v_cross(self, cmd):
        d = self.alias_dir("cross")
        if d:
            return self.move(d)
        self.say("There's nothing here to cross.")
        return False

    def v_jump(self, cmd):
        if self.state["room"] in ("fissure_e", "fissure_w", "chasm_sw", "chasm_ne",
                                  "view", "brink", "window_pit", "small_pit"):
            self.say("That would be a very quick way to end your adventure. Better not.")
        else:
            self.say("Wheee! You jump on the spot. Nothing happens.")
        return True

    def v_back(self, cmd):
        target = self.state["came_from"]
        if target:
            for d, (t, _g) in self.room["exits"].items():
                if t == target:
                    return self.move(d)
        self.say("You can't retrace your steps from here. Try GO TO <place>, or click the map.")
        return False

    # GO TO ---------------------------------------------------------------

    def find_place(self, query):
        q = _norm(query)
        if not q:
            return None, "Where to? Name a place you've visited, or click it on the map."
        special = {"home": "building", "house": "building", "well": "building",
                   "start": "road", "surface": "building"}
        if q in special and special[q] in self.state["visited"]:
            return special[q], None
        visited = [r for r in self.state["visited"] if r in ROOMS]
        if q.replace(" ", "_") in visited:
            return q.replace(" ", "_"), None
        exact, partial = [], []
        for rid in visited:
            r = ROOMS[rid]
            names = {_norm(r["name"]), _norm(r["label"])}
            if q in names:
                exact.append(rid)
            elif any(q in n for n in names) or all(w in " ".join(names) for w in q.split()):
                partial.append(rid)
        hits = exact or partial
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, ("You haven't been anywhere called '%s' yet. (You can only GO TO "
                          "places you've visited.)" % query)
        here = self.state["room"]
        if here in hits:
            hits.remove(here)
            if len(hits) == 1:
                return hits[0], None
        labels = sorted({ROOMS[h]["label"] for h in hits})
        return None, "Which do you mean: %s?" % ", ".join(labels[:6])

    def route(self, target):
        start = self.state["room"]
        visited = self.state["visited"]
        prev = {start: None}
        queue = deque([start])
        while queue:
            rid = queue.popleft()
            if rid == target:
                break
            for d in DIRECTIONS:
                ex = ROOMS[rid]["exits"].get(d)
                if not ex:
                    continue
                nxt, gate = ex
                if nxt in prev or nxt not in visited:
                    continue
                if gate:
                    if gate == "dragon":
                        if self.istate("dragon") != "dead":
                            continue
                    elif not self.gate(gate, nxt, rid=rid)[0]:
                        continue
                prev[nxt] = (rid, d)
                queue.append(nxt)
        if target not in prev:
            return None
        path = []
        node = target
        while prev[node]:
            rid, d = prev[node]
            path.append(d)
            node = rid
        return list(reversed(path))

    def v_goto(self, cmd):
        arg = (cmd.arg or "").strip()
        d = DIR_WORDS.get(arg)
        if d:
            return self.move(d)
        if arg in self.room["aliases"]:
            return self.move(self.room["aliases"][arg])
        target, err = self.find_place(arg)
        if err:
            self.say(err)
            return False
        if target == self.state["room"]:
            self.say("You're already there.")
            return False
        path = self.route(target)
        if not path:
            self.say("You don't know a way to %s from here that you can manage right now."
                     % ROOMS[target]["name"])
            return False
        via = []
        for i, d in enumerate(path):
            if not self.move(d, quiet=True):
                break
            before = len(self.buf)
            self.tick()
            if self.state["game_over"]:
                return False
            if self.state["room"] != target:
                via.append(ROOMS[self.state["room"]]["label"])
            if len(self.buf) > before and self.state["room"] != target:
                self.say("You stop at %s." % self.room["name"])
                self.describe(full=False)
                return False
        if self.state["room"] == target:
            if via:
                self.say("You make your way via %s." % ", ".join(via))
            first = self.state["visited"].get(target) == self.state["turns"]
            self.describe(full=first)
        return False   # turns already counted step by step

    # ------------------------------------------------------------------
    # Resolving nouns
    # ------------------------------------------------------------------

    @staticmethod
    def _wmatch(word, vocab):
        if word in vocab:
            return True
        if len(word) >= 4 and any(v.startswith(word) for v in vocab):
            return True
        if len(word) >= 5 and any(v[:5] == word[:5] for v in vocab):
            return True
        return False

    def match_items(self, words, pool):
        hits = []
        for iid in pool:
            it = ITEMS[iid]
            nouns = set(it["nouns"])
            vocab = nouns | set(it["adjectives"])
            if iid == "bottle":
                nouns |= {"water", "oil"} if self.istate("bottle") != "empty" else set()
                vocab |= nouns
            if all(self._wmatch(w, vocab) for w in words) and any(self._wmatch(w, nouns) for w in words):
                hits.append(iid)
        return hits

    def visible_pool(self):
        pool = []
        lit = self.lit()
        for iid in ITEMS:
            if self.carried(iid) or (lit and self.at_room(iid)):
                pool.append(iid)
        return pool

    def resolve(self, words, prefer=None, quiet=False):
        """Resolve a noun phrase to an item id or a Ref; None if not found."""
        s = self.state
        words = [w for w in words if w not in ("of",)]
        if not words:
            return None
        if words in (["it"], ["them"]):
            if s["last_noun"] and self.present(s["last_noun"]):
                return s["last_noun"]
            if not quiet:
                self.say("I'm not sure what you mean by '%s'." % words[0])
            return None
        if words[0] in ("dwarf", "dwarves") and s["dwarf"]["here"] == s["room"]:
            return Ref("dwarf")
        # A bare "water" or "oil" is the bottle's contents, or else the stream/pool.
        if len(words) == 1 and words[0] in ("water", "oil"):
            liquid = words[0]
            if self.present("bottle") and self.istate("bottle") == liquid:
                return "bottle"
            if self.room[liquid]:
                return Ref("liquid", liquid)
            if not quiet:
                self.say("I see no %s here." % liquid)
            return None
        pool = self.visible_pool()
        hits = self.match_items(words, pool)
        if len(hits) > 1 and prefer:
            narrowed = [h for h in hits if prefer(h)]
            if narrowed:
                hits = narrowed
        if len(hits) > 1:
            exact = [h for h in hits if words[-1] in ITEMS[h]["nouns"]]
            if exact:
                hits = exact
        if len(hits) == 1:
            s["last_noun"] = hits[0]
            return hits[0]
        if len(hits) > 1:
            if not quiet:
                self.say("Which do you mean: %s?" % " or ".join(self.the(h) for h in hits))
            return None
        # Scenery in this room
        if self.lit():
            for key, text in self.room["scenery"].items():
                keys = key.split()
                if all(self._wmatch(w, set(keys)) for w in words):
                    return Ref("scenery", key, text)
        if words[-1] in ("wall", "walls", "ceiling", "floor", "ground", "rock", "rocks",
                         "cave", "passage", "room"):
            return Ref("global", words[-1], "It looks much like the rest of the cave."
                       if self.room["region"] != "surface" else "Nothing unusual.")
        if not quiet:
            known = any(self.match_items(words, list(ITEMS)))
            if not self.lit() and known:
                self.say("It's too dark to see.")
            else:
                self.say("I see no %s here." % " ".join(words))
        return None

    def resolve_objs(self, cmd, verb_word, prefer=None, allow_all=False):
        """Resolve all direct objects. Handles ALL and TREASURES."""
        if not cmd.objs:
            self.say("%s what?" % verb_word.capitalize())
            return []
        out = []
        for words in cmd.objs:
            if allow_all and words and words[0] in ("all", "everything"):
                return ["*all"]
            if allow_all and words and words[0] in ("treasure", "treasures"):
                return ["*treasures"]
            r = self.resolve(words, prefer=prefer)
            if r is not None:
                out.append(r)
        return out

    # ------------------------------------------------------------------
    # Looking and information
    # ------------------------------------------------------------------

    def v_look(self, cmd):
        if cmd.objs:
            return self.v_examine(cmd)
        self.describe(full=True)
        return False

    def describe_item(self, iid):
        it = ITEMS[iid]
        st = self.istate(iid)
        if iid == "lamp":
            if self.state["lamp"] <= 0:
                return "The lamp's batteries are completely dead."
            return "A sturdy brass lantern. It is %s, with power for about %d more turns." % (
                "lit" if st == "on" else "switched off", self.state["lamp"])
        if iid == "bottle":
            return {"water": "A small glass bottle, full of water.",
                    "oil": "A small glass bottle, full of oil."}.get(st, "A small glass bottle. It's empty.")
        if iid == "cage":
            return it["examine"] + (" A little bird is inside." if self.loc("bird") == "in:cage" else " It's empty.")
        if iid == "plant":
            return self.item_text("plant") or "A plant."
        if iid == "door":
            return it["examine"] if st == "rusty" else "The hinges are well oiled now, and the door stands open."
        if iid == "grate":
            return "A strong steel grate set in concrete. It is %s." % ("open" if st == "open" else "locked")
        if iid == "clam":
            return "It must be four feet across. " + (
                "Its shell gapes open, and it's empty." if st == "open" else "Its shell is tightly closed.")
        if iid == "bear":
            return {"chained": "A huge, ferocious cave bear, held back by a golden chain. It looks hungry.",
                    "fed": "The bear looks content and friendly. It's still chained to the wall."}.get(
                st, "A big friendly bear. It seems to like you.")
        if iid == "vase" and st == "broken":
            return "Worthless shards of pottery. Such a shame."
        if iid == "dragon" and st == "dead":
            return "The dragon is quite dead."
        if iid == "chain":
            return "A heavy chain of solid gold." + (" It's locked to the wall." if st == "locked" else "")
        if it["examine"]:
            return it["examine"]
        return "It looks just like %s." % ("any other " + self.name(iid))

    def v_examine(self, cmd):
        if not cmd.objs:
            self.describe(full=True)
            return False
        for r in self.resolve_objs(cmd, "examine"):
            if isinstance(r, Ref):
                if r.kind == "dwarf":
                    self.say("A nasty-looking little dwarf with a knife.")
                elif r.kind == "liquid":
                    self.say("Clear, cold water." if r.key == "water" else "Thick black oil.")
                else:
                    self.say(r.text)
            else:
                self.say(self.describe_item(r))
                self.note_seen(r)
        return False

    def v_read(self, cmd):
        if not self.lit():
            self.say("It's too dark to read.")
            return False
        if not cmd.objs:
            if self.room["scenery"]:
                for key, text in self.room["scenery"].items():
                    if any(k in key.split() for k in ("writing", "inscription", "tablet", "sign", "notice", "note", "warning")):
                        self.say(text)
                        return False
            self.say("Read what?")
            return False
        for r in self.resolve_objs(cmd, "read"):
            if isinstance(r, Ref):
                self.say(r.text or "There's nothing written on it.")
            elif ITEMS[r]["read"]:
                self.say(ITEMS[r]["read"])
            else:
                self.say("There's nothing written on %s." % self.the(r))
        return False

    def v_inventory(self, cmd):
        ids = self.inventory_ids()
        if not ids:
            self.say("You're not carrying anything.")
            return False
        lines = ["You are carrying:"]
        for iid in ids:
            label = self.name(iid)
            if iid == "lamp":
                label += " (lit)" if self.istate("lamp") == "on" else " (off)"
            if iid == "cage" and self.loc("bird") == "in:cage":
                label += ", containing a little bird"
            lines.append("  " + label[0].upper() + label[1:])
        self.say("\n".join(lines))
        return False

    def v_exits(self, cmd):
        dirs = self.exit_dirs(for_dark=not self.lit())
        if not dirs:
            self.say("You can't make out any way to go from here.")
            return False
        parts = []
        for d in dirs:
            target, gate = self.room["exits"][d]
            label = DIR_NAMES[d]
            if target in self.state["visited"]:
                label += " (%s)" % ROOMS[target]["name"]
            parts.append(label)
        self.say("From here you can go " + ", ".join(parts) + ".")
        return False

    def v_find(self, cmd):
        if not cmd.objs:
            self.say("What are you looking for?")
            return False
        words = cmd.objs[0]
        hits = self.match_items(words, [i for i in ITEMS if i in self.state["seen"] or self.carried(i)])
        if not hits:
            self.say("You haven't seen anything like that yet.")
            return False
        for iid in hits[:3]:
            if self.carried(iid):
                self.say("You're carrying %s." % self.the(iid))
            elif self.at_room(iid) and self.lit():
                self.say("%s is right here." % self.the(iid).capitalize())
            else:
                where = self.state["seen"].get(iid)
                if where and where in ROOMS:
                    self.say("You last saw %s at %s. (Type GO TO %s to walk there.)" % (
                        self.the(iid), ROOMS[where]["name"], ROOMS[where]["label"].upper()))
                else:
                    self.say("You don't know where %s is now." % self.the(iid))
        return False

    def v_map(self, cmd):
        from .mapview import ascii_map
        self.say(ascii_map(self, self.room["region"]))
        return False

    def v_itinerary(self, cmd):
        lines = ["ITINERARY (most recent last)"]
        for e in self.state["log"][-14:]:
            lines.append("  T%-4d %s" % (e["t"], e["text"]))
        n = sum(1 for t in TREASURES if self.stored(t))
        lines.append("Treasures stored in the well house: %d of %d." % (n, len(TREASURES)))
        self.say("\n".join(lines))
        return False

    def score_parts(self):
        s = self.state
        stored = sum(ITEMS[t]["treasure"] for t in TREASURES if self.stored(t))
        return [
            ("Treasures found", 2 * len(s["found"]), 30),
            ("Treasures stored in the well house", stored, 188),
            ("Reaching the Hall of Mists", 25 if self.flag("hall") else 0, 25),
            ("Lives kept", 10 * max(0, LIVES - s["deaths"]), 30),
            ("Not quitting", 0 if s["quit"] else 4, 4),
            ("Leaving the magazine at Witt's End", 1 if self.loc("magazine") == "witts" else 0, 1),
            ("Seeing the cave close", 25 if s["closed"] else 0, 25),
            ("The final blast", s["blast"], 45),
            ("Rounding off", 2, 2),
        ]

    def score(self):
        return sum(p for _n, p, _m in self.score_parts())

    def rank(self):
        sc = self.score()
        for limit, text in RANKS:
            if sc <= limit:
                return text
        return RANKS[-1][1]

    def v_score(self, cmd):
        lines = ["You have scored %d out of a possible %d, in %d turns." % (
            self.score(), MAX_SCORE, self.state["turns"])]
        for label, pts, mx in self.score_parts():
            lines.append("  %-38s %3d / %d" % (label, pts, mx))
        self.say("\n".join(lines))
        return False

    def v_hint(self, cmd):
        tips = hint_mod.hints(self)
        self.say("\n".join(tips[:3]))
        return False

    def v_help(self, cmd):
        self.say(HELP_TEXT)
        return False

    def v_about(self, cmd):
        self.say(ABOUT_TEXT)
        return False

    def v_verbose(self, cmd):
        self.state["verbose"] = True
        self.say("Verbose mode: you'll get full descriptions every time.")
        return False

    def v_brief(self, cmd):
        self.state["verbose"] = False
        self.say("Brief mode: full descriptions on first visits only. LOOK shows them again.")
        return False

    def v_baud(self, cmd):
        arg = (cmd.arg or "").strip()
        if arg in ("off", "max", "fast", "instant", "none"):
            arg = "0"
        if not arg.isdigit():
            self.say("The line is running at %s. Try BAUD 300, 1200, 2400, 9600, or BAUD 0 for instant text."
                     % ("full speed" if not self.state["baud"] else "%d baud" % self.state["baud"]))
            return False
        rate = int(arg)
        if rate not in BAUD_RATES:
            self.say("Choose one of: %s." % ", ".join(str(b) for b in BAUD_RATES))
            return False
        self.state["baud"] = rate
        self.say("Serial delay off: text appears at once." if rate == 0 else "Line speed set to %d baud." % rate)
        return False

    def v_wait(self, cmd):
        self.say("Time passes...")
        return True

    def v_listen(self, cmd):
        rid = self.state["room"]
        if self.room["water"] and self.room["region"] != "surface":
            self.say("The rush of water fills your ears.")
        elif rid in ("view", "warm", "boulders"):
            self.say("A deep, steady roar, like a furnace.")
        elif rid == "y2":
            self.say("A hollow voice whispers 'PLUGH'.")
        elif self.at_room("bird") and self.loc("bird") != "in:cage":
            self.say("The little bird sings sweetly.")
        elif rid == "repo_ne":
            self.say("Snoring. A great deal of snoring.")
        else:
            self.say("The cave is silent apart from the occasional drip of water.")
        return True

    def v_smell(self, cmd):
        rid = self.state["room"]
        if rid in ("lair", "secret_ns", "secret_ew"):
            self.say("Smoke and sulphur.")
        elif self.present("spices"):
            self.say("Mmm. Cinnamon and saffron.")
        elif self.room["region"] == "surface":
            self.say("Pine needles and damp earth.")
        else:
            self.say("Damp stone.")
        return True

    def v_swim(self, cmd):
        if self.state["room"] == "reservoir":
            self.say("The water is far too cold. You'd freeze before you got anywhere.")
        else:
            self.say("There's nowhere here to swim.")
        return True

    def v_sing(self, cmd):
        self.say("You sing a few bars. The cave echoes them back, somewhat improved.")
        return True

    # ------------------------------------------------------------------
    # Taking and dropping
    # ------------------------------------------------------------------

    def can_carry_more(self):
        return len(self.inventory_ids()) < MAX_CARRY

    def take_one(self, iid, many=False):
        prefix = (self.name(iid)[0].upper() + self.name(iid)[1:] + ": ") if many else ""
        if self.carried(iid):
            self.say(prefix + "You're already carrying it!")
            return
        it = ITEMS[iid]
        if iid == "bird":
            self.catch_bird(prefix)
            return
        if iid == "chain" and self.istate("chain") == "locked":
            self.say(prefix + "The chain is still locked to the wall.")
            return
        if iid == "rug" and self.istate("dragon") == "alive" and self.at_room("dragon"):
            self.say(prefix + "You can't be serious! The dragon is lying on it.")
            return
        if not it["portable"]:
            msg = {
                "snake": "Surely you're joking.",
                "dragon": "Surely you're joking.",
                "troll": "The troll is far too big, and far too cross.",
                "bear": ("The bear is still chained to the wall." if self.istate("bear") in ("chained", "fed")
                         else "Bears don't like being carried."),
                "plant": "The plant has exceptionally deep roots and won't come free.",
                "clam": "The clam is far too heavy to lift.",
                "machine": "It weighs a ton.",
            }.get(iid, "It's firmly fixed in place.")
            self.say(prefix + msg)
            return
        if not self.can_carry_more():
            self.say(prefix + "You can't carry anything more. You'll have to drop something first.")
            return
        if iid == "vase" and self.broken("vase"):
            self.say(prefix + "The shards are worthless. Leave them.")
            return
        self.set_loc(iid, "player")
        self.state["items"][iid]["moved"] = True
        self.say(prefix + "Taken.")
        self.mark_found(iid)
        if iid == "cage" and self.loc("bird") == "in:cage":
            self.state["items"]["bird"]["moved"] = True

    def catch_bird(self, prefix=""):
        if self.loc("bird") == "in:cage":
            self.take_one("cage")
            return
        if self.carried("rod"):
            self.say(prefix + "The bird was unafraid when you came in, but as you approach it "
                     "takes fright at the black rod and flutters out of reach.")
            return
        if not self.carried("cage"):
            self.say(prefix + "You can catch the bird, but you have nothing to carry it in.")
            return
        self.set_loc("bird", "in:cage")
        self.state["items"]["bird"]["moved"] = True
        self.say(prefix + "You catch the bird in the wicker cage.")
        self.log("Caught the little bird.", "event")

    def v_take(self, cmd):
        if not self.lit() and not (cmd.objs and all(self.match_items(w, self.inventory_ids()) for w in cmd.objs)):
            self.say("It's too dark to see anything to take.")
            return False
        for words in cmd.objs:
            if words in (["water"], ["oil"]) and not (
                    self.present("bottle") and self.istate("bottle") == words[0]):
                return self.v_fill_with(words[0])
        targets = self.resolve_objs(cmd, "take", prefer=lambda i: not self.carried(i), allow_all=True)
        if targets == ["*all"] or targets == ["*treasures"]:
            pool = [i for i in self.room_ids() if ITEMS[i]["portable"] or i == "bird"]
            if targets == ["*treasures"]:
                pool = [i for i in pool if ITEMS[i]["treasure"]]
            pool = [i for i in pool if not (i == "chain" and self.istate("chain") == "locked")
                    and not (i == "rug" and self.istate("dragon") == "alive")
                    and not (i == "bird" and self.loc("bird") == "in:cage" and self.at_room("cage"))
                    and not self.broken(i)]
            if not pool:
                self.say("There's nothing here you can take.")
                return False
            mark = len(self.buf)
            for iid in pool:
                self.take_one(iid, many=True)
            self.group_since(mark)
            return True
        mark = len(self.buf)
        for r in targets:
            if isinstance(r, Ref):
                if r.kind == "dwarf":
                    self.say("The dwarf is not at all keen on being picked up.")
                elif r.kind == "liquid":
                    return self.v_fill_with(r.key)
                else:
                    self.say("That's not something you can carry.")
                continue
            self.take_one(r, many=len(targets) > 1)
        self.group_since(mark)
        return True

    def v_drop(self, cmd):
        targets = self.resolve_objs(cmd, "drop", prefer=self.carried, allow_all=True)
        if targets in (["*all"], ["*treasures"]):
            pool = self.inventory_ids()
            if targets == ["*treasures"]:
                pool = [i for i in pool if ITEMS[i]["treasure"]]
            if not pool:
                self.say("You're not carrying anything%s." % (" valuable" if targets == ["*treasures"] else ""))
                return False
            mark = len(self.buf)
            for iid in pool:
                self.drop_one(iid, many=True)
            self.group_since(mark)
            return True
        mark = len(self.buf)
        for r in targets:
            if isinstance(r, Ref):
                if r.kind == "liquid":
                    return self.pour_bottle()
                self.say("You aren't carrying that.")
                continue
            self.drop_one(r, many=len(targets) > 1)
        self.group_since(mark)
        return True

    def drop_one(self, iid, many=False, thrown=False):
        prefix = (self.name(iid)[0].upper() + self.name(iid)[1:] + ": ") if many else ""
        rid = self.state["room"]
        if iid == "bird" and self.loc("bird") == "in:cage" and self.carried("cage"):
            self.release_bird(prefix)
            return
        if not self.carried(iid):
            self.say(prefix + "You aren't carrying %s." % ("it" if prefix else self.the(iid)))
            return
        if iid == "coins" and rid == "d5":
            self.set_loc("coins", rid)
            self.vend()
            return
        if iid == "vase":
            if self.at_room("pillow") and not self.carried("pillow"):
                self.set_loc("vase", rid)
                self.say(prefix + "The vase is now resting, delicately, on a velvet pillow.")
                self.after_drop("vase")
                return
            if rid == "soft":
                self.set_loc("vase", rid)
                self.say(prefix + "The vase settles gently on the thick carpet.")
                return
            self.set_loc("vase", rid)
            self.set_istate("vase", "broken")
            self.say(prefix + "The Ming vase drops with a delicate crash.")
            self.log("Broke the Ming vase. (UNDO might help.)", "loss")
            return
        self.set_loc(iid, rid)
        self.say(prefix + ("Thrown." if thrown else "Dropped."))
        self.after_drop(iid)

    def after_drop(self, iid):
        if self.state["room"] == STORE_ROOM and ITEMS[iid]["treasure"] and self.stored(iid):
            n = sum(1 for t in TREASURES if self.stored(t))
            self.log("Stored the %s in the well house (%d/15)." % (self.name(iid), n), "store")

    def release_bird(self, prefix=""):
        rid = self.state["room"]
        self.set_loc("bird", rid)
        if self.loc("snake") == rid:
            self.set_loc("snake", "void")
            self.say(prefix + "The little bird attacks the huge snake, and in an astounding "
                     "flurry drives the snake away.")
            self.log("The bird drove off the snake.", "event")
        elif self.at_room("dragon") and self.istate("dragon") == "alive":
            self.set_loc("bird", "void")
            self.say(prefix + "The little bird attacks the dragon, and in an astounding flurry "
                     "gets burnt to a cinder. The ashes blow away.")
            self.log("The bird was burnt to a cinder.", "loss")
        else:
            self.say(prefix + "The little bird flies free.")

    def v_put(self, cmd):
        if not cmd.iobj:
            if cmd.prep is None:
                return self.v_drop(cmd)
            self.say("Put it %s what?" % cmd.prep)
            return False
        objs = self.resolve_objs(cmd, "put", prefer=self.carried)
        if not objs:
            return False
        dest = self.resolve(cmd.iobj)
        if dest is None:
            return False
        for obj in objs:
            if isinstance(obj, Ref):
                if obj.kind == "liquid" and dest == "bottle":
                    return self.v_fill_with(obj.key)
                self.say("You can't do that.")
                continue
            if dest == "cage" and obj == "bird":
                self.catch_bird()
            elif dest == "machine" and obj == "coins":
                if not self.carried("coins"):
                    self.say("You aren't carrying the coins.")
                else:
                    self.set_loc("coins", self.state["room"])
                    self.vend()
            elif dest == "lamp" and obj == "batteries":
                self.replace_batteries()
            elif dest == "pillow" and obj == "vase":
                self.drop_one("vase")
            elif dest == "troll":
                self.pay_troll(obj)
            elif dest == "bottle" and obj in ("water", "oil"):
                self.v_fill_with(obj)
            elif dest in ("bear",) and obj == "food":
                self.feed_bear()
            elif cmd.prep in ("on", "onto", "upon", "down") or dest in ("plant", "door"):
                if obj == "bottle" and dest in ("plant", "door"):
                    self.pour_bottle(onto=dest)
                else:
                    self.drop_one(obj)
            else:
                self.say("You can't put %s in %s." % (self.the(obj), self.the(dest) if not isinstance(dest, Ref) else "that"))
        return True

    def v_give(self, cmd):
        objs = self.resolve_objs(cmd, "give", prefer=self.carried)
        if not objs:
            return False
        if not cmd.iobj:
            self.say("Give it to whom?")
            return False
        dest = self.resolve(cmd.iobj)
        if dest is None:
            return False
        obj = objs[0]
        if isinstance(obj, Ref):
            self.say("You can't give that away.")
            return False
        if dest == "troll":
            self.pay_troll(obj)
        elif dest == "bear" and obj == "food":
            self.feed_bear()
        elif isinstance(dest, Ref) and dest.kind == "dwarf":
            if obj == "food":
                self.say("You fool, dwarves eat only coal! Now you've made him really mad!!")
            else:
                self.say("The dwarf is not at all interested in your offer.")
        elif dest == "dragon":
            self.say("The dragon is not interested. It would rather eat you.")
        else:
            self.say("I don't think %s wants it." % (self.the(dest) if not isinstance(dest, Ref) else "that"))
        return True

    def v_throw(self, cmd):
        objs = self.resolve_objs(cmd, "throw", prefer=self.carried)
        if not objs:
            return False
        obj = objs[0]
        if isinstance(obj, Ref):
            self.say("You can't throw that.")
            return False
        if not self.carried(obj):
            self.say("You aren't carrying %s." % self.the(obj))
            return False
        dest = self.resolve(cmd.iobj, quiet=True) if cmd.iobj else None
        if dest is None and not cmd.iobj and self.state["dwarf"]["here"] == self.state["room"] and obj == "axe":
            dest = Ref("dwarf")
        if isinstance(dest, Ref) and dest.kind == "dwarf":
            if obj == "axe":
                npcs.attack_dwarf(self, thrown=True)
            else:
                self.drop_one(obj, thrown=True)
            return True
        if dest == "troll":
            self.pay_troll(obj)
        elif dest == "bear" and obj == "food":
            self.feed_bear()
        elif dest == "dragon":
            self.set_loc(obj, self.state["room"])
            self.say("The %s bounces harmlessly off the dragon's thick scales." % self.name(obj))
        elif obj == "vase":
            self.set_loc("vase", self.state["room"])
            self.set_istate("vase", "broken")
            self.say("The Ming vase drops with a delicate crash.")
            self.log("Broke the Ming vase. (UNDO might help.)", "loss")
        else:
            self.drop_one(obj, thrown=True)
        return True

    # ------------------------------------------------------------------
    # Puzzles
    # ------------------------------------------------------------------

    def pay_troll(self, obj):
        if not self.at_room("troll"):
            self.say("There's no troll here.")
            return
        if not self.carried(obj):
            self.say("You aren't carrying %s." % self.the(obj))
            return
        if not ITEMS[obj]["treasure"] or self.broken(obj):
            self.set_loc(obj, self.state["room"])
            self.say("The troll deftly catches %s, turns it over, and tosses it back "
                     "with a sniff. 'Treasure,' he insists." % self.the(obj))
            return
        self.set_loc(obj, "void")
        self.set_loc("troll", "void")
        if obj != "eggs":
            self.set_flag("troll_took", obj)
        self.say("The troll catches your treasure and scurries away out of sight.")
        self.log("Paid the troll with the %s." % self.name(obj), "event")

    def feed_bear(self):
        if not self.at_room("bear"):
            self.say("There's no bear here.")
            return
        if not self.present("food"):
            self.say("You have nothing to feed the bear with.")
            return
        if self.istate("bear") != "chained":
            self.say("The bear has already eaten and seems perfectly content.")
            return
        self.set_loc("food", "void")
        self.set_istate("bear", "fed")
        self.say("The bear eagerly wolfs down your food, after which it seems to calm down "
                 "considerably and even becomes rather friendly.")
        self.log("Fed the bear.", "event")

    def unlock_chain(self):
        if self.istate("chain") != "locked":
            self.say("The chain is already unlocked.")
            return
        if not self.carried("keys"):
            self.say("You have no keys!")
            return
        if self.istate("bear") == "chained":
            self.say("There is no way to get past the bear to unlock the chain, which is probably just as well.")
            return
        self.set_istate("chain", "unlocked")
        self.set_istate("bear", "free")
        self.say("The chain is now unlocked. The bear, freed, ambles over and nuzzles you. "
                 "It seems to have decided to follow you around.")
        self.log("Unlocked the golden chain.", "event")

    def vend(self):
        if self.loc("batteries") == "void":
            self.set_loc("batteries", self.state["room"])
            self.say("There's a whir and a clunk, and a pack of fresh batteries drops into the "
                     "tray. A moment later your coins rattle back out of the change slot: the "
                     "machine seems to be broken in your favour.")
            self.log("Got fresh batteries from the vending machine.", "event")
        else:
            self.say("The machine whirs, thinks about it, and spits your coins back out. It seems to be empty.")

    def replace_batteries(self, auto=False):
        if not self.present("batteries") or self.istate("batteries") != "fresh":
            self.say("You have no fresh batteries.")
            return
        if not self.present("lamp"):
            self.say("You'd need the lamp too.")
            return
        self.state["lamp"] = BATTERY_POWER
        self.set_istate("batteries", "worn")
        self.set_loc("batteries", self.state["room"])
        if auto:
            self.say("Your lamp is getting dim. I'm taking the liberty of replacing the batteries.")
        else:
            self.say("Your lamp is now running on fresh batteries.")

    def v_replace(self, cmd):
        self.replace_batteries()
        return True

    def v_fill_with(self, liquid=None):
        if not self.present("bottle"):
            self.say("You have nothing to put it in.")
            return False
        if self.istate("bottle") != "empty":
            self.say("Your bottle is already full.")
            return True
        r = self.room
        if r["water"] and liquid in (None, "water"):
            self.set_istate("bottle", "water")
            self.say("Your bottle is now full of water.")
        elif r["oil"] and liquid in (None, "oil"):
            self.set_istate("bottle", "oil")
            self.say("Your bottle is now full of oil.")
        else:
            self.say("There is nothing here with which to fill the bottle.")
        return True

    def v_fill(self, cmd):
        if cmd.objs:
            target = self.resolve(cmd.objs[0])
            if target is None:
                return False
            if isinstance(target, Ref) and target.kind == "liquid":
                return self.v_fill_with(target.key)
            if target == "lamp":
                self.say("The lamp runs on batteries, not oil.")
                return False
            if target != "bottle":
                self.say("You can't fill that.")
                return False
        liquid = cmd.iobj[-1] if cmd.iobj and cmd.iobj[-1] in ("water", "oil") else None
        return self.v_fill_with(liquid)

    def pour_bottle(self, onto=None):
        if not self.present("bottle"):
            self.say("You have nothing to pour.")
            return False
        liquid = self.istate("bottle")
        if liquid == "empty":
            self.say("Your bottle is empty.")
            return False
        self.set_istate("bottle", "empty")
        if onto in (None, "plant") and self.at_room("plant"):
            if liquid == "oil":
                self.say("The plant indignantly shakes the oil off its leaves and asks, 'Water?'")
                return True
            stage = self.istate("plant")
            if stage == 0:
                self.set_istate("plant", 1)
                self.say("The plant spurts into furious growth for a few seconds. It's now a "
                         "twelve-foot beanstalk, and it's still bellowing for water.")
                self.log("Watered the plant; it's twelve feet tall.", "event")
            elif stage == 1:
                self.set_istate("plant", 2)
                self.say("The plant grows explosively, almost filling the bottom of the pit. A "
                         "gigantic beanstalk now reaches up through the hole in the ceiling above.")
                self.log("The beanstalk reached the hole in the ceiling.", "event")
            else:
                self.say("The beanstalk has all the water it can use. The excess soaks away.")
            return True
        if onto in (None, "door") and self.at_room("door"):
            if liquid == "oil":
                self.set_istate("door", "oiled")
                self.say("The oil has freed up the hinges, so that the door will now move, "
                         "although it takes some effort. The door now stands open.")
                self.log("Oiled the rusty iron door.", "event")
            else:
                self.say("The hinges are quite thoroughly rusted now and won't budge.")
            return True
        if liquid == "water":
            self.say("Your bottle is empty and the ground is wet.")
        else:
            self.say("Your bottle is empty and the floor is slippery with oil.")
        return True

    def v_pour(self, cmd):
        onto = self.resolve(cmd.iobj, quiet=True) if cmd.iobj else None
        if cmd.objs:
            what = self.resolve(cmd.objs[0], quiet=True)
            if what in ("plant", "door") and onto is None:
                onto = what
        return self.pour_bottle(onto=onto if isinstance(onto, str) else None)

    def v_water(self, cmd):
        if not self.present("bottle") or self.istate("bottle") != "water":
            self.say("You have no water.")
            return False
        target = self.resolve(cmd.objs[0], quiet=True) if cmd.objs else None
        if target == "plant" or (target is None and self.at_room("plant")):
            return self.pour_bottle(onto="plant")
        return self.pour_bottle(onto=target if isinstance(target, str) else None)

    def v_oil(self, cmd):
        if not self.present("bottle") or self.istate("bottle") != "oil":
            self.say("You have no oil.")
            return False
        target = self.resolve(cmd.objs[0], quiet=True) if cmd.objs else None
        return self.pour_bottle(onto=target if isinstance(target, str) else None)

    def v_drink(self, cmd):
        target = self.resolve(cmd.objs[0], quiet=True) if cmd.objs else None
        if isinstance(target, Ref) and target.key == "water" or (target is None and self.room["water"] and not self.present("bottle")):
            self.say("You have taken a drink from the stream. The water tastes strongly of "
                     "minerals, but is not unpleasant. It is extremely cold.")
            return True
        if target in ("bottle", None) and self.present("bottle") and self.istate("bottle") == "water":
            self.set_istate("bottle", "empty")
            self.say("The bottle of water is now empty.")
            return True
        if target == "bottle" and self.istate("bottle") == "oil" or (isinstance(target, Ref) and target.key == "oil"):
            self.say("Absolutely not.")
            return False
        if self.room["water"]:
            self.say("You have taken a drink from the stream. The water tastes strongly of "
                     "minerals, but is not unpleasant. It is extremely cold.")
            return True
        self.say("You have nothing to drink.")
        return False

    def v_eat(self, cmd):
        target = self.resolve(cmd.objs[0]) if cmd.objs else ("food" if self.present("food") else None)
        if target is None:
            if not cmd.objs:
                self.say("You have nothing to eat.")
            return False
        if target == "food":
            self.set_loc("food", STORE_ROOM)
            self.say("Thank you, it was delicious! (The well house seems to keep a well-stocked pantry.)")
            return True
        self.say("I think I just lost my appetite.")
        return False

    def v_wave(self, cmd):
        targets = self.resolve_objs(cmd, "wave", prefer=self.carried)
        if not targets:
            return False
        obj = targets[0]
        if obj == "rod":
            if not self.carried("rod"):
                self.say("You aren't carrying it.")
                return False
            if self.state["room"] in ("fissure_e", "fissure_w"):
                if self.flag("bridge"):
                    self.set_flag("bridge", False)
                    self.say("The crystal bridge has vanished!")
                else:
                    self.set_flag("bridge", True)
                    self.say("A crystal bridge now spans the fissure.")
                    self.log("Conjured a crystal bridge over the fissure.", "event")
                return True
        self.say("Nothing happens.")
        return True

    def v_feed(self, cmd):
        targets = self.resolve_objs(cmd, "feed")
        if not targets:
            return False
        t = targets[0]
        if t == "bear":
            self.feed_bear()
        elif t == "bird":
            self.say("It's not hungry (it's merely pining for the fjords). Besides, you have no bird seed.")
        elif t == "troll":
            self.say("Gluttony is not one of the troll's vices. Avarice, however, is.")
        elif t == "dragon":
            self.say("There's nothing here it wants to eat (except perhaps you).")
        elif t == "snake":
            self.say("The snake isn't interested in anything you've got. Except perhaps the bird.")
        elif isinstance(t, Ref) and t.kind == "dwarf":
            self.say("You fool, dwarves eat only coal! Now you've made him really mad!!")
        else:
            self.say("I'm not sure how to feed that.")
        return True

    def v_attack(self, cmd):
        if not cmd.objs:
            if self.state["dwarf"]["here"] == self.state["room"]:
                return npcs.attack_dwarf(self, thrown=False) or True
            for c in ("dragon", "snake", "troll", "bear", "bird", "clam"):
                if self.at_room(c) and self.lit():
                    cmd.objs = [[c]]
                    break
            else:
                self.say("There is nothing here to attack.")
                return False
        targets = self.resolve_objs(cmd, "attack")
        if not targets:
            return False
        t = targets[0]
        bare = cmd.iobj and any(w in ("hands", "hand", "fists", "bare") for w in cmd.iobj)
        if isinstance(t, Ref) and t.kind == "dwarf":
            npcs.attack_dwarf(self, thrown=self.carried("axe"))
        elif t == "dragon":
            if self.istate("dragon") == "dead":
                self.say("For crying out loud, the poor thing is already dead!")
            elif bare:
                self.kill_dragon()
            else:
                self.state["pending"] = "dragon"
                self.say("With what? Your bare hands?")
                return False
        elif t == "snake":
            self.say("Attacking the snake both doesn't work and is very dangerous.")
        elif t == "troll":
            self.say("The troll laughs aloud at your pitiful attempt to injure him.")
        elif t == "bear":
            if self.istate("bear") == "chained":
                self.say("With what? Your bare hands? Against his bear hands??")
            else:
                self.say("The bear is confused; he only wants to be your friend.")
        elif t == "bird":
            self.say("Oh, leave the poor little bird alone.")
        elif t == "clam":
            self.say("The shell is very strong and is impervious to attack.")
        elif t == "machine":
            self.say("You give the machine a good thump. Nothing comes out.")
        else:
            self.say("Violence isn't the answer to this one.")
        return True

    def kill_dragon(self):
        self.set_istate("dragon", "dead")
        self.say("Congratulations! You have just vanquished a dragon with your bare hands! "
                 "(Unbelievable, isn't it?)")
        self.log("Slew the dragon with your bare hands.", "event")

    def v_yes(self, cmd):
        p = self.state["pending"]
        self.state["pending"] = None
        if p == "dragon":
            if self.at_room("dragon") and self.istate("dragon") == "alive":
                self.kill_dragon()
                self.tick()
            return False
        if p == "restart":
            baud = self.state["baud"]
            self.new_game(baud=baud)
            return False
        if p == "quit":
            self.state["quit"] = True
            self.end_game("You have quit.")
            return False
        self.say("Yes what?")
        return False

    def v_no(self, cmd):
        p = self.state["pending"]
        self.state["pending"] = None
        if p == "dragon":
            self.say("Very wise.")
        elif p in ("restart", "quit"):
            self.say("Carry on, then.")
        else:
            self.say("No what?")
        return False

    def v_break(self, cmd):
        targets = self.resolve_objs(cmd, "break")
        if not targets:
            return False
        t = targets[0]
        if t == "vase" and not self.broken("vase"):
            self.set_loc("vase", self.state["room"])
            self.set_istate("vase", "broken")
            self.say("You have taken the vase and hurled it delicately to the ground.")
            self.log("Broke the Ming vase. (UNDO might help.)", "loss")
        elif isinstance(t, Ref) and t.key == "mirror":
            self.say("It is too far up for you to reach.")
        elif t == "clam":
            self.say("The shell is very strong and is impervious to attack.")
        else:
            self.say("It is beyond your power to do that.")
        return True

    def v_wake(self, cmd):
        words = [w for g in cmd.objs for w in g]
        if self.state["room"] == "repo_ne" and any(w.startswith("dwar") for w in words):
            self.say("You prod the nearest dwarf, who wakes up grumpily, takes one look at you, "
                     "curses, and grabs for his axe. The noise wakes the rest, and in moments "
                     "you are surrounded by a horde of furious dwarves.")
            self.end_game("You have been killed by a horde of angry dwarves.")
            return False
        self.say("Nothing seems to be asleep here.")
        return True

    # Opening and locking -------------------------------------------------

    def v_unlock(self, cmd):
        targets = self.resolve_objs(cmd, "unlock")
        if not targets:
            return False
        t = targets[0]
        if t == "grate":
            if not self.carried("keys"):
                self.say("You have no keys!")
            elif self.istate("grate") == "open":
                self.say("It's already open.")
            else:
                self.set_istate("grate", "open")
                self.say("The grate is now unlocked, and you swing it open.")
                self.log("Unlocked the grate.", "event")
        elif t == "chain":
            self.unlock_chain()
        elif t == "bear":
            self.unlock_chain()
        elif t == "door":
            self.say("The door has no keyhole. Its hinges are the problem.")
        elif t == "clam":
            return self.open_clam(cmd)
        else:
            self.say("You can't unlock that.")
        return True

    def v_lock(self, cmd):
        targets = self.resolve_objs(cmd, "lock")
        if not targets:
            return False
        t = targets[0]
        if t == "grate":
            if not self.carried("keys"):
                self.say("You have no keys!")
            elif self.istate("grate") != "open":
                self.say("It's already locked.")
            else:
                self.set_istate("grate", "locked")
                self.say("The grate is now locked.")
        elif t == "chain":
            self.say("You'd rather not chain up the bear again.")
        else:
            self.say("You can't lock that.")
        return True

    def open_clam(self, cmd):
        if self.istate("clam") == "open":
            self.say("The clam is already open, and empty.")
            return True
        if not self.carried("trident"):
            self.say("You don't have anything strong enough to open the clam.")
            return True
        self.set_istate("clam", "open")
        self.set_loc("pearl", "cul")
        self.say("A glistening pearl falls out of the clam and rolls away. Goodness, this must "
                 "really be an oyster. (I never was very good at identifying bivalves.) "
                 "Whatever it is, it has now snapped shut again.")
        self.log("Prised open the clam; a pearl rolled away.", "event")
        return True

    def v_open(self, cmd):
        targets = self.resolve_objs(cmd, "open")
        if not targets:
            return False
        t = targets[0]
        if t == "grate":
            return self.v_unlock(cmd)
        if t == "clam":
            return self.open_clam(cmd)
        if t == "door":
            if self.istate("door") == "oiled":
                self.say("It's already open.")
            else:
                self.say("The door is extremely rusty and refuses to open.")
            return True
        if t == "cage":
            if self.loc("bird") == "in:cage":
                if self.carried("cage"):
                    self.release_bird()
                else:
                    self.set_loc("bird", self.state["room"])
                    self.say("The little bird flies free.")
            else:
                self.say("The cage is empty.")
            return True
        if t == "chain":
            self.unlock_chain()
            return True
        if t == "bottle":
            self.say("The bottle has no stopper. It's always open.")
            return False
        self.say("You can't open that.")
        return False

    def v_close(self, cmd):
        targets = self.resolve_objs(cmd, "close")
        if not targets:
            return False
        t = targets[0]
        if t == "grate":
            if self.istate("grate") == "open":
                self.set_istate("grate", "locked")
                self.say("The grate clangs shut and locks.")
            else:
                self.say("It's already closed.")
        elif t == "door":
            self.say("The door is far too heavy to move.")
        else:
            self.say("You can't close that.")
        return True

    # Light ---------------------------------------------------------------

    def v_light(self, cmd):
        if cmd.objs:
            t = self.resolve(cmd.objs[0])
            if t is None:
                return False
        else:
            t = "lamp"
        if t == "dynamite":
            self.say("Nice try. You'll want to BLAST it.")
            return False
        if t != "lamp":
            self.say("You can't light that.")
            return False
        if not self.present("lamp"):
            self.say("You have no source of light.")
            return False
        if self.state["lamp"] <= 0:
            self.say("Your lamp has run out of power.")
            return False
        was_dark = not self.lit()
        self.set_istate("lamp", "on")
        self.say("Your lamp is now on.")
        if was_dark:
            self.describe(full=True)
        return True

    def v_extinguish(self, cmd):
        if cmd.objs:
            t = self.resolve(cmd.objs[0])
            if t is None:
                return False
        else:
            t = "lamp"
        if t != "lamp":
            self.say("You can't put that out.")
            return False
        if not self.present("lamp"):
            self.say("You have no lamp.")
            return False
        self.set_istate("lamp", "off")
        self.say("Your lamp is now off.")
        if not self.lit():
            self.say("It is now pitch dark.")
        return True

    # Magic ---------------------------------------------------------------

    def v_say(self, cmd):
        words = (cmd.arg or "").split()
        if not words:
            self.say("Say what?")
            return False
        if words[0] in ("yes", "y"):
            return self.v_yes(cmd)
        if words[0] == "no":
            return self.v_no(cmd)
        self.say("Okay, '%s'." % " ".join(words))
        return True

    def v_magic(self, cmd):
        words = (cmd.arg or "").split()
        if words and words[0] in FEE_FIE:
            return self.fee_fie([w for w in words if w in FEE_FIE])
        s = self.state
        word = words[0]
        rid = s["room"]
        if s["closed"] or s["closing"] is not None:
            self.say("Nothing happens. The cave's magic seems to have faded.")
            return True
        pairs = {"xyzzy": ("building", "debris"), "plugh": ("building", "y2"),
                 "plover": ("y2", "plover")}
        a, b = pairs[word]
        if rid not in (a, b):
            self.say("Nothing happens.")
            return True
        target = b if rid == a else a
        if word == "plover" and self.carried("emerald"):
            self.set_loc("emerald", "plover")
            if rid == "y2":
                self.say("As you say the word, the emerald slips from your grasp... and is "
                         "waiting for you on the floor when you arrive.")
            else:
                self.say("As you say the word, the emerald slips from your grasp and stays behind.")
        if not self.flag("magic_" + word):
            self.set_flag("magic_" + word)
            self.log("Discovered the magic word %s." % word.upper(), "magic")
        self.enter(target, teleport=True)
        return True

    def fee_fie(self, words):
        s = self.state
        done = False
        for w in words:
            if w == FEE_FIE[s["fee"]]:
                s["fee"] += 1
            elif w == "fee":
                s["fee"] = 1
            else:
                s["fee"] = 0
                self.say("Get it right, dummy!")
                return True
            if s["fee"] == 4:
                s["fee"] = 0
                done = True
        if not done:
            self.say("Ok.")
            return True
        if self.loc("eggs") == "giant":
            self.say("Nothing happens.")
            return True
        was_here = self.present("eggs")
        self.set_loc("eggs", "giant")
        self.state["items"]["eggs"]["moved"] = True
        if self.state["room"] == "giant":
            self.say("A large nest full of golden eggs suddenly appears out of nowhere!")
        elif was_here:
            self.say("The nest of golden eggs has vanished!")
        else:
            self.say("Done!")
        self.log("Summoned the golden eggs back to the Giant Room.", "magic")
        return True

    def v_blast(self, cmd):
        s = self.state
        dyn = self.loc("dynamite")
        if not s["closed"] or dyn == "void":
            self.say("Blasting requires dynamite.")
            return False
        here = s["room"]
        if self.carried("dynamite") or dyn == here:
            self.say("There is a loud explosion, and you are suddenly splashed across the walls of the room.")
            self.end_game("You have blown yourself up.")
            return False
        if here == "repo_sw" and dyn == "repo_ne":
            s["blast"] = 45
            s["won"] = True
            self.say("There is a tremendous explosion. When the dust settles, a twenty-foot hole "
                     "has appeared in the far wall, and the snoring dwarves are buried under the "
                     "rubble. You march through the hole into the main office, where a cheering "
                     "band of friendly elves carries the conquering adventurer off into the sunset.")
            self.log("Blasted your way out. Victory!", "win")
            self.end_game(None)
            return False
        self.say("There is a loud explosion, and a twenty-foot hole appears in the far wall, "
                 "burying the snakes in the rubble. A river of molten lava pours in through the "
                 "hole, destroying everything in its path, including you!")
        self.end_game("You have been engulfed in lava.")
        return False

    # Endings ---------------------------------------------------------------

    def die(self, msg):
        s = self.state
        self.say(msg)
        s["deaths"] += 1
        self.log("Died. (%s)" % msg.split(".")[0].split("!")[0], "death")
        if s["deaths"] > LIVES:
            self.end_game("You've run out of lives.")
            return
        rid = s["room"]
        for iid in self.inventory_ids():
            self.set_loc(iid, rid)
        if self.loc("lamp") == rid and self.room["region"] != "surface":
            self.set_loc("lamp", "road")
        self.set_istate("lamp", "off")
        s["dwarf"]["here"] = None
        left = LIVES - s["deaths"]
        self.say("Oh dear, you seem to have got yourself killed. Luckily, I've had a little "
                 "practice at reincarnation. There's a puff of orange smoke, and you find "
                 "yourself back in the well house. Your belongings are where you fell, and "
                 "the lamp is by the road. (%s left. Or type UNDO to rewind.)" %
                 ("%d %s" % (left, "life" if left == 1 else "lives") if left else "No lives"))
        s["came_from"] = None
        s["room"] = STORE_ROOM
        self.describe(full=False)

    def end_game(self, reason):
        s = self.state
        s["game_over"] = True
        if reason:
            self.say(reason)
        self.say("You scored %d out of a possible %d, using %d turns.\n%s\n"
                 "Type RESTART to play again, or UNDO to take back that last move." % (
                     self.score(), MAX_SCORE, s["turns"], self.rank()))

    def v_quit(self, cmd):
        self.state["pending"] = "quit"
        self.say("Do you really want to quit now? (yes/no)")
        return False

    def v_restart(self, cmd):
        if self.state["game_over"]:
            self.new_game(baud=self.state["baud"])
            return False
        self.state["pending"] = "restart"
        self.say("Are you sure you want to start a new game? (yes/no)")
        return False

    # Undo, save, restore ------------------------------------------------------

    def undo(self):
        if not self.undo_stack:
            self.say("There's nothing to undo.")
            return
        baud = self.state["baud"]
        self.state = json.loads(self.undo_stack.pop())
        self.state["baud"] = baud
        self.say("Undone.")
        self.describe(full=False)

    def _save_path(self, name):
        name = re.sub(r"[^a-z0-9_-]", "", (name or "").lower()) or "quicksave"
        return name, os.path.join(self.save_dir, name + ".json")

    def v_save(self, cmd):
        if not self.save_dir:
            self.say("Saving isn't available here.")
            return False
        name, path = self._save_path(cmd.arg)
        os.makedirs(self.save_dir, exist_ok=True)
        with open(path, "w") as fh:
            json.dump({"version": SAVE_VERSION, "state": self.state}, fh)
        self.say("Game saved as '%s'. RESTORE %s brings it back." % (name, name.upper()))
        return False

    def saves(self):
        if not self.save_dir or not os.path.isdir(self.save_dir):
            return []
        return sorted(f[:-5] for f in os.listdir(self.save_dir) if f.endswith(".json"))

    def v_restore(self, cmd):
        if not self.save_dir:
            self.say("Restoring isn't available here.")
            return False
        name, path = self._save_path(cmd.arg)
        if not os.path.exists(path):
            names = self.saves()
            if names:
                self.say("There's no save called '%s'. Saved games: %s." % (name, ", ".join(names)))
            else:
                self.say("There are no saved games yet. Type SAVE to make one.")
            return False
        try:
            with open(path) as fh:
                data = json.load(fh)
            state = data["state"]
            if data.get("version") != SAVE_VERSION or state.get("room") not in ROOMS:
                raise ValueError("incompatible save")
        except (ValueError, KeyError, OSError):
            self.say("That save file can't be read.")
            return False
        self.undo_stack.append(json.dumps(self.state))
        baud = self.state["baud"]
        self.state = state
        self.state["baud"] = baud
        self.say("Restored '%s'." % name)
        self.describe(full=True)
        return False

    # Odds and ends for views ---------------------------------------------

    def treasure_status(self, iid):
        if self.broken(iid) or (self.loc(iid) == "void" and self.flag("troll_took") == iid):
            return "lost"
        if self.stored(iid):
            return "stored"
        if self.carried(iid):
            return "carried"
        if iid in self.state["seen"] or iid in self.state["found"]:
            return "seen"
        return "unknown"

    def regions_visited(self):
        seen = {ROOMS[r]["region"] for r in self.state["visited"] if r in ROOMS}
        return [rid for rid, _n in REGIONS if rid in seen]
