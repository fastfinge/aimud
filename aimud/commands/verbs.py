"""
The verb commands: create, edit, delete, reset, view, import, export, enter.

Each is the same command with a different word. It finds the subject named
after it and hands over the rest of the line; typed alone, or with a subject
and nothing more, it opens a menu. What a verb can act on lives in
`commands.subjects`, so these classes never grow a branch per subject.

Inside a generated world the parser only gives one of these the input when it
names a subject or nothing at all, so `reset the trap` still reaches the
world. See `server/conf/cmdparser.py`.
"""

from commands.command import Command
from commands import subjects
from world import menus


class VerbCommand(Command):
    """
    Do something to one of the things this game lets you make.

    Usage:
      <verb>
      <verb> <subject> [...]
    """

    verb = ""
    locks = "cmd:all()"
    help_category = "World"

    #: Not a verb the engine owns. A world may still write rules for
    #: "reset" or "view" -- this command only takes the input when a subject
    #: follows -- so it must not be listed where generators are told which
    #: verbs are the engine's. See `world.verbs.engine_verbs`.
    reserves_word = False

    def func(self):
        ctx = menus.Context(self.caller, session=self.session)
        subject, rest = subjects.named(self.verb, self.args)
        if subject is None:
            if self.args.strip():
                # Outside a world, where the parser hands over everything.
                self.caller.msg(self._nothing_called(ctx, self.args.strip()))
                return
            menus.open_menu(self.caller, subjects.verb_form(self.verb),
                            session=self.session)
            return
        subject.uses[self.verb].run(self, ctx, rest.split())

    def _nothing_called(self, ctx, asked):
        words = [subject.words()[0] for subject in subjects.for_verb(self.verb)
                 if subject.words()]
        if not words:
            return f"There is nothing you can {self.verb} yet."
        listed = ", ".join(f"|w{self.verb} {word}|n" for word in words)
        return (f"You cannot {self.verb} {asked}. You can {listed}, or type "
                f"|w{self.verb}|n on its own to choose.")

    def get_help(self, caller, cmdset):
        """
        The docstring, and every subject this verb has, read off the register.

        Built rather than written, like `effects`: a subject added by a plugin
        documents itself here without anybody editing this command.
        """
        lines = [self.__doc__.strip(), ""]
        found = subjects.for_verb(self.verb)
        if not found:
            lines.append(f"There is nothing to {self.verb} yet.")
        for subject in found:
            words = subject.words()
            if words:
                lines.append(f"  |w{self.verb} {words[0]}|n: {subject.help}")
        return "\n".join(lines)


class CmdCreate(VerbCommand):
    """
    Make something new.

    Usage:
      create
      create world [<description>]

    On its own it asks what to make. |wcreate world|n opens the world wizard:
    a title, a description every generator reads, who you are in the world,
    and guidance for each generator on its own. Giving a description fills
    that in. Nothing is made until you choose to generate it.
    """

    key = "create"
    verb = "create"


class CmdEdit(VerbCommand):
    """
    Change something you made.

    Usage:
      edit
      edit world [<number or title>]

    |wedit world|n opens the same wizard |wcreate world|n uses, filled in with
    what that world was set up with. Nothing already built changes; the new
    wording governs whatever is generated afterwards.
    """

    key = "edit"
    verb = "edit"


class CmdDelete(VerbCommand):
    """
    Delete something you made, permanently.

    Usage:
      delete
      delete world [<number or title>] [yes]

    You are asked yes or no first, unless you add |wyes|n or have turned that
    confirmation off. You cannot delete the world you are standing in.
    """

    key = "delete"
    verb = "delete"


class CmdReset(VerbCommand):
    """
    Put something back the way it started.

    Usage:
      reset
      reset world [<number or title>] [yes]

    |wreset world|n generates the world again from its setup. The new world is
    built first, and the old one is only removed once that succeeds.
    """

    key = "reset"
    verb = "reset"


class CmdView(VerbCommand):
    """
    Look over something the game keeps, without changing it.

    Usage:
      view
      view worlds
      view world <number or title>
    """

    key = "view"
    verb = "view"


class CmdImport(VerbCommand):
    """
    Bring something into the game from outside it.

    Usage:
      import
    """

    key = "import"
    verb = "import"


class CmdExport(VerbCommand):
    """
    Take something out of the game to use elsewhere.

    Usage:
      export
    """

    key = "export"
    verb = "export"


class CmdEnter(VerbCommand):
    """
    Go into one of your worlds, or back to where everybody starts.

    Usage:
      enter
      enter world [<number or title>]
      enter start

    |wenter world|n takes you to where you last were in that world, or to its
    first room. |wenter start|n takes you back to the room everybody starts
    in, outside every world; it also answers to that room's name, so |wenter
    limbo|n works too. On its own, |wenter|n lists where you can go.
    """

    key = "enter"
    verb = "enter"


VERB_COMMANDS = (CmdCreate, CmdEdit, CmdDelete, CmdReset, CmdView, CmdImport,
                 CmdExport, CmdEnter)
