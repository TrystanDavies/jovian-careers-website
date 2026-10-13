# Colossal Cave

The original *Colossal Cave Adventure* (Will Crowther, 1976; Don Woods, 1977),
remade with a map that is never impossible.

* **The cave:** 89 locations in seven regions, all 15 treasures, the classic
  puzzles (the bird and the snake, the crystal bridge, the plover tunnel, the
  beanstalk, the rusty door, the clam, the dragon, the troll, the bear) and
  the closing of the cave. 350 points, as before.
* **Navigation you can trust:** every passage leads the way it says and can be
  walked back, and no passage on the map crosses another room. The tests in
  `tests/test_world.py` enforce all of this. The mazes are small, and your map
  keeps track of them.
* **Windows:**
  * **Terminal:** an amber VT-100 where text arrives down a serial line at
    300, 1200, 2400 or 9600 baud (or instantly). Press Enter or Esc to skip
    ahead.
  * **Map:** fills in as you explore, one sheet per region. Click a room
    you've visited to walk there.
  * **Itinerary:** your journey so far, plus a checklist of the treasures.
  * **Inventory:** what you're carrying, with your score, lamp and lives.
  * **Scene:** a painting of where you are, in Lowry's five pigments: flake
    white, ivory black, vermilion, Prussian blue and yellow ochre. Like
    Lowry, it mixes every other colour from those five.

## Playing

```
python3 play.py                 # opens the game in your browser (http://127.0.0.1:8765)
python3 play.py --terminal      # amber text in this terminal; MAP draws an ASCII map
python3 play.py --peaceful      # no dwarves, no pirate
python3 play.py --baud 1200     # start at a slower line speed
```

Nothing to install: the game uses only the Python standard library. By
default the browser version listens only on your own machine (127.0.0.1).
Saved games go in `saves/`.

## Commands

Type plain English: `take the lamp and the keys`, `unlock grate with keys`,
`put vase on pillow`, `throw axe at dwarf`. Chain commands with `then` or
full stops.

| | |
|---|---|
| Moving | `n s e w ne nw se sw up down`, `in`, `out`, `cross`, `climb`, `back`, `go to <place>`, `exits` |
| Things | `take`/`drop` (also `all`, `treasures`), `put`, `give`, `throw`, `examine` (`x`), `read`, `open`, `close`, `lock`, `unlock`, `light`, `extinguish`, `fill`, `pour`, `water`, `oil`, `drink`, `eat`, `wave`, `feed`, `attack`, `break`, `wake` |
| Information | `look` (`l`), `inventory` (`i`), `itinerary`, `map`, `where is <thing>`, `score`, `hint` (free) |
| Game | `save [name]`, `restore [name]`, `undo`, `again` (`g`), `wait` (`z`), `restart`, `quit`, `baud <rate>`, `verbose`, `brief` |

Magic words are said by typing them. As in the original, the first five
letters of a word are enough.

## Tests

```
python3 -m unittest discover -s tests -t .
```

The tests cover the following:
* the map's geometry
* the parser
* every puzzle
* undo, saving and restoring
* the palette rules
* the web server
* a complete walkthrough that scores the full 350 points
