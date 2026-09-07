"""
World management commands: worlds, worldedit, worldremove, worldreset.
"""

from commands.command import Command
from world import lore


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


def _choose_world(caller, worlds, world_num, action, usage):
    """
    Which world a command with an optional number is aimed at, or None.

    With a number it is that one; without, it is the world the caller is
    standing in. Anything that stops it resolving is reported here, so the
    caller is told what to type next rather than merely refused.
    """
    if not worlds:
        caller.msg(
            "You haven't created any worlds yet. "
            "Use |wworldgen <description>|n to generate one."
        )
        return None

    if world_num is not None:
        idx = world_num - 1
        if not (0 <= idx < len(worlds)):
            caller.msg(f"Invalid world number. Choose 1–{len(worlds)}.")
            return None
        return worlds[idx][0]

    current = _current_world_root(caller)
    if current is None:
        lines = [f"You are not in a world. Choose one to {action}:\n"]
        for i, (root, count) in enumerate(worlds, 1):
            lines.append(f"  |w{i}.|n {lore.title(root)}  |x({count} rooms)|n")
        lines.append(f"\nType |w{usage}|n.")
        caller.msg("\n".join(lines))
        return None

    if not any(root.id == current.id for root, _ in worlds):
        caller.msg(f"You can only {action} worlds you created.")
        return None
    return current


def _quest_holders(rooms, account):
    """
    Everyone who might be carrying a quest from this world.

    The characters standing in it, plus the account's own playable characters
    -- a player can perfectly well be somewhere else entirely when they delete
    a world they took an errand from.
    """
    from evennia.objects.objects import DefaultCharacter

    found = {}
    for room in rooms:
        for obj in room.contents:
            if isinstance(obj, DefaultCharacter):
                found[obj.id] = obj
    for character in (getattr(account, "characters", None) or []):
        if character:
            found[character.id] = character
    return list(found.values())


def _clear_world(root, account, destination=None, message=None):
    """
    Delete every room of a world, and everything in them, and forget the world
    on the account.

    Characters are moved out first -- to `destination`, or to their own home --
    whether or not they are logged in.  Everything else the world contains is
    destroyed: deleting a room only sends its contents home, so items and NPCs
    would otherwise survive as orphans scattered through Limbo.

    Returns the number of rooms deleted.
    """
    from evennia import search_tag
    from evennia.objects.objects import DefaultCharacter

    from world import quests

    root_id = root.id
    rooms = list(search_tag(str(root_id), category="ai_world"))

    # Quests are held by the player, not by the world, so deleting the world
    # leaves them behind: an errand from somebody who no longer exists, about
    # things that no longer exist, which can never be finished and is re-tested
    # on every deadline tick.  Collected before anything is destroyed, because
    # older quests are identified by who gave them.
    givers = {obj.id for room in rooms for obj in room.contents if obj.db.is_npc}
    for character in _quest_holders(rooms, account):
        quests.forget_world(character, root_id, givers)

    for room in rooms:
        for obj in list(room.contents):
            if isinstance(obj, DefaultCharacter):
                if message and obj.sessions.count():
                    obj.msg(message)
                obj.move_to(destination or getattr(obj, "home", None), quiet=True)
            else:
                # Items, NPCs and exits belong to the world, not to Limbo.
                obj.delete()

    for room in rooms:
        room.delete()

    created = account.db.created_worlds or []
    if root_id in created:
        created.remove(root_id)
        account.db.created_worlds = created

    locs = account.db.world_last_locations or {}
    locs.pop(str(root_id), None)
    account.db.world_last_locations = locs

    return len(rooms)


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
    aliases = ["world"]
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
            desc = lore.title(root)
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
        desc = lore.title(root)
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

        desc = lore.title(root)

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
            desc = lore.title(root)
            here = " |y[current — cannot delete]|n" if (
                current_root and current_root.id == root.id
            ) else ""
            lines.append(f"  |w{i}.|n {desc}  |x({room_count} rooms){here}|n")
        self.caller.msg("\n".join(lines))

    def _delete_world(self, root, room_count, account, desc):
        _clear_world(
            root, account,
            message=(f"|rThe world '{desc}' is being deleted. "
                     "You have been moved to your home location.|n"),
        )
        self.caller.msg(
            f"|gDeleted world '|w{desc}|g' — {room_count} room(s) removed.|n"
        )


