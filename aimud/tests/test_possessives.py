"""
"Get her sword."

Three words, and until now every one of them was read wrongly. "Her" was part
of a name, so the search looked for an object called "her sword"; it found
none, and offered to invent one -- which is how a room comes to hold a sword
belonging to nobody, standing beside the sword it was a copy of. "My" was
noise and thrown away outright, so "my ball" and "the ball" were the same
request.

What is asserted here is the narrowing, and that it is a narrowing rather
than a search: a stated possessive is a claim about the world, so it is
matched against what that person owns and what they are carrying, and against
nothing else. When the claim fails the answer is a refusal that names the
owner -- "you see no sword here" being a lie when there are three on the floor
and none of them is hers.
"""

from django.test import tag
from evennia import create_object

from tests.base import GameTest
from world import bulk, nounphrase, ownership, verbs


def _read(phrase):
    return nounphrase.read(phrase)


@tag("world")
class Whose(GameTest):
    """Who a possessive says the thing belongs to."""

    characters = 2

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.char2.location = self.room1
        self.char2.key = "Jessica"
        self.char2.db.pronouns = "she"

    def person(self, phrase):
        read = _read(phrase)
        return ownership.person_meant(self.char1, read.possessor,
                                      read.possessor_words)

    def test_my_is_whoever_is_speaking(self):
        person, asked = self.person("my ball")
        self.assertIs(person, self.char1)
        self.assertIsNone(asked)

    def test_her_is_whoever_here_goes_by_her(self):
        person, _asked = self.person("her sword")
        self.assertIs(person, self.char2)

    def test_and_a_name_is_looked_up(self):
        person, _asked = self.person("Jessica's sword")
        self.assertIs(person, self.char2)

    def test_but_his_is_not_her(self):
        """
        A pronoun set is what somebody goes by, and "his" is not what Jessica
        goes by. The old rule -- the only other person present -- answered
        this wrongly and had no way not to.
        """
        third = create_object("typeclasses.characters.Character",
                              key="Britney", location=self.room1)
        third.db.pronouns = "she"
        person, _asked = self.person("his sword")
        self.assertIsNone(person)

    def test_several_of_them_is_asked_rather_than_guessed(self):
        britney = create_object("typeclasses.characters.Character",
                                key="Britney", location=self.room1)
        britney.db.pronouns = "she"
        person, asked = self.person("her sword")
        self.assertIsNone(person)
        self.assertIn("Jessica", asked)
        self.assertIn("Britney", asked)

    def test_unless_one_of_them_was_just_referred_to(self):
        from world import referents

        britney = create_object("typeclasses.characters.Character",
                                key="Britney", location=self.room1)
        britney.db.pronouns = "she"
        referents.note(self.char1, britney, self.room1)
        person, asked = self.person("her sword")
        self.assertIs(person, britney)
        self.assertIsNone(asked)

    def test_and_a_world_that_never_said_still_works(self):
        """
        The fallback that was the whole rule before pronoun sets existed: one
        other person present, so they are who was meant. Kept, because a world
        whose characters were never asked must go on behaving as it did.
        """
        self.char2.attributes.remove("pronouns")
        person, _asked = self.person("her sword")
        self.assertIs(person, self.char2)


@tag("world")
class Binding(GameTest):
    """What "her sword" binds to, and what it refuses to bind to."""

    characters = 2
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.char2.location = self.room1
        self.char2.key = "Jessica"
        self.char2.db.pronouns = "she"
        self.sword = self.obj1
        self.sword.key = "sword"
        self.sword.location = self.room1

    def test_a_thing_of_hers_lying_here(self):
        ownership.set_owner(self.sword, self.char2)
        self.assertIs(verbs.bind(self.char1, "her sword"), self.sword)

    def test_and_one_she_is_merely_carrying(self):
        """
        Ownership is the stronger claim and is asked first, but a sword she is
        holding and has never been given is still the sword she means.
        """
        self.sword.location = self.char2
        self.assertIs(verbs.bind(self.char1, "her sword"), self.sword)

    def test_owning_it_beats_holding_it(self):
        hers = self.sword
        ownership.set_owner(hers, self.char2)
        borrowed = create_object(key="sword", location=self.char2)
        ownership.set_owner(borrowed, self.char1)
        self.assertIs(verbs.bind(self.char1, "her sword"), hers)

    def test_my_means_mine_and_not_merely_a_ball(self):
        """
        "My" used to be noise, so "my ball" was "the ball" -- and found one
        lying on the floor that was never yours.
        """
        ball = create_object(key="ball", location=self.room1)
        self.assertIsNone(verbs.bind(self.char1, "my ball"))
        ownership.set_owner(ball, self.char1)
        self.assertIs(verbs.bind(self.char1, "my ball"), ball)

    def test_somebody_elses_sword_is_not_hers(self):
        ownership.set_owner(self.sword, self.char1)
        self.assertIsNone(verbs.bind(self.char1, "her sword"))

    def test_and_nothing_is_conjured_to_satisfy_the_claim(self):
        """
        The failure this exists to stop. A stated possessive that finds
        nothing is refused; inventing a sword to satisfy it puts a second
        sword in the room indistinguishable from the one she really has.
        """
        from world import naming

        obj, complaint = naming.instead_of_creating(self.char1, "her sword")
        self.assertIsNone(obj)
        self.assertTrue(complaint)

    def test_counting_counts_among_hers(self):
        first = self.sword
        first.location = self.char2
        second = create_object(key="sword", location=self.char2)
        self.assertIs(verbs.bind(self.char1, "her second sword"), second)

    def test_a_part_of_her_is_her_and_not_what_she_carries(self):
        """
        "Her hand" is Jessica, not the hand mirror in her bag -- which
        resembles "hand" quite enough to be picked up instead of her being
        touched.
        """
        create_object(key="hand mirror", location=self.char2)
        self.assertIsNone(verbs.bind(self.char1, "her hand"))
        from world import naming

        obj, complaint = naming.instead_of_creating(self.char1, "her hand")
        self.assertIs(obj, self.char2)
        self.assertIsNone(complaint)

    def test_a_name_with_an_apostrophe_in_it_is_still_a_name(self):
        """
        Worlds call things "Captain's Log" and "Baker's Rack", and an
        apostrophe is an apostrophe whether it is grammar or spelling. Read as
        a claim about a captain it finds nothing and is refused, which would
        make a shelf of ordinary objects unnameable.
        """
        log = create_object(key="Captain's Log", location=self.room1)
        self.assertIs(verbs.bind(self.char1, "captain's log"), log)

    def test_but_a_pronoun_never_falls_back_to_a_name(self):
        """
        The half that must not be symmetrical. "My ball" scores 0.9 against a
        Leather Ball on somebody else's shelf, which is the answer this whole
        phase exists to stop.
        """
        create_object(key="Leather Ball", location=self.room1)
        self.assertIsNone(verbs.bind(self.char1, "my ball"))

    def test_the_question_reaches_whoever_typed_it(self):
        britney = create_object("typeclasses.characters.Character",
                                key="Britney", location=self.room1)
        britney.db.pronouns = "she"
        _bound, _unbound, questions = verbs.bind_all(
            self.char1, {"direct": "her sword"}, verb="get")
        self.assertTrue(questions)
        self.assertIn("Which her", questions[0][1])


