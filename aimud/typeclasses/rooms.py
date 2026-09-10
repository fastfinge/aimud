"""
Room

Rooms are simple containers that has no location of their own.

"""

from evennia.objects.objects import DefaultRoom

from .objects import ObjectParent


class Room(ObjectParent, DefaultRoom):
    """
    Rooms are like any Object, except their location is None
    (which is default). They also use basetype_setup() to
    add locks so they cannot be puppeted or picked up.
    (to change that, use at_object_creation instead)

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Objects.
    """

    def return_appearance(self, looker, **kwargs):
        """
        What this place looks like, or that it cannot be seen.

        Overridden here rather than left to the rules alone, because arriving
        somewhere is not an action. Evennia describes the room you have walked
        into from a movement hook, so the check rule that refuses looking in the
        dark never runs for it -- and a world that refused to let you examine
        anything in a cellar while still handing you the cellar's description on
        the way in would be telling you two different things.

        A world that has never registered a `light` trait has no darkness in it
        and never reaches the second branch. See world.conditions.sees and
        docs/rulebooks-from-inform.md 8.1.
        """
        from world import conditions

        root = getattr(self.db, "world_root", None)
        if root is None or conditions.sees(looker, self, root):
            return super().return_appearance(looker, **kwargs)
        return conditions.darkness(looker, self, root)

    def get_display_things(self, looker, **kwargs):
        """
        The room's loose contents, each noting what it is holding.

        A mug left on a table is in plain sight and has to read that way, or
        putting something down would be indistinguishable from hiding it. The
        note is short -- "an oak table (a mug on it)" -- because the full
        account belongs to looking at the table itself.
        """
        from world import relations

        listing = super().get_display_things(looker, **kwargs)
        notes = []
        for obj in self.contents:
            if not relations._is_thing(obj):
                continue
            summary = relations.summary(obj, looker)
            if summary:
                notes.append(
                    f"  {obj.get_numbered_name(1, looker, return_string=True)} "
                    f"|x{summary}|n")
        if not notes:
            return listing
        extra = "\n".join(notes)
        return f"{listing}\n{extra}" if listing else extra
