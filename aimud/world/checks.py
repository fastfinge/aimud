"""
Rolling for an outcome, so that trying is not the same as doing.

Everything else in the verb pipeline answers "may you do this?" -- the rule's
preconditions say the door is openable and you are holding the key. Nothing
asked "did you?", so a verb that passed its preconditions always worked, and a
world where every swing lands is not a game.

The division of labour is the same one the rest of the system uses: the model
says what KIND of thing is being attempted, and code decides what happened. A
rule declares the contest once -- which figure of the actor's decides it, and
what opposes it -- and that declaration is cached with the rule and reused
forever. The roll itself never goes near a model. That is not only cheaper: a
model asked "did they succeed?" says yes, and asked twice says something
different the second time, which is the opposite of a rule.

A check is optional and most verbs have none. Reading a notice is not a
gamble, and making it one would be a worse game rather than a better one.
"""

import random

from evennia.utils import logger

#: The outcomes a check can produce, worst to best.
OUTCOMES = ("critical_failure", "failure", "success", "critical_success")

#: Outcomes that mean the thing was actually accomplished.
GOOD = frozenset(["success", "critical_success"])

#: What a branch falls back to when the rule did not write one, so a world
#: that only bothered to describe success and failure still behaves sensibly
#: at the extremes rather than doing nothing at all.
FALLBACK = {
    "critical_failure": "failure",
    "critical_success": "success",
}

#: The die. Twenty is not arbitrary: coarse enough that a single point of a
#: trait is worth having, wide enough that a novice occasionally beats an
#: expert, which is the whole reason for rolling.
DIE = 20

#: What a check is measured against when the rule named no figure at all.
#: Even odds for somebody with none of the trait.
DEFAULT_DIFFICULTY = 10

#: How far past the target a roll lands before it is more than a plain
#: success -- and how far short before it is worse than a plain failure.
CRITICAL_MARGIN = 10


def _mapping(value):
    """
    True for something that behaves like a dict.

    Not `isinstance(value, dict)`. Anything read back out of an Evennia
    attribute is a _SaverDict, which is a MutableMapping and NOT a dict
    subclass, so an isinstance test here would reject every rule a world has
    actually stored and silently turn every check off.
    """
    return hasattr(value, "get") and hasattr(value, "items")


def _sequence(value):
    """True for something that behaves like a list (see `_mapping`)."""
    return hasattr(value, "__iter__") and not isinstance(value, (str, bytes))


# ---------------------------------------------------------------------------
# What a rule declared
# ---------------------------------------------------------------------------

def clean(spec):
    """
    A model's `check` reduced to the shape this module reads, or None.

    None for anything malformed is deliberate: a check nobody can make sense
    of should leave the verb deterministic, exactly as it was before, rather
    than roll against a target invented here.
    """
    if not _mapping(spec):
        return None

    from world import traits

    trait = traits._slug(spec.get("trait", ""))

    against = None
    raw = spec.get("against")
    if _mapping(raw):
        role = str(raw.get("role", "")).strip().lower()
        # "actor" is the person rolling. A verb contested by its own actor is
        # a rule that means nothing, so it is dropped rather than obeyed.
        if role and role != "actor":
            against = {"role": role,
                       "trait": traits._slug(raw.get("trait", "")) or trait}

    try:
        difficulty = float(spec.get("difficulty"))
    except (TypeError, ValueError):
        difficulty = None

    if not trait and against is None and difficulty is None:
        return None
    return {"trait": trait, "against": against, "difficulty": difficulty}


def wanted(rule):
    """The check a stored rule declared, or None if the verb is a certainty."""
    if not _mapping(rule):
        return None
    return clean(rule.get("check"))


def effects_for(rule, outcome):
    """
    The effects that fire for this outcome.

    A flat list is what every rule looked like before checks existed, and what
    an uncontested verb still looks like: it is the success branch, and there
    is nothing to do on a failure that cannot happen.
    """
    if not _mapping(rule):
        return []
    branches = rule.get("effects")
    if branches is None:
        return []

    if not _mapping(branches):
        if not _sequence(branches):
            return []
        return list(branches) if outcome in GOOD else []

    seen = set()
    name = outcome
    while name and name not in seen:
        seen.add(name)
        found = branches.get(name)
        if found and _sequence(found):
            return list(found)
        name = FALLBACK.get(name)
    return []


def every_effect(effects):
    """
    Every effect in a rule, whichever shape it came in and whatever it means.

    For things that must reach all of them regardless of outcome -- rewriting
    a trait name, say. Anything asking what a verb *accomplishes* wants
    `effects_for(rule, "success")` instead: a failure branch is a list of
    things that go wrong, and treating it as an achievement is how a planner
    ends up recommending that somebody drop their sword on purpose.
    """
    if _mapping(effects):
        for branch in effects.values():
            for effect in branch or []:
                yield effect
        return
    if not _sequence(effects):
        return
    for effect in effects or []:
        yield effect


