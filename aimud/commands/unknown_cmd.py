"""
AI-powered fallback for unrecognized commands in AI worlds.

Flow:
  0. Bare directional input ("north", "n", "ne", "up", ...) that matched no exit
     is refused outright.  The validator is not consulted: a direction the room
     has no exit for is impossible by definition, not a matter of judgement.
  1. Player types an unrecognized command.
  2. Cache check (object → room → player). Cache entries are dicts:
       {"response": str, "effects": list, "repeatable": bool}
     - Non-repeatable hit: show response only (effects already applied once).
     - Repeatable hit: show response AND re-apply effects (e.g. brew another potion).
  3. On miss: validate with the validator model, then generate with the commands
     model. Show the response, apply effects, cache the entry.

Cache storage keys:
  object  — obj.db.ai_commands[cmd_verb]
  room    — room.db.ai_commands["verb args"]
  player  — character.db.ai_commands[cmd_verb]
"""

from evennia.commands.cmdhandler import CMD_NOMATCH
from evennia.commands.default.syscommands import SystemNoMatch


def _get_account(caller):
    return getattr(caller, "account", None) or caller


def _in_ai_world(room):
    return bool(room and room.db.world_description)


def _try_direction(caller, cmd_verb, args):
    """
    Refuse bare directional input, and report whether it was consumed.

    Every exit answers to its direction and to the abbreviation (see
    `worldgen.direction_aliases`), so an exit the room actually has is matched
    by its own exit command and never arrives here — a locked one included.
    Getting this far means there is no exit that way, which is a fact about the
    map rather than something to ask the AI about.
    """
    if args:
        return False

    from world.worldgen import canonical_direction

    if not canonical_direction(cmd_verb):
        return False

    caller.msg("You cannot go there.")
    return True


class CmdAIUnknown(SystemNoMatch):
    """
    Intercepts unrecognized commands in AI worlds and treats them as verbs.

    Input is parsed into a verb and the roles its nouns play, the nouns are
    bound to real objects, and only a combination the world has not met before
    costs a model call.  Outside AI worlds the default "Huh?" is shown.
    """

    key = CMD_NOMATCH
    locks = "cmd:all()"

    def func(self):
        caller = self.caller
        room = caller.location

        if not _in_ai_world(room):
            super().func()
            return

        raw = self.raw_string.strip()
        if not raw:
            super().func()
            return

        parts = raw.split(None, 1)
        cmd_verb = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if _try_direction(caller, cmd_verb, args):
            return

        if caller.ndb.attempting:
            caller.msg("You're still trying to do that...")
            return

        account = _get_account(caller)
        try:
            account.get_openrouter_key()
        except ValueError as e:
            caller.msg(str(e))
            return

        caller.ndb.attempting = raw

        def deliver(actor_text, room_text=""):
            caller.ndb.attempting = None
            if actor_text:
                caller.msg(actor_text)
            if room_text:
                # Everyone present sees what happened, which matters now that
                # verbs actually change the world rather than only narrating.
                room.msg_contents(room_text, exclude=[caller])
                from world.npc_gen import notify_npcs
                notify_npcs(room, "action", caller.get_display_name(caller),
                            room_text, exclude=caller, actor=caller)

        from world.attempt import attempt
        attempt(caller, raw, account, deliver)
