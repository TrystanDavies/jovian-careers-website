"""Turn typed text into commands.

Much friendlier than the original two-word parser: articles are ignored,
several commands can be chained with "then" or full stops, objects can be
listed ("take lamp and keys"), prepositions are understood ("put the vase
on the pillow"), "it" means the last thing you mentioned, and unknown words
get a "did you mean" suggestion.  As in the original, the first five letters
of a word are enough.
"""

import difflib
import re

from .vocab import (ALIAS_WORDS, ARTICLES, DIR_WORDS, MAGIC_WORDS, NOUN_WORDS,
                    PREPOSITIONS, VERB_OF)


class Command(object):
    """One parsed command."""

    def __init__(self, verb, raw, words=None, direction=None, objs=None,
                 prep=None, iobj=None, arg=None, error=None):
        self.verb = verb
        self.raw = raw
        self.words = words or []
        self.direction = direction      # canonical direction, for "go"
        self.objs = objs or []          # list of word-lists
        self.prep = prep
        self.iobj = iobj or []          # word-list
        self.arg = arg                  # free text (say, save, goto, baud)
        self.error = error

    def __repr__(self):
        return "Command(%r, dir=%r, objs=%r, prep=%r, iobj=%r, arg=%r, error=%r)" % (
            self.verb, self.direction, self.objs, self.prep, self.iobj,
            self.arg, self.error)


TWO_WORD = {
    ("pick", "up"): "take",
    ("put", "down"): "drop",
    ("set", "down"): "drop",
    ("let", "go"): "drop",
    ("turn", "on"): "light",
    ("switch", "on"): "light",
    ("turn", "off"): "extinguish",
    ("switch", "off"): "extinguish",
    ("put", "out"): "extinguish",
    ("blow", "out"): "extinguish",
    ("look", "at"): "examine",
    ("look", "in"): "examine",
    ("look", "inside"): "examine",
    ("look", "around"): "look",
    ("look", "for"): "find",
    ("where", "is"): "find",
    ("where", "are"): "find",
    ("blow", "up"): "blast",
    ("set", "off"): "blast",
    ("go", "back"): "back",
    ("go", "to"): "goto",
    ("walk", "to"): "goto",
    ("run", "to"): "goto",
    ("head", "to"): "goto",
    ("travel", "to"): "goto",
    ("return", "to"): "goto",
    ("take", "inventory"): "inventory",
    ("wake", "up"): "wake",
    ("climb", "up"): "climb-u",
    ("climb", "down"): "climb-d",
    ("get", "in"): "enter",
    ("get", "out"): "out",
}

GO_WORDS = {"go", "walk", "run", "travel", "head", "proceed", "move"}

KNOWN_WORDS = (set(VERB_OF) | set(DIR_WORDS) | MAGIC_WORDS | NOUN_WORDS |
               ALIAS_WORDS | PREPOSITIONS | ARTICLES | {"and", "then", "all"})

_SPLIT_RE = re.compile(r"[.;!?]+|\bthen\b")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*|\?|,")


def tokenize(text):
    return _TOKEN_RE.findall(text.lower())


def split_commands(text):
    parts = [p.strip(" ,") for p in _SPLIT_RE.split(text.lower())]
    return [p for p in parts if p]


def lookup_verb(word):
    """Exact word, or a unique prefix of three or more letters."""
    if word in VERB_OF:
        return VERB_OF[word]
    if len(word) >= 3:
        hits = {VERB_OF[w] for w in VERB_OF if w.startswith(word) or
                (len(word) >= 5 and w[:5] == word[:5])}
        if len(hits) == 1:
            return hits.pop()
    return None


def lookup_dir(word):
    if word in DIR_WORDS:
        return DIR_WORDS[word]
    if word in ALIAS_WORDS or word in VERB_OF:
        return None                     # "downstream" is not "downstairs"
    if len(word) >= 5:
        hits = {DIR_WORDS[w] for w in DIR_WORDS if w[:5] == word[:5]}
        if len(hits) == 1:
            return hits.pop()
    return None


def suggest(word):
    pool = sorted(set(VERB_OF) | set(DIR_WORDS) | MAGIC_WORDS | NOUN_WORDS)
    pool = [w for w in pool if len(w) > 1]
    close = difflib.get_close_matches(word, pool, n=1, cutoff=0.72)
    return close[0] if close else None


def _strip_articles(tokens):
    return [t for t in tokens if t not in ARTICLES]


def _noun_lists(tokens):
    """'lamp and keys, bottle' -> [['lamp'], ['keys'], ['bottle']]"""
    groups, cur = [], []
    for t in tokens:
        if t in ("and", ",", "&"):
            if cur:
                groups.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        groups.append(cur)
    return groups


def _split_prep(tokens):
    for i, t in enumerate(tokens):
        if t in PREPOSITIONS and i > 0:
            return tokens[:i], t, tokens[i + 1:]
    if tokens and tokens[0] in PREPOSITIONS:
        return [], tokens[0], tokens[1:]
    return tokens, None, []


