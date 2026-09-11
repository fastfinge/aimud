"""
Exits

Exits are connectors between Rooms. An exit always has a destination property
set and has a single command defined on itself with the same name as its key,
for allowing Characters to traverse the exit to its destination.

"""

from evennia.objects.objects import DefaultExit

from .objects import ObjectParent


class Exit(ObjectParent, DefaultExit):
    """
    Exits are connectors between rooms. Exits are normal Objects except
    they defines the `destination` property and overrides some hooks
    and methods to represent the exits.

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Objects child classes like this.

    """

    pass


#: World root id -> the exit an NPC currently has building there.
#:
#: A player waiting at an exit is the whole point of the game and never queues
#: behind anybody.  An NPC is different: every character in a world idles on
#: its own timer, so without this a populated world could set a dozen rooms
#: generating at the same moment somebody logged in -- three model calls each,
#: for rooms nobody is standing in.  One at a time still grows the world, and
#: the wait costs an NPC nothing.
_NPC_BUILDS = {}


def _is_player(obj):
    """True for something a person is playing through."""
    return getattr(obj, "account", None) is not None


def _sponsor_for(traversing_object, source_room):
    """
    Who pays for the room beyond this exit, and who is walking through it.

    It used to be whoever was passing, then anybody in the room with a key,
    then the world's creator. That is the same fault `npcs._find_account` had
    and it is worse here, because it is silent: a visitor who steps through a
    door in somebody else's world buys the room on the other side, and the
    first they know of it is the bill. The world pays for its own rooms.
    """
    from world import sponsor

    world_root = source_room.db.world_root if source_room else None
    return sponsor.of_world(world_root, actor=traversing_object)


class AIExit(ObjectParent, DefaultExit):
    """
    An exit created by AI world generation.

    If db.pending_generation is True the destination has not been generated
    yet.  The first traversal triggers async generation; subsequent attempts
    while generation is in progress are queued and moved when it completes.
    """

    def _room_already_there(self, source_room):
        """
        The room occupying the cell this exit leads to, or None.

        Returns None for exits with no compass sense (portals, labelled exits)
        and for rooms that predate the coordinate index -- both fall through to
        ordinary generation.
        """
        from world import coords

        world_root = source_room.db.world_root if source_room else None
        source_coord = coords.get_coord(source_room) if source_room else None
        if world_root is None or source_coord is None:
            return None
        target = coords.step(source_coord, self.key)
        if target is None:
            return None
        found = coords.room_at(world_root, target)
        return found if found is not source_room else None

    def at_traverse(self, traversing_object, target_location, **kwargs):
        # Before anything is built or entered: some states stop you leaving at
        # all. Here rather than in `at_post_move`, because a step that never
        # happens must not build the room on the far side of it -- and because
        # blocking here is what lets a posture still end on movement while a
        # rope does not, the one clearing after a step the other forbids.
        from world import verbs

        refusal = verbs.refuse(traversing_object, "prevents_moving")
        if refusal:
            traversing_object.msg(refusal)
            return

        # And some states stop you going through this particular way. A door
        # has been shuttable since `relations.SHUT` named the vocabulary, and
        # shutting one did nothing: a rule could set `locked` on an exit and the
        # exit went on admitting everybody. So the `locked` state that 121
        # `lacks` clauses in the corpus talk about had nothing behind it.
        #
        # Read from the same set a container uses, so that closing a thing means
        # one thing in this game and not two. Checked here rather than in a
        # rulebook because going is Evennia's own command and does not come
        # through the attempt pipeline -- which is a limit worth naming: a world
        # cannot yet write its own rules about walking, only set the states this
        # reads. See docs/development-plan.md phase 9.
        from world import relations

        shut = relations.SHUT & verbs.states(self)
        if shut:
            traversing_object.msg(
                f"{self.get_numbered_name(1, traversing_object, return_string=True)}"
                f" is {sorted(shut)[0]}.".capitalize())
            return

        if not self.db.pending_generation:
            return super().at_traverse(traversing_object, target_location, **kwargs)

        source_room = self.location
        # Read from the world root rather than the room's own copy, so that a
        # description changed with `worldedit` governs every room built after
        # it. The room's copy is the fallback for anything built before worlds
        # kept their text in one place.
        from world import lore

        world_description = (
            (lore.raw_description(source_room) or source_room.db.world_description)
            if source_room else None
        )

        if not world_description:
            traversing_object.msg("This exit leads nowhere.")
            return

        sponsor = _sponsor_for(traversing_object, source_room)
        if not sponsor.answers:
            traversing_object.msg("There is no way through yet.")
            return

        # If a room already stands where this exit leads, connect to it rather
        # than building a second one on the same spot.  This is what lets a
        # world close back on itself, and it costs no API call.
        existing = self._room_already_there(source_room)
        if existing is not None:
            from world.worldgen import ensure_return_exit

            self.db.pending_generation = False
            self.destination = existing
            ensure_return_exit(existing, source_room, self.key)
            return super().at_traverse(traversing_object, existing, **kwargs)

        # Queue the traveler; avoid spawning duplicate generation tasks.
        if self.ndb.generating:
            if not self.ndb.waiting_travelers:
                self.ndb.waiting_travelers = []
            if traversing_object not in self.ndb.waiting_travelers:
                self.ndb.waiting_travelers.append(traversing_object)
                traversing_object.msg("A room is already being generated here — you'll be moved when it's ready.")
            return

        # NPCs take turns at this; a player never waits on one.
        world_root = source_room.db.world_root
        if not _is_player(traversing_object):
            holder = _NPC_BUILDS.get(getattr(world_root, "id", None))
            if holder is not None and holder != self.id:
                return
            if world_root is not None:
                _NPC_BUILDS[world_root.id] = self.id

        self.ndb.generating = True
        self.ndb.waiting_travelers = [traversing_object]
        traversing_object.msg(f"Generating room to the {self.key}...")

        exit_key = self.key  # capture before async
        hint = self.db.destination_hint or ""

        def release():
            self.ndb.generating = False
            if _NPC_BUILDS.get(getattr(world_root, "id", None)) == self.id:
                del _NPC_BUILDS[world_root.id]

        def on_success(room):
            release()
            self.db.pending_generation = False
            self.destination = room
            for traveler in (self.ndb.waiting_travelers or []):
                if traveler.location is not None:
                    traveler.move_to(room, quiet=False)
            self.ndb.waiting_travelers = []

        def on_error(err):
            release()
            for traveler in (self.ndb.waiting_travelers or []):
                traveler.msg(f"|rRoom generation failed: {err}|n")
                # An NPC has nowhere to read that, and would pick the same way
                # again next turn. Telling it keeps it from looping on a door
                # that cannot be built.
                if hasattr(traveler, "_note_to_self"):
                    traveler._note_to_self(f"the way {self.key} from here would not open")
            self.ndb.waiting_travelers = []

        from world.worldgen import generate_connected_room
        generate_connected_room(
            sponsor, world_description, source_room, exit_key, on_success,
            on_error, destination_hint=hint,
        )
