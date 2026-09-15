"""
Whose it is.

Three relations a world needs, and until now only two of them existed:

    containment   Evennia's `location`        where is it
    placement     `world.relations`           how is it there -- in, on, under
    ownership     here                        whose is it

Orthogonal to both, and that is the whole reason for a third: a sword you own
can be in a chest you do not, in a room neither of you is in. Neither of the
other two can say that, and every attempt to make them say it -- reading the
container's owner, or calling a thing "in Jessica's keeping" -- gets one of
the two cases wrong.

**An owner is a character.** `quests.is_person` is the test, so a robot or a
ship's computer owns things like anybody else, and a chest does not.
Everything that seems to want an object as owner is one of three other
things: an institution (not an object -- a guild is not a thing standing in a
room), a fit rather than a claim ("the key belongs to the chest", which is
containment read the way a player means it), or a place, which is what
`world.zones` is for. The stronger argument is that ownership only means
anything through the things that read it -- the `owned_by` condition, whose
refusals are addressed to somebody; possessive matching, where "my" and "her"
resolve to people; an NPC wanting back what is theirs -- and an object owner
resolves to nothing useful in any of them. See docs/pronouns-and-ownership.md
6.2.

**The name is stored beside the id deliberately.** An Evennia attribute
holding an object reference reads back as `None` once that object is deleted,
and the rules here have to tell "owned by nobody" from "owned by somebody who
is no longer alive to hold it" -- the second is what makes a dead man's sword
claimable, and the first is what stops a rock on the floor being somebody's
rock. With only a reference the two are the same value.

**Transfer cascades; asking does not.** Handing somebody a box of things hands
them the things, so `set_owner` walks into the contents once, when ownership
changes, and writes an owner onto each thing it reaches. Afterwards
everything carries its own answer and nothing is inferred from where it
happens to be sitting -- which is why `owned_by` does not walk up the
container chain: if I own a chest and you put your sword in it, the sword is
still yours. The two do not conflict because they happen at different
moments. See 6.3.
"""

import time

#: Where the record lives. One attribute holding a whole record rather than a
#: reference, for the reason in the docstring.
ATTR = "owner"

#: The verbs this module owns. `give` is a mechanic in the sense `wear` and
#: `put` are -- it means one thing, the game knows what it is, and no world
#: should be paying a model to invent a private meaning for it. See 6.6.
VERBS = ("give",)


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------

def record(obj):
    """The ownership record written on something, or {} for nobody's."""
    if obj is None:
        return {}
    try:
        found = getattr(obj.db, ATTR, None)
    except AttributeError:
        return {}
    try:
        return dict(found or {})
    except (TypeError, ValueError):
        return {}


def owner_name(obj):
    """
    What the owner was called, whether or not they are still here.

    The half of the record that survives its subject, and the half a refusal
    is written from: "the sword is not yours" has to name somebody even when
    the somebody is dead.
    """
    return str(record(obj).get("name") or "")


def owner_of(obj):
    """The character who owns this, or None if nobody does or they are gone."""
    from evennia.objects.models import ObjectDB

    owner_id = record(obj).get("id")
    if not owner_id:
        return None
    try:
        return ObjectDB.objects.filter(id=int(owner_id)).first()
    except (TypeError, ValueError):
        return None


def unowned(obj):
    """True when nobody has ever claimed it."""
    return not record(obj)


def orphaned(obj):
    """True when it was somebody's and that somebody has left the world."""
    return bool(record(obj)) and owner_of(obj) is None


def claimable(obj):
    """
    True when it is nobody's -- never claimed, or claimed by somebody gone.

    What `{"owned_by": "nobody"}` tests, and the guard on the standard rule
    that makes picking a thing up yours. The two cases are deliberately one
    answer here: to whoever is reaching for it they are the same situation,
    and the difference is worth keeping only so that the *record* can still
    tell them apart afterwards.
    """
    return unowned(obj) or orphaned(obj)


def may_own(who):
    """Whether this is the sort of thing that can own anything: a character."""
    if who is None:
        return False
    from world.quests import is_person

    try:
        return bool(is_person(who))
    except Exception:
        return False


