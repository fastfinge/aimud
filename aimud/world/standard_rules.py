"""
Making sure a world has its rules before anything reads them.

Inform ships a Standard Rules extension holding dozens of named check rules --
"can't take what's fixed in place", "can't insert into closed containers" --
and they are the reason an author writes so little. Every game gets the
obvious refusals without anybody restating them, and an author's own rules
compose on top rather than starting from nothing.

This game had been restating them. "You must be holding it" appears in 54
`holds` clauses across the exported corpus, each separately invented by a
model. So the same eight rules were written here once, by hand, and seeded
into every world.

**They are data now**, in `world/rulesets/default.json`, and they are one
ruleset among several. What moved them was noticing that the list this module
seeded was not all of one kind: "you must be able to reach what you act on" is
true of every world that could exist, and `life_status` -- with `dead` and
`prevents_acting` -- was being seeded into a world about a dinner party.
Separating the two is what `world.rulesets` is for.

What is left here is the doorway. `rulebooks.for_attempt` and `rules_subject`
have always called `seed` before reading a world's rules, and what that means
has not changed: by the time anything reads them, they are there.
"""

#: Marks a world as having been through here. Kept because worlds in play
#: carry it, and because it is the cheapest possible answer to "has this world
#: ever been seeded" for anything that only wants to know that.
SEEDED = "standard_rules_seeded"

#: What the default ruleset was called when it was the only one.
VERSION_ATTR = "standard_rules_version"


def seed(world_root):
    """
    Make sure a world has the rulesets it was built with. Safe to repeat.

    Returns what was added: nothing after the first time, and everything again
    the first time after a ruleset is corrected. See `world.rulesets.seed`.
    """
    if not world_root:
        return []
    # The times of day, which every world has because every world has a clock.
    # Once, with their own mark, so a world that renamed night keeps its own
    # word. See world/clock.py. Deliberately not a ruleset: a world with no
    # clock at all is not a kind of game anybody has asked for.
    from world import clock, rulesets

    clock.seed_periods(world_root)
    added = rulesets.seed(world_root)
    setattr(world_root.db, SEEDED, True)
    return added


def is_standard(rule):
    """
    Whether a rule came with the world rather than being learned in it.

    True for any ruleset's rule, not only the default one. That is the
    question every caller was really asking -- `rules` lists a world's own
    inventions separately, `item_gen` counts what a world made up for itself
    -- and a rule a world was built with is not that, whichever ruleset put it
    there.
    """
    from world import rulesets

    return rulesets.from_ruleset(rule)
