"""
The remember command: ask your character what they recall.

A player should not have to keep notes on a legal pad beside the keyboard.
Their character was there, so the character is the one asked -- in plain
English, and answered from that character's own memory bank alone.
"""


from commands.command import Command

_RECALL_SYSTEM = """You answer a player's question about their own character's past in a text MUD.

You are given memories recalled from that character's memory, most relevant first.
Answer from those memories only.

- Answer in one or two sentences, plainly, in second person ("You met her...").
- If the memories do not answer the question, say so plainly. Never invent an
  event, a name or a detail that is not in the memories.
- If the memories are partial, say what is known and what is not.
- Do not list the memories back or mention that you were given memories."""


def _get_account(caller):
    return getattr(caller, "account", None) or caller


class CmdRemember(Command):
    """
    Ask your character what they remember.

    Usage:
      remember <question>

    Your character records where they have been, what they have witnessed and
    what they have done. This asks them about it in plain English, so you do
    not have to keep notes yourself.

    Examples:
      remember what did the captain ask me to do?
      remember have I met Cherrie before?
      remember where did I find the brass key?

    Only your own character's memories are searched. You can never recall
    something that happened to somebody else.
    """

    key = "remember"
    aliases = ["recall"]
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        question = self.args.strip()

        if not question:
            caller.msg(
                "Ask your character something, for example: "
                "|wremember have I met Cherrie before?|n"
            )
            return

        from world.memory import available, bank_for

        if not available():
            caller.msg("You find your memory of recent events oddly blank.")
            return

        account = _get_account(caller)
        try:
            api_key = account.get_openrouter_key()
        except ValueError as e:
            caller.msg(str(e))
            return

        if caller.ndb.recalling:
            caller.msg("You are already trying to remember something.")
            return
        caller.ndb.recalling = True

        model = account.model_for("memory", "dialogue")
        bank = bank_for(caller)
        caller.msg("You cast your mind back...")

        def _fetch():
            # Recall and the model call share one trip into the thread pool,
            # keeping both off the reactor.
            from world import llm
            from world.memory import format_memories, recall_sync

            memories = recall_sync(bank, question, top_k=8)
            if not memories:
                return None
            messages = [
                {"role": "system", "content": _RECALL_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Memories recalled:\n{format_memories(memories)}\n\n"
                        f"The player asks: {question}"
                    ),
                },
            ]
            return llm.ask(api_key, model, messages)

        def _done(answer):
            caller.ndb.recalling = False
            if answer is None:
                caller.msg("You cannot bring anything to mind about that.")
            else:
                caller.msg(str(answer).strip())

        def _fail(failure):
            caller.ndb.recalling = False
            caller.msg(f"|rYou cannot gather your thoughts: {failure.getErrorMessage()}|n")

        llm.fetch(_fetch, on_success=_done, on_error=_fail)


class CmdMemoryMaintenance(Command):
    """
    Consolidate memories, and clear up after characters that no longer exist.

    Usage:
      memcheck            what would be done, changing nothing
      memcheck sleep      consolidate now
      memcheck sweep      delete banks whose character is gone
      memcheck distil     turn recent summaries into what characters know
      memcheck all        all three

    Sleeping is what makes a memory permanent. Anything not consolidated is
    deleted once it passes mnemosyne's retention window, so a character that
    never sleeps remembers only the last few days. It happens on a clock and
    at every server start; this is for doing it now.

    Sweeping deletes the memories of characters that have been removed --
    usually a whole world at once. Those banks are unreachable: a dbref is
    never issued twice, so nothing will ever ask for them again.

    Distilling reads what sleeping wrote and asks the memory model what each
    character now knows. It is the only part of this that costs anything, so
    it happens on its own only when the game has been quiet for a while; this
    runs it whether or not it has.
    """

    key = "memcheck"
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "World"

    def func(self):
        from world import memory

        what = self.args.strip().lower() or "report"
        if not memory.available():
            self.caller.msg("The memory backend is not available.")
            return

        banks = memory._bank_names()
        stranded = memory.orphaned_banks()
        alive = len(banks) - len(stranded)

        if what == "report":
            lines = [
                f"|wMemory banks:|n {len(banks)} "
                f"({alive} in use, {len(stranded)} orphaned)"
            ]
            for name in stranded[:10]:
                lines.append(f"  |x{name} — character #{name.rsplit('-', 1)[1]} is gone|n")
            if len(stranded) > 10:
                lines.append(f"  |x...and {len(stranded) - 10} more|n")
            lines.append(
                "\nType |wmemcheck sleep|n to consolidate, |wmemcheck sweep|n "
                "to clear up, |wmemcheck all|n for both."
            )
            self.caller.msg("\n".join(lines))
            return

        if what in ("sleep", "all"):
            self.caller.msg(
                f"Consolidating {len(banks)} bank(s) in the background..."
            )
            memory.consolidate(
                on_done=lambda result: self.caller.msg(
                    f"Consolidated. {sum(1 for r in result.values() if isinstance(r, dict) and r.get('status') != 'no_op')} "
                    f"of {len(result)} bank(s) had anything old enough to sleep on."
                )
            )

        if what in ("sweep", "all"):
            if not stranded:
                self.caller.msg("No orphaned banks to clear up.")
                return
            self.caller.msg(f"Clearing up {len(stranded)} orphaned bank(s)...")
            memory.drop_banks(
                stranded,
                on_done=lambda removed: self.caller.msg(
                    f"Deleted {len(removed)} bank(s)."
                ),
            )

        if what in ("distil", "all"):
            from world.fact_gen import distil

            self.caller.msg("Distilling recent summaries into facts...")
            distil(on_done=lambda tally: self.caller.msg(
                f"Distilled {tally['facts']} fact(s) from "
                f"{tally['characters']} character(s)."
            ))

        if what not in ("sleep", "sweep", "distil", "all"):
            self.caller.msg("Usage: memcheck [sleep|sweep|distil|all]")
