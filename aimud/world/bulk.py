"""
Doing one thing to everything at once.

"Drop all" has existed for as long as inventories have got out of hand, and it
existed as a command of its own -- a hundred lines that knew about undressing,
about the order things come off in, and about one verb. Nothing else could be
done in bulk, so "eat all" reached for an object called "all", found none, and
offered to conjure one.

The temptation is to make "all" a role a rule can bind, so that a verb's rule
runs once against a dozen things. That breaks in three places at once. Effects
name one object per role. A check is one roll or twelve and there is no
principled answer. And a narration is cached on the thing it describes, so a
sentence about twelve things has nowhere to live -- cache it on one and it is
wrong for the other eleven, cache it on each and one action has written twelve
descriptions.

So bulk is an expansion rather than a role. "Eat all" becomes as many ordinary
attempts as there are things to eat, each with one object, one check and one
narration cached where it belongs. The second time, in a room of familiar
things, it costs nothing at all. Nothing downstream of here knows that bulk
exists.

**What "all" ranges over is the verb's business, not this module's.** Dropping
all means everything carried; taking all means everything in the room; eating
all cannot sensibly mean the floorboards. There is no general answer, so the
caller says where to look, and `matching` narrows that to what the verb can
actually be done to -- which the kinds now know, and which is the closest
thing to a general answer there is.
"""

#: What somebody types when they mean the lot.
WORDS = frozenset(["all", "everything", "every", "each", "the lot"])

#: And when they mean the people rather than the things.
PEOPLE_WORDS = frozenset(["everyone", "everybody", "all of them"])

#: A ceiling, because "eat all" in a storeroom should not be a hundred model
#: calls before anybody can type again. Deliberately small: past about here a
#: player has stopped meaning "all" and started meaning "too much".
LIMIT = 12


def wanted(phrase):
    """Whether a noun phrase means everything rather than something."""
    text = str(phrase or "").lower().strip()
    return text in WORDS or text in PEOPLE_WORDS


def _people_meant(phrase):
    return str(phrase or "").lower().strip() in PEOPLE_WORDS


def matching(caller, verb, phrase, where=None):
    """
    The things "all" means here, for this verb.

    Narrowed three ways, in order of how sure each is. Whatever cannot be
    acted on at all is dropped -- exits are map, not furniture. Whatever the
    verb is refused on is dropped, because a kind that has already said a
    bottle cannot be read should not be asked again twelve times. And people
    are included only when the word was about people, so "eat all" in a busy
    room does not begin with the innkeeper.
    """
    from world import kinds, verbs
    from world.quests import is_person

    room = getattr(caller, "location", None)
    where = where if where is not None else room
    if where is None:
        return []

    world_root = getattr(getattr(room, "db", None), "world_root", None)
    people = _people_meant(phrase)

    found = []
    for obj in list(getattr(where, "contents", []) or []):
        if obj is caller or getattr(obj, "destination", None) is not None:
            continue
        if is_person(obj) != people:
            continue
        # A kind that has already settled the question keeps its answer. Only
        # a definite refusal is honoured: silence means nobody has decided,
        # and deciding it twelve times over is exactly what bulk must not do.
        if kinds.admits(world_root, obj.db.kinds, verb) is False:
            continue
        found.append(obj)
        if len(found) >= LIMIT:
            break
    return found


def expand(caller, verb, roles, where=None):
    """
    One command as a list of ordinary ones, or [] when it was not bulk.

    Only the direct object is expanded. "Put all in the box" is one bulk
    action with a fixed container; "put the key in all" is not a sentence
    anybody means, and expanding both sides would multiply.
    """
    phrase = (roles or {}).get("direct", "")
    if not wanted(phrase):
        return []

    targets = matching(caller, verb, phrase, where)
    if not targets:
        return []

    rest = " ".join(
        f"{preposition} {roles[role]}"
        for role, preposition in _tail(roles)
    )
    return [
        (obj, f"{verb} {obj.key}{(' ' + rest) if rest else ''}")
        for obj in targets
    ]


#: How a role reads back as words, so the rest of the sentence survives the
#: expansion: "put all in the chest" has to become "put the ladle in the
#: chest", not "put the ladle".
_PREPOSITION_FOR = {
    "container": "in", "target": "on", "source": "from", "instrument": "with",
}


def _tail(roles):
    """Every role but the direct object, with a word to reintroduce it."""
    return [
        (role, _PREPOSITION_FOR[role])
        for role in sorted(roles or {})
        if role != "direct" and role in _PREPOSITION_FOR
    ]
