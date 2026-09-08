"""
Whose hand it is.

This world makes real whatever it is asked for, which is its best trick and
the reason body parts end up on the floor. Ask to touch "Samuel's shoulder"
and every check passes honestly: a shoulder is plausible here, because Samuel
is standing in the room with one. So a shoulder gets built, given a
description and a takeable flag, and set down on the floorboards next to him.

The mistake is not plausibility, it is category. A shoulder is not a thing
that happens to be nearby; it is part of somebody who is. Naming it is naming
*them* -- which is why the fix is not a refusal but a resolution. "Touch
Samuel's shoulder" means touch Samuel, and answering it that way makes the
verb work instead of littering the room.

Three questions, in order, and none of them costs a model call:

* **Who does the phrase belong to?** "Samuel's", "her", "my" -- possession is
  syntax, and syntax is free. An owner who is not here is a phrase about
  nobody, and nothing gets made for it.

* **Is the tail one of their parts?** Judged on the head noun, so a "shoulder
  bag" is a bag and the "back of her hand" is a hand. The vocabulary is
  a list, which means it is incomplete by construction; `item_gen`'s
  existence check carries the same rule in words for whatever the list
  misses.

* **Is it something they are carrying?** Falls out of the same work for free.
  "Samuel's hat" should find the hat he is wearing rather than run one off.

Severed parts are deliberately left alone. A hand that has been cut off is an
object like any other and arrives the way objects do -- from a verb's
`create_object` effect, not from somebody naming it -- and once it exists the
ordinary search finds it long before this module is consulted. A phrase that
says outright that a part is detached is treated as naming a thing, so a world
where somebody is being butchered still works.
"""

import re

#: Parts, as head nouns and singular. Not only human ones: a world with
#: beetles and birds in it has mandibles and wings, and they are no more
#: separate objects than a shoulder is.
PARTS = frozenset("""
    head skull face scalp hair brow eyebrow eyelash eyelid eye cheek nose
    nostril mouth lip tongue tooth jaw chin ear neck throat beard moustache
    shoulder arm elbow forearm wrist hand palm fist finger thumb knuckle
    fingernail nail chest breast bosom back spine rib flank waist hip belly
    stomach navel groin buttock backside rump leg thigh knee shin calf ankle
    foot heel toe sole lap
    skin flesh bone blood muscle sinew tendon vein artery nerve gut entrail
    heart lung liver kidney brain womb bladder
    wing tail claw talon paw pawpad hoof horn antler fang tusk beak snout
    muzzle whisker mane fur pelt hide scale feather plume fin gill tentacle
    antenna mandible carapace shell stinger
""".split())

#: Plurals the ordinary rule does not reach.
IRREGULAR = {
    "teeth": "tooth", "feet": "foot", "hands": "hand", "eyes": "eye",
    "entrails": "entrail", "viscera": "gut", "bowels": "gut",
    "knees": "knee", "calves": "calf", "hooves": "hoof",
    "leaves": "leaf", "wolves": "wolf",
}

#: Words that say a part has been separated from whoever had it. Then it is a
#: thing, and making one is exactly right.
DETACHED = frozenset("""
    severed cut chopped hacked torn ripped bitten amputated dismembered
    detached lopped broken-off discarded spare false wooden prosthetic
    mummified pickled preserved dried stuffed mounted rotting rotten
    bloody bloodied butchered flayed skinned
""".split())

#: Words that pick out which of a pair, or what condition it is in. They sit
#: between the owner and the part -- "yuna's left hand" -- so a phrase read
#: without punctuation has to step back over them to find where the name ends.
MODIFIERS = frozenset("""
    left right upper lower fore hind front back near far other second
    bare good bad free whole broken bruised outstretched open closed
""".split())

#: Owners that are said rather than named. First and second person mean
#: whoever is speaking: a player typing "my hand" and an NPC thinking "your
#: hand" are each talking about the one holding the conversation.
SPEAKER = frozenset(["my", "mine", "our", "ours", "your", "yours", "own"])

