"""
The remember command: ask your character what they recall.

A player should not have to keep notes on a legal pad beside the keyboard.
Their character was there, so the character is the one asked -- in plain
English, and answered from that character's own memory bank alone.
"""


from commands.command import Command

_RECALL_SYSTEM = """You answer a player's question about their own character's past in a text MUD.

You are given memories recalled from that character's memory, oldest first,
each with how long ago it was, and sometimes a line saying what is true now.
Answer from those only.

- Answer in one or two sentences, plainly, in second person ("You met her...").
- If the memories do not answer the question, say so plainly. Never invent an
  event, a name or a detail that is not in the memories.
- If the memories are partial, say what is known and what is not.
- Do not list the memories back or mention that you were given memories."""


def _sponsor_for(caller):
    """Who pays for this. See world.sponsor."""
    from world import sponsor

    return sponsor.of(caller)


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

        from world.memory import available, where_for

        if not available():
            caller.msg("You find your memory of recent events oddly blank.")
            return

        sponsor = _sponsor_for(caller)
        try:
            sponsor.key()      # refuse early rather than mid-prompt
        except ValueError as e:
            caller.msg(str(e))
            return

        if caller.ndb.recalling:
            caller.msg("You are already trying to remember something.")
            return
        caller.ndb.recalling = True

        model = sponsor.model_for("memory", "dialogue")
        where = where_for(caller)
        caller.msg("You cast your mind back...")

        # Imported here rather than inside `_fetch`, where an earlier version
        # had it: `llm.fetch` below is called in this scope, and a name bound
        # inside the inner function is not visible here. Every `recall` raised
        # NameError before it reached the thread pool.
        from world import busy, llm

        wait = busy.start(caller, "casting your mind back")

        def _fetch():
            # Recall in the thread pool, off the reactor.
            from world.memory import recall_rows_sync

            return recall_rows_sync(where, question, top_k=8)

        def _done(rows):
            # Back on the main thread: each memory is said again with the
            # names things have now, which reads the game's database. Then the
            # model is asked, off the reactor again.
            if not rows:
                _answered(None)
                return
            from world.memory import format_recalled

            try:
                memories = format_recalled(rows)
            except Exception as exc:
                wait.done()
                caller.ndb.recalling = False
                caller.msg(f"|rYou cannot gather your thoughts: {exc}|n")
                return
            wait.stage("putting what you remember into words")
            messages = [
                {"role": "system", "content": _RECALL_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Memories recalled:\n{memories}\n\n"
                        f"The player asks: {question}"
                    ),
                },
            ]
            llm.fetch(llm.ask, sponsor, model, messages,
                      on_success=_answered, on_error=_fail)

        def _answered(answer):
            wait.done()
            caller.ndb.recalling = False
            if answer is None:
                caller.msg("You cannot bring anything to mind about that.")
            else:
                caller.msg(str(answer).strip())

        def _fail(failure):
            wait.done()
            caller.ndb.recalling = False
            caller.msg(f"|rYou cannot gather your thoughts: {failure.getErrorMessage()}|n")

        llm.fetch(_fetch, on_success=_done, on_error=_fail)


class CmdMemoryMaintenance(Command):
    """
    Consolidate memories, and clear up after characters that no longer exist.

    Usage:
      memcheck            what would be done, changing nothing
      memcheck sleep      consolidate now
      memcheck sweep      delete banks nothing can read any more
      memcheck distil     turn recent summaries into what characters know
      memcheck all        all three

    Sleeping is what makes a memory permanent. Anything not consolidated is
    deleted once it passes mnemosyne's retention window, so a character that
    never sleeps remembers only the last few days. It happens on a clock and
    at every server start; this is for doing it now.

    Sweeping deletes memories nothing can reach any more: a world that has
    been removed, and anything left under the naming that came before one
    bank per world. A dbref is never issued twice, so nothing will ever ask
    for either of them again.

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
