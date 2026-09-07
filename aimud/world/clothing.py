"""
Wearing things.

Evennia's clothing contrib provides the mechanism -- worn flags, covering, how
many hats one head will take. This module is the game's own layer over it, and
exists for three reasons the contrib does not cover.

* One path for everyone. A player types `wear coat` and an NPC decides to put
  its coat on; both end up in `put_on` here, so an NPC is dressed by the same
  rules a player is, and the room hears the same sentence either way.

* Clothing is never a learned verb. Everything else a character does is
  worked out by a model and cached as a rule; wearing is not, because it is
  already a mechanic. `handle` catches the clothing verbs before an attempt
  reaches the model, exactly as following is caught, so no world ever invents
  its own private meaning for "wear".

* Appearance follows the wardrobe. A description says what is permanently true
  of a body; what someone has on is added to it from the garments they are
  actually carrying. Change your clothes and you look different, with nothing
  rewriting your description to say so.
"""

from evennia.contrib.game_systems.clothing.clothing import (
    CLOTHING_OVERALL_LIMIT,
    CLOTHING_TYPE_LIMIT,
    CLOTHING_TYPE_ORDER,
    WEARSTYLE_MAXLENGTH,
    ContribClothing,
    get_worn_clothes,
    single_type_count,
)
from evennia.utils import inherits_from, iter_to_str

#: The affordance that makes an item a garment. Every generator that can
#: produce an object offers it, so a coat found in a wardrobe is as wearable
#: as one a character was born in.
WEARABLE = "wearable"

#: The kinds of garment the contrib knows how to order and limit. Given to the
#: models so what they invent lands in a slot the game understands; anything
#: else is kept as untyped clothing, which simply wears without limit.
GARMENT_TYPES = tuple(CLOTHING_TYPE_ORDER)

#: The verbs this module owns. An attempt at one of these never reaches a
#: model, so long as it is really about clothes.
VERBS = ("wear", "remove", "cover", "uncover")


def is_garment(obj):
    """True for something that already knows how to be worn."""
    return obj is not None and inherits_from(obj, ContribClothing)


def wearable(obj):
    """
    True for anything that ought to be wearable, garment or not yet.

    Affordances are the world's own word for what can be done with a thing,
    and an item the generators called wearable is a garment whether or not it
    was built as one -- so this is what decides whether the clothing verbs
    take an attempt over.
    """
    if obj is None:
        return False
    return is_garment(obj) or WEARABLE in {str(a).lower()
                                           for a in (obj.db.affordances or [])}


def as_garment(obj):
    """
    The same object, able to be worn, or None if it never could be.

    An item may be wearable by its affordances and still be a plain object:
    everything made before clothes existed is, and so is anything a generator
    marked wearable as an afterthought. Rather than refuse to put a coat on,
    the coat is made into a garment here, keeping its name, description and
    everything else. It happens once, the first time anyone tries.
    """
    if is_garment(obj):
        return obj
    if not wearable(obj):
        return None
    from typeclasses.clothing import Garment

    obj.swap_typeclass(Garment, clean_attributes=False, run_start_hooks=None)
    return obj


def typeclass_for(affordances):
    """
    The typeclass an item with these affordances should be created as.

    Called wherever the world makes an object -- room contents, a fixture
    reached for, an effect that conjures something -- so wearability is
    decided once, from what the item is, rather than by each generator.
    """
    from typeclasses.clothing import Garment
    from typeclasses.objects import Object

    wanted = {str(a).lower().strip() for a in (affordances or [])}
    return Garment if WEARABLE in wanted else Object


def worn_by(character, exclude_covered=True):
    """The garments a character has on, outermost kind first."""
    if character is None:
        return []
    return get_worn_clothes(character, exclude_covered=exclude_covered)


#: Endings that only look plural. A dress is one thing; boots are two.
_SINGULAR_TAILS = ("ss", "us", "is", "as", "ics")


def item_name(obj, looker=None):
    """
    An item as it reads in a sentence, article and all.

    Evennia works the article out from the name, and gets it wrong for the
    words clothing is full of: "a hobnailed boots", "an iron gauntlets". A
    name that is already plural takes no article at all, which is why the
    generators are asked for "pair of boots" when there really are two --
    that form articles correctly and this leaves it alone.
    """
    name = obj.key or ""
    last = name.rsplit(" ", 1)[-1].lower()
    if last.endswith("s") and not last.endswith(_SINGULAR_TAILS):
        return name
    return obj.get_numbered_name(1, looker, return_string=True)


def _garment_name(garment, looker=None):
    """A garment as it reads in a sentence, wear style and all."""
    name = item_name(garment, looker)
    style = garment.db.worn
    return f"{name} {style}" if isinstance(style, str) and style else name


