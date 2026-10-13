import os
import shutil
import tempfile
import unittest

from advent.engine import Game
from advent.world import ITEMS, ROOMS


def out(result):
    return "\n".join(result.lines)


def setup(room, carrying=(), peaceful=True, **items):
    """A game with the player dropped straight into `room`."""
    g = Game(seed=3, peaceful=peaceful)
    g.state["room"] = room
    g.state["visited"][room] = 0
    for iid in carrying:
        g.set_loc(iid, "player")
    for iid, where in items.items():
        g.set_loc(iid, where)
    g.set_istate("lamp", "on")
    return g


class MovementTests(unittest.TestCase):

    def test_aliases_and_exits_line(self):
        g = Game(seed=1, peaceful=True)
        r = g.do("enter building")
        self.assertEqual(g.state["room"], "building")
        self.assertIn("Exits: west.", out(r))
        g.do("out")
        self.assertEqual(g.state["room"], "road")
        g.do("downstream")
        self.assertEqual(g.state["room"], "valley")

    def test_bad_direction_lists_exits(self):
        g = Game(seed=1, peaceful=True)
        self.assertIn("Exits:", out(g.do("ne")))

    def test_back_retraces(self):
        g = Game(seed=1, peaceful=True)
        g.do("s")
        g.do("back")
        self.assertEqual(g.state["room"], "road")

    def test_goto_walks_known_route(self):
        g = Game(seed=1, peaceful=True)
        g.do("s. s. s")
        self.assertEqual(g.state["room"], "depression")
        before = g.state["turns"]
        r = g.do("go to end of road")
        self.assertEqual(g.state["room"], "road")
        self.assertEqual(g.state["turns"], before + 3)
        self.assertIn("via", out(r))

    def test_goto_unknown_place(self):
        g = Game(seed=1, peaceful=True)
        self.assertIn("haven't been anywhere", out(g.do("go to giant room")))

    def test_darkness_only_lets_you_retreat(self):
        g = setup("cobble", carrying=["lamp"])
        g.set_istate("lamp", "off")
        g.state["came_from"] = "below_grate"
        g.do("w")                                    # debris room, unlit
        self.assertEqual(g.state["room"], "debris")
        self.assertIn("pitch dark", out(g.do("look")))
        r = g.do("w")                                # unknown passage: refused
        self.assertEqual(g.state["room"], "debris")
        self.assertIn("darkness", out(r))
        g.do("e")                                    # the way back is fine
        self.assertEqual(g.state["room"], "cobble")

    def test_magic_words(self):
        g = setup("building")
        g.do("xyzzy")
        self.assertEqual(g.state["room"], "debris")
        g.do("xyzzy")
        self.assertEqual(g.state["room"], "building")
        self.assertIn("Nothing happens", out(setup("valley").do("plugh")))


