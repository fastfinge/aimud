"""
Worlds, and the room everybody starts in, as subjects of the verb commands.

`create world` is the old `worldgen` wizard, `edit world` was `worldedit`,
`delete world` was `worldremove`, `reset world` was `worldreset`, `view worlds`
was `worlds`, and `enter world` was `worlds <n>`. `enter start` is new: once a
player had entered a world there was no way back to Limbo, because Evennia's
`home` is a builder command.

**Worlds keep their numbers.** A world is numbered by when it was made, and
the one you are standing in is marked rather than moved to the top. The plan
said the world you are in comes first; but `delete world 2` must mean the same
world wherever it is typed, and a list that reorders itself by where you stand
would make it mean a different one.

**The wizard is a draft form.** Nothing is written until it is generated or
saved, and quitting with something typed asks first. Long fields -- the
description and each generator's guidance -- open the line editor and come
back to the form.
"""

from django.conf import settings

from commands.subjects import Subject, Use, answered, asking, names_for, owns
from world import lore, menus
from world import sponsor as sponsor_mod

# ---------------------------------------------------------------------------
# Worlds an account has made
# ---------------------------------------------------------------------------

def account_of(caller):
    return getattr(caller, "account", None) or caller


def resolve_worlds(account):
    """
    (world root room, room count) for every world the account created.

    Prunes ids that no longer exist from `account.db.created_worlds` on the way.
    """
    from evennia import search_tag
    from evennia.objects.models import ObjectDB

    world_ids = account.db.created_worlds or []
    results = []
    valid_ids = []
    for wid in world_ids:
        try:
            root = ObjectDB.objects.get(id=wid)
        except ObjectDB.DoesNotExist:
            continue
        results.append((root, len(search_tag(str(wid), category="ai_world"))))
        valid_ids.append(wid)
    if valid_ids != world_ids:
        account.db.created_worlds = valid_ids
    return results


def current_world_root(caller):
    """The world root of the room the caller is in, or None."""
    location = getattr(caller, "location", None)
    return location.db.world_root if location else None


def quest_holders(rooms, account):
    """
    Everyone who might be carrying a quest from this world: the characters in
    it, and the account's own characters wherever they are.
    """
    from evennia.objects.objects import DefaultCharacter

    found = {}
    for room in rooms:
        for obj in room.contents:
            if isinstance(obj, DefaultCharacter):
                found[obj.id] = obj
    for character in (getattr(account, "characters", None) or []):
        if character:
            found[character.id] = character
    return list(found.values())


def clear_world(root, account, destination=None, message=None):
    """
    Delete every room of a world and everything in it, and forget the world.

    Characters are moved out first -- to `destination`, or home. Everything
    else is destroyed, because deleting a room only sends its contents home,
    which would leave the world's items and NPCs scattered through Limbo.
    Quests from the world and its memory bank go with it.

    Returns the number of rooms deleted.
    """
    from evennia import search_tag
    from evennia.objects.objects import DefaultCharacter

    from world import ledger, memory, quests

    root_id = root.id
    rooms = list(search_tag(str(root_id), category="ai_world"))

    # Collected before anything is destroyed, because older quests are
    # identified by who gave them.
    givers = {obj.id for room in rooms for obj in room.contents if obj.db.is_npc}
    for character in quest_holders(rooms, account):
        quests.forget_world(character, root_id, givers)

    memory.forget_world(root)
    ledger.forget_world(account, root_id)

    for room in rooms:
        for obj in list(room.contents):
            if isinstance(obj, DefaultCharacter):
                if message and obj.sessions.count():
                    obj.msg(message)
                obj.move_to(destination or getattr(obj, "home", None), quiet=True)
            else:
                obj.delete()
    for room in rooms:
        room.delete()

    # A world nobody owns is a real case: `exchange.build` takes away a world
    # it half made, and a test may build one with no account behind it. The
    # rooms still have to go.
    if account is not None:
        created = account.db.created_worlds or []
        if root_id in created:
            created.remove(root_id)
            account.db.created_worlds = created
        locations = account.db.world_last_locations or {}
        locations.pop(str(root_id), None)
        account.db.world_last_locations = locations
    return len(rooms)


