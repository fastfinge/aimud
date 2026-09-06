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


class AIExit(ObjectParent, DefaultExit):
    """
    An exit created by AI world generation.

    If db.pending_generation is True the destination has not been generated
    yet.  The first traversal triggers async generation; subsequent attempts
    while generation is in progress are queued and moved when it completes.
    """

    def at_traverse(self, traversing_object, target_location, **kwargs):
        if not self.db.pending_generation:
            return super().at_traverse(traversing_object, target_location, **kwargs)

        account = getattr(traversing_object, "account", None) or traversing_object
        source_room = self.location
        world_description = source_room.db.world_description if source_room else None

        if not world_description:
            traversing_object.msg("This exit leads nowhere.")
            return

        # Queue the traveler; avoid spawning duplicate generation tasks.
        if self.ndb.generating:
            if not self.ndb.waiting_travelers:
                self.ndb.waiting_travelers = []
            if traversing_object not in self.ndb.waiting_travelers:
                self.ndb.waiting_travelers.append(traversing_object)
                traversing_object.msg("A room is already being generated here — you'll be moved when it's ready.")
            return

        self.ndb.generating = True
        self.ndb.waiting_travelers = [traversing_object]
        traversing_object.msg(f"Generating room to the {self.key}...")

        exit_key = self.key  # capture before async
        hint = self.db.destination_hint or ""

        def on_success(room):
            self.ndb.generating = False
            self.db.pending_generation = False
            self.destination = room
            for traveler in (self.ndb.waiting_travelers or []):
                if traveler.location is not None:
                    traveler.move_to(room, quiet=False)
            self.ndb.waiting_travelers = []

        def on_error(err):
            self.ndb.generating = False
            for traveler in (self.ndb.waiting_travelers or []):
                traveler.msg(f"|rRoom generation failed: {err}|n")
            self.ndb.waiting_travelers = []

        from world.worldgen import generate_connected_room
        generate_connected_room(
            account, world_description, source_room, exit_key, on_success, on_error,
            destination_hint=hint,
        )
