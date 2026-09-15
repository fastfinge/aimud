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

Two questions, in order, and neither of them costs a model call:

* **Who does the phrase belong to?** "Samuel's", "her", "my" -- possession is
  syntax, and syntax is free. Asked of `world.ownership`, which is where that
  question lives now that it is everybody's: `verbs.bind` and `world.bulk`
  both ask it, and an answer here that disagreed with theirs would be two
  answers to one question. An owner who is not here is a phrase about nobody,
  and nothing gets made for it.

* **Is the tail one of their parts?** Judged on the head noun, so a "shoulder
  bag" is a bag and the "back of her hand" is a hand. The vocabulary is a
  list, which means it is incomplete by construction -- so WordNet is asked
  for whatever the list misses, and `item_gen`'s existence check carries the
  same rule in words for whatever both of them miss.

**There was a third question, and it has moved.** "Samuel's hat" should find
the hat he is wearing rather than run one off, and that used to be a search
of his contents made right here, at the last moment before something was
conjured. It happens in `verbs.bind` now, where every other noun is matched,
against what he owns as well as what he is holding -- so by the time a phrase
reaches this module the search has already failed, and what is left to do is
refuse it in words that name him.

Severed parts are deliberately left alone. A hand that has been cut off is an
object like any other and arrives the way objects do -- from a verb's
`create_object` effect, not from somebody naming it -- and once it exists the
ordinary search finds it long before this module is consulted. A phrase that
says outright that a part is detached is treated as naming a thing, so a world
where somebody is being butchered still works.
"""

import re

from world import lexicon, nounphrase

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

#: Owners that are said rather than named. The sets live in
#: `world.nounphrase` with the rest of the grammar and are re-exported here,
#: object and all: `ownership.person_meant` tells them apart with `is`, so
#: there has to be exactly one of each in the process.
SPEAKER = nounphrase.SPEAKER
THIRD_PERSON = nounphrase.THIRD_PERSON

#: Dropped from the front of a phrase before anything is read into it.
ARTICLES = nounphrase.DETERMINERS



def _words(text):
    """The words of a phrase, hyphens counting as spaces."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _singular(word):
    """
    A word reduced to the form the list above is written in.

    The table first, because half of it is not singularising at all: viscera
    and bowels are folded onto "gut" because this vocabulary keeps one word
    for the place they name, and no dictionary is going to volunteer that.
    The rest is ordinary English and is left to one -- teeth, feet, calves,
    hooves and wolves are all handled, along with the antennae and vertebrae
    of a world with beetles in it, which a suffix rule would have had to grow
    a case for and which the table above never listed.
    """
    if word in IRREGULAR:
        return IRREGULAR[word]
    return lexicon.lemma(word, "n")


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


#: What WordNet calls the place a body part hangs. Four roots rather than one,
#: because it files a carapace, a hide, blood and a hand in four different
#: places and all four are things a creature is made of.
BODY_ROOTS = frozenset([
    "body_part.n.01", "body_covering.n.01", "animal_tissue.n.01",
    "body_substance.n.01",
])


def is_listed_part(phrase):
    """
    True for a word this module names outright as part of a body.

    The curated list and nothing else, for the one caller that needs to be
    *sure*: `ownership.whose` decides between reading "her hand" as her and
    reading it as something she is carrying, and a false positive there is a
    hand mirror picked up instead of somebody being touched. Everything
    wider goes through `is_part`, which is asked at the other end -- when a
    thing is about to be conjured, where a false positive costs nothing worse
    than a verb landing on the person it was about.
    """
    if not phrase:
        return False
    if set(_words(phrase)) & DETACHED:
        return False
    return head_noun(phrase) in PARTS


def is_part(phrase):
    """
    True if `phrase` names part of a body rather than a thing.

    Three answers in order of how sure each is. The hand-written list first,
    which is the first answer and not a fallback. Then WordNet, because a
    world with beetles and birds in it has thoraxes and probosces and this
    list has about 120 nouns in it -- and WordNet files every one of them
    under something in `BODY_ROOTS`, for every creature somebody invents
    rather than only the ones whoever wrote the list thought of.

    The commonsense corpus is asked last and only about a word WordNet has
    never heard of, which is a narrower job than it used to have and a better
    one. Asked about ordinary English it answers that a sword is part of
    something and so is a wrench -- true of a scabbard and of a sprained
    ankle, and worth nothing here: it reads "her sword" as anatomy, so the
    verb lands on *her* and the sword she is carrying is never looked at.
    That was invisible until a possessive could be matched against what
    somebody owns, and it is the reason this order exists.
    """
    if not phrase:
        return False
    words = set(_words(phrase))
    if words & DETACHED:
        return False        # a severed hand is a thing, and may be made
    noun = head_noun(phrase)
    if noun in PARTS:
        return True

    senses = lexicon.senses(noun, "n")
    if senses:
        return any(BODY_ROOTS & lexicon.ancestors(name)
                   for name, _definition in senses)

    from world import commonsense

    return commonsense.is_part_of_anything(noun)


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
    pronoun states ownership outright, and that half is ordinary grammar --
    `world.nounphrase` reads it, here and everywhere else.

    What stays here is the half that is not grammar at all. "samuels
    shoulder", typed by somebody who does not stop for punctuation, only
    *suggests* an owner, and the suggestion is worth acting on solely because
    the phrase ends in a part of a body. That test is this module's knowledge
    and no parser has it, which is why the fallback did not move.
    """
    read = nounphrase.read(phrase)
    if read.stated_possessor:
        return read.possessor, read.thing, True

    text = " ".join((phrase or "").lower().replace("-", " ").split())
    if not text:
        return None, phrase, False

    # No punctuation, but the phrase ends in somebody's shoulder and the
    # words in front of it are as likely to be their name as anything. Step
    # back over the part and whatever qualifies it, so that the name in
    # "yuna chois left hand" does not end up with a "left" stuck on it.
    words = text.split()
    cut = len(words)
    while cut and (words[cut - 1] in MODIFIERS or is_part(words[cut - 1])):
        cut -= 1
    if 0 < cut < len(words):
        owner = " ".join(w for w in words[:cut] if w not in ARTICLES)
        if owner and is_part(words[-1]):
            return owner, " ".join(words[cut:]), False

    return None, text, False


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

    from world import ownership

    owner, tail, stated = split_owner(phrase)
    said = nounphrase.read(phrase).possessor_words
    if owner is None:
        return None, None

    spoken = owner in (SPEAKER, THIRD_PERSON)
    person, asked = ownership.person_meant(caller, owner, said)
    if person is None:
        if not stated:
            return None, None   # only ever a guess; let it be conjured
        if asked:
            # Several people here go by that word. Asking which is better
            # than picking, and better than a refusal that names nobody.
            return None, asked
        return None, (f"Whose {tail} do you mean?" if spoken
                      else f"You see no {str(owner).title()} here.")

    if is_part(tail):
        return person, None

    # Not a part, and not anything of theirs either -- `verbs.bind` has
    # already looked, because matching a possessive is what it does now, and
    # what it could not find is not here. So this is the refusal, and the
    # owner is named in it: "you see no hat here" is a lie when there are
    # three on the floor and none of them is hers.
    return None, ownership.no_such(caller, person, tail, spoken=spoken)