def _pick_world(caller, words):
    """
    The world `words` name, by number or title, or None with the caller told.

    Returns (root, room count, number).
    """
    worlds = resolve_worlds(account_of(caller))
    if not worlds:
        caller.msg("You haven't made any worlds yet. |wcreate world|n makes "
                   "one.")
        return None
    said = " ".join(words).strip()
    if said.isdigit():
        index = int(said) - 1
        if 0 <= index < len(worlds):
            return worlds[index] + (index + 1,)
        caller.msg(f"There is no world {said}. Choose 1 to {len(worlds)}; "
                   f"|wview worlds|n lists them.")
        return None
    lowered = said.lower()
    matches = [(root, count, number)
               for number, (root, count) in enumerate(worlds, 1)
               if lore.title(root).lower().rstrip(".") == lowered.rstrip(".")]
    if not matches:
        matches = [(root, count, number)
                   for number, (root, count) in enumerate(worlds, 1)
                   if lowered in lore.title(root).lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        caller.msg(f"None of your worlds is called {said}. |wview worlds|n "
                   f"lists them.")
    else:
        caller.msg(f"More than one of your worlds matches {said}. Give its "
                   f"number instead.")
    return None


def _world_line(root, count, current):
    here = " (you are here)" if current is not None and current.id == root.id \
        else ""
    rooms = f"{count} room{'s' if count != 1 else ''}"
    return f"{lore.title(root)}, {rooms}{here}"


def _world_entries(ctx, make):
    """One entry per world the account made, numbered as they were made."""
    worlds = resolve_worlds(account_of(ctx.caller))
    current = current_world_root(ctx.character)
    return [make(number, root, count, current)
            for number, (root, count) in enumerate(worlds, 1)]


def _which_world_form(verb, make, empty):
    """A list of the account's worlds, each doing `make` when chosen."""
    return menus.Form(
        key=f"{verb}-world", title=f"{verb.capitalize()} which world?",
        intro=lambda ctx: "" if resolve_worlds(account_of(ctx.caller))
        else empty,
        items=lambda ctx: _world_entries(ctx, make),
        command=lambda ctx: f"{verb} world",
    )


# ---------------------------------------------------------------------------
# The wizard: create world, edit world
# ---------------------------------------------------------------------------

def _guidance_field(facet):
    def get(ctx):
        return (ctx.draft.get("guidance") or {}).get(facet.key) or None

    def put(ctx, value):
        guide = dict(ctx.draft.get("guidance") or {})
        if value:
            guide[facet.key] = value
        else:
            guide.pop(facet.key, None)
        ctx.draft["guidance"] = guide
        ctx.dirty = True

    return menus.Field(
        facet.key, f"{facet.label} guidance", kind=menus.LONG_TEXT,
        suggestible=True,
        aliases=names_for(facet.label),
        get=get, set=put,
        help=(f"{facet.hint[0].upper() + facet.hint[1:]}. Only this part of "
              f"the world reads it, so it can be as detailed as you like "
              f"without crowding anything else. <user> works here too."),
    )


def _draft_field(key, label, spec_key, kind, help, empty="not set",
                 required=False):
    def get(ctx):
        return ctx.draft.get(spec_key) or None

    def put(ctx, value):
        ctx.draft[spec_key] = value or ""
        ctx.dirty = True

    return menus.Field(key, label, kind=kind, get=get, set=put, help=help,
                       empty=empty, required=required, suggestible=True)


def _draft_root(ctx):
    """The world a draft is editing, or None for a world not made yet."""
    from evennia.objects.models import ObjectDB

    world_id = ctx.draft.get("world_id")
    if not world_id:
        return None
    try:
        return ObjectDB.objects.get(id=world_id)
    except ObjectDB.DoesNotExist:
        return None


def _clock_change(ctx):
    return dict((ctx.draft.get("clock") or {}))


def _clock_field(key, label, show, parse, help):
    """
    One of the clock's fields. Every world has a clock, the real one until
    told otherwise, so each field shows what is true now and a change waits in
    the draft until the world is saved or made. "real" puts it back.
    """
    def get(ctx):
        change = _clock_change(ctx)
        if change.get("real"):
            return "back to the real date and time"
        return show(ctx, change)

    def put(ctx, value):
        change = _clock_change(ctx)
        change.pop("settings", None)
        if value == "real":
            change = {"real": True}
        else:
            change.pop("real", None)
            change[key] = value
        ctx.draft["clock"] = change
        ctx.dirty = True

    def parsing(ctx, text):
        text = str(text or "").strip()
        if text.lower() in ("real", "the real one", "reset"):
            return "real", None
        return parse(text)

    return menus.Field(key, label, kind=menus.TEXT, get=get, set=put,
                       parse=parsing, help=help)


def _show_year(ctx, change):
    from world import clock

    if change.get("year"):
        return str(change["year"])
    root = _draft_root(ctx)
    year = clock.now(root).year
    return f"{year}" + (" (the real year)" if clock.is_real(root) else "")


def _parse_year(text):
    try:
        year = int(text)
    except ValueError:
        return None, "A year is a whole number, like 1852 or 2253."
    if not 1 <= year <= 9999:
        return None, "A year from 1 to 9999."
    return year, None


def _show_now(ctx, change):
    from world import clock

    if change.get("now"):
        return str(change["now"]).replace("T", " ")
    return clock.exactly(_draft_root(ctx))


def _parse_now(text):
    from datetime import datetime

    for shape in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, shape).isoformat(), None
        except ValueError:
            continue
    return None, "Write it as year-month-day and hour:minute, like 1852-06-14 19:30."


def _show_day(ctx, change):
    from world import clock, traits

    if change.get("day_minutes"):
        return f"{traits._round(change['day_minutes'])} real minutes"
    root = _draft_root(ctx)
    if clock.speed(root) == 1.0:
        return "a real day"
    return f"{traits._round(clock.day_length_minutes(root))} real minutes"


def _parse_day(text):
    words = text.lower().replace("minutes", "").replace("minute", "").strip()
    try:
        minutes = float(words)
    except ValueError:
        return None, "How many real minutes a day lasts, like 120, or real."
    if minutes <= 0:
        return None, "A day has to last some time."
    return minutes, None


CLOCK_FIELDS = [
    _clock_field("year", "Year", _show_year, _parse_year,
                 "The year it is here. The day and the hour stay as they are, "
                 "so a Victorian London is real time in 1852. Type real to "
                 "go back to the real date."),
    _clock_field("now", "Date and time", _show_now, _parse_now,
                 "The date and hour it is here now, from which the clock runs "
                 "on: year-month-day and hour:minute. Type real to go back to "
                 "the real date and time."),
    _clock_field("day_minutes", "Length of a day", _show_day, _parse_day,
                 "How many real minutes a day lasts here. Leave it a real day "
                 "unless this world's days truly differ. Type real to go back "
                 "to the real day."),
]


