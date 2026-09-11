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


def _world_root(room):
    """
    The world this room belongs to, or None outside a generated one.

    The test for whether there are rulebooks to consult at all. Limbo, the
    character creation rooms and anything built by hand have no root, and must
    go on behaving exactly as they did -- a look that refused to work outside a
    generated world would be a far worse bug than anything rules could fix.
    """
    return getattr(room.db, "world_root", None) if room is not None else None


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


def _or_typo(caller, query):
    """
    (obj, complaint) for a name nothing here answered to.

    The last thing tried before conjuring, and the reason it exists: a typo
    and an invention look exactly alike to this game, so "blackbaord" would
    otherwise buy a second blackboard, slightly different from the first,
    standing beside it for good. A confident match is used; a near miss is
    put back to the player; only a genuinely new name gets made.
    """
    from world import naming

    obj, suggestion = naming.instead_of_creating(caller, query)
    return obj, suggestion


def _counted(caller, query):
    """
    The one of several things a query counted out, or None.

    "The second wrench" is a count and not a name, and Evennia's own search
    reads it as a name -- so it found nothing, and this game's answer to
    finding nothing is to offer to invent it. A player who has just been shown
    three wrenches and asks for the second should get the second.
    """
    from world import verbs

    return verbs.counted(caller, query)


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

    Looking is an action with rulebooks, so in a generated world this command
    finds what was meant and then hands the attempt to the pipeline rather than
    describing anything itself. That is what lets a world say its cave is dark,
    that the ghost needs the right spectacles, or that the moon may be looked at
    and not touched -- none of which could be said while the describing happened
    here. See docs/rulebooks-from-inform.md 8.1.

    Outside a generated world there is no rulebook to consult and nothing to
    consult it with, so the original behaviour stands unchanged. Limbo still
    looks like Limbo.
    """

    def func(self):
        caller = self.caller
        room = caller.location
        root = _world_root(room)

        if not self.args:
            if root is None:
                super().func()          # no world, no rules: look as ever
                return
            # Bare `look` goes through as an attempt with nothing bound. A
            # standard `instead` rule guarded by `unbound` redirects it to
            # looking at the room, which is how the room's own rules -- its
            # darkness, its kind -- come to apply without this command knowing
            # anything about them.
            self._attempt(caller, "look")
            return

        query = self.args.strip()
        obj = _counted(caller, query)
        multiple = False
        if obj is None:
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
            obj, complaint = _or_typo(caller, query)
            if complaint:
                caller.msg(complaint)
                return
        if not obj:
            self._ai_look(caller, query)
            return

        if root is None:
            caller.msg(obj.return_appearance(caller))
            obj.at_desc(looker=caller)
            return
        self._attempt(caller, f"look {query}")

    def _attempt(self, caller, raw):
        """Hand the look to the rulebooks, and say whatever they answer."""
        from world import attempt as attempt_mod

        attempt_mod.attempt(caller, raw, _account_from(caller),
                            on_message=lambda actor_text, room_text=None:
                                caller.msg(actor_text) if actor_text else None)

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
    # Through the pipeline, like any other look: a thing that has just been
    # conjured is as subject to the room's darkness as one that was always here.
    if _world_root(room) is None:
        caller.msg(item.return_appearance(caller))
        item.at_desc(looker=caller)
    else:
        from world import attempt as attempt_mod

        attempt_mod.attempt(
            caller, f"look {item.key}", _account_from(caller),
            on_message=lambda actor_text, room_text=None:
                caller.msg(actor_text) if actor_text else None)
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

    |wget <obj> with <tool>|n and |wget <obj> from <place>|n are not this
    command's business and are handed to the rulebooks, which is the whole
    difference between a world where tongs are for something and one where
    "get the stone with the tongs" conjures an object called "stone with
    tongs" -- which is what this did, because it read everything after the
    verb as one name.
    """

    def func(self):
        caller = self.caller

        if not self.args:
            caller.msg("Get what?")
            return

        query = self.args.strip()
        room = caller.location

        # Anything but a plain noun is a sentence rather than a name. The
        # pipeline knows what to do with a preposition and this command does
        # not, so it goes there whole -- picking something up with a tool is a
        # thing a world may have an opinion about, and taking it out of
        # something is a placement the game already understands.
        from world import verbs

        parsed = verbs.parse(f"get {query}")
        if set(parsed["roles"]) - {"direct"}:
            self._through_the_rulebooks(caller, f"get {query}")
            return

        # "Get all" is every takeable thing here, one at a time. Through the
        # same expander every other verb uses, so what "all" leaves out is
        # decided in one place -- exits, people, and anything whose kind has
        # already said it cannot be picked up.
        from world import bulk

        several, sort = bulk.split(query)
        if several:
            found = bulk.matching(caller, "get", query)
            takeable = [obj for obj in found if _takeable(obj, room) is not False]
            if not takeable:
                caller.msg(f"There is no {sort} here to pick up." if sort
                           else "There is nothing here to pick up.")
                return
            for obj in takeable:
                self._take_existing(caller, obj, room)
            return

        obj = _counted(caller, query)
        multiple = False
        if obj is None:
            obj, multiple = _find_one(caller, query, location=room)

        if multiple:
            caller.search(query, location=room)  # let Evennia show disambiguation
            return

        if not obj:
            obj = _reach(caller, query)
        if not obj:
            obj, complaint = _or_typo(caller, query)
            if complaint:
                caller.msg(complaint)
                return
        if not obj:
            self._ai_take_nonexistent(caller, query, room)
            return

        self._take_existing(caller, obj, room)

    def _through_the_rulebooks(self, caller, raw):
        """Hand a get the command set cannot express to the attempt pipeline."""
        from world import attempt as attempt_mod

        attempt_mod.attempt(
            caller, raw, _account_from(caller),
            on_message=lambda actor_text, room_text=None:
                caller.msg(actor_text) if actor_text else None)

    # -- object already in room --

    def _take_existing(self, caller, obj, room):
        if not _in_ai_world(room):
            # Outside AI worlds: use plain Evennia take behaviour.
            _do_take(caller, obj)
            return

        settled = _takeable(obj, room)
        if settled is True:
            _do_take(caller, obj)
            return
        if settled is False:
            caller.msg("You can't take that.")
            return

        # Nobody has decided whether this sort of thing can be picked up. Ask
        # once, about the kind rather than about this one -- the answer holds
        # for every table in the world, and for the next one made.
        account = _account_from(caller)

        from world import kinds
        from world.item_gen import validate_object_takeable

        def remember(allowed):
            kinds.admit(_root(room), obj.db.kinds, "get", allowed)
            obj.db.ai_takeable = allowed      # the fallback answer, for a
                                              # thing that has no kind at all

        def on_valid(_reason):
            remember(True)
            _do_take(caller, obj)

        def on_invalid(_reason):
            remember(False)
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