def describe_outfit(character, looker=None):
    """
    What `character` is wearing, as a sentence, or "" if nothing shows.

    Silence rather than "is wearing nothing": most of what is looked at in
    this game is dressed, and a character whose garments failed to generate
    should read as undescribed, not as standing there naked.
    """
    garments = worn_by(character)
    if not garments:
        return ""
    names = iter_to_str([_garment_name(g, looker) for g in garments])
    return f"{character.get_display_name(looker)} is wearing {names}."


def appearance(character, base_desc, looker=None):
    """A description with the outfit appended -- what a look should show."""
    outfit = describe_outfit(character, looker)
    if not outfit:
        return base_desc or ""
    return f"{base_desc}\n\n{outfit}" if base_desc else outfit


def carried_by(character):
    """What a character is holding rather than wearing."""
    if character is None:
        return []
    return [obj for obj in character.contents
            if not obj.db.worn and getattr(obj, "destination", None) is None]


def own_appearance(character, base_desc):
    """
    A character's body and belongings, addressed to themselves.

    For an NPC's own prompt: a character who does not know they are in a
    bloodstained apron cannot mention it, take it off, or be embarrassed by
    it, and their clothes are the part of them that changes.
    """
    parts = [base_desc.strip()] if base_desc else []
    garments = worn_by(character)
    if garments:
        parts.append("You are wearing "
                     + iter_to_str([_garment_name(g, character) for g in garments])
                     + ".")
    held = carried_by(character)
    if held:
        parts.append("You are carrying "
                     + iter_to_str([item_name(o, character)
                                    for o in held])
                     + ".")
    return "\n".join(parts)


def display_things(character, looker=None, **kwargs):
    """
    The "is carrying" line for someone being looked at, garments excluded.

    Worn clothes are already named in the description, and a coat listed both
    as worn and as carried reads as two coats.
    """
    held = [obj for obj in carried_by(character)
            if obj is not looker and obj.access(looker, "view")]
    if not held:
        return ""
    grouped = {}
    for thing in held:
        grouped.setdefault(thing.get_display_name(looker, **kwargs), []).append(thing)

    names = []
    for label, things in sorted(grouped.items()):
        if len(things) == 1:
            names.append(item_name(things[0], looker))
            continue
        _singular, plural = things[0].get_numbered_name(len(things), looker, key=label)
        names.append(plural)
    return (f"\n{character.get_display_name(looker, **kwargs)} is carrying "
            f"{iter_to_str(names)}")


def inventory_line(character, looker=None):
    """
    "wearing x, y; carrying z" -- one line for a prompt.

    NPC prompts and quest prompts both need to know what people have on them,
    and both want it short.
    """
    parts = []
    garments = worn_by(character)
    if garments:
        parts.append("wearing "
                     + iter_to_str([_garment_name(g, looker) for g in garments]))
    held = carried_by(character)
    if held:
        parts.append("carrying "
                     + iter_to_str([item_name(o, looker)
                                    for o in held]))
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Putting things on and taking them off
# ---------------------------------------------------------------------------

def _refuse(text):
    return False, text, ""


def put_on(character, garment, wearstyle=True):
    """
    Wear a garment. Returns (worn, what the wearer is told, what the room sees).

    Every limit the contrib defines is checked here rather than in a command,
    so an NPC dressing itself cannot end up in four hats.
    """
    garment = as_garment(garment)
    if garment is None:
        return _refuse("That is not something you can wear.")
    if garment.location is not character:
        return _refuse("You would have to be holding that first.")
    if garment.db.worn:
        return _refuse(f"You are already wearing "
                       f"{item_name(garment, character)}.")

    already = worn_by(character, exclude_covered=False)
    if CLOTHING_OVERALL_LIMIT and len(already) >= CLOTHING_OVERALL_LIMIT:
        return _refuse("You cannot wear any more than you already have on.")

    kind = garment.db.clothing_type
    limit = CLOTHING_TYPE_LIMIT.get(kind) if kind else None
    if limit is not None and single_type_count(already, kind) >= limit:
        return _refuse(f"You are already wearing all the {kind} you can.")

    if isinstance(wearstyle, str):
        wearstyle = wearstyle.strip()[:WEARSTYLE_MAXLENGTH] or True

    # quiet: the contrib's own announcement names the garment without its
    # article, and the room should hear one voice for this whether a player or
    # a character put the coat on.
    garment.wear(character, wearstyle, quiet=True)

    label = _garment_name(garment, character)
    name = character.get_display_name(character)
    covered = [g for g in character.contents if g.db.covered_by is garment]
    tail = f", covering {iter_to_str([_garment_name(g, character) for g in covered])}" \
        if covered else ""
    return True, f"You put on {label}{tail}.", f"{name} puts on {label}{tail}."