WIZARD_FIELDS = [
    _draft_field("title", "Title", "title", menus.TEXT,
                 "A short name, which is what world listings show."),
    _draft_field("description", "Description", "description",
                 menus.LONG_TEXT,
                 "As long as you like. Every room, item and character in the "
                 "world is generated with this in front of it, and every "
                 "character is told it, so keep it to what they all need. "
                 "Write <user> where the player should be named, and it "
                 "becomes whatever they are called in this world.",
                 empty="not set, and it is needed"),
    _draft_field("name", "Your name here", "player_name", menus.TEXT,
                 "What you are called in this world. You can change it later "
                 "with name or settings name.", empty="your account name"),
    _draft_field("looks", "How you look here", "player_description",
                 menus.TEXT,
                 "What other characters see when they look at you here."),
]


def _generate(ctx):
    draft = ctx.draft
    if not (draft.get("description") or "").strip():
        raise menus.Refuse("A world needs a description before it can be "
                           "generated. Choose Description to write one.")
    caller = ctx.character or ctx.caller
    account = account_of(caller)
    title = draft.get("title") or ""

    def on_success(room):
        caller.msg(f"|gEntering: {room.db.room_title or room.key}|n")
        caller.move_to(room, quiet=False)

    def on_error(err):
        caller.msg(f"|rWorld generation failed: {err}|n")

    from world import busy
    from world.worldgen import generate_first_room

    wait = busy.start(caller, f"generating {title or 'your world'}")
    generate_first_room(sponsor_mod.of_account(account), dict(draft),
                        busy.closing(wait, on_success),
                        busy.closing(wait, on_error),
                        creator_character=caller)
    return f"Generating |w{title or 'your world'}|n..."


def _save(ctx):
    from evennia.objects.models import ObjectDB

    draft = ctx.draft
    caller = ctx.character or ctx.caller
    try:
        root = ObjectDB.objects.get(id=draft.get("world_id"))
    except ObjectDB.DoesNotExist:
        return "|rThat world no longer exists, so nothing was saved.|n"
    if not owns(account_of(caller), root):
        return "Only whoever made a world can change it."

    lore.store(root, draft)
    # Unlike a new world, an edit is allowed to take a name or a look away
    # again: the player is changing what they set, not being given a default.
    caller.set_world_name(root, (draft.get("player_name") or "").strip())
    caller.set_world_desc(root, (draft.get("player_description") or "").strip())
    guided = [lore.FACETS_BY_KEY[key].label
              for key in (root.db.world_guidance or {})
              if key in lore.FACETS_BY_KEY]
    return (f"|gSaved |w{lore.title(root)}|g.|n Guidance is set for: "
            f"{', '.join(guided) or 'nothing'}.\n"
            "Rooms, items and characters already built keep the text they "
            "were written with; anything generated from now on follows this.")


def _wizard_intro(ctx):
    said = ("The description is put in front of every generator and every "
            "character in the world, so keep it to what they all need; put "
            "what only one of them needs in that one's guidance.")
    if ctx.draft.get("mode") == "edit":
        said += (" Changes apply to whatever is generated from now on. Rooms, "
                 "items and characters that already exist keep the text they "
                 "were written with.")
    return said


def open_a_way(ctx):
    """
    Open a way on, in a world that has built itself into a corner.

    A world grows by having somewhere unexplored left in it. Every room built
    spends one of those and leaves behind however many its exits promise, so a
    run of dead ends can close a world off. Worlds built now do this for
    themselves the moment they would otherwise end; this is for one that
    already has. It was `worldopen`.
    """
    from evennia.objects.models import ObjectDB

    from world.worldgen import ensure_frontier, frontier, pending_exits

    try:
        root = ObjectDB.objects.get(id=ctx.draft.get("world_id"))
    except ObjectDB.DoesNotExist:
        return "That world no longer exists."
    left = frontier(root)
    if left:
        ways = pending_exits(root)[:5]
        where = ", ".join(
            f"{ex.key} from {ex.location.db.room_title or ex.location.key}"
            for ex in ways)
        return (f"|w{lore.title(root)}|n still has {left} way(s) nobody has "
                f"taken. Nothing to open.\n|x{where}|n")
    location = getattr(ctx.character or ctx.caller, "location", None)
    in_it = location is not None and location.db.world_root == root
    opened = ensure_frontier(root, near=location if in_it else root)
    if opened is None:
        return ("There is nowhere left to open a way onto: every room is "
                "walled in on all six sides. That should not be possible; the "
                "world may have lost its coordinates.")
    where = opened.location.db.room_title or opened.location.key
    return (f"A way |w{opened.key}|n opens from |w{where}|n. The world has "
            f"somewhere to go again.")


def _permits_label(ctx):
    """The submenu's own line: what is off, or that nothing is."""
    from world import permits

    chosen = dict(permits.held(_draft_root(ctx)))
    chosen.update(_permits_draft(ctx))
    quiet = [name for name in permits.MADE
             if chosen.get(name) != permits.ALWAYS]
    if not quiet:
        return "What this world writes for itself: all of it"
    return (f"What this world writes for itself: not "
            f"{', '.join(quiet)}")


def _permit_field(making, label, off):
    """
    One of the five, held in the draft until the world is made or saved.

    Asked here and not only in `settings` because the answer has to be known
    *before* anything is generated: a world that does not write its own rooms
    would otherwise be given a planned zone, a named first room and whatever
    the contents pass put in it, and then have to be undone. See
    world/permits.py.
    """
    from world import permits

    def get(ctx):
        return _permits_draft(ctx).get(making, _permits_now(ctx, making))

    def put(ctx, value):
        chosen = _permits_draft(ctx)
        chosen[making] = value
        ctx.draft[permits.ATTR] = chosen
        ctx.dirty = True

    return menus.Field(
        making, label, kind=menus.CHOICE, get=get, set=put,
        choices=lambda ctx: [
            menus.Choice(permits.ALWAYS, "whenever anything asks",
                         keys=("always", "on")),
            menus.Choice(permits.ASKED, "only when a player goes looking",
                         keys=("asked", "player", "players")),
            menus.Choice(permits.NEVER, f"never -- {off}",
                         keys=("never", "off", "no")),
        ],
        help=f"{label}. |wonly when a player goes looking|n keeps the world "
             f"from growing while nobody is watching -- a character wandering "
             f"through a door finds nothing where a player would find a room. "
             f"|wnever|n means {off}.")


