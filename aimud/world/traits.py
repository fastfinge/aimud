"""
Traits: what is measurably true of a person, and how it changes.

States say what is true of a thing right now -- wet, burning, open -- and are
either so or not. A trait is the same idea carried to people and given a
number: stamina 40, swordsmanship 12, reputation -3. That is what lets a rule
say something about a character rather than only about the objects they act
on, and what lets an effect happen over time rather than all at once.

Evennia's Traits contrib supplies the arithmetic -- bases, modifiers, bounds,
the per-second rate that makes a poison drain and a rest restore. Everything
here is the layer above it, and exists for three reasons.

* **One vocabulary per world.** This is the whole problem with letting a model
  invent traits. Left alone, one character is given "magic: 14" and the next
  "mana: 14", and then half the rules test one and half the other and neither
  works. So a world keeps a register of every trait in it, exactly as it keeps
  one of every state, and the answer has the same three parts: the register is
  shown to every prompt that could invent a trait, with an instruction to
  reuse what is there; a new name close to an existing one is folded onto it
  on the way in; and nothing anywhere reads a trait that was never registered.

* **One door for changes.** Everything that alters a trait comes through
  `adjust`, so a character can be told what happened to them. A number that
  changes silently is not a trait anyone can play with.

* **Drift is noticed.** A trait with a rate changes on its own, and nothing
  fires when it does -- the contrib computes the new value when next asked.
  So the value each character was last told about is remembered, and compared
  at the moments the game already looks at a character anyway.
"""

import re

from evennia.utils import logger

#: How a trait behaves. The contrib offers more; these three are what a world
#: needs, and a short list is one a model can choose from correctly.
#:
#: counter -- a number that moves from a base, up or down, with optional
#:            bounds. Skills, reputation, tallies. The general case.
#: gauge   -- something depletable that refills to a maximum. Health, stamina,
#:            fuel. `.current` falls, `.max` is base + mod.
#: static  -- a fixed figure that only deliberate change moves. Raw attributes.
TRAIT_TYPES = ("counter", "gauge", "static")

DEFAULT_TRAIT_TYPE = "counter"

#: Traits the game itself keeps, seeded into every world so that no model ever
#: invents a second name for them. A tally of errands run is the clearest case
#: there is of something that must be called one thing everywhere.
BUILTIN = {
    "quests_completed": {
        "name": "Errands completed",
        "means": "how many errands this character has finished",
        "trait_type": "counter", "base": 0, "min": 0,
    },
    "quests_failed": {
        "name": "Errands failed",
        "means": "how many errands this character has failed or given up on",
        "trait_type": "counter", "base": 0, "min": 0,
    },
}

#: Where a character remembers what they were last told each trait was, so
#: that a value which drifted on its own can be noticed and reported.
_SEEN = "trait_last_seen"


def _slug(text):
    """A trait name reduced to the form it is stored under."""
    slug = re.sub(r"[^a-z0-9_]", "_", str(text or "").lower().strip())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def has_traits(obj):
    """True for something that can carry traits at all -- a person."""
    return obj is not None and hasattr(obj, "traits")


# ---------------------------------------------------------------------------
# The world's register
# ---------------------------------------------------------------------------

def vocabulary(world_root):
    """{slug: {"name", "means", "trait_type", ...}} for this world."""
    if world_root is None:
        return dict(BUILTIN)
    stored = dict(world_root.db.trait_vocabulary or {})
    for slug, entry in BUILTIN.items():
        stored.setdefault(slug, dict(entry))
    return stored


def known(world_root, slug):
    """The register's entry for a trait, or None if the world has no such thing."""
    return vocabulary(world_root).get(_slug(slug))


def _matching(world_root, slug):
    """
    An existing trait that `slug` is really just another spelling of.

    Deliberately narrow. Folding "str" onto "strength" is repairing a typo;
    folding "mana" onto "magic" would be deciding a question of meaning that
    is not this function's to decide. What keeps those two apart is that every
    prompt able to invent a trait is shown the register first and told to
    reuse it -- this only catches what slips through as a near-miss.
    """
    for existing in vocabulary(world_root):
        if existing == slug:
            return existing
        # One is an abbreviation of the other ("str"/"strength"), or they
        # differ only by a plural or a separator ("quest_failed").
        short, long = sorted((existing, slug), key=len)
        if len(short) >= 3 and long.startswith(short) and len(long) - len(short) <= 3:
            return existing
        if short.replace("_", "") == long.replace("_", "").rstrip("s"):
            return existing
    return None


