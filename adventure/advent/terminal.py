"""Play in a plain terminal: amber text arriving down a slow serial line."""

import os
import shutil
import sys
import textwrap
import time

AMBER = "\033[38;5;214m"
BRIGHT = "\033[1;38;5;221m"
RESET = "\033[0m"


def _wrap(paragraph, width):
    out = []
    for line in paragraph.split("\n"):
        if len(line) <= width or line.startswith(" ") or "--[" in line or "]--" in line:
            out.append(line)
        else:
            out.append(textwrap.fill(line, width))
    return "\n".join(out)


def _ready_to_read():
    """True if the player has pressed Enter (POSIX only)."""
    try:
        import select
        return bool(select.select([sys.stdin], [], [], 0)[0])
    except (ImportError, OSError, ValueError):
        return False


def run(game, out=sys.stdout, inp=sys.stdin):
    colour = out.isatty() and not os.environ.get("NO_COLOR")
    interactive = inp.isatty()
    typed_ahead = []

    def emit(lines):
        width = max(40, min(shutil.get_terminal_size((80, 24)).columns, 100) - 2)
        text = "\n\n".join(_wrap(p, width) for p in lines) + "\n\n"
        baud = game.state["baud"]
        cps = baud / 10.0 if (baud and interactive) else 0
        if colour:
            out.write(AMBER)
        i = 0
        try:
            if cps:
                delay = 1.0 / cps
                while i < len(text):
                    out.write(text[i])
                    out.flush()
                    i += 1
                    time.sleep(delay)
                    if text[i - 1] == "\n" and _ready_to_read():
                        line = inp.readline()
                        if line.strip():
                            typed_ahead.append(line.strip())
                        break
        except KeyboardInterrupt:
            pass
        out.write(text[i:])
        if colour:
            out.write(RESET)
        out.flush()

    emit(["(Type commands at the > prompt. Ctrl+C or Enter skips slow text; "
          "Ctrl+D quits. BAUD 0 turns the delay off.)"] + game.state.get("last_output", []))
    while True:
        if typed_ahead:
            line = typed_ahead.pop(0)
        else:
            try:
                if colour:
                    out.write(BRIGHT)
                line = input("> ")
                if colour:
                    out.write(RESET)
            except (EOFError, KeyboardInterrupt):
                out.write((RESET if colour else "") + "\nGoodbye.\n")
                return 0
        result = game.do(line)
        emit(result.lines)
