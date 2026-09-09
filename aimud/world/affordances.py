"""
What can be done to a thing.

An affordance is half of a verb rule's cache key -- `verbs.signature()` builds
its key out of them, so two things with the same affordances share every rule
either of them ever taught the world. That makes this vocabulary load-bearing
in a way it does not look: a word that drifts here does not degrade a match,
it silently stops matching, and the world pays a model again for something it
already knew.

It drifted. Across five worlds these came back as sixty-four different words,
holding `consumable` beside `edible` beside `drinkable`, `holdable` beside
`wieldable` beside `takeable`, and `smellable` beside `sniffable`.

The fix is to stop inventing a vocabulary that already exists. Every one of
those words is a verb wearing a suffix -- `brewable` is not in any dictionary
but `brew` is, and nine in ten of them come apart the same way. Once they are
verbs again, three things follow that no amount of care with strings would
have given:

* **They fold through `VERB_SYNONYMS`.** That table already knows `consume` is
  `eat`, `take` is `get`, `touch` is `feel`, `listen` is `hear`, `sniff` is
  `smell`. It has been folding player input for as long as the game has run
  and affordances were simply never put through it.

* **Negation stops needing words.** An affordance is an entry in a map, so
  `{"burn": False}` is how a thing does not burn. Nothing has to decide
  whether the opposite of `flammable` is `unburnable`, `fireproof` or
  `nonflammable`, and nothing has to stop a thing being two of them at once --
  a map cannot hold a key twice. States need `register_state()` and exclusive
  groups to get the same guarantee; here it is free, because the group is
  always {yes, no} and never has to be declared.

* **They meet the verbs.** `openable` and `open` were unrelated strings in
  unrelated namespaces. Now an affordance is a verb, which is what it was
  always describing.

Two conventions, because the suffix was carrying them and prose is not:

**Voice is passive.** `-able` always meant *can be done to*: a readable thing
can be read, it cannot read. Every affordance names what happens TO the thing.
The one word that fought this is `flammable`, which is intransitive in English
and becomes `burn` here meaning *can be burned*.

**Where a thing goes is not an affordance.** `container` and `surface` say
that things fit in or on this, which is `world.relations`' question and not
this one. They are kept out, and the list is better for holding one kind of
fact instead of two.
"""

import re

#: Words that do not come apart, because they are Latin rather than English.
#: `edible` has no verb `ed`; the verb is `eat`. Small by nature -- English
#: builds affordances with `-able` and only borrows a handful.
#:
#: `flammable` is the interesting one: it is the only word here whose ordinary
#: reading is active, a thing that burns rather than a thing that can be
#: burned. It folds onto `burn` like the rest, and the passive convention
#: above decides what that means.
_LATINATE = {
    "edible": "eat",
    "potable": "drink",
    "flammable": "burn",
    "inflammable": "burn",
    "combustible": "burn",
    "audible": "hear",
    "visible": "see",
    "legible": "read",
    "comestible": "eat",
    "frangible": "break",
}

#: Not affordances at all, however often a generator offers them. The first
#: two are placement -- `world.relations` answers where a thing goes. The rest
#: are qualities: a sticky thing is not a thing that can be stuck.
NOT_AFFORDANCES = frozenset([
    "container", "surface", "sticky", "resonant", "conductive", "plain",
])

#: Suffixes that turn a verb into "can be verbed".
_SUFFIXES = ("able", "ible", "ble")


def _candidates(word):
    """Every verb `word` might be hiding, longest suffix first."""
    for suffix in _SUFFIXES:
        if not word.endswith(suffix) or len(word) <= len(suffix) + 1:
            continue
        stem = word[: -len(suffix)]
        yield stem                      # readable -> read
        yield stem + "e"                # movable -> move, usable -> use
        if len(stem) > 2 and stem[-1] == stem[-2]:
            yield stem[:-1]             # scrubbable -> scrub
        if stem.endswith("i"):
            yield stem[:-1] + "y"       # deniable -> deny


def _clean(word):
    return re.sub(r"[^a-z_]", "", (word or "").lower().strip()).replace("_", "")


