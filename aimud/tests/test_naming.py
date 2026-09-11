"""
Turning what a player typed into the things they meant.

Every failure in this file had the same shape and the same cost. A noun phrase
the parser could not bind is not refused -- it is *promoted*, because a fixture
the room describes should become real when somebody reaches for it. So a phrase
that named something perfectly ordinary and merely did not look like a name
bought a model call and left an absurd object standing in the world for good:
an object called "here", one called "stone with tongs", one called "every
wrench".

The one to read first is `TheTwoThingsNoSearchCanFind`. A room does not appear
in its own contents and a character is not in their own inventory, so the two
things always in scope were the two things `bind` could never answer -- which
is why "look here" conjured a `here`.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeAccount, immediately, replying
from world import attempt as attempt_mod
from world import bulk, relations, standard_rules, verbs


@tag("unit")
class CountingWordsAreNotNames(SimpleTestCase):
    """`ordinal` is pure, so it is asserted without a world in front of it."""

    def test_a_count_is_split_from_what_is_counted(self):
        self.assertEqual(verbs.ordinal("the second wrench"), (2, "wrench"))
        self.assertEqual(verbs.ordinal("3rd wrench"), (3, "wrench"))
        self.assertEqual(verbs.ordinal("last wrench"), (-1, "wrench"))

    def test_a_plain_noun_counts_nothing(self):
        self.assertEqual(verbs.ordinal("wrench"), (0, "wrench"))
        self.assertEqual(verbs.ordinal("the brass wrench"), (0, "brass wrench"))

    def test_a_count_with_nothing_after_it_is_a_name(self):
        """
        "get first" is somebody naming a thing called first, not an empty
        request for the first of nothing. Zero means nobody counted.
        """
        self.assertEqual(verbs.ordinal("first"), (0, "first"))

    def test_quantifiers_split_the_same_way(self):
        self.assertEqual(bulk.split("every wrench"), (True, "wrench"))
        self.assertEqual(bulk.split("all the wrenches"), (True, "wrenches"))
        self.assertEqual(bulk.split("all"), (True, ""))
        self.assertEqual(bulk.split("wrench"), (False, "wrench"))

    def test_the_lot_still_means_the_lot(self):
        """Noise words are gone by the time a phrase is tested, so both spellings."""
        self.assertTrue(bulk.wanted("the lot"))
        self.assertTrue(bulk.wanted("everything"))
        self.assertTrue(bulk.wanted("everyone"))


class Naming(EvenniaTest):
    """A world, a room, and three wrenches to count through."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        self.room2.db.world_description = "A workshop under a ruined keep."
        self.room2.db.desc = "A low workshop, badly lit."
        self.char1.move_to(self.room2, quiet=True)
        standard_rules.seed(self.root)

    def thing(self, key, location=None):
        """
        One ordinary, liftable object.

        Takeability is settled here rather than left to a model. Whether a
        wrench can be picked up is a question asked and cached elsewhere, and
        leaving it open would make every test in this file need a scripted
        answer to a question it is not about.
        """
        from evennia import create_object

        made = create_object("typeclasses.objects.Object", key=key,
                             location=location or self.room2)
        made.db.ai_takeable = True
        return made

    def wrenches(self, count=3):
        """`count` identically named things, oldest first."""
        return [self.thing("Wrench") for _ in range(count)]

    def typed(self, raw, *replies):
        """What the player is told, having typed this at the command set."""
        said = []
        self.char1.msg = lambda text="", **kwargs: said.append(str(text))
        with immediately(), replying(*(replies or ("{}",))):
            self.char1.execute_cmd(raw)
        return "\n".join(s for s in said if s)

    def attempted(self, raw, *replies):
        """What the pipeline answers, with the model answering from a script."""
        said = []
        with immediately(), replying(*(replies or ("{}",))):
            attempt_mod.attempt(
                self.char1, raw, FakeAccount(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text or ""))
        return "\n".join(s for s in said if s)


