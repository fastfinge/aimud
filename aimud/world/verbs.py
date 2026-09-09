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

from evennia.utils import logger

from world import lexicon

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
}

# Words that carry no meaning in a command.
_NOISE = frozenset(["the", "a", "an", "my", "your", "some", "that", "this"])

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
        if current:
            roles.setdefault(current_role, " ".join(current))
            if current_word:
                prepositions.setdefault(current_role, current_word)

    for word in words[1:]:
        if word in PREPOSITION_ROLES:
            flush()
            current = []
            current_role = PREPOSITION_ROLES[word]
            current_word = word
            continue
        if word in _NOISE:
            continue
        if lexicon.is_only_adverb(word):
            # Wherever it fell.  An adverb belongs to the verb no matter which
            # noun phrase it landed in the middle of: "put the lamp down
            # gently" and "gently put the lamp down" are the same request.
            manner.append(word)
            continue
        current.append(word)

    flush()
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


def bind(caller, phrase, fuzzy=False):
    """
    Find what a noun phrase refers to, searching outward from the character.

    Inventory first, then the room, because "read my letter" should find the
    one being carried.

    Ambiguity is NOT absence.  Several things matching means the noun exists
    several times over, so one of them is chosen -- the oldest, for
    predictability -- rather than reporting nothing.  Returning None here for
    an ambiguous noun is what let a room fill up with chalkboards: nothing
    matched, so another was conjured, which made the next match worse.

    With `fuzzy`, a name only resembling the phrase will do. That is for NPCs,
    who name things from memory in their own words: better they wipe the
    chalkboard that is already there than hang a blackboard next to it.
    """
    if not phrase:
        return None

    for location in (caller, caller.location):
        candidates = _matches(caller, phrase, location)
        if candidates:
            return min(candidates, key=lambda o: o.id)

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