def _root(room):
    """The world an object belongs to, found from the room holding it."""
    where = room
    while where is not None:
        found = getattr(getattr(where, "db", None), "world_root", None)
        if found is not None:
            return found
        where = getattr(where, "location", None)
    return None


def _takeable(obj, room):
    """
    Whether this can be picked up: True, False, or None for undecided.

    Asked of the kind first, because being liftable is a fact about tables
    rather than about this table. It used to be a flag on each object, set by
    a model call of its own -- so a world with forty chairs in it asked forty
    times whether a chair can be carried off, and could get forty answers.

    Now `get` is a verb like any other and a kind can refuse it, which is what
    "an object that cannot be taken" always wanted to be. The old flag is
    still read underneath, for things made before kinds existed and for the
    occasional thing that has no kind at all.
    """
    from world import kinds

    settled = kinds.admits(_root(room), obj.db.kinds, "get")
    if settled is not None:
        return settled
    return obj.db.ai_takeable


def _finish_take(caller, item, room, key):
    _release_gen_lock(room, key)
    if _takeable(item, room):
        _do_take(caller, item)
    else:
        # Show the item but explain why it stays.
        caller.msg(
            f"{item.return_appearance(caller)}\n"
            f"|x(You can't take the {item.get_display_name(caller)}.)|n"
        )
