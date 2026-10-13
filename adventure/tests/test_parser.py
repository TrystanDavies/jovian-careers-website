import unittest

from advent.parser import parse


def one(text):
    cmds = parse(text)
    assert len(cmds) == 1, cmds
    return cmds[0]


class ParserTests(unittest.TestCase):

    def test_directions(self):
        self.assertEqual(one("n").direction, "n")
        self.assertEqual(one("go north-east").direction, "ne")
        self.assertEqual(one("downstairs").direction, "d")

    def test_aliases_are_not_prefix_matched_as_directions(self):
        c = one("downstream")
        self.assertEqual((c.verb, c.direction, c.arg), ("go", None, "downstream"))

    def test_articles_and_lists(self):
        c = one("take the lamp, the keys and some food")
        self.assertEqual(c.verb, "take")
        self.assertEqual(c.objs, [["lamp"], ["keys"], ["food"]])

    def test_two_word_verbs(self):
        self.assertEqual(one("pick up the rod").verb, "take")
        self.assertEqual(one("turn the lamp on").verb, "light")
        self.assertEqual(one("lamp off").verb, "extinguish")
        self.assertEqual(one("look at rod").verb, "examine")
        self.assertEqual(one("where is the bird").verb, "find")

    def test_prepositions(self):
        c = one("unlock grate with keys")
        self.assertEqual((c.objs, c.prep, c.iobj), ([["grate"]], "with", ["keys"]))
        c = one("feed food to bear")
        self.assertEqual((c.objs, c.iobj), ([["bear"]], ["food"]))

    def test_chaining(self):
        cmds = parse("take lamp. e then w; inventory")
        self.assertEqual([c.verb for c in cmds], ["take", "go", "go", "inventory"])

    def test_magic(self):
        self.assertEqual(one("xyzzy").verb, "magic")
        self.assertEqual(one("say plugh").arg, "plugh")
        self.assertEqual(one("fee fie foe foo").arg, "fee fie foe foo")

    def test_five_letter_abbreviations(self):
        self.assertEqual(one("inven").verb, "inventory")
        self.assertEqual(one("exami lamp").verb, "examine")

    def test_goto(self):
        c = one("go to the hall of mists")
        self.assertEqual((c.verb, c.arg), ("goto", "hall of mists"))

    def test_unknown_words(self):
        self.assertIn("Did you mean", one("lmap").error)
        self.assertIn("What do you want to do with the lamp", one("lamp").error)


if __name__ == "__main__":
    unittest.main()
