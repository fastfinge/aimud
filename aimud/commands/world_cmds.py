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


class CmdZones(Command):
    """
    Show the areas of the world you are in, and how full each one is.

    Usage:
      zones

    Every room belongs to an area, and every area has a size it was planned
    to be. An area that has reached that size takes no more rooms, and the
    next room built at its edge starts somewhere new instead. Areas contain
    other areas -- a town holds a school, which holds a gym block -- and each
    one says what may exist only once inside it.
    """

    key = "zones"
    locks = "cmd:all()"
    help_category = "World"

    def func(self):
        from world import zones

        root = _current_world_root(self.caller)
        if root is None:
            self.caller.msg("You are not in a generated world.")
            return

        if not zones.all_zones(root):
            self.caller.msg("This world has no areas recorded yet.")
            return

        location = getattr(self.caller, "location", None)
        self.here = zones.slugify(location.db.zone) if location else ""
        self.root = root
        lines = [f"|wAreas of {lore.title(root)}:|n\n"]
        self._branch(zones.ROOT, 0, lines)
        self.caller.msg("\n".join(lines))

    def _branch(self, zone_id, level, lines):
        """One area and everything inside it, deepest last."""
        from world import zones

        if zone_id != zones.ROOT:
            lines.append(self._line(zone_id, level))
        for child in sorted(zones.children_of(self.root, zone_id),
                            key=lambda z: zones.name_of(self.root, z)):
            self._branch(child, level + (0 if zone_id == zones.ROOT else 1), lines)

    def _line(self, zone_id, level):
        from world import zones

        record = zones.get(self.root, zone_id)
        filled, size = len(record["rooms"]), record["budget"]
        if not zones.placed(self.root, zone_id):
            state = "|xnot built yet|n"
        elif zones.finished(self.root, zone_id):
            state = "|yfinished|n"
        elif zones.full(self.root, zone_id):
            state = "|yfull; its parts are still growing|n"
        else:
            state = f"|g{size - filled} to go|n"

        indent = "  " + "    " * level
        mark = " |g[you are here]|n" if zone_id == self.here else ""
        out = [f"{indent}|w{record['name']}|n — {filled}/{size} rooms, {state}{mark}"]
        if record["purpose"]:
            out.append(f"{indent}    |x{record['purpose']}|n")
        if record.get("singleton_types"):
            only = ", ".join(record["singleton_types"])
            out.append(f"{indent}    |xonly one of: {only}|n")
        return "\n".join(out)


class CmdWorldMode(Command):
    """
    Whether this world thinks only when watched, or all the time.

    Usage:
      worldmode
      worldmode normal
      worldmode always

    |wnormal|n is how a world runs by default, and it is careful with your
    money. Characters act while somebody is in the room with them, keep going
    for a few minutes after that somebody leaves, and go still altogether once
    five minutes pass with nobody typing. A world nobody is watching thinks
    nothing and costs nothing.

    |walways|n takes both of those off. Every character in this world acts on
    every turn, wherever you are standing and however long since you last
    typed -- so the far side of the map goes on living while you are on this
    side of it, and a room you have never visited is busy before you arrive.

    That is what it is for, and it is not free: every character acting is a
    model call, and in |walways|n they all act, all the time, whether or not
    anything you see is affected by it. Turn it on to watch a world run;
    leave it on and it will run up a bill while you make a sandwich.

    It puts itself away. The moment the last player logs out, every world
    goes back to |wnormal|n -- checked at server start as well, so a crash or
    a dropped connection cannot leave a world talking to itself all night.
    Nothing switches it back on by itself; that is always your decision.
    """

    key = "worldmode"
    locks = "cmd:all()"
    help_category = "World"

    def func(self):
        from world import activity

        root = _current_world_root(self.caller)
        if root is None:
            self.caller.msg("You are not in a generated world.")
            return

        name = lore.title(root)
        wanted = self.args.strip().lower()

        if not wanted:
            self.caller.msg(self._standing(activity, root, name))
            return

        if wanted not in activity.MODES:
            self.caller.msg(
                f"There is no |w{wanted}|n mode. Choose |wnormal|n or "
                f"|walways|n, or type |wworldmode|n on its own to see which "
                f"one |w{name}|n is in."
            )
            return

        was = activity.mode(root)
        if wanted == was:
            self.caller.msg(self._standing(activity, root, name))
            return

        activity.set_mode(root, wanted)
        if wanted == activity.ALWAYS:
            self.caller.msg(
                f"|w{name}|n is now running |walways|n. Everybody in it acts "
                f"from now on, wherever you are and whether or not you are "
                f"typing. It costs a model call every time any of them does, "
                f"so put it back to |wnormal|n when you have seen enough -- "
                f"and it does that itself when you log out."
            )
        else:
            self.caller.msg(
                f"|w{name}|n is back to |wnormal|n. Characters you have just "
                f"been with stay live for a few more minutes, and then the "
                f"world goes quiet until you are watching it again."
            )

    def _standing(self, activity, root, name):
        """How the world is running now, said plainly."""
        if activity.mode(root) == activity.ALWAYS:
            return (f"|w{name}|n is running |walways|n: everybody in it acts "
                    f"on every turn, watched or not. Type |wworldmode "
                    f"normal|n to stop that.")
        return (f"|w{name}|n is running |wnormal|n: characters act while you "
                f"are with them and for a few minutes after, and the world "
                f"goes still when nobody is typing. Type |wworldmode always|n "
                f"to have all of it act all the time.")