def resolve(world_root, slug):
    """
    The name this world actually keeps a trait under.

    Everything that is about to read or write a trait by a name a model chose
    goes through here first, so that "stam" and "stamina" reach the same
    figure rather than sitting beside each other as two.
    """
    slug = _slug(slug)
    return _matching(world_root, slug) or slug


def register(world_root, slug, name="", means="", trait_type=DEFAULT_TRAIT_TYPE,
             **properties):
    """
    Put a trait in the world's register, or fold it onto one already there.

    Returns the slug actually in use, which may not be the one asked for --
    that return value is the point, and every caller must use it rather than
    what it passed in, or the fold achieves nothing.
    """
    slug = _slug(slug)
    if not slug:
        return ""
    if world_root is None:
        return slug

    existing = _matching(world_root, slug)
    if existing:
        return existing

    # A word already meaning something else in this world is not free. See
    # `world.vocabulary`: a state and a trait sharing a name are two answers
    # to one question about a thing, and nothing afterwards can say which was
    # meant.
    from world import vocabulary

    if not vocabulary.permit(world_root, slug, "trait"):
        return ""

    trait_type = trait_type if trait_type in TRAIT_TYPES else DEFAULT_TRAIT_TYPE
    entry = {
        "name": str(name).strip() or slug.replace("_", " ").title(),
        "means": str(means).strip(),
        "trait_type": trait_type,
    }
    for field in ("base", "min", "max", "mod", "rate", "descs"):
        if properties.get(field) is not None:
            entry[field] = properties[field]

    vocab = dict(world_root.db.trait_vocabulary or {})
    vocab[slug] = entry
    world_root.db.trait_vocabulary = vocab
    logger.log_info(f"traits: {world_root.key} learned {slug!r} ({trait_type})")
    return slug


def vocabulary_block(world_root, header="Traits this world already uses"):
    """
    The register as a prompt block, or "" when the world has none yet.

    Every prompt that could invent a trait gets this, which is the part of
    keeping one vocabulary that actually does the work: a model shown that
    "stamina" exists does not go on to invent "vigour".
    """
    vocab = vocabulary(world_root)
    if not vocab:
        return ""
    lines = []
    for slug, entry in sorted(vocab.items()):
        means = entry.get("means") or entry.get("name") or ""
        lines.append(f"  {slug} ({entry.get('trait_type', 'counter')}): {means}")
    return (f"{header} — reuse these rather than inventing another name for "
            f"the same idea:\n" + "\n".join(lines) + "\n\n")


# ---------------------------------------------------------------------------
# Reading a character
# ---------------------------------------------------------------------------

def _bounds(trait):
    low = getattr(trait, "min", None)
    high = getattr(trait, "max", None)
    return low, high


def value(character, slug):
    """A character's value for a trait, or None if they do not have it."""
    if not has_traits(character):
        return None
    trait = character.traits.get(_slug(slug))
    return None if trait is None else trait.value


def all_of(character):
    """[(slug, trait), ...] for everything a character has, in name order."""
    if not has_traits(character):
        return []
    found = []
    for slug in character.traits.all():
        trait = character.traits.get(slug)
        if trait is not None:
            found.append((slug, trait))
    return sorted(found, key=lambda pair: pair[0])


def describe(character, slug=None):
    """
    A character's traits as one readable line, for prompts.

    Short on purpose: this goes into every NPC reaction, where it competes for
    attention with everything else the character knows.
    """
    entries = all_of(character)
    if slug is not None:
        entries = [(s, t) for s, t in entries if s == _slug(slug)]
    if not entries:
        return ""

    parts = []
    for name, trait in entries:
        text = f"{name} {_round(trait.value)}"
        low, high = _bounds(trait)
        if high is not None:
            text += f"/{_round(high)}"
        worded = _worded(trait)
        if worded:
            text += f" ({worded})"
        rate = getattr(trait, "rate", 0) or 0
        if rate:
            text += f", {'rising' if rate > 0 else 'falling'} on its own"
        parts.append(text)
    return ", ".join(parts)