def bind_all(caller, roles, fuzzy=False):
    """
    Bind every role. Returns (bound, unbound) -- {role: obj}, [role, ...].

    Unbound roles are not an error by themselves: the noun may be a fixture
    that exists only in the room's description and can be promoted to a real
    object, which is the caller's decision to make.
    """
    bound, unbound = {}, []
    for role, phrase in roles.items():
        obj = bind(caller, phrase, fuzzy=fuzzy)
        if obj is None:
            unbound.append(role)
        else:
            bound[role] = obj
    return bound, unbound


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

    `bound` is still accepted so that callers need not change, and ignored.
    """
    return verb


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


def engine_verbs():
    """
    Every verb the game itself answers, read off the running game.

    Two sources, because there are two ways a verb never reaches a model: a
    real command in the character's command set, and the three modules that
    take a verb over inside the attempt pipeline when the noun suits --
    wearing, wielding, and putting one thing on another.

    Read rather than written out here. A hand-written list is one that goes
    quietly stale: the day somebody adds a command or aliases one, a prompt
    saying otherwise starts teaching a model something false, and nothing
    fails loudly enough for anyone to notice.

    Only the "general" category is offered. Building, admin and system
    commands are staff tools no verb rule could be mistaken for, and putting
    @teleport in front of a model deciding what "kiss" means is only noise.
    """
    global _ENGINE_VERBS
    if _ENGINE_VERBS is not None:
        return _ENGINE_VERBS

    from world import clothing, gear, relations

    found = set()
    for module in (clothing, gear, relations):
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
        if (getattr(command, "help_category", "") or "").lower() != "general":
            continue
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
NEW_GROUP = {"exclusive": True, "ends_on_move": False}

#: Groups every world starts with, and how they behave.
#:
#: exclusive    -- only one member can be true of a thing at a time, so
#:                 sitting down stops you standing without any rule saying so.
#: ends_on_move -- walking out of the room ends it. You cannot carry a chair
#:                 away by remaining seated on it.
#:
#: These are seeds rather than the whole list. A world registers its own as it
#: needs them -- see `register_group` -- and what is here is only what no world
#: should have to discover for itself: `ends_on_move` in particular is not
#: something a model reliably works out, and getting it wrong means a character
#: who stays seated in every room they walk into.
STATE_GROUPS = {
    "posture": {"exclusive": True, "ends_on_move": True},
    "wetness": {"exclusive": True, "ends_on_move": False},
    "fire":    {"exclusive": True, "ends_on_move": False},
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


def register_group(world_root, group, exclusive=None, ends_on_move=None):
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
    if exclusive is not None:
        entry["exclusive"] = bool(exclusive)
    if ends_on_move is not None:
        entry["ends_on_move"] = bool(ends_on_move)

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


def register_state(world_root, slug, means="", conflicts=(), group=None,
                   ends_on_move=None):
    """
    Add a state to the world's vocabulary, or fold it onto an existing one.

    Returns the slug actually in use, which may not be the one asked for:
    keeping the vocabulary small is what stops a world accumulating damp,
    moist, soaked and wet as four unrelated conditions.
    """
    if not world_root or not slug:
        return slug
    slug = re.sub(r"[^a-z0-9_]", "", slug.lower().strip())
    if not slug:
        return ""

    vocab = vocabulary(world_root)
    for existing in vocab:
        if _similar(slug, existing):
            return existing

    # The group is registered before the state, so a state that names a new
    # group leaves behind a group that behaves like one. A seeded slug keeps
    # its seeded group whatever was declared -- see DEFAULT_STATE_GROUP.
    seeded = DEFAULT_STATE_GROUP.get(slug)
    opposite = _opposite_group(world_root, slug, vocab)
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
        group = register_group(world_root, group, ends_on_move=ends_on_move)

    vocab[slug] = {
        "means": means,
        "conflicts": [c for c in (conflicts or []) if c],
        "group": group or "",
    }
    world_root.db.state_vocabulary = vocab
    return slug


#: The category the state aliases are filed under, so they can be thrown away
#: and rebuilt without touching the aliases something else put there -- an
#: item conjured as a "Brass Orrery" answers to "astrolabe" because somebody
#: asked for one, and that must survive the bottle being emptied.
STATE_ALIAS = "state"


def condition(obj, looker=None):
    """
    What is currently true of a thing, as a sentence, or "" if nothing is.

    Says the slugs rather than what they mean, because these are also the
    words the thing now answers to: a bottle that reads "It is empty" can be
    taken with "get empty bottle", and one that read "It is drained dry"
    could not. What you are shown and what you can type stay the same words.
    """
    current = sorted(states(obj))
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


def apply_states(obj, add=(), remove=(), world_root=None):
    """
    Change an object's condition, honouring declared conflicts.

    Adding "wet" removes "burning" without anyone having written that rule
    down here, because the conflict was declared when "wet" was registered.
    """
    current = states(obj)
    vocab = vocabulary(world_root)

    for slug in remove:
        current.discard(slug)
    for slug in add:
        if not slug:
            continue
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
    return obj.db.states


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
    clean = {}
    for role, needed in (requires or {}).items():
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


def _as_quality(affordance):
    """
    An affordance as it fits into "X is not ___".

    Almost every one a world invents is already an adjective -- readable,
    sittable, breakable, flammable -- and the two that are not are things
    rather than qualities, so they take an article instead.
    """
    word = str(affordance or "").replace("_", " ").strip()
    if not word:
        return ""
    return word if word.endswith(("able", "ible")) else f"a {word}"


def check(requires, bound, actor, world_root=None):
    """
    Test a rule's preconditions. Returns None when met, else why not.

    requires is {role: {"has": [affordance], "lacks": [state],
    "is": [state], "holds": [name]}} where role may also be "actor".

    The message is the point of this function as much as the verdict. It used
    to say "X is not something you can do that to", which names neither what
    was wanted nor what would have served -- so a player who tried to sit on a
    bottle learned only that they could not, and an NPC told the same thing
    asked for it again next turn. Every clause here now says which
    requirement failed, and a missing affordance also says what the thing IS
    good for, because that is the sentence that answers "then what can I do
    with it?" without another attempt.
    """
    complaints = []

    def note(text):
        if text and text not in complaints:
            complaints.append(text)

    for role, needed in requirements(requires).items():
        obj = actor if role == "actor" else bound.get(role)
        if obj is None:
            note("There is nothing here to do that to.")
            continue

        name, be, pronoun = _speak_of(obj, actor)
        have = affordances(obj)
        is_now = states(obj)

        for affordance in needed.get("has", []):
            if affordance in have:
                continue
            quality = _as_quality(affordance)
            said = f"{_cap(name)} {be} not {quality}."
            # What it IS for. The hint the old message withheld: a bottle that
            # cannot be sat on can still be drunk, broken and put things in.
            if have:
                from evennia.utils.utils import iter_to_str

                # Qualities before things, so it reads "breakable, drinkable
                # and a container" rather than opening on the odd one out.
                qualities = sorted(_as_quality(a) for a in have)
                qualities.sort(key=lambda q: q.startswith("a "))
                said += f" {pronoun} {be} {iter_to_str(qualities)}."
            note(said)

        for state in needed.get("is", []):
            if state in is_now:
                continue
            # The meaning as well as the word, because half these words the
            # world invented for itself and "not charged" is only useful to
            # somebody who knows what this world charges.
            means = (vocabulary(world_root).get(state) or {}).get("means") \
                if world_root is not None else ""
            note(f"{_cap(name)} {be} not {state}"
                 + (f" ({means})." if means else "."))

        for state in needed.get("lacks", []):
            if state in is_now:
                note(f"{_cap(name)} {be} already {state}.")

        for carried in needed.get("holds", []):
            # A rule may name another role here rather than an item, and for
            # the verbs where holding matters it almost always does: "to throw
            # it you must be holding it" is a condition about whatever is being
            # thrown, which has no name until somebody throws something. Read
            # literally it asks the player to carry an object called "direct",
            # which nothing is and nothing can be -- so the rule could never be
            # satisfied, and picking the thing up changed nothing.
            role_wanted = bound.get(str(carried).strip().lower())
            if role_wanted is not None:
                if role_wanted not in obj.contents:
                    held_name, _be, _pronoun = _speak_of(role_wanted, actor)
                    note(f"{_cap(name)} {be} not holding {held_name}.")
                continue

            if not any(carried.lower() in o.key.lower() for o in obj.contents):
                # A rule writes the item as a bare noun phrase ("brass key"),
                # which needs an article to be said aloud. Any it already has
                # is dropped first, so "a brass key" does not become "the a
                # brass key".
                wanted = re.sub(r"^(?:an?|the|some)\s+", "", carried.strip(),
                                flags=re.IGNORECASE)
                note(f"{_cap(name)} {be} not holding the {wanted}.")

        # What is measurably true of a person, tested the same way as what is
        # true of a thing. This is what lets a rule say "you need 10 stamina
        # for that" rather than only "the door must be unlocked".
        wanted_traits = needed.get("trait") or needed.get("traits")
        if wanted_traits:
            from world import traits as traits_mod

            note(traits_mod.meets(obj, wanted_traits))

    if not complaints:
        return None
    return " ".join(complaints[:MAX_COMPLAINTS])
