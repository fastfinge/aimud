"""
The worldgen command: a wizard for setting a world up before generating it.
"""

from evennia.utils.evmenu import EvMenu

from commands.command import Command

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
                       every NPC is told it. Write |w{{user}}|n where the player
                       should be named, and it becomes whatever they are
                       called in this world -- so "{{user}} is the rightful
                       heir" is true of whoever is playing.
      |wYour name|n    what you are called here, which you can change later
                       with |wname|n.
      |wYour looks|n   what other characters see when they look at you here.

    Giving a description on the command line fills that field in and opens
    the wizard on it.

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

        _set(caller, description=self.args.strip(), title="",
             player_name="", player_description="")
        EvMenu(caller, "commands.worldgen_cmd", startnode="node_main",
               cmd_on_exit=None)


# ---------------------------------------------------------------------------
# Wizard nodes
# ---------------------------------------------------------------------------

def _summary(draft):
    def shown(value, empty):
        if not value:
            return f"|x{empty}|n"
        first = value.splitlines()[0]
        more = len(value.splitlines()) - 1
        text = first if len(first) <= 58 else first[:55].rstrip() + "..."
        return f"{text}|x{f'  (+{more} more lines)' if more else ''}|n"

    return (
        f"  |w1.|n Title . . . . . {shown(draft.get('title'), 'not set')}\n"
        f"  |w2.|n Description . . {shown(draft.get('description'), 'not set — required')}\n"
        f"  |w3.|n Your name . . . {shown(draft.get('player_name'), 'your account name')}\n"
        f"  |w4.|n Your looks  . . {shown(draft.get('player_description'), 'not set')}"
    )


def node_main(caller, raw_string, **kwargs):
    draft = _draft(caller)
    text = (
        "|wNew world|n\n\n"
        + _summary(draft)
        + "\n\nThe description is put in front of every generator and every "
        "character in the world. Write |w{{user}}|n where the player should be "
        "named."
    )

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
    if draft.get("description"):
        options.append({"key": ("g", "go", "generate"),
                        "desc": "|gGenerate this world|n", "goto": "node_generate"})
    options.append({"key": ("q", "quit", "cancel"), "desc": "Cancel",
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


def node_description(caller, raw_string, **kwargs):
    """
    The description, in a proper line editor.

    A world description is meant to run to paragraphs, and a menu prompt is a
    poor place to write one.
    """
    from evennia.utils.eveditor import EvEditor

    def load(caller):
        return _draft(caller).get("description", "")

    def save(caller, buffer):
        _set(caller, description=buffer.strip())
        return True

    def quit_editor(caller):
        caller.msg("Description saved.")
        EvMenu(caller, "commands.worldgen_cmd", startnode="node_main",
               cmd_on_exit=None)

    # The menu has to stand aside while the editor has the screen.
    EvEditor(caller, loadfunc=load, savefunc=save, quitfunc=quit_editor,
             key="world description", persistent=False)
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


def node_cancel(caller, raw_string, **kwargs):
    setattr(caller.ndb, DRAFT, None)
    caller.msg("No world generated.")
    return "", []
