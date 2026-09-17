"""
The remember command: ask your character what they recall.

A player should not have to keep notes on a legal pad beside the keyboard.
Their character was there, so the character is the one asked -- in plain
English, and answered from that character's own memory bank alone.
"""


from commands.command import Command
from world import menus

_RECALL_SYSTEM = """You answer a player's question about their own character's past in a text MUD.

You are given memories recalled from that character's memory, oldest first,
each with how long ago it was, and sometimes a line saying what is true now.
Answer from those only.

- Answer in one or two sentences, plainly, in second person ("You met her...").
- If they only half answer it, you may call recall with other words before
  answering.
- If the memories do not answer the question, say so plainly. Never invent an
  event, a name or a detail that is not in the memories.
- If the memories are partial, say what is known and what is not.
- Do not list the memories back or mention that you were given memories."""


def _sponsor_for(caller):
    """Who pays for this. See world.sponsor."""
    from world import sponsor

    return sponsor.of(caller)


#: Rounds `remember` may take (docs/generator-tool-loops.md §10.3): enough to
#: recall again under other words, and a player is waiting.
REMEMBER_ROUNDS = 6


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
        if question:
            recall(caller, question)
            return

        # Nothing asked: a one-question form, which asks the moment it has
        # the question. With nobody to show it to, the example as before.
        if menus.interactive(menus.account_of(caller) or caller):
            menus.open_menu(caller, ASK, session=self.session)
            return
        caller.msg(
            "Ask your character something, for example: "
            "|wremember have I met Cherrie before?|n"
        )


def recall(caller, question):
    """
    Ask `caller`'s own memory `question`, and tell them the answer.

    What `remember <question>` does, and what its menu does once a question
    is typed. Everything is said to the caller as it happens; nothing is
    returned.
    """
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
            here = caller.location
            memories = format_recalled(
                rows, world_root=here.db.world_root if here is not None else None)
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
        from world import lookups
        from world import toolbox as tb

        # No finish tool: the answer is prose, and the loop ends on a
        # reply that calls nothing. `recall` is offered for a question the
        # first memories only half answer.
        room = caller.location
        box = tb.Toolbox(lookups.named("recall"), tb.ToolContext(
            world_root=room.db.world_root if room is not None else None,
            room=room, actor=caller, sponsor=sponsor, job="memory",
            wait=wait))
        llm.converse(sponsor, model, messages, box,
                     on_done=lambda said: _answered(said or None),
                     on_error=_failed, rounds=REMEMBER_ROUNDS)

    def _answered(answer):
        wait.done()
        caller.ndb.recalling = False
        if answer is None:
            caller.msg("You cannot bring anything to mind about that.")
        else:
            caller.msg(str(answer).strip())

    def _failed(why):
        wait.done()
        caller.ndb.recalling = False
        caller.msg(f"|rYou cannot gather your thoughts: {why}|n")

    def _fail(failure):
        _failed(failure.getErrorMessage())

    llm.fetch(_fetch, on_success=_done, on_error=_fail)


ASK = menus.Form(
    key="remember", title="Remember",
    guided=True,
    items=[menus.Field(
        "question", "What do you want to remember?", required=True,
        after=menus.CLOSE,
        prompt="Type a question, like have I met Cherrie before",
        help="Your character is asked in plain English, and answers from "
             "their own memory of where they have been, what they saw and "
             "what they did.",
        set=lambda ctx, value: recall(ctx.character or ctx.caller, value),
        get=lambda ctx: None)],
)
