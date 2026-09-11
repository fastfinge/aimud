"""
What a player meant by a run of words.

Six modules in this game know a little about what a noun phrase looks like,
and three of them keep their own list of words to ignore:

    verbs._NOISE     the a an my your some that this
    naming._NOISE    the a an my your some that this of
    anatomy.ARTICLES the a an some that this those these

They disagree, and the disagreement is not cosmetic. `verbs` and `naming`
throw "my" and "your" away as noise; `anatomy` reads them as a claim about who
something belongs to. `naming` discards "of"; `anatomy` uses it to turn a
phrase around, so that the back of her hand is a hand. Whoever adds
possessives to one of the three will not think to look at the other two, and
nothing will fail -- the wrong answer is a quiet one.

So there is one reader, and everything else becomes a caller of it.

**The grammar, which is worth writing down because it is small:**

    NP := Quantifier? "of"? Determiner? Possessive? Ordinal? Modifier* Head
        | Pronoun
    Possessive := PossessivePronoun | Name "'s"
    Head := Noun

Recursive descent over that, by hand, and about as long as this docstring.
Not a parser generator and not a tagger, for a reason that is a contract
rather than a preference: `lexicon.py` promises that a missing WordNet makes
the world clumsier and never impossible, and a grammar that has to know
whether "slate" is a noun or an adjective breaks that promise on its first
line. This one never asks. **Everything before the head is a modifier and the
head is the last word** -- wrong about English in general, right about every
name this game generates, because `verbs.naming_rule()` is what wrote them.

**What `.plain` is, and why it is not `.head`.** `.plain` is the phrase with
its determiners gone and nothing else touched, which is exactly what
`verbs.plain` has always returned, and half this game matches on it. The
structure sits beside it rather than replacing it: `.possessor` and `.head`
are new information that nothing reads yet. They are read in phase P6, when
possessive matching arrives and "get her ball" has somewhere to look. Until
then this module changes what the code *knows* and not what it *does*, which
is the whole of what P0 is for.
"""

import re

#: Words that carry no meaning of their own in a noun phrase.
#:
#: The union of the three lists above, minus the two that turned out not to be
#: noise at all. "of" is grammar and is read below; "my" and "your" are a claim
#: about ownership and are read as one.
DETERMINERS = frozenset([
    "the", "a", "an", "some", "that", "this", "those", "these",
])

#: Possessive pronouns, and whose they are.
#:
#: First and second person mean whoever is holding the conversation -- a player
#: typing "my hand" and a character thinking "your hand" are each talking about
#: the one they are talking to. Third person needs somebody to point at, which
#: is `world.referents`' job and not this module's; here it is only recognised
#: and handed back.
SPEAKER = frozenset(["my", "mine", "our", "ours", "your", "yours", "own"])
THIRD_PERSON = frozenset(["his", "her", "hers", "its", "their", "theirs"])
POSSESSIVES = SPEAKER | THIRD_PERSON

#: What says nothing about *what a thing is*, and so is dropped before a name
#: is matched. Determiners, and a possessive in the person already holding the
#: conversation: "my ball" is a ball, and which ball is a separate question
#: answered by `.possessor`. All three of the lists this module replaces agreed
#: on exactly these, give or take "those" and "these", which two of them had
#: simply never got around to.
MEANINGLESS = DETERMINERS | (SPEAKER - {"own"})

#: Words that mean the lot, and the ones that narrow it. "all" on its own is
#: everything here; "every wrench" is a narrowing, and reading the second as
#: the first is how "get every wrench" came to offer to invent an object
#: called "every wrench".
QUANTIFIERS = frozenset(["all", "every", "each", "both", "any"])

#: And the plain words for the same thing, which take no noun after them.
EVERYTHING = frozenset(["all", "everything", "every", "each", "both",
                        "the lot", "lot"])
EVERYBODY = frozenset(["everyone", "everybody", "all of them"])

#: How somebody picks one of several things with the same name. Ordinals only,
#: never the cardinals beside them: "the second wrench" is one wrench and "two
#: wrenches" is two of them. `-1` is the last, which is the only count anybody
#: makes from the other end, and "other" is second -- exact rather than
#: approximate, given that what you are carrying is counted first.
ORDINALS = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2, "other": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
    "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7,
    "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
    "last": -1, "final": -1,
}

#: The place and the person, which no search can find: a room is not in its own
#: contents and nobody is in their own inventory.
HERE_WORDS = frozenset(["here", "around", "room"])
SELF_WORDS = frozenset(["me", "myself", "self"])

