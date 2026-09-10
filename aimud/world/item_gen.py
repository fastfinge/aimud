"""
AI-powered item validation and generation.

Two models are used (configured separately via the `models` command):
  validation — decides whether an object/action makes sense
  items       — creates the object with name, description, and takeability
"""


from twisted.internet import threads

from world import llm


_EXISTENCE_SYSTEM_PROMPT = """You are a game master for a text MUD deciding if an object could plausibly exist in a room.
Respond with JSON only: {"valid": true|false, "reason": "one sentence"}
Be permissive — if it's plausible for the world and room, say valid.
Deny only clear impossibilities (e.g. a spaceship in a medieval dungeon).

One thing is never valid however plausible it sounds: part of a living body.
A hand, a shoulder, hair, a wing, an antenna belongs to whoever has it and is
not a separate object, so answer invalid — otherwise it is built and left
lying on the floor. This is about bodies only: part of a made thing (a door
handle, a table leg, a page of a book) is fine, and so is a part that has
plainly been cut free — a severed hand, a mounted stag's head, a bone."""

_TAKEABILITY_SYSTEM_PROMPT = """You are a game master deciding if a player can pick up an object in a MUD.
Respond with JSON only: {"valid": true|false, "reason": "one sentence"}
Fixed features (walls, doors, floor, built-in or very heavy furniture) cannot be taken.
Portable items (weapons, tools, books, loose objects) can be taken."""