def owns(who, obj):
    """Whether `who` is the owner of `obj` -- the plain, non-cascading test."""
    if who is None or obj is None:
        return False
    try:
        return int(record(obj).get("id") or 0) == int(who.id)
    except (TypeError, ValueError, AttributeError):
        return False


def owns_through_containers(who, obj, depth=None):
    """
    Whether `who` owns this, or anything it is inside.

    The standing inference the plain test refuses to make, kept available for
    a world that really means it -- a landlord, a ship's captain, a guild hall
    where everything on the premises is the guild's. Written as the second
    form of the condition, `{"owned_by": {"role": ..., "through":
    "containers"}}`, so that no rule meaning the ordinary thing has to say so.
    """
    from world import relations

    if depth is None:
        depth = relations.MAX_DEPTH
    where, steps = obj, 0
    while where is not None and steps <= depth:
        if owns(who, where):
            return True
        where = getattr(where, "location", None)
        steps += 1
    return False


# ---------------------------------------------------------------------------
# Changing it
# ---------------------------------------------------------------------------

def set_owner(obj, owner, cascade=True):
    """
    Make `obj` somebody's, or nobody's when `owner` is None. Answers the record.

    The cascade claims only what the previous owner owned: giving you a chest
    containing Britney's sword does not give you her sword, and giving you a
    chest of unowned pebbles leaves them unowned until somebody takes one --
    at which point the standard `get` rule claims it with no special case
    here. Anything owned by somebody else, or by nobody, is left as it was.
    """
    if obj is None:
        return {}
    if owner is not None and not may_own(owner):
        return record(obj)

    previous = record(obj)
    written = _write(obj, owner)
    if cascade and previous:
        # `previous` and not merely "matches": a thing nobody owned is untouched
        # even when what it was inside was also nobody's. Giving you a chest of
        # unowned pebbles leaves them unowned until somebody takes one, at which
        # point the standard `get` rule claims that one -- and a cascade that
        # read two empty records as a match would hand you the whole chest's
        # worth on a technicality.
        for inside in _within(obj):
            if _same_owner(previous, record(inside)):
                _write(inside, owner)
    _remembered(obj, previous, written)
    return written


def claim(who, obj, cascade=True):
    """
    Make it theirs if it is nobody's. True when the claim was made.

    The one-way form, and the one most callers want: picking a thing up, being
    created holding it, being dressed in it. Something that is already
    somebody else's is left alone -- taking a person's sword is not a way of
    acquiring it, and a world that means it to be says so with a rule.
    """
    if obj is None or not may_own(who) or not claimable(obj):
        return False
    set_owner(obj, who, cascade=cascade)
    return True


def disown(obj, cascade=True):
    """Make it nobody's again."""
    set_owner(obj, None, cascade=cascade)


def forget(obj):
    """
    Close the record because the thing itself is gone.

    Destruction is written rather than erased. The attribute goes with the
    object, but what was recorded of it outlives both: the fact is closed at
    this moment and stays answerable as of any moment before it, which is what
    lets somebody ask after -- or mourn -- a sword that no longer exists. See
    docs/pronouns-and-ownership.md 7.6.
    """
    if obj is None or unowned(obj):
        return
    from world import memory

    where = _where(owner_of(obj), obj)
    if where is not None:
        memory.end_triples(where, _handle(obj), "owned_by")


def _write(obj, owner):
    """Put the record on one object, with no cascade and no provenance."""
    if owner is None:
        try:
            obj.attributes.remove(ATTR)
        except AttributeError:
            pass
        return {}
    written = {"id": int(owner.id), "name": str(owner.key),
               "since": time.time()}
    setattr(obj.db, ATTR, written)
    return written


def _same_owner(one, other):
    """Whether two records name the same owner -- including nobody at all."""
    return str(dict(one or {}).get("id") or "") == \
        str(dict(other or {}).get("id") or "")


def _within(obj, depth=None):
    """
    Everything inside something, to `relations.MAX_DEPTH`.

    The same depth reach uses, and for the same reason: past about here
    nobody -- player or rule -- has much idea what is where.
    """
    from world import relations

    if depth is None:
        depth = relations.MAX_DEPTH
    found, edge = [], [obj]
    for _step in range(depth):
        deeper = []
        for thing in edge:
            for inside in (getattr(thing, "contents", []) or []):
                if getattr(inside, "destination", None) is not None:
                    continue        # an exit is part of the map
                found.append(inside)
                deeper.append(inside)
        if not deeper:
            break
        edge = deeper
    return found