def take_off(character, garment):
    """Remove a worn garment. Returns (removed, wearer text, room text)."""
    if not is_garment(garment) or not garment.db.worn:
        return _refuse("You are not wearing that.")
    if covering := garment.db.covered_by:
        return _refuse(f"You would have to take off "
                       f"{item_name(covering, character)} "
                       f"first.")

    label = _garment_name(garment, character)
    revealed = [g for g in character.contents if g.db.covered_by is garment]
    garment.remove(character, quiet=True)

    name = character.get_display_name(character)
    tail = f", revealing {iter_to_str([_garment_name(g, character) for g in revealed])}" \
        if revealed else ""
    return True, f"You take off {label}{tail}.", f"{name} takes off {label}{tail}."


def cover_with(character, garment, covering):
    """Hide one worn garment under another. Returns (ok, wearer text, room text)."""
    if not is_garment(garment) or not garment.db.worn:
        return _refuse("You are not wearing that.")
    covering = as_garment(covering)
    if covering is None:
        return _refuse("You cannot cover anything with that.")
    if garment is covering:
        return _refuse("That would cover nothing.")
    if garment.db.covered_by:
        return _refuse("That is covered up already.")

    if not covering.db.worn:
        worn_ok, actor_text, room_text = put_on(character, covering)
        if not worn_ok:
            return False, actor_text, room_text
    garment.db.covered_by = covering

    label = _garment_name(garment, character)
    over = _garment_name(covering, character)
    name = character.get_display_name(character)
    return (True, f"You cover {label} with {over}.",
            f"{name} covers {label} with {over}.")


def uncover(character, garment):
    """Reveal a covered garment. Returns (ok, wearer text, room text)."""
    if not is_garment(garment) or not garment.db.covered_by:
        return _refuse("That is not covered by anything.")
    garment.db.covered_by = False
    label = _garment_name(garment, character)
    name = character.get_display_name(character)
    return True, f"You uncover {label}.", f"{name} uncovers {label}."


# ---------------------------------------------------------------------------
# Verbs
# ---------------------------------------------------------------------------

def handle(caller, verb, bound, on_message):
    """
    Deal with a clothing verb, or decline it. True when it was handled.

    Declining matters as much as handling. "remove the screw" and "cover the
    body" are not about clothes, and a world is perfectly entitled to work out
    what they mean; only an attempt whose noun really is a garment is taken
    over here. A garment named in a verb the world would otherwise have to
    invent is the one case where the game already knows the answer.
    """
    if verb not in VERBS:
        return False

    garment = bound.get("direct")
    if verb in ("wear", "remove"):
        if not wearable(garment):
            return False
        if verb == "remove" and not garment.db.worn:
            # A garment being put away rather than taken off; that is a move,
            # and the world may have its own idea of what removing it means.
            return False
        act = put_on if verb == "wear" else take_off
        _deliver(on_message, act(caller, garment))
        return True

    covering = bound.get("instrument") or bound.get("target")
    if verb == "cover":
        if not is_garment(garment) or not wearable(covering):
            return False
        _deliver(on_message, cover_with(caller, garment, covering))
        return True

    if not is_garment(garment) or not garment.db.covered_by:
        return False
    _deliver(on_message, uncover(caller, garment))
    return True


def _deliver(on_message, outcome):
    _ok, actor_text, room_text = outcome
    on_message(actor_text, room_text)


# ---------------------------------------------------------------------------
# Making clothes
# ---------------------------------------------------------------------------

def create(spec, location, worn_on=None):
    """
    Build one item from a generator's description of it, and wear it if asked.

    `spec` is the JSON a model returned: name, description, affordances,
    states, and for a garment its clothing_type and wearstyle. Returns the
    object, or None when there was not enough to make one.
    """
    from evennia import create_object

    name = str(spec.get("name", "")).strip()
    if not name:
        return None

    affordances = sorted({str(a).lower().strip()
                          for a in (spec.get("affordances") or []) if a})
    kind = str(spec.get("clothing_type", "")).strip().lower()
    if worn_on is not None and WEARABLE not in affordances:
        # It is being put on somebody, so it is wearable whatever the model
        # remembered to say.
        affordances = sorted(set(affordances) | {WEARABLE})

    obj = create_object(typeclass_for(affordances), key=name, location=location)
    obj.db.desc = str(spec.get("description", "")).strip()
    obj.db.is_ai_item = True
    obj.db.ai_takeable = bool(spec.get("takeable", True))
    obj.db.affordances = affordances
    obj.db.states = sorted({str(s).lower().strip()
                            for s in (spec.get("states") or []) if s})
    if kind in GARMENT_TYPES:
        obj.db.clothing_type = kind

    if worn_on is not None:
        style = str(spec.get("wearstyle", "")).strip()
        put_on(worn_on, obj, wearstyle=style or True)
    return obj
