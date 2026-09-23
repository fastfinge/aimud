"""
How many of what sort, and which ones.

A rule could say "you must be carrying the brass key" and could not say "two
lumps of coal". `conditions._held` matched a clause's word against a substring
of an object's key, so "iron" was answered by an iron *key*, and nothing
anywhere counted at all.

That gap is not crafting's. It is the same missing sentence in six places: a
recipe wants two of something, a wardrobe wants no more than one hat, a quest
wants three apples, the planner wants to know how far off three is, trade is
quantity from end to end, and `world.gear`'s own comment observes that nothing
stops somebody carrying six lucky charms. Six systems working around one hole
is the case `docs/basic-principles.md` says to pull out and make generic.

So this module answers one question -- *which of these things answer to this
description, and are there enough of them* -- and everything that used to guess
at half of it asks here instead.

**A description is a spec, and a spec is data.** `{"of_kind": "coal.n.01",
"count": 2}` is what a rule stores. A bare word still means exactly what it
always meant, so every condition already written goes on saying what it said.

**Sort beats spelling.** `of_kind` matches through `kinds.is_a`, so a rule
about wood is answered by an oak plank and a rule about iron is not answered by
an iron key. `of_name` keeps the substring match, for a rule that really does
mean one particular thing by the name it goes by.

**One is a count like any other.** `holds` means "at least this many" and
`not_holds` means "fewer than this many", both defaulting to one -- so the
uncounted pair keeps its old meaning exactly ("carrying it" and "carrying none
of them") and the counted pair needs no separate rule for how they mirror. That
is what makes a count negatable at all; see `conditions.OPPOSITES`.

**Counting has a ceiling**, for the reason `conditions.MAX_DEPTH` has one: a
rule asking for a hundred of something has stopped being a fact about the world
and started being a program.

Nothing here searches the world. The caller says which things to look at --
what somebody carries, what they have on -- because where to look is a fact
about the predicate asking, and a module that decided it for everybody would be
back to guessing at half the question.
"""

import re

from world import english

#: The most of anything one clause may ask for.
#:
#: `bulk.LIMIT`, deliberately, and for its reason rather than by coincidence:
#: past about here a player has stopped meaning a number and started meaning
#: "too many". A clause over the ceiling is refused rather than trimmed, the
#: way `conditions.normalise` refuses a condition too deep to store -- a
#: requirement cut down to fit asks for something other than what was written.
MAX_COUNT = 12

#: The fields a spec is stored with. `role` and the two `of_` fields are three
#: ways of saying which things count, and exactly one of them is ever set.
#:
#: of_kind -- a synset. Matched through the taxonomy, so a sort covers its
#:            sorts: `wood.n.01` is answered by an oak plank.
#: of_name -- a word, matched against what a thing is called. The old
#:            behaviour, kept for a rule that means one particular thing.
#: role    -- another role in the same attempt: "to throw it you must be
#:            holding it" is about whatever is being thrown, which has no name
#:            until somebody throws something.
#: count   -- how many. One unless said.
#: as      -- what to file the things found under, so an effect can name them.
#:            Empty for a clause nothing needs to act on. See `world.effects`.
FIELDS = ("of_kind", "of_name", "role", "count", "as")

#: How else a model may write the three that pick things out. Accepted because
#: `conditions.resolve` already takes `named` and `of_kind` for a *subject*, and
#: a language where the same idea is spelled two ways depending on which half of
#: a clause it is in is a language nobody can write correctly.
_ALIASES = {"named": "of_name", "name": "of_name", "kind": "of_kind",
            "sort": "of_kind", "of_role": "role", "as_role": "as"}

#: Dropped from the front of a name before it is matched, so that a clause
#: written "a brass key" looks for the same thing as one written "brass key".
_ARTICLE = re.compile(r"^(?:an?|the|some)\s+", re.IGNORECASE)


def blank():
    """A spec with every field present, so nothing downstream has to guess."""
    return {"of_kind": "", "of_name": "", "role": "", "count": 1, "as": ""}


def read(item, roles=()):
    """
    One clause item as a spec, or None when it says nothing.

    `roles` is which words are roles in the attempt asking, so that a bare
    "direct" is read as the role rather than as a thing called direct. Left
    empty by a caller with no attempt in front of it -- a `rules` listing, a
    quest -- and then a bare word is always a name, which is the safe reading:
    a name that matches nothing refuses, and a role that matches nothing would
    silently pass.
    """
    spec = blank()
    if item is None:
        return None

    if isinstance(item, (str, bytes)):
        word = str(item).strip()
        if not word:
            return None
        if word in roles:
            spec["role"] = word
        else:
            spec["of_name"] = _ARTICLE.sub("", word).strip()
        return spec if (spec["role"] or spec["of_name"]) else None

    # A mapping, which an Evennia attribute hands back as a _SaverDict -- a
    # mapping but not a dict, so it is tested for the way `conditions.node_of`
    # tests: by what it can do, never by what it is.
    if not hasattr(item, "keys"):
        return None
    given = {}
    for key in item.keys():
        field = _ALIASES.get(str(key), str(key))
        if field in FIELDS:
            given[field] = item[key]

    for field in ("of_kind", "of_name", "role"):
        value = str(given.get(field) or "").strip()
        if field == "of_name":
            value = _ARTICLE.sub("", value).strip()
        spec[field] = value
    spec["as"] = str(given.get("as") or "").strip()

    # A word written where a role was meant, and the other way about. Reading
    # it here rather than at every call site is what lets `{"of_name":
    # "direct"}` mean what somebody plainly meant by it.
    if spec["of_name"] and spec["of_name"] in roles and not spec["role"]:
        spec["role"], spec["of_name"] = spec["of_name"], ""

    count = given.get("count", 1)
    try:
        spec["count"] = int(count)
    except (TypeError, ValueError):
        return None
    if spec["count"] < 1 or spec["count"] > MAX_COUNT:
        return None
    if not (spec["of_kind"] or spec["of_name"] or spec["role"]):
        return None
    return spec


