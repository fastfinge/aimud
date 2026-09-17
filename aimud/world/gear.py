"""
What a thing does for the person carrying it.

Traits say what is measurably true of a character, and until now the only way
one moved was a verb effect: drinking the potion raised your strength, and
raised it for good. That leaves no way to say the obvious thing about a
breastplate, which is not that wearing it makes you permanently tougher but
that you are tougher *while you have it on*. Without that, armour and weapons
are description with nothing behind them.

So an item may carry `trait_bonuses` -- {slug: amount} -- and a `bonus_when`
saying what has to be true for them to count: worn, wielded, or merely
carried. Everything else here follows from two decisions.

**The total is derived, never accumulated.** Putting a helmet on does not add
two to anything. It recalculates, from scratch, the whole of what this
character's gear is worth, and writes that to the trait's `mod` -- the field
the traits contrib keeps precisely so that something can be true of a
character conditionally, without touching the figure they have earned. A
number that is added on wear and subtracted on removal is a number that drifts
the first time anything is missed; a number that is recomputed cannot.

**Wielding is a mechanic, like wearing.** The generators have been offering a
"wieldable" affordance since long before anything could be wielded. `handle`
takes the wielding verbs before an attempt reaches a model, exactly as the
clothing layer takes `wear`, so that no world invents its own private meaning
for holding a sword -- and declines anything that is not really about
wielding, so "draw the curtain" goes on through the ordinary pipeline.
"""

from evennia.utils import logger

#: When an item's bonuses count.
#:
#: worn    -- a garment, and it is on. Armour, rings, a heavy cloak.
#: wielded -- in a hand. Weapons, tools, a lantern held up.
#: carried -- anywhere about the person. For charms and burdens only: a thing
#:            that works from inside a pack is the exception, not the rule,
#:            and left to itself it lets somebody carry six of them.
#: present -- in the same room, and doing it for everybody there: lying about,
#:            or in the hands of anybody standing in it. A fire warms whoever
#:            is by it, whoever lit it and whoever walked in afterwards, and
#:            stops the moment they leave. A candle does the same whether it
#:            stands on the table or somebody picks it up. This is the one
#:            condition that is not about a person's belongings at all, which
#:            is why a room may carry bonuses of its own: a forge is warm
#:            whether or not anything in it is.
CONDITIONS = ("worn", "wielded", "carried", "present")

DEFAULT_CONDITION = "carried"

#: The affordance that makes something wieldable: the verb itself, since
#: `world.affordances` made affordances and verbs one vocabulary. "wieldable"
#: and "wield" had been the same idea in two namespaces that never met.
WIELDABLE = "wield"

#: How many things can be in hand at once. Two, because there are two hands;
#: a sword and a shield is the case this exists for.
WIELD_LIMIT = 2

#: The verbs this module owns, when the noun really is something to wield.
#:
#: "hold" is here because it means both things at once and only one of them is
#: a mechanic. Holding a sword is wielding it; holding somebody's hand is not,
#: and `handle` below tells them apart by the noun rather than the verb -- a
#: person is not wieldable, so that attempt declines and goes on to be learned
#: as the social verb it is.
VERBS = ("wield", "unwield", "hold")

#: The ones that can only mean this. "wield" is not English for anything else,
#: and `VERB_SYNONYMS` folds "brandish" and "equip" onto it precisely because
#: they are not either -- the table's own comment says so, and leaves "sheathe"
#: and "draw" alone for being genuinely ambiguous.
#:
#: Which matters because the noun test below is a test of what a world has
#: happened to say. A thing is wieldable if its kind's affordance map holds
#: `wield`, and most kinds say nothing at all: a lantern, a crowbar, a torch
#: and a broom all come out of the generators with an empty map, because the
#: taxonomy floor only speaks for weapons. Applying the test to "wield" meant
#: `wield the crowbar` declined the mechanic and bought a model call to invent
#: a meaning for a word the game already answers. Only "hold" needs asking
#: about, and only "hold" is asked.
UNAMBIGUOUS = ("wield", "unwield")


