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

def bind(caller, phrase):
    """
    Find what a noun phrase refers to, searching outward from the character.

    Inventory first, then the room, because "read my letter" should find the
    one being carried.  Returns None when nothing matches -- the caller then
    decides whether the noun is worth conjuring out of the room description.
    """
    if not phrase:
        return None
    from commands.look_take_cmds import _find_one

    obj, _ = _find_one(caller, phrase, location=caller)
    if obj:
        return obj
    obj, _ = _find_one(caller, phrase, location=caller.location)
    return obj


def bind_all(caller, roles):
    """
    Bind every role. Returns (bound, unbound) -- {role: obj}, [role, ...].

    Unbound roles are not an error by themselves: the noun may be a fixture
    that exists only in the room's description and can be promoted to a real
    object, which is the caller's decision to make.
    """
    bound, unbound = {}, []
    for role, phrase in roles.items():
        obj = bind(caller, phrase)
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


def register_state(world_root, slug, means="", conflicts=()):
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
        current.add(slug)

    obj.db.states = sorted(current)
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
    return None
