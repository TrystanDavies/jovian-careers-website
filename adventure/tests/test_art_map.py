"""Lowry's five pigments, and nothing else.

Pictures may use the five pigments and mixtures of them (as Lowry did on his
palette); every mixture must have been made by art.mix() from the five.
The map is drawn with the five pure colours only.
"""

import re
import unittest
import xml.etree.ElementTree as ET

from advent.art import MIXES, PALETTE, allowed_colours, scene_svg
from advent.engine import Game
from advent.mapview import ascii_map, region_svg
from advent.world import ROOMS, REGIONS

PURE = set(c.upper() for c in PALETTE) | {"NONE"}
COLOUR_ATTRS = ("fill", "stroke", "stop-color", "color", "flood-color", "lighting-color")


def colours_ok(testcase, svg, where, pure=False):
    allowed = PURE if pure else allowed_colours() | {"NONE"}
    root = ET.fromstring(svg)
    ids = {el.get("id") for el in root.iter() if el.get("id")}
    for el in root.iter():
        testcase.assertIsNone(el.get("style"), where)
        if pure:
            testcase.assertIsNone(el.get("opacity"), where)
        for attr in COLOUR_ATTRS:
            v = el.get(attr)
            if v is None:
                continue
            m = re.match(r"url\(#([^)]+)\)$", v)
            if m:
                testcase.assertIn(m.group(1), ids, "%s: missing pattern %s" % (where, v))
                continue
            testcase.assertIn(v.upper(), allowed, "%s: colour %s on <%s>" % (where, v, el.tag))


class ArtTests(unittest.TestCase):

    def test_mixes_are_made_from_the_five_pigments(self):
        self.assertTrue(MIXES)
        for colour, recipe in MIXES.items():
            for pigment, weight in recipe:
                self.assertIn(pigment, PALETTE, colour)
                self.assertGreater(weight, 0)

    def test_every_room_scene_is_five_colour(self):
        g = Game(seed=2, peaceful=True)
        g.set_loc("lamp", "player")
        g.set_istate("lamp", "on")
        for rid in ROOMS:
            g.state["room"] = rid
            colours_ok(self, scene_svg(g), rid)

    def test_scenes_with_everything_in_them(self):
        g = Game(seed=2, peaceful=True)
        g.set_istate("lamp", "on")
        for iid in g.state["items"]:
            g.set_loc(iid, "barren")
        g.set_istate("plant", 2)
        g.set_istate("chain", "unlocked")
        g.state["dwarf"]["here"] = "barren"
        g.state["room"] = "barren"
        colours_ok(self, scene_svg(g), "barren-with-everything")

    def test_darkness(self):
        g = Game(seed=2, peaceful=True)
        g.state["room"] = "debris"
        svg = scene_svg(g)
        self.assertIn("PITCH DARK", svg)
        colours_ok(self, svg, "dark")


class MapTests(unittest.TestCase):

    def test_maps_are_five_colour_and_clickable(self):
        g = Game(seed=2, peaceful=True)
        for rid in ROOMS:
            g.state["visited"][rid] = 0
        for region, _name in REGIONS:
            svg = region_svg(g, region)
            colours_ok(self, svg, region, pure=True)
            n = sum(1 for r in ROOMS.values() if r["region"] == region)
            self.assertEqual(svg.count('class="room"'), n, region)

    def test_map_grows_as_you_explore(self):
        g = Game(seed=2, peaceful=True)
        self.assertEqual(region_svg(g, "surface").count('class="room"'), 1)
        g.do("s")
        self.assertEqual(region_svg(g, "surface").count('class="room"'), 2)

    def test_ascii_map_marks_current_room(self):
        g = Game(seed=2, peaceful=True)
        g.do("e")
        text = ascii_map(g, "surface")
        self.assertIn("<Well Hous", text)
        self.assertIn("[End of Ro", text)


if __name__ == "__main__":
    unittest.main()