@tag("world")
class TheRefusal(GameTest):
    """It names the owner, in the words the claim was made in."""

    characters = 2
    second_room = True

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.char2.location = self.room1
        self.char2.key = "Jessica"
        self.char2.db.pronouns = "she"

    def said(self, phrase):
        from world import anatomy

        _obj, complaint = anatomy.instead_of_a_part(self.char1, phrase)
        return complaint or ""

    def test_of_hers_when_a_pronoun_was_used(self):
        self.assertEqual(self.said("her sword"),
                         "You see no sword of hers here.")

    def test_of_yours_when_you_claimed_it(self):
        self.assertEqual(self.said("my sword"),
                         "You see no sword of yours here.")

    def test_and_by_name_when_a_name_was_used(self):
        self.assertEqual(self.said("Jessica's sword"),
                         "You see no sword of Jessica's here.")

    def test_an_owner_who_is_not_here_is_said_so(self):
        self.assertIn("Britney", self.said("Britney's sword"))

    def test_and_a_pronoun_meaning_nobody_asks_whose(self):
        self.char2.location = self.room2
        self.assertEqual(self.said("her sword"), "Whose sword do you mean?")


@tag("world")
class PartsAndPossessions(GameTest):
    """
    Which reading "her X" gets, and why the test for it had to be tightened.

    The commonsense corpus was being asked whether a word names part of
    something, and it answers yes for a sword -- true of a scabbard, and worth
    nothing here. Nothing noticed while the only consequence was that "touch
    her sword" resolved to her; once a possessive could be matched against
    what she owns, it meant the sword was never looked at.
    """

    def test_a_sword_is_not_part_of_anybody(self):
        from world import anatomy

        self.assertFalse(anatomy.is_part("sword"))
        self.assertFalse(anatomy.is_part("wrench"))

    def test_but_a_thorax_still_is(self):
        """The dictionary answers for every creature somebody invents."""
        from world import anatomy

        self.assertNotIn("thorax", anatomy.PARTS)
        self.assertTrue(anatomy.is_part("thorax"))
        self.assertTrue(anatomy.is_part("proboscis"))

    def test_and_the_narrow_test_is_the_list_and_nothing_else(self):
        """
        What `ownership.whose` gates on, where being sure matters more than
        being wide: a false positive there picks up the hand mirror.
        """
        from world import anatomy

        self.assertTrue(anatomy.is_listed_part("hand"))
        self.assertFalse(anatomy.is_listed_part("thorax"))
        self.assertFalse(anatomy.is_listed_part("severed hand"))


@tag("world")
class InBulk(GameTest):
    """"Get all of her machines" is not "get all the machines"."""

    characters = 2
    loose_objects = 2
    second_room = True

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.char2.location = self.room1
        self.char2.key = "Jessica"
        self.char2.db.pronouns = "she"
        self.hers = self.obj1
        self.hers.key = "machine"
        self.hers.location = self.room1
        ownership.set_owner(self.hers, self.char2)
        self.mine = self.obj2
        self.mine.key = "machine"
        self.mine.location = self.room1
        ownership.set_owner(self.mine, self.char1)

    def test_only_hers(self):
        found = bulk.matching(self.char1, "get", "all of her machines")
        self.assertEqual(found, [self.hers])

    def test_and_only_mine(self):
        found = bulk.matching(self.char1, "get", "all my machines")
        self.assertEqual(found, [self.mine])

    def test_a_claim_about_nobody_finds_nothing(self):
        """
        Rather than everything. Sweeping the room because one person's things
        could not be found is the one answer worse than refusing.
        """
        self.char2.location = self.room2
        self.assertEqual(bulk.matching(self.char1, "get", "all of her machines"),
                         [])

    def test_saying_nothing_about_whose_narrows_nothing(self):
        found = bulk.matching(self.char1, "get", "all machines")
        self.assertEqual(sorted(found, key=lambda o: o.id),
                         sorted([self.hers, self.mine], key=lambda o: o.id))

    def test_the_expansion_carries_the_narrowing(self):
        spread = bulk.expand(self.char1, "get", {"direct": "all of her machines"})
        self.assertEqual([obj for obj, _command in spread], [self.hers])
