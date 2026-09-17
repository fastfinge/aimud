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

#: Which edition of the standard rules a world holds.
#:
#: `reset world` is this project's usual answer to a change in shape, and it is
#: the right one for a world's *own* rules -- nobody can say what a world meant
#: by something it wrote. These are not a world's own rules: they are the
#: engine's, written here, and a world holding last week's copy of them is
#: holding a bug rather than a decision. So the seed carries a number, and a
#: world a version behind has its standard rules replaced -- only the ones
#: marked `standard`, and never anything it learned for itself.
#:
#: Raise this whenever STANDARD or DECLARED changes.
#:
#: 2 -- the reach and sight rules gained a guard, so a verb naming nothing is
#:      no longer refused for not reaching it; the placement verbs are declared
#:      rather than having an arity read off a figure of speech; and looking
#:      happens in spite of the gates, so being dead is not being blind.
#: 3 -- ownership: taking something nobody owns claims it, and giving it hands
#:      the owning over with it.
#: 4 -- "you may not take what is not yours", shipped suspended; and whatever
#:      a world did with `rules suspend` or `rules restore` to a standard rule
#:      now survives the next edition, instead of being quietly undone by it.
VERSION = 4
VERSION_ATTR = "standard_rules_version"

#: The action that reads the world rather than changing it. Named rather than
#: spelled out at each use, because every one of `examine`, `inspect`, `study`,
#: `view`, `x` and `l` folds onto it and a typo here would seed rules that
#: nothing ever gathers -- which fails by doing nothing, the worst way.
LOOK = "look"

