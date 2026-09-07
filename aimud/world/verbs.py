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
}


def canonical_verb(word):
    """Fold a verb onto its canonical form."""
    word = word.lower().strip()
    return VERB_SYNONYMS.get(word, word)


def parse(raw):
    """
    Split raw input into a verb and its noun phrases by role.

    Returns {"verb": str, "roles": {role: phrase}} where "direct" is the
    thing acted on and the rest are named by the preposition that introduced
    them.  Word order is preserved, so "tie rope to tree" and "tie tree to
    rope" parse differently, which is the whole point of tracking roles
    rather than collecting a bag of nouns.
    """
    words = [w for w in re.findall(r"[\w'-]+", raw.lower()) if w]
    if not words:
        return {"verb": "", "roles": {}}

    verb = canonical_verb(words[0])
    roles = {}
    current_role = "direct"
    current = []

    for word in words[1:]:
        if word in PREPOSITION_ROLES:
            if current:
                roles.setdefault(current_role, " ".join(current))
                current = []
            current_role = PREPOSITION_ROLES[word]
            continue
        if word in _NOISE:
            continue
        current.append(word)

    if current:
        roles.setdefault(current_role, " ".join(current))
    return {"verb": verb, "roles": roles}


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
    Meaningful words of a name or phrase.

    Noise words are dropped here as well as in parse(), because they drag a
    score down for saying nothing: "the board" against "Slate Chalkboard"
    should be judged on "board" alone.
    """
    return [
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
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
    """The stable capabilities of an object ("readable", "flammable")."""
    return set(obj.db.affordances or [])


def states(obj):
    """The mutable conditions currently true of an object ("wet", "burning")."""
    return set(obj.db.states or [])


def signature(bound):
    """
    A cache key describing the *kind* of situation, not the specific objects.

    "read" applied to anything readable is one rule, so a rule learned for a
    flyer applies to a poster without asking the model again.
    """
    parts = []
    for role in sorted(bound):
        marks = ",".join(sorted(affordances(bound[role]))) or "plain"
        parts.append(f"{role}:{marks}")
    return "|".join(parts) or "none"


def rule_key(verb, bound):
    """The key a learned verb rule is cached under."""
    return f"{verb}#{signature(bound)}"


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


#: Groups of states that behave as a set rather than as loose flags.
#:
#: exclusive    -- only one member can be true of a thing at a time, so
#:                 sitting down stops you standing without any rule saying so.
#: ends_on_move -- walking out of the room ends it. You cannot carry a chair
#:                 away by remaining seated on it.
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


def group_of(world_root, slug):
    """Which group a state belongs to, or None."""
    entry = vocabulary(world_root).get(slug) or {}
    try:
        declared = entry.get("group")
    except AttributeError:
        declared = None
    return declared or DEFAULT_STATE_GROUP.get(slug)


def group_members(world_root, group):
    """Every state known to belong to `group`."""
    if not group:
        return set()
    known = {slug for slug, g in DEFAULT_STATE_GROUP.items() if g == group}
    for slug in vocabulary(world_root):
        if group_of(world_root, slug) == group:
            known.add(slug)
    return known


def register_state(world_root, slug, means="", conflicts=(), group=None):
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

    vocab[slug] = {
        "means": means,
        "conflicts": [c for c in (conflicts or []) if c],
        "group": group or DEFAULT_STATE_GROUP.get(slug, ""),
    }
    world_root.db.state_vocabulary = vocab
    return slug


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
        if STATE_GROUPS.get(group, {}).get("exclusive"):
            current -= (group_members(world_root, group) - {slug})
        current.add(slug)

    obj.db.states = sorted(current)
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
        if STATE_GROUPS.get(group_of(world_root, slug), {}).get("ends_on_move")
    }
    if not ending:
        return sorted(current)
    obj.db.states = sorted(current - ending)
    return obj.db.states


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def check(requirements, bound, actor):
    """
    Test a rule's preconditions. Returns None when met, else why not.

    requirements is {role: {"has": [affordance], "lacks": [state],
    "is": [state], "holds": [name]}} where role may also be "actor".
    The message returned is shown to the player, so it says what is wrong in
    the world's terms rather than the rule's.
    """
    for role, needed in (requirements or {}).items():
        obj = actor if role == "actor" else bound.get(role)
        if obj is None:
            return f"There is nothing here to do that {role and 'to' or ''}".strip() + "."

        name = obj.get_display_name(actor) if obj is not actor else "you"

        for affordance in needed.get("has", []):
            if affordance not in affordances(obj):
                return f"{name.capitalize()} is not something you can do that to."
        for state in needed.get("is", []):
            if state not in states(obj):
                return f"{name.capitalize()} is not {state}."
        for state in needed.get("lacks", []):
            if state in states(obj):
                return f"{name.capitalize()} is already {state}."
        for carried in needed.get("holds", []):
            if not any(carried.lower() in o.key.lower() for o in obj.contents):
                return f"You would need {carried} for that."

        # What is measurably true of a person, tested the same way as what is
        # true of a thing. This is what lets a rule say "you need 10 stamina
        # for that" rather than only "the door must be unlocked".
        wanted_traits = needed.get("trait") or needed.get("traits")
        if wanted_traits:
            from world import traits as traits_mod

            complaint = traits_mod.meets(obj, wanted_traits)
            if complaint:
                return complaint
    return None
