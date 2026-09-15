"""
What English does to a word once it is in a sentence.

Articles, plurals, counts, agreement and the past tense, asked of the thing
first and of spelling last. Every one of these was being decided somewhere
already -- `events` choosing "the", `events._stance` agreeing verbs,
`referents.is_plural` reading a name, Evennia's `get_numbered_name` asking
`inflect` for "a" and "three" -- and each knew a different part of the
answer. See docs/tokens-and-phrases.md §7.

**The layers, in the order they are asked:**

1. *The thing itself.* A person takes no article: "Jessica", never "a
   Jessica". Something filed under a WordNet sense in `noun.substance` is
   stuff rather than things: "some water", never "a water" or "waters".
2. *A word already plural.* "glasses" takes no second plural and no "a" --
   the dictionary's lemma is shorter than the word, which is
   `referents.is_plural`'s test, kept here.
3. *Evennia's conjugator*, for agreement and for the past, where its table
   knows the verb: went, took, gave, was and were.
4. *WordNet's verb exceptions*, for a past Evennia's table does not have:
   bound, bore, baby-sat, co-starred.
5. *`inflect`*, for plurals and "a" or "an" by sound: teeth, bottles of soju,
   an hour, an honest man.
6. *Suffix rules*, last, for a verb nobody has heard of: airlocked,
   teleported, rebooted.

Each is optional. Without WordNet the first two layers and the fourth know
nothing, and the answers are `inflect`'s and Evennia's, which is what the game
said before this module existed.

**Why WordNet's exceptions come after Evennia, and not before as the plan
had them.** The tables cannot tell a past from a participle, and a verb whose
past is regular lists only its participle: sow is filed with "sown" alone, so
"take the one form" gives "she sown". Evennia's table knows both columns, and
knows sow. But it does not know 158 of the 1,392 verbs WordNet lists
irregular forms for -- bind, bear, baby-sit among them -- and for those the
table is right far more often than a regular ending would be.

**Why they are not used for nouns at all.** `inflect` already knows every
irregular plural the noun table does and gets fewer wrong: the table says
fish becomes "fishes".
"""

import re

#: Words that already determine a noun phrase. A name that starts with one
#: takes no other: "the Crown", not "the the Crown".
DETERMINERS = frozenset(("the", "a", "an", "some"))

#: The lexicographer file that means a thing is stuff: water, sand, gold as a
#: metal. `noun.food` is not here and cannot be -- bread, soup and apple share
#: it -- so a kind that is mass and edible has to say so itself one day.
MASS_FILES = frozenset(("noun.substance",))

#: Above this, a count is written in figures: "thirteen coins" is a
#: sentence, "four hundred and twelve coins" is a nuisance. Evennia's own
#: threshold, so nothing a player already reads changes.
FIGURES_ABOVE = 12

_ENGINE = None


def _inflect():
    global _ENGINE
    if _ENGINE is None:
        import inflect

        _ENGINE = inflect.engine()
    return _ENGINE


# ---------------------------------------------------------------------------
# What a thing is
# ---------------------------------------------------------------------------

def is_plural(noun):
    """
    Whether a noun phrase is grammatically plural: "glasses", "coins".

    Read from its head -- the last word, or the last before "of", since "a
    pair of boots" is one pair -- and asked of the dictionary rather than of a
    suffix: the lemma is shorter than the word. False without a dictionary,
    which is the neutral answer. False for "scissors" too, which WordNet files
    as its own headword -- a known gap rather than a guess made here.

    `referents.is_plural` asks about the last word instead, and means
    something different by it: a pile of coins is "them" to somebody typing,
    whatever it is to a grammarian.
    """
    from world import lexicon

    word = _head(noun).lower()
    if not word:
        return False
    return lexicon.lemma(word, "n") != word


