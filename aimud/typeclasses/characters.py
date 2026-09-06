"""
Characters

Characters are (by default) Objects setup to be puppeted by Accounts.
They are what you "see" in game. The Character class in this module
is setup to be the "default" character type created by the default
creation commands.

"""

from evennia.objects.objects import DefaultCharacter

from .objects import ObjectParent


class Character(ObjectParent, DefaultCharacter):
    """
    The Character just re-implements some of the Object's methods and hooks
    to represent a Character entity in-game.

    See mygame/typeclasses/objects.py for a list of
    properties and methods available on all Object child classes like this.

    """

    def at_say(self, message, msg_self=None, msg_location=None,
               receivers=None, msg_type="say", **kwargs):
        super().at_say(message, msg_self=msg_self, msg_location=msg_location,
                       receivers=receivers, msg_type=msg_type, **kwargs)
        room = self.location
        if not room:
            return
        from world.npc_gen import notify_npcs

        notify_npcs(room, "say", self.get_display_name(self), message,
                    exclude=self, actor=self)

    def at_post_move(self, source_location, move_type="move", **kwargs):
        super().at_post_move(source_location, move_type=move_type, **kwargs)
        room = self.location
        if not room:
            return

        # Where the character has been is part of what they know.
        from world.memory import remember

        where = room.db.room_title or room.key
        came_from = source_location.db.room_title or source_location.key if source_location else None
        remember(
            self,
            f"I arrived in {where}" + (f", coming from {came_from}" if came_from else ""),
            kind="moved",
            importance=0.3,
        )

        world_root = room.db.world_root
        if not world_root:
            return
        account = self.account
        if not account:
            return
        locs = account.db.world_last_locations or {}
        locs[str(world_root.id)] = room
        account.db.world_last_locations = locs
