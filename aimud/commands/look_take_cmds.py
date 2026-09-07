"""
AI-enhanced look and take (get) commands.

In AI worlds:
  look <thing>  — if thing doesn't exist, the validator decides whether it
                  should, then the item model creates it.
  take/get <thing> — if thing doesn't exist, same as above (then take if
                  takeable).  If thing exists but takeability is unknown, the
                  validator decides and the result is cached on the object so
                  the LLM is never asked again.
"""

from evennia.commands.default.general import CmdLook as _DefaultLook
from evennia.commands.default.general import CmdGet as _DefaultGet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _account_from(caller):
    return getattr(caller, "account", None) or caller


def _in_ai_world(room):
    return bool(room and room.db.world_description)


def _reach(caller, query):
    """
    Something in reach that the room's own contents did not answer for.

    A key in an open drawer, a mug on the table: in plain sight, and a player
    should be able to take or examine it without emptying the drawer onto the
    floor first. Anything inside a closed container is not in reach, which is
    what closing it is for.
    """
    from world import relations

    return relations.find(caller, query)


def _find_one(caller, query, **search_kwargs):
    """
    Search with quiet=True and normalize the result.

    Evennia may return a list even for a single match depending on version.
    Returns (obj, is_multiple):
        obj          -- the single match, or None if not found
        is_multiple  -- True when there are 2+ matches (caller should re-run
                        without quiet so Evennia shows a disambiguation menu)
    """
    result = caller.search(query, quiet=True, **search_kwargs)

    # Already a single Evennia object (has return_appearance)
    if hasattr(result, "return_appearance"):
        return result, False

    # None or empty
    if not result:
        return None, False

    # Queryset / list
    try:
        items = [r for r in result if r is not None]
    except TypeError:
        # Not iterable at all — treat as single object
        return result, False

    if not items:
        return None, False
    if len(items) == 1:
        return items[0], False
    return None, True


def _acquire_gen_lock(room, key):
    """
    Claim a per-room generation slot for `key` (lowercased query string).
    Returns True if we got it, False if generation is already in progress.
    Prevents duplicate items when a player spams the same look/take.
    """
    pending = room.ndb.generating_items
    if pending is None:
        pending = set()
    if key in pending:
        return False
    pending.add(key)
    room.ndb.generating_items = pending
    return True


def _release_gen_lock(room, key):
    pending = room.ndb.generating_items or set()
    pending.discard(key)
    room.ndb.generating_items = pending


def _do_take(caller, obj):
    """Perform the physical take after all validation has passed."""
    if obj.location == caller:
        caller.msg("You already have that.")
        return
    if not obj.access(caller, "get"):
        caller.msg("You can't take that.")
        return
    room = caller.location
    success = obj.move_to(caller, quiet=True)
    if success:
        caller.msg(f"You pick up {obj.get_display_name(caller)}.")
        obj.at_get(caller)
        if room:
            from world.npc_gen import notify_npcs
            notify_npcs(room, "action", caller.get_display_name(caller),
                        f"picked up {obj.get_display_name(caller)}")
    else:
        caller.msg("You can't pick that up.")


# ---------------------------------------------------------------------------
# Look
# ---------------------------------------------------------------------------

class CmdAILook(_DefaultLook):
    """
    look at location or object

    Usage:
      look
      look <obj>

    In AI worlds, examining something that doesn't yet exist may cause it to
    materialise if the world and room context makes it plausible.
    """

    def func(self):
        caller = self.caller

        if not self.args:
            # No target — look at the room normally.
            super().func()
            return

        query = self.args.strip()
        obj, multiple = _find_one(caller, query)

        if multiple:
            caller.search(query)  # let Evennia show disambiguation
            return

        if not obj:
            # Before conjuring anything, look outward: on the table, in the
            # open drawer. Inventing a second mug because the first one was
            # put down somewhere would be the worst of both.
            obj = _reach(caller, query)
        if not obj:
            self._ai_look(caller, query)
            return

        # Single match — standard look.
        caller.msg(obj.return_appearance(caller))
        obj.at_desc(looker=caller)

    def _ai_look(self, caller, query):
        room = caller.location
        if not _in_ai_world(room):
            caller.search(query)   # prints the standard "not found" message
            return

        key = query.lower()
        if not _acquire_gen_lock(room, key):
            caller.msg("Something is already appearing there.")
            return

        account = _account_from(caller)
        caller.msg(f"You look carefully for {query}...")

        from world.item_gen import validate_object_existence, generate_item

        def on_valid(_reason):
            generate_item(
                account, room, query,
                on_success=lambda item: _finish_look(caller, item, room, key),
                on_error=lambda err: _gen_error(caller, room, key, err),
            )

        def on_invalid(_reason):
            _release_gen_lock(room, key)
            caller.msg(f"You don't see any {query} here.")

        def on_error(err):
            _release_gen_lock(room, key)
            caller.msg(f"|rError: {err}|n")

        validate_object_existence(account, room, query, on_valid, on_invalid, on_error)


