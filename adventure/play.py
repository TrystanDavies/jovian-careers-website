#!/usr/bin/env python3
"""Colossal Cave: start here.

    python3 play.py               # opens the game in your web browser
    python3 play.py --terminal    # plays in this terminal instead

Needs only Python 3.9 or newer. Nothing to install.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from advent.engine import BAUD_RATES, DEFAULT_BAUD, Game  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Colossal Cave: Advent reworked, with a map, an itinerary and Lowry-palette pictures.")
    ap.add_argument("--terminal", action="store_true", help="play in this terminal instead of the browser")
    ap.add_argument("--port", type=int, default=8765, help="local port for the browser game (default 8765)")
    ap.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser window automatically")
    ap.add_argument("--peaceful", action="store_true", help="no dwarves, no pirate")
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD, choices=BAUD_RATES,
                    help="starting line speed; 0 means no delay (default %d)" % DEFAULT_BAUD)
    ap.add_argument("--seed", type=int, help="fix the random seed")
    args = ap.parse_args(argv)

    game = Game(seed=args.seed, peaceful=args.peaceful, baud=args.baud,
                save_dir=os.path.join(HERE, "saves"))
    if args.terminal:
        from advent.terminal import run
        return run(game)
    from advent.server import serve
    serve(game, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
