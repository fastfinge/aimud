"""
The clothing commands: wear, remove, cover, uncover.

Thin wrappers. Every decision -- whether a thing can be worn, how many hats
fit on a head, what the room is told -- lives in `world.clothing`, because an
NPC putting its coat on has to reach exactly the same answers without going
anywhere near a command. What is here is only the finding of the garment a
player named, and the telling of who saw what.
"""

from commands.command import Command
from world import clothing


def _find_carried(caller, query, worn=None):
    """
    A thing the caller has on them, by name or by pronoun.

    Search is limited to their own contents: `wear` and `remove` are about
    what you already hold, and looking further afield would only find someone
    else's coat and refuse it a moment later.

    `worn` narrows to garments that are (or are not) currently being worn, so
    "remove hat" finds the one on your head rather than the spare in your bag.

    A pronoun is resolved before the search, because `caller.search` looks
    for a thing NAMED "it" and finds none -- the same gap `get` and `drop`
    had. Narrowed by `worn` afterwards like any other candidate, so "remove
    it" said of something not being worn is refused in words rather than
    quietly finding a different garment.
    """
    from world import nounphrase, referents

    text = str(query or "").strip()
    if not text:
        return None

    spoken = nounphrase.read(text).pronoun
    if spoken:
        found = referents.recall(caller, spoken)
        if found is None or found.location is not caller:
            return None
        if worn is not None and bool(found.db.worn) != worn:
            return None
        return found

    candidates = [obj for obj in caller.contents
                  if worn is None or bool(obj.db.worn) == worn]
    if not candidates:
        return None
    found = caller.search(text, candidates=candidates, quiet=True)
    if not found:
        return None
    return found[0] if isinstance(found, (list, tuple)) else found


def _announce(caller, actor_text, event=None):
    """Tell the wearer, and tell the room if there was anything to see."""
    from world import events, verbs

    if event is not None:
        # So that "it" means this garment next time. Only on the paths that
        # did something: a refusal has not referred to anything.
        verbs.note_one(caller, event.roles.get("direct"))
    events.show(actor_text, event, caller)


class CmdWear(Command):
    """
    Put on something you are carrying.

    Usage:
      wear <item>
      wear <item> = <how you are wearing it>

    The clothes you have on are shown to anyone who looks at you, so what you
    wear is part of how you appear. Adding a style after |w=|n describes the
    way you wear it -- |wwear scarf = wound twice about the throat|n -- and
    that is shown along with it.

    Some garments cover others when you put them on; see |wcover|n.
    """

    key = "wear"
    aliases = ["don"]
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        args = self.args.strip()
        if not args:
            caller.msg("Wear what?")
            return

        name, _, style = args.partition("=")
        garment = _find_carried(caller, name.strip(), worn=False)
        if garment is None:
            caller.msg(f"You are not carrying any {name.strip()}.")
            return

        _announce(caller, *clothing.put_on(caller, garment,
                                           wearstyle=style.strip() or True)[1:])


class CmdRemove(Command):
    """
    Take off something you are wearing.

    Usage:
      remove <item>

    You keep hold of it -- taking a coat off is not dropping it. Anything
    covered by what you take off comes back into view.
    """

    key = "remove"
    aliases = ["doff"]
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        args = self.args.strip()
        if not args:
            caller.msg("Remove what?")
            return

        garment = _find_carried(caller, args, worn=True)
        if garment is None:
            caller.msg(f"You are not wearing any {args}.")
            return

        _announce(caller, *clothing.take_off(caller, garment)[1:])


class CmdCover(Command):
    """
    Hide one thing you are wearing under another.

    Usage:
      cover <worn item> with <item>

    The covered garment stops showing in your description and cannot be taken
    off until whatever is over it comes off first. If the covering garment is
    not on yet, you put it on in the same movement.
    """

    key = "cover"
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        args = self.args.strip()
        under, _, over = args.partition(" with ")
        if not under.strip() or not over.strip():
            caller.msg("Usage: cover <worn item> with <item>")
            return

        garment = _find_carried(caller, under.strip(), worn=True)
        if garment is None:
            caller.msg(f"You are not wearing any {under.strip()}.")
            return
        covering = _find_carried(caller, over.strip())
        if covering is None:
            caller.msg(f"You are not carrying any {over.strip()}.")
            return

        _announce(caller, *clothing.cover_with(caller, garment, covering)[1:])


class CmdUncover(Command):
    """
    Bring a covered garment back into view.

    Usage:
      uncover <worn item>

    Whatever was covering it stays on; it simply stops hiding this.
    """

    key = "uncover"
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        args = self.args.strip()
        if not args:
            caller.msg("Uncover what?")
            return

        garment = _find_carried(caller, args, worn=True)
        if garment is None:
            caller.msg(f"You are not wearing any {args}.")
            return

        _announce(caller, *clothing.uncover(caller, garment)[1:])