# ---------------------------------------------------------------------------
# Matching a possessive
#
# "Get her sword" names a sword by saying whose it is, and until now the whose
# was thrown away: `verbs.plain` dropped "my" as noise and "her" reached the
# search as part of a name, so "her sword" looked for an object called "her
# sword", found none, and offered to invent one. Everything needed to do
# better arrived in the phases before this one -- `nounphrase` returns the
# possessor, `referents` can say who "her" was, and the record above can say
# whose a thing is -- so this is the one filter that puts them together.
#
# Two passes, and the order matters. **Owned first**, because it is the
# stronger claim: a sword she owns is hers whoever happens to be holding it.
# **Then merely carried**, because "her sword" said of a sword she is holding
# and has never been given is still the sword she means. Nothing else is
# considered: a stated possessive is a claim about the world, and widening the
# search when the claim fails would answer a question nobody asked.
#
# **Nothing is ever conjured for a possessive.** That line is drawn in
# `anatomy` already and is most of the reason this is worth doing: inventing a
# ball to satisfy "her ball" is the worst available answer, because it is
# indistinguishable from the ball she actually has until somebody looks.
#
# See docs/pronouns-and-ownership.md 6.7.
# ---------------------------------------------------------------------------

def person_meant(caller, owner, word=""):
    """
    (person, question) for the owner half of a possessive phrase.

    Shaped like `verbs.resolve_pronoun` and for the same reason: with several
    people answering to "her" there is no defensible way to pick one, and
    acting on a stranger is worse than asking. `owner` is a name to go looking
    for, or one of `nounphrase`'s marker sets standing in for a pronoun.

    First and second person are whoever is holding the conversation. Third
    person goes to the people here whose pronoun set claims things with that
    word -- and, failing that, to the rule that was all there was before sets
    existed: if exactly one other person is present, they are who was meant.
    That fallback is what keeps a world whose characters were never asked
    their pronouns working exactly as it did.
    """
    from world import anatomy, nounphrase

    if owner is nounphrase.SPEAKER:
        return caller, None
    if owner is not nounphrase.THIRD_PERSON:
        from world.naming import CONFIDENT, best_match

        person, score = best_match(caller, owner,
                                   candidates=anatomy.people_near(caller))
        return (person, None) if score >= CONFIDENT else (None, None)

    from world import choosing, referents

    here = [p for p in anatomy.people_near(caller) if p is not caller]
    answering = _claiming_with(caller, here, word)
    if len(answering) == 1:
        return answering[0], None
    if answering:
        # Several, so the question is which of them was last meant.
        remembered = referents.recall_by_set(caller, word, "adjective",
                                             _world_of(caller))
        if remembered is not None and remembered in answering:
            return remembered, None
        names = [p.get_display_name(caller) for p in answering]
        return None, choosing.question(word, names)

    # Nobody here goes by that word. Before pronoun sets were recorded this
    # was every case, and the answer was the only other person in the room;
    # it is kept as what to do when a world has not said.
    return (here[0], None) if len(here) == 1 else (None, None)


def _claiming_with(caller, people, word):
    """Whoever here would say `word` to claim something of theirs."""
    from world import pronouns

    said = str(word or "").lower().strip()
    if not said:
        return []
    world_root = _world_of(caller)
    found = []
    for person in people:
        entry = pronouns.of(person, world_root)
        if said in (entry.get("adjective", ""), entry.get("possessive", "")):
            found.append(person)
    return found


