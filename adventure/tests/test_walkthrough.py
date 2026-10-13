"""A complete solution must score the full 350 points."""

import unittest

from advent.engine import Game

# Each block is one trip out from the well house and back. Lines starting
# with "#" are notes.
SOLUTION = """
# 1. Supplies, the grate, the bird, the rod, and the first five treasures
e
take keys, lamp, food and bottle
w
s
s
s
unlock grate with keys
d
light lamp
w
take cage
w
w
w
catch bird
e
e
take rod
w
w
w
d
e
take nugget
w
w
wave rod
w
take diamonds
e
e
s
release bird
drop cage
w
take coins
e
s
take jewelry
n
e
take silver
e
plugh
drop treasures

# 2. Plover Room and the Dark Room: emerald and platinum pyramid
plugh
plover
drop all
take emerald
e
drop emerald
w
take all
s
take pyramid
n
plover
plugh
drop pyramid

# 3. Magazine to Witt's End, pillow, Ming vase, and the emerald from the alcove
plugh
w
d
w
s
s
take magazine
e
drop magazine
w
n
w
w
sw
take pillow
ne
nw
take vase
n
w
take emerald
e
s
se
e
e
n
e
u
e
plugh
drop pillow
drop vase
drop emerald

# 4. Beanstalk, golden eggs, oiled door, trident, and the pearl from the clam
plugh
w
d
w
s
w
w
w
w
d
pour water on plant
u
sw
s
s
s
fill bottle
n
n
n
ne
d
water plant
u
e
d
fill bottle
u
w
u
w
take eggs
n
pour oil on door
n
take trident
e
d
e
se
e
e
u
open clam
s
s
take pearl
n
n
d
n
e
u
e
plugh
drop eggs
drop trident
drop pearl

# 5. Slay the dragon for the Persian rug
plugh
w
w
sw
w
kill dragon
yes
take rug
e
ne
e
e
plugh
drop rug

# 6. The pirate's chest in the twisty maze
plugh
w
w
n
w
w
w
s
s
s
take chest
n
n
n
e
e
e
s
e
e
plugh
drop chest

# 7. Pay the troll with the eggs; spices; tame the bear for the golden chain
take eggs
plugh
w
d
w
s
w
w
nw
w
s
d
throw eggs at troll
ne
e
e
ne
e
take spices
w
n
s
sw
se
e
e
feed bear
unlock chain
take chain
w
w
nw
w
w
sw
u
n
e
se
e
e
n
e
u
e
plugh
drop spices
drop chain

# 8. Summon the eggs home to the Giant Room, then fetch them again
fee fie foe foo
plugh
w
d
w
s
w
w
nw
w
u
w
s
s
take eggs
n
n
e
d
e
se
e
e
n
e
u
e
plugh
drop eggs
"""

ENDGAME = ["wait"] * 14 + ["sw", "take rod", "ne", "drop rod", "sw", "blast"]

TROUBLE = ("I see no", "can't go that way", "Nothing happens", "I don't know",
           "pitch dark", "You aren't carrying")


class WalkthroughTest(unittest.TestCase):

    def test_full_solution_scores_350(self):
        g = Game(seed=7, peaceful=True)
        for line in SOLUTION.strip().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            out = "\n".join(g.do(line).lines)
            for bad in TROUBLE:
                self.assertNotIn(bad, out, "%r went wrong:\n%s" % (line, out))
        self.assertTrue(all(g.stored(t) for t in g.state["found"]))
        self.assertEqual(len(g.state["found"]), 15)
        self.assertIsNotNone(g.state["closing"])
        for line in ENDGAME:
            g.do(line)
        self.assertTrue(g.state["closed"])
        self.assertTrue(g.state["won"])
        self.assertTrue(g.state["game_over"])
        self.assertEqual(g.score(), 350)


if __name__ == "__main__":
    unittest.main()
