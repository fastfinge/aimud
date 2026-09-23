"""
Wearing things.

This was a layer over Evennia's clothing contrib and is now the whole of it.
What the contrib supplied came to seven names -- three limits, a typeclass,
and two helpers of a dozen lines -- against seven hundred lines here, and two
of the seven were actively in the way.

**The typeclass was the tail wagging the dog.** A garment was an instance of
`ContribClothing`, but an item the generators called wearable was not one
unless something had thought to build it as one, so `as_garment` performed a
`swap_typeclass` on a live object the first time anybody tried to put a coat
on. A boolean stored in a class hierarchy, converted in flight. Wearability is
an affordance, and the affordance was there all along.

**The limits were decisions dressed as constants.** "One hat" and "no more
than twenty things" say what sort of world this is -- one world's guard is
buried under six coats and another's has a rule against hats indoors -- and
they are check rules now, in `world/rulesets/clothing.json`, where a world can
read them and change them. `put_on` asks through `attempt.permitted`, the same
door `ownership` and `relations` already use.

The three reasons this module existed have not changed.

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

from evennia.utils import iter_to_str

#: The affordance that makes an item a garment. Every generator that can
#: produce an object offers it, so a coat found in a wardrobe is as wearable
#: as one a character was born in.
#:
#: A verb rather than an adjective, since `world.affordances` folded the two
#: vocabularies together: "wearable" and "wear" were the same idea kept in two
#: namespaces that could not see each other.
WEARABLE = "wear"

#: The order garments read in, outermost first. Anything untyped, or of a type
#: not named here, comes last.
#:
#: The contrib's list, kept because it is a good one and because the worlds in
#: play have `clothing_type` written on their garments from it. Ours now, so
#: it can grow a hood and a cloak without waiting on anybody.
GARMENT_TYPES = ("hat", "jewelry", "top", "undershirt", "gloves", "fullbody",
                 "bottom", "underpants", "socks", "shoes", "accessory")

#: What putting one thing on hides, when the thing hidden is already on. Worn
#: the other way round -- underpants over trousers -- nothing is covered, and
#: that is not a bug.
AUTOCOVER = {
    "top": ("undershirt",),
    "bottom": ("underpants",),
    "fullbody": ("undershirt", "underpants"),
    "shoes": ("socks",),
}

#: How long a wear style may be: "tied loosely around her waist".
WEARSTYLE_MAXLENGTH = 50

#: The verbs this module owns. An attempt at one of these never reaches a
#: model, so long as it is really about clothes.
VERBS = ("wear", "remove", "cover", "uncover")


def is_garment(obj):
    """
    True for something that can be worn.

    Asked of the thing's affordances, which is the world's own word for what
    can be done with it. It used to be asked of the thing's *typeclass*, and
    that was the tail wagging the dog: an item the generators called wearable
    was not a `Garment` unless something had thought to build it as one, so
    `as_garment` swapped the typeclass of a live object the first time anybody
    tried to put it on. A boolean stored on a class hierarchy, converted in
    flight. The affordance was there all along and says the same thing.

    Something already worn counts whatever it affords, because it plainly is
    being worn and refusing to take it off would be worse than untidy.
    """
    if obj is None:
        return False
    if getattr(obj.db, "worn", False):
        return True
    from world import verbs

    return WEARABLE in verbs.affordances(obj)


#: The old name, kept because it reads better at several call sites: "is this
#: a garment" and "could this be worn" were two questions while a garment was
#: a typeclass, and are one question now.
wearable = is_garment


def ordered(garments):
    """Garments in the order they should be read, outermost first."""
    order = {name: index for index, name in enumerate(GARMENT_TYPES)}
    return sorted(garments,
                  key=lambda g: order.get(str(g.db.clothing_type or ""),
                                          len(order)))


def worn_by(character, exclude_covered=True):
    """The garments a character has on, outermost kind first."""
    if character is None:
        return []
    return ordered(
        obj for obj in character.contents
        if obj.db.worn and not (exclude_covered and obj.db.covered_by))


def single_type_count(garments, kind):
    """How many of these are that sort of garment."""
    return sum(1 for obj in garments
               if str(obj.db.clothing_type or "") == kind)


def _wear(character, garment, wearstyle=True):
    """
    Put it on, and hide whatever it covers. Answers with what it covered.

    Was the contrib's `ContribClothing.wear`, minus its room announcement --
    which named the garment without its article and would have been a second
    voice beside the one `put_on` already raises.

    `becoming.mark` before anything changes, because what somebody is wearing
    is a fact a rule may watch: see `world/becoming.py`.
    """
    from world import becoming

    becoming.mark(character)
    garment.db.worn = wearstyle
    hides = AUTOCOVER.get(str(garment.db.clothing_type or ""), ())
    covered = [other for other in worn_by(character, exclude_covered=False)
               if other is not garment
               and str(other.db.clothing_type or "") in hides]
    for other in covered:
        other.db.covered_by = garment
    return covered


def _unwear(character, garment):
    """Take it off, revealing whatever it hid. Answers with what it revealed."""
    from world import becoming

    becoming.mark(character)
    garment.db.worn = False
    revealed = []
    for other in character.contents:
        if other.db.covered_by is garment:
            other.db.covered_by = False
            revealed.append(other)
    return revealed


def leaving(garment, destination):
    """
    Take a garment off before it leaves the person wearing it.

    Giving away or dropping something you have on is an ordinary thing to do,
    and every path that moves an object goes through `at_pre_move`. Without
    this, a garment handed to somebody else would still be listed as worn by
    the person who no longer has it.

    Answers False to refuse the move, which is what a covered garment gets:
    you cannot hand somebody the shirt under your coat.

    On `typeclasses.objects.ObjectParent` rather than on a garment class,
    because there is no garment class any more -- wearability is an affordance
    and any object may have it. See `is_garment`.
    """
    if not getattr(garment.db, "covered_by", None) in (None, False):
        return False
    wearer = garment.location
    if garment.db.worn and wearer is not None and wearer is not destination:
        _unwear(wearer, garment)
        _revalue(wearer)
    return True


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
    """
    Nothing happened, and here is why. `(ok, actor_text, event)`.

    `None` for the event and not `""`. The third slot used to be the room's
    finished sentence, where an empty string honestly meant "the room sees
    nothing"; P4 made it an event, and a string is not one. `events.show`
    guards `None`, so the empty string went to `deliver`, which asked it for
    its `.actor` -- and every refusal in this module, plus the success path
    through the same delivery, died on it. `wear` did not work at all.
    """
    return False, text, None


def _event(character, verb, garment, template, quotes=None, **roles):
    """
    One thing somebody did with what they are wearing.

    The room's half as an event rather than a sentence, so that each person
    watching is told in their own words, with the verb as `$pconj(...)` so it
    agrees with whoever did it. See `world.events`. `quotes` are words the
    template names but must not read: the garments' names in "covering the
    shirt", which a model chose.

    P3 wrote every call to this and never the function: wearing anything
    raised a NameError that `attempt`'s broad except turned into "Something
    went wrong doing that." Found by pyflakes, not by a test, which is the
    argument for running pyflakes.
    """
    from world import events

    return events.Event(actor=character, verb=verb,
                        roles={"direct": garment, **roles},
                        room_template=template, quotes=quotes)


def _revalue(character):
    """
    Work out again what this character's gear is worth to them.

    Armour is worth nothing in a pile beside the bed. What a garment does for
    somebody depends on it being on, so every path that changes what is worn
    has to say so -- see world.gear, which recomputes the whole total rather
    than trusting anybody to add and subtract correctly.
    """
    from world import gear

    gear.recompute(character)


def put_on(character, garment, wearstyle=True):
    """
    Wear a garment. Returns (worn, what the wearer is told, what the room sees).

    The refusals that are about wearing anything at all stay here, because
    they are what the mechanic *is*: a thing you are not holding, or already
    have on, is not a limit anybody would want to change.

    **How much you may wear is not one of those.** "One hat" and "no more than
    twenty things" were constants in the contrib, and they are a decision
    about what sort of world this is: one world's guard is buried under six
    coats and another's has a rule against hats indoors. So they are check
    rules now, in `world/rulesets/clothing.json`, and asked here through
    `attempt.permitted` -- the same door `ownership` and `relations` already
    use to let a rule refuse something a mechanic is about to do.
    """
    from world import attempt

    if not is_garment(garment):
        return _refuse("That is not something you can wear.")
    if garment.location is not character:
        return _refuse("You would have to be holding that first.")
    if garment.db.worn:
        return _refuse(f"You are already wearing "
                       f"{item_name(garment, character)}.")

    refused = attempt.permitted(character, "wear", {"direct": garment})
    if refused:
        return _refuse(refused)

    if isinstance(wearstyle, str):
        wearstyle = wearstyle.strip()[:WEARSTYLE_MAXLENGTH] or True

    covered = _wear(character, garment, wearstyle)
    _revalue(character)

    label = _garment_name(garment, character)
    tail = f", covering {iter_to_str([_garment_name(g, character) for g in covered])}" \
        if covered else ""
    return (True, f"You put on {label}{tail}.",
            _event(character, "wear", garment,
                   "{actor} $pconj(put) on {direct}{tail}.",
                   quotes={"tail": tail}))


def take_off(character, garment):
    """Remove a worn garment. Returns (removed, wearer text, room text)."""
    if not is_garment(garment) or not garment.db.worn:
        return _refuse("You are not wearing that.")
    if covering := garment.db.covered_by:
        return _refuse(f"You would have to take off "
                       f"{item_name(covering, character)} "
                       f"first.")

    label = _garment_name(garment, character)
    revealed = _unwear(character, garment)
    _revalue(character)

    tail = f", revealing {iter_to_str([_garment_name(g, character) for g in revealed])}" \
        if revealed else ""
    return (True, f"You take off {label}{tail}.",
            _event(character, "remove", garment,
                   "{actor} $pconj(take) off {direct}{tail}.",
                   quotes={"tail": tail}))


def cover_with(character, garment, covering):
    """Hide one worn garment under another. Returns (ok, wearer text, room text)."""
    if not is_garment(garment) or not garment.db.worn:
        return _refuse("You are not wearing that.")
    if not is_garment(covering):
        return _refuse("You cannot cover anything with that.")
    if garment is covering:
        return _refuse("That would cover nothing.")
    if garment.db.covered_by:
        return _refuse("That is covered up already.")

    if not covering.db.worn:
        worn_ok, actor_text, event = put_on(character, covering)
        if not worn_ok:
            return False, actor_text, event
    garment.db.covered_by = covering

    label = _garment_name(garment, character)
    over = _garment_name(covering, character)
    return (True, f"You cover {label} with {over}.",
            _event(character, "cover", garment,
                   "{actor} $pconj(cover) {direct} with {instrument}.",
                   instrument=covering))


def uncover(character, garment):
    """Reveal a covered garment. Returns (ok, wearer text, room text)."""
    if not is_garment(garment) or not garment.db.covered_by:
        return _refuse("That is not covered by anything.")
    garment.db.covered_by = False
    label = _garment_name(garment, character)
    return (True, f"You uncover {label}.",
            _event(character, "uncover", garment,
                   "{actor} $pconj(uncover) {direct}."))


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
    _ok, actor_text, event = outcome
    on_message(actor_text, event)


# ---------------------------------------------------------------------------
# Making clothes
# ---------------------------------------------------------------------------

def _root_of(location):
    """The world an object is being made in, found from where it is going."""
    where = location
    while where is not None:
        root = getattr(getattr(where, "db", None), "world_root", None)
        if root is not None:
            return root
        where = getattr(where, "location", None)
    return None


def create(spec, location, worn_on=None):
    """
    Build one item from a generator's description of it, and wear it if asked.

    `spec` is the JSON a model returned: name, description, affordances,
    states, what sort of thing it is, and for a garment its clothing_type and
    wearstyle. Returns the object, or None when there was not enough to make
    one.
    """
    from evennia import create_object
    from world import affordances as af, kinds as kinds_mod, lexicon

    name = str(spec.get("name", "")).strip()
    if not name:
        return None

    garment_type = str(spec.get("clothing_type", "")).strip().lower()

    # What sort of thing this is, kept apart from what this particular one is
    # like -- the same split as name and states, one level down. The kind is
    # what a blue cup and a red cup have in common; the qualifiers are what
    # they do not.
    #
    # The primary kind comes from the sense where the generator picked one and
    # from the head noun otherwise, because English noun phrases are head-final
    # and a generator that forgot the field still made something that is a cup.
    # Secondary kinds are for a thing that is genuinely two things -- a sword
    # with an inscription on the blade -- and `prune` drops any that the
    # taxonomy already implies, so "sword, weapon" comes back as "sword".
    declared_kinds = [str(k) for k in (spec.get("kinds") or []) if k]
    sense = str(spec.get("sense", "")).strip()
    if sense and not lexicon.ancestors(sense):
        sense = ""
    primary = sense or str(spec.get("kind", "")).strip() or lexicon.head_noun(name)
    the_kinds = kinds_mod.prune([primary] + declared_kinds)

    qualifiers = sorted({str(q).lower().strip()
                         for q in (spec.get("qualifiers") or []) if q})

    # Read through the kind, so that every bottle in a world affords what
    # bottles afford. What the generator said only settles a kind this world
    # has never made before; after that it is the kind's answer, and seventy
    # bottles cannot drift into twenty-five different cache keys.
    declared = spec.get("affordances")
    # An invented noun -- datapad, holodeck -- has no taxonomy above it, so the
    # generator is asked which real sense it hangs beneath and it is settled
    # with the kind. Checked inside `kinds`: an anchor WordNet does not know is
    # dropped rather than believed.
    granted = kinds_mod.resolve(
        location and _root_of(location), the_kinds, declared,
        accepts=spec.get("holds") or (),
        under=str(spec.get("under", "") or "").strip(),
    )
    if worn_on is not None and not af.afforded(granted).intersection({WEARABLE}):
        # It is being put on somebody, so it is wearable whatever the model
        # remembered to say.
        granted = af.merge(granted, {WEARABLE: True})

    afforded = sorted(af.afforded(granted))
    obj = create_object("typeclasses.objects.Object", key=name,
                        location=location)
    obj.db.desc = str(spec.get("description", "")).strip()
    obj.db.is_ai_item = True
    # Whether a thing can be picked up is a fact about its sort -- tables are
    # not liftable and cups are -- so the generator's answer settles the kind
    # rather than only this object. That retires a model call of its own: a
    # world with forty chairs used to ask forty times, once per chair, the
    # first time somebody reached for each.
    takeable = bool(spec.get("takeable", True))
    obj.db.ai_takeable = takeable
    kinds_mod.admit(_root_of(location), the_kinds, "get", takeable)
    obj.db.affordances = granted
    obj.db.kinds = the_kinds
    obj.db.kind = the_kinds[0] if the_kinds else ""
    obj.db.qualifiers = qualifiers
    from world.model_json import listed

    obj.db.states = sorted({str(s).lower().strip()
                            for s in listed(spec.get("states")) if s})

    # The naming rule, checked rather than only asked for. Reported and not
    # repaired: a name is what everything else has learned to call the thing,
    # and rewriting one here would cost more than the contradiction does.
    # What this is for is seeing that a prototype has begun to drift, in the
    # log, while it is still one object rather than a world of them.
    from evennia.utils import logger
    from world import verbs

    welded = verbs.name_contradicts_states(
        name, obj.db.states,
        getattr(getattr(location, "db", None), "world_root", None),
    )
    if welded:
        logger.log_info(
            f"naming: {name!r} has {', '.join(welded)} in its name, which "
            f"this world treats as a condition -- changing it will leave the "
            f"name saying otherwise"
        )

    # Answerable to its condition from the first moment: a bottle created
    # half full is gettable as "full bottle" without waiting for a verb.
    from world import verbs

    # And what its name says it is, it is: a "Wax-Sealed Vial" made in a world
    # that knows `sealed` is sealed. See verbs.adopt_named_states.
    verbs.adopt_named_states(obj, _root_of(location))
    verbs.refresh_state_aliases(obj)
    # Every choice its description makes, made now, before anything reads it.
    # A choice can be a state, so this comes after the states are written and
    # can add to them. See `world.token_lists`.
    from world import tokens

    tokens.settle(obj)
    if garment_type in GARMENT_TYPES:
        obj.db.clothing_type = garment_type

    # What the thing is worth to whoever has it. Every generator that can make
    # an object comes through here, so a breastplate found in a chest protects
    # exactly as well as one a guard was created wearing.
    from world import gear

    granted = {}
    try:
        declared = (spec.get("trait_bonuses") or {}).items()
    except AttributeError:
        declared = []
    for slug, amount in declared:
        from world import traits

        slug = traits._slug(slug)
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            continue
        if slug and amount:
            granted[slug] = amount
    if granted:
        obj.db.trait_bonuses = granted
        gate = str(spec.get("bonus_while", "")).strip().lower()
        if gate:
            obj.db.bonus_while = gate
        when = str(spec.get("bonus_when", "")).strip().lower()
        if when in gear.CONDITIONS:
            obj.db.bonus_when = when

    if worn_on is not None:
        style = str(spec.get("wearstyle", "")).strip()
        put_on(worn_on, obj, wearstyle=style or True)

    # Born with it. Anything made *on* somebody is theirs -- the clothes a
    # character was generated wearing, what they were given to carry -- and
    # anything made in a room is the room's furniture and belongs to nobody
    # until somebody picks it up. Done here rather than at each generator,
    # because every route that makes an object comes through this function and
    # only this function knows, in one place, who it was made for.
    from world import ownership

    ownership.claim(worn_on if worn_on is not None else location, obj)
    return obj


# ---------------------------------------------------------------------------
# The shape of an item, for a tool's parameters (docs §4.1)
# ---------------------------------------------------------------------------

def spec_schema(ctx=None, worn=False):
    """
    One item, as `create` reads it: the shared schema for everything that
    makes a thing -- an item looked for, a room's contents, what a character
    wears and carries.

    `worn` is for a garment, which must say what sort of garment it is.
    """
    from world import gear, kinds

    world_root = getattr(ctx, "world_root", None)
    known_traits = []
    if world_root is not None:
        from world import traits

        # `offerable`, so that a lantern can be given the one trait the engine
        # reads by name. It is never in the register until something grants it,
        # and a thing that burns is the other half of what can.
        known_traits = traits.offerable(world_root)
    garments = list(GARMENT_TYPES)
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string",
                     "description": "What it is called, with no article; "
                                    "never its condition"},
            "description": {"type": "string",
                            "description": "What it looks like, alone"},
            "takeable": {"type": "boolean",
                         "description": "Whether it can be picked up"},
            "kind": {"type": "string",
                     "description": "The common noun it is, singular"},
            "kinds": {"type": "array", "items": {"type": "string"},
                      "description": "Only for a thing that is genuinely two "
                                     "things at once"},
            "qualifiers": {"type": "array", "items": {"type": "string"},
                           "description": "The describing words taken off "
                                          "its name"},
            "sense": {"type": "string",
                      "description": "Which dictionary sense of its kind, "
                                     "when asked"},
            "under": {"type": "string",
                      "description": "For a kind no dictionary knows: the "
                                     "nearest real sense"},
            "holds": {"type": "array",
                      "items": {"type": "string",
                                "enum": list(kinds.PLACEMENT)},
                      "description": "Where things go: in it, on it, both, "
                                     "or neither"},
            "affordances": {"type": "object",
                            "description": "What can be done to it, as a "
                                           "plain verb to true or false"},
            "states": {"type": "array", "items": {"type": "string"},
                       "description": "Conditions true of it now; reuse "
                                      "this world's words (list_states)"},
            "clothing_type": {"type": "string", "enum": garments,
                              "description": "What sort of garment it is"
                                             + ("" if worn else
                                                "; leave it out for anything "
                                                "that is not clothing")},
            "wearstyle": {"type": "string",
                          "description": "How it is worn, if that says "
                                         "something"},
            "trait_bonuses": {"type": "object",
                              "description": "What it does for whoever has "
                                             "it, as {trait: amount}; only "
                                             "traits this world keeps"
                                             + (": " + ", ".join(known_traits)
                                                if known_traits and
                                                len(known_traits) <= 50
                                                else " (list_traits)")},
            "bonus_when": {"type": "string",
                           "enum": list(gear.CONDITIONS),
                           "description": "What has to be true for the bonus "
                                          "to count; leave it out to let the "
                                          "thing's own affordances decide"},
            "bonus_while": {"type": "string",
                            "description": "A condition it must be in for "
                                           "the bonus to count"},
        },
        "required": ["name", "description", "kind"]
                    + (["clothing_type"] if worn else []),
    }
