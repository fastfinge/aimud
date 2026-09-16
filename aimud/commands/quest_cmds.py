"""
The quests command: see what you have been asked to do, and answer for it.
"""

from commands.command import Command
from world import menus


class CmdQuests(Command):
    """
    See what people have asked of you, and how far along you are.

    Usage:
      quests
      quests hint
      quests accept
      quests decline
      quests abandon [yes]

    Characters you meet may ask you to do things. Anything offered waits at
    the top of the list until you accept or decline it; anything underway
    shows each part of it and whether you have done that part yet. On its
    own, |wquests|n shows the list and then offers whichever of the others
    apply.

    You carry one errand at a time. Until it is done, has failed, or you
    abandon it, nobody will ask you for anything else -- and abandoning costs
    you nothing beyond the giver knowing you are not going to do it. You are
    asked first, unless you add |wyes|n or have turned that confirmation off.

    Some errands come with a time limit, and some with a consequence for
    letting it run out. Both are shown before you agree to anything.

    |wquests hint|n shows how far along you are and what to do next: the
    actual command to type, worked out from where you are standing and what
    the world already knows. It is a reminder, not an autopilot -- nothing
    acts for you, and ignoring it costs you nothing. See also |wgoal|n, which
    does the same for something you decided to do yourself.

    A number may be given if you want to name one exactly, but with a single
    errand at a time it is rarely needed.
    """

    key = "quests"
    aliases = ["quest"]
    locks = "cmd:all()"
    help_category = "General"

    def parse(self):
        parts = self.args.strip().split()
        self.action = parts[0].lower() if parts else ""
        self.confirmed = bool(parts) and parts[-1].lower() in ("yes", "confirm")
        self.number = None
        for part in parts[1:]:
            if part.isdigit():
                self.number = int(part)
                break

    def func(self):
        caller = self.caller

        if not self.action:
            menus.open_menu(caller, QUESTS, session=self.session)
            return

        if self.action == "hint":
            caller.msg(hint(caller))
            return

        if self.action not in ("accept", "decline", "abandon"):
            caller.msg("Usage: |wquests|n, |wquests hint|n, |wquests accept|n, "
                       "|wquests decline|n, |wquests abandon|n.")
            return

        if self.action == "abandon" and not self.confirmed:
            # The giver is told, so it is asked first -- unless the player has
            # said yes already or turned that confirmation off.
            menus.confirm(caller, ABANDON_QUESTION,
                          lambda: caller.msg(answer(caller, "abandon",
                                                    self.number)),
                          key="abandon_quest", session=self.session,
                          command="quests abandon")
            return
        caller.msg(answer(caller, self.action, self.number))


ABANDON_QUESTION = ("Give up on the errand you are carrying? Whoever asked is "
                    "told.")


def listing(caller):
    """
    The quest list, brought up to date first so a quest finished a moment ago
    does not still read as outstanding.
    """
    from world import quests

    quests.review(caller)
    return quests.format_list(caller)


def hint(caller):
    """How far along, and the command to type next. Up to date first."""
    from world import hints, quests

    quests.review(caller)
    return hints.quest_hint(caller)


def answer(caller, action, number=None):
    """
    Accept, decline or abandon. Returns what to tell the caller.

    The number is optional: there is only ever one offer waiting and one
    errand underway, so naming it is a convenience, not a requirement. The
    person who asked hears the answer, and so do the characters in the room.
    """
    from world import quests

    if action == "accept":
        quest, message = quests.accept(caller, number)
    elif action == "decline":
        quest, message = quests.decline(caller, number)
    else:
        quest, message = quests.abandon(caller, number)
    if quest is None:
        return message

    room = caller.location
    if room:
        verb = {"accept": "accepts", "decline": "declines",
                "abandon": "gives up on"}[action]
        room.msg_contents(
            f"{caller.get_display_name(caller)} {verb} {quest['giver']}'s request.",
            exclude=[caller],
        )
        from world.npc_gen import notify_npcs

        notify_npcs(room, "action", caller.get_display_name(caller),
                    f"{verb} the request: {quest['title']}",
                    exclude=caller, actor=caller)

    if action == "accept":
        # It may already be satisfied by what the player happens to carry.
        quests.review(caller)
    return message


def _caller(ctx):
    return ctx.character or ctx.caller


def _quest_items(ctx):
    """Only what applies: an offer to answer, or an errand to give up."""
    from world import quests

    caller = _caller(ctx)
    items = [menus.Action("hint", "What to do next",
                          run=lambda ctx: hint(_caller(ctx)),
                          command=lambda ctx: "quests hint")]
    if quests.offered_to(caller):
        items += [
            menus.Action("accept", "Accept the offer",
                         run=lambda ctx: answer(_caller(ctx), "accept"),
                         command=lambda ctx: "quests accept"),
            menus.Action("decline", "Decline the offer",
                         run=lambda ctx: answer(_caller(ctx), "decline"),
                         command=lambda ctx: "quests decline"),
        ]
    if quests.current(caller):
        items.append(menus.Action(
            "abandon", "Give up on your errand",
            run=lambda ctx: answer(_caller(ctx), "abandon"),
            confirm="abandon_quest", question=ABANDON_QUESTION,
            command=lambda ctx: "quests abandon"))
    return items


QUESTS = menus.Form(
    key="quests", title="Quests", kind=menus.VIEW,
    intro=lambda ctx: listing(_caller(ctx)), items=_quest_items,
)
