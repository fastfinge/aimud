"""
Another word for something this world already knows.

`rulesets` has folded verb spellings since crafting taught a world that `forge`
means `make`: world-scoped on purpose, because a server runs many worlds and
only some of them are about smithing. What it could never fold is a **noun**,
and that is the half an invented word actually needs.

A world that declares a kind called `raygun` has the kind, the affordances and
every rule filed against it, and a player who types `blaster` gets nothing --
or worse, gets a second object conjured beside the first, because a word the
game does not know is indistinguishable from a word it has not met. The
register exists and the way in does not.

So this is both halves in one place:

* **a verb fold** sends one spelling to another verb, which is what
  `rulesets` already wrote and `verbs.canonical_verb` already reads;
* **a noun fold** sends one spelling to a kind, and everything of that kind in
  reach answers to it -- through `naming.best_match`, alongside an object's own
  aliases, which is where a conjured thing's second name already lives.

**Never in front of English.** `VERB_SYNONYMS` is consulted first and this
second, exactly as a ruleset's folds are, for the reason written there: a world
that could move `get` or `look` underneath the engine would be a data file
rewriting the game.

**A fold is not a kind and does not ground anything.** `blaster` is a spelling
for `raygun`; it has no spec, no affordances and no place in the taxonomy, and
`kinds.canonical` never sees it. Grounding is what a kind's sense and anchor
are for.
"""

from evennia.utils import logger

#: Where the two halves live. The verb side keeps the name rulesets wrote it
#: under: every world in play holds one, and a rename would buy tidiness and
#: cost a migration.
VERBS_ATTR = "verb_synonyms"
NOUNS_ATTR = "noun_folds"


def _store(world_root, attr):
    if world_root is None:
        return {}
    return dict(getattr(world_root.db, attr, None) or {})


def verbs_of(world_root):
    """{spelling: the verb it means} for this world."""
    return _store(world_root, VERBS_ATTR)


def nouns_of(world_root):
    """{spelling: the kind it means} for this world."""
    return _store(world_root, NOUNS_ATTR)


def all_folds(world_root):
    """Both halves at once, for a listing."""
    found = dict(verbs_of(world_root))
    found.update(nouns_of(world_root))
    return found


def means(world_root, word):
    """What one spelling means here, or ""."""
    return all_folds(world_root).get(str(word or "").strip().lower(), "")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def fold(world_root, word, meaning, noun=False):
    """
    Teach this world a spelling. Returns whether anything changed.

    The low door, for `rulesets` and for anything else with a document in its
    hand. `add` is the one with the complaints in it.
    """
    word = str(word or "").strip().lower()
    meaning = str(meaning or "").strip().lower() if not noun \
        else str(meaning or "").strip()
    if not word or not meaning or word == meaning or world_root is None:
        return False
    attr = NOUNS_ATTR if noun else VERBS_ATTR
    stored = _store(world_root, attr)
    if stored.get(word) == meaning:
        return False
    stored[word] = meaning
    setattr(world_root.db, attr, stored)
    logger.log_info(f"folds: {word!r} means {meaning!r} in {world_root.key}")
    return True


def add(world_root, word, meaning):
    """
    Fold a spelling onto a verb or a kind, working out which. Returns prose.

    Which side it belongs on is not a question for whoever typed it: a word
    means something this world knows, and this world knows which register that
    something is in.
    """
    from world import actions, kinds, verbs

    word = str(word or "").strip().lower()
    meaning = str(meaning or "").strip()
    if not word:
        return "A word is needed."
    if not meaning:
        return f"What should |w{word}|n mean?"
    if " " in word:
        return "A fold is one word, not a phrase."
    if word == meaning.lower():
        return f"|w{word}|n already means itself."

    known = all_folds(world_root)
    if word in known:
        return (f"|w{word}|n already means |w{known[word]}|n here. "
                f"|wdelete word {word}|n takes it back.")

    # English first, and said rather than silently overridden: somebody who
    # types this is owed the reason their world did not change.
    if verbs.VERB_SYNONYMS.get(word) or word in verbs.VERB_SYNONYMS.values():
        return (f"|w{word}|n is already English the game knows everywhere, "
                f"and a world may not move it. Pick another spelling.")

    lowered = meaning.lower()
    if lowered in (actions.vocabulary(world_root) or {}):
        fold(world_root, word, lowered)
        return f"This world now reads |w{word}|n as |w{lowered}|n."
    if kinds.spec(world_root, kinds.canonical(meaning)) is not None:
        settled = kinds.canonical(meaning)
        fold(world_root, word, settled, noun=True)
        return (f"This world now reads |w{word}|n as a |w{settled}|n. "
                f"Anything of that sort in reach answers to it.")
    return (f"This world knows nothing called |w{meaning}|n. A word can only "
            f"mean one of its verbs or one of its sorts of thing. "
            f"|wview kinds|n and |wview actions|n list them.")


def remove(world_root, word):
    """Take a fold back. Returns prose."""
    word = str(word or "").strip().lower()
    for attr in (VERBS_ATTR, NOUNS_ATTR):
        stored = _store(world_root, attr)
        if word in stored:
            stored.pop(word)
            setattr(world_root.db, attr, stored)
            return f"|w{word}|n no longer means anything here."
    return f"This world does not read |w{word}|n as anything."


# ---------------------------------------------------------------------------
# Reading, by whoever is matching a name
# ---------------------------------------------------------------------------

def words_for(world_root, wanted):
    """
    Every spelling folded onto any of these kinds.

    `naming.best_match` asks this for each candidate, so a fold reads exactly
    like an alias: it is another name the thing answers to, and it is scored
    the same way, with the same tolerance for a typo in it.
    """
    if world_root is None or not wanted:
        return []
    wanted = {str(kind) for kind in wanted}
    return [word for word, kind in nouns_of(world_root).items()
            if kind in wanted]