def _permits_draft(ctx):
    from world import permits

    return dict(ctx.draft.get(permits.ATTR) or {})


def _permits_now(ctx, making):
    from world import permits

    return permits.setting(_draft_root(ctx), making)


def _permit_fields():
    from world import permits

    return [_permit_field(name, label, off)
            for name, label, off in permits.MAKES]


def _wizard_items(ctx):
    from commands import rulesets_subject
    from world import permits

    items = (list(WIZARD_FIELDS) + list(CLOCK_FIELDS)
             + [_guidance_field(f) for f in lore.FACETS])
    # What this world may write for itself. Its own submenu rather than five
    # more fields in a form that already has a dozen: it is one decision made
    # five times, and a world where the answer is "all of it" -- which is
    # most of them -- should not have to read past it.
    items.append(menus.Submenu(
        permits.ATTR, _permits_label, menus.Form(
            key="generation", title="What this world writes for itself",
            intro="What a model may bring into being here, and on whose "
                  "account. Everything is on until you say otherwise.\n\n"
                  "A world with rooms turned off starts as one plain room "
                  "for you to build out from, and costs nothing to make.",
            items=_permit_fields()),
        help="Whether this world grows its own rooms, items, characters, "
             "verbs and errands -- always, only when a player goes looking, "
             "or never. A hand-built world turns off what it means to build "
             "itself; everything else it can still be asked for."))
    # Which bundles of rules the world is built with. The same form `edit
    # rulesets` opens, so what is offered here cannot drift from what is
    # offered there.
    items.append(menus.Submenu(
        "rulesets", "Which rulesets this world uses",
        rulesets_subject.FORM,
        help="Bundles of rules a world can be built with -- crafting, death, "
             "and whatever else this server offers. What one requires is "
             "switched on with it."))
    if ctx.draft.get("mode") == "edit":
        items.append(menus.Action(
            "open", "Open a way on, if the world has nowhere left to go",
            run=open_a_way, help=(
                "A run of dead ends can close a world off, with no unexplored "
                "ways left and so no more rooms. This finds the best place to "
                "carry on from and opens a door there. Nothing else in the "
                "form is saved by it.")))
        items.append(menus.Action("save", "Save these changes", run=_save,
                                  after=menus.CLOSE))
    else:
        items.append(menus.Action(
            "generate", "Generate this world", run=_generate,
            after=menus.CLOSE, aliases=("go",),
            command=lambda ctx: "create world <description>"))
    return items


def _wizard_title(ctx):
    if ctx.draft.get("mode") == "edit":
        return f"Editing {ctx.draft.get('title') or 'this world'}"
    return "A new world"


def _wizard_sponsor(ctx):
    """
    Whoever will own the world pays for a draft of it, as they pay for
    generating it: there is no world yet to read a payer off.
    """
    return sponsor_mod.of_account(account_of(ctx.character or ctx.caller))


WIZARD = menus.Form(
    key="world", title=_wizard_title, intro=_wizard_intro,
    items=_wizard_items, discard="Throw away what you have entered?",
    sponsor=_wizard_sponsor,
    context=lambda ctx: ("This form sets up a world that a game will generate "
                         "rooms, characters and items for. Guidance is read "
                         "only by the generator it names."),
)


def new_draft(description=""):
    from world import rulesets

    return {"mode": "create", "world_id": None, "description": description,
            "title": "", "player_name": "", "player_description": "",
            "guidance": {}, "rulesets": rulesets.defaults()}


def _key_problem(caller, spec=None):
    """
    Why this cannot be paid for, or "".

    A world that writes none of its own rooms is made without a single model
    call -- that is the whole of what turning them off buys -- so it needs no
    key, and demanding one refuses exactly the person the switch exists for.
    `spec` says what is being built; with none given the question is only
    whether a key is there at all.
    """
    from world import permits

    if spec is not None and permits.from_spec(spec).get("rooms")             == permits.NEVER:
        return ""
    try:
        sponsor_mod.of_account(account_of(caller)).key()
    except ValueError as err:
        return str(err)
    return ""


def create_run(cmd, ctx, words):
    caller = cmd.caller
    # Said rather than refused. Whether a key is needed depends on what the
    # wizard is about to be filled in with -- a world that writes none of its
    # own rooms needs none -- and refusing here would shut the form before
    # anybody could say so. Generating without one still fails, with the same
    # sentence, at the moment it would have spent something.
    problem = _key_problem(caller)
    if problem:
        caller.msg(f"{problem}\n|xA world that writes none of its own rooms "
                   f"needs no key at all: turn them off under |wWhat this "
                   f"world writes for itself|x.|n")
    from commands.subjects import verb_form

    menus.open_menu(caller, verb_form("create"), session=cmd.session,
                    path=["world"],
                    draft=new_draft(" ".join(words)))


def create_items(ctx):
    return [menus.Submenu("world", "A world", WIZARD, help=(
        "Set up and generate a new world: its title, its description, who you "
        "are in it, and guidance for each generator."),
        draft=lambda ctx: ctx.draft if ctx.draft.get("mode") == "create"
        else new_draft())]


def _edit_draft(root):
    def draft(ctx):
        spec = lore.spec_of(root, ctx.character)
        spec.update(mode="edit", world_id=root.id)
        return spec
    return draft


