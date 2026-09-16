"""
AI-powered item validation and generation.

Two models are used (configured separately via the `models` command):
  validation — decides whether an object/action makes sense
  items       — creates the object with name, description, and takeability
"""

from world import llm


_EXISTENCE_SYSTEM_PROMPT = """You are a game master for a text MUD deciding if an object could plausibly exist in a room.
Answer by calling judge_existence.
Be permissive — if it's plausible for the world and room, say valid.
Deny only clear impossibilities (e.g. a spaceship in a medieval dungeon).

One thing is never valid however plausible it sounds: part of a living body.
A hand, a shoulder, hair, a wing, an antenna belongs to whoever has it and is
not a separate object, so answer invalid — otherwise it is built and left
lying on the floor. This is about bodies only: part of a made thing (a door
handle, a table leg, a page of a book) is fine, and so is a part that has
plainly been cut free — a severed hand, a mounted stag's head, a bone."""

_TAKEABILITY_SYSTEM_PROMPT = """You are a game master deciding if a player can pick up an object in a MUD.
Answer by calling judge_takeable.
Fixed features (walls, doors, floor, built-in or very heavy furniture) cannot be taken.
Portable items (weapons, tools, books, loose objects) can be taken."""

_ITEM_SYSTEM_PROMPT = """You generate items for a text-based MUD.
Answer by calling make_item.

name is 2-4 words in title case, and description is 2-3 atmospheric sentences
about the item alone.

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

{anchor_rule}

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


def _plural_note(object_name):
    """
    What to tell the item model when it is asked to make something plural.

    Found in playtesting: looking at the sarcophagi a room described made one
    object called "Sarcophagi", which the game then called "some sarcophagi"
    and nobody could ever look at one of. Whether a plural names several
    separate things or one thing with a plural name -- trousers, barracks --
    is a question about English that a dictionary cannot settle and the model
    can, so it is asked rather than the name being changed here. What was
    typed is kept as an alias either way, and `naming` finds the singular.
    """
    from world import english

    if not english.is_plural(object_name):
        return ""
    return (
        f"'{object_name}' is plural. If it names several separate things -- "
        f"sarcophagi along a wall, statues in a row -- make just ONE of them, "
        f"named in the singular, so each can be looked at and handled on its "
        f"own. If it is one thing with a plural name, like trousers or "
        f"barracks, keep the name as it is.\n\n"
    )


def _room_context(room):
    from world import tokens

    title = room.db.room_title or room.key
    return f"[{title}]\n{tokens.text_of(room)}"


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

def validate_object_existence(sponsor, room, object_name, on_valid, on_invalid, on_error):
    """
    Async. Ask the validation model whether object_name could exist in room.
    Calls on_valid(reason) or on_invalid(reason) or on_error(msg) in the main thread.
    """
    model = sponsor.model_for("validation")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
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
    _judged(sponsor, model, messages, "judge_existence",
            f"Say whether '{object_name}' could plausibly exist in this room.",
            on_valid, on_invalid, on_error, room)


def validate_object_takeable(sponsor, room, obj, on_valid, on_invalid, on_error):
    """
    Async. Ask the validation model whether obj can be picked up.
    Calls on_valid(reason) or on_invalid(reason) or on_error(msg) in the main thread.
    """
    model = sponsor.model_for("validation")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    from world import tokens

    obj_name = obj.db.room_title or obj.key
    obj_desc = tokens.text_of(obj)

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
    _judged(sponsor, model, messages, "judge_takeable",
            f"Say whether a player can pick up '{obj_name}'.",
            on_valid, on_invalid, on_error, room)


def generate_item(sponsor, room, object_name, on_success, on_error):
    """
    Async. Ask the item model to create object_name and spawn it in room.
    The created object has db.ai_takeable already set from the model response.
    Calls on_success(item_obj) or on_error(msg) in the main thread.
    """
    model = sponsor.model_for("items")
    try:
        sponsor.key()          # refuse early rather than mid-prompt
    except ValueError as e:
        on_error(str(e))
        return

    from world import affordances as af, gear, lexicon, verbs

    from world import kinds, lookups, token_lists
    from world import toolbox as tb

    # Which sense, or what an invented noun hangs under, is in the tool's
    # schema now: an enum of the senses for a word whose senses disagree, and
    # an open field with the anchors for one no dictionary knows. The prompt
    # only says that it is being asked.
    world_root = room.db.world_root if room else None
    messages = [
        {"role": "system",
         "content": _ITEM_SYSTEM_PROMPT.replace(
             "{naming_rule}", verbs.naming_rule()).replace(
             "{anchor_rule}", kinds.anchor_rule()).replace(
             "{affordance_rule}", af.PROMPT)},
        {
            "role": "user",
            "content": (
                f"{_world_and_room(room, 'items')}\n\n"
                f"{gear.prompt_block(world_root)}"
                f"{token_lists.TOOL_PROMPT}\n"
                f"{_sense_note(object_name)}"
                f"{_state_hints(world_root, [lexicon.head_noun(object_name)])}"
                f"{_plural_note(object_name)}"
                f"Generate the item the player is examining: '{object_name}'"
            ),
        },
    ]
    box = tb.Toolbox([item_tool(object_name)] + lookups.named(*ITEM_LOOKUPS),
                     tb.ToolContext(world_root=world_root, room=room,
                                    sponsor=sponsor, job="items"))

    def _done(data):
        try:
            data = dict(data or {})
            name = str(data.get("name") or object_name).strip()
            description = str(data.get("description", "")).strip()
            takeable = bool(data.get("takeable", True))

            from world import clothing

            # Lists first, so that the description's choices can be made the
            # moment the thing exists.
            token_lists.declare(world_root, data.get("new_token_lists"))

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

    # Rounds out, the last item sent is made as it stands: a thing the player
    # reached for and got is better than an error, and the registers still
    # fold whatever near-duplicates it carries.
    llm.converse(sponsor, model, messages, box, on_done=_done,
                 on_error=on_error,
                 on_exhausted=lambda last: _done(last) if last
                 else on_error("no item came back"),
                 rounds=ITEM_ROUNDS)


# ---------------------------------------------------------------------------
# The one way a thing comes into being
# ---------------------------------------------------------------------------

def conjure(caller, room, sponsor, phrase, on_ready, on_refused, fuzzy=False):
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
        generate_item(sponsor, room, phrase, on_success=made, on_error=failed)

    def on_invalid(_reason):
        release()
        on_refused(f"You see no {phrase} here.")

    def on_error(err):
        release()
        on_refused(f"|rError: {err}|n")

    validate_object_existence(sponsor, room, phrase, on_valid, on_invalid,
                              on_error)


# ---------------------------------------------------------------------------
# The finish tools (docs/generator-tool-loops.md §4.2)
# ---------------------------------------------------------------------------

#: Rounds each may take (§10.3). The judgements are a yes or no a player waits
#: on; an item is a little more, and a player waits on it too.
JUDGING_ROUNDS = 4
ITEM_ROUNDS = 6

#: The lookups offered while making an item: the registers its prompt used to
#: paste in, and the dictionaries its sense and anchor are checked against.
ITEM_LOOKUPS = ("list_states", "list_state_groups", "list_traits",
                "list_word_lists", "show_word_list", "kind_info",
                "lexicon_senses", "lexicon_define", "commonsense")


def _listed(value):
    return list(value) if isinstance(value, (list, tuple)) else []


def _judged(sponsor, model, messages, tool_name, question, on_valid,
            on_invalid, on_error, room):
    """
    A yes or no through a finish tool: `judge_existence` or `judge_takeable`.

    Rounds out is an error, as a reply that was not JSON used to be. There is
    no answer to take as it stands, and guessing one would either conjure a
    thing nobody allowed or refuse one nobody refused.
    """
    from world import toolbox as tb

    world_root = room.db.world_root if room is not None else None
    box = tb.Toolbox([tb.Tool(
        tool_name, question,
        tb.params({"valid": {"type": "boolean",
                             "description": "The answer"},
                   "reason": {"type": "string",
                              "description": "One sentence"}}, ["valid"]),
        lambda ctx, args, answer: answer(tb.accept(args)), finishes=True)],
        tb.ToolContext(world_root=world_root, room=room, sponsor=sponsor,
                       job="validation"))

    def done(data):
        reason = str(data.get("reason") or "")
        if data.get("valid"):
            on_valid(reason)
        else:
            on_invalid(reason)

    llm.converse(sponsor, model, messages, box, on_done=done,
                 on_error=on_error,
                 on_exhausted=lambda _last: on_error("no answer came back"),
                 rounds=JUDGING_ROUNDS)


def _needs_anchor(word):
    """Whether the dictionary has never heard of a noun at all."""
    from world import lexicon

    return (bool(word) and lexicon.available()
            and not lexicon.ancestors(word)
            and not lexicon.settled_noun_sense(word)
            and not lexicon.needs_sense_choice(word))


def _sense_note(object_name):
    """One line saying which of `sense` and `under` is being asked, or ""."""
    from world import lexicon

    word = lexicon.head_noun(object_name)
    if word and lexicon.needs_sense_choice(word):
        return (f"'{word}' means several different kinds of thing; say in "
                f"sense which one this is, given the room.\n\n")
    if _needs_anchor(word):
        return (f"'{word}' is not a word the dictionary knows; say in under "
                f"what sort of thing it most nearly is.\n\n")
    return ""


def item_tool(object_name):
    """
    `make_item`, the finish tool `generate_item` answers with.

    `clothing.spec_schema`, with `sense` closed to the word's senses when they
    disagree about what sort of thing it is -- what `lexicon.sense_prompt`
    used to write as a menu -- and `under` described with the anchors when the
    word is one no dictionary knows, and a field for the word lists its
    description declares.
    """
    from world import clothing, lexicon, token_lists
    from world import toolbox as tb

    word = lexicon.head_noun(object_name)

    def parameters(ctx):
        schema = clothing.spec_schema(ctx)
        properties = dict(schema["properties"])
        if word and lexicon.needs_sense_choice(word):
            listed = lexicon.senses(word)
            if listed:
                properties["sense"] = {
                    "type": "string",
                    "enum": [name for name, _ in listed],
                    "description": "Which of these this one is, given the "
                                   "room: " + "; ".join(
                                       f"{name} -- {definition}"
                                       for name, definition in listed)
                                   + ". Leave it out if none of them fits."}
        elif _needs_anchor(word):
            proposed = lexicon.suggested_anchors(word)
            properties["under"] = {
                "type": "string",
                "description": "The nearest real sense this hangs under. Any "
                               "dictionary identifier will do; most often one "
                               "of " + ", ".join(sorted(lexicon.KIND_BUCKETS))
                               + (". Something outside the dictionary "
                                  "suggests " + ", ".join(proposed)
                                  if proposed else "") + "."}
        properties["new_token_lists"] = {
            "type": "array", "items": token_lists.schema(ctx),
            "description": "Word lists the description uses that this world "
                           "does not keep yet"}
        return dict(schema, properties=properties, additionalProperties=False)

    def handler(ctx, args, answer):
        said = item_complaints(args, ctx.world_root)
        if said:
            answer(tb.complain("Not made: " + "; ".join(said) + ". Send the "
                               "item again with that put right.", value=args))
            return
        answer(tb.accept(args))

    return tb.Tool("make_item", f"Make '{object_name}'.", parameters, handler,
                   finishes=True)


def item_complaints(args, world_root):
    """
    What is wrong with an item that asking again can put right, as short
    phrases; [] when nothing is.

    What every other door into the world is already held to: a name that
    carries a condition, a sense that contradicts what the thing was said to
    be, an anchor the dictionary does not know, a word list nothing keeps, and
    a state or list that is another spelling of one this world has.
    """
    from world import kinds, lexicon, token_lists, verbs, vocabulary

    said = []
    name = str(args.get("name") or "").strip()
    states = [str(state).strip().lower() for state in _listed(args.get("states"))
              if str(state).strip()]

    wrong = verbs.name_contradicts_states(name, states, world_root)
    if wrong:
        one = len(wrong) == 1
        said.append(f"a name says what a thing is and never its condition, "
                    f"and {', '.join(wrong)} {'is a condition' if one else 'are conditions'}: "
                    f"put {'it' if one else 'them'} in states instead")

    sense = str(args.get("sense") or "").strip()
    if sense:
        given = args.get("affordances")
        given = given if isinstance(given, dict) else {}
        clash = kinds.sense_contradicts(
            sense, [verb for verb, yes in given.items() if yes],
            args.get("takeable"))
        if clash:
            said.append(f"{sense} is a {clash}, which does not fit what you "
                        f"said can be done with it; choose the sense you "
                        f"mean, or leave it empty")

    under = str(args.get("under") or "").strip()
    if under and lexicon.available() and not lexicon.definition(under):
        said.append(f"{under} is not a sense the dictionary knows; give a "
                    f"real identifier, such as device.n.01")

    bonuses = args.get("trait_bonuses")
    if isinstance(bonuses, dict) and bonuses:
        from world import traits

        strange = sorted(slug for slug in bonuses
                         if traits._slug(slug) not in traits.offerable(world_root))
        if strange:
            said.append("trait_bonuses names " + ", ".join(strange) + ", which "
                        "this world does not measure; list_traits shows what "
                        "it does")

    lists = [entry for entry in _listed(args.get("new_token_lists"))
             if isinstance(entry, dict)]
    said += token_lists.complaints(world_root,
                                   _listed(args.get("new_token_lists")),
                                   [args.get("description")])

    vocab = verbs.vocabulary(world_root)
    said += [line.rstrip(".") for line in vocabulary.near_duplicates(
        world_root, new_states=[{"slug": state} for state in states
                                if state not in vocab],
        new_token_lists=lists)]
    return said


def _state_hints(world_root, words):
    """
    The conditions things of this sort have been in, and the unused words in
    their groups (§5.2), as a block for the prompt, or "".

    Free: the scan is dictionary work over the registers, and it is only run
    when there are groups to look in.
    """
    if world_root is None:
        return ""
    from world import kinds, rulecheck, verbs

    try:
        of = [kinds.canonical(word) for word in words if word]
        of = [kind for kind in of if kind]
        vocab = verbs.vocabulary(world_root)
        familiar = sorted(set(kinds.states_of(world_root, of)) & set(vocab))
        groups = {verbs.group_of(world_root, state) for state in familiar} - {""}
        unused = []
        if groups:
            findings = rulecheck.scan(rulecheck.of_world(world_root))
            unused = [state for state in findings.get("dead_vocabulary") or []
                      if verbs.group_of(world_root, state) in groups
                      and state not in familiar]
    except Exception:
        from evennia.utils import logger

        logger.log_trace("item_gen: the state hints could not be worked out")
        return ""

    lines = []
    if familiar:
        lines.append("Conditions things of this sort have been in before: "
                     + ", ".join(familiar) + ".")
    if unused:
        lines.append("Already in this world's vocabulary and used by nothing "
                     "yet: " + ", ".join(unused) + ". Reuse one before "
                     "coining another.")
    return "\n".join(lines) + "\n\n" if lines else ""