@tag("world")
class TheTwoThingsNoSearchCanFind(Naming):
    """
    The room and the actor: always in scope, never in anybody's contents.

    `bind` answered None for both, and an unbound noun is promoted -- so "look
    here" was a request to invent an object called "here", and "mine here with
    the trowel" could not name the room it was standing in at all.
    """

    def test_here_is_the_room(self):
        self.assertIs(verbs.bind(self.char1, "here"), self.room2)
        self.assertIs(verbs.bind(self.char1, "the room"), self.room2)
        self.assertIs(verbs.bind(self.char1, "around"), self.room2)

    def test_me_is_the_actor(self):
        self.assertIs(verbs.bind(self.char1, "me"), self.char1)
        self.assertIs(verbs.bind(self.char1, "myself"), self.char1)

    def test_looking_here_describes_the_room(self):
        said = self.attempted("look here")
        self.assertIn("A low workshop", said)

    def test_and_conjures_nothing(self):
        before = len(self.room2.contents)
        self.attempted("look here")
        self.assertEqual(len(self.room2.contents), before,
                         "looking here should have made nothing")

    def test_a_room_can_be_the_thing_a_tool_is_used_on(self):
        """
        "mine here with the trowel" binds both roles rather than neither. What
        mining means is the world's business; that the sentence resolves is
        this module's.
        """
        self.thing("Trowel", location=self.char1)
        bound, unbound = verbs.bind_all(
            self.char1, verbs.parse("mine here with the trowel")["roles"])
        self.assertEqual(unbound, [])
        self.assertIs(bound["direct"], self.room2)
        self.assertEqual(bound["instrument"].key, "Trowel")


@tag("world")
class CountingThroughSeveral(Naming):

    def test_the_second_wrench_is_the_second_wrench(self):
        one, two, three = self.wrenches()
        self.assertIs(verbs.bind(self.char1, "second wrench"), two)
        self.assertIs(verbs.bind(self.char1, "third wrench"), three)
        self.assertIs(verbs.bind(self.char1, "first wrench"), one)

    def test_the_last_one_counts_from_the_other_end(self):
        _one, _two, three = self.wrenches()
        self.assertIs(verbs.bind(self.char1, "last wrench"), three)

    def test_counting_past_the_end_names_nothing(self):
        """
        And must not: inventing a fourth wrench to satisfy a request for the
        fourth of three is the worst possible reading of it.
        """
        self.wrenches(3)
        self.assertIsNone(verbs.counted(self.char1, "fourth wrench"))

    def test_what_is_carried_is_counted_first(self):
        """One list, in the order somebody counting out loud would use."""
        one, _two, _three = self.wrenches()
        one.move_to(self.char1, quiet=True)
        self.assertIs(verbs.bind(self.char1, "first wrench"), one)

    def test_getting_the_second_wrench_picks_up_the_second(self):
        _one, two, _three = self.wrenches()
        self.typed("get second wrench")
        self.assertIs(two.location, self.char1)

    def test_dropping_the_second_wrench_drops_the_second(self):
        one, two, _three = self.wrenches()
        for obj in (one, two):
            obj.move_to(self.char1, quiet=True)
        self.typed("drop second wrench")
        self.assertIs(two.location, self.room2)
        self.assertIs(one.location, self.char1)


@tag("world")
class EveryOneOfSomething(Naming):
    """
    "Every wrench" is a narrowing, and was read as a name.

    `bulk` knew "all" and nothing else, so "get every wrench" matched nothing,
    which this game answers by offering to invent it -- an object called "every
    wrench", bought with a model call.
    """

    def test_matching_narrows_to_what_was_named(self):
        self.wrenches(2)
        self.thing("Hammer")
        found = bulk.matching(self.char1, "get", "every wrench")
        self.assertEqual(sorted(o.key for o in found), ["Wrench", "Wrench"])

    def test_all_still_means_everything(self):
        self.wrenches(2)
        self.thing("Hammer")
        found = bulk.matching(self.char1, "get", "all")
        self.assertEqual(len(found), 3)

    def test_getting_every_wrench_gets_every_wrench(self):
        made = self.wrenches(2)
        hammer = self.thing("Hammer")
        self.typed("get every wrench")
        for wrench in made:
            self.assertIs(wrench.location, self.char1)
        self.assertIs(hammer.location, self.room2)

    def test_dropping_every_wrench_keeps_the_hammer(self):
        made = self.wrenches(2)
        hammer = self.thing("Hammer", location=self.char1)
        for wrench in made:
            wrench.move_to(self.char1, quiet=True)
        self.typed("drop every wrench")
        for wrench in made:
            self.assertIs(wrench.location, self.room2)
        self.assertIs(hammer.location, self.char1,
                      "a hammer is not a wrench")

    def test_naming_a_sort_nothing_here_is_says_so(self):
        said = self.typed("get every wrench")
        self.assertIn("wrench", said.lower())