def whose(caller, read):
    """
    (object, question) for a noun phrase that said whose it is.

    `None` for both means nothing here answers to it, which is a refusal and
    never an invitation to make one -- see `anatomy.instead_of_a_part`, where
    the refusal is worded, because that is the point every path passes through
    just before something would be conjured.

    Takes no `fuzzy`, unlike everything else `bind` calls. The looser bar is
    for characters naming things from memory in their own words, and the bar
    here is already that one: see `_named`.
    """
    from world import anatomy

    person, asked = person_meant(caller, read.possessor, read.possessor_words)
    if person is None:
        named = _spelled_out(caller, read)
        return (named, None) if named is not None else (None, asked)
    if anatomy.is_listed_part(read.thing):
        # "her arm" is not a thing of hers, it is her, and anatomy answers it.
        # Kept out of the search rather than allowed to fall through it: a
        # hand mirror in her bag resembles "hand" quite enough to be picked up
        # instead of her being touched.
        #
        # The narrow test, not `is_part`: this decides between two readings
        # and has to be sure, while the one asked at conjuring time only has
        # to be sure enough not to make a shoulder. A word that is a part
        # anywhere but on the list comes through here, finds nothing of hers,
        # and reaches anatomy anyway a moment later.
        return None, None
    found = theirs(caller, person, read)
    return (found if found is not None else _spelled_out(caller, read)), None


def _spelled_out(caller, read):
    """
    The thing a possessive-shaped *name* names, when that is what it is.

    Worlds call things "Captain's Log", "Baker's Rack" and "Widow's Lamp", and
    every one of those reads as a claim about somebody: an apostrophe is an
    apostrophe whether it is grammar or spelling. Read as a claim it finds
    nothing and is refused, which would have made a shelf of perfectly
    ordinary objects unnameable.

    So a written-out possessor gets one more question, and only a written-out
    one: is there something here actually called that? Confident matches only,
    and never for a pronoun -- "my ball" scores 0.9 against a Leather Ball on
    somebody else's shelf, which is precisely the answer this phase exists to
    stop, while "captain's log" scores 1.0 against a Captain's Log and can
    mean nothing else.
    """
    from world import nounphrase
    from world.naming import CONFIDENT, best_match

    if read.possessor in (None, nounphrase.SPEAKER, nounphrase.THIRD_PERSON):
        return None
    obj, score = best_match(caller, read.raw)
    return obj if score >= CONFIDENT else None


def theirs(caller, person, read):
    """The thing of theirs that the rest of the phrase names, or None."""
    from world import relations

    thing = read.thing
    if not thing or person is None:
        return None

    carried = [obj for obj in (getattr(person, "contents", []) or [])
               if getattr(obj, "destination", None) is None]
    owned = [obj for obj in relations.reachable(caller) if owns(person, obj)]
    for obj in carried:
        if owns(person, obj) and obj not in owned:
            owned.append(obj)

    for candidates in (owned, carried):
        found = _named(caller, thing, candidates, read.ordinal)
        if found is not None:
            return found
    return None


def _named(caller, phrase, candidates, ordinal=0):
    """
    Whichever of these a phrase names, or None. Counting honoured.

    A lower bar than an open search uses, because the possessive has already
    done the narrowing a bare name has to do by spelling: among the four
    things she is carrying, "sword" is unambiguous in a way it would not be
    across a room.
    """
    from world.naming import PLAUSIBLE, resemblance

    scored = []
    for obj in candidates:
        names = [obj.key] + [str(alias) for alias in obj.aliases.all()]
        score = max(resemblance(phrase, name) for name in names)
        if score >= PLAUSIBLE:
            scored.append((score, obj))
    if not scored:
        return None
    if ordinal:
        counted = sorted((obj for _score, obj in scored), key=lambda o: o.id)
        if ordinal == -1:
            return counted[-1]
        return counted[ordinal - 1] if ordinal <= len(counted) else None
    return max(scored, key=lambda pair: (pair[0], -pair[1].id))[1]


def no_such(caller, person, thing, spoken=False):
    """
    "You see no sword of hers here."

    The owner is named, because "you see no sword here" is a lie when there
    are three of them on the floor and none of them is hers. Said with the
    pronoun when the player used one and with the name when they did not, so
    the refusal reads back in the words the claim was made in.
    """
    said = str(thing or "").strip() or "such thing"
    if person is caller:
        whose_it = "yours"
    elif spoken:
        from world import pronouns

        whose_it = (pronouns.of(person, _world_of(caller)).get("possessive")
                    or f"{person.key}'s")
    else:
        whose_it = f"{person.key}'s"
    return f"You see no {said} of {whose_it} here."