def read_all(value, roles=()):
    """
    Every spec a clause's value names, and whether all of it could be read.

    Returns (specs, ok). `ok` is false when any item was unreadable, which the
    caller must not paper over: a requirement with a piece missing asks for
    less than was written, and a check that asks for less is a check that lets
    something through.
    """
    from world.model_json import listed

    items = listed(value)
    specs, ok = [], True
    for item in items:
        spec = read(item, roles)
        if spec is None:
            ok = False
            continue
        specs.append(spec)
    return specs, ok


def counted(value):
    """
    Whether a clause's value says anything a bare word could not.

    What tells an old condition from a new one, for the callers that still have
    a fast path for the old shape.
    """
    specs, _ok = read_all(value)
    return any(spec["count"] != 1 or spec["of_kind"] for spec in specs)


# ---------------------------------------------------------------------------
# Which things answer to it
# ---------------------------------------------------------------------------

def matching(objects, spec, ctx=None, limit=None):
    """
    The things among these that answer to this spec, in the order given.

    Stops at `limit`, or at what the spec asks for, because nothing wants the
    seventh match once six were enough -- and a rule that files what it found
    should file the number it asked for rather than everything in the pack.
    Pass `limit=0` for all of them, which is what a listing wants.
    """
    wanted = spec.get("count", 1) if limit is None else limit
    found = []
    if spec.get("role"):
        bound = (ctx.bound if ctx is not None else {}) or {}
        one = bound.get(spec["role"])
        # Identity, not a name match: the role is already a thing, and asking
        # whether it is in the pool is the whole of the question.
        return [one] if one is not None and one in (objects or []) else []

    kind = spec.get("of_kind") or ""
    name = (spec.get("of_name") or "").lower()
    world_root = getattr(ctx, "world_root", None) if ctx is not None else None
    for obj in (objects or []):
        if obj is None:
            continue
        if kind and not _is_kind(obj, kind, world_root):
            continue
        if name and name not in str(getattr(obj, "key", "")).lower():
            continue
        found.append(obj)
        if wanted and len(found) >= wanted:
            break
    return found


def _is_kind(obj, kind, world_root):
    """Whether this thing is that sort of thing, through the taxonomy."""
    from world import kinds as kinds_mod

    return kinds_mod.any_is_a(world_root, kinds_mod.of(obj), kind)


def enough(found, spec):
    """Whether this many is as many as the spec asked for."""
    return len(found) >= int(spec.get("count", 1) or 1)


# ---------------------------------------------------------------------------
# What it is called
# ---------------------------------------------------------------------------

def said(spec, ctx=None, definite=None):
    """
    How to name what a spec asks for, in a sentence.

    "the brass key", "two lumps of coal", "three apples". Definite for a named
    thing, because a rule naming a thing means that thing; indefinite for a
    sort or a number, because a rule asking for two apples does not mean two
    apples in particular. A caller may say which it wants when the grammar
    around it has already decided.
    """
    count = int(spec.get("count", 1) or 1)

    if spec.get("role"):
        from world import conditions

        subject = conditions.Subject(conditions.THING,
                                     (ctx.bound if ctx else {}).get(spec["role"]),
                                     ctx=ctx)
        return subject.name()

    noun = spec.get("of_name") or _kind_word(spec.get("of_kind") or "")
    if not noun:
        return "it"
    if definite is None:
        definite = bool(spec.get("of_name")) and count == 1
    if count == 1 and definite:
        return f"the {noun}"
    return english.count(count, noun)


def _kind_word(kind):
    """The ordinary English for a synset: `coal.n.01` is "coal"."""
    if not kind:
        return ""
    from world import lexicon

    return lexicon.word_of(kind) or str(kind).split(".", 1)[0].replace("_", " ")


def shortfall(found, spec, ctx=None):
    """
    What is still wanted, as a phrase, or "" when nothing is.

    "one more apple" rather than "three apples", because somebody holding two
    of three is told what to do next and not what the rule says. The planner
    reads the same arithmetic backwards; see `world.planner`.
    """
    want = int(spec.get("count", 1) or 1)
    short = want - len(found or [])
    if short <= 0:
        return ""
    if want == 1 or spec.get("role"):
        return said(spec, ctx)
    noun = spec.get("of_name") or _kind_word(spec.get("of_kind") or "")
    if short == want:
        return said(spec, ctx)          # none yet: ask for the whole of it
    # "one more apple", not "an apple more": the number goes in front and
    # `more` sits between it and the noun, so the noun agrees with the number
    # rather than taking an article it should not have.
    if english.is_mass(None, noun):
        return f"more {noun}"
    plural = short != 1
    return (f"{english.number(short)} more "
            f"{english.plural(noun) if plural else noun}")


def lookup_tools():
    """Nothing to look up. Here so the toolbox's sweep finds a stable shape."""
    return []