def _worded(trait):
    """The trait's own word for where it stands, if it has one."""
    try:
        return trait.desc() or ""
    except Exception:
        return ""


def _round(number):
    """Numbers as a person would write them: 12, not 12.0."""
    try:
        if float(number) == int(float(number)):
            return str(int(float(number)))
        return f"{float(number):.1f}"
    except (TypeError, ValueError):
        return str(number)


# ---------------------------------------------------------------------------
# Changing a character
# ---------------------------------------------------------------------------

def _world_root(character):
    room = getattr(character, "location", None)
    return room.db.world_root if room else None


def ensure(character, slug, world_root=None, **properties):
    """
    Make sure a character has a trait, creating it from the register if not.

    The register is the authority on what a trait is: its type, its bounds and
    its starting value are the world's, not this character's, so two people
    with the same trait have the same kind of thing.
    """
    if not has_traits(character):
        return None
    slug = _slug(slug)
    if not slug:
        return None
    if world_root is None:
        world_root = _world_root(character)

    existing = character.traits.get(slug)
    if existing is not None:
        return existing

    entry = dict(known(world_root, slug) or {})
    if not entry:
        # Not in the register: put it there, so the next character to gain it
        # gets the same thing and no prompt invents a rival name for it.
        slug = register(world_root, slug, **properties)
        entry = dict(known(world_root, slug) or {})
        if not entry:
            return None

    trait_type = entry.get("trait_type", DEFAULT_TRAIT_TYPE)
    kwargs = {"trait_type": trait_type, "name": entry.get("name") or slug}
    for field in ("base", "min", "max", "mod", "rate", "descs"):
        if entry.get(field) is not None:
            kwargs[field] = entry[field]
    kwargs.setdefault("base", 0)
    if trait_type == "gauge":
        # A gauge's maximum is its base, and it starts full.
        kwargs.pop("max", None)

    try:
        character.traits.add(slug, **kwargs)
    except Exception as exc:
        logger.log_info(f"traits: could not give {character.key} {slug!r}: {exc}")
        return None
    return character.traits.get(slug)


def adjust(character, slug, change=None, set_to=None, rate=None, world_root=None,
           announce=True, reason=""):
    """
    Change one of a character's traits, and tell them about it.

    This is the only way a trait ever moves, so that nothing changes about a
    character without them noticing. Returns (slug, before, after), or None if
    the trait could not be given or found.

    `change` moves the value; `set_to` puts it at a figure; `rate` sets the
    per-second drift that makes an effect play out over time rather than all
    at once -- a poison, a fever breaking, a skill going rusty.
    """
    if not has_traits(character):
        return None
    if world_root is None:
        world_root = _world_root(character)

    slug = _slug(slug)
    existing = character.traits.get(slug) if slug else None
    if existing is None:
        # Fold the name onto whatever this world already calls it, BEFORE
        # anything is created or recorded under the name that was asked for.
        # A character who already has it under the old name keeps it: renaming
        # what somebody already has would lose the figure.
        slug = resolve(world_root, slug)
        existing = character.traits.get(slug)
    gained = existing is None
    trait = existing or ensure(character, slug, world_root=world_root)
    if trait is None:
        return None

    before = trait.value
    try:
        if set_to is not None:
            _write(trait, float(set_to))
        if change:
            _write(trait, float(trait.value) + float(change))
        if rate is not None:
            _set_rate(trait, rate)
    except Exception as exc:
        logger.log_info(f"traits: could not change {slug!r} on {character.key}: {exc}")
        return None

    after = trait.value
    _remember_seen(character, slug, after)
    if announce and (gained or after != before or rate):
        _announce(character, slug, trait, before, after, gained, reason)
    return slug, before, after


def _set_rate(trait, rate):
    """
    Start, change or stop a trait drifting on its own.

    The contrib defines no setter for `rate`: assigning it writes the number
    and nothing else, and the clock it is measured against is only started
    when a trait is *created* with a rate already set. So a rate set after the
    fact does nothing at all, which is precisely the case every rule produces.

    Setting one therefore has to start the clock too, and clearing one has to
    stop it -- otherwise the whole idle period would be applied at once the
    next time a rate was set.
    """
    rate = float(rate)
    trait.value              # flush whatever accrued at the previous rate
    trait.rate = rate
    if rate == 0:
        # No public way to stop it: _stop_timer refuses once the rate is zero,
        # and this is the field the contrib's own code writes.
        trait._data["last_update"] = None
    else:
        trait._check_and_start_timer(trait.value)