#: The two actions ownership turns on, named for the same reason. Both are
#: mechanics -- neither reaches a model -- and both run their after-rules
#: through `attempt.consequences`, which is what makes a seeded rule about
#: them fire at all.
TAKE, GIVE = "get", "give"

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
        # Guarded on something having been named, and the guard is not a
        # nicety. This rule applies to every action there is, so a verb that
        # takes no object at all -- smiling, waiting, shouting -- gathered it
        # too, and `reachable_by` answers a subject that is not there with
        # "There is nothing here to do that to." So `smile` was refused, in
        # words that read as though the game had misunderstood the word rather
        # than as what it was: a rule about a thing, asked about no thing.
        #
        # A required role left unbound is a different question and is asked
        # elsewhere, in better words ("smile at what?"). An optional one left
        # unbound is what a redirect is for. Neither wants reach tested
        # against nothing.
        "name": "you must be able to reach what you act on",
        "phase": rulebooks.CHECK,
        "action": None,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "when": [{"subject": "direct", "unbound": False}],
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
        # Guarded for the same reason as the reach rule above. Bare `look` is
        # redirected to the room before this could fire, but the redirect is a
        # rule and a world may replace it, and a check that refuses in the
        # wrong words when it does is not a check worth having.
        "name": "you must be able to see what you look at",
        "phase": rulebooks.CHECK,
        "action": LOOK,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "when": [{"subject": "direct", "unbound": False}],
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
    {
        # An `after` rule rather than a `carry_out` one, and that is the whole
        # reason these are rules at all: a world that means "you may not take
        # what is not yours" writes a check rule and puts it in front of this,
        # and neither rule has to know the other exists. A guard welded into
        # the get command could not be composed with, read, or replaced.
        #
        # "Nobody" covers the thing nobody has ever claimed and the thing whose
        # owner has left the world, which is what makes a dead man's sword
        # claimable and leaves a living woman's alone.
        "name": "taking something nobody owns makes it yours",
        "phase": rulebooks.AFTER,
        "action": TAKE,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "when": [{"subject": "direct", "owned_by": conditions.NOBODY}],
        "effects": [{"type": "set_owner", "name_role": "direct",
                     "to": "actor"}],
    },
    {
        # And the other half: handing a thing over hands over the owning of
        # it, contents and all. Here rather than inside the giving mechanic
        # for the same reason -- a world where handing somebody your sword
        # lends it rather than gives it says so by replacing this one rule.
        "name": "giving something hands over the owning of it",
        "phase": rulebooks.AFTER,
        "action": GIVE,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "effects": [{"type": "set_owner", "name_role": "direct",
                     "to": "target"}],
    },
    {
        # The one standard rule that ships suspended. Whether taking what is
        # somebody's is refused or merely noticed is a decision about what
        # sort of world this is -- a heist and a monastery answer it
        # differently -- and it is a check rule in front of the claiming rule
        # above precisely so that a world can make it with `rules restore`
        # and neither rule has to know the other exists.
        #
        # Guarded on the thing being somebody's rather than conditioned on it
        # being yours-or-nobody's, because the condition language has no "or":
        # nobody's things are never gathered, and everything else must be
        # yours. A dead owner's sword counts as nobody's, as it does above.
        "name": "you may not take what is not yours",
        "phase": rulebooks.CHECK,
        "action": TAKE,
        "scope": {rulebooks.WORLD: True},
        "about": "direct",
        "when": [{"subject": "direct", "unbound": False},
                 {"subject": "direct", "owned_by": conditions.SOMEBODY}],
        "conditions": [{"subject": "direct", "owned_by": "actor"}],
        "listed": False,
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
#: The roles a placement verb may name, all of them optional. See below.
_PLACEMENT_ROLES = [
    {"role": role, "access": "touchable", "optional": True}
    for role in ("direct", "container", "target", "source")
]

DECLARED = (
    {
        # `despite: acting` because reading the world is not acting on it, and
        # because the alternative is a player with no output at all. "You must
        # be able to act" applies to every action, so a character who has been
        # killed, tied up or gagged could not look at the room they were stuck
        # in -- and a game that answers every single thing you type with the
        # same refusal has stopped telling you anything, including how you got
        # there.
        #
        # This gives up nothing a world wanted. Darkness, a ghost and the right
        # spectacles are all `visible_to` and a check rule, which is per object
        # and reversible; a world that means "the dead see nothing" has a
        # sharper tool for it than the universal gate. See 8.1.
        "action": LOOK,
        "means": "to take in what something looks like",
        "despite": ["acting"],
        "applies_to": [{"role": "direct", "access": "visible",
                        "optional": True}],
    },
    # The placement verbs, whose shape the engine also knows, and which are
    # declared here for a sharper reason than looking's.
    #
    # `world.relations` answers every one of them when the nouns really are a
    # thing and somewhere to put it, and hands back the rest -- "put out the
    # fire", "drop the subject" -- for a world to make sense of. So what
    # reaches the rulebooks is always the leftovers, and `actions.observe`
    # would read an arity off *those*: "put out the fire" names a source and no
    # direct object, so `put` was declared as needing a source, and "put the
    # coins in the pouch" was answered "Put from what?" ever after.
    #
    # Every role optional, because the mechanic has already taken every attempt
    # whose roles were the ordinary ones. What is left for a rule is a figure
    # of speech, and a figure of speech has no arity worth insisting on.
    {
        "action": "put",
        "means": "to set something down somewhere, or whatever else this "
                 "world means by it",
        "applies_to": _PLACEMENT_ROLES,
    },
    {
        "action": "place",
        "means": "to set something down somewhere",
        "applies_to": _PLACEMENT_ROLES,
    },
    {
        "action": "insert",
        "means": "to put something inside something else",
        "applies_to": _PLACEMENT_ROLES,
    },
    # Giving, declared for the sharper of the two reasons above. The mechanic
    # in `world.ownership` answers every attempt whose nouns really are a
    # thing and somebody to hand it to, and hands back the rest -- "give up",
    # "give a speech", "give the door a shove" -- so what reaches the
    # rulebooks is always the leftovers, and an arity read off *those* would
    # have the game answering "Give to what?" to somebody giving up.
    {
        "action": GIVE,
        "means": "to hand something to somebody, or whatever else this world "
                 "means by it",
        "applies_to": [
            {"role": "direct", "access": "carried", "optional": True},
            {"role": "target", "access": "visible", "optional": True},
        ],
    },
)


def seed(world_root):
    """
    Make sure a world has the standard rules. Cheap to call, safe to repeat.

    Returns what was added, which is nothing after the first time -- and
    everything again the first time after these rules are corrected, which is
    what VERSION is for.
    """
    if not world_root:
        return []
    # And the times of day, which every world has because every world has a
    # clock. Once, with their own mark, so a world that renamed night keeps
    # its own word. See world/clock.py.
    from world import clock

    clock.seed_periods(world_root)
    held = int(getattr(world_root.db, VERSION_ATTR, 0) or 0)
    if getattr(world_root.db, SEEDED, False) and held >= VERSION:
        return []
    from world import actions

    # What this world decided about the last edition's rules, read before they
    # go. See `_decisions`.
    decided = _decisions(world_root)
    if held < VERSION:
        _retire(world_root)
    for spec in DECLARED:
        actions.declare(world_root, spec["action"],
                        applies_to=spec["applies_to"],
                        means=spec.get("means", ""),
                        despite=spec.get("despite", ()))
    added = [rulebooks.add(world_root, dict(
                 rule, source="standard",
                 listed=decided.get(rule["name"], rule.get("listed", True))))
             for rule in STANDARD]
    setattr(world_root.db, SEEDED, True)
    setattr(world_root.db, VERSION_ATTR, VERSION)
    return added


def _decisions(world_root):
    """
    {name: listed} for the standard rules a world holds now.

    `rules suspend` and `rules restore` are a world's own decisions about the
    engine's rules, and a new edition is not a reason to undo them. That used
    to happen: `_retire` deletes the old copies and the new ones arrived in
    force, so a world that had suspended a standard rule found it back the
    next time this file changed. It matters most for the rule that ships
    suspended, where restoring it is how a world says what sort of place it
    is. Matched by name, which is what a rule is to anybody reading `rules`;
    a rule renamed between editions is a new rule, and gets its new default.
    """
    return {str(rule.get("name") or ""): bool(rule.get("listed", True))
            for rule in rulebooks.all_rules(world_root)
            if is_standard(rule)}


def _retire(world_root):
    """
    Drop what the last edition seeded, so the current one can land.

    Deleted rather than unlisted, because an unlisted rule is a proposal
    somebody may accept and these are not proposals -- they are a superseded
    copy of what this file says, and leaving them in `rules` to be read would
    be worse than the bug being fixed. Nothing but `source: "standard"` is
    touched: what a world wrote for itself is its own.

    The declarations go with them, and have to. `actions.declare` is
    first-answer-wins on purpose -- an arity is what every rule about an action
    was written against -- so a world that guessed `put` before this file
    declared it would keep the guess for ever, which is the bug rather than the
    fix. Only the actions named in DECLARED are dropped, and only their
    declaration: no rule about them is touched.
    """
    from evennia.utils.dbserialize import deserialize
    from world import actions, verbs

    store = dict(deserialize(getattr(world_root.db, rulebooks.ATTR, None))
                 or {})
    keeping = {rule_id: rule for rule_id, rule in store.items()
               if not is_standard(rule)}
    if len(keeping) != len(store):
        setattr(world_root.db, rulebooks.ATTR, keeping)

    declared = dict(getattr(world_root.db, actions.ATTR, None) or {})
    ours = {verbs.canonical_verb(spec["action"]) for spec in DECLARED}
    left = {name: entry for name, entry in declared.items() if name not in ours}
    if len(left) != len(declared):
        setattr(world_root.db, actions.ATTR, left)


def is_standard(rule):
    """Whether a rule came with the world rather than being learned in it."""
    try:
        return str(rule.get("source") or "") == "standard"
    except AttributeError:
        return False