@tag("world")
class SentencesTheCommandSetCannotSay(Naming):
    """
    `get` takes a noun. "Get the stone with the tongs" takes a noun and a tool.

    The command read everything after the verb as one name, so it looked for a
    thing called "stone with tongs", found none, and offered to make one. What
    it should do is hand the sentence to the rulebooks, which is where a world
    is allowed to have an opinion about tongs.
    """

    def test_a_get_with_a_tool_reaches_the_pipeline(self):
        from unittest import mock

        with mock.patch.object(attempt_mod, "attempt") as attempted:
            self.typed("get stone with tongs")
        self.assertTrue(attempted.called)
        self.assertEqual(attempted.call_args[0][1], "get stone with tongs")

    def test_and_a_plain_get_does_not(self):
        from unittest import mock

        stone = self.thing("Stone")
        with mock.patch.object(attempt_mod, "attempt") as attempted:
            self.typed("get stone")
        self.assertFalse(attempted.called)
        self.assertIs(stone.location, self.char1)

    def test_the_pipeline_does_not_hand_it_straight_back(self):
        """
        The bounce, in the one direction that is newly possible. `get` is a
        command, so the pipeline hands it over -- and the command hands
        sentences like this one to the pipeline, so the two would pass it
        between them for ever. Answered once, with nothing conjured.
        """
        self.thing("Stone")
        self.thing("Tongs", location=self.char1)
        before = len(self.room2.contents)
        self.typed("get stone with tongs",
                   '{"applies_to": [{"role": "direct"}]}',
                   '{"rules": []}',
                   '{"allowed": true, "reason": ""}',
                   '{"actor": "You lift it with the tongs.", "room": ""}')
        self.assertEqual(len(self.room2.contents), before,
                         "nothing should have been conjured")


@tag("world")
class TakingOutAndPuttingIn(Naming):
    """
    Placement read backwards, and the room as a place to put things.

    Both were sentences the game understood every word of and had nowhere to
    send: "get the key from the drawer" looked for a thing called "key from the
    drawer", and "put the lamp in here" would have been refused for the
    workshop not holding things.
    """

    def setUp(self):
        super().setUp()
        from world import kinds

        self.drawer = self.thing("Drawer")
        self.drawer.db.kinds = ["drawer.n.01"]
        # Settled up front. Whether a drawer holds things is a fact about
        # drawers, decided where that is tested; here it would only be another
        # scripted reply about something this file is not about.
        store = dict(getattr(self.root.db, kinds.ATTR, None) or {})
        store["drawer.n.01"] = {"affordances": {}, "holds": ["in"]}
        setattr(self.root.db, kinds.ATTR, store)
        self.key = self.thing("Key")

    def test_getting_something_out_of_what_holds_it(self):
        relations.place(self.key, self.drawer, "in")
        said = self.attempted("get key from drawer")
        self.assertIs(self.key.location, self.char1)
        self.assertIn("take", said.lower())

    def test_and_declining_when_it_is_not_in_there(self):
        """
        "Get the answer from the book" stays a question for a world rather
        than a placement that failed, so the mechanic answers False and the
        pipeline goes on.
        """
        self.assertFalse(relations.handle(
            self.char1, "get", verbs.parse("get key from drawer"),
            {"direct": self.key, "source": self.drawer},
            lambda actor, room="": None))

    def test_a_shut_container_keeps_what_is_in_it(self):
        relations.place(self.key, self.drawer, "in")
        verbs.apply_states(self.drawer, add=["closed"], world_root=self.root)
        said = self.attempted("get key from drawer")
        self.assertIn("closed", said.lower())
        self.assertIs(self.key.location, self.drawer)

    def test_putting_something_in_here_is_a_drop(self):
        self.key.move_to(self.char1, quiet=True)
        said = self.attempted("put key in here")
        self.assertIs(self.key.location, self.room2)
        self.assertIn("put down", said.lower())

    def test_a_room_is_not_something_things_are_in(self):
        """
        `host_of` promised None for a thing lying loose on the floor and
        answered the room, so everything in every room read as being *in*
        something -- one confusion away from telling a rule that a key on the
        floor is in the box.
        """
        self.assertIsNone(relations.host_of(self.key))
        self.assertEqual(relations.relation_of(self.key), (None, None))