def free_to_fail(rule):
    """
    True for a contested rule whose failure changes nothing.

    Worth knowing about: it is the one way a check makes a world worse than no
    check at all, because the player simply repeats the command until it
    works. Reported rather than repaired -- inventing a penalty the rule did
    not ask for would be a mechanic nobody wrote.
    """
    if wanted(rule) is None:
        return False
    return not effects_for(rule, "failure")


# ---------------------------------------------------------------------------
# Rolling
# ---------------------------------------------------------------------------

def _figure(who, slug, world_root):
    """
    A character's standing in a trait, creating it at the world's base if this
    is the first time anything asked.

    Creating it is the point rather than a side effect: the register says what
    a trait starts at, so a character who has never held a sword rolls from
    the same place every other novice does, and `score` begins showing them a
    figure the world has started to care about.
    """
    from world import traits

    if not slug or not traits.has_traits(who):
        return 0.0
    trait = traits.ensure(who, traits.resolve(world_root, slug),
                          world_root=world_root)
    if trait is None:
        return 0.0
    try:
        return float(trait.value)
    except (TypeError, ValueError):
        return 0.0


def _target(actor, spec, bound, world_root):
    """
    The number to beat, and the name of whoever set it.

    A contest against a person wins over a fixed difficulty whenever that
    person is really there and really has the trait: that is what makes a
    veteran guard harder to fight than a starving one, which a number written
    into the rule could never do.
    """
    from world import traits

    against = spec.get("against")
    if against:
        opponent = bound.get(against["role"])
        if opponent is not None and traits.has_traits(opponent):
            standing = _figure(opponent, against["trait"], world_root)
            return (DEFAULT_DIFFICULTY + standing,
                    opponent.get_display_name(actor))

    if spec.get("difficulty") is not None:
        return float(spec["difficulty"]), ""
    return float(DEFAULT_DIFFICULTY), ""


def _band(margin, die):
    """
    Which outcome a margin lands in.

    The extremes of the die overrule the arithmetic: a perfect roll is never a
    failure however outmatched the actor is, and a hopeless one never a
    success. Without that, a trait gap of twenty makes the die irrelevant and
    the fight is decided before it starts.
    """
    if margin >= CRITICAL_MARGIN:
        index = 3
    elif margin >= 0:
        index = 2
    elif margin > -CRITICAL_MARGIN:
        index = 1
    else:
        index = 0

    if die == DIE:
        index = max(index, 2)
    elif die == 1:
        index = min(index, 1)
    return OUTCOMES[index]


def resolve(actor, spec, bound, world_root):
    """
    Roll one check. Returns a dict describing what happened, never None.

    The dict carries the numbers as well as the outcome, because the narration
    is written from it: how narrowly a thing was missed is most of what makes
    a failure worth reading.
    """
    standing = _figure(actor, spec.get("trait"), world_root)
    target, opposed_by = _target(actor, spec, bound, world_root)

    die = random.randint(1, DIE)
    roll = die + standing
    margin = roll - target

    result = {
        "outcome": _band(margin, die),
        "margin": margin,
        "die": die,
        "roll": roll,
        "target": target,
        "trait": spec.get("trait") or "",
        "standing": standing,
        "opposed_by": opposed_by,
    }
    logger.log_info(f"check: {actor.key} {describe(result)}")
    return result


def describe(result):
    """The roll as one line, for the log. Players are never shown this."""
    if not result:
        return "no check"
    against = f" ({result['opposed_by']})" if result.get("opposed_by") else ""
    return (f"{result.get('trait') or 'untrained'} "
            f"{result['die']}+{result['standing']:g} = {result['roll']:g} "
            f"vs {result['target']:g}{against} -> {result['outcome']} "
            f"(by {result['margin']:+g})")


def narration_hint(result):
    """
    How the attempt went, in words a model can write prose from.

    Deliberately not the numbers. A narrator given "13 against 12" writes
    about dice; one given "succeeded by the barest margin" writes about a
    blade turning at the last moment.
    """
    if not result:
        return ""
    outcome = result["outcome"]
    margin = abs(result["margin"])
    closeness = ("by the barest margin" if margin <= 2
                 else "clearly" if margin < CRITICAL_MARGIN
                 else "utterly")

    wording = {
        "critical_success": "succeeded far better than they had any right to",
        "success": f"succeeded, {closeness}",
        "failure": f"failed, {closeness}",
        "critical_failure": "failed badly, and it went wrong on them",
    }[outcome]

    against = (f", against {result['opposed_by']}"
               if result.get("opposed_by") else "")
    return f"{outcome} -- the actor {wording}{against}."
