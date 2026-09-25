"""
What a thing is worth to whoever has it, as a form.

`world/gear.py` is explicit that this is the whole of how armour, weapons and
tools are worth anything -- a breastplate is not a description of protection,
it *is* the protection -- and `gear.prompt_block` has told every generator how
to declare one since long before a person could. A world built by hand could
make a sword and could not make a good one.

Three fields, and they are one idea rather than three, which is why they are
here together rather than written out in each of the four forms that want
them: what it grants, what has to be true of the *holding* for it to count,
and what has to be true of the *thing*.

**`present` is the odd one and the reason rooms are here too.** The other
three are about somebody's belongings; `present` is about being in the room at
all, for everybody in it. A fire warms whoever lit it and whoever walked in
afterwards, and stops the moment they leave -- so a room may carry bonuses of
its own, and a forge is warm whether or not anything in it is. A room's are
always `present`, so its form does not ask.
"""

from world import gear, making, menus

#: How each condition reads where somebody is choosing one. `gear.CONDITIONS`
#: is the list; these are the sentences, kept beside the form that shows them.
WHEN_SAID = {
    "worn": "while it is worn -- armour, rings, a heavy cloak",
    "wielded": "while it is in a hand -- weapons, tools, a lantern held up",
    "carried": "while it is carried at all, even in a pack",
    "present": "for everybody in the room with it -- a fire, a lamp",
}


def _root(ctx):
    return making.root_of(ctx)


def trait_options(ctx):
    from world.makers import vocabulary

    return [(value, label) for value, label, _help
            in vocabulary.attribute_entries(_root(ctx))]


def state_options(ctx):
    from world import verbs

    return [(slug, f"{slug} -- {entry.get('means') or ''}".rstrip(" -"))
            for slug, entry in sorted((verbs.vocabulary(_root(ctx))
                                       or {}).items())]


def _keep_bonus(ctx):
    trait = str(ctx.draft.get("trait") or "").strip()
    if not trait:
        raise menus.Refuse("Name an attribute.")
    try:
        amount = float(ctx.draft.get("amount"))
    except (TypeError, ValueError):
        raise menus.Refuse("How much is it worth?")
    if not amount:
        raise menus.Refuse(
            "A bonus of nothing is not a bonus. Leave it out instead.")
    return ({"trait": trait, "amount": amount},
            f"{trait} {'+' if amount > 0 else ''}{amount:g}")


NEW_BONUS = menus.Form(
    key="new-bonus", title="What it is worth", guided=True,
    intro="One attribute, and how much this thing is worth to it.",
    items=[
        making.picker("trait", "Which attribute", "attribute",
                      options=trait_options, required=True,
                      help="What it makes its owner better or worse at. Only "
                           "an attribute this world measures: half the armour "
                           "in a world measuring defence and the other half "
                           "measuring protection measures nothing."),
        menus.Field("amount", "How much", kind=menus.NUMBER, required=True,
                    help="Negative is as real as positive. Mail that costs "
                         "stealth is a better item than one that only gives."),
        making.keeper("keep", "Keep it", _keep_bonus),
    ],
)


def bonus_line(ctx, entry):
    amount = entry.get("amount") or 0
    return f"{entry.get('trait')} {'+' if amount > 0 else ''}{amount:g}"


def items(present_only=False):
    """
    The three fields, for a form that makes something worth having.

    `present_only` is a room: its bonuses are for everybody standing in it and
    could not be anything else, so it is told rather than asked.
    """
    found = [making.listing_field(
        "trait_bonuses", "What it is worth", NEW_BONUS, bonus_line,
        add_label="Add what it is worth", empty="nothing in particular",
        help="What it does for whoever has it. Leave it empty for an ordinary "
             "thing -- most things are ordinary, and a world where every "
             "teacup grants something measures nothing.")]
    if present_only:
        return found
    found.append(menus.Field(
        "bonus_when", "When it counts", kind=menus.CHOICE,
        lock=_has_bonuses,
        choices=lambda ctx: [menus.Choice(name, WHEN_SAID.get(name, name))
                             for name in gear.CONDITIONS],
        help="What has to be true of the holding. `carried` is for charms and "
             "burdens only: a thing that works from inside a pack lets "
             "somebody carry six of them."))
    found.append(making.picker(
        "bonus_while", "And only while it is", "condition",
        options=state_options, lock=_has_bonuses,
        help="A condition the thing itself must be in first: a lamp is worth "
             "nothing until it is lit, a brazier nothing until it burns. "
             "Left empty, it is always worth what it is worth."))
    return found