def known_verb(word):
    """
    The dictionary verb an affordance is about, or "" if there is not one.

    Strict: a stem that is not really a verb is rejected rather than invented,
    so "tableable" does not quietly become "table". Kept separate from
    `to_verb` below because two callers want opposite things from a word
    nobody recognises -- one wants to keep it, and one needs to know that it
    was never a word, which is how "unreadable" is told from "unable".
    """
    from world import lexicon
    from world.verbs import canonical_verb

    word = _clean(word)
    if not word or word in NOT_AFFORDANCES:
        return ""

    if word in _LATINATE:
        return canonical_verb(_LATINATE[word])

    for candidate in _candidates(word):
        if "v" in lexicon.parts_of_speech(candidate):
            return canonical_verb(candidate)

    # Already a verb, said plainly. A generator that writes "read" rather than
    # "readable" has said the same thing and should not be punished for it.
    if "v" in lexicon.parts_of_speech(word):
        return canonical_verb(word)
    return ""


def to_verb(word):
    """
    The verb an affordance is about, keeping the word itself as a last resort.

    A world that invents "scryable" for something no dictionary has a word for
    is doing what this game is for, so an unrecognised affordance is folded to
    one spelling rather than thrown away. `known_verb` is the strict form.
    """
    from world.verbs import canonical_verb

    word = _clean(word)
    if not word or word in NOT_AFFORDANCES:
        return ""
    return known_verb(word) or canonical_verb(word)


def normalise(declared):
    """
    Whatever a generator offered, as {verb: bool}.

    Accepts the list every prompt used to ask for, the map they ask for now,
    and a list with negations written the way people write them -- "not
    burnable", "-burn", "unreadable" -- because a model told it may say no
    will find a way to say no whatever the schema said.

    Later entries win. A reply that says a thing both burns and does not is
    contradicting itself in one breath, and there is nothing to be learned
    from the earlier half.
    """
    if not declared:
        return {}

    items = []
    try:
        items = list(declared.items())
    except AttributeError:
        for entry in declared:
            text = str(entry).lower().strip()
            negated = False
            for prefix in ("not ", "no ", "cannot ", "can not ", "can't ", "-"):
                if text.startswith(prefix):
                    negated, text = True, text[len(prefix):].strip()
                    break
            else:
                # "unreadable", "nonflammable". Stripped only when the rest is
                # a verb the dictionary knows AND the whole word is not --
                # which is what keeps "inflatable" from becoming "not flatable"
                # and "unable" from becoming "not able".
                for prefix in ("un", "non", "in", "im"):
                    rest = text[len(prefix):]
                    if (text.startswith(prefix) and known_verb(rest)
                            and not known_verb(text)):
                        negated, text = True, rest
                        break
            items.append((text, not negated))

    out = {}
    for word, value in items:
        verb = to_verb(str(word))
        if verb:
            out[verb] = bool(value)
    return out


def afforded(mapping):
    """The verbs a thing affords: the map read as the set it used to be."""
    try:
        return {verb for verb, value in dict(mapping or {}).items() if value}
    except (AttributeError, TypeError, ValueError):
        # A list, from a world written before this module existed.
        return set(normalise(mapping))


def refused(mapping):
    """The verbs a thing is explicitly said NOT to afford."""
    try:
        return {verb for verb, value in dict(mapping or {}).items() if not value}
    except (AttributeError, TypeError, ValueError):
        return set()


def merge(*mappings):
    """
    Several kinds' affordances, as one map.

    A thing may be more than one kind -- a sword with runes on it is a sword
    and an inscription -- and what it affords is what any of its kinds afford.
    So yes wins: being an inscription makes a sword readable, and nothing
    about being a sword makes it unreadable.

    Which is the whole of the conflict rule, and the reason a kind may only
    ever add. There is no way here to say that a thing lacks what its kind
    has, deliberately: see docs/kinds-and-affordances.md. When a thing cannot
    do what its kind does it is either in a state that stops it, or it is not
    really that kind.
    """
    out = {}
    for mapping in mappings:
        for verb, value in dict(mapping or {}).items():
            out[verb] = bool(out.get(verb)) or bool(value)
    return out


#: How to ask for these, for any prompt that has to.
PROMPT = """\
affordances say what can be DONE to this thing, as a JSON object mapping a
plain verb to true or false: {"read": true, "burn": true, "open": false}.

Write the verb itself, not an adjective made out of it -- "read", never
"readable"; "burn", never "flammable". Write it in the infinitive, as a player
would type it.

Every verb describes what happens TO the thing, never what the thing does. A
lantern affords "light" because it can be lit, not because it gives light.

Say false only where a thing is a plain exception to what its sort can usually
do. Leaving a verb out means nobody has decided, which is the ordinary case;
there is no need to list everything a thing cannot do.

Do not use these for where things go -- whether things fit in it or on it is
recorded elsewhere and is not a verb.
"""
