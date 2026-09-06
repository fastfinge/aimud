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

    def world_name(self, world_root=None):
        """
        What this character is called in a given world, if anything.

        Names are per world, because a character who is "Sister Agnes" in a
        convent has no business being Sister Agnes aboard a freighter. With
        none set the account name stands.
        """
        if world_root is None:
            room = self.location
            world_root = room.db.world_root if room else None
        if world_root is None:
            return None
        return (self.db.world_names or {}).get(str(world_root.id)) or None

    def set_world_name(self, world_root, name):
        """
        Name this character in `world_root`, or clear it with a falsy name.

        The name is also kept as an alias, so that a character can be spoken
        to, given things and named in commands by what everyone actually calls
        them -- an NPC that sees "Aria" would otherwise offer a quest to
        nobody, since the lookup would be searching for the account name.
        """
        if world_root is None:
            return None
        names = dict(self.db.world_names or {})
        key = str(world_root.id)
        previous = names.get(key)

        if name:
            names[key] = name
        else:
            names.pop(key, None)
        self.db.world_names = names

        # Retire the old alias unless another world still uses that name.
        if previous and previous not in names.values():
            self.aliases.remove(previous)
        if name and name.lower() != self.key.lower():
            self.aliases.add(name)
        return names.get(key)

    def get_display_name(self, looker=None, **kwargs):
        """Everyone, the character included, sees the name they chose here."""
        return self.world_name() or super().get_display_name(looker, **kwargs)

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

        # Arriving puts every NPC here back in company, so they keep acting
        # for a while after this character wanders off again.
        from world.activity import refresh_npcs_near

        refresh_npcs_near(room)

        # Arriving can satisfy a quest by itself, and is a natural moment to
        # notice one that has run out of time.
        from world.quests import review

        review(self)

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
