"""
Account-level commands available to all logged-in players.
"""

from evennia.accounts.accounts import DefaultAccount

from commands.command import Command


def _get_account(caller):
    return caller if isinstance(caller, DefaultAccount) else caller.account


class CmdRounds(Command):
    """
    How many rounds the game's conversations with models take.

    Usage:
      rounds
      rounds <job>
      rounds world <number>
      rounds clear

    When the game asks a model something, the model may look things up
    before it answers, and every look is a round: another call, and more
    waiting. This counts them for each job -- the same jobs |wsettings
    models|n lists -- so the budgets can be set from what models actually do.

    |wrounds|n gives one line per job: how many conversations, how many
    rounds they took on average and at most, the budget, how often the model
    had to be made to answer, and how long they took.

    |wrounds <job>|n adds which tools were used and how often, and how often
    an answer was sent back to be put right.

    |wrounds world <number>|n counts only one of your worlds, numbered as
    |wworlds|n numbers them.

    |wrounds clear|n starts counting again, after a change worth measuring.
    What has been spent is kept.
    """

    key = "rounds"
    locks = "cmd:all()"
    help_category = "Account"
    account_caller = True

    def func(self):
        from world import ledger

        account = _get_account(self.caller)
        word, _, rest = self.args.strip().partition(" ")
        word, rest = word.lower(), rest.strip()

        if word == "clear":
            ledger.forget_loops(account)
            self.caller.msg("Round counts cleared. What has been spent is "
                            "kept.")
            return

        where = ""
        if word == "world":
            root = self._world(account, rest)
            if root is None:
                return
            from world import lore

            figures = ledger.loops(account, root.id)
            where = f" in {lore.title(root)}"
            word = ""
        else:
            figures = ledger.loops(account)

        if word:
            row = figures.get(word)
            if not row or not row["loops"]:
                self.caller.msg(f"No conversations have been counted for "
                                f"{word} yet.")
                return
            self.caller.msg(self._in_full(word, row))
            return

        if not figures:
            self.caller.msg(f"No conversations with tools have been counted"
                            f"{where} yet.")
            return
        ordered = sorted(figures.items(),
                         key=lambda pair: (-pair[1]["loops"], pair[0]))
        self.caller.msg("\n".join(self._line(job, row) for job, row in ordered))

    def _world(self, account, number):
        from commands.world_cmds import _resolve_worlds

        worlds = _resolve_worlds(account)
        try:
            root = worlds[int(number) - 1][0]
        except (ValueError, IndexError):
            self.caller.msg("Give a world's number, as |wworlds|n lists them: "
                            "|wrounds world 1|n.")
            return None
        return root

    @staticmethod
    def _line(job, row):
        """One job, the count first, so it is the first thing heard."""
        loops = row["loops"]
        said = [f"{loops} {'conversation' if loops == 1 else 'conversations'}"]
        if loops:
            said.append(f"{row['rounds'] / loops:.1f} rounds on average")
            said.append(f"{row['most_rounds']} at most")
        if row["limit"]:
            said.append(f"budget {row['limit']}")
        said.append(f"{row['forced']} made to answer")
        if row["failed"]:
            said.append(f"{row['failed']} failed or ran out")
        if loops and row["seconds"]:
            said.append(f"{row['seconds'] / loops:.0f} seconds on average")
        return f"{job}: " + ", ".join(said) + "."

    @classmethod
    def _in_full(cls, job, row):
        lines = [cls._line(job, row)]
        loops = row["loops"] or 1
        lines.append(f"{row['complaints']} answers sent back to be put right, "
                     f"{row['complaints'] / loops:.1f} a conversation.")
        tools = sorted(row["tools"].items(), key=lambda pair: (-pair[1],
                                                                pair[0]))
        if tools:
            lines.append("Tools used: " + ", ".join(
                f"{name} {calls} {'time' if calls == 1 else 'times'}"
                for name, calls in tools) + ".")
        if row["hints_shown"]:
            lines.append(f"{row['hints_used']} of {row['hints_shown']} hints "
                         f"were used.")
        return "\n".join(lines)