def _finish_look(caller, item, room, key):
    _release_gen_lock(room, key)
    caller.msg(item.return_appearance(caller))
    item.at_desc(looker=caller)
    from world.npc_gen import notify_npcs
    notify_npcs(room, "action", caller.get_display_name(caller),
                f"examined {item.get_display_name(caller)}")


def _gen_error(caller, room, key, err):
    _release_gen_lock(room, key)
    caller.msg(f"|rCould not create item: {err}|n")


# ---------------------------------------------------------------------------
# Take / Get
# ---------------------------------------------------------------------------

class CmdAIGet(_DefaultGet):
    """
    pick up an object

    Usage:
      get <obj>
      take <obj>

    In AI worlds, trying to take something that doesn't exist may cause it to
    appear (if context allows) and then be picked up.  Whether an object can
    be taken is validated once by the AI and then cached on the object forever.
    """

    def func(self):
        caller = self.caller

        if not self.args:
            caller.msg("Get what?")
            return

        query = self.args.strip()
        room = caller.location
        obj, multiple = _find_one(caller, query, location=room)

        if multiple:
            caller.search(query, location=room)  # let Evennia show disambiguation
            return

        if not obj:
            obj = _reach(caller, query)
        if not obj:
            self._ai_take_nonexistent(caller, query, room)
            return

        self._take_existing(caller, obj, room)

    # -- object already in room --

    def _take_existing(self, caller, obj, room):
        if not _in_ai_world(room):
            # Outside AI worlds: use plain Evennia take behaviour.
            _do_take(caller, obj)
            return

        cached = obj.db.ai_takeable

        if cached is True:
            _do_take(caller, obj)
            return

        if cached is False:
            caller.msg("You can't take that.")
            return

        # Takeability not yet known — ask the validator and cache.
        account = _account_from(caller)

        from world.item_gen import validate_object_takeable

        def on_valid(_reason):
            obj.db.ai_takeable = True
            _do_take(caller, obj)

        def on_invalid(_reason):
            obj.db.ai_takeable = False
            caller.msg("You can't take that.")

        def on_error(err):
            caller.msg(f"|rValidation error: {err}|n")

        validate_object_takeable(account, room, obj, on_valid, on_invalid, on_error)

    # -- object doesn't exist yet --

    def _ai_take_nonexistent(self, caller, query, room):
        if not _in_ai_world(room):
            caller.search(query, location=room)   # standard "not found" message
            return

        key = query.lower()
        if not _acquire_gen_lock(room, key):
            caller.msg("Something is already appearing there.")
            return

        account = _account_from(caller)
        caller.msg(f"You look for {query}...")

        from world.item_gen import validate_object_existence, generate_item

        def on_valid(_reason):
            generate_item(
                account, room, query,
                on_success=lambda item: _finish_take(caller, item, room, key),
                on_error=lambda err: _gen_error(caller, room, key, err),
            )

        def on_invalid(_reason):
            _release_gen_lock(room, key)
            caller.msg(f"You don't see any {query} here.")

        def on_error(err):
            _release_gen_lock(room, key)
            caller.msg(f"|rError: {err}|n")

        validate_object_existence(account, room, query, on_valid, on_invalid, on_error)


def _finish_take(caller, item, room, key):
    _release_gen_lock(room, key)
    if item.db.ai_takeable:
        _do_take(caller, item)
    else:
        # Show the item but explain why it stays.
        caller.msg(
            f"{item.return_appearance(caller)}\n"
            f"|x(You can't take the {item.get_display_name(caller)}.)|n"
        )