class CmdWorldCheck(Command):
    """
    What this world's own rules say about each other.

    Usage:
      worldcheck
      worldcheck <number>

    Reads the rules a world has learned and reports what they cannot do
    between them. It costs nothing -- no model is asked anything, and the
    answer comes out of what the world already wrote down.

    Two faults matter most, and they are usually the same one seen twice. A
    condition that some rule can set and no rule can unset is a lamp that
    lights and never goes out. A condition that some rule requires and nothing
    can bring about is a rule that will never fire, however long anybody
    plays. When both turn up in one group of conditions -- open and closed,
    lit and unlit -- the gap between them is a single rule nobody ever wrote,
    and this says which.

    It also counts what was refused and why, which rules change nothing at
    all, and which words are in the vocabulary that no rule uses.

    Nothing is repaired. This is a report, and reading it is the point.
    """

    key = "worldcheck"
    locks = "cmd:perm(Builder) or perm(Admin)"
    help_category = "World"

    def parse(self):
        arg = self.args.strip()
        self.world_num = int(arg) if arg.isdigit() else None

    def func(self):
        from world import rulecheck

        if self.world_num is not None:
            account = _get_account(self.caller)
            worlds = _resolve_worlds(account)
            root = _choose_world(self.caller, worlds, self.world_num,
                                 "check", "worldcheck <number>")
            if root is None:
                return
        else:
            root = _current_world_root(self.caller)
            if root is None:
                self.caller.msg(
                    "You are not in a generated world. Give a number from "
                    "|wworlds|n to check one you are not standing in.")
                return

        findings = rulecheck.scan(rulecheck.of_world(root))
        self.caller.msg(rulecheck.report(findings, lore.title(root)))