def _edit_entry(number, root, count, current):
    return menus.Submenu(
        f"world{root.id}", _world_line(root, count, current), WIZARD,
        aliases=names_for(lore.title(root)), draft=_edit_draft(root),
        command=lambda ctx: f"edit world {number}")


EDIT_WHICH = _which_world_form("edit", _edit_entry,
                               "You haven't made any worlds yet.")


def edit_run(cmd, ctx, words):
    from commands.subjects import verb_form

    if not words:
        menus.open_menu(cmd.caller, verb_form("edit"), session=cmd.session,
                        path=["world"])
        return
    picked = _pick_world(cmd.caller, words)
    if picked is None:
        return
    root, _count, number = picked
    menus.open_menu(cmd.caller, verb_form("edit"), session=cmd.session,
                    path=["world", str(number)])


def edit_items(ctx):
    return [menus.Submenu("world", "A world you made", EDIT_WHICH, help=(
        "Change what a world tells its generators without rebuilding it."))]


# ---------------------------------------------------------------------------
# delete world, reset world
# ---------------------------------------------------------------------------

def _cannot_delete(caller, root):
    """Why this world cannot be deleted by this caller, or "". Asked first."""
    here = current_world_root(caller)
    if here is not None and here.id == root.id:
        return ("You cannot delete the world you are standing in. |wenter "
                "start|n first.")
    if not owns(account_of(caller), root):
        return "Only whoever made a world can delete it."
    return ""


def _delete(caller, root, count):
    title = lore.title(root)
    refused = _cannot_delete(caller, root)
    if refused:
        return refused
    clear_world(root, account_of(caller), message=(
        f"|rThe world '{title}' is being deleted. You have been moved to your "
        f"home location.|n"))
    return f"|gDeleted world '|w{title}|g', {count} room(s) removed.|n"


def _delete_question(root, count):
    return (f"Permanently delete {lore.title(root)} and all {count} of its "
            f"rooms? This cannot be undone.")


def _delete_entry(number, root, count, current):
    if current is not None and current.id == root.id:
        # Listed, so the numbers hold still, but refused before anything is
        # asked: a yes/no that ends in "you cannot" wastes the question.
        return menus.Action(
            f"world{root.id}", _world_line(root, count, current),
            run=lambda ctx: _cannot_delete(ctx.character or ctx.caller, root),
            aliases=names_for(lore.title(root)))
    return menus.Action(
        f"world{root.id}", _world_line(root, count, current),
        run=lambda ctx: _delete(ctx.character or ctx.caller, root, count),
        confirm="delete_world", question=_delete_question(root, count),
        after=menus.CLOSE, aliases=names_for(lore.title(root)),
        command=lambda ctx: f"delete world {number}")


DELETE_WHICH = _which_world_form("delete", _delete_entry,
                                 "You have no worlds to delete.")


def delete_run(cmd, ctx, words):
    from commands.subjects import verb_form

    caller = cmd.caller
    answered = bool(words) and words[-1].lower() in ("yes", "confirm")
    words = words[:-1] if answered else words
    if not words:
        menus.open_menu(caller, verb_form("delete"), session=cmd.session,
                        path=["world"])
        return
    picked = _pick_world(caller, words)
    if picked is None:
        return
    root, count, number = picked
    refused = _cannot_delete(caller, root)
    if answered or refused:
        caller.msg(refused or _delete(caller, root, count))
        return
    menus.confirm(caller, _delete_question(root, count),
                  lambda: caller.msg(_delete(caller, root, count)),
                  key="delete_world", session=cmd.session,
                  command=f"delete world {number}")


def delete_items(ctx):
    return [menus.Submenu("world", "A world you made", DELETE_WHICH, help=(
        "Delete a world and everything in it, permanently. You cannot delete "
        "the world you are standing in."))]


def _reset(caller, root):
    """Build the world again from its setup, and only then remove the old."""
    account = account_of(caller)
    if not owns(account, root):
        return "Only whoever made a world can reset it."
    # A world that was imported, or exported, has somewhere to go back to, and
    # a reset means that place rather than a world generated again from the
    # same description. It also costs nothing and needs no key, which is why
    # this comes before `_key_problem`. See docs/archived/import-and-export.md 8.
    if _restore_point(root) is not None:
        return _replay(caller, root)
    spec = lore.spec_of(root, caller)
    description = spec["description"]
    if not description:
        return ("That world has no stored description, so it cannot be "
                "rebuilt. |wdelete world|n removes it instead.")
    # Asked of the spec, so a world that writes no rooms of its own is rebuilt
    # without a key, exactly as it was made without one.
    problem = _key_problem(caller, spec)
    if problem:
        return problem

    def on_success(new_root):
        removed = clear_world(root, account, destination=new_root,
                              message="|yThe world is being rebuilt around you.|n")
        caller.msg(f"|gRebuilt '|w{spec['title'] or description}|g', "
                   f"{removed} old room(s) removed.|n")
        if caller.location is not new_root:
            caller.move_to(new_root, quiet=False)
        else:
            caller.execute_cmd("look")

    def on_error(err):
        caller.msg(f"|rWorld generation failed: {err}|n\n"
                   f"Your existing world was left untouched.")

    from world import busy
    from world.worldgen import generate_first_room

    wait = busy.start(caller, f"rebuilding {lore.title(root)}")
    # A reset builds a world that does not exist yet, so whoever asked for it
    # is the one who will own it and pay for it, as with a new world.
    generate_first_room(sponsor_mod.of_account(account), spec,
                        busy.closing(wait, on_success),
                        busy.closing(wait, on_error),
                        creator_character=caller)
    return (f"Rebuilding |w{lore.title(root)}|n, generating the new world "
            f"first...")


