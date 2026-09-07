"""
Garments: the things characters wear.

A garment is an ordinary object of the world -- it has affordances and states,
verbs work on it, it can be given away and burned -- that additionally knows
how to be worn. Evennia's clothing contrib supplies the wearing itself
(`wear`, `remove`, covering, the type limits); this adds the world's own
behaviour on top and keeps a worn garment honest about leaving its wearer.

What a character looks like is therefore no longer fixed at birth. The
description says what is permanently true of their body, and what they have on
is added to it from the garments they are actually carrying, so a change of
clothes changes what people see when they look.
"""

from evennia.contrib.game_systems.clothing.clothing import ContribClothing

from .objects import ObjectParent


class Garment(ObjectParent, ContribClothing):
    """
    Something that can be worn.

    Created wherever an item turns out to be wearable, so clothes found in a
    room can be put on and clothes taken off can be dropped, without anything
    having to decide in advance which objects are outfits and which are props.
    """

    def at_pre_move(self, destination, **kwargs):
        """
        Take a garment off before it leaves the person wearing it.

        Giving away or dropping something you have on is a perfectly ordinary
        thing to do, and every path that moves objects -- `give`, `drop`, a
        verb's move_object effect -- goes through here. Without this a garment
        handed to someone else would still be listed as worn by the person who
        no longer has it.
        """
        if not super().at_pre_move(destination, **kwargs):
            return False      # covered by something else; take that off first

        wearer = self.location
        if self.db.worn and wearer is not None and wearer is not destination:
            self.remove(wearer, quiet=True)
        return True
