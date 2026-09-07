"""
The worldgen wizard: setting a world up, and editing one already built.

Both commands open the same menu. `worldgen` ends it by generating a world
from the draft; `worldedit` loads an existing world into the draft and ends by
writing it back, so a description can be refined without throwing the rooms
away to try it.
"""

from evennia.utils.evmenu import EvMenu

from commands.command import Command
from world import lore

#: Kept on the character while the wizard is open, so answers survive being
#: interrupted by the line editor and come back when it closes.
DRAFT = "worldgen_draft"


def _draft(caller):
    return getattr(caller.ndb, DRAFT, None) or {}


def _set(caller, **changes):
    draft = dict(_draft(caller))
    draft.update(changes)
    setattr(caller.ndb, DRAFT, draft)
    return draft


def open_wizard(caller, draft):
    """
    Start the wizard on a draft.

    `worldedit` comes in this way with a world's stored spec, which is what
    lets one menu serve both making a world and changing one.
    """
    setattr(caller.ndb, DRAFT, dict(draft))
    EvMenu(caller, "commands.worldgen_cmd", startnode="node_main",
           cmd_on_exit=None)


def _editing(draft):
    return draft.get("mode") == "edit"


class CmdWorldgen(Command):
    """
    Set up and generate a new AI world.

    Usage:
      worldgen
      worldgen <short description>

    Opens a wizard for the things a world is made of:

      |wTitle|n        a short name, which is what world listings show.
      |wDescription|n  as long as you like. Every room, item and character in
                       the world is generated with this in front of it, and
                       every NPC is told it. Write |w<user>|n where the player
                       should be named, and it becomes whatever they are
                       called in this world -- so "<user> is the rightful
                       heir" is true of whoever is playing.
      |wYour name|n    what you are called here, which you can change later
                       with |wname|n.
      |wYour looks|n   what other characters see when they look at you here.

    Below those sits |wguidance|n: a separate note for each generator, given
    only to that one. The description is read by everything, so it should stay
    short enough that everything still attends to it; anything that concerns
    one task alone belongs in that task's guidance instead.

      |wRooms|n        the layout, the naming, the room descriptions
      |wCharacters|n   who is generated to be found in the world
      |wItems|n        the things lying about, and the ones you ask for
      |wDialogue|n     how characters speak, act and set errands
      |wRules|n        what is possible here -- consulted whenever the world
                       has to decide whether something can exist or be done

    So "every character is a vampire" goes to Characters, where it is the
    whole job, rather than into a description that the room writer must read
    past on every call.

    Giving a description on the command line fills that field in and opens
    the wizard on it. Use |wworldedit|n to change any of this afterwards.

    Requires an OpenRouter API key (see |wapikey|n) and a model (see
    |wmodels|n).
    """

    key = "worldgen"
    locks = "cmd:all()"
    help_category = "World"

    def func(self):
        caller = self.caller
        account = getattr(caller, "account", None) or caller

        try:
            account.get_openrouter_key()
        except ValueError as e:
            caller.msg(str(e))
            return

        open_wizard(caller, {
            "mode": "create",
            "world_id": None,
            "description": self.args.strip(),
            "title": "",
            "player_name": "",
            "player_description": "",
            "guidance": {},
        })


# ---------------------------------------------------------------------------
# Wizard nodes
# ---------------------------------------------------------------------------

def _shown(value, empty):
    """One line standing for a field's value, or a grey note when it has none."""
    from evennia.utils.ansi import raw

    if not value:
        return f"|x{empty}|n"
    first = value.splitlines()[0]
    more = len(value.splitlines()) - 1
    text = first if len(first) <= 58 else first[:55].rstrip() + "..."
    # Escaped, so what someone typed is what they see back. Evennia reads
    # "{{" and "||" as markup, and would otherwise show "{{user}}" as
    # "{user}}" and look as though the text had been damaged.
    return f"{raw(text)}|x{f'  (+{more} more lines)' if more else ''}|n"


#: Where every field's value starts, so the whole summary reads down one
#: column however many fields there turn out to be.
_VALUE_COLUMN = 21


