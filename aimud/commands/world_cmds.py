"""
World management commands: worlds, worldremove.
"""

from commands.command import Command


def _get_account(caller):
    return getattr(caller, "account", None) or caller


def _resolve_worlds(account):
    """
    Return a list of (world_root_room, room_count) for all worlds the account
    created.  Prunes stale IDs from account.db.created_worlds as a side-effect.
    """
    from evennia import search_tag
    from evennia.objects.models import ObjectDB

    world_ids = account.db.created_worlds or []
    results = []
    valid_ids = []

    for wid in world_ids:
        try:
            root = ObjectDB.objects.get(id=wid)
        except ObjectDB.DoesNotExist:
            continue
        room_count = len(search_tag(str(wid), category="ai_world"))
        results.append((root, room_count))
        valid_ids.append(wid)

    if valid_ids != world_ids:
        account.db.created_worlds = valid_ids

    return results


def _current_world_root(caller):
    """Return the world_root of the room the caller is in, or None."""
    loc = getattr(caller, "location", None)
    return loc.db.world_root if loc else None


class CmdWorlds(Command):
    """
    List your worlds or enter one.

    Usage:
      worlds
      worlds <number>

    Without an argument, lists all worlds you have created with worldgen,
    showing how many rooms have been explored in each.

    With a number, moves you to your last location in that world (or its
    starting room if you have never visited it before).
    """

    key = "worlds"
    locks = "cmd:all()"
    help_category = "World"

    def parse(self):
        arg = self.args.strip()
        self.world_num = int(arg) if arg.isdigit() else None

    def func(self):
        account = _get_account(self.caller)
        worlds = _resolve_worlds(account)

        if not worlds:
            self.caller.msg(
                "You haven't created any worlds yet. "
                "Use |wworldgen <description>|n to generate one."
            )
            return

        if self.world_num is None:
            self._show_list(worlds)
        else:
            self._enter_world(worlds, account)

    def _show_list(self, worlds):
        current_root = _current_world_root(self.caller)
        lines = ["|wYour worlds:|n\n"]
        for i, (root, room_count) in enumerate(worlds, 1):
            desc = root.db.world_description or "(no description)"
            here = " |g[here]|n" if (current_root and current_root.id == root.id) else ""
            lines.append(f"  |w{i}.|n {desc}  |x({room_count} rooms explored){here}|n")
        lines.append("\nType |wworlds <number>|n to enter a world.")
        self.caller.msg("\n".join(lines))

    def _enter_world(self, worlds, account):
        idx = self.world_num - 1
        if not (0 <= idx < len(worlds)):
            self.caller.msg(f"Invalid world number. Choose 1–{len(worlds)}.")
            return

        root, _ = worlds[idx]

        current_root = _current_world_root(self.caller)
        if current_root and current_root.id == root.id:
            self.caller.msg("You are already in that world.")
            return

        # Find last visited location in this world, fall back to root.
        locs = account.db.world_last_locations or {}
        last = locs.get(str(root.id))

        if last:
            # last is stored as an object reference by Evennia; just validate it still exists.
            from evennia.objects.models import ObjectDB
            try:
                dest = ObjectDB.objects.get(id=last.id) if hasattr(last, "id") else None
            except ObjectDB.DoesNotExist:
                dest = None
        else:
            dest = None

        destination = dest or root
        desc = root.db.world_description or root.key
        self.caller.msg(f"Entering world: |w{desc}|n")
        self.caller.move_to(destination, quiet=False)