class CmdRules(Command):
    """
    What this world's rules say, and the order they say it in.

    Usage:
      rules
      rules <verb>

    Every rule this world holds, or with a verb after it, only the rules
    about that verb: what it needs before it will work, what it does, and
    what follows from it having worked.

    The order is the point. A rule about one particular thing is consulted
    before a rule about that sort of thing, which comes before one about the
    sort of place you are standing in, then the room, then the area, then the
    world. So a rule about datapads decides what powering a datapad does,
    even aboard a ship with its own rule about powering.

    Rules marked |xsuspended|n are in the book and not in force. Ones marked
    |xstandard|n came with the world rather than being learned in it.

    Nothing here costs anything: it is read out of what the world already
    wrote down.
    """

    key = "rules"
    locks = "cmd:all()"
    help_category = "World"

    def func(self):
        from world import rulebooks, standard_rules, verbs

        root = _current_world_root(self.caller)
        if root is None:
            self.caller.msg("You are not in a generated world.")
            return
        standard_rules.seed(root)

        asked = self.args.strip().lower()
        if asked:
            self.caller.msg(self._one_verb(root, verbs.canonical_verb(asked)))
        else:
            self.caller.msg(self._everything(root))

    def _said(self, rule, root):
        """One rule as a line: where it applies, and what it says."""
        from world import conditions, rulebooks, standard_rules

        marks = []
        if not rule.get("listed", True):
            marks.append("suspended")
        if standard_rules.is_standard(rule):
            marks.append("standard")
        said = rule.get("name") or ""
        if not said and rule.get("conditions"):
            said = conditions.describe(rule["conditions"][0])
        where = rulebooks.said_scope(rule.get("scope"), root)
        note = f" |x({', '.join(marks)})|n" if marks else ""
        return f"{where} -- {said}{note}"

    def _one_verb(self, root, verb):
        from world import actions, rulebooks

        lines = [f"|w{verb}|n"]
        declared = actions.spec(root, verb)
        if declared:
            takes = ", ".join(
                f"{r['role']} ({r['access']}"
                + (", optional)" if r["optional"] else ")")
                for r in declared.get("applies_to") or []) or "nothing"
            lines.append(f"  takes {takes}")
            if declared.get("means"):
                lines.append(f"  |x{declared['means']}|n")
        else:
            lines.append("  |xnobody has declared what it takes yet|n")

        found = [r for r in rulebooks.all_rules(root)
                 if r.get("action") in (None, verb)]
        if not found:
            lines.append("")
            lines.append("  No rules about it yet.")
            return "\n".join(lines)

        for phase in rulebooks.PHASES:
            here = sorted((r for r in found if r.get("phase") == phase),
                          key=lambda r: rulebooks.rank(r, None, root))
            if not here:
                continue
            lines.append("")
            lines.append(f"  |y{phase.replace('_', ' ')}|n")
            lines += [f"    {self._said(rule, root)}" for rule in here]
        return "\n".join(lines)

    def _everything(self, root):
        from world import rulebooks

        found = rulebooks.all_rules(root)
        if not found:
            return "This world has no rules yet."

        by_action = {}
        for rule in found:
            by_action.setdefault(rule.get("action") or "any action",
                                 []).append(rule)
        lines = [f"|w{lore.title(root)}|n has {len(found)} rules, "
                 f"over {len(by_action)} verbs.", ""]
        for action in sorted(by_action):
            lines.append(f"  |w{action}|n")
            for rule in sorted(by_action[action],
                               key=lambda r: rulebooks.rank(r, None, root)):
                lines.append(f"    {rule.get('phase', ''):10} "
                             f"{self._said(rule, root)}")
        lines.append("")
        lines.append("|xType |wrules <verb>|x for one verb in firing order.|n")
        return "\n".join(lines)


class CmdWorldOpen(Command):
    """
    Open a way on, in a world that has nowhere left to go.

    Usage:
      worldopen

    A world grows by having somewhere unexplored left in it. Every room built
    spends one of those and leaves behind however many its exits promise, so a
    run of dead ends can close a world off entirely -- no unexplored ways, no
    more rooms, however small it stopped.

    This finds the best place to carry on from and opens a door there. Worlds
    built from now on do this for themselves the moment they would otherwise
    have ended; this is for one that already has.
    """

    key = "worldopen"
    locks = "cmd:all()"
    help_category = "World"

    def func(self):
        from world.worldgen import ensure_frontier, frontier, pending_exits

        root = _current_world_root(self.caller)
        if root is None:
            self.caller.msg("You are not in a generated world.")
            return

        left = frontier(root)
        if left:
            ways = pending_exits(root)[:5]
            where = ", ".join(
                f"{ex.key} from {ex.location.db.room_title or ex.location.key}"
                for ex in ways
            )
            self.caller.msg(
                f"|w{lore.title(root)}|n still has {left} way(s) nobody has "
                f"taken. Nothing to open.\n|x{where}|n"
            )
            return

        opened = ensure_frontier(root, near=self.caller.location)
        if opened is None:
            self.caller.msg(
                "There is nowhere left to open a way onto — every room is "
                "walled in on all six sides. That should not be possible; "
                "the world may have lost its coordinates."
            )
            return

        where = opened.location.db.room_title or opened.location.key
        self.caller.msg(
            f"A way |w{opened.key}|n opens from |w{where}|n. "
            f"The world has somewhere to go again."
        )
