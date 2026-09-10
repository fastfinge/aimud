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


#: How closely a typed word must resemble a real command before we assume it
#: was meant as one. High, because a genuine verb that merely rhymes with a
#: command must still reach the world -- being told "did you mean recall?" when
#: you tried to read something would be worse than the typo.
NEAR_MISS = 0.85

#: Short words are not checked at all. Among three and four letter words a
#: coincidence is likelier than a typo -- "tie" scores 0.86 against "time" --
#: and short verbs are exactly the ones players use most.
MIN_GUARDED_LENGTH = 5


def _closest_command(cmd, word):
    """
    A real command `word` almost is, if any.

    Without this a mistyped command name is treated as an action and sent to a
    model: typing "worldg" would cost a rule call and answer with narration
    about doing something nonsensical, rather than saying it is not a command.

    Anything the word matches exactly has already been run by the time we get
    here, so only genuine near-misses reach this.
    """
    from world.verbs import similarity

    cmdset = getattr(cmd, "cmdset", None)
    if cmdset is None or len(word) < MIN_GUARDED_LENGTH:
        return None

    best, best_score = None, 0.0
    for candidate in cmdset.commands:
        for name in [candidate.key, *candidate.aliases]:
            # Builder commands are staff-facing and mostly duplicates of a
            # plain-named one, so "@time" is never a useful suggestion.
            if not name or name.startswith("__") or name.startswith("@"):
                continue
            score = similarity(word, name)
            if score > best_score:
                best, best_score = name, score
    return best if best_score >= NEAR_MISS else None


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

        # A near-miss for a real command was meant as one. Say so, rather than
        # spending a model call narrating a mistyped command name.
        suggestion = _closest_command(self, cmd_verb)
        if suggestion:
            caller.msg(
                f"There is no |w{cmd_verb}|n command. Did you mean |w{suggestion}|n?"
            )
            return

        if caller.ndb.attempting:
            caller.msg("You're still trying to do that...")
            return

        account = _get_account(caller)
        # A key is wanted before anything is attempted, because almost every
        # attempt ends at a model and being told so after the wait is worse
        # than being told so now.
        #
        # Not every attempt does, though. Looking is answered by the rulebooks
        # out of what the world already holds -- `describe` returns the
        # appearance and nobody is asked anything -- so refusing `x lantern` for
        # want of an API key refuses the one action that never needs one. The
        # generators inside the pipeline each report a missing key for
        # themselves, so letting these through costs only a later, truer
        # message. See docs/rulebooks-from-inform.md 8.1.
        from world import verbs as _verbs

        if _verbs.canonical_verb(cmd_verb) not in _verbs.PIPELINE_VERBS:
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

        def waiting():
            # Only fires when the attempt actually has to go to a model, so a
            # cached verb stays instant and a slow one does not look ignored.
            caller.msg(f"You try to {raw}...")

        from world.attempt import attempt
        attempt(caller, raw, account, deliver, on_wait=waiting)