class CmdNPCGen(Command):
    """
    Generate an NPC in the current room.

    Usage:
      npcgen

    Generates an NPC appropriate to the current room and world. Only works
    in AI-generated rooms. If the room already contains an NPC, the command
    will tell you so rather than adding a second one.
    """

    key = "npcgen"
    locks = "cmd:all()"
    help_category = "World"

    def func(self):
        caller = self.caller
        room = caller.location
        if not room or not room.db.is_ai_room:
            caller.msg("You can only generate NPCs in AI-created rooms.")
            return

        for obj in room.contents:
            if obj.db.is_npc:
                caller.msg(f"There is already an NPC here ({obj.key}).")
                return

        if room.ndb.generating_npc:
            caller.msg("An NPC is already being generated for this room.")
            return

        account = _get_account(caller)
        try:
            account.get_openrouter_key()
        except ValueError as e:
            caller.msg(str(e))
            return

        room.ndb.generating_npc = True
        caller.msg("Generating NPC for this room...")

        def on_success(npc):
            room.ndb.generating_npc = False
            room.msg_contents(
                f"|g{npc.key} has arrived.|n", exclude=None
            )

        def on_error(err):
            room.ndb.generating_npc = False
            caller.msg(f"|rNPC generation failed: {err}|n")

        from world.npc_gen import generate_npc
        generate_npc(account=account, room=room,
                     on_success=on_success, on_error=on_error)


class CmdWorldRemove(Command):
    """
    Permanently delete one of your worlds.

    Usage:
      worldremove
      worldremove <number>
      worldremove <number> confirm

    Without arguments, lists your worlds with numbers.
    With a number, shows what will be deleted.
    Adding |wconfirm|n permanently deletes the world and every room in it.

    You cannot delete a world you are currently inside, and you cannot
    delete worlds created by other players.
    """

    key = "worldremove"
    locks = "cmd:all()"
    help_category = "World"

    def parse(self):
        parts = self.args.strip().split()
        self.world_num = int(parts[0]) if parts and parts[0].isdigit() else None
        self.confirmed = len(parts) > 1 and parts[1].lower() == "confirm"

    def func(self):
        account = _get_account(self.caller)
        worlds = _resolve_worlds(account)

        if not worlds:
            self.caller.msg("You have no worlds to remove.")
            return

        if self.world_num is None:
            self._show_list(worlds)
            return

        idx = self.world_num - 1
        if not (0 <= idx < len(worlds)):
            self.caller.msg(f"Invalid world number. Choose 1–{len(worlds)}.")
            return

        root, room_count = worlds[idx]

        # Guard: can't delete the world you're currently in.
        current_root = _current_world_root(self.caller)
        if current_root and current_root.id == root.id:
            self.caller.msg(
                "You cannot delete the world you are currently inside. "
                "Leave the world first."
            )
            return

        desc = root.db.world_description or root.key

        if not self.confirmed:
            self.caller.msg(
                f"|rWarning:|n This will permanently delete |w{desc}|n "
                f"and all |w{room_count}|n rooms in it.\n"
                f"Type |wworldremove {self.world_num} confirm|n to proceed."
            )
            return

        # Delete the world.
        self._delete_world(root, room_count, account, desc)

    def _show_list(self, worlds):
        current_root = _current_world_root(self.caller)
        lines = ["|wYour worlds (worldremove <number> to delete):|n\n"]
        for i, (root, room_count) in enumerate(worlds, 1):
            desc = root.db.world_description or "(no description)"
            here = " |y[current — cannot delete]|n" if (
                current_root and current_root.id == root.id
            ) else ""
            lines.append(f"  |w{i}.|n {desc}  |x({room_count} rooms){here}|n")
        self.caller.msg("\n".join(lines))

    def _delete_world(self, root, room_count, account, desc):
        from evennia import search_tag

        rooms = list(search_tag(str(root.id), category="ai_world"))

        # Notify and relocate any characters caught inside.
        for room in rooms:
            for obj in list(room.contents):
                if hasattr(obj, "sessions") and obj.sessions.count():
                    home = getattr(obj, "home", None)
                    obj.msg(
                        f"|rThe world '{desc}' is being deleted. "
                        "You have been moved to your home location.|n"
                    )
                    obj.move_to(home, quiet=True)

        # Delete every room (exits located inside are deleted with their room).
        for room in rooms:
            room.delete()

        # Remove from account tracking.
        created = account.db.created_worlds or []
        if root.id in created:
            created.remove(root.id)
            account.db.created_worlds = created

        locs = account.db.world_last_locations or {}
        locs.pop(str(root.id), None)
        account.db.world_last_locations = locs

        self.caller.msg(
            f"|gDeleted world '|w{desc}|g' — {room_count} room(s) removed.|n"
        )