@tag("world")
class TheMechanicsGetTheirSayTwice(Naming):
    """
    "Put the coins in the pouch", when there are no coins yet.

    Three of the game's verbs are mechanics rather than questions -- wearing,
    wielding and placement -- and each declines anything that is not really its
    business, so "put out the fire" still reaches a world. They were asked
    once, before anything unbound had been promoted, so a placement with a
    noun still missing was declined for the missing noun and then never asked
    again once it was there.

    What the attempt reached instead was the rulebooks, where `put` had had an
    arity read off whichever roles some earlier sentence happened to fill.
    "Put out the fire" names a source and no direct object, so `put` was
    settled as needing a source -- and every placement afterwards was answered
    "Put from what?" or "Put at what?".
    """

    def setUp(self):
        super().setUp()
        from world import kinds

        self.pouch = self.thing("Pouch")
        self.pouch.db.kinds = ["pouch.n.01"]
        store = dict(getattr(self.root.db, kinds.ATTR, None) or {})
        store["pouch.n.01"] = {"affordances": {}, "holds": ["in"]}
        setattr(self.root.db, kinds.ATTR, store)

    def test_a_placement_whose_noun_had_to_be_made_is_still_a_placement(self):
        made = []

        def conjure(caller, room, account, phrase, on_ready, on_refused,
                    fuzzy=False):
            coins = self.thing("Coins")
            made.append(coins)
            on_ready(coins, True)

        from unittest import mock
        from world import item_gen

        with mock.patch.object(item_gen, "conjure", conjure):
            said = self.attempted("put coins in pouch")
        self.assertTrue(made, "the coins should have been conjured")
        self.assertIs(made[0].location, self.pouch)
        self.assertIn("put", said.lower())
        self.assertNotIn("what?", said)

    def test_the_placement_verbs_are_declared_rather_than_guessed(self):
        from world import actions

        for verb in ("put", "place", "insert"):
            declared = actions.spec(self.root, verb)
            self.assertIsNotNone(declared, verb)
            self.assertTrue(
                all(role["optional"] for role in declared["applies_to"]),
                f"{verb} should insist on nothing")

    def test_so_a_figure_of_speech_never_settles_an_arity(self):
        from world import actions

        self.attempted("put out the fire", '{"rules": []}')
        declared = actions.spec(self.root, "put")
        self.assertTrue(all(role["optional"]
                            for role in declared["applies_to"]))


@tag("unit")
class CountingIsNotCounting(SimpleTestCase):
    """
    "The second wrench" is one wrench; "two wrenches" is two of them. Reading
    the second as the first would answer a request for a pair with one thing,
    so the cardinals are deliberately not in the table.
    """

    def test_a_cardinal_is_not_an_ordinal(self):
        self.assertEqual(verbs.ordinal("two wrenches"), (0, "two wrenches"))
        self.assertEqual(verbs.ordinal("three wrenches"), (0, "three wrenches"))

    def test_the_other_one_is_the_second_one(self):
        self.assertEqual(verbs.ordinal("the other wrench"), (2, "wrench"))


@tag("world")
class TakingSomethingOffSomething(Naming):
    """
    "Get the lamp on the table" is a take, not a request for a thing called
    "lamp on the table" -- and nor is it a question for a world.

    Any of the three roles a preposition can land a host in says the same
    thing: where the thing is now. `_take_from` declines unless it really is
    there, so "get the answer from the book" still reaches the rulebooks.
    """

    def setUp(self):
        super().setUp()
        from world import kinds

        self.table = self.thing("Table")
        self.table.db.kinds = ["table.n.02"]
        store = dict(getattr(self.root.db, kinds.ATTR, None) or {})
        store["table.n.02"] = {"affordances": {}, "holds": ["on"]}
        setattr(self.root.db, kinds.ATTR, store)
        self.lamp = self.thing("Lamp")

    def test_off_a_surface(self):
        relations.place(self.lamp, self.table, "on")
        said = self.attempted("get lamp on table")
        self.assertIs(self.lamp.location, self.char1)
        self.assertIn("on", said.lower())

    def test_and_not_when_it_is_not_there(self):
        self.assertFalse(relations.handle(
            self.char1, "get", verbs.parse("get lamp on table"),
            {"direct": self.lamp, "target": self.table},
            lambda actor, room="": None))