def _restore_point(root):
    from world import exchange

    return exchange.restore_point(root)


def _replay(caller, root):
    """
    Put an imported world back as it arrived, and only then remove the old.

    The same shape as a generated reset -- build the new one, move everybody
    into it, destroy the old -- and for the same reason: a reset that
    destroyed first would take somebody's world away and then discover it
    could not make another. What is different is that this cannot fail for
    want of a key, and takes no time at all.
    """
    from world import exchange

    account = account_of(caller)
    doc = _restore_point(root)
    title = lore.title(root)
    try:
        new_root = exchange.build(doc, account, caller)
    except exchange.Refused as refusal:
        return (f"|r{title} could not be put back: {refusal}|n\n"
                f"Your existing world was left untouched.")
    removed = clear_world(root, account, destination=new_root,
                          message="|yThe world is being put back as it was.|n")
    if caller.location is not new_root:
        caller.move_to(new_root, quiet=False)
    else:
        caller.execute_cmd("look")
    return (f"|g{title} is back as it was, {removed} old room(s) removed.|n")


def _reset_question(root, count):
    doc = _restore_point(root)
    if doc is not None:
        taken = str(doc.get("exported") or "")
        return (f"Put {lore.title(root)} back as it was"
                + (f" on {taken}" if taken else "")
                + f", destroying all {count} of its rooms as they are now? "
                  f"Nothing is generated and nothing is spent.")
    return (f"Destroy all {count} rooms of {lore.title(root)}, with everything "
            f"in them, and generate the world again from its setup? The old "
            f"world is only removed once the new one is ready.")


def _reset_entry(number, root, count, current):
    return menus.Action(
        f"world{root.id}", _world_line(root, count, current),
        run=lambda ctx: _reset(ctx.character or ctx.caller, root),
        confirm="reset_world", question=_reset_question(root, count),
        after=menus.CLOSE, aliases=names_for(lore.title(root)),
        command=lambda ctx: f"reset world {number}")


RESET_WHICH = _which_world_form("reset", _reset_entry,
                                "You have no worlds to reset.")


def reset_run(cmd, ctx, words):
    from commands.subjects import verb_form

    caller = cmd.caller
    answered = bool(words) and words[-1].lower() in ("yes", "confirm")
    words = words[:-1] if answered else words
    if not words:
        menus.open_menu(caller, verb_form("reset"), session=cmd.session,
                        path=["world"])
        return
    picked = _pick_world(caller, words)
    if picked is None:
        return
    root, count, number = picked
    if answered:
        caller.msg(_reset(caller, root))
        return
    menus.confirm(caller, _reset_question(root, count),
                  lambda: caller.msg(_reset(caller, root)),
                  key="reset_world", session=cmd.session,
                  command=f"reset world {number}")


def reset_items(ctx):
    return [menus.Submenu("world", "A world you made", RESET_WHICH, help=(
        "Wipe a world and generate it again from the same setup."))]


# ---------------------------------------------------------------------------
# view worlds
# ---------------------------------------------------------------------------

def _worlds_listing(ctx):
    worlds = resolve_worlds(account_of(ctx.caller))
    if not worlds:
        return "You haven't made any worlds yet. |wcreate world|n makes one."
    current = current_world_root(ctx.character)
    lines = [f"{number}. {_world_line(root, count, current)}"
             for number, (root, count) in enumerate(worlds, 1)]
    return "\n".join(lines)


def _world_detail(root, count, number):
    from world import activity, clock, verbs

    description = (root.db.world_description or "").strip().splitlines()
    first = description[0] if description else ""
    lines = [f"|w{lore.title(root)}|n, {count} room{'s' if count != 1 else ''}, "
             f"running {activity.mode(root)}."]
    if first:
        lines.append(first)
    # What time it is there, and what part of the day, which every world has.
    period = sorted(state for state in verbs.implied_states(root, root)
                    if verbs.group_of(root, state) == clock.PERIOD_GROUP)
    lines.append(f"It is {clock.exactly(root)}"
                 + (f", {' and '.join(period)}" if period else "")
                 + (", real time." if clock.is_real(root) else "."))
    # Whether a reset means "back to this" or "generated again", said here
    # rather than left for the confirmation to spring on somebody.
    doc = _restore_point(root)
    if doc is not None:
        taken = str(doc.get("exported") or "")
        lines.append(f"|wreset world {number}|n puts it back as it was"
                     + (f" on {taken}." if taken else "."))
    lines.append(f"|wenter world {number}|n goes there.")
    return "\n".join(lines)


def _view_entry(number, root, count, current):
    return menus.Action(
        f"world{root.id}", lore.title(root),
        run=lambda ctx: _world_detail(root, count, number),
        aliases=names_for(lore.title(root)),
        command=lambda ctx: f"view world {number}")


VIEW_WORLDS = menus.Form(
    key="worlds", title="Your worlds", kind=menus.VIEW,
    intro=_worlds_listing,
    items=lambda ctx: _world_entries(ctx, _view_entry),
    command=lambda ctx: "view worlds",
)


def view_run(cmd, ctx, words):
    if words:
        picked = _pick_world(cmd.caller, words)
        if picked is not None:
            cmd.caller.msg(_world_detail(*picked))
        return
    menus.open_menu(cmd.caller, VIEW_WORLDS, session=cmd.session)


def view_items(ctx):
    return [menus.Submenu("worlds", "Your worlds", VIEW_WORLDS, help=(
        "Every world you have made, and how big each has grown."))]


# ---------------------------------------------------------------------------
# enter world, enter start
# ---------------------------------------------------------------------------

