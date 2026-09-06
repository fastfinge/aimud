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


def _find_target(caller, room, args):
    """Return the best-matching object in the room or caller's inventory, or None."""
    if not args:
        return None
    from commands.look_take_cmds import _find_one
    obj, _ = _find_one(caller, args, location=room)
    if obj:
        return obj
    obj, _ = _find_one(caller, args, location=caller)
    return obj


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


def _room_key(cmd_verb, args):
    return f"{cmd_verb} {args.lower()}".strip() if args else cmd_verb


def _get_cached(caller, room, cmd_verb, args, target_obj):
    """Return a cache dict or None."""
    if target_obj:
        hit = (target_obj.db.ai_commands or {}).get(cmd_verb)
        if hit is not None:
            return hit
    hit = (room.db.ai_commands or {}).get(_room_key(cmd_verb, args))
    if hit is not None:
        return hit
    hit = (caller.db.ai_commands or {}).get(cmd_verb)
    if hit is not None:
        return hit
    return None


def _store_cached(caller, room, cmd_verb, args, entry, cache_on, target_obj):
    if cache_on == "object" and target_obj:
        cmds = target_obj.db.ai_commands or {}
        cmds[cmd_verb] = entry
        target_obj.db.ai_commands = cmds
    elif cache_on == "player":
        cmds = caller.db.ai_commands or {}
        cmds[cmd_verb] = entry
        caller.db.ai_commands = cmds
    else:
        cmds = room.db.ai_commands or {}
        cmds[_room_key(cmd_verb, args)] = entry
        room.db.ai_commands = cmds


def _acquire_lock(caller, lock_key):
    pending = caller.ndb.generating_cmds
    if pending is None:
        pending = set()
    if lock_key in pending:
        return False
    pending.add(lock_key)
    caller.ndb.generating_cmds = pending
    return True


def _release_lock(caller, lock_key):
    pending = caller.ndb.generating_cmds or set()
    pending.discard(lock_key)
    caller.ndb.generating_cmds = pending


class CmdAIUnknown(SystemNoMatch):
    """
    Intercepts unrecognized commands in AI worlds and routes them through
    the AI validation + command-generation pipeline.

    Responses (and effects) are cached persistently so that:
      - Non-repeatable commands (pull lever) show the same text again and
        do NOT re-apply their effects.
      - Repeatable commands (brew potion) show the same text and DO re-apply
        their effects, creating a new object / changing the world each time.

    Outside AI worlds the default "Huh?" message is shown.
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
        parts = raw.split(None, 1)
        cmd_verb = parts[0].lower() if parts else ""
        args = parts[1].strip() if len(parts) > 1 else ""

        if not cmd_verb:
            super().func()
            return

        if _try_direction(caller, cmd_verb, args):
            return

        target_obj = _find_target(caller, room, args)

        # --- Cache hit ---
        cached = _get_cached(caller, room, cmd_verb, args, target_obj)
        if cached is not None:
            if isinstance(cached, dict):
                caller.msg(cached.get("response", ""))
                if cached.get("repeatable") and cached.get("effects"):
                    from world.cmd_gen import apply_effects
                    apply_effects(caller, room, cached["effects"])
            else:
                # Compatibility with any plain-string entries written before this version.
                caller.msg(cached)
            return

        # --- Spam guard ---
        lock_key = f"{cmd_verb}:{args.lower()}"
        if not _acquire_lock(caller, lock_key):
            caller.msg("You're still trying to do that...")
            return

        account = _get_account(caller)
        try:
            account.get_openrouter_key()
        except ValueError as e:
            _release_lock(caller, lock_key)
            caller.msg(str(e))
            return

        action = f"{cmd_verb} {args}".strip()
        caller.msg(f"You attempt to {action}...")

        from world.cmd_gen import validate_command, generate_command_response, apply_effects
        from world.npc_gen import notify_npcs

        def on_valid():
            def on_success(response, cache_on, obj, effects, repeatable):
                _release_lock(caller, lock_key)
                caller.msg(response)
                if effects:
                    apply_effects(caller, room, effects)
                notify_npcs(room, "action", caller.get_display_name(caller),
                            action, exclude=None)
                entry = {"response": response, "effects": effects, "repeatable": repeatable}
                _store_cached(caller, room, cmd_verb, args, entry, cache_on, obj)

            def on_gen_error(err):
                _release_lock(caller, lock_key)
                caller.msg(f"|rCould not generate response: {err}|n")

            generate_command_response(
                account, caller, room, action, target_obj,
                on_success=on_success,
                on_error=on_gen_error,
            )

        def on_invalid(_reason):
            _release_lock(caller, lock_key)
            caller.msg("You can't do that here.")

        def on_error(err):
            _release_lock(caller, lock_key)
            caller.msg(f"|rError: {err}|n")

        validate_command(account, room, action, target_obj, on_valid, on_invalid, on_error)