def _row(number, label, value, empty):
    """One numbered field, its dotted leader, and what it is set to."""
    room_for_leader = _VALUE_COLUMN - len(f"  {number}. {label} ")
    dots = ". " * max(0, room_for_leader // 2)
    pad = " " * max(0, room_for_leader - len(dots))
    return f"  |w{number}.|n {label} {pad}{dots}{_shown(value, empty)}"


def _summary(draft):
    guide = draft.get("guidance") or {}
    lines = [
        _row(1, "Title", draft.get("title"), "not set"),
        _row(2, "Description", draft.get("description"), "not set — required"),
        _row(3, "Your name", draft.get("player_name"), "your account name"),
        _row(4, "Your looks", draft.get("player_description"), "not set"),
        "",
        "|wGuidance|n — read only by the generator it names:",
    ]
    for number, facet in enumerate(lore.FACETS, start=5):
        lines.append(_row(number, facet.label, guide.get(facet.key), "not set"))
    return "\n".join(lines)


def node_main(caller, raw_string, **kwargs):
    draft = _draft(caller)
    editing = _editing(draft)

    heading = (f"|wEditing {draft.get('title') or 'this world'}|n"
               if editing else "|wNew world|n")
    footer = (
        "The description is put in front of every generator and every "
        "character in the world, so keep it to what they all need; put what "
        "only one of them needs in that one's guidance. Write |w<user>|n "
        "where the player should be named, and it becomes whatever they are "
        "called here."
    )
    if editing:
        footer += (
            "\n\nChanges apply to whatever is generated from now on. Rooms, "
            "items and characters that already exist keep the text they were "
            "written with."
        )

    text = f"{heading}\n\n{_summary(draft)}\n\n{footer}"

    options = [
        {"key": ("1", "title"), "desc": "Set the title",
         "goto": ("node_ask", {"field": "title", "label": "title"})},
        {"key": ("2", "description"), "desc": "Write the description (opens an editor)",
         "goto": "node_description"},
        {"key": ("3", "name"), "desc": "Set your name in this world",
         "goto": ("node_ask", {"field": "player_name", "label": "name"})},
        {"key": ("4", "looks"), "desc": "Describe how you look here",
         "goto": ("node_ask", {"field": "player_description", "label": "appearance"})},
    ]
    for number, facet in enumerate(lore.FACETS, start=5):
        # Both the label and the storage key answer, since "characters" and
        # "npcs" are the same thing to a player and only one of them is shown.
        names = dict.fromkeys([str(number), facet.label.lower(), facet.key])
        options.append({
            "key": tuple(names),
            "desc": f"{facet.label} — {facet.hint}",
            "goto": ("node_guidance", {"facet": facet.key}),
        })

    if editing:
        options.append({"key": ("s", "save"), "desc": "|gSave these changes|n",
                        "goto": "node_save"})
    elif draft.get("description"):
        options.append({"key": ("g", "go", "generate"),
                        "desc": "|gGenerate this world|n", "goto": "node_generate"})
    options.append({"key": ("q", "quit", "cancel"),
                    "desc": "Discard these changes" if editing else "Cancel",
                    "goto": "node_cancel"})
    return text, options


def node_ask(caller, raw_string, **kwargs):
    """A single-line field."""
    field = kwargs.get("field", "title")
    label = kwargs.get("label", field)
    current = _draft(caller).get(field) or ""

    text = f"Type the {label}, or |wclear|n to unset it."
    if current:
        text = f"Currently: |w{current}|n\n\n" + text

    def _save(caller, raw, **kw):
        value = raw.strip()
        if value.lower() == "clear":
            value = ""
        _set(caller, **{field: value})
        return "node_main", {}

    return text, [
        {"key": ("b", "back"), "desc": "Back without changing it", "goto": "node_main"},
        {"key": "_default", "desc": f"Type the {label}", "goto": _save},
    ]


def _open_editor(caller, key, load, save, note):
    """
    Hand the screen to the line editor, and take the menu back afterwards.

    A world's prose runs to paragraphs and a menu prompt is a poor place to
    write one, so every long field is written here instead. The menu cannot
    share the screen with the editor, so it closes and is reopened on quit --
    which is safe because the draft lives on the character, not in the menu.
    """
    from evennia.utils.eveditor import EvEditor

    caller.msg(note)

    def _save(caller, buffer):
        save(caller, buffer.strip())
        return True

    def _quit(caller):
        caller.msg(f"{key.capitalize()} saved.")
        EvMenu(caller, "commands.worldgen_cmd", startnode="node_main",
               cmd_on_exit=None)

    EvEditor(caller, loadfunc=load, savefunc=_save, quitfunc=_quit,
             key=key, persistent=False)


def node_description(caller, raw_string, **kwargs):
    """The description everything in the world is generated in front of."""

    def load(caller):
        return _draft(caller).get("description", "")

    def save(caller, text):
        _set(caller, description=text)

    _open_editor(
        caller, "world description", load, save,
        note=(
            "This goes to every generator and every character, so keep it to "
            "what the whole world needs; anything only one task needs belongs "
            "in that task's guidance.\n"
            "Write |w<user>|n where the player should be named. (The "
            "doubled-brace form works too, but Evennia's markup eats one brace "
            "when showing it back -- what you type is stored correctly.)"
        ),
    )
    return "", []


def node_guidance(caller, raw_string, **kwargs):
    """One generator's own instructions."""
    facet = lore.FACETS_BY_KEY.get(kwargs.get("facet"))
    if facet is None:
        return "node_main", {}

    def load(caller):
        return (_draft(caller).get("guidance") or {}).get(facet.key, "")

    def save(caller, text):
        guide = dict(_draft(caller).get("guidance") or {})
        if text:
            guide[facet.key] = text
        else:
            guide.pop(facet.key, None)
        _set(caller, guidance=guide)

    _open_editor(
        caller, f"{facet.label.lower()} guidance", load, save,
        note=(
            f"|w{facet.label}|n: {facet.hint}\n"
            f"Only this part of the world reads it, so it can be as detailed "
            f"as you like without crowding anything else. Save an empty "
            f"buffer to remove it. |w<user>|n works here too."
        ),
    )
    return "", []


def node_generate(caller, raw_string, **kwargs):
    draft = _draft(caller)
    account = getattr(caller, "account", None) or caller

    title = draft.get("title") or ""
    caller.msg(f"Generating |w{title or 'your world'}|n...")

    def on_success(room):
        caller.msg(f"|gEntering: {room.db.room_title or room.key}|n")
        caller.move_to(room, quiet=False)

    def on_error(err):
        caller.msg(f"|rWorld generation failed: {err}|n")

    from world.worldgen import generate_first_room

    generate_first_room(account, dict(draft), on_success, on_error,
                        creator_character=caller)
    setattr(caller.ndb, DRAFT, None)
    return "", []


def node_save(caller, raw_string, **kwargs):
    """Write an edited draft back onto the world it came from."""
    from evennia.objects.models import ObjectDB

    draft = _draft(caller)
    setattr(caller.ndb, DRAFT, None)

    try:
        root = ObjectDB.objects.get(id=draft.get("world_id"))
    except ObjectDB.DoesNotExist:
        caller.msg("|rThat world no longer exists, so nothing was saved.|n")
        return "", []

    lore.store(root, draft)
    # Unlike a new world, an edit is allowed to take a name or a look away
    # again: the player is changing what they set, not being given a default.
    caller.set_world_name(root, (draft.get("player_name") or "").strip())
    caller.set_world_desc(root, (draft.get("player_description") or "").strip())

    guided = [lore.FACETS_BY_KEY[key].label
              for key in (root.db.world_guidance or {})
              if key in lore.FACETS_BY_KEY]
    caller.msg(
        f"|gSaved |w{lore.title(root)}|g.|n Guidance is set for: "
        f"{', '.join(guided) or '|xnothing|n'}.\n"
        "Rooms, items and characters already built keep the text they were "
        "written with; anything generated from now on follows this."
    )
    return "", []


def node_cancel(caller, raw_string, **kwargs):
    editing = _editing(_draft(caller))
    setattr(caller.ndb, DRAFT, None)
    caller.msg("No changes saved." if editing else "No world generated.")
    return "", []