_ITEM_SYSTEM_PROMPT = """You generate items for a text-based MUD.
Respond with a single JSON object — no other text:
{
  "name": "Item Name (2-4 words, title case)",
  "description": "2-3 sentence atmospheric description of the item.",
  "takeable": true|false,
  "kind": "cup",
  "kinds": [],
  "qualifiers": ["blue", "ceramic"],
  "sense": "",
  "holds": ["in"],
  "affordances": {"read": true, "burn": true},
  "states": ["dusty"],
  "clothing_type": "",
  "trait_bonuses": {"defence": 2},
  "bonus_when": "worn",
  "bonus_while": ""
}
kind is the common noun this thing IS, singular and lowercase. Strip the words
that only describe it: a "Blue Ceramic Cup" is a cup, a "Stained Slate
Chalkboard" is a chalkboard. It is what the thing has in common with every
other one of its sort, and it is how the game knows the blue cup and the red
cup are two cups.

But keep any word that changes what the thing can DO, because everything of a
kind shares one answer to that. An "Aerosol Can" is an "aerosol can" and not a
"can" — a soup can is opened and emptied, an aerosol can is sprayed, and
filing both under "can" makes the world think you can drink from a paint
sprayer. Same for a "watering can", a "walking stick", a "fire door". When in
doubt ask whether the plain noun would do the same things; if it would not,
the word stays in the kind.

qualifiers are the describing words you took off it — what makes this one
different from the others of its kind. Colour, material, make, whose it is.
Not its condition: that is what states are for.

kinds is for a thing that is genuinely two things at once — a sword with an
inscription along the blade is a sword AND an inscription, and can be read as
well as swung. Leave it empty, which is the ordinary case. Never list what the
kind already is: a sword is obviously a weapon, and saying so adds nothing.

holds says where things can be put: ["in"] for anything hollow, ["on"] for
anything with a top, both for something like an open crate, and [] for
anything solid. This is not a verb and does not go in affordances.
takeable should be false for fixed features (bolted or structural) and true for portable objects.

clothing_type is only for something that can be worn, and goes with the
"wear" affordance. Use one of: hat, jewelry, top, undershirt, gloves,
fullbody, bottom, underpants, socks, shoes, accessory. Leave it "" for
anything that is not clothing.

{affordance_rule}

states are conditions currently true of it (locked, lit, wet, dirty, broken),
usually empty for a new object.

{naming_rule}"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_json(content):
    """
    Parse a model response that should be a single JSON object.

    Delegates to world.model_json, which repairs the near-misses models make
    -- a trailing comma, a stray comment, an answer cut off mid-object --
    rather than losing a whole generation over one character.
    """
    from world.model_json import parse_object

    return parse_object(content)


def _room_context(room):
    title = room.db.room_title or room.key
    desc = room.db.desc or ""
    return f"[{title}]\n{desc}"


def _world_and_room(room, facet):
    """
    The world, what this world tells `facet` in particular, and the room.

    The facet is named by the caller rather than fixed here: deciding whether
    a thing could exist is the world's rules talking, and writing the thing
    once it may is the world's items talking, and the two want to be told
    different things.
    """
    from world import lore

    return (f"World: {lore.description(room)}\n\n"
            f"{lore.guidance_block(room, facet)}"
            f"Room:\n{_room_context(room)}")


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

def validate_object_existence(account, room, object_name, on_valid, on_invalid, on_error):
    """
    Async. Ask the validation model whether object_name could exist in room.
    Calls on_valid(reason) or on_invalid(reason) or on_error(msg) in the main thread.
    """
    model = account.model_for("validation")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    messages = [
        {"role": "system", "content": _EXISTENCE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_world_and_room(room, 'validation')}\n\n"
                f"Could '{object_name}' plausibly exist in this room?"
            ),
        },
    ]

    def _fetch():
        return llm.ask(api_key, model, messages)

    def _done(content):
        try:
            data = _parse_json(content)
            reason = str(data.get("reason", ""))
            if data.get("valid"):
                on_valid(reason)
            else:
                on_invalid(reason)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


def validate_object_takeable(account, room, obj, on_valid, on_invalid, on_error):
    """
    Async. Ask the validation model whether obj can be picked up.
    Calls on_valid(reason) or on_invalid(reason) or on_error(msg) in the main thread.
    """
    model = account.model_for("validation")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    obj_name = obj.db.room_title or obj.key
    obj_desc = obj.db.desc or ""

    messages = [
        {"role": "system", "content": _TAKEABILITY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{_world_and_room(room, 'validation')}\n\n"
                f"Object: {obj_name}\n{obj_desc}\n\n"
                f"Can the player pick up '{obj_name}'?"
            ),
        },
    ]

    def _fetch():
        return llm.ask(api_key, model, messages)

    def _done(content):
        try:
            data = _parse_json(content)
            reason = str(data.get("reason", ""))
            if data.get("valid"):
                on_valid(reason)
            else:
                on_invalid(reason)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


def generate_item(account, room, object_name, on_success, on_error):
    """
    Async. Ask the item model to create object_name and spawn it in room.
    The created object has db.ai_takeable already set from the model response.
    Calls on_success(item_obj) or on_error(msg) in the main thread.
    """
    model = account.model_for("items")
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        on_error(str(e))
        return

    from world import affordances as af, gear, lexicon, verbs

    # Only for a word whose senses disagree about what kind of thing it is --
    # a chest, a board, a bar. Empty for almost everything, and a sword or a
    # bottle never costs a token for it.
    which_sense = lexicon.sense_prompt(object_name)

    messages = [
        {"role": "system",
         "content": _ITEM_SYSTEM_PROMPT.replace(
             "{naming_rule}", verbs.naming_rule()).replace(
             "{affordance_rule}", af.PROMPT)},
        {
            "role": "user",
            "content": (
                f"{_world_and_room(room, 'items')}\n\n"
                f"{gear.prompt_block(room.db.world_root if room else None)}"
                f"{which_sense}"
                f"Generate the item the player is examining: '{object_name}'"
            ),
        },
    ]

    def _fetch():
        return llm.ask(api_key, model, messages)

    def _done(content):
        try:
            data = _parse_json(content)
            name = str(data.get("name", object_name)).strip()
            description = str(data.get("description", "")).strip()
            takeable = bool(data.get("takeable", True))

            from world import clothing

            # Built through the clothing layer so that anything the model
            # called wearable really can be put on. A coat found in a
            # wardrobe is the same kind of thing as a coat a character was
            # born in, and nothing here has to know which.
            item = clothing.create(
                {**dict(data), "name": name, "description": description,
                 "takeable": takeable},
                location=room,
            )
            if item is None:
                raise ValueError("the model named no item")
            # Answer to the words that asked for it, not only to the name it
            # was given. Ask for an astrolabe and get a "Brass Orrery", and
            # without this the next request for an astrolabe finds nothing and
            # conjures another one.
            requested = str(object_name or "").strip().lower()
            if requested and requested != name.lower():
                item.aliases.add(requested)

            on_success(item)
        except Exception as exc:
            on_error(str(exc))

    def _fail(failure):
        on_error(failure.getErrorMessage())

    threads.deferToThread(_fetch).addCallbacks(_done, _fail)


# ---------------------------------------------------------------------------
# The one way a thing comes into being
# ---------------------------------------------------------------------------

def conjure(caller, room, account, phrase, on_ready, on_refused, fuzzy=False):
    """
    Async. Settle what `phrase` names, making it real if nothing answers to it.

    on_ready(obj, created) -- what to use, and whether it had to be made.
    on_refused(message)    -- nothing should be made, and what to say instead.

    Every route into existence comes through here: a player reaching for a
    fixture the room describes, an NPC doing the same, and a character
    deliberately producing something. There used to be two routes and only one
    of them asked anything -- a character could name whatever it liked into
    being, and what it got had no affordances and no states, so no verb rule
    could ever match it and nothing could be done to the thing afterwards.

    Four questions, in this order, because each is cheaper than the next:

      * does something here already answer to a near-enough name. A typo and
        an invention are the same thing to this game, so this is asked first
        and answers most of it.
      * is one already being made under this name in this room, two round
        trips being long enough for a second attempt to arrive.
      * could it plausibly be here at all, given the world and this room.
      * and only then, what exactly is it.

    `fuzzy` loosens the first question, and is for characters rather than
    players: an NPC names things from memory in its own words and there is
    nobody to put a disambiguation to, so a near miss is good enough.
    """
    from commands.look_take_cmds import _acquire_gen_lock, _release_gen_lock
    from world.naming import instead_of_creating

    existing, complaint = instead_of_creating(caller, phrase, fuzzy=fuzzy)
    if existing is not None:
        on_ready(existing, False)
        return
    if complaint:
        on_refused(complaint)
        return

    if not _acquire_gen_lock(room, phrase.lower()):
        on_refused("Something is already appearing there.")
        return

    def release():
        _release_gen_lock(room, phrase.lower())

    def made(item):
        release()
        on_ready(item, True)

    def failed(err):
        release()
        on_refused(f"|rCould not resolve {phrase}: {err}|n")

    def on_valid(_reason):
        generate_item(account, room, phrase, on_success=made, on_error=failed)

    def on_invalid(_reason):
        release()
        on_refused(f"You see no {phrase} here.")

    def on_error(err):
        release()
        on_refused(f"|rError: {err}|n")

    validate_object_existence(account, room, phrase, on_valid, on_invalid,
                              on_error)
