"""
Verb parsing, noun binding, and the world's open state vocabulary.

This is the deterministic half of the command system.  A player types "tie
rope to tree"; this module turns that into a verb, a set of roles, and the
actual objects those roles refer to, without asking a model anything.  Only
when the parse binds successfully and the outcome is genuinely unknown does
the model get involved.

The design point that matters: a verb's meaning belongs to the objects it
acts on, never to the room it was used in.  "read" means the same thing in a
classroom and a submarine; what differs is what is written on the thing being
read.  Binding nouns to real objects is what lets an outcome be cached where
it belongs and stay true everywhere.

States are an open vocabulary.  Nothing here enumerates what an object may be
-- burning, wet, dirty, locked are all just slugs, registered on the world the
first time a rule needs them, with their conflicts declared at that point so
that wetting a burning thing puts it out.
"""

import re
import threading

from evennia.utils import logger

from world import lexicon, nounphrase

# Prepositions that introduce a second noun, mapped to the role that noun
# plays.  "unlock door with key" -> direct=door, instrument=key.
PREPOSITION_ROLES = {
    "with": "instrument",
    "using": "instrument",
    "to": "target",
    "at": "target",
    "on": "target",
    "onto": "target",
    "in": "container",
    "into": "container",
    "inside": "container",
    "from": "source",
    "out": "source",
    "under": "target",
    "over": "target",
    "behind": "target",
    "for": "target",
    "about": "target",
    # What something is done by way of: "look at the moon through the
    # spyglass" keeps the moon and the spyglass both, which `target` could not
    # -- the moon has already taken it.
    "through": "instrument",
}

#: Verbs whose object may arrive behind a preposition, when nothing came
#: before one. "look at the lamp", "look in the chest", "look through the
#: spyglass" all name what is looked at, and read strictly each of them named
#: nothing to look at -- which the rules answer by describing the room, and
#: the look command answered by conjuring a thing called "at the lamp". The
#: preposition is kept, so a world can still tell looking into a chest from
#: looking at one.
PREPOSITION_MAY_NAME_DIRECT = frozenset(["look"])

# Words that carry no meaning in a command. One list, in world.nounphrase,
# which is also where "my" stopped being noise and started being a claim.
_NOISE = nounphrase.MEANINGLESS

# Verb synonyms folded onto one canonical verb, so the cache does not
# fragment into examine/inspect/study/peruse all meaning the same thing.
VERB_SYNONYMS = {
    "examine": "look", "inspect": "look", "study": "look", "observe": "look",
    "l": "look", "x": "look", "view": "look",
    "peruse": "read", "skim": "read",
    "grab": "get", "take": "get", "pick": "get", "collect": "get",
    "toss": "drop", "discard": "drop",
    "shut": "close",
    "ignite": "light", "kindle": "light",
    "extinguish": "douse", "quench": "douse",
    "smash": "break", "shatter": "break", "destroy": "break",
    "talk": "speak", "chat": "speak",
    "listen": "hear",
    "sniff": "smell",
    "touch": "feel",
    "consume": "eat", "devour": "eat",
    "sip": "drink", "swig": "drink",
    "shove": "push", "press": "push",
    "tug": "pull", "yank": "pull",
    "seat": "sit", "rest": "sit",
    "slumber": "sleep",
    "clean": "wash", "rinse": "wash",
    "fix": "repair", "mend": "repair",
    # Clothing. These four are not learned verbs at all -- world.clothing
    # takes them over before an attempt reaches a model -- but they still have
    # to fold onto one spelling first, or "doff" would be learned as a verb of
    # its own and "remove" would go on meaning something else.
    "don": "wear", "wearing": "wear",
    "doff": "remove", "unwear": "remove",
    # Wielding, for the same reason: world.gear takes these over when the noun
    # really is something to hold, and hands them back when it is not, so
    # "equip the winch" still reaches a model.
    #
    # Only words that can mean nothing else. "sheathe" and "stow" are left
    # alone deliberately: a sword going into its scabbard is a placement, and
    # the game already knows what putting a thing somewhere means.
    "brandish": "wield", "equip": "wield",
    "unequip": "unwield", "lower": "unwield",
}


def canonical_verb(word):
    """
    Fold a verb onto its canonical form.

    Two foldings, and the order matters.  The table above is consulted first
    and exactly as it always was, so nothing a previous world learned can move
    underneath it.  Only a word the table does not know is put through the
    dictionary, which reduces it to its infinitive -- "lit" is light, "broke"
    is break, "held" is hold, "ate" is eat -- and then offered to the table
    again, because the infinitive may be a synonym even where the tense was
    not.

    That second pass is why "wearing" no longer has to be written down.  It
    was never a synonym of "wear"; it is "wear", and a suffix table that knew
    as much would also have to know about "ate".
    """
    word = word.lower().strip()
    folded = VERB_SYNONYMS.get(word)
    if folded is not None:
        return folded

    root = lexicon.lemma(word, "v")
    if root != word:
        return VERB_SYNONYMS.get(root, root)
    return word


def parse(raw):
    """
    Split raw input into a verb, its noun phrases by role, and how it was done.

    Returns {"verb": str, "roles": {role: phrase},
             "prepositions": {role: word}, "manner": [word, ...]} where
    "direct" is the thing acted on and the rest are named by the preposition
    that introduced them.  Word order is preserved, so "tie rope to tree" and
    "tie tree to tree" parse differently, which is the whole point of tracking
    roles rather than collecting a bag of nouns.

    The preposition itself is kept as well as the role it implies, because
    several of them share a role and do not share a meaning: "on the table"
    and "under the table" are both `target`, and putting a book in one place
    rather than the other is the whole of what the player asked for.

    Manner is lifted out of the phrase rather than left in it.  "Drink the cup
    quickly" used to bind nothing at all -- the noun phrase came out as "cup
    quickly", which resembles a cup too little to match one and so conjured a
    second cup with an adverb in its name, at the cost of two model calls.
    Every adverb would do this, and the point of asking a dictionary rather
    than keeping a list is that nobody has to write down what the adverbs of
    English are.  Manner is handed back rather than thrown away, because
    drinking something quickly and drinking it slowly are allowed to differ.
    """
    words = [w for w in re.findall(r"[\w'-]+", raw.lower()) if w]
    if not words:
        return {"verb": "", "roles": {}, "prepositions": {}, "manner": []}

    manner = []

    # A command may open with its manner -- "carefully open the gate" -- and
    # the first word is otherwise taken for the verb, which would leave the
    # world learning a verb called "carefully".  Only leading words are taken
    # this way, and never the last word standing, so "quickly" alone is still
    # somebody typing a verb this world has not met yet.
    while len(words) > 1 and lexicon.is_only_adverb(words[0]):
        manner.append(words.pop(0))

    verb = canonical_verb(words[0])
    roles, prepositions = {}, {}
    current_role = "direct"
    current_word = ""
    current = []

    def flush():
        # Both the phrase and the word that introduced it, together: a role
        # closed by the next preposition has to keep its own, or "put key in
        # box with care" would forget that the box was an "in".
        #
        # The phrase goes through the reader rather than being filtered here.
        # Filtering here is what this used to do, and it could not tell a
        # determiner in front of a noun from a pronoun standing in for one:
        # with "mine" and "yours" in the list, "get mine" dropped every word
        # it had and bound nothing at all.
        if current:
            phrase = nounphrase.read(" ".join(current)).plain
            if phrase:
                roles.setdefault(current_role, phrase)
                if current_word:
                    prepositions.setdefault(current_role, current_word)

    for word in words[1:]:
        if word in PREPOSITION_ROLES:
            flush()
            current = []
            current_role = PREPOSITION_ROLES[word]
            current_word = word
            continue
        if lexicon.is_only_adverb(word):
            # Wherever it fell.  An adverb belongs to the verb no matter which
            # noun phrase it landed in the middle of: "put the lamp down
            # gently" and "gently put the lamp down" are the same request.
            manner.append(word)
            continue
        current.append(word)

    flush()

    # "look at the lamp": the first phrase is what is acted on when nothing
    # came before a preposition. See PREPOSITION_MAY_NAME_DIRECT.
    if verb in PREPOSITION_MAY_NAME_DIRECT and roles and "direct" not in roles:
        first = next(iter(roles))
        roles = {"direct": roles.pop(first), **roles}
        word = prepositions.pop(first, "")
        if word:
            prepositions = {"direct": word, **prepositions}

    return {"verb": verb, "roles": roles, "prepositions": prepositions,
            "manner": manner}


# ---------------------------------------------------------------------------
# Binding nouns to things that actually exist
# ---------------------------------------------------------------------------

#: How closely a name must resemble a phrase to count as the same thing.
#: A player typing a noun means it, so only an exact or contained match will
#: do -- guessing at their words is worse than saying "you see no such thing".
#: An NPC is describing something from memory in its own words, and would
#: rather find the blackboard already on the wall than hang another beside it.
STRICT_SIMILARITY = 0.9
FUZZY_SIMILARITY = 0.6

#: The place and the person, which no search can find. See world.nounphrase.
HERE_WORDS = nounphrase.HERE_WORDS
SELF_WORDS = nounphrase.SELF_WORDS

#: How somebody picks one of several things with the same name. The table
#: itself is in `world.nounphrase` with the rest of the grammar; the name
#: stays here because `suggest` and the tests read it.
ORDINALS = nounphrase.ORDINALS


def plain(phrase):
    """A noun phrase with its noise words gone, for comparing against a list."""
    return nounphrase.read(phrase).plain


def ordinal(phrase):
    """
    (which, rest) -- "the second wrench" is (2, "wrench"), "wrench" is (0, "wrench").

    Zero means nobody counted, which is not the same as one: "wrench" takes
    whichever wrench is nearest to hand, and "first wrench" takes the first of
    them however many there are. Only a phrase with something left after the
    number counts, so "get first" is still somebody naming a thing called
    first rather than an empty request for the first of nothing.
    """
    return nounphrase.read(phrase).counted


def _words(text):
    """
    Meaningful words of a name or phrase, singular.

    Noise words are dropped here as well as in parse(), because they drag a
    score down for saying nothing: "the board" against "Slate Chalkboard"
    should be judged on "board" alone.

    Both sides are reduced to the singular, so "take the knives" finds the
    knife and "wipe the boards" finds the board.  A suffix rule gets most of
    this and then falls over on exactly the words a world is full of -- knives,
    leaves, mice, geese, shelves -- which is the sort of thing a dictionary
    already knows and nobody should be writing down again.
    """
    return [
        lexicon.lemma(w, "n")
        for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if w and w not in _NOISE
    ]


