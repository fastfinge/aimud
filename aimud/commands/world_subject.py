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

from commands.subjects import Subject, Use, names_for, owns
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
                       empty=empty, required=required)


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


def _wizard_items(ctx):
    items = list(WIZARD_FIELDS) + [_guidance_field(f) for f in lore.FACETS]
    if ctx.draft.get("mode") == "edit":
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


WIZARD = menus.Form(
    key="world", title=_wizard_title, intro=_wizard_intro,
    items=_wizard_items, discard="Throw away what you have entered?",
)


def new_draft(description=""):
    return {"mode": "create", "world_id": None, "description": description,
            "title": "", "player_name": "", "player_description": "",
            "guidance": {}}


def _key_problem(caller):
    try:
        sponsor_mod.of_account(account_of(caller)).key()
    except ValueError as err:
        return str(err)
    return ""


def create_run(cmd, ctx, words):
    caller = cmd.caller
    problem = _key_problem(caller)
    if problem:
        caller.msg(problem)
        return
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
    spec = lore.spec_of(root, caller)
    description = spec["description"]
    if not description:
        return ("That world has no stored description, so it cannot be "
                "rebuilt. |wdelete world|n removes it instead.")
    problem = _key_problem(caller)
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


def _reset_question(root, count):
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
    from world import activity

    description = (root.db.world_description or "").strip().splitlines()
    first = description[0] if description else ""
    lines = [f"|w{lore.title(root)}|n, {count} room{'s' if count != 1 else ''}, "
             f"running {activity.mode(root)}."]
    if first:
        lines.append(first)
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
            "enter": Use(enter_world_run, enter_world_items,
                         offered=_has_account),
        },
        help="The worlds you have made.",
    ),
]