#: A possessive with punctuation: "Samuel's shoulder", "Ris' badge". Matched
#: against text that still has its apostrophes, which is the whole signal --
#: tokenising first turns "Samuel's" into two words and loses it.
_POSSESSIVE = re.compile(r"^(?P<owner>.+?)['’]s?(?=\s)\s+(?P<tail>.+)$")

#: "of" only turns a phrase around when what follows it claims ownership: "the
#: back of her hand" is about a hand, while a "chest of drawers" is a chest and
#: the "eye of the storm" is weather.
_OWNED = re.compile(r"^(?:%s)\b|['’]s?\s" % "|".join(POSSESSIVES))


#: The tables a world may add to, and the attribute each is read from.
#:
#: Nothing overrides anything yet, and this is here anyway because the first
#: thing that will is already scheduled: a world that invents a pronoun set
#: (P1) has invented a possessive adjective with it, and "get zir sword" has to
#: reach the same branch "get her sword" does. Retrofitting that later means
#: finding every call site a second time.
#:
#: Additive only. A world may teach the parser a word; it may not take one
#: away, because the words here are English rather than furniture, and a world
#: that unteaches "the" is a world nobody can type in.
OVERRIDABLE = {
    "determiners": "extra_determiners",
    "possessives": "extra_possessives",
    "quantifiers": "extra_quantifiers",
    "here_words": "extra_here_words",
    "self_words": "extra_self_words",
}

_BUILT_IN = {
    "determiners": DETERMINERS,
    "possessives": POSSESSIVES,
    "quantifiers": QUANTIFIERS,
    "here_words": HERE_WORDS,
    "self_words": SELF_WORDS,
}


def tables(world_root=None):
    """
    The word tables this reader works from, with a world's own added.

    One function, so a plugin or a pronoun register has one place to reach and
    no caller has to know whether a world had anything to say.
    """
    built = dict(_BUILT_IN)
    if world_root is None:
        return built
    for name, attribute in OVERRIDABLE.items():
        try:
            extra = getattr(world_root.db, attribute, None) or ()
            words = {str(w).lower().strip() for w in extra if str(w).strip()}
        except (AttributeError, TypeError):
            continue
        if words:
            built[name] = built[name] | words
    return built


class NounPhrase:
    """
    One noun phrase, read apart.

    Every field is answered for every phrase, so no caller has to test whether
    a part was present before asking about it: a phrase with no quantifier has
    an empty one rather than None, and a phrase nobody counted has an ordinal
    of zero. Zero is not one -- "wrench" takes whichever is nearest and "first
    wrench" takes the first of however many there are.
    """

    __slots__ = ("raw", "words", "rest", "quantifier", "possessor",
                 "possessor_words", "ordinal", "modifiers", "head", "pronoun")

    def __init__(self, raw="", words=(), rest=(), quantifier="",
                 possessor=None, possessor_words="", ordinal=0, modifiers=(),
                 head="", pronoun=""):
        self.raw = raw
        self.words = list(words)
        self.rest = list(rest)
        self.quantifier = quantifier
        self.possessor = possessor
        self.possessor_words = possessor_words
        self.ordinal = ordinal
        self.modifiers = list(modifiers)
        self.head = head
        self.pronoun = pronoun

    @property
    def plain(self):
        """
        The phrase with its determiners gone, and nothing else taken out.

        What `verbs.plain` has always returned, and what half this game
        matches on. It still carries the quantifier, the count and any written
        possessive: "the second wrench" is "second wrench" here, not "wrench".

        That is deliberate and it is the line between this phase and the next.
        P0 changes what the code *knows*, not what it *does* -- so the parts
        that were being thrown away are now named and kept beside this string
        rather than replacing it. `naming` is the reason: it scores a typed
        phrase against an object's key, and an object called "Second Wrench"
        is a real possibility.
        """
        return " ".join(self.words)

    @property
    def thing(self):
        """
        What is left once the grammar has been taken off: "wrench" from "all
        of her second-best wrenches".

        This is the string a search should actually use, and almost nothing
        uses it yet. `bind` moves onto it in P2, possessive matching in P6.
        """
        return " ".join(self.rest)

    @property
    def counted(self):
        """(which, rest) the way `verbs.ordinal` has always answered."""
        if not self.ordinal:
            return 0, self.plain
        return self.ordinal, " ".join(self.words[1:])

    @property
    def means_everything(self):
        """Whether this names the lot rather than a thing."""
        return bool(self.quantifier)

    @property
    def about_people(self):
        """Whether "everyone" was meant rather than "everything"."""
        return self.plain in EVERYBODY

    @property
    def is_self(self):
        return self.plain in SELF_WORDS

    @property
    def is_here(self):
        return self.plain in HERE_WORDS

    @property
    def stated_possessor(self):
        """
        Whether ownership was claimed rather than guessed at.

        An apostrophe or a possessive pronoun states it outright. Bare
        adjacency -- "samuels shoulder", typed by somebody who does not stop
        for punctuation -- only suggests it, and a caller that acts on a guess
        must not refuse when the guess turns out to name nobody.
        """
        return self.possessor is not None

    def __repr__(self):
        return f"<NounPhrase {self.raw!r} head={self.head!r}>"