def prompt_block(world_root):
    """
    How to declare what an item is worth, for any generator that makes one.

    One text in one place because four different generators can produce an
    object -- a room's contents, a fixture reached for, a character's outfit,
    a verb that conjures something -- and a world where only some of them can
    arm a character is worse than one where none of them can.

    It ends by pointing at the world's trait register rather than pasting it
    in. `list_traits` answers when a bonus needs a name, and a bonus naming a
    trait nothing measures is sent back by whichever finish tool took it --
    which is what stops half the armour in a world measuring "protection"
    while the other half measures "defence".
    """
    return (
        "trait_bonuses is what this item does for whoever has it, as\n"
        '{"trait": amount} — {"defence": 2}, {"stealth": -1}. This is the\n'
        "whole of how armour, weapons and tools are worth anything: a\n"
        "breastplate is not a description of protection, it IS the protection.\n"
        "Give it to anything that would plainly make its owner better or worse\n"
        "at something, and leave it out for ordinary objects — most things are\n"
        "ordinary, and a world where every teacup grants something measures\n"
        "nothing. Negative amounts are as real as positive: mail that costs\n"
        "stealth is a better item than one that only gives.\n\n"
        "bonus_when says what has to be true for it to count:\n"
        "  worn    — a garment, and it is on. Armour, rings, a heavy cloak.\n"
        "  wielded — held in a hand. Weapons, tools, a raised lantern.\n"
        "  carried — merely about the person. Charms only; prefer the others,\n"
        "            or somebody will carry six of them at once.\n"
        "  present — in the room, and doing it for everybody there, whether\n"
        "            it lies about or somebody carries it. A fire, a stove, a\n"
        "            candle, a draughty window. This is the one that works on\n"
        "            people who never touched it, and it stops the moment they\n"
        "            leave the room.\n"
        "An item given trait_bonuses and no bonus_when is judged by its own\n"
        "affordances, so a wearable thing counts when worn and a wieldable one\n"
        "when held.\n\n"
        "bonus_while names a state the thing must be in before it is worth\n"
        "anything: a lantern is only worth light while it is \"lit\", a stove\n"
        "only warms while \"burning\". Leave it out for anything that works by\n"
        "simply existing, which is most things. Use it whenever the object has\n"
        "a condition that could be turned off — otherwise a lamp in a pack\n"
        "shines as brightly as one alight.\n\n"
        "list_traits shows the traits this world measures; a bonus names "
        "one of those, or light.\n\n"
        "light is the one the game reads by name. A lamp, a torch, a candle\n"
        "or a burning brazier gives {\"light\": 1} — with bonus_while \"lit\",\n"
        "so that it shines only while it burns. Nothing else need say anything\n"
        "about light: darkness is what is left where none is given.\n\n"
    )


# ---------------------------------------------------------------------------
# What an item claims
# ---------------------------------------------------------------------------

def bonuses(obj):
    """{slug: amount} this item is worth, if it is worth anything."""
    if obj is None:
        return {}
    stored = obj.db.trait_bonuses
    if not stored:
        return {}
    found = {}
    try:
        items = stored.items()
    except AttributeError:
        return {}
    for slug, amount in items:
        try:
            found[str(slug)] = float(amount)
        except (TypeError, ValueError):
            continue
    return found


def wieldable(obj):
    """True for something that can be taken in hand."""
    if obj is None:
        return False
    from world import verbs

    return WIELDABLE in verbs.affordances(obj)


def condition(obj):
    """
    What has to be true for this item's bonuses to count.

    A model that declared one is believed. One that did not gets the answer
    its own affordances imply, because an item described as a breastplate and
    given a bonus plainly means it to apply when worn, and refusing to guess
    would only mean the bonus never applied at all.
    """
    from world import clothing

    declared = str(obj.db.bonus_when or "").strip().lower()
    if declared in CONDITIONS:
        return declared
    if clothing.wearable(obj):
        return "worn"
    if wieldable(obj):
        return "wielded"
    return DEFAULT_CONDITION