def _head(noun):
    """The word a noun phrase's number and article are decided by."""
    words = str(noun or "").split()
    lowered = [word.lower() for word in words]
    if "of" in lowered[1:-1]:
        words = words[:lowered.index("of", 1)]
    return words[-1] if words else ""


def is_proper(obj):
    """Whether this is somebody, who is called by name and takes no article."""
    if obj is None:
        return False
    from world.quests import is_person

    try:
        return bool(is_person(obj))
    except AttributeError:
        return False


def is_mass(obj):
    """
    Whether a thing is stuff rather than things.

    Read off the sense it was filed under -- its first kind, when that is a
    WordNet id -- and never guessed from its name: "gold" is a metal in one
    sense and a coin's worth in another, and only the thing knows which.
    """
    from world import lexicon

    try:
        kinds = list(obj.db.kinds or [])
    except AttributeError:
        return False
    return bool(kinds) and lexicon.lexical_file(kinds[0]) in MASS_FILES


# ---------------------------------------------------------------------------
# Nouns
# ---------------------------------------------------------------------------

def article(noun, obj=None, definite=False):
    """
    The article a noun takes: "the", "a", "an", "some", or nothing.

    Nothing for a name that already has one and for somebody. "some" for
    stuff and for a word already plural. Otherwise "a" or "an" by how the
    word sounds, which `inflect` knows and spelling does not: an hour, a
    unicorn, an X-ray.
    """
    noun = str(noun or "").strip()
    if not noun:
        return ""
    if noun.split(" ", 1)[0].lower() in DETERMINERS:
        return ""
    if is_proper(obj):
        return ""
    if definite:
        return "the"
    if is_mass(obj) or is_plural(noun):
        return "some"
    try:
        return _inflect().a(noun).split(" ", 1)[0]
    except Exception:
        return "a"


def with_article(noun, obj=None, definite=False):
    """The noun with whatever article it takes: "a sword", "Jessica"."""
    noun = str(noun or "").strip()
    word = article(noun, obj, definite)
    return f"{word} {noun}" if word else noun


def plural(noun, obj=None):
    """
    More than one: "swords", "teeth", "bottles of soju".

    Unchanged for stuff, which has no plural, and for a word that already is
    one. `inflect` does the rest, and puts the plural where English does: on
    the bottle, not the soju.
    """
    noun = str(noun or "").strip()
    if not noun or is_mass(obj) or is_plural(noun):
        return noun
    try:
        return _inflect().plural_noun(noun) or noun
    except Exception:
        return noun


def count(n, noun, obj=None):
    """
    A number of something: "a sword", "three swords", "13 coins", "some water".

    One is the noun with its article. Stuff is "some" however much there is,
    because "three water" is not English and "three measures of water" is a
    decision about measures nobody has made.
    """
    noun = str(noun or "").strip()
    if not noun:
        return ""
    if n == 1:
        return with_article(noun, obj)
    if is_mass(obj):
        return f"some {noun}"
    try:
        figure = _inflect().number_to_words(n, threshold=FIGURES_ABOVE)
    except Exception:
        figure = str(n)
    return f"{figure} {plural(noun, obj)}"


# ---------------------------------------------------------------------------
# Verbs
# ---------------------------------------------------------------------------

def conjugate(verb, person=3, plural=False, tense="present"):
    """
    A verb agreeing with its subject, in a tense.

    `person` is 2 for the reader and 3 for everybody else; `plural` is the
    subject's number, which for a person is their pronoun set's and not their
    count. Only the first word is touched, so "pick up" is "picks up" and
    "picked up".
    """
    verb = str(verb or "").strip()
    if not verb:
        return ""
    head, _, tail = verb.partition(" ")
    if tense == "past":
        word = past(head, person, plural)
    else:
        second, third = _stance(head, plural)
        word = second if person == 2 else third
    return f"{word} {tail}".strip()