def words_of(text):
    """The words of a phrase, hyphens counting as spaces, lowercased."""
    return re.findall(r"[a-z0-9']+", (text or "").lower().replace("-", " "))


def read(phrase, world_root=None):
    """
    Read one noun phrase apart. Never raises; an empty phrase reads as empty.

    The order is the grammar's order, and each step consumes from the front:
    the quantifier, then the possessive, then the determiner and the count,
    and whatever is left is modifiers and a head.

    `world_root` lets a world's own words in -- see `tables`. Left out, the
    reader knows only English, which is what every caller wants today.
    """
    words_that = tables(world_root)
    raw = str(phrase or "").strip()
    text = " ".join(raw.lower().replace("-", " ").split())
    if not text:
        return NounPhrase()

    # The matching view first, off the phrase as typed: determiners and a
    # first-or-second-person possessive carry nothing about what the thing is,
    # and every one of the three lists this module replaces agreed on that.
    spelled = words_of(text)
    meaningless = words_that['determiners'] | (words_that['possessives'] & SPEAKER)
    words = [w for w in spelled if w not in meaningless] or spelled

    # Then the grammar, which consumes from the front.
    rest_text, quantifier = _take_quantifier(text, words_that['quantifiers'])
    rest_text = _turn_around(rest_text)
    rest_text, possessor, possessor_words = _take_possessor(
        rest_text, words_that['determiners'], words_that['possessives'])
    rest = [w for w in words_of(rest_text) if w not in words_that['determiners']]
    ordinal, rest = _take_ordinal(rest)

    pronoun = (words[0] if len(words) == 1
               and words[0] in words_that['possessives'] else "")
    head = rest[-1] if rest else ""
    modifiers = rest[:-1] if len(rest) > 1 else []

    return NounPhrase(raw=raw, words=words, rest=rest, quantifier=quantifier,
                      possessor=possessor, possessor_words=possessor_words,
                      ordinal=ordinal, modifiers=modifiers, head=head,
                      pronoun=pronoun)


def _turn_around(text):
    """
    "the back of her hand" is about a hand; "a chest of drawers" is a chest.

    The test is whether what follows "of" claims ownership of anything, which
    a pronoun or an apostrophe does and a plain noun does not.
    """
    if " of " not in text:
        return text
    part, _, owner = text.rpartition(" of ")
    if part and _OWNED.search(owner + " "):
        return owner
    return text


def _take_quantifier(text, quantifiers=QUANTIFIERS):
    """(rest, quantifier). "all of the wrenches" and "every wrench" both."""
    if text in EVERYTHING or text in EVERYBODY:
        # The whole phrase was the quantifier: nothing narrows it, so nothing
        # is left. "all" means the room, not a thing called all.
        return "", "all"
    words = text.split()
    if words[0] in quantifiers and len(words) > 1:
        rest = words[1:]
        if rest and rest[0] == "of":
            rest = rest[1:]
        return " ".join(rest), words[0]
    return text, ""


def _take_possessor(text, determiners=DETERMINERS,
                    possessives=POSSESSIVES):
    """
    (rest, possessor, what was written).

    The possessor comes back as one of the marker sets when it was a pronoun,
    and as a name to go looking for when it was written out. `None` means
    nobody claimed anything -- which is not the same as a claim that failed.
    """
    words = text.split()
    if len(words) > 1:
        lead = words[0].strip("'’")
        if lead in SPEAKER:
            return " ".join(words[1:]), SPEAKER, lead
        if lead in possessives:
            # Anything a world taught the parser is third person: a world
            # invents a possessive when it invents a character to use it, and
            # first and second person are whoever is talking either way.
            return " ".join(words[1:]), THIRD_PERSON, lead

    match = _POSSESSIVE.match(text)
    if match:
        owner = " ".join(w for w in match.group("owner").split()
                         if w not in determiners)
        if owner:
            return match.group("tail"), owner, owner
    return text, None, ""


def _take_ordinal(words):
    """
    (which, rest). Only a phrase with something left after the number counts,
    so "get first" is still somebody naming a thing called first rather than
    an empty request for the first of nothing.
    """
    if len(words) < 2:
        return 0, words
    which = ORDINALS.get(words[0], 0)
    return (which, words[1:]) if which else (0, words)