class PuzzleTests(unittest.TestCase):

    def test_grate_needs_keys(self):
        g = setup("depression")
        self.assertIn("no keys", out(g.do("unlock grate")))
        self.assertIn("locked steel grate", out(g.do("d")))
        g.set_loc("keys", "player")
        g.do("unlock grate")
        g.do("d")
        self.assertEqual(g.state["room"], "below_grate")

    def test_bird_fears_rod_and_needs_cage(self):
        g = setup("bird_ch", carrying=["lamp", "rod", "cage"])
        self.assertIn("takes fright", out(g.do("catch bird")))
        g.do("drop rod")
        self.assertIn("catch the bird", out(g.do("catch bird")))
        self.assertEqual(g.loc("bird"), "in:cage")

    def test_bird_drives_off_snake(self):
        g = setup("mtking", carrying=["lamp", "cage"], bird="in:cage")
        self.assertIn("snake", out(g.do("w")))
        self.assertEqual(g.state["room"], "mtking")
        self.assertIn("drives the snake away", out(g.do("release bird")))
        g.do("w")
        self.assertEqual(g.state["room"], "west_ch")

    def test_crystal_bridge(self):
        g = setup("fissure_e", carrying=["lamp", "rod"])
        self.assertIn("too wide", out(g.do("w")))
        self.assertIn("crystal bridge", out(g.do("wave rod")))
        g.do("cross")
        self.assertEqual(g.state["room"], "fissure_w")
        g.do("wave rod")
        self.assertIn("too wide", out(g.do("e")))

    def test_nugget_wont_go_up_the_steps(self):
        g = setup("hall_mists", carrying=["lamp", "nugget"])
        self.assertIn("unclimbable", out(g.do("u")))
        self.assertEqual(g.state["room"], "hall_mists")
        g.do("drop nugget")
        g.do("u")
        self.assertEqual(g.state["room"], "small_pit")

    def test_plover_tunnel_and_word(self):
        g = setup("alcove", carrying=["lamp"])
        self.assertIn("won't fit", out(g.do("w")))
        g.do("drop lamp")
        g.do("w")
        self.assertEqual(g.state["room"], "plover")
        g.do("take emerald")
        g.do("e")
        self.assertEqual(g.state["room"], "alcove")
        g2 = setup("y2", carrying=["lamp", "emerald"])
        g2.do("plover")
        self.assertEqual(g2.state["room"], "plover")
        self.assertEqual(g2.loc("emerald"), "plover")

    def test_vase_needs_pillow_and_undo_saves_it(self):
        g = setup("building", carrying=["vase"])
        self.assertIn("delicate crash", out(g.do("drop vase")))
        self.assertTrue(g.broken("vase"))
        g.do("undo")
        self.assertFalse(g.broken("vase"))
        self.assertTrue(g.carried("vase"))
        g.set_loc("pillow", "building")
        self.assertIn("velvet pillow", out(g.do("drop vase")))
        self.assertTrue(g.stored("vase"))

    def test_dragon_bare_hands(self):
        g = setup("lair", carrying=["lamp"])
        g.state["came_from"] = "secret_ew"
        self.assertIn("nasty", out(g.do("w")))
        self.assertIn("can't be serious", out(g.do("take rug")))
        self.assertIn("bare hands?", out(g.do("kill dragon")))
        self.assertIn("vanquished", out(g.do("yes")))
        g.do("take rug")
        self.assertTrue(g.carried("rug"))
        g.do("w")
        self.assertEqual(g.state["room"], "secret_ns")

    def test_dragon_no_answer(self):
        g = setup("lair", carrying=["lamp"])
        g.do("attack dragon")
        g.do("no")
        self.assertEqual(g.istate("dragon"), "alive")

    def test_troll_and_eggs(self):
        g = setup("chasm_sw", carrying=["lamp", "keys", "eggs"])
        self.assertIn("refuses", out(g.do("ne")))
        self.assertIn("tosses it back", out(g.do("throw keys at troll")))
        g.do("take keys")
        self.assertIn("scurries away", out(g.do("throw eggs to troll")))
        g.do("cross")
        self.assertEqual(g.state["room"], "chasm_ne")
        g.do("fee fie foe foo")
        self.assertEqual(g.loc("eggs"), "giant")

    def test_fee_fie_one_word_at_a_time(self):
        g = setup("building", eggs="building")
        for w in ("fee", "fie", "foe"):
            self.assertIn("Ok", out(g.do(w)))
        g.do("foo")
        self.assertEqual(g.loc("eggs"), "giant")
        self.assertIn("Get it right", out(g.do("fie")))

    def test_bear_and_chain(self):
        g = setup("barren", carrying=["lamp", "keys", "food"])
        self.assertIn("no way to get past the bear", out(g.do("unlock chain")))
        self.assertIn("still locked", out(g.do("take chain")))
        g.do("feed bear")
        g.do("unlock chain with keys")
        g.do("take chain")
        self.assertTrue(g.carried("chain"))
        g.do("w")
        self.assertEqual(g.loc("bear"), "barren_front")

    def test_bear_stops_at_bridge(self):
        g = setup("chasm_ne", carrying=["lamp"], bear="chasm_ne", troll="void")
        g.set_istate("bear", "free")
        self.assertIn("won't follow", out(g.do("sw")))
        self.assertEqual(g.loc("bear"), "chasm_ne")

    def test_plant_and_beanstalk(self):
        g = setup("west_pit", carrying=["lamp", "bottle"])
        self.assertIn("furious growth", out(g.do("water plant")))
        self.assertIn("empty", out(g.do("pour water")))
        g.set_istate("bottle", "water")
        self.assertIn("explosively", out(g.do("pour water on plant")))
        g.do("u")
        self.assertEqual(g.state["room"], "twopit_w")
        self.assertIn("u", g.exit_dirs())
        g.do("climb beanstalk")
        self.assertEqual(g.state["room"], "narrow_corr")

    def test_beanstalk_hidden_until_grown(self):
        g = setup("twopit_w", carrying=["lamp"])
        self.assertNotIn("u", g.exit_dirs())
        self.assertIn("out of reach", out(g.do("u")))

    def test_rusty_door(self):
        g = setup("immense", carrying=["lamp", "bottle"])
        self.assertIn("rusted shut", out(g.do("n")))
        self.assertIn("won't budge", out(g.do("pour water on door")))
        g.set_istate("bottle", "oil")
        self.assertIn("freed up the hinges", out(g.do("oil door")))
        g.do("n")
        self.assertEqual(g.state["room"], "waterfall")

    def test_clam_and_pearl(self):
        g = setup("shell", carrying=["lamp"])
        self.assertIn("strong enough", out(g.do("open clam")))
        g.set_loc("trident", "player")
        self.assertIn("pearl", out(g.do("open clam with trident")))
        self.assertEqual(g.loc("pearl"), "cul")

    def test_vending_machine_and_batteries(self):
        g = setup("d5", carrying=["lamp", "coins"])
        g.state["lamp"] = 20
        self.assertIn("fresh batteries", out(g.do("put coins in machine")))
        g.do("take coins")
        self.assertTrue(g.carried("coins"))
        g.do("take batteries")
        g.do("replace batteries")
        self.assertGreater(g.state["lamp"], 1000)

    def test_lamp_runs_out(self):
        g = setup("debris", carrying=["lamp"])
        g.state["lamp"] = 1
        r = g.do("wait")
        self.assertIn("run out of power", out(r))
        self.assertFalse(g.lit())

    def test_magazine_point(self):
        g = setup("witts", carrying=["lamp", "magazine"])
        before = g.score()
        g.do("drop magazine")
        self.assertEqual(g.score(), before + 1)

    def test_closing_and_blast(self):
        g = setup("building")
        for t in [i for i in ITEMS if ITEMS[i]["treasure"]]:
            g.set_loc(t, "building")
        g.set_istate("vase", "ok")
        self.assertIn("sepulchral", out(g.do("wait")))
        for _ in range(15):
            g.do("wait")
        self.assertEqual(g.state["room"], "repo_ne")
        self.assertEqual(g.inventory_ids(), [])
        g.do("sw. take rod. blast")
        self.assertTrue(g.state["game_over"])
        self.assertFalse(g.state["won"])