class CmdWorldReset(Command):
    """
    Wipe a world and build it again from the same description.

    Usage:
      worldreset
      worldreset confirm
      worldreset <number>
      worldreset <number> confirm

    With no number, resets the world you are standing in. With a number,
    resets that world from your |wworlds|n list.

    Every room, item and NPC in the world is destroyed and a fresh world is
    generated from the same description, so you can try a change to the
    generator without writing a new description each time.

    The replacement is generated first and the old world is only removed once
    it succeeds, so a failed generation leaves your existing world alone.
    """

    key = "worldreset"
    locks = "cmd:all()"
    help_category = "World"

    def parse(self):
        parts = self.args.strip().split()
        self.world_num = int(parts[0]) if parts and parts[0].isdigit() else None
        self.confirmed = bool(parts) and parts[-1].lower() == "confirm"

    def func(self):
        caller = self.caller
        account = _get_account(caller)
        worlds = _resolve_worlds(account)

        root = self._target(worlds)
        if root is None:
            return

        # Rebuild from everything the world was set up with, not just its
        # theme: a reset that forgot the title, the guidance, or the player's
        # name here would quietly undo half the wizard.
        spec = lore.spec_of(root, caller)
        description = spec["description"]
        if not description:
            caller.msg(
                "That world has no stored description, so it cannot be rebuilt. "
                "Use |wworldremove|n to delete it instead."
            )
            return

        room_count = next(count for r, count in worlds if r.id == root.id)

        if not self.confirmed:
            suffix = f" {self.world_num}" if self.world_num else ""
            caller.msg(
                f"|rWarning:|n this destroys all |w{room_count}|n room(s) of "
                f"|w{lore.title(root)}|n, with everything in them, and generates the "
                f"world again from that description.\n"
                f"Type |wworldreset{suffix} confirm|n to proceed."
            )
            return

        # Fail before destroying anything, not after.
        try:
            account.get_openrouter_key()
        except ValueError as e:
            caller.msg(str(e))
            return

        caller.msg(f"Rebuilding |w{lore.title(root)}|n — generating the new world first...")

        def on_success(new_root):
            # Only now is the old world expendable.
            removed = _clear_world(
                root, account, destination=new_root,
                message="|yThe world is being rebuilt around you.|n",
            )
            caller.msg(
                f"|gRebuilt '|w{spec['title'] or description}|g' — "
                f"{removed} old room(s) removed.|n"
            )
            if caller.location is not new_root:
                caller.move_to(new_root, quiet=False)
            else:
                caller.execute_cmd("look")

        def on_error(err):
            caller.msg(
                f"|rWorld generation failed: {err}|n\n"
                f"Your existing world was left untouched."
            )

        from world.worldgen import generate_first_room
        generate_first_room(account, spec, on_success, on_error,
                            creator_character=caller)

    def _target(self, worlds):
        """Resolve which world to reset, reporting any problem to the caller."""
        return _choose_world(self.caller, worlds, self.world_num,
                             "reset", "worldreset <number> confirm")


class CmdWorldEdit(Command):
    """
    Change what a world tells its generators, without rebuilding it.

    Usage:
      worldedit
      worldedit <number>

    Opens the same wizard |wworldgen|n uses, filled in with what this world
    was set up with: its title, its description, your name and looks here, and
    the guidance given to each generator separately -- rooms, characters,
    items, dialogue and the world's rules.

    With no number it edits the world you are standing in; with one, that
    world from your |wworlds|n list.

    Nothing already built changes. The rooms, items and characters that exist
    keep the text they were written with, and the new wording governs whatever
    is generated afterwards -- so you can try a change out by walking into
    somewhere new rather than throwing the world away. Use |wworldreset|n when
    you do want it all built again from the top.
    """

    key = "worldedit"
    locks = "cmd:all()"
    help_category = "World"

    def parse(self):
        arg = self.args.strip()
        self.world_num = int(arg) if arg.isdigit() else None

    def func(self):
        caller = self.caller
        account = _get_account(caller)
        worlds = _resolve_worlds(account)

        root = _choose_world(caller, worlds, self.world_num,
                             "edit", "worldedit <number>")
        if root is None:
            return

        from commands.worldgen_cmd import open_wizard

        spec = lore.spec_of(root, caller)
        spec.update(mode="edit", world_id=root.id)
        open_wizard(caller, spec)
