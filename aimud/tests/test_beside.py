"""
Being under or behind a thing, which is not being inside it.

Every preposition used to be stored the same way -- `obj.move_to(host)` --
which is right for two of the four and plainly wrong for the other two. The
case that shows it: a coin under a rug was kept *inside* the rug, so picking
the rug up carried the coin off in your inventory and left the floor with
neither.

`in` and `on` are still containment and should be: a thing in a box or on a
tray travels with it, is hidden when the box is shut, and needs no bookkeeping
because Evennia's containment does all of it. `under` and `behind` say where a
thing is in a room rather than what is holding it, so they are a pointer and
both things stay where they were.

What falls out of it is in `test_wearing.Covering`: covering is placement now,
and `world.clothing` keeps no relation of its own.
"""

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import kinds, relations


class TheTwoSorts(SimpleTestCase):

    def test_every_preposition_is_one_or_the_other(self):
        self.assertEqual(sorted(relations.CONTAINED + relations.BESIDE),
                         sorted(relations.PREPOSITIONS))

    def test_and_each_has_an_other_side(self):
        for preposition in relations.PREPOSITIONS:
            self.assertIn(preposition, relations.INVERSE)


@tag("world")
class ACoinUnderARug(GameTest):
    loose_objects = 2

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.rug, self.coin = self.obj1, self.obj2
        self.rug.key, self.coin.key = "rug", "coin"

    def test_it_stays_on_the_floor(self):
        """Inside the rug is where it used to go, and a coin is not in a rug."""
        relations.place(self.coin, self.rug, "under")
        self.assertIs(self.coin.location, self.room1)
        self.assertIs(relations.host_of(self.coin), self.rug)

    def test_and_the_rug_knows_what_is_under_it(self):
        relations.place(self.coin, self.rug, "under")
        self.assertEqual(relations.contents(self.rug, "under"), [self.coin])

    def test_taking_the_rug_leaves_the_coin(self):
        """
        The bug this exists for. The coin went into the taker's inventory,
        still inside the rug, and the floor had neither.
        """
        relations.place(self.coin, self.rug, "under")
        self.rug.move_to(self.char1, quiet=True)
        self.assertIs(self.coin.location, self.room1)
        self.assertIn(self.coin, self.room1.contents)

    def test_and_the_relation_lapses_when_they_part(self):
        """
        No hook unpicks it. A thing is under another because they are in the
        same place, so parting them is the whole of the cleanup -- and nothing
        is said about it, because what to say when a coin comes to light is a
        rule's business.
        """
        relations.place(self.coin, self.rug, "under")
        self.rug.move_to(self.char1, quiet=True)
        self.assertIsNone(relations.host_of(self.coin))

    def test_putting_down_something_you_are_holding(self):
        self.coin.move_to(self.char1, quiet=True)
        ok, _said = relations.place(self.coin, self.rug, "under")
        self.assertTrue(ok)
        self.assertIs(self.coin.location, self.room1)

    def test_it_is_listed_by_the_rug_and_not_beside_it(self):
        """
        The coin is in the room's own contents now, so without care it reads
        twice: loosely among what you see, and again under the rug.
        """
        relations.place(self.coin, self.rug, "under")
        said = self.room1.return_appearance(self.char1)
        self.assertEqual(said.count("coin"), 1, said)
        self.assertIn("under it", said)


@tag("world")
class ATableOnARug(GameTest):
    """`on` stays containment, and the cases the user asked about."""

    loose_objects = 2

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.rug, self.table = self.obj1, self.obj2
        self.rug.key, self.table.key = "rug", "table"
        for obj, kind in ((self.rug, "rug.n.01"), (self.table, "table.n.02")):
            obj.db.kinds = [kind]
            kinds.remember(self.root, kind, {}, accepts=["on"])

    def test_the_table_goes_on_the_rug(self):
        ok, _said = relations.place(self.table, self.rug, "on")
        self.assertTrue(ok)
        self.assertIs(self.table.location, self.rug, "on is containment")

    def test_and_then_the_rug_is_under_the_table(self):
        """
        The other side, which nothing could say. Only the guest carried the
        word, so `relation_of(rug)` answered that the rug was nowhere in
        particular while a table stood on it.
        """
        relations.place(self.table, self.rug, "on")
        self.assertEqual(relations.standing(self.rug), "under a table")
        self.assertEqual(relations.context_line(self.table), "on a rug")

    def test_the_rug_cannot_then_go_on_the_table(self):
        relations.place(self.table, self.rug, "on")
        ok, said = relations.place(self.rug, self.table, "on")
        self.assertFalse(ok)

    def test_and_is_told_which_way_round_it_already_is(self):
        """
        "That would have to go inside itself" was the only refusal available,
        and it named containment in a sentence where the player said "on".
        """
        relations.place(self.table, self.rug, "on")
        _ok, said = relations.place(self.rug, self.table, "on")
        self.assertIn("already on", said)
        self.assertIn("table", said)

    def test_neither_can_a_coin_be_under_what_is_under_it(self):
        """The same question asked of the pointer side."""
        relations.place(self.table, self.rug, "under")
        ok, said = relations.place(self.rug, self.table, "under")
        self.assertFalse(ok, said)