def start_room():
    """
    The room everybody starts in: Limbo, or whatever the server has put in its
    place. Read from the room itself, so renaming it renames the subject.
    """
    from evennia import search_object

    for dbref in (settings.START_LOCATION, settings.DEFAULT_HOME):
        found = search_object(dbref)
        if found:
            return found[0]
    return None


def _start_words():
    room = start_room()
    words = ["start"]
    if room is not None:
        words.append(room.key)
    return words


def _leaving_note(caller, destination):
    """
    Said when somebody leaves a world they made that is still running always.

    Leaving does not change the mode and nothing is switched for them; they
    are told, because the world goes on spending money.
    """
    from world import activity

    root = current_world_root(caller)
    if root is None or activity.mode(root) != activity.ALWAYS:
        return ""
    if getattr(destination.db, "world_root", None) == root:
        return ""
    if not owns(account_of(caller), root):
        return ""
    return (f"|y{lore.title(root)} is still running always, and its characters "
            f"go on acting and costing model calls while you are away. "
            f"|wsettings mode normal|y, typed there, puts it back.|n")


def _go(caller, destination, arriving):
    if caller.location is destination:
        return "You are already there."
    note = _leaving_note(caller, destination)
    if note:
        caller.msg(note)
    caller.msg(arriving)
    caller.move_to(destination, quiet=False)
    return None


def enter_world(caller, root):
    current = current_world_root(caller)
    if current is not None and current.id == root.id:
        return "You are already in that world."
    account = account_of(caller)
    last = (account.db.world_last_locations or {}).get(str(root.id))
    destination = last if getattr(last, "pk", None) else root
    return _go(caller, destination, f"Entering world: |w{lore.title(root)}|n")


def enter_start(caller):
    room = start_room()
    if room is None:
        return "There is no start room on this server."
    return _go(caller, room, f"Returning to |w{room.key}|n.")


def _enter_entry(number, root, count, current):
    return menus.Action(
        f"world{root.id}", _world_line(root, count, current),
        run=lambda ctx: enter_world(ctx.character or ctx.caller, root),
        after=menus.CLOSE, aliases=names_for(lore.title(root)),
        command=lambda ctx: f"enter world {number}")


ENTER_WHICH = _which_world_form("enter", _enter_entry,
                                "You haven't made any worlds yet.")


def enter_world_run(cmd, ctx, words):
    if not words:
        menus.open_menu(cmd.caller, ENTER_WHICH, session=cmd.session)
        return
    picked = _pick_world(cmd.caller, words)
    if picked is not None:
        said = enter_world(cmd.caller, picked[0])
        if said:
            cmd.caller.msg(said)


def enter_world_items(ctx):
    return _world_entries(ctx, _enter_entry)


def enter_start_run(cmd, ctx, words):
    said = enter_start(cmd.caller)
    if said:
        cmd.caller.msg(said)


def enter_start_items(ctx):
    room = start_room()
    if room is None or getattr(ctx.character, "location", None) is room:
        return []
    return [menus.Action(
        "start", f"Back to {room.key}",
        run=lambda ctx: enter_start(ctx.character or ctx.caller),
        after=menus.CLOSE, aliases=names_for(room.key),
        help="The room everybody starts in, outside every world.",
        command=lambda ctx: "enter start")]


# ---------------------------------------------------------------------------
# export world, import world
# ---------------------------------------------------------------------------
#
# Two more things done to a world, so two more uses here rather than a subject
# of their own. What is left over -- the folder itself, and taking something
# out of it -- is `commands/exchange_subject.py`.
#
# Neither calls a model. An export is a read and an import is a build, and a
# server with no API key does both. See docs/archived/import-and-export.md 12.

EXPORT_QUESTION = ("Write {title} to the shared folder, where anybody here "
                   "can build a world from it, and make this the state "
                   "|wreset world|n comes back to?")


def _export(caller, root):
    from commands import exchange_subject
    from world import exchange

    account = account_of(caller)
    if not owns(account, root):
        return "Only whoever made a world can export it."
    doc = exchange.document(root)
    wrong = exchange.problems(doc)
    if wrong:
        # Refused rather than written. A document this server cannot read back
        # is not an export, it is a file; and the fault is ours, so it is
        # logged where somebody can find it as well as said here.
        from evennia.utils import logger

        logger.log_err(f"exchange: {lore.title(root)} exported wrongly: "
                       f"{'; '.join(wrong)}")
        return (f"|r{lore.title(root)} could not be written down: "
                f"{wrong[0]}|n")
    try:
        name = exchange.write(doc)
    except exchange.Refused as refusal:
        return f"|r{refusal}|n"
    exchange_subject.wrote(account, name)
    exchange.remember(root, doc)
    carried = _carried_note(caller, root)
    return (f"|g{lore.title(root)} is in the shared folder as |w{name}|g, "
            f"{doc['rooms']} room(s). |wreset world|g now puts it back as it "
            f"is today.|n" + carried)


def _carried_note(caller, root):
    """
    Said when somebody exported a world while holding some of it.

    A world missing its crowbar is broken and a world with a crowbar on the
    floor is not, so what a player is carrying is written down where they were
    standing. Nobody would guess that, so it is said. See
    docs/archived/import-and-export.md 4.1.
    """
    from evennia.objects.objects import DefaultCharacter
    from world import exchange

    held = []
    for room in exchange.rooms_of(root):
        for obj in room.contents:
            if isinstance(obj, DefaultCharacter) and not obj.db.is_npc:
                held.extend(thing for thing in obj.contents
                            if getattr(thing, "destination", None) is None)
    if not held:
        return ""
    return (f"\n|x{len(held)} thing(s) somebody was carrying were written "
            f"down where they were standing: a world missing them would be "
            f"broken, and one with them on the floor is not.|n")