#: Third person, which needs somebody to point at. Nothing here tracks who
#: was last mentioned, so these only resolve when there is exactly one
#: candidate and the question answers itself.
THIRD_PERSON = frozenset(["his", "her", "hers", "its", "their", "theirs"])

#: Dropped from the front of a phrase before anything is read into it.
ARTICLES = frozenset(["the", "a", "an", "some", "that", "this", "those",
                      "these"])

#: A possessive: "Samuel's shoulder", "the innkeeper's hands", "Ris' badge".
#: Matched against text that still has its apostrophes, which is the whole
#: signal -- tokenising first turns "Samuel's" into two words and loses it.
_POSSESSIVE = re.compile(r"^(?P<owner>.+?)['’]s?(?=\s)\s+(?P<tail>.+)$")

#: "of" only turns a phrase around when what follows it is a person: "the
#: back of her hand" is about a hand, while a "chest of drawers" is a chest
#: and the "eye of the storm" is weather. The test is whether the tail claims
#: ownership of anything, which a pronoun or a possessive does and a plain
#: noun does not.
_OWNED = re.compile(r"^(?:%s)\b|['’]s?\s" % "|".join(SPEAKER | THIRD_PERSON))


def _words(text):
    """The words of a phrase, hyphens counting as spaces."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _singular(word):
    """Enough of a singulariser for a word list to be looked up with."""
    if word in IRREGULAR:
        return IRREGULAR[word]
    for suffix, stem in (("ies", "y"), ("ses", "s"), ("xes", "x"),
                         ("zes", "z"), ("ches", "ch"), ("shes", "sh")):
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            return word[: -len(suffix)] + stem
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def head_noun(phrase):
    """
    The word a phrase is actually about.

    The last one, except that "of" turns a phrase around: a "shoulder bag" is
    a bag, and the "back of her hand" is a hand rather than a back. Getting
    this right is most of what keeps the vocabulary from over-reaching.
    """
    words = [w for w in _words(phrase) if w not in ARTICLES]
    if not words:
        return ""
    if "of" in words:
        after = words[words.index("of") + 1:]
        words = after or words[: words.index("of")]
    return _singular(words[-1]) if words else ""


def is_part(phrase):
    """True if `phrase` names part of a body rather than a thing."""
    if not phrase:
        return False
    words = set(_words(phrase))
    if words & DETACHED:
        return False        # a severed hand is a thing, and may be made
    return head_noun(phrase) in PARTS


def people_near(caller):
    """Everybody the caller could be talking about, themselves included."""
    from world.quests import is_person

    room = getattr(caller, "location", None)
    found = [caller] if caller is not None else []
    for obj in (room.contents if room is not None else []):
        if obj is not caller and is_person(obj):
            found.append(obj)
    return found


def split_owner(phrase):
    """
    (owner, tail, stated) for a phrase that says whose something is.

    The owner comes back either as a string to go looking for, or as one of
    the SPEAKER / THIRD_PERSON marker sets standing in for a pronoun.

    `stated` is the difference between a claim and a guess, and it decides
    what happens when the owner turns out not to be here. An apostrophe or a
    pronoun states ownership outright. Bare adjacency -- "samuels shoulder",
    typed by somebody who does not stop for punctuation -- only suggests it,
    and is read that way only when the phrase ends in a part of a body, so
    that "table leg" is not quietly taken to be a table's leg.
    """
    text = " ".join((phrase or "").lower().replace("-", " ").split())
    if not text:
        return None, phrase, False

    if " of " in text:
        part, _, owner = text.rpartition(" of ")
        if part and _OWNED.search(owner + " "):
            # "the back of her hand": the owner is hers, the part is a hand.
            return split_owner(owner)

    words = text.split()
    lead = words[0].strip("'’")
    if len(words) > 1:
        if lead in SPEAKER:
            return SPEAKER, " ".join(words[1:]), True
        if lead in THIRD_PERSON:
            return THIRD_PERSON, " ".join(words[1:]), True

    match = _POSSESSIVE.match(text)
    if match:
        owner = " ".join(w for w in match.group("owner").split()
                         if w not in ARTICLES)
        if owner:
            return owner, match.group("tail"), True

    # No punctuation, but the phrase ends in somebody's shoulder and the
    # words in front of it are as likely to be their name as anything. Step
    # back over the part and whatever qualifies it, so that the name in
    # "yuna chois left hand" does not end up with a "left" stuck on it.
    cut = len(words)
    while cut and (words[cut - 1] in MODIFIERS or is_part(words[cut - 1])):
        cut -= 1
    if 0 < cut < len(words):
        owner = " ".join(w for w in words[:cut] if w not in ARTICLES)
        if owner and is_part(words[-1]):
            return owner, " ".join(words[cut:]), False

    return None, text, False


def resolve_owner(caller, owner):
    """
    The person an owner phrase refers to, or None.

    A pronoun in the first or second person is whoever is speaking. One in
    the third person is only answered when a single other person is present,
    because guessing which of three people "her" meant is how you end up
    acting on a stranger.
    """
    if owner is SPEAKER:
        return caller
    if owner is THIRD_PERSON:
        others = [p for p in people_near(caller) if p is not caller]
        return others[0] if len(others) == 1 else None

    from world.naming import CONFIDENT, best_match

    person, score = best_match(caller, owner, candidates=people_near(caller))
    return person if score >= CONFIDENT else None


def instead_of_a_part(caller, phrase):
    """
    What to do about a phrase that names something of somebody's.

    Returns the same three answers `naming.instead_of_creating` does, and for
    the same reason -- both are asked just before something would be conjured:

      (obj, None)   -- this is what was meant; act on it
      (None, text)  -- it belongs to somebody, but there is nothing to act
                       on; say `text` and make nothing
      (None, None)  -- nobody owns this; carry on and conjure it

    Note which way the two failures fall. A part of somebody present resolves
    to *them*, so the verb still runs; a part of somebody absent is refused
    outright, because the alternative is a shoulder on the floor belonging to
    a man who left an hour ago.

    A phrase that names nobody is not this module's business, even when it is
    plainly anatomical. "Hand" on its own has no owner to resolve to, and half
    the vocabulary doubles as ordinary furniture -- a nail, a horn, a shell, a
    chest. Those go on to the existence check, which is told the same rule in
    words and can weigh it against the room.
    """
    if caller is None or not phrase:
        return None, None

    # A part said to be off the body is a thing, and a thing may be named,
    # found and made like any other. This has to come before the owner is
    # read, or "the mounted stag's head" is refused for want of a stag.
    if set(_words(phrase)) & DETACHED:
        _, thing, stated = split_owner(phrase)
        if stated:
            # "Samuel's severed hand" names whose it was, which is no help in
            # finding it: what is lying there is a severed hand. Ask again
            # without him, so the one already on the floor is found rather
            # than a second one made.
            from world.naming import CONFIDENT, best_match

            obj, score = best_match(caller, thing)
            if obj is not None and score >= CONFIDENT:
                return obj, None
        return None, None

    owner, tail, stated = split_owner(phrase)
    if owner is None:
        return None, None

    person = resolve_owner(caller, owner)
    if person is None:
        if not stated:
            return None, None   # only ever a guess; let it be conjured
        label = "them" if owner in (SPEAKER, THIRD_PERSON) else owner
        return None, f"You see no {label} here."

    part = is_part(tail)

    if part:
        return person, None

    # Not a part, but still theirs: the hat they are wearing, the ledger they
    # carry. Finding it beats running off a second one.
    from world.naming import PLAUSIBLE, best_match

    carried = list(person.contents)
    if carried:
        obj, score = best_match(caller, tail, candidates=carried)
        if obj is not None and score >= PLAUSIBLE:
            return obj, None

    whose = "your" if person is caller else f"{person.key}'s"
    return None, f"You see no {whose} {tail} here."