class SystemTests(unittest.TestCase):

    def test_take_all_and_inventory(self):
        g = Game(seed=1, peaceful=True)
        g.do("e")
        r = g.do("take all")
        self.assertEqual(len(g.inventory_ids()), 4)
        self.assertIn("Brass lantern", out(g.do("i")))
        self.assertEqual(len(r.view["inventory"]), 4)

    def test_carry_limit(self):
        g = setup("building")
        for iid in ["keys", "lamp", "food", "bottle", "cage", "rod", "pillow",
                    "magazine", "axe", "nugget"]:
            g.set_loc(iid, "player")
        g.set_loc("silver", "building")
        self.assertIn("can't carry anything more", out(g.do("take silver")))

    def test_undo_and_again(self):
        g = Game(seed=1, peaceful=True)
        g.do("s")
        g.do("again")
        self.assertEqual(g.state["room"], "slit")
        g.do("undo")
        self.assertEqual(g.state["room"], "valley")
        self.assertIn("nothing to undo", out(Game(seed=1).do("undo")))

    def test_save_and_restore(self):
        tmp = tempfile.mkdtemp()
        try:
            g = Game(seed=1, peaceful=True, save_dir=tmp)
            g.do("s")
            self.assertIn("saved", out(g.do("save test-1")))
            g.do("s")
            g.do("restore test-1")
            self.assertEqual(g.state["room"], "valley")
            self.assertIn("no save called", out(g.do("restore nope")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "test-1.json")))
        finally:
            shutil.rmtree(tmp)

    def test_baud(self):
        g = Game(seed=1)
        g.do("baud 1200")
        self.assertEqual(g.state["baud"], 1200)
        self.assertIn("Choose one of", out(g.do("baud 1234")))
        g.do("baud off")
        self.assertEqual(g.state["baud"], 0)

    def test_score_starts_at_36(self):
        self.assertEqual(Game(seed=1).score(), 36)

    def test_unknown_word_suggestion(self):
        self.assertIn("Did you mean 'north'", out(Game(seed=1).do("nroth")))

    def test_hints_are_contextual(self):
        g = setup("mtking", carrying=["lamp"])
        self.assertIn("RELEASE BIRD", out(g.do("hint")))

    def test_where_is(self):
        g = Game(seed=1, peaceful=True)
        g.do("e")
        g.do("w")
        self.assertIn("Well House", out(g.do("where is the lamp")))

    def test_restart_needs_confirmation(self):
        g = Game(seed=1, peaceful=True)
        g.do("s")
        g.do("restart")
        self.assertEqual(g.state["room"], "valley")
        g.do("restart")
        g.do("yes")
        self.assertEqual(g.state["room"], "road")

    def test_death_and_reincarnation(self):
        g = setup("hall_mists", carrying=["lamp", "keys"])
        g.die("Splat.")
        self.assertEqual(g.state["room"], "building")
        self.assertEqual(g.loc("keys"), "hall_mists")
        self.assertEqual(g.loc("lamp"), "road")
        self.assertEqual(g.score(), 36 - 10)        # one life spent

    def test_state_is_json_round_trippable(self):
        import json
        g = Game(seed=1)
        g.do("e. take all. w")
        self.assertEqual(json.loads(json.dumps(g.state)), g.state)


