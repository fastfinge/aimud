"""
The rules every world starts with, written by hand once.

Inform ships a Standard Rules extension holding dozens of named check rules --
"can't take what's fixed in place", "can't insert into closed containers" --
and they are the reason an author writes so little. Every game gets the
obvious refusals without anybody restating them, and an author's own rules
compose on top rather than starting from nothing.

This game has been restating them. "You must be holding it" appears in 54
`holds` clauses across the exported corpus, each separately invented by a
model. "It must not already be burning" appears in 121 `lacks` clauses. The
three `prevents_` flags on a state group are a universal precondition that had
to be a hard-coded guard at the top of the attempt pipeline, because there was
nowhere else for a rule that applies to every verb to live.

Now there is. A rule with no action applies to all of them, a world-scope rule
applies everywhere, and the check phase accumulates -- so these are simply the
first entries in the book.

**They are seeded lazily**, the first time a world's rules are read, so a
world made before this gets them too, and re-seeding is a no-op. They carry
`source: "standard"`, which keeps them out of anything that counts what a
world invented for itself.
"""

from world import conditions, rulebooks

#: Marks a world as already having them, so seeding is cheap and idempotent.
SEEDED = "standard_rules_seeded"

#: The action that reads the world rather than changing it. Named rather than
#: spelled out at each use, because every one of `examine`, `inspect`, `study`,
#: `view`, `x` and `l` folds onto it and a typo here would seed rules that
#: nothing ever gathers -- which fails by doing nothing, the worst way.
LOOK = "look"

#: What every world knows before it has learned anything.
#:
#: Deliberately short. Inform can afford dozens because its world model is
#: fixed; here every extra one is a refusal a player meets before the world
#: has had a chance to be interesting, and the ones that are not obviously
#: right belong in a world's own rulebook rather than in everybody's.
STANDARD = (
    {
        "name": "you must be able to act",
        "phase": rulebooks.CHECK,
        "action": None,
        "scope": {rulebooks.WORLD: True},
        "about": "actor",
        "conditions": [{"subject": "actor", "able": "acting"}],
    },
    {
        "name": "you must be able to reach what you act on",
        "phase": rulebooks.CHECK,
        "action": None,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "conditions": [{"subject": "direct", "reachable_by": "actor"}],
    },
    {
        "name": "looking about you means looking at the room",
        "phase": rulebooks.INSTEAD,
        "action": LOOK,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "when": [{"subject": "direct", "unbound": True}],
        "effects": [{"type": "try", "action": LOOK,
                     "roles": {"direct": conditions.HERE}}],
    },
    {
        "name": "you must be able to see what you look at",
        "phase": rulebooks.CHECK,
        "action": LOOK,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "conditions": [{"subject": "direct", "visible_to": "actor"}],
    },
    {
        "name": "what looking at a thing shows",
        "phase": rulebooks.CARRY_OUT,
        "action": LOOK,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "effects": [{"type": "describe", "role": "direct"}],
    },
)


#: Actions the engine knows the shape of, declared rather than asked about.
#:
#: A declaration is normally bought -- `actions.learn` asks what a verb takes,
#: once per verb per world. Looking is not normally: the engine ships rules about
#: it, and those rules were written against a particular arity, so asking a model
#: to guess that same arity risks a world where the standard rules do not gather.
#: It would also be a round trip for an answer already known.
#:
#: `direct` is **optional**, which is what makes bare `look` reach the redirect
#: above rather than being answered "look at what?"; and **visible**, which is
#: what excuses it the reach rule so that sight and touch stop being the same
#: question. See docs/rulebooks-from-inform.md 8.1.
DECLARED = (
    {
        "action": LOOK,
        "means": "to take in what something looks like",
        "applies_to": [{"role": "direct", "access": "visible",
                        "optional": True}],
    },
)


def seed(world_root):
    """
    Make sure a world has the standard rules. Cheap to call, safe to repeat.

    Returns what was added, which is nothing after the first time.
    """
    if not world_root or getattr(world_root.db, SEEDED, False):
        return []
    from world import actions

    for spec in DECLARED:
        actions.declare(world_root, spec["action"],
                        applies_to=spec["applies_to"],
                        means=spec.get("means", ""))
    added = [rulebooks.add(world_root, dict(rule, source="standard"))
             for rule in STANDARD]
    setattr(world_root.db, SEEDED, True)
    return added


def is_standard(rule):
    """Whether a rule came with the world rather than being learned in it."""
    try:
        return str(rule.get("source") or "") == "standard"
    except AttributeError:
        return False
