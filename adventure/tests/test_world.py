"""The map must never be impossible: these tests hold the cave to that."""

import math
import unittest
from collections import deque

from advent.world import (DIRECTIONS, ITEMS, OPPOSITE, REGION_NAMES, ROOMS,
                          START_ROOM, TREASURES, VECTORS)

# Passages that deliberately run one way only.  There are none at present;
# any addition must say so in its room text.
ONE_WAY = set()


def sign(v):
    return (v > 0) - (v < 0)


def dist_point_segment(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = ((px - ax) * dx + (py - ay) * dy) / float(dx * dx + dy * dy)
    if t <= 0 or t >= 1:
        return float("inf")          # beyond the ends: not "on" the passage
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


class WorldTests(unittest.TestCase):

    def test_exit_targets_exist(self):
        for rid, r in ROOMS.items():
            for d, (target, _gate) in r["exits"].items():
                self.assertIn(target, ROOMS, "%s %s -> %s" % (rid, d, target))

    def test_regions_known(self):
        for rid, r in ROOMS.items():
            self.assertIn(r["region"], REGION_NAMES, rid)

    def test_aliases_point_at_real_exits(self):
        for rid, r in ROOMS.items():
            for word, d in r["aliases"].items():
                self.assertIn(d, DIRECTIONS, "%s alias %s" % (rid, word))
                self.assertIn(d, r["exits"], "%s alias %r -> %s has no exit" % (rid, word, d))
                self.assertNotIn(word, DIRECTIONS, "%s aliases a direction word" % rid)

    def test_compass_exits_point_the_way_they_say(self):
        for rid, r in ROOMS.items():
            for d, (target, _gate) in r["exits"].items():
                t = ROOMS[target]
                if d not in VECTORS or t["region"] != r["region"]:
                    continue
                vx, vy = VECTORS[d]
                dx, dy = t["x"] - r["x"], t["y"] - r["y"]
                self.assertEqual((sign(dx), sign(dy)), (vx, vy),
                                 "%s --%s--> %s is drawn the wrong way" % (rid, d, target))

    def test_every_passage_can_be_walked_back(self):
        for rid, r in ROOMS.items():
            for d, (target, _gate) in r["exits"].items():
                if (rid, d) in ONE_WAY:
                    continue
                back = ROOMS[target]["exits"].get(OPPOSITE[d])
                self.assertIsNotNone(back, "%s --%s--> %s has no way back %s"
                                     % (rid, d, target, OPPOSITE[d]))
                self.assertEqual(back[0], rid, "%s --%s--> %s but %s leads to %s"
                                 % (rid, d, target, OPPOSITE[d], back[0]))

    def test_no_two_rooms_share_a_cell(self):
        seen = {}
        for rid, r in ROOMS.items():
            key = (r["region"], r["x"], r["y"])
            self.assertNotIn(key, seen, "%s and %s overlap" % (rid, seen.get(key)))
            seen[key] = rid

    def test_no_passage_runs_through_another_room(self):
        by_region = {}
        for rid, r in ROOMS.items():
            by_region.setdefault(r["region"], []).append(r)
        for rid, r in ROOMS.items():
            for d, (target, _gate) in r["exits"].items():
                t = ROOMS[target]
                if t["region"] != r["region"]:
                    continue
                a, b = (r["x"], r["y"]), (t["x"], t["y"])
                for other in by_region[r["region"]]:
                    if other["id"] in (rid, target):
                        continue
                    gap = dist_point_segment((other["x"], other["y"]), a, b)
                    self.assertGreater(gap, 0.4, "%s --%s--> %s passes through %s"
                                       % (rid, d, target, other["id"]))

    def test_everything_reachable_with_puzzles_solved(self):
        seen = {START_ROOM}
        queue = deque([START_ROOM])
        while queue:
            rid = queue.popleft()
            for target, _gate in ROOMS[rid]["exits"].values():
                if target not in seen:
                    seen.add(target)
                    queue.append(target)
        unreachable = set(ROOMS) - seen - {"repo_ne", "repo_sw"}
        self.assertEqual(unreachable, set())

    def test_fifteen_treasures_in_real_places(self):
        self.assertEqual(len(TREASURES), 15)
        total = sum(ITEMS[t]["treasure"] for t in TREASURES)
        self.assertEqual(total, 188)
        for t in TREASURES:
            start = ITEMS[t]["start"]
            if t == "pearl":
                self.assertEqual(start, "void")   # it's inside the clam
            else:
                self.assertIn(start, ROOMS, t)

    def test_item_nouns_and_starts(self):
        for iid, it in ITEMS.items():
            self.assertTrue(it["nouns"], iid)
            self.assertTrue(it["start"] == "void" or it["start"] in ROOMS, iid)
            for extra in it["also"]:
                self.assertIn(extra, ROOMS, iid)


if __name__ == "__main__":
    unittest.main()
