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
        speaker_name = self.get_display_name(self)
        for obj in room.contents:
            if obj is not self and obj.db.is_npc:
                obj.witness("say", speaker_name, message)

    def at_post_move(self, source_location, move_type="move", **kwargs):
        super().at_post_move(source_location, move_type=move_type, **kwargs)
        room = self.location
        if not room:
            return
        world_root = room.db.world_root
        if not world_root:
            return
        account = self.account
        if not account:
            return
        locs = account.db.world_last_locations or {}
        locs[str(world_root.id)] = room
        account.db.world_last_locations = locs