def _has_bonuses(ctx):
    """Nothing to say about when a bonus counts until there is one."""
    return bool(ctx.draft.get("trait_bonuses"))


def spec(draft):
    """
    What was filled in, as the three fields `clothing.create` reads.

    `{}` when nothing was: an item with no bonuses must not arrive carrying an
    empty map and a condition, because `gear.bonuses` reads the map's presence
    as a claim that this is a thing worth having.
    """
    granted = {}
    for entry in (draft.get("trait_bonuses") or []):
        try:
            trait = str(entry.get("trait") or "").strip()
            amount = float(entry.get("amount") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if trait and amount:
            granted[trait] = amount
    if not granted:
        return {}
    found = {"trait_bonuses": granted}
    when = str(draft.get("bonus_when") or "").strip().lower()
    if when in gear.CONDITIONS:
        found["bonus_when"] = when
    gate = str(draft.get("bonus_while") or "").strip().lower()
    if gate:
        found["bonus_while"] = gate
    return found


def drafted(obj):
    """The other way: what a thing already carries, as a draft to edit."""
    granted = {}
    try:
        granted = dict(getattr(obj.db, "trait_bonuses", None) or {})
    except (AttributeError, TypeError, ValueError):
        granted = {}
    return {
        "trait_bonuses": [{"trait": slug, "amount": amount}
                          for slug, amount in sorted(granted.items())],
        "bonus_when": gear.condition(obj) if granted else "",
        "bonus_while": gear.gated_by(obj) if granted else "",
    }


def write(obj, draft, present_only=False):
    """
    Put what was filled in onto a thing that already exists, and recount.

    Recounting matters and is easy to forget: what gear is worth is derived
    from scratch rather than accumulated (`gear.recompute`), so a bonus
    written onto something already in somebody's hands is worth nothing at all
    until something asks again.
    """
    found = spec(draft)
    if not found:
        obj.attributes.remove("trait_bonuses")
        obj.attributes.remove("bonus_when")
        obj.attributes.remove("bonus_while")
    else:
        obj.db.trait_bonuses = found["trait_bonuses"]
        if present_only:
            obj.db.bonus_when = "present"
        elif found.get("bonus_when"):
            obj.db.bonus_when = found["bonus_when"]
        if found.get("bonus_while"):
            obj.db.bonus_while = found["bonus_while"]
        else:
            obj.attributes.remove("bonus_while")
    _recount(obj)
    return said(obj)


def _recount(obj):
    from evennia.objects.objects import DefaultCharacter

    holder = getattr(obj, "location", None)
    try:
        if isinstance(holder, DefaultCharacter) or gear.is_person(holder):
            gear.recount_around(holder, item=obj)
        elif holder is not None:
            gear.recompute_room(holder)
    except Exception:
        from evennia.utils import logger

        logger.log_trace("gearing: could not recount what this is worth")


def said(obj):
    """What a thing is worth, as one line."""
    granted = dict(getattr(obj.db, "trait_bonuses", None) or {})
    if not granted:
        return "It is worth nothing in particular."
    listed = ", ".join(f"{slug} {'+' if amount > 0 else ''}{amount:g}"
                       for slug, amount in sorted(granted.items()))
    when = WHEN_SAID.get(gear.condition(obj), gear.condition(obj))
    gate = gear.gated_by(obj)
    return (f"Worth {listed}, {when}"
            + (f", and only while it is {gate}" if gate else "") + ".")