def gated_by(obj):
    """The state this item must be in before it is worth anything, or ""."""
    return str(getattr(obj.db, "bonus_while", "") or "").lower().strip()


def _gate_open(obj):
    """
    Whether a thing that only counts in some condition is in it.

    An unlit lantern lights nobody, and that could not be said before: a bonus
    applied whenever the thing was held, so a lamp in a pack was as good as one
    burning. The gate names a state, and states are what the game already uses
    for a condition that comes and goes.
    """
    from world import verbs

    wanted = gated_by(obj)
    return not wanted or wanted in verbs.states(obj)


def applies(obj, character):
    """True when this item is doing something for this character right now."""
    if obj is None or not bonuses(obj) or not _gate_open(obj):
        return False

    where = condition(obj)
    if where == "present":
        # Not a belonging at all: it works for everybody in the room with it,
        # and the room itself is allowed to be such a thing. So is a candle in
        # somebody's hand -- picking it up does not put it out for the rest of
        # the room, nor for the person holding it.
        room = getattr(character, "location", None)
        if room is None:
            return False
        holder = obj.location
        return (obj is room or holder is room
                or (holder is not None and holder.location is room
                    and is_person(holder)))

    if obj.location is not character:
        return False
    if where == "worn":
        return bool(obj.db.worn)
    if where == "wielded":
        return bool(obj.db.wielded)
    return True


# ---------------------------------------------------------------------------
# Wielding
# ---------------------------------------------------------------------------

def wielded(character):
    """Everything this character has in hand, oldest first."""
    if character is None:
        return []
    return sorted(
        (obj for obj in character.contents if obj.db.wielded),
        key=lambda o: o.id,
    )


def _event(character, verb, obj, template, **roles):
    """
    One thing somebody did with what they are wearing or holding.

    The room's half as an event rather than a sentence, so that each person
    watching is told in their own words -- and the verb as `$pconj(...)`, so
    that it agrees with whoever did it. See `world.events`.
    """
    from world import events

    return events.Event(actor=character, verb=verb,
                        roles={"direct": obj, **roles},
                        room_template=template)


def wield(character, obj):
    """Take something in hand. Returns (ok, actor_text, event)."""
    name = obj.get_display_name(character)

    if obj.location is not character:
        return False, f"You are not carrying {name}.", None
    if obj.db.wielded:
        return False, f"You are already wielding {name}.", None
    if obj.db.worn:
        return False, f"You would have to take {name} off first.", None

    in_hand = wielded(character)
    if len(in_hand) >= WIELD_LIMIT:
        busy = ", ".join(o.get_display_name(character) for o in in_hand)
        return False, f"Your hands are full: {busy}.", None

    obj.db.wielded = True
    recompute(character)
    return (True, f"You take {name} in hand.",
            _event(character, "wield", obj, "{actor} $pconj(take) {direct} in hand."))


def unwield(character, obj):
    """Stop holding something. Returns (ok, actor_text, event)."""
    name = obj.get_display_name(character)
    if not obj.db.wielded:
        return False, f"You are not wielding {name}.", None

    obj.attributes.remove("wielded")
    recompute(character)
    return (True, f"You lower {name}.",
            _event(character, "unwield", obj, "{actor} $pconj(lower) {direct}."))


def release(obj, character=None):
    """
    Stop this item counting for anybody, because it has left their hands.

    Called when a thing is dropped, given away, or destroyed. Separate from
    `unwield` because nobody chose it and there is nothing to narrate.
    """
    if obj is not None and obj.db.wielded:
        obj.attributes.remove("wielded")
    if character is not None:
        # Only discounted while it is still on them. Dropping and giving call
        # this once the thing has gone, and a candle set down on the floor is
        # still lighting the room -- ignoring it there put the light out a
        # moment after the room had counted it.
        still_held = obj is not None and obj.location is character
        recompute(character, ignoring=obj if still_held else None)