class RobustnessTests(unittest.TestCase):

    def test_magic_word_with_extra_words(self):
        g = setup("building")
        self.assertIn("Get it right", out(g.do("fie treasure")))
        g.do("xyzzy lamp")
        self.assertEqual(g.state["room"], "debris")

    def test_random_commands_never_crash(self):
        import random
        from advent.vocab import DIR_WORDS, completion_words
        words = completion_words()
        dirs = list(DIR_WORDS)
        for seed in (11, 12):
            rnd = random.Random(seed)
            g = Game(seed=seed)
            for _ in range(400):
                if rnd.random() < 0.5:
                    cmd = rnd.choice(dirs)
                else:
                    cmd = " ".join(rnd.choice(words) for _ in range(rnd.randint(1, 4)))
                self.assertIsInstance(g.do(cmd).lines, list)


class DwarfTests(unittest.TestCase):

    def test_dwarves_appear_and_can_be_killed(self):
        g = setup("hall_mists", carrying=["lamp"], peaceful=False)
        g.set_flag("dwarves")
        g.set_flag("dwarves_turn", 0)
        g.state["turns"] = 10
        axe_seen = False
        for _ in range(200):
            g.do("wait")
            if g.loc("axe") != "void":
                axe_seen = True
                break
        self.assertTrue(axe_seen)
        g.do("take axe")
        g.state["dwarf"].update(here="hall_mists", armed=False)
        for _ in range(10):
            if g.state["dwarf"]["here"] != "hall_mists":
                break
            g.do("throw axe at dwarf")
            g.do("take axe")
        self.assertLess(g.state["dwarf"]["remaining"], 5)

    def test_peaceful_mode_has_no_dwarves(self):
        g = setup("hall_mists", carrying=["lamp"], peaceful=True)
        g.do("d. u. d. u. d. u")
        for _ in range(100):
            g.do("wait")
        self.assertEqual(g.loc("axe"), "void")

    def test_dwarves_never_on_surface(self):
        for rid, r in ROOMS.items():
            if r["region"] == "surface":
                self.assertTrue(r["no_dwarf"], rid)


if __name__ == "__main__":
    unittest.main()