def similarity(phrase, key):
    """
    How well `phrase` names something called `key`, from 0 to 1.

    Exact wins, then containment -- "chalkboard" naming a "Stained Slate
    Chalkboard" -- and below that the best per-word resemblance, which is what
    lets "blackboard" find a chalkboard and still not find an astrolabe.
    """
    import difflib

    phrase_words, key_words = _words(phrase), _words(key)
    if not phrase_words or not key_words:
        return 0.0
    if phrase_words == key_words:
        return 1.0
    if set(phrase_words) <= set(key_words):
        return 0.9
    def best(word):
        return max(
            (difflib.SequenceMatcher(None, word, other).ratio(), other)
            for other in key_words
        )

    # Every word of the phrase has to find a home, and the weakest one decides.
    # Averaging instead lets a single strong word carry a wrong answer: "wall
    # clock" would score well against a "Stained Wall Chalkboard" on the
    # strength of "wall" alone.
    score = min(best(word)[0] for word in phrase_words)

    # What a name is *of* is its last word. "board" resembles "cardboard"
    # slightly more than "chalkboard" on letters alone, but a Cardboard
    # Nametag is a nametag, while a Slate Chalkboard is a board -- so a match
    # against the head noun counts for more than one against a modifier.
    if best(phrase_words[-1])[1] != key_words[-1]:
        score *= 0.85
    return score


def _best_by_similarity(caller, phrase, threshold):
    """
    The thing in reach whose name best resembles `phrase`, if any is close
    enough. Ties go to the oldest, so repeated attempts settle on one object
    instead of wandering between near-identical ones.
    """
    candidates = []
    for location in (caller, caller.location):
        for obj in (location.contents if location else []):
            if getattr(obj, "destination", None) is not None:
                continue     # exits are matched by the movement code, not here
            score = similarity(phrase, obj.key)
            if score >= threshold:
                candidates.append((score, -obj.id, obj))
    if not candidates:
        return None
    return max(candidates)[2]


def _matches(caller, phrase, location):
    """Every object at `location` that the phrase could refer to."""
    from commands.look_take_cmds import _find_one

    obj, multiple = _find_one(caller, phrase, location=location)
    if obj is not None:
        return [obj]
    if not multiple:
        return []
    # _find_one reports ambiguity without saying what matched, so gather the
    # candidates ourselves.
    wanted = phrase.lower().strip()
    words = [w for w in wanted.split() if len(w) > 2]
    found = []
    for candidate in (location.contents if location else []):
        key = candidate.key.lower()
        if key == wanted or wanted in key or any(w in key for w in words):
            found.append(candidate)
    return found


def candidates(caller, phrase):
    """
    Everything in reach that a noun phrase could mean, in counting order.

    What the player is carrying first and then what is in the room, each
    oldest first, which is the order anybody counting out loud would use.
    One list rather than two, because "the second wrench" counts through
    everything it can see and does not start again at the doorway.
    """
    found, seen = [], []
    for location in (caller, getattr(caller, "location", None)):
        if location is None:
            continue
        for obj in sorted(_matches(caller, phrase, location),
                          key=lambda o: o.id):
            if obj.id not in seen:
                seen.append(obj.id)
                found.append(obj)
    return found


def counted(caller, phrase):
    """
    The one of several things a phrase counted out, or None if it counted none.

    Answers None for a phrase with no number in it, so a caller can fall
    through to the ordinary search, and None again when the count runs off the
    end -- asking for the fourth of three wrenches names nothing, and inventing
    a fourth wrench to satisfy it would be the worst possible reading.
    """
    which, rest = ordinal(phrase)
    if not which:
        return None
    found = candidates(caller, rest)
    if not found:
        return None
    if which == -1:
        return found[-1]
    return found[which - 1] if which <= len(found) else None