def recount_around(holder, item=None):
    """
    Redo the sums that `item` coming into or going out of `holder` changed.

    Called once the move is over, from both ends of it, so the sums are only
    ever done on where things really are. Done while a thing was halfway out
    of the door, a candle being picked up was discounted by the room it was
    leaving and counted again by the hand it arrived in, and whoever held it
    was told their light fell and rose over one move.

    A room is everybody in it. A person is themselves -- unless the thing is
    one that works for the whole room, in which case it is the whole room,
    because a candle taken out of a pack lights everybody standing there.
    """
    if holder is None:
        return
    from evennia.objects.objects import DefaultRoom

    if isinstance(holder, DefaultRoom):
        recompute_room(holder)
        return
    room = getattr(holder, "location", None)
    if (item is not None and room is not None and is_person(holder)
            and condition(item) == "present" and bonuses(item)):
        recompute_room(room)
        return
    recompute(holder)


def handle(caller, verb, bound, on_message):
    """
    Deal with a wielding verb, or decline it. True when it was handled.

    Declining is half the job, and the reason this is not simply a pair of
    commands. "hold the door" and "hold her hand" are ordinary verbs that a
    world is entitled to work out for itself, so an attempt on a noun this
    world does not think of as something to take in hand goes on through.

    Only the ambiguous verb is asked that question. "Wield" means one thing in
    English and the noun test was refusing it for lanterns and crowbars, whose
    kinds simply never said. See `UNAMBIGUOUS`.
    """
    if verb not in VERBS:
        return False

    obj = bound.get("direct")
    if obj is None:
        return False

    if verb == "unwield":
        # Nothing else can mean this about a thing already in hand.
        if not obj.db.wielded:
            return False
        _deliver(on_message, unwield(caller, obj))
        return True

    if (verb not in UNAMBIGUOUS
            and not wieldable(obj) and not bonuses(obj)):
        # "Hold" said of something this world does not think of as a thing to
        # take in hand -- somebody's hand, a door, a note -- means the other
        # thing it means. Let the model decide what.
        return False
    _deliver(on_message, wield(caller, obj))
    return True


def _deliver(on_message, outcome):
    _ok, actor_text, event = outcome
    on_message(actor_text, event)


# ---------------------------------------------------------------------------
# Working out what it all adds up to
# ---------------------------------------------------------------------------

def is_person(obj):
    """Whether something carries things about with it: a character or an NPC."""
    from world.quests import is_person as person

    return obj is not None and person(obj)


def _around(character):
    """
    Everything that could be worth something to this character.

    What they carry, and then what is simply here. A room contributes as a
    thing in its own right -- a forge is warm on its own account -- and so does
    anything lying in it, or in the hands of anybody standing in it, that says
    it works for whoever is present.
    """
    room = getattr(character, "location", None)
    found = list(character.contents)
    if room is not None:
        found.append(room)
        for obj in room.contents:
            found.append(obj)
            if obj is not character and is_person(obj):
                found.extend(obj.contents)
    return found


def total(character, ignoring=None):
    """{slug: amount} every piece of gear on this character is worth."""
    from world import traits

    world_root = traits._world_root(character)
    found = {}
    for obj in _around(character):
        if obj is ignoring or obj is character or not applies(obj, character):
            continue
        for slug, amount in bonuses(obj).items():
            slug = traits.resolve(world_root, slug)
            if not slug:
                continue
            found[slug] = found.get(slug, 0.0) + amount
    # And what they are in: a state may be worth something too, set or worked
    # out, which is how "starving costs 3 strength" lives on `starving`
    # rather than in every rule that could leave somebody hungry.
    for _state, granted in _state_sources(character, world_root):
        for slug, amount in granted.items():
            slug = traits.resolve(world_root, slug)
            if not slug:
                continue
            found[slug] = found.get(slug, 0.0) + amount
    return found