def _export_entry(number, root, count, current):
    return menus.Action(
        f"world{root.id}", _world_line(root, count, current),
        run=lambda ctx: _export(ctx.character or ctx.caller, root),
        confirm="export_world",
        question=EXPORT_QUESTION.format(title=lore.title(root)),
        after=menus.CLOSE, aliases=names_for(lore.title(root)),
        command=lambda ctx: f"export world {number}")


EXPORT_WHICH = _which_world_form("export", _export_entry,
                                 "You have no worlds to export.")


def export_run(cmd, ctx, words):
    from commands.subjects import verb_form

    caller = cmd.caller
    words, yes = answered(words)
    if not words:
        menus.open_menu(caller, verb_form("export"), session=cmd.session,
                        path=["world"])
        return
    picked = _pick_world(caller, words)
    if picked is None:
        return
    root, _count, number = picked
    asking(cmd, EXPORT_QUESTION.format(title=lore.title(root)),
           "export_world", f"export world {number}",
           lambda: caller.msg(_export(caller, root)), already=yes)


def export_items(ctx):
    return [menus.Submenu("world", "A world you made", EXPORT_WHICH, help=(
        "Write a world to the shared folder, and make today's state the one "
        "|wreset world|n comes back to."))]


IMPORT_QUESTION = ("Build a world from {name}, {rooms} room(s), made by "
                   "somebody else? Its descriptions and its characters' words "
                   "are sent to your model on your key when you play it.")


def _import(caller, name):
    from world import exchange

    account = account_of(caller)
    if account is None:
        return "Only an account can hold a world."
    try:
        doc = exchange.read(name)
        root = exchange.build(doc, account, caller)
    except exchange.Refused as refusal:
        return ("|r" + str(refusal.complaints[0]) + "|n"
                + ("".join(f"\n|r  {said}|n"
                           for said in refusal.complaints[1:6])))
    number = len(resolve_worlds(account))
    return (f"|g{lore.title(root)} is yours, "
            f"{len(exchange.rooms_of(root))} room(s). "
            f"|wenter world {number}|g goes there, and |wreset world "
            f"{number}|g puts it back as it is now.|n")


def _import_entry(name, heading):
    return menus.Action(
        f"import-{name}",
        f"{heading['title'] or name} -- {heading['rooms']} room"
        f"{'s' if heading['rooms'] != 1 else ''}"
        + (f", |rneeds {', '.join(heading['missing'])}|n"
           if heading["missing"] else ""),
        run=lambda ctx: _import(ctx.character or ctx.caller, name),
        confirm="import_world",
        question=IMPORT_QUESTION.format(name=heading["title"] or name,
                                        rooms=heading["rooms"]),
        after=menus.CLOSE, aliases=names_for(name, heading["title"]),
        command=lambda ctx: f"import world {name}")


IMPORT_WHICH = menus.Form(
    key="import-world", title="Build a world from which document?",
    intro=lambda ctx: _import_intro(),
    items=lambda ctx: _import_entries(),
    command=lambda ctx: "import world",
)


def _import_intro():
    from commands import exchange_subject

    if not exchange_subject.exports():
        return ("The shared folder is empty. |wexport world|n puts one of "
                "yours in it for everybody here.")
    return ("A world somebody here exported. It becomes yours: you own it, "
            "you pay for it, and its text reaches your model.")


def _import_entries():
    from commands import exchange_subject

    return [_import_entry(name, heading)
            for name, heading in sorted(exchange_subject.exports().items())]


def import_run(cmd, ctx, words):
    from commands.subjects import verb_form

    caller = cmd.caller
    words, yes = answered(words)
    if not words:
        menus.open_menu(caller, verb_form("import"), session=cmd.session,
                        path=["world"])
        return
    from commands import exchange_subject

    said = " ".join(words).strip()
    found = exchange_subject.exports()
    # By the name the folder uses, or by the world's own title: nobody types
    # `import world the_school` having read "The School" in the listing.
    name, heading = said, found.get(said)
    if heading is None:
        matches = [(made, entry) for made, entry in found.items()
                   if entry["title"].lower() == said.lower()]
        if len(matches) == 1:
            name, heading = matches[0]
    if heading is None:
        caller.msg(f"There is no world called {said} in the shared folder. "
                   f"|wview exports|n lists what is.")
        return
    asking(cmd, IMPORT_QUESTION.format(name=heading["title"] or name,
                                       rooms=heading["rooms"]),
           "import_world", f"import world {name}",
           lambda: caller.msg(_import(caller, name)), already=yes)


def import_items(ctx):
    return [menus.Submenu("world", "One from the shared folder", IMPORT_WHICH,
                          help=("Build a world somebody here exported. It "
                                "becomes yours, and costs nothing to build."))]


# ---------------------------------------------------------------------------
# The subjects
# ---------------------------------------------------------------------------

def _has_account(ctx):
    return account_of(ctx.caller) is not None


SUBJECTS = [
    Subject(
        "start", _start_words,
        uses={"enter": Use(enter_start_run, enter_start_items)},
        help="The room everybody starts in, outside every world.",
    ),
    Subject(
        "world", ("world", "worlds"),
        uses={
            "create": Use(create_run, create_items, offered=_has_account),
            "edit": Use(edit_run, edit_items, offered=_has_account),
            "delete": Use(delete_run, delete_items, offered=_has_account),
            "reset": Use(reset_run, reset_items, offered=_has_account),
            "view": Use(view_run, view_items, offered=_has_account),
            "export": Use(export_run, export_items, offered=_has_account),
            "import": Use(import_run, import_items, offered=_has_account),
            "enter": Use(enter_world_run, enter_world_items,
                         offered=_has_account),
        },
        help="The worlds you have made.",
    ),
]
