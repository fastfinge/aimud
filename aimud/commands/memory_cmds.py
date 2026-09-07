"""
The remember command: ask your character what they recall.

A player should not have to keep notes on a legal pad beside the keyboard.
Their character was there, so the character is the one asked -- in plain
English, and answered from that character's own memory bank alone.
"""

from twisted.internet import threads

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
            from world.verb_gen import _call_openrouter
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
            return _call_openrouter(api_key, model, messages)

        def _done(answer):
            caller.ndb.recalling = False
            if answer is None:
                caller.msg("You cannot bring anything to mind about that.")
            else:
                caller.msg(str(answer).strip())

        def _fail(failure):
            caller.ndb.recalling = False
            caller.msg(f"|rYou cannot gather your thoughts: {failure.getErrorMessage()}|n")

        threads.deferToThread(_fetch).addCallbacks(_done, _fail)