def _world_of(caller):
    room = getattr(caller, "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


def _in_scope(caller):
    """Everything a pronoun could be about: the people here and what is in reach."""
    from world import anatomy, relations

    found = list(anatomy.people_near(caller))
    for obj in relations.reachable(caller):
        if obj not in found:
            found.append(obj)
    return found


def _verb_allows(world_root, obj, verb):
    """
    Whether this sort of thing admits the verb at all.

    The SHRDLU borrowing, and the cheapest useful half of it: "open it" after
    looking at a candle and then a box prefers the box, because the candle's
    kind has already said it does not open. Only a definite refusal filters --
    silence means nobody has decided, and deciding it here is exactly what a
    pronoun must not do.
    """
    if not verb:
        return True
    from world import kinds

    try:
        return kinds.admits(world_root, obj.db.kinds, verb) is not False
    except Exception:
        return True


def pronoun_candidates(caller, form, verb=""):
    """Everything in reach that this pronoun could mean, nearest first."""
    from world import referents

    world_root = _world_of(caller)
    answering = [obj for obj in _in_scope(caller)
                 if obj is not caller
                 and form in referents.forms_of(obj, world_root)]
    return [obj for obj in answering if _verb_allows(world_root, obj, verb)]


def resolve_pronoun(caller, form, verb=""):
    """
    (object, question) for a pronoun somebody typed.

    A question rather than a guess is the one place this deliberately breaks
    `bind`'s usual contract. `bind` resolves an ambiguous NAME by taking the
    oldest, because the alternative was a room filling up with chalkboards --
    nothing matched, so another was conjured. A pronoun has no such failure
    mode: nothing is ever conjured for "her", so asking costs nothing and
    guessing costs acting on a stranger.
    """
    from world import choosing, referents

    found = pronoun_candidates(caller, form, verb)
    if not found:
        return None, None
    if len(found) == 1:
        return found[0], None

    # Several answer to the word, so the question is which was last meant.
    # Still in reach and still able to be acted on, or it is no answer.
    remembered = referents.recall(caller, form)
    if remembered is not None and remembered in found:
        return remembered, None

    names = [obj.get_display_name(caller) for obj in found]
    return None, choosing.question(form, names)


def bind_or_pronoun(caller, phrase, verb=""):
    """
    What a player's phrase means, pronouns included.

    For the game's own commands -- `get`, `drop` -- which are Evennia's
    wearing a subclass and so never went near the pipeline that resolves
    "it". `get pipe` then `drop it` answered "You aren't carrying it",
    because Evennia searched the inventory for a thing named "it" and found
    nothing. This is the one line of the pipeline they were missing.

    Returns None when nothing answers, exactly as `bind` does, so a caller
    falls through to its own not-found message.
    """
    from world import nounphrase, referents

    text = str(phrase or "").strip()
    if not text:
        return None
    word = nounphrase.read(text, _world_of(caller)).pronoun
    if word:
        found, _question = resolve_pronoun(caller, word, verb)
        # The table before the room: "it" is a promise that both of us
        # already know which one, and the last thing referred to is that
        # promise kept. `resolve_pronoun` only asks the table when several
        # candidates answer, which is right for a typed name and wrong here.
        return referents.recall(caller, word) or found
    return bind(caller, text, verb=verb)


def note_one(caller, obj):
    """
    Record that a command acted on this, so "it" means it next time.

    The single-object counterpart to `note_all`, for the commands that bind
    their own object rather than going through `attempt`. Kept here beside
    that one so there is one place where a binding becomes a referent.
    """
    from world import referents

    referents.note(caller, obj, _world_of(caller))


def bind(caller, phrase, fuzzy=False, verb=""):
    """
    Find what a noun phrase refers to, searching outward from the character.

    Inventory first, then the room, because "read my letter" should find the
    one being carried.

    Ambiguity is NOT absence.  Several things matching means the noun exists
    several times over, so one of them is chosen -- the oldest, for
    predictability -- rather than reporting nothing.  Returning None here for
    an ambiguous noun is what let a room fill up with chalkboards: nothing
    matched, so another was conjured, which made the next match worse.

    Unless the player counted, in which case they meant a particular one of
    them and taking the oldest every time is how "get the second wrench" picks
    up the first wrench twice.

    With `fuzzy`, a name only resembling the phrase will do. That is for NPCs,
    who name things from memory in their own words: better they wipe the
    chalkboard that is already there than hang a blackboard next to it.
    """
    if not phrase:
        return None

    # The two things no search can find, because neither is in anybody's
    # contents: the room you are standing in and yourself.
    text = plain(phrase)
    if text in SELF_WORDS:
        return caller
    if text in HERE_WORDS:
        return getattr(caller, "location", None)

    # A phrase that is one pronoun and nothing else is not a name at all, and
    # must never reach the search below -- what is not found there is
    # conjured, and conjuring a thing called "her" is the worst answer
    # available.
    read = nounphrase.read(phrase, _world_of(caller))
    if read.pronoun:
        found, _question = resolve_pronoun(caller, read.pronoun, verb)
        return found

    # A phrase that says whose it is has narrowed the search itself, and the
    # narrowing is the answer: "her sword" is not a name to look up but a
    # claim to test, so it is matched against what she owns and what she is
    # carrying and against nothing else. Failing that it binds nothing, which
    # is a refusal rather than an invitation -- the alternative, and what this
    # used to do, was to search for an object called "her sword" and offer to
    # invent one. See `world.ownership`.
    if read.possessor is not None:
        from world import ownership

        found, _question = ownership.whose(caller, read)
        return found

    one_of_several = counted(caller, phrase)
    if one_of_several is not None:
        return one_of_several

    for location in (caller, caller.location):
        found = _matches(caller, phrase, location)
        if found:
            return min(found, key=lambda o: o.id)

    # Then outward: on the table, under the rug, inside the open drawer. A
    # thing put down somewhere has to stay nameable, or putting it away would
    # be the same as losing it.
    from world import relations

    placed = relations.find(caller, phrase)
    if placed is not None:
        return placed

    return _best_by_similarity(
        caller, phrase, FUZZY_SIMILARITY if fuzzy else STRICT_SIMILARITY
    )


def bind_all(caller, roles, fuzzy=False, verb=""):
    """
    Bind every role. Returns (bound, unbound, questions).

    Unbound roles are not an error by themselves: the noun may be a fixture
    that exists only in the room's description and can be promoted to a real
    object, which is the caller's decision to make.

    A question is different and is not the caller's decision. It means several
    things here answer to a word somebody used and the game has no business
    picking one -- so the role is neither bound nor available for promoting,
    and whoever typed it gets asked. See `world.choosing`.
    """
    from world import referents

    bound, unbound, questions = {}, [], []
    world_root = _world_of(caller)
    for role, phrase in roles.items():
        read = nounphrase.read(phrase, world_root)
        if read.pronoun:
            obj, asked = resolve_pronoun(caller, read.pronoun, verb)
            if asked:
                questions.append((role, asked))
                continue
        elif read.possessor is not None:
            # "Which her?" is the same question whether the word stood in for
            # the thing or for whoever owns it, so it is asked the same way.
            from world import ownership

            obj, asked = ownership.whose(caller, read)
            if asked:
                questions.append((role, asked))
                continue
        else:
            obj = bind(caller, phrase, fuzzy=fuzzy, verb=verb)
        if obj is None:
            unbound.append(role)
        else:
            bound[role] = obj

    # What was referred to, remembered, so the next "it" has an answer. One
    # place, after everything has bound, so the table cannot disagree with
    # what the attempt actually acted on.
    referents.note_all(caller, bound, world_root)
    return bound, unbound, questions


# ---------------------------------------------------------------------------
# Affordances and states
# ---------------------------------------------------------------------------

def affordances(obj):
    """
    What can be done to an object, as a set of verbs ("read", "burn").

    The one way anything asks. Every caller sees a set of words, which is what
    they have always seen -- what changed underneath is where the words come
    from and what they are. They are verbs now rather than adjectives made out
    of verbs, and they belong to the object's kind rather than to the object,
    so seventy-three bottles cannot arrive at twenty-five answers between
    them. See `world.affordances` and `world.kinds`.

    A map is stored, because a map can say no and a set can only fail to say
    yes. What is returned here is the yes half, since that is what a cache key
    and a precondition both want; `world.affordances.refused()` is the other
    half, for the one caller that needs to tell "cannot" from "nobody said".
    """
    from world import affordances as af

    return af.afforded(obj.db.affordances)


def states(obj):
    """The mutable conditions currently true of an object ("wet", "burning")."""
    return set(obj.db.states or [])


def rule_key(verb, bound=None):
    """
    The key a learned verb rule is cached under: the verb, and nothing else.

    This used to be the verb plus every affordance of every object involved,
    on the reasoning that a verb's meaning belongs to the things it acts on.
    The reasoning was right and the key was the wrong way to act on it. Across
    five worlds it produced 664 rules for 151 verbs -- `drink` thirty times
    over, forked on `breakable` and `flammable` and eight other marks that no
    drink rule has ever mentioned. Eighty-six percent of those rules existed
    because the object said nothing at all about the verb being tried, so
    every new sort of thing somebody drank from bought another copy of what
    drinking means.

    What a verb means is now stored once, here. What a *kind* of thing admits
    -- whether a bottle can be burned at all -- is a yes or no on the kind,
    in `world.kinds`. What happens to *this* bottle when it burns is written
    on the bottle, in the same call that writes what the player reads, which
    was always per-object and always had to be. Three questions that were
    being answered by one overloaded cache key, and only the first of them is
    about the verb alone.

    What remains in the key besides the verb is the *shape* of the sentence:
    which roles were filled, and nothing about what filled them. "Drink the
    bottle" and "drink from the bottle" are not the same request, and a rule
    learned for one is wrong for the other in a way no precondition can
    rescue -- a rule that requires the `source` be open and not empty, met
    with an attempt that bound only `direct`, refuses with "you are not
    holding the source", which is true, unanswerable and about nothing the
    player said.

    So `drink#direct` and `drink#source` are two rules, while a flammable
    bottle and a plain one still share both. Role names are a closed set of
    five and most verbs are typed one or two ways, so this costs a fraction
    of what affordances cost and buys back the distinction that matters.
    """
    shape = ",".join(sorted(bound or {}))
    return f"{verb}#{shape}" if shape else verb


# ---------------------------------------------------------------------------
# What belongs in a name, and what belongs in a state
# ---------------------------------------------------------------------------

#: The rule, for every generator that can name a thing.
#:
#: One text in one place because four of them can: a room's contents, a
#: fixture reached for, a character's outfit, and a verb that conjures
#: something. A name written by one of them and a state changed by another
#: have to agree, and they only agree if all four were told the same rule.
_NAMING_RULE = """\
A name says what a thing IS. Its condition goes in "states", never in the
name, and never in the description either.

Both are written once and shown for the rest of the object's life, while what
is true of the thing changes underneath them. Drink a "half-empty bottle" and
the world marks it empty -- and it is still called a half-empty bottle, and
still described as half full, and nothing can put either right. States are
the part that is allowed to change, which is why every passing condition
belongs there and nowhere else.

The test is whether anything anybody could do here would make the word wrong.
If it would, it is a state: how full, lit, clean, broken, wet, open, locked,
worn or fresh a thing is -- half-empty, empty, full, lit, unlit, burning,
dirty, dusty, muddy, wet, damp, dry, broken, cracked, torn, stained, locked,
unlocked, open, shut, used, spoiled.

What stays is what will still be true when all of that has changed: material,
colour, shape, make, purpose, whose it is. "glass soju bottle", not
"half-empty soju bottle". "canvas satchel", not "torn canvas satchel" -- put
"torn" in states, where mending it can undo it. Describe the thing itself the
same way: what it is made of and what it is for, not how much is left in it.
"""


def naming_rule():
    """How to name a made thing, for any generator that makes one."""
    return _NAMING_RULE


def name_contradicts_states(name, states, world_root=None):
    """
    Words in a name that the rule above says belong in states instead.

    The rule is easy to state and easy for a generator to drift away from, and
    the damage is silent: a "Stained Slate Chalkboard" can be wiped clean and
    goes on being called stained forever, because a name is written once and
    shown for the rest of the object's life. Nothing here can repair that --
    renaming a thing after the fact breaks every alias anybody has learned for
    it -- so this reports rather than corrects, and what it is for is noticing
    that a prompt has started to slip.

    Two things count, and neither is a guess:

    * A word in both the name and this object's own states. That is the model
      contradicting itself inside one reply, and needs no world to detect.

    * A word in the name that this world has already registered as a state.
      By then some verb is able to change the condition, and the name is
      welded against it.

    Note what is deliberately NOT consulted: whether the word is an adjective.
    It sounds like the test and it is the wrong one in both directions. Half
    the words it catches are perfectly good names -- "wooden", "ornate",
    "sturdy" and "tiny" are adjectives and can be nothing else -- while half
    the conditions this rule exists to catch are ordinary nouns, "wet",
    "burning" and "open" among them, which is to say most of the list the rule
    itself prints. What makes a word wrong here is that it names something
    changeable, and the state vocabulary is the only place this game says
    which words those are.
    """
    words = {w for w in re.findall(r"[a-z0-9]+", (name or "").lower())}
    if not words:
        return []

    own = {str(s).lower().strip() for s in (states or []) if s}
    registered = set(DEFAULT_STATE_GROUP) | set(vocabulary(world_root))
    return sorted(words & (own | registered))


#: Which condition words in a thing's name it has already been given, so that
#: a state taken away later is not handed straight back by the name.
NAMED_STATES = "name_states_considered"


def adopt_named_states(obj, world_root=None):
    """
    Put a thing into the conditions its own name says it is in. Returns what
    was added.

    Found in playtesting. A "Wax-Sealed Glass Vial" was made in a world that
    had no `sealed` yet; ten minutes later somebody tried to unseal it, the
    rule written for that introduced `sealed` and required it -- rightly --
    and the vial was refused: "Wax-sealed glass vial is not sealed." The
    naming rule asks generators to keep conditions out of names, and
    `name_contradicts_states` only reports when they do not, because a name
    cannot be repaired. But the state can be: whatever the name says is true
    of the thing from the moment this world knows the word as a condition.

    So this is asked when a thing is made and again whenever it is acted on,
    before any check is read -- which is what catches a condition a rule has
    only just introduced.

    **Once per word.** Each condition word in the name is considered a single
    time and remembered, so a vial that has since been unsealed stays unsealed
    however often it is picked up afterwards.

    **Things only, and not conditions that belong to people.** A person's name
    is not a claim about them, and a group that ends when somebody walks away
    or stops them acting is about people: a sleeping bag is not asleep and a
    standing stone is not standing. Names only, never descriptions: "stoppered
    with a wax-dipped cork" says too little too loosely to act on.
    """
    from world import relations

    if obj is None or world_root is None:
        return []
    try:
        if not relations._is_thing(obj):
            return []
        considered = set(getattr(obj.db, NAMED_STATES, None) or [])
    except AttributeError:
        return []

    words = set(re.findall(r"[a-z0-9]+", str(getattr(obj, "key", "")).lower()))
    registered = set(DEFAULT_STATE_GROUP) | set(vocabulary(world_root))
    fresh = sorted((words & registered) - considered)
    if not fresh:
        return []
    setattr(obj.db, NAMED_STATES, sorted(considered | set(fresh)))

    held = states(obj)
    missing = [slug for slug in fresh
               if slug not in held and not _about_people(world_root, slug)]
    if missing:
        apply_states(obj, add=missing, world_root=world_root, announce=False)
        logger.log_info(f"states: {obj.key} is {', '.join(missing)}, as its "
                        f"name says")
    return missing


def _about_people(world_root, slug):
    """Whether a condition belongs to people: it ends on moving or stops acting."""
    rules = group_rules(world_root, group_of(world_root, slug))
    return any(rules.get(flag) for flag in
               ("ends_on_move", "prevents_acting", "prevents_moving",
                "prevents_speaking"))


# ---------------------------------------------------------------------------
# What the game already answers for itself
# ---------------------------------------------------------------------------

_ENGINE_RULE_HEAD = """The game already answers these verbs itself, and the
list is all of them -- read off the running game rather than remembered:

"""

_ENGINE_RULE_TAIL = """

Treat that list as closed, in both directions. A verb ON it is not yours to
define: mark it invalid. A verb NOT on it IS yours, however much it resembles
one that is -- "handhold" is not "hold", "embrace" is not "wear", "pull" is
not "get". Never refuse a verb on the grounds that the engine probably
handles it, or that it sounds like the sort of thing an engine would: if it
is not listed above then nothing handles it, and refusing it leaves this
world with no way to perform the action at all.
"""

#: Worked out once. The command set cannot change without a reload and the
#: modules below are read at import, so there is nothing here that can go
#: stale within the life of one server.
_ENGINE_VERBS = None

#: The half of `engine_verbs` that the command set really answers, as opposed
#: to the half handled inside the attempt pipeline by clothing, gear and
#: placement. Filled in alongside it.
#:
#: The distinction is not academic. Handing a verb to the command set that the
#: command set does not know sends it straight back out as an unknown command,
#: which reaches the attempt pipeline again, which hands it over again. Typing
#: "study scroll" did exactly that: "study" folds to "look", "look" is an
#: engine verb, and "study" is not a command -- so the two bounced it between
#: them for ever and the player was told they were still trying.
_COMMAND_VERBS = set()

#: Verbs with a command of their own that the attempt pipeline owns anyway.
#:
#: `look` is a command, because typing it is how a player looks. What looking
#: MEANS is a world's business -- whether the cave is dark, whether the ghost
#: needs the right spectacles, whether the moon may be looked at without being
#: touched -- and none of that could be said while the pipeline handed the verb
#: straight back to `CmdAILook`. See docs/rulebooks-from-inform.md 8.1.
#:
#: `give` is the same case arrived at from the other end. Evennia ships a give
#: command and this game replaces it with one that hands the sentence to the
#: pipeline, because giving is where ownership moves and because Evennia's
#: cannot resolve "give it to her". Handing the verb back would therefore hand
#: it to our own command, which would hand it here again -- the bounce above,
#: with both ends inside this game.
#:
#: Canonical verbs only. Everything folds through `VERB_SYNONYMS` before this is
#: consulted, so one entry covers `l`, `x`, `examine`, `inspect`, `study` and
#: `view`, and adding the spellings separately would be six chances to miss one.
PIPELINE_VERBS = frozenset(["look", "give"])


def reserves_word(command):
    """
    Whether a command's name is a verb the engine owns.

    Read off the command's own `reserves_word` flag. A command that does not
    say -- every one of Evennia's -- falls back to its help category, where
    "General" is the playing commands (look, get, say) and everything else is
    building or bookkeeping. The flag exists for the commands that category
    got wrong: the verb commands are filed under World, and must not reserve
    "reset" or "view" however they are filed, because a world may still write
    rules for them. docs/commands-and-settings.md §2.
    """
    flagged = getattr(command, "reserves_word", None)
    if flagged is not None:
        return bool(flagged)
    return (getattr(command, "help_category", "") or "").lower() == "general"


def command_verbs():
    """The verbs the command set itself answers, by a name it will recognise."""
    engine_verbs()
    return _COMMAND_VERBS


def engine_verbs():
    """
    Every verb the game itself answers, read off the running game.

    Two sources, because there are two ways a verb never reaches a model: a
    real command in the character's command set, and the four modules that
    take a verb over inside the attempt pipeline when the nouns suit --
    wearing, wielding, putting one thing on another, and handing one to
    somebody.

    Read rather than written out here. A hand-written list is one that goes
    quietly stale: the day somebody adds a command or aliases one, a prompt
    saying otherwise starts teaching a model something false, and nothing
    fails loudly enough for anyone to notice.

    Only commands that reserve their word are offered (`reserves_word`), which
    for Evennia's own means the "general" category. Building, admin and system
    commands are staff tools no verb rule could be mistaken for, and putting
    @teleport in front of a model deciding what "kiss" means is only noise.
    """
    global _ENGINE_VERBS
    if _ENGINE_VERBS is not None:
        return _ENGINE_VERBS

    from world import clothing, gear, ownership, relations

    found = set()
    for module in (clothing, gear, ownership, relations):
        found.update(str(verb) for verb in getattr(module, "VERBS", ()))

    try:
        from commands.default_cmdsets import CharacterCmdSet

        cmdset = CharacterCmdSet()
        cmdset.at_cmdset_creation()
    except Exception as exc:
        # Worth saying out loud rather than degrading in silence. The prompt
        # goes out either way, and one built from the intercepts alone will
        # let through rules for verbs the game already answers.
        logger.log_info(f"verbs: could not read the command set: {exc}")
        _ENGINE_VERBS = sorted(found)
        return _ENGINE_VERBS

    for command in cmdset.commands:
        if not reserves_word(command):
            continue
        for name in [command.key] + list(command.aliases or []):
            spelled = str(name or "")
            if spelled[:1].isalpha():
                _COMMAND_VERBS.add(spelled)
        for name in [command.key] + list(command.aliases or []):
            # Punctuation aliases -- the quote mark for say, the colon for
            # pose -- are not verbs anybody would write a rule for, and one
            # sitting in a list of words reads as a typing mistake.
            name = str(name or "")
            if name[:1].isalpha():
                found.add(name)

    # A verb is folded onto its canonical form before anybody is asked about
    # it, so "grab" arrives as "get" and is answered by the engine under a
    # name the player never typed. Those spellings are engine verbs too, and
    # a list that left them out would be inviting a rule for one of them.
    # Only the ones landing on a verb already found: "tug" folds to "pull",
    # which nothing handles, so tug stays free.
    for spelling, canonical in VERB_SYNONYMS.items():
        if canonical in found:
            found.add(spelling)

    _ENGINE_VERBS = sorted(found)
    return _ENGINE_VERBS


def engine_command_block():
    """
    The closed list of engine verbs, for a prompt that must not redefine one.

    This exists because "the engine probably handles that" is a guess, and a
    model left to make it makes it by resemblance. Told in prose that wearing
    and wielding are handled, it went on to refuse get, give, pull and -- the
    one that actually cost us -- handhold, on the grounds that holding a thing
    in your hands is surely a mechanic too. Every one of those was a rule the
    world then could not write and an action nothing could perform. A list
    turns the guess into a lookup.
    """
    return (_ENGINE_RULE_HEAD + "  " + ", ".join(engine_verbs())
            + _ENGINE_RULE_TAIL)


# ---------------------------------------------------------------------------
# The world's state vocabulary
# ---------------------------------------------------------------------------

def vocabulary(world_root):
    """{slug: {"means": str, "conflicts": [slug, ...]}} for this world."""
    return dict(world_root.db.state_vocabulary or {}) if world_root else {}


# ---------------------------------------------------------------------------
# States that are worked out rather than written
# ---------------------------------------------------------------------------
#
# A state in the register may carry a `when`: the conditions under which it
# holds. It is never written onto anything. `implied_states` works it out, as
# it already works out that a character nothing has killed is alive. So
# "starving" is defined once, as hunger at 10 or less, and every rule, goal and
# refusal that cares asks `is: ["starving"]` and never mentions the number.
#
#   A state persists until something changes it. A derived state holds exactly
#   while its conditions do. A trait modifier persists only while its source
#   does.
#
# Death is not derived, because it is sticky: healing a corpse to 1 health
# should not raise it. See docs/becoming-and-time.md §5.

#: How many derived states deep a definition may reach: "exhausted" meaning
#: "tired and starving" is two. Past this, a derived state is simply not true,
#: which is a guard rather than a limit -- `register_state` refuses a cycle.
MAX_DERIVED_DEPTH = 3

_DERIVING = threading.local()


def _definition(entry):
    """A register entry's `when`, as a list, or [] for a written state."""
    try:
        when = entry.get("when")
    except AttributeError:
        return []
    return list(when) if when else []


def derived_states(world_root):
    """{slug: entry} for every state this world works out rather than writes."""
    return {slug: entry for slug, entry in vocabulary(world_root).items()
            if _definition(entry)}


def is_derived(world_root, slug):
    """True for a state that is worked out, and so can never be set."""
    entry = vocabulary(world_root).get(str(slug or "").lower().strip())
    return bool(entry) and bool(_definition(entry))


def derived_holds(obj, world_root, only=None):
    """
    The derived states true of `obj` now, of those named in `only` or of all.

    A definition is asked about the thing whose state it is: `direct` is the
    thing, and so is `actor` when the thing is a person, so a definition reads
    the same written either way.
    """
    found = set()
    if obj is None or world_root is None:
        return found
    derived = derived_states(world_root)
    if only is not None:
        derived = {slug: entry for slug, entry in derived.items()
                   if slug in only}
    if not derived:
        return found
    depth = getattr(_DERIVING, "depth", 0)
    if depth >= MAX_DERIVED_DEPTH:
        return found

    from world import conditions
    from world.quests import is_person

    ctx = conditions.context({"direct": obj},
                             obj if is_person(obj) else None, world_root)
    _DERIVING.depth = depth + 1
    try:
        for slug, entry in derived.items():
            if all(conditions.evaluate(c, ctx) for c in _definition(entry)):
                found.add(slug)
    finally:
        _DERIVING.depth = depth
    return found


# ---------------------------------------------------------------------------
# States that are worth something to a person's figures
# ---------------------------------------------------------------------------

def _clean_bonuses(bonuses):
    """{trait slug: amount}, with anything that is not a number left out."""
    clean = {}
    try:
        items = dict(bonuses or {}).items()
    except (TypeError, ValueError):
        return clean
    for trait, amount in items:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            continue
        name = str(trait or "").strip().lower()
        if name and amount:
            clean[name] = amount
    return clean


def set_bonuses(world_root, slug, bonuses):
    """
    Say what being in a state is worth to a person's figures.

    Kept on the state's register entry, the same shape an item's
    `trait_bonuses` has, and summed by `gear.total` from scratch like the
    rest: "starving costs 3 strength" is said once, on `starving`, and taking
    away the hunger takes away the cost with no accounting kept anywhere.
    An empty map takes the bonuses away. Returns the map as stored.
    """
    vocab = vocabulary(world_root)
    if not world_root or slug not in vocab:
        return {}
    entry = dict(vocab[slug] or {})
    clean = _clean_bonuses(bonuses)
    if clean:
        entry["bonuses"] = clean
    else:
        entry.pop("bonuses", None)
    vocab[slug] = entry
    world_root.db.state_vocabulary = vocab
    return clean


def state_bonuses(world_root):
    """{state: {trait: amount}} for every state that is worth something."""
    found = {}
    for slug, entry in vocabulary(world_root).items():
        try:
            clean = _clean_bonuses(entry.get("bonuses"))
        except AttributeError:
            continue
        if clean:
            found[slug] = clean
    return found


def _worded_definition(definition):
    """A derived state's definition as it reads, with nothing to evaluate."""
    from world import conditions

    return " and ".join(said for said in (conditions.describe(c)
                                         for c in definition) if said)


def _refers_to(entry, derived):
    """The derived states a definition asks about by name."""
    from world import conditions
    from world.model_json import listed

    named = set()
    for top in _definition(entry):
        for leaf, _optional in conditions.leaves(top):
            for field in ("is", "lacks"):
                named |= {str(s).lower() for s in listed(leaf.get(field))
                          if str(s).lower() in derived}
    return named


def _makes_a_cycle(vocab, slug):
    """Whether `slug`'s definition reaches back to `slug` through others."""
    derived = {s: e for s, e in vocab.items() if _definition(e)}
    seen, waiting = set(), list(_refers_to(derived.get(slug), derived))
    while waiting:
        name = waiting.pop()
        if name == slug:
            return True
        if name in seen:
            continue
        seen.add(name)
        waiting.extend(_refers_to(derived.get(name), derived))
    return False


def _derive(world_root, slug, when, means="", group=None):
    """
    Register a state that is worked out from `when`. Returns the slug, or "".

    Refused, with the reason logged, when the definition asks nothing, when
    the word is already a written state, when it would make a cycle, and when
    its group already holds written members: exclusivity is enforced when a
    state is written, and a derived one never is, so a mixed group could be
    `fed` and `starving` at once.
    """
    from world import conditions
    from world import vocabulary as _vocabulary
    from world.model_json import listed

    kept, refused = conditions.normalise_all(listed(when))
    if refused or not kept:
        logger.log_info(f"states: {slug!r} not derived: its definition asks "
                        f"nothing that can be tested")
        return ""

    vocab = vocabulary(world_root)
    existing = vocab.get(slug)
    if existing is None:
        for other, entry in vocab.items():
            if not _similar(slug, other):
                continue
            if _definition(entry):
                return other     # another spelling of a derived state
            logger.log_info(f"states: {slug!r} not derived: {other!r} is "
                            f"already a state that is set, not worked out")
            return ""
    elif not _definition(existing):
        logger.log_info(f"states: {slug!r} not derived: it is already a state "
                        f"that is set, not worked out")
        return ""

    if not _vocabulary.permit(world_root, slug, "state"):
        return ""

    if group:
        group = register_group(world_root, group)
        written = {member for member in group_members(world_root, group)
                   if member != slug and not is_derived(world_root, member)}
        if written:
            logger.log_info(
                f"states: {slug!r} not derived: group {group!r} already holds "
                f"states that are set ({', '.join(sorted(written))})")
            return ""

    entry = {"means": str(means or (existing or {}).get("means") or ""),
             "conflicts": [], "group": group or "", "when": kept}
    trial = dict(vocab)
    trial[slug] = entry
    if _makes_a_cycle(trial, slug):
        logger.log_info(f"states: {slug!r} not derived: its definition leads "
                        f"back to itself")
        return ""
    world_root.db.state_vocabulary = trial
    return slug


def _similar(a, b):
    """Crude overlap test, to fold 'soaked' into an existing 'wet'."""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    return a.startswith(b) or b.startswith(a)


#: What a group is taken to mean when nobody has said otherwise.
#:
#: Exclusive by default, and that default is the whole point: a group IS a set
#: of states only one of which can hold at once -- it is what every prompt that
#: can invent one is told a group is. A model that declares "openness" for open
#: and closed has already said what it means, and treating an unrecognised name
#: as a loose flag threw that away, so a thing could be open and closed at the
#: same time and opening it cleared nothing.
NEW_GROUP = {"exclusive": True, "ends_on_move": False,
             "prevents_acting": False, "prevents_moving": False,
             "prevents_speaking": False, "default": ""}

#: Groups every world starts with, and how they behave.
#:
#: exclusive    -- only one member can be true of a thing at a time, so
#:                 sitting down stops you standing without any rule saying so.
#: ends_on_move -- walking out of the room ends it. You cannot carry a chair
#:                 away by remaining seated on it.
#:
#: The last three are what a state does to whoever is IN it, rather than what
#: it says about them. Three and no more, and never a list of forbidden verbs:
#: a state is settled once and never revised, while the verb vocabulary grows
#: for as long as a world runs, so a list written when "gagged" was coined
#: cannot mention singing, chanting or reciting and gets staler every day. A
#: gate is closed and total instead -- everything is an action, so acting
#: covers the verbs nobody has invented yet.
#:
#: prevents_acting   -- a dead thing does not go on about its business.
#: prevents_moving   -- you cannot walk away tied to a chair.
#: prevents_speaking -- a gagged mouth makes no dialogue.
#:
#: These are seeds rather than the whole list. A world registers its own as it
#: needs them -- see `register_group` -- and what is here is only what no world
#: should have to discover for itself: `ends_on_move` in particular is not
#: something a model reliably works out, and getting it wrong means a character
#: who stays seated in every room they walk into.
STATE_GROUPS = {
    # Sitting ends when you walk rather than stopping you walking, which is
    # the difference between a posture and a restraint: standing up is part of
    # leaving. `bonds` is the other half of that, seeded because a world that
    # ties somebody up and then lets them stroll off has wasted the rope.
    "posture": {"exclusive": True, "ends_on_move": True},
    "wetness": {"exclusive": True, "ends_on_move": False},
    "fire":    {"exclusive": True, "ends_on_move": False},
    # `default` is the member a thing is in until something puts it in another,
    # and it is the answer to a fault that turned up in play: a rule required
    # the target of `greet` to be `alive`, nothing anywhere sets `alive`, and so
    # every character in the world was refused as not being alive.
    #
    # The state could have been written on to each character at creation, and
    # should not be. Being alive is not a fact worth storing -- it is what is
    # true of anything nothing has killed -- and storing it would print "Rina is
    # alive" under every look, need backfilling on to every character that
    # already exists, and drift the first time something forgot to set it. An
    # implied default has none of those problems and costs one lookup.
    #
    # It also attacks a measured fault from the other end. 45 of 62 states in
    # the exported corpus can be set and never unset, and a group with a default
    # is a group whose other end always exists: `dead` cancels `alive` by
    # exclusivity, and removing `dead` puts it back with no rule needed.
    "life_status": {"exclusive": True, "prevents_acting": True,
                    "prevents_moving": True, "prevents_speaking": True,
                    "default": "alive"},
    "bonds":   {"exclusive": True, "prevents_moving": True},
    "gagged":  {"exclusive": True, "prevents_speaking": True},
}

#: Where a state belongs when nothing says otherwise. Seeded for the ones a
#: world is certain to invent, so posture is exclusive from the first use
#: rather than from whenever a model happens to declare it -- left to itself
#: it decided "seated" ruled out "following" and "mobile", neither of which
#: anything sets, and said nothing about standing.
#:
#: A seeded slug keeps its seeded group even when a model declares another,
#: which is what stops "wet" being filed under an invented "moisture" while
#: "dry" sits in "wetness" -- two groups for one question, and neither
#: cancelling the other.
DEFAULT_STATE_GROUP = {
    slug: "posture" for slug in (
        "seated", "sitting", "sat", "standing", "stood", "upright",
        "lying", "lain", "laid", "prone", "supine", "reclining", "reclined",
        "kneeling", "knelt", "crouching", "crouched", "perched", "sprawled",
    )
}
DEFAULT_STATE_GROUP.update({
    slug: "wetness" for slug in ("wet", "soaked", "damp", "dry", "sodden")
})
DEFAULT_STATE_GROUP.update({
    slug: "fire" for slug in ("burning", "alight", "lit", "extinguished", "unlit")
})
DEFAULT_STATE_GROUP.update({
    slug: "life_status" for slug in ("dead", "slain", "killed", "deceased",
                                     "lifeless", "alive", "living")
})
DEFAULT_STATE_GROUP.update({
    slug: "bonds" for slug in ("bound", "tied", "shackled", "chained",
                               "manacled", "pinned", "trapped", "free")
})
DEFAULT_STATE_GROUP.update({
    slug: "gagged" for slug in ("gagged", "muzzled", "muted", "silenced")
})


def _similar_group(name, other):
    """
    Whether two group names are the same question asked twice.

    A prefix test catches "open" against "openness". It cannot catch
    "openess", which is the commoner miss by far -- a model writing a group
    name is writing prose, not choosing from a list -- so one edit counts as
    the same name too. Short names are left alone: "fire" and "hire" are one
    edit apart and are not the same question.
    """
    if _similar(name, other):
        return True
    from world.naming import edit_distance

    return min(len(name), len(other)) >= 5 and edit_distance(name, other) <= 1


def groups(world_root):
    """Every group this world knows: the seeds, then whatever it has added."""
    merged = {name: dict(rules) for name, rules in STATE_GROUPS.items()}
    stored = (world_root.db.state_groups or {}) if world_root else {}
    for name, rules in stored.items():
        merged.setdefault(name, {}).update(dict(rules or {}))
    return merged


def group_rules(world_root, group):
    """
    How a group behaves.

    A group nobody registered still behaves as a group. That is the safety
    net under the register rather than a substitute for it: a rule can name a
    group in an effect long before anything writes it down, and the answer to
    "what does this unrecognised group do?" is what a group does.
    """
    if not group:
        return {}
    return groups(world_root).get(group) or dict(NEW_GROUP)


#: The three things a state can stop somebody doing, and how to say so.
#:
#: The wording is built from the slug because the slugs are already adjectives
#: -- dead, tied, gagged, sitting -- so "You cannot move while tied" falls out
#: without anybody writing a sentence for it. A state whose slug does not read
#: that way still gets an honest line, just a duller one.
GATES = {
    "prevents_acting": "do that",
    "prevents_moving": "move",
    "prevents_speaking": "speak",
}


def blocked(character, gate, world_root=None):
    """
    The state stopping this character, or "" if nothing is.

    One question asked in three places -- before an action, before a step,
    before a word -- because a state that stops you doing something has to
    stop the player and the character alike, and neither of them should be
    asked a different question.

    Cheap enough to ask on every movement and every line of dialogue: a set
    intersection against the states already on the object, and a dict lookup
    per group.

    A derived state stops somebody too when its group says so, and is worked
    out for this only: nothing derived is evaluated unless its group gates
    this very thing, so a world whose derived states gate nothing asks nothing
    it did not ask before.
    """
    if character is None or gate not in GATES:
        return ""
    held = states(character)
    if world_root is None:
        room = getattr(character, "location", None)
        world_root = getattr(getattr(room, "db", None), "world_root", None)
    gating = _derived_gating(world_root, gate)
    if gating:
        held = held | derived_holds(character, world_root, only=gating)
    if not held:
        return ""
    known = groups(world_root)
    for slug in sorted(held):
        group = group_of(world_root, slug)
        if not group:
            continue
        rules = known.get(group) or STATE_GROUPS.get(group) or {}
        try:
            if rules.get(gate):
                return slug
        except AttributeError:
            continue
    return ""


def _derived_gating(world_root, gate):
    """The derived states whose group stops its holder doing `gate`."""
    derived = derived_states(world_root)
    if not derived:
        return set()
    known = groups(world_root)
    found = set()
    for slug, entry in derived.items():
        try:
            group = entry.get("group") or ""
        except AttributeError:
            continue
        rules = known.get(group) or STATE_GROUPS.get(group) or {}
        if group and rules.get(gate):
            found.add(slug)
    return found


def refuse(character, gate, world_root=None):
    """
    What to tell somebody who cannot do this, or "" when they can.

    Second person because both halves of the game need it: a player is told
    directly, and a character is told the same words as a thing it noticed,
    which is what stops it trying again every turn for as long as the state
    lasts.
    """
    slug = blocked(character, gate, world_root)
    if not slug:
        return ""
    return f"You cannot {GATES[gate]} while {slug.replace('_', ' ')}."


def register_group(world_root, group, default=None, exclusive=None,
                   ends_on_move=None,
                   prevents_acting=None, prevents_moving=None,
                   prevents_speaking=None):
    """
    Put a group in the world's register, or fold it onto one already there.

    Returns the name actually in use, which may not be the one asked for --
    and every caller must store what comes back, or the fold achieves nothing
    and the world ends up with "openness" and "open_state" both half-working.

    Only what is explicitly passed overrides what is already known, so
    registering a group a second time to note a member does not silently
    reset how it behaves.
    """
    group = re.sub(r"[^a-z0-9_]", "", str(group or "").lower().strip())
    if not group:
        return ""
    if world_root is None:
        return group

    known = groups(world_root)
    if group not in known:
        for existing in known:
            if _similar_group(group, existing):
                group = existing
                break

    entry = dict(known.get(group) or NEW_GROUP)
    if default is not None:
        entry["default"] = str(default or "")
    if exclusive is not None:
        entry["exclusive"] = bool(exclusive)
    if ends_on_move is not None:
        entry["ends_on_move"] = bool(ends_on_move)
    for name, given in (("prevents_acting", prevents_acting),
                        ("prevents_moving", prevents_moving),
                        ("prevents_speaking", prevents_speaking)):
        if given is not None:
            entry[name] = bool(given)
        entry.setdefault(name, False)

    stored = dict(world_root.db.state_groups or {})
    if stored.get(group) != entry:
        was_new = group not in known
        stored[group] = entry
        world_root.db.state_groups = stored
        if was_new:
            logger.log_info(
                f"states: {world_root.key} learned group {group!r} "
                f"({'exclusive' if entry['exclusive'] else 'loose'}"
                f"{', ends on move' if entry['ends_on_move'] else ''})"
            )
    return group


def group_of(world_root, slug):
    """
    Which group a state belongs to, or None.

    The seed is consulted before what was declared, not after. A model naming
    the group for "wet" is guessing at a question this file has already
    answered, and the two answers disagreeing is worse than either.
    """
    seeded = DEFAULT_STATE_GROUP.get(slug)
    if seeded:
        return seeded
    entry = vocabulary(world_root).get(slug) or {}
    try:
        return entry.get("group") or None
    except AttributeError:
        return None


def group_members(world_root, group):
    """Every state known to belong to `group`."""
    if not group:
        return set()
    known = {slug for slug, g in DEFAULT_STATE_GROUP.items() if g == group}
    for slug in vocabulary(world_root):
        if group_of(world_root, slug) == group:
            known.add(slug)
    return known


#: How English spells "not this". Ordered longest first so "non" is tried
#: before "no" would be, and kept short: these are the four that actually turn
#: a condition into its opposite rather than merely starting a word with them.
_NEGATING = ("non", "dis", "un", "in", "im")


def _opposite_group(world_root, slug, vocab):
    """
    The group of a state this one is the plain negation of, if there is one.

    Only when the other half is ALREADY registered, which is what makes this
    safe to act on without a dictionary: "unfolded" is only read as the
    opposite of "folded" in a world that has met a folded thing. Nothing is
    inferred about English, so "inert" cannot become "not ert" and "impassive"
    cannot become "not passive" -- there is no state called ert or passive to
    be the other half of.

    WordNet is deliberately not consulted here, and it is worth saying why,
    because antonymy looks like exactly the right relation. Its antonyms run
    lemma to lemma, and the participles these states are made of are not their
    own lemmas: it gives "fold" for "unfolded", "lighted" for "unlit", "tune"
    for "untuned" and nothing at all for "untransformed". It knows the pairs
    this cannot reach -- open and closed, wet and dry -- and misses every pair
    this catches, while cheerfully reporting that the opposite of "broken" is
    "promote".
    """
    for prefix in _NEGATING:
        if not slug.startswith(prefix):
            continue
        positive = slug[len(prefix):]
        if len(positive) < 3 or positive not in vocab:
            continue
        found = group_of(world_root, positive)
        if found:
            return found
    return None


def _adjective_senses(slug):
    """
    A state word's adjective senses, or [] when there is no dictionary.

    Adjectives only, and that restriction is the whole reason the relations
    below are usable. Asked without it, WordNet reports that the opposite of
    "broken" is "conform_to", "keep", "make" and "promote" -- all of them
    perfectly good antonyms of the verb "to break", and none of them a way for
    a thing to be. Filtered to how a word describes something rather than how
    it acts, the noise disappears entirely.
    """
    from world import lexicon

    wordnet = lexicon._wordnet()
    if wordnet is None:
        return []
    try:
        return [s for s in wordnet.synsets(slug) if s.pos() in ("a", "s")]
    except Exception:
        return []


def _antonym_group(world_root, slug, vocab):
    """
    The group of a state this one is the opposite of.

    The most clearly correct of the three checks here, because a group is a
    set of states only one of which can hold at once, and that is precisely
    what an opposite is. Wet and dry are not two conditions that happen to
    conflict; being one is what it means not to be the other.

    It also reaches the pairs the other two cannot. Neither spelling nor
    synonymy connects open to closed, wet to dry, clean to dirty, full to
    empty or seated to standing -- and those are the ordinary furniture of a
    world's vocabulary. Of eight such pairs across five worlds, seven were
    already grouped correctly and the eighth, active against dormant, was not.
    """
    found = set()
    for sense in _adjective_senses(slug):
        try:
            for lemma in sense.lemmas():
                for other in lemma.antonyms():
                    found.add(other.name().lower())
        except Exception:
            continue
    for other in found & set(vocab):
        group = group_of(world_root, other)
        if group:
            return group
    return None


def _synonym_group(world_root, slug, vocab):
    """
    The group of a state that means the same thing as this one.

    Five worlds coined "shut" while already keeping "closed", and "dormant"
    while already keeping "inactive". Nothing noticed, because folding on the
    way in compares spellings -- "emptied" collapses onto "empty" and "shut"
    does not collapse onto anything.

    The slugs are NOT merged, which is the important part. WordNet also calls
    "broken" and "crushed" synonyms, and a world where a crushed thing is
    simply a broken one has lost a distinction worth having; sense overlap
    does not separate the good pairs from that one, since "closed" and "shut"
    share as little as "broken" and "crushed" do.

    What is safe is the weaker claim: two states that mean the same thing must
    at least rule each other out. So a synonym joins the group rather than the
    slug -- which fixes dormant against inactive, leaves shut and closed where
    they already were, and does the right thing by broken and crushed, since
    those genuinely are two ways for one thing to be damaged.
    """
    kin = set()
    for sense in _adjective_senses(slug):
        try:
            kin |= {name.lower() for name in sense.lemma_names()}
        except Exception:
            continue
    kin.discard(slug)
    for other in kin & set(vocab):
        found = group_of(world_root, other)
        if found:
            return found
    return None


def _commonsense_group(world_root, slug, vocab):
    """
    The group an outside corpus thinks this state belongs with, or None.

    `DistinctFrom` is definitionally what a group is -- "something that is A is
    not B" -- so ConceptNet knows the ordinary pairs, open/closed, wet/dry,
    locked/unlocked, that nobody should have to declare by hand.

    **Ranked last on purpose, and behind a declaration rather than in front of
    it.** The three tests above may overrule a declared group, and they have
    earned that: spelling is certain, and WordNet is curated and
    sense-disambiguated. This corpus is crowdsourced and its nodes are words
    rather than senses, which is exactly why 7.1 says it may never hold a
    position it can win from -- never a floor, never against what somebody
    actually wrote down. So it only ever fills a silence.

    The pair still has to be in this world. A world that has never heard of
    `closed` gets no group for `open` out of this, for the same reason every
    suggestion in this project wants evidence from the world it is about.
    """
    from world import commonsense

    for other in commonsense.opposites(slug):
        other = _slug_state(other)
        if not other or other == slug or other not in vocab:
            continue
        found = group_of(world_root, other)
        if found:
            return found
    return None


def _slug_state(word):
    """A word as a state slug: lower case, underscores, nothing else."""
    import re

    found = re.sub(r"[^a-z0-9_]+", "_", str(word or "").lower().strip())
    return found.strip("_")


def register_state(world_root, slug, means="", conflicts=(), group=None,
                   ends_on_move=None, prevents_acting=None,
                   prevents_moving=None, prevents_speaking=None, when=None,
                   bonuses=None):
    """
    Add a state to the world's vocabulary, or fold it onto an existing one.

    Returns the slug actually in use, which may not be the one asked for:
    keeping the vocabulary small is what stops a world accumulating damp,
    moist, soaked and wet as four unrelated conditions.

    `when` makes it a derived state: worked out from those conditions and
    never written. See `_derive` for what that refuses.

    `bonuses` is what being in it is worth to a person's figures --
    {"strength": -3} -- summed by `gear` beside what they carry. See
    `set_bonuses`.
    """
    if not world_root or not slug:
        return slug
    slug = re.sub(r"[^a-z0-9_]", "", slug.lower().strip())
    # A condition is never one letter. Whatever asked for this was reading a
    # word a character at a time, and the belt to `listed`'s braces: a world
    # in the first soak came out of an afternoon with d, e, h, s, t and x in
    # its vocabulary, none of which anything could mean or ever unset.
    if len(slug) < 2:
        return ""
    if when is not None:
        slug = _derive(world_root, slug, when, means, group)
        if slug and bonuses is not None:
            set_bonuses(world_root, slug, bonuses)
        return slug

    vocab = vocabulary(world_root)
    for existing in vocab:
        if _similar(slug, existing):
            if bonuses is not None:
                set_bonuses(world_root, existing, bonuses)
            return existing

    # The same guard traits keep, from the other side. See `world.vocabulary`.
    from world import vocabulary as _vocabulary

    if not _vocabulary.permit(world_root, slug, "state"):
        return ""

    # The group is registered before the state, so a state that names a new
    # group leaves behind a group that behaves like one. A seeded slug keeps
    # its seeded group whatever was declared -- see DEFAULT_STATE_GROUP.
    seeded = DEFAULT_STATE_GROUP.get(slug)
    # Three ways one state can belong with another, tried in order of how
    # certain they are. Spelling is certain: "unfolded" negates "folded" and
    # no dictionary is consulted. An opposite is the surest thing a dictionary
    # can tell us, since a group IS a set of mutually exclusive states. A
    # synonym is the weakest, and is acted on only as far as making two words
    # for one condition rule each other out.
    opposite = (_opposite_group(world_root, slug, vocab)
                or _antonym_group(world_root, slug, vocab)
                or _synonym_group(world_root, slug, vocab))
    if seeded:
        group = register_group(world_root, seeded)
    elif opposite:
        # A state spelled as the negation of one this world already keeps
        # belongs with it, whatever group was declared -- because the declared
        # group is the thing that goes wrong. Five worlds registered five such
        # pairs and put four of them together; the fifth had "folded" under
        # openness and "unfolded" under foldedness, which let a paper be both
        # at once with nothing able to put it right.
        group = register_group(world_root, opposite)
    elif group:
        group = register_group(world_root, group, ends_on_move=ends_on_move,
                               prevents_acting=prevents_acting,
                               prevents_moving=prevents_moving,
                               prevents_speaking=prevents_speaking)
    else:
        # Last of all, and only into a silence: a second corpus knows that open
        # and closed answer one question, and nobody here has said so. It is
        # placed after the declaration rather than among the three tests above
        # because those are allowed to overrule what was declared and this is
        # not -- see `_commonsense_group`.
        outside = _commonsense_group(world_root, slug, vocab)
        if outside:
            group = register_group(world_root, outside)

    if group and any(is_derived(world_root, member)
                     for member in group_members(world_root, group)
                     if member != slug):
        # A group holds derived members or written ones, never both: a written
        # member's exclusivity is enforced when it is set and a derived one is
        # never set. The state is still registered, just not into that group.
        logger.log_info(f"states: {slug!r} kept out of group {group!r}, whose "
                        f"members are worked out rather than set")
        group = ""

    vocab[slug] = {
        "means": means,
        "conflicts": [c for c in (conflicts or []) if c],
        "group": group or "",
    }
    world_root.db.state_vocabulary = vocab
    if bonuses is not None:
        set_bonuses(world_root, slug, bonuses)
    return slug


#: The category the state aliases are filed under, so they can be thrown away
#: and rebuilt without touching the aliases something else put there -- an
#: item conjured as a "Brass Orrery" answers to "astrolabe" because somebody
#: asked for one, and that must survive the bottle being emptied.
STATE_ALIAS = "state"


def implied_states(obj, world_root=None):
    """
    Everything true of a thing: what was written on it, plus group defaults.

    A group may name the member a thing is in until something puts it in
    another -- `life_status` defaults to `alive` -- and that member is implied
    rather than stored. So a character nothing has killed is alive without
    anybody writing it down, a character that has been killed is not, because
    `dead` is a member of the same group, and removing `dead` makes them alive
    again with no rule for it.

    Kept apart from `states`, which stays the record of what was actually
    written. The difference matters in exactly one place and it is a visible
    one: `condition` prints what a thing is, and printing "It is alive" under
    every character would be noise. What a *condition* tests is this.
    """
    now = set(states(obj))
    if world_root is None:
        # The same walk `blocked` does, and for the same reason: a caller deep
        # in a condition often has the thing and not the world it belongs to.
        room = obj if getattr(obj, "location", None) is None             else getattr(obj, "location", None)
        world_root = getattr(getattr(room, "db", None), "world_root", None)

    # Worked out before the defaults, so a derived member of a group with a
    # default is enough to keep the default from being implied beside it.
    now |= derived_holds(obj, world_root)

    # The built-ins as well as the register, because a world that has never
    # registered `life_status` still has characters in it, and the seeds are
    # exactly the groups no world should have to discover for itself.
    known = dict(STATE_GROUPS)
    known.update(groups(world_root) or {})
    for group, rules in known.items():
        try:
            fallback = str(rules.get("default") or "")
        except AttributeError:
            continue
        if not fallback:
            continue
        members = group_members(world_root, group) | {
            slug for slug, name in DEFAULT_STATE_GROUP.items()
            if name == group}
        if now & members:
            continue          # already in one of them; nothing to imply
        now.add(fallback)
    return now


def condition(obj, looker=None):
    """
    What is currently true of a thing, as a sentence, or "" if nothing is.

    Says the slugs rather than what they mean, because these are also the
    words the thing now answers to: a bottle that reads "It is empty" can be
    taken with "get empty bottle", and one that read "It is drained dry"
    could not. What you are shown and what you can type stay the same words.

    Derived states are said as well, unlike group defaults. "It is alive"
    under every character is noise; "You are starving" is exactly what a
    player needs to be told.
    """
    room = obj if getattr(obj, "location", None) is None \
        else getattr(obj, "location", None)
    world_root = getattr(getattr(room, "db", None), "world_root", None)
    current = sorted(states(obj) | derived_holds(obj, world_root))
    if not current:
        return ""
    from evennia.utils.utils import iter_to_str

    from world.quests import is_person

    # People are named; things are "it". Every Evennia object carries an
    # `account` attribute, so testing for one would call the bottle by name.
    subject = "It"
    if is_person(obj):
        subject = obj.get_display_name(looker) if looker else obj.key
    return f"{subject} is {iter_to_str(current)}."


def state_aliases(state, key):
    """
    The names one state lets a thing answer to.

    Three shapes, because there are three ways people type it. The state on
    its own is "drop empty". With the head noun is "get empty bottle", which
    is what anyone says who is not reading the full name off the screen. With
    the whole name is the exact phrase, and the one this world's own fuzzy
    matcher scores highest.
    """
    key = " ".join(str(key or "").split())
    aliases = {state}
    if key:
        head = key.split()[-1]
        aliases.add(f"{state} {head}")
        aliases.add(f"{state} {key}")
    return {a.lower() for a in aliases}


def refresh_state_aliases(obj):
    """
    Rebuild the names a thing answers to on account of its condition.

    Called wherever states change or a name does. Rebuilt wholesale rather
    than patched, because a state that has just been removed must stop
    matching: a bottle you have refilled should not still come when called
    "empty bottle", or the world fills up with things answering to what they
    used to be.
    """
    if obj is None:
        return []

    # Things only. People collect states faster than anything else -- damp,
    # seated, tipsy, holding_hands, all at once -- and letting each one become
    # a name would put a person into the running every time somebody reached
    # for a wet rag. Their condition is still shown when they are looked at;
    # it is only being addressable by it that does no good.
    from world.quests import is_person

    if is_person(obj):
        obj.aliases.clear(category=STATE_ALIAS)
        return []

    obj.aliases.clear(category=STATE_ALIAS)
    made = set()
    for state in states(obj):
        made |= state_aliases(state, obj.key)
    for alias in sorted(made):
        obj.aliases.add(alias, category=STATE_ALIAS)
    return sorted(made)


def apply_states(obj, add=(), remove=(), world_root=None, announce=True):
    """
    Change an object's condition, honouring declared conflicts.

    Adding "wet" removes "burning" without anyone having written that rule
    down here, because the conflict was declared when "wet" was registered.

    **One door, and it speaks.** `traits.adjust` has told a character about
    every figure that moved since traits existed, on the stated ground that a
    number which changes silently is not a trait anyone can play with. States
    are the other half of what is true of somebody and said nothing at all --
    so a player could be killed mid-sentence and read only the narration ("you
    lunge at them, they scramble onto the defensive"), and then meet a refusal
    on every verb afterwards for a reason nothing had ever told them.

    `announce` is for the one caller that is restoring a condition rather than
    causing one, where the character already knows.
    """
    from world.model_json import listed

    current = states(obj)
    before = set(current)
    # A derived state is worked out, never written: setting one would make it
    # true twice over for two reasons, and clearing one would leave its
    # definition still holding. So it is refused at the door every write comes
    # through, and said so where somebody can find it.
    derived = set(derived_states(world_root)) if world_root else set()

    # Through `listed`, because this is the innermost door every state comes
    # through: an effect written "add": "sharpened" rather than ["sharpened"]
    # was read a letter at a time and each letter registered as a condition of
    # its own. See `model_json.listed`.
    for slug in listed(remove):
        if slug in derived:
            logger.log_info(f"states: not clearing {slug!r} on {obj}: it is "
                            f"worked out, not set")
            continue
        current.discard(slug)
    for slug in listed(add):
        # Registered on the way in, so that every caller gets the same
        # guarantees rather than only the ones that remembered: a meaning, a
        # group, a help entry, and the fold that turns "soaked" into the "wet"
        # this world already has. Idempotent for a word already known, which
        # is why `effects.py` registering first as well costs nothing.
        slug = register_state(world_root, str(slug)) if world_root else slug
        if not slug:
            continue
        if slug in derived:
            logger.log_info(f"states: not setting {slug!r} on {obj}: it is "
                            f"worked out, not set")
            continue
        vocab = vocabulary(world_root)
        for conflict in vocab.get(slug, {}).get("conflicts", []):
            current.discard(conflict)
        # Everything in an exclusive group cancels everything else in it, so
        # sitting down ends standing whether or not anyone wrote that rule.
        group = group_of(world_root, slug)
        if group_rules(world_root, group).get("exclusive"):
            current -= (group_members(world_root, group) - {slug})
        current.add(slug)

    obj.db.states = sorted(current)
    refresh_state_aliases(obj)
    if announce:
        announce_states(obj, before, set(current), world_root)
    # A state that is worth something to a person's figures changes the sum
    # the moment it is set or ended. Only when one of those actually changed,
    # so the ordinary case costs one lookup.
    changed = before ^ set(current)
    if changed and world_root is not None and changed & set(
            state_bonuses(world_root)):
        from world import gear
        from world.quests import is_person

        if is_person(obj):
            gear.recompute(obj)
    return obj.db.states


def announce_states(obj, before, after, world_root=None):
    """
    Tell whoever this happened to what has changed about them.

    People only. There is nobody in a lantern to tell, and what the room sees
    a lantern do is the narration's business and is said there.

    A group with a `default` has an other end, and saying it is the whole
    difference between "you are no longer dead" and knowing you can act again.
    A state cancelled by an exclusive one that replaced it says nothing of its
    own: standing up has already been reported as standing up.

    Returns the plain sentences, which is also what a character is given: they
    read nothing, so the change reaches them as something they noticed.
    """
    from world.quests import is_person

    if obj is None or not is_person(obj):
        return []
    gained, lost = sorted(after - before), sorted(before - after)
    if not gained and not lost:
        return []

    vocab = vocabulary(world_root)

    def said(slug, colour):
        """The state as a phrase, with its meaning beside it when it has one."""
        word = str(slug).replace("_", " ")
        means = str((vocab.get(slug) or {}).get("means") or "").strip()
        if not means:
            return word
        return f"{word} |x({means})|n" if colour else f"{word} ({means})"

    def lines(colour):
        out = [f"You are now {said(slug, colour)}." for slug in gained]
        replaced = {group_of(world_root, slug) for slug in gained}
        for slug in lost:
            group = group_of(world_root, slug)
            if group and group in replaced:
                continue
            back = str(group_rules(world_root, group).get("default") or "")
            if back and back not in after:
                out.append(f"You are {back.replace('_', ' ')} again.")
            else:
                out.append(f"You are no longer {said(slug, colour)}.")
        return out

    plain = lines(False)
    if not plain:
        return []

    if getattr(obj, "db", None) is not None and obj.db.is_npc:
        # A character reads nothing. Putting it in working memory is what makes
        # the change reach their next thought, which is the point of telling
        # them -- the same bargain `traits._announce` strikes.
        if hasattr(obj, "_note_to_self"):
            obj._note_to_self(" ".join(plain))
        return plain
    obj.msg("\n".join(f"|y{line}|n" for line in lines(True)))
    return plain


def clear_on_move(obj, world_root=None):
    """
    Drop the states that walking away ends.

    A character who was sitting is not still sitting in the next room: the
    chair did not come with them. Called after every move, so it also repairs
    anything left over from before groups existed.
    """
    if world_root is None:
        room = obj.location
        world_root = room.db.world_root if room else None
    current = states(obj)
    if not current:
        return []
    ending = {
        slug for slug in current
        if group_rules(world_root, group_of(world_root, slug)).get("ends_on_move")
    }
    if not ending:
        return sorted(current)
    obj.db.states = sorted(current - ending)
    refresh_state_aliases(obj)
    return obj.db.states


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

#: How many things to say are wrong at once. Every unmet requirement is worth
#: knowing -- being told you need the key, then that the door is barred, then
#: that your hands are full is three attempts to learn one thing -- but a rule
#: with eight clauses would answer with a paragraph, so the tail is dropped.
MAX_COMPLAINTS = 3

#: The requirement clauses that name several things and are read one at a time.
_LISTED = ("has", "is", "lacks", "holds")


def _listed(value):
    """
    True for something that behaves like a list of names.

    Not `isinstance(value, (list, tuple))`. Everything read back out of an
    Evennia attribute is a _SaverList, which is a MutableSequence and NOT a
    list subclass -- so a concrete test misses every clause a world has
    actually stored, and the value falls through to str() below. That turned
    ["drinkable"] into the single condition "['drinkable']", which nothing
    is and nothing can ever be, so every rule with any precondition at all
    was unsatisfiable and players were told they were "not a ['drinkable']".

    The same trap as checks._mapping, which is where this was learned the
    first time. Stored data was never the problem in either case; reading it
    was.

    A mapping is excluded deliberately: it has __iter__ too, and iterating
    one yields its keys, which are not the names anybody meant.
    """
    return (hasattr(value, "__iter__")
            and not isinstance(value, (str, bytes))
            and not hasattr(value, "items"))

def _named(value):
    """
    Every name a requirement clause holds, however it was written.

    A model asked for a list of conditions writes one of three things: the
    list, one bare word, or -- having been shown a list -- a list with the
    list inside it. Only the names matter, so all three flatten to the same
    thing here rather than each shape being guarded against separately.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if _listed(value):
        found = []
        for item in value:
            found.extend(_named(item))
        return found
    text = str(value)
    return [text] if text.strip() else []


def requirements(requires):
    """
    A rule's preconditions, with every clause that lists things a real list.

    Asked for one condition, a model writes one word rather than a list of
    one: {"holds": "direct"} instead of {"holds": ["direct"]}. Read as
    written that is not one requirement but six, one per letter, and the
    player is told to pick up "the d". Worse, it half-passes -- a letter that
    appears in the name of anything they are carrying is satisfied -- so the
    complaint that surfaces is whichever letter they happen to own least of,
    naming a thing that does not exist and that no action could ever produce.

    A list nested inside the list fails the other way and never passes at
    all: the condition becomes the printed shape of the list, which is not a
    state anything can be in, so the rule is unsatisfiable and the player is
    told they are "not ['greeted']".

    Fixed here, where rules are read, rather than where they are written:
    every world already playing has these clauses stored, and a rule is only
    written once.
    """
    # The outer shape is checked as well as each clause inside it, for the
    # same reason: this reads stored model output, and a model asked for
    # role-keyed preconditions sometimes writes the list of conditions it
    # would have written elsewhere. Read as a mapping that is an
    # AttributeError deep inside a rulebook gather, which takes down an
    # attempt rather than refusing one rule.
    try:
        requires = dict(requires or {})
    except (TypeError, ValueError):
        return {}

    clean = {}
    for role, needed in requires.items():
        try:
            clause = dict(needed)
        except (TypeError, ValueError):
            continue     # a role whose conditions are not conditions at all
        for field in _LISTED:
            # A clause written as an explicit null becomes an empty list and
            # not a null left in place, which is what everything downstream
            # reads as "no conditions" without having to test for it.
            if field in clause:
                clause[field] = _named(clause[field])
        clean[role] = clause
    return clean


def _cap(text):
    """
    Capitalise the first letter, leaving the rest alone.

    `str.capitalize` lowercases everything after it, which turns a "Slate
    Chalkboard" into a "Slate chalkboard". A leading colour code is stepped
    over so the letter after it is the one raised.
    """
    text = str(text or "")
    start = 2 if text[:1] == "|" and len(text) > 2 else 0
    return text[:start] + text[start:start + 1].upper() + text[start + 1:]


def _speak_of(obj, actor):
    """(name, "is"/"are", "It"/"You") for saying something about a thing."""
    if obj is actor:
        return "you", "are", "You"
    return obj.get_display_name(actor), "is", "It"


def _in_a_sentence(obj, actor):
    """
    The thing as it reads in the middle of a sentence, article and all.

    `_speak_of` gives a name for the front of one -- "Glittery Aerosol Can is
    not..." -- and a refusal phrased around a verb puts it in the middle
    instead, where a bare name reads as a stranger's: "you cannot read
    Glittery Aerosol Can".
    """
    if obj is actor:
        return "yourself"
    try:
        return obj.get_numbered_name(1, actor, return_string=True)
    except (AttributeError, TypeError):
        return obj.get_display_name(actor)


#: What "container" and "surface" became. They were affordances until
#: `world.affordances` turned affordances into verbs, and they are not verbs
#: -- they say where things go, which is a fact about a kind. A rule still
#: allowed to ask for them, and plenty do.
_PLACEMENT_AFFORDANCE = {"container": "in", "surface": "on"}


def _wanted_affordances(needed):
    """
    What a rule's `has` list means, in the vocabulary objects actually use.

    Rules are written by models and models write "readable" where the world
    now keeps "read". Both are the same requirement and the second is the one
    that can be checked, so the list is folded on the way in rather than the
    rule being blamed for it -- 39 of the first 42 requirements written after
    the vocabulary changed were adjectives, and every one of them would have
    been a condition no object could ever meet.

    Placement comes back separately, since a rule asking for a container is
    asking a question about the kind rather than about what can be done.
    """
    from world import affordances as af

    verbs_wanted, placement = [], []
    for entry in needed or []:
        word = str(entry or "").lower().strip()
        if word in _PLACEMENT_AFFORDANCE:
            placement.append(_PLACEMENT_AFFORDANCE[word])
            continue
        folded = af.to_verb(word)
        if folded:
            verbs_wanted.append(folded)
    return verbs_wanted, placement


def check(requires, bound, actor, world_root=None):
    """
    Test a rule's preconditions. Returns None when met, else why not.

    The testing and the wording both live in `world.conditions` now. This is
    the shape the attempt pipeline still calls it by: role-keyed `requires`
    in, one sentence out, `None` when nothing is wrong.

    The message was always as much the point of this function as the verdict.
    It used to say "X is not something you can do that to", which names
    neither what was wanted nor what would have served, so a player who tried
    to sit on a bottle learned only that they could not. Every clause now says
    which requirement failed, and a missing affordance also says what the
    thing IS good for -- the sentence that answers "then what can I do with
    it?" without another attempt.
    """
    from world import conditions

    said = conditions.complaints(
        conditions.from_requires(requires),
        conditions.context(bound, actor, world_root),
        limit=MAX_COMPLAINTS,
    )
    return " ".join(said) if said else None


# ---------------------------------------------------------------------------
# Lookups (docs/generator-tool-loops.md §5)
# ---------------------------------------------------------------------------

def lookup_tools():
    """`list_states`, `show_state` and `list_state_groups`."""
    from world import kinds as kinds_mod
    from world import toolbox as tb

    def worked_out(info):
        """How a derived state is worked out, or "" for one that is set."""
        definition = _definition(info)
        if not definition:
            return ""
        return _worded_definition(definition)

    def line(world_root, slug, info):
        how = worked_out(info)
        return (f"{slug}: {info.get('means', '')} "
                f"(group: {group_of(world_root, slug) or 'none'})"
                + (f" -- worked out, never set: holds when {how}"
                   if how else ""))

    def listing(ctx, args):
        vocab = vocabulary(ctx.world_root)
        kind = str(args.get("kind") or "").strip()
        slugs = sorted(vocab)
        if kind:
            familiar = kinds_mod.states_of(ctx.world_root, [kind])
            slugs = [slug for slug in slugs if slug in familiar]
        return tb.paged([line(ctx.world_root, slug, vocab[slug])
                         for slug in slugs], args, "states")

    def showing(ctx, args):
        slug = str(args.get("slug") or "").strip().lower()
        info = vocabulary(ctx.world_root).get(slug)
        group = group_of(ctx.world_root, slug)
        if info is None and not group:
            return f"This world has no state called {slug}."
        said = [f"{slug}: {(info or {}).get('means', '(not said)')}"]
        how = worked_out(info or {})
        if how:
            said.append(f"worked out, never set by any effect: holds when "
                        f"{how}")
        if (info or {}).get("conflicts"):
            said.append(f"cancels: {', '.join(info['conflicts'])}")
        if group:
            rules = group_rules(ctx.world_root, group)
            members = sorted(group_members(ctx.world_root, group) - {slug})
            said.append(f"group: {group}"
                        + (f", with {', '.join(members)}" if members else ""))
            flags = [flag.replace("_", " ") for flag in
                     ("exclusive", "ends_on_move", "prevents_acting",
                      "prevents_moving", "prevents_speaking") if rules.get(flag)]
            if flags:
                said.append("the group is: " + ", ".join(flags))
        return "\n".join(said)

    def grouping(ctx, args):
        lines = []
        for group, rules in sorted(groups(ctx.world_root).items()):
            members = sorted(group_members(ctx.world_root, group))
            lines.append(f"{group}: {', '.join(members) or '(no members yet)'}"
                         + ("" if rules.get("exclusive", True)
                            else " (not exclusive)"))
        return tb.paged(lines, args, "groups")

    return [
        tb.Tool("list_states",
                "The conditions this world already has words for. Reuse one "
                "rather than coining a second word for the same condition.",
                tb.params({**tb.PAGE, "kind": {
                    "type": "string",
                    "description": "Optional. Only the conditions things of "
                                   "this sort have been in"}}),
                tb.answering(listing), doing="looking up this world's states",
                looks=True),
        tb.Tool("show_state",
                "One condition: what it means, its group, and what it stops.",
                tb.params({"slug": {"type": "string",
                                    "description": "The state's name"}},
                          ["slug"]),
                tb.answering(showing), doing="looking up a state", looks=True),
        tb.Tool("list_state_groups",
                "The groups of conditions only one of which can be true at once.",
                tb.params(tb.PAGE), tb.answering(grouping),
                doing="looking up state groups", looks=True),
    ]


# ---------------------------------------------------------------------------
# The shape of a declaration, and whether it is one this world has (docs §4.1)
# ---------------------------------------------------------------------------

def state_declaration_schema(ctx=None):
    """One new state, as `register_state` reads it."""
    world_root = getattr(ctx, "world_root", None)
    in_use = sorted(groups(world_root)) if world_root is not None else []
    return {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Its name"},
            "means": {"type": "string",
                      "description": "What being in it means"},
            "group": {"type": "string",
                      "description": "Optional. The set of conditions only "
                                     "one of which can be true at once"
                                     + (": reuse one of " + ", ".join(in_use)
                                        if in_use and len(in_use) <= 50
                                        else " (list_state_groups)")},
            "conflicts": {"type": "array", "items": {"type": "string"},
                          "description": "Optional. States it ends"},
            "group_ends_on_move": {"type": "boolean",
                                   "description": "Walking away ends it"},
            "group_prevents_acting": {"type": "boolean",
                                      "description": "It stops its holder "
                                                     "doing anything"},
            "group_prevents_moving": {"type": "boolean",
                                      "description": "It stops its holder "
                                                     "moving"},
            "group_prevents_speaking": {"type": "boolean",
                                        "description": "It stops its holder "
                                                       "speaking"},
        },
        "required": ["slug", "means"],
    }


def near_duplicate_state(world_root, slug):
    """
    The state this world already keeps that a new one is really another word
    for, or "".

    A near spelling, as `register_state` would fold it ("emptied" onto
    "empty"), or a synonym in the dictionary's adjective senses ("shut" beside
    "closed"). `register_state` puts a synonym in the same group and keeps both
    words; asked first, the model can use the word the world already has.
    """
    wanted = _slug_state(slug)
    vocab = vocabulary(world_root)
    if not wanted or wanted in vocab:
        return ""
    for existing in sorted(vocab):
        if _similar(wanted, existing):
            return existing
    kin = set()
    for sense in _adjective_senses(wanted):
        try:
            kin |= {name.lower() for name in sense.lemma_names()}
        except Exception:
            continue
    kin.discard(wanted)
    found = sorted(kin & set(vocab))
    return found[0] if found else ""