def past(verb, person=3, plural=False):
    """
    The simple past: "handed", "went", "was" for her and "were" for them.

    Evennia's table first, which knows irregular verbs and knows that "be"
    agrees in the past as in nothing else. Then WordNet's irregular forms, for
    a verb Evennia's table lacks. A verb neither has heard of -- anything a
    world invented -- is regular, which is what an invented verb is.
    """
    verb = str(verb or "").strip()
    if not verb:
        return ""
    who = "*" if plural else (2 if person == 2 else 3)
    try:
        from evennia.utils.verb_conjugation.conjugate import verb_past

        word = verb_past(verb, person=who)
    except Exception:
        word = ""
    return str(word) if word else (irregular_past(verb) or regular_past(verb))


def irregular_past(verb):
    """
    The past WordNet's exception table gives a verb, or "".

    One form is taken as it is: bind, bound. Where there are several, the ones
    that look like participles -- ending "n" or "ne", as born, borne, sown and
    hewn do -- are set aside, and what is left is used only if it is one form:
    bear, bore.
    """
    from world import lexicon

    forms = lexicon.verb_exceptions(verb)
    if len(forms) > 1:
        forms = [form for form in forms if not form.endswith(("n", "ne"))]
    return forms[0] if len(forms) == 1 else ""


#: A verb of one syllable ending consonant, vowel, consonant, whose last
#: letter doubles: zap, zapped. w, x and y never double.
_DOUBLES = re.compile(r"[^aeiou]*[aeiou][b-df-hj-np-tvz]")


def regular_past(verb):
    """
    The past a verb would have if it were regular.

    Only for verbs no table knows, so only the three rules that decide
    spelling: an e takes d, a consonant and y becomes ied, and a
    one-syllable consonant-vowel-consonant doubles its last letter. A longer
    verb that would double -- "hotswapped" -- does not; that needs stress,
    which spelling does not show.
    """
    word = str(verb or "").strip()
    lower = word.lower()
    if not lower:
        return ""
    if lower.endswith("e"):
        return word + "d"
    if len(lower) > 1 and lower.endswith("y") and lower[-2] not in "aeiou":
        return word[:-1] + "ied"
    if _DOUBLES.fullmatch(lower):
        return word + word[-1] + "ed"
    return word + "ed"


def _stance(verb, plural):
    """(second person, third person) present for one word."""
    try:
        from evennia.utils.verb_conjugation.conjugate import (
            verb_actor_stance_components)

        second, third = verb_actor_stance_components(verb, plural=plural)
        return str(second or verb), str(third or verb)
    except Exception:
        return verb, verb if plural else f"{verb}s"


def base_form(word):
    """
    The base form of a third-person-singular verb, or "" if it is not one.

    Asked of the conjugator rather than guessed at with suffix rules, which is
    the only way "tries" comes back "try", "watches" "watch" and "is" "be"
    without a table of exceptions here. "" for anything whose third person is
    not the word given, so a caller leaves alone whatever it cannot be sure
    about.

    Evennia's own infinitive is asked first. Guessing alone once answered
    "i" for "is" -- the third person of a verb "i" is "is", by the suffix
    rule -- and `events.repair` turned "{actor} is tired" into a template
    that told its own actor "You i tired". A one-letter guess is never taken.
    """
    word = str(word or "")
    try:
        from evennia.utils.verb_conjugation.conjugate import verb_infinitive

        known = verb_infinitive(word)
    except Exception:
        known = ""
    if known and known != word and _stance(known, False)[1] == word:
        return known
    for guess in _base_guesses(word):
        if len(guess) < 2:
            continue
        try:
            if _stance(guess, False)[1] == word:
                return guess
        except Exception:
            continue
    return ""


def _base_guesses(word):
    """Every base form `word` could be the third person singular of."""
    if word.endswith("ies") and len(word) > 4:
        yield word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        yield word[:-2]
    if word.endswith("es"):
        yield word[:-1]
        yield word[:-2]
    if word.endswith("s"):
        yield word[:-1]