def parse_one(text):
    raw = text
    tokens = _strip_articles(tokenize(text))
    while tokens and tokens[0] == ",":
        tokens.pop(0)
    if not tokens or all(t == "," for t in tokens):
        return None
    words = [t for t in tokens if t != ","]

    first = tokens[0]

    # Magic words, alone or in sequence ("fee fie foe foo").
    if all(t in MAGIC_WORDS for t in words):
        return Command("magic", raw, words, arg=" ".join(words))

    # A bare direction ("north", "ne", "down").
    d = lookup_dir(first)
    if d and len(words) == 1:
        return Command("go", raw, words, direction=d)

    # Two-word verbs ("pick up", "turn on", "go to").
    verb = None
    rest = tokens[1:]
    if len(tokens) >= 2 and (first, tokens[1]) in TWO_WORD:
        verb = TWO_WORD[(first, tokens[1])]
        rest = tokens[2:]
    elif len(tokens) >= 2 and first in ("turn", "switch", "pick") and tokens[-1] in ("on", "off", "up"):
        verb = {"on": "light", "off": "extinguish", "up": "take"}[tokens[-1]]
        rest = tokens[1:-1]
    elif len(tokens) >= 2 and tokens[-1] in ("on", "off") and first not in VERB_OF:
        # "lamp on", "lamp off"
        verb = "light" if tokens[-1] == "on" else "extinguish"
        rest = tokens[:-1]

    if verb is None:
        if first in GO_WORDS:
            if len(words) == 1:
                return Command("go", raw, words, error="Where do you want to go?")
            nxt = tokens[1]
            nd = lookup_dir(nxt)
            if nd and len(words) == 2:
                return Command("go", raw, words, direction=nd)
            if nxt in ALIAS_WORDS and len(words) == 2:
                return Command("go", raw, words, arg=nxt)
            if nxt == "back":
                return Command("back", raw, words)
            return Command("goto", raw, words, arg=" ".join(t for t in tokens[1:] if t != ","))
        if first in ALIAS_WORDS and first not in VERB_OF and len(words) == 1:
            return Command("go", raw, words, arg=first)
        verb = lookup_verb(first)
        if verb is None and first in MAGIC_WORDS:
            return Command("magic", raw, words, arg=" ".join(words))
        if verb is None:
            if first in NOUN_WORDS or first in ALIAS_WORDS:
                return Command(None, raw, words,
                               error="What do you want to do with the %s?" % first)
            guess = suggest(first)
            msg = "I don't know the word '%s'." % first
            if guess:
                msg += " Did you mean '%s'?" % guess
            return Command(None, raw, words, error=msg)

    # Verbs that take free text.
    if verb == "say":
        said = [t for t in rest if t != ","]
        if said and all(t in MAGIC_WORDS for t in said):
            return Command("magic", raw, words, arg=" ".join(said))
        return Command("say", raw, words, arg=" ".join(said))
    if verb == "goto":
        return Command("goto", raw, words, arg=" ".join(t for t in rest if t != ","))
    if verb in ("save", "restore", "baud", "help"):
        return Command(verb, raw, words, arg=" ".join(t for t in rest if t != ","))
    if verb == "go":
        # "move north" etc.
        if rest:
            nd = lookup_dir(rest[0])
            if nd:
                return Command("go", raw, words, direction=nd)
        return Command("goto", raw, words, arg=" ".join(rest))
    if verb in ("climb-u", "climb-d"):
        return Command("climb", raw, words, direction=verb[-1], objs=_noun_lists(rest))
    if verb == "climb" and rest:
        nd = lookup_dir(rest[0])
        if nd in ("u", "d") and len(rest) == 1:
            return Command("climb", raw, words, direction=nd)
    if verb == "out" and rest:
        # "leave the lamp" means drop it
        verb = "drop"
    if verb == "enter" and rest:
        target = [t for t in rest if t != ","]
        if len(target) == 1 and target[0] in ALIAS_WORDS:
            return Command("go", raw, words, arg=target[0])
        return Command("go", raw, words, arg="in")
    if verb in ("enter", "out"):
        return Command("go", raw, words, arg="in" if verb == "enter" else "out")

    direct, prep, indirect = _split_prep(rest)
    # "feed food to bear" -> feed bear (with food)
    if verb == "feed" and prep == "to":
        direct, indirect = indirect, direct
        prep = "with"
    # "turn the lamp on" leaves a stray 'on' in direct objects
    direct = [t for t in direct if not (verb in ("light", "extinguish") and t in ("on", "off"))]
    return Command(verb, raw, words, objs=_noun_lists(direct), prep=prep,
                   iobj=[t for t in indirect if t not in (",", "and")])


def parse(text):
    """Parse a whole line into a list of Commands."""
    cmds = []
    for part in split_commands(text):
        c = parse_one(part)
        if c is not None:
            cmds.append(c)
    return cmds