def _state_sources(character, world_root):
    """[(state, {trait: amount})] for each state this person is in that counts."""
    from world import verbs

    worth = verbs.state_bonuses(world_root)
    if not worth:
        return []
    held = verbs.implied_states(character, world_root)
    return [(state, worth[state]) for state in sorted(worth) if state in held]


def recompute_room(room, ignoring=None):
    """
    Redo the sums for everybody standing here.

    Two things make this necessary and neither of them is a timer. Somebody
    arrives or leaves, and their own totals change -- that is `recompute` on
    one person. But a fire being lit changes what the room is worth to
    everyone already in it, and there is nobody to hang that on.

    Still a checkpoint rather than a tick: it runs when a thing changes, not
    while it stays changed. A room where nothing happens costs nothing, which
    is the same bargain the rest of the game makes.

    `ignoring` is a **person** who is leaving, and need not be recounted
    because they are about to be recounted where they arrive. There is no
    item to discount: moves are recounted once they are over (see
    `recount_around`), when a lamp carried out is no longer here to count.
    """
    if room is None:
        return
    for obj in list(room.contents):
        if obj is not ignoring and is_person(obj):
            recompute(obj)


def recompute(character, ignoring=None):
    """
    Work out afresh what this character's gear is worth, and write it down.

    `ignoring` is for the moment a thing is leaving: Evennia announces a
    departure before it happens, so the item is still in `contents` when we
    are told it is going.

    Every trait is rewritten, not only the ones something is bonusing now, so
    that taking the helmet off removes exactly what putting it on added and no
    accounting is kept anywhere. What the register says a trait is modified by
    on its own is preserved underneath -- gear adds to that, it does not
    replace it.
    """
    from world import traits

    if not traits.has_traits(character):
        return {}

    world_root = traits._world_root(character)
    found = total(character, ignoring=ignoring)

    # A bonus for a figure this character has never had gives them the figure.
    # Otherwise a first suit of armour would raise a defence they do not have
    # and nothing would come of it.
    for slug in found:
        traits.ensure(character, slug, world_root=world_root)

    for slug, trait in traits.all_of(character):
        base = (traits.known(world_root, slug) or {}).get("mod") or 0
        try:
            wanted = float(base) + found.get(slug, 0.0)
        except (TypeError, ValueError):
            continue
        if getattr(trait, "mod", None) == wanted:
            continue
        try:
            trait.mod = wanted
        except Exception as exc:
            logger.log_info(
                f"gear: could not modify {slug!r} on {character.key}: {exc}"
            )

    # The character is told what changed by the same path that reports a
    # poison wearing off: the figures moved, and they should notice.
    traits.notice_changes(character)
    return found


def sources(character, slug):
    """
    What is granting this character a figure, and by how much.

    For `score`, so that a defence of 9 says where the other four came from
    rather than looking like something the character was simply born with.

    Which means it has to look exactly where `total()` looks. A `present`
    source is not a belonging -- the room itself, or a fire burning in it --
    and leaving those out would put the warmth in the figure and nothing
    beside it to explain the warmth, which is the one failure this exists to
    prevent.
    """
    from world import traits

    world_root = traits._world_root(character)
    slug = traits.resolve(world_root, slug)
    found = []
    for obj in _around(character):
        if obj is character or not applies(obj, character):
            continue
        for granted, amount in bonuses(obj).items():
            if traits.resolve(world_root, granted) == slug and amount:
                found.append((obj.get_display_name(character), amount))
    for state, granted in _state_sources(character, world_root):
        for trait, amount in granted.items():
            if traits.resolve(world_root, trait) == slug and amount:
                found.append((f"being {state.replace('_', ' ')}", amount))
    return sorted(found)


def _signed(amount):
    """A bonus as a person would write it: +3, -1, +2.5."""
    from world import traits

    text = traits._round(amount)
    return text if text.startswith("-") else f"+{text}"


def describe(character, slug):
    """The gear behind a figure as one short phrase, or "" if there is none."""
    found = sources(character, slug)
    if not found:
        return ""
    return ", ".join(f"{name} {_signed(amount)}" for name, amount in found)