def _world_of(caller):
    room = getattr(caller, "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


# ---------------------------------------------------------------------------
# Taking what is somebody's
#
# Ownership with no consequence is bookkeeping, and this is the least of the
# consequences: somebody watching a thing of theirs being picked up has seen
# something the room has not. The room's sentence stays as it was -- whose a
# thing is is not something anybody can see -- and the witnesses are told.
#
# Whether taking it is *allowed* is not decided here. That is the standard
# rule "you may not take what is not yours", suspended until a world restores
# it, and a world that leaves it suspended gets exactly this: the taking
# happens, and the owner knows.
#
# See docs/pronouns-and-ownership.md, phase P7.
# ---------------------------------------------------------------------------

def taken_from(taker, obj):
    """
    Who a thing was taken from, when it was not the taker's to take. Else None.

    Nobody's things and the taker's own are not taken from anybody, and nor is
    a thing whose owner has left the world: a dead man's sword is claimable,
    which is the whole of what `claimable` is for.
    """
    if taker is None or obj is None or claimable(obj) or owns(taker, obj):
        return None
    return owner_of(obj)


def witnessed_taking(sentence, taker, obj):
    """
    `sentence`, saying whose the thing was when it was somebody else's.

    "Raldor picks up the crowbar." becomes "Raldor picks up the crowbar, which
    belongs to Olara Voss." Names and not pronouns, because what reads this is
    a model with no attention to resolve a pronoun with -- and because being
    named is what makes an NPC answer, which is what an owner should do.

    The owner, when they are standing there watching and are a character the
    game plays, also now wants it back. Said here rather than by each caller
    because every door a taking comes through already has to call this, and a
    theft that set a goal by one door and not another would be a bug nobody
    could see.
    """
    said = str(sentence or "")
    owner = taken_from(taker, obj)
    if owner is None:
        return said
    if getattr(owner, "location", None) is getattr(taker, "location", None):
        want_back(owner, obj)
    body = said.rstrip()
    stop = body[-1] if body[-1:] in (".", "!") else ""
    if stop:
        body = body[:-1]
    return f"{body}, which belongs to {owner.key}{stop}"


def want_back(owner, obj):
    """
    Give a character the goal of getting a thing of theirs back. True if set.

    The template is `goals.recover`: having it in hand again, which the planner
    already knows how to pursue and which is met the moment it comes back,
    whoever brings it. An errand somebody else set them is left alone -- a
    character who has agreed to do something for a player does not drop it
    without a word -- and players are never given goals at all.
    """
    if owner is None or obj is None or not getattr(owner.db, "is_npc", False):
        return False
    if owner.db.goal_from_quest is not None:
        return False
    from world import goals

    wanted = goals.recover(obj)
    if [dict(c) for c in (owner.db.goal or [])] == wanted:
        return False
    owner.db.goal = wanted
    owner.db.goal_stalls = 0
    return True


# ---------------------------------------------------------------------------
# Giving
# ---------------------------------------------------------------------------

def give(character, obj, recipient):
    """
    Hand something over. Returns (ok, what the giver is told, what happened).

    The mechanic itself, so that a player typing it and a character deciding
    to hand something over reach the same code, the same refusals and the same
    sentence. It moves the thing and nothing else: the ownership goes with it
    through the standard `after` rule on `give`, which is where a world can
    read it, argue with it, or replace it.
    """
    from world import events, gear, relations

    name = obj.get_numbered_name(1, character, return_string=True)
    if obj.location is not character:
        return False, f"You are not carrying {name}.", None
    if obj.db.worn:
        return False, f"You would have to take {name} off first.", None
    if recipient is character:
        return False, "You already have that.", None
    if not may_own(recipient):
        return (False, f"{recipient.get_display_name(character)} is not "
                       f"somebody you can give things to.", None)
    # And whatever this world's check rules say about giving, which nothing
    # else on this path would ever ask. See `attempt.permitted`.
    from world import attempt

    refused = attempt.permitted(character, "give",
                                {"direct": obj, "target": recipient})
    if refused:
        return False, refused, None

    # The hooks Evennia's own giving fires, because a thing that refuses to be
    # given away has to go on refusing when the giving arrives by this door
    # instead -- the same reason the taking command calls `at_get`.
    if not obj.at_pre_give(character, recipient):
        return False, f"You cannot give {name} away.", None
    if not obj.move_to(recipient, quiet=True, move_type="give"):
        return False, f"You cannot give {name} away.", None
    obj.at_give(character, recipient)

    # It is in somebody's hands now, and no longer on or in whatever it was.
    relations.displace(obj)
    gear.release(obj, character)
    return (True,
            f"You give {name} to {recipient.get_display_name(character)}.",
            events.Event(actor=character, verb="give",
                         roles={"direct": obj, "target": recipient},
                         room_template=("{actor} $pconj(give) {direct} "
                                        "to {target}.")))


def handle(caller, verb, parsed, bound, on_message):
    """
    Deal with a giving, or decline it. True when it was handled.

    Declining is as much of the job as handling, exactly as it is for the
    clothing and placement mechanics: "give up", "give a speech" and "give the
    door a shove" are ordinary verbs a world is entitled to work out for
    itself, and only an attempt that really is one person handing another
    person a thing is taken over here.
    """
    if verb not in VERBS:
        return False

    obj = bound.get("direct")
    recipient = bound.get("target") or bound.get("container")
    if obj is None or recipient is None:
        # "give jessica the crowbar" -- two nouns with no preposition between
        # them, which the parser reads as one long name and binds to nothing.
        # Split here rather than in the parser: it is the shape of this one
        # verb, and a grammar that knew it would have to know it for every
        # ditransitive verb a world ever invents.
        obj, recipient = _ditransitive(caller, parsed)
    if obj is None or recipient is None or not may_own(recipient):
        return False

    ok, actor_text, event = give(caller, obj, recipient)
    on_message(actor_text, event)
    if ok:
        from world import attempt

        attempt.consequences(caller, "give",
                             {"direct": obj, "target": recipient})
    return True


def _ditransitive(caller, parsed):
    """
    "give jessica the crowbar", read as the two things it names.

    Answers (thing, recipient), either of which may be None. The recipient is
    looked for at the front because that is where English puts it, and only
    people are considered -- so "give iron crowbar" is not read as giving
    something to somebody called Iron.
    """
    from commands.follow_cmds import _find_person
    from world import verbs

    phrase = str((parsed.get("roles") or {}).get("direct") or "").strip()
    words = phrase.split()
    for cut in range(1, len(words)):
        recipient = _find_person(caller, " ".join(words[:cut]))
        if recipient is None or recipient is caller:
            continue
        obj = verbs.bind(caller, " ".join(words[cut:]), verb="give")
        if obj is not None:
            return obj, recipient
    return None, None


# ---------------------------------------------------------------------------
# What was recorded of it
#
# Two writes, because they answer two different questions and live in two
# different tables. The fact is the readable half -- "the iron crowbar is
# owned by Olara Voss" -- written at the engine's veracity tier so that
# something the game knows outranks something a model inferred, and it is what
# recall finds when somebody asks about the crowbar. The triple is the exact
# half: dbrefs rather than names, so that two swords both called "sword" are
# two subjects; `supersede=True`, so a transfer closes the previous owner by
# itself; and temporal, so `as_of` still answers who it belonged to last week.
#
# See docs/pronouns-and-ownership.md 7.5.
# ---------------------------------------------------------------------------

def _handle(obj):
    """What a thing is called in the triple store: exact, and not its name."""
    return f"#{obj.id}"


def _where(owner, obj):
    """
    The bank and session this belongs in, or None when there is no world.

    The bank is the world, and is what matters most here -- triples carry no
    session at all, and ownership is world history rather than one character's
    belief. The session is the owner's, so that the readable fact reads back
    to the person it is about.
    """
    from world import memory

    for who in (owner, obj):
        if who is None:
            continue
        where = memory.where_for(who)
        if where.bank:
            return where
    return None


def _remembered(obj, previous, written):
    """Record that this changed hands. Never blocks, and never raises."""
    if _same_owner(previous, written):
        return
    from world import memory

    where = _where(owner_of(obj), obj)
    if where is None:
        return
    if not written:
        memory.end_triples(where, _handle(obj), "owned_by")
        return
    memory.note_triple(where, _handle(obj), "owned_by", f"#{written['id']}")
    memory.note_fact(where, obj.key, "owned_by", str(written["name"]),
                     veracity=memory.FROM_ENGINE)