def _write(trait, target):
    """
    Put a trait at a value, whichever field this kind of trait moves.

    A counter and a gauge are moved by `.current`; a static trait has no
    current and is moved by its base. Getting this wrong is silent -- the
    contrib ignores writes to `.value` -- so it is decided in one place.
    """
    if hasattr(trait, "current"):
        trait.current = target
    else:
        trait.base = target


def bump(character, slug, amount=1, world_root=None, reason=""):
    """Move a trait by a step, creating it at zero if this is the first."""
    return adjust(character, slug, change=amount, world_root=world_root,
                  reason=reason)


def _announce(character, slug, trait, before, after, gained, reason=""):
    """Tell a character what changed about them, in their own terms."""
    label = getattr(trait, "name", None) or slug
    tail = f" ({reason})" if reason else ""

    if gained:
        text = f"|yYou gain {label}: {_round(after)}.|n{tail}"
    else:
        direction = "rises" if after > before else "falls"
        text = (f"|yYour {label} {direction} to {_round(after)}|n "
                f"|x(was {_round(before)})|n{tail}")

    if getattr(character, "db", None) is not None and character.db.is_npc:
        # An NPC reads nothing. Putting it in working memory is what makes the
        # change reach the character's next thought, which is the whole point
        # of telling them.
        if hasattr(character, "_note_to_self"):
            plain = (f"{label} is now {_round(after)}"
                     + (f", up from {_round(before)}" if not gained else "")
                     + (f" ({reason})" if reason else ""))
            character._note_to_self(plain)
        return
    character.msg(text)


# ---------------------------------------------------------------------------
# Noticing what changed on its own
# ---------------------------------------------------------------------------

def _seen(character):
    return dict(getattr(character.db, _SEEN, None) or {})


def _remember_seen(character, slug, current):
    seen = _seen(character)
    seen[slug] = current
    setattr(character.db, _SEEN, seen)


def notice_changes(character):
    """
    Report any trait that has drifted since the character last looked.

    A trait with a rate is not recalculated on a timer -- the contrib works
    out the new value only when something asks for it -- so there is no moment
    to hang a notification on. Instead this is called at the moments the game
    already turns its attention to a character: when they arrive somewhere,
    and when an NPC takes its turn. A fever that broke while they walked down
    the corridor is reported when they get there.

    Returns the list of slugs that had moved.
    """
    if not has_traits(character):
        return []
    seen = _seen(character)
    moved = []
    for slug, trait in all_of(character):
        current = trait.value
        previous = seen.get(slug)
        seen[slug] = current
        if previous is None or current == previous:
            continue
        moved.append(slug)
        _announce(character, slug, trait, previous, current, gained=False,
                  reason="")
    if moved or len(seen) != len(_seen(character)):
        setattr(character.db, _SEEN, seen)
    return moved


# ---------------------------------------------------------------------------
# Requirements and goals
# ---------------------------------------------------------------------------

def meets(character, requirement):
    """
    Test one trait requirement against a character. None when met, else why not.

    `requirement` is {slug: {"min": n, "max": n, "at_least": n}} -- the same
    shape a verb rule's `requires` uses and a goal's condition reads, so a
    thing a rule can demand is a thing a goal can ask for.
    """
    for slug, wanted in (requirement or {}).items():
        slug = _slug(slug)
        trait = character.traits.get(slug) if has_traits(character) else None
        current = None if trait is None else trait.value
        label = (getattr(trait, "name", None) or slug.replace("_", " "))

        try:
            low = wanted.get("min", wanted.get("at_least"))
            high = wanted.get("max", wanted.get("at_most"))
        except AttributeError:
            low, high = wanted, None

        if current is None:
            return f"You have no {label} to speak of."
        if low is not None and current < float(low):
            return f"Your {label} is not high enough ({_round(current)}/{_round(low)})."
        if high is not None and current > float(high):
            return f"Your {label} is too high ({_round(current)})."
    return None


def satisfied(character, requirement):
    """True when every trait requirement holds."""
    return meets(character, requirement) is None
