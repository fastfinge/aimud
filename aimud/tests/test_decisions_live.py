"""
The decision model, against the real service.

`test_llm.DecidingSomething` asserts the request this game builds and the
reply it can read, both against a fake. That is the half worth having in the
free suite, and it is also the half that cannot tell you the endpoint exists.

The Decisions API is **alpha**, and everything here was written from its
documentation rather than from a reply anybody had seen. These tests are how
the two are compared: that the path is right, that `noul` comes back under the
name it was asked under, that `usage` carries the shape `ledger` reads, and
that the answers to the two questions `item_gen` actually asks fall on the
sides of `decisions`' thresholds that the game assumes they do.

That last one is a calibration check, not a logic check. It is allowed to fail
when a release moves the numbers -- which is exactly what it is for, and why
`decisions.JEV` is pinned.
"""

from django.test import SimpleTestCase, tag

from tests import live
from world import decisions, llm

#: A room the answers should be obvious about, in both directions.
CELLAR = {"world_and_room": "World: a damp medieval cellar under an inn.\n\n"
                            "Room:\n[Cellar]\nBarrels line the walls.",
          "thing_asked_for": ""}

#: And one where the line between a thing and what it shows is the question:
#: the starship bridge an NPC filled with signals, settings and readouts.
BRIDGE = {"world_and_room": "World: a Korean-built deep-space survey ship.\n\n"
                            "Room:\n[The Bridge]\nTwo worn crash couches sit "
                            "bolted to the deck, wrapped in instrumentation "
                            "and status monitors. A curve of screens shows "
                            "the forward sensor arrays and deep space.",
          "thing_asked_for": ""}


@tag("llm")
class AskingTheRealThing(SimpleTestCase):

    def setUp(self):
        self.sponsor = live.live_sponsor(self)

    def decide(self, thing, **questions):
        state = dict(CELLAR, thing_asked_for=thing)
        return llm.decide(self.sponsor, decisions.JEV, state, questions)

    def existence(self, thing, hosts=(), room=None):
        """
        The questions `item_gen.validate_object_existence` asks, in its own
        words: asked through `existence_questions`, so a change to them is a
        change measured here.
        """
        from world import item_gen

        state = dict(room or CELLAR, thing_asked_for=thing)
        return llm.decide(self.sponsor, decisions.JEV, state,
                          item_gen.existence_questions(thing, hosts))

    # -- the contract ----------------------------------------------------

    def test_a_noul_comes_back_under_the_name_it_was_asked_under(self):
        answers = self.existence("an old lantern")
        self.assertEqual(sorted(answers),
                         ["could_exist", "is_body_part", "is_intangible"])
        for name, answer in answers.items():
            self.assertEqual(answer["type"], "noul", name)
            self.assertIsInstance(answer["noul"], (int, float), name)
            self.assertTrue(0.0 <= answer["noul"] <= 1.0, answer)

    def test_the_reader_this_game_uses_reads_it(self):
        answers = self.existence("an old lantern")
        self.assertGreater(decisions.certainty(answers, "could_exist"), 0.0)
        self.assertEqual(decisions.certainty(answers, "not_asked"), 0.0)

    def test_what_it_cost_arrives_in_a_shape_the_ledger_counts(self):
        """
        `input_tokens` where a chat reply says `prompt_tokens`. `ledger` reads
        both already -- this is the test that it is in fact both, and that a
        decision is not being recorded as free.
        """
        from world import ledger

        while not llm._spending.empty():
            llm._spending.get_nowait()
        self.existence("an old lantern")
        _sponsor, _model, usage, _seconds = llm._spending.get_nowait()
        self.assertGreater(ledger._count(usage or {}, ledger._PROMPT), 0)

    # -- the calibration -------------------------------------------------

    def test_something_ordinary_is_allowed(self):
        answers = self.existence("an old lantern")
        self.assertGreaterEqual(
            decisions.certainty(answers, "could_exist"),
            decisions.ALLOW_EXISTENCE)

    def test_a_clear_impossibility_is_refused(self):
        answers = self.existence("a fusion reactor")
        self.assertLess(decisions.certainty(answers, "could_exist"),
                        decisions.ALLOW_EXISTENCE)

    def test_part_of_a_body_is_recognised_as_one(self):
        answers = self.existence("a shoulder")
        self.assertGreaterEqual(
            decisions.certainty(answers, "is_body_part"),
            decisions.DENY_BODY_PART)

    def test_and_is_caught_by_that_question_rather_than_the_first(self):
        """
        Why there are two questions and not one. A shoulder in a cellar is
        *plausible* -- it clears `ALLOW_EXISTENCE` easily -- so nothing in the
        existence answer would stop it being built and left on the floor. If
        this ever fails, the second question has stopped being load-bearing
        and somebody should find out why before removing it.
        """
        answers = self.existence("a shoulder")
        self.assertGreaterEqual(
            decisions.certainty(answers, "could_exist"),
            decisions.ALLOW_EXISTENCE)

    def test_a_part_cut_free_is_not(self):
        """The carve-out the old prompt had to argue for in a paragraph."""
        answers = self.existence("a severed hand")
        self.assertLess(decisions.certainty(answers, "is_body_part"),
                        decisions.DENY_BODY_PART)

    # -- what a bridge full of things taught it --------------------------
    #
    # Every phrase here is one an NPC conjured into a real room. `measure`
    # prints the numbers, which is how `PART_OF_HOST` and `DENY_INTANGIBLE`
    # were chosen: run with `-v 2` and read them.

    def measure(self, thing, hosts=(), room=None):
        answers = self.existence(thing, hosts, room=room or BRIDGE)
        print(f"\n  {thing!r}: " + ", ".join(
            f"{name}={decisions.certainty(answers, name):.2f}"
            for name in sorted(answers)))
        return answers

    def test_a_signal_has_no_body(self):
        for thing in ("a slow pulse", "a telemetry signal",
                      "the beacon source direction"):
            answers = self.measure(thing)
            self.assertGreaterEqual(
                decisions.certainty(answers, "is_intangible"),
                decisions.DENY_INTANGIBLE, thing)

    def test_a_fixture_has_one(self):
        for thing in ("an amber diagnostic switch", "a status monitor",
                      "a crash couch"):
            answers = self.measure(thing)
            self.assertLess(decisions.certainty(answers, "is_intangible"),
                            decisions.DENY_INTANGIBLE, thing)

    def test_a_readout_is_part_of_its_computer(self):
        answers = self.measure("a main bridge computer readout",
                               ["Main Bridge Computer", "Hyundai Crash Couch"])
        self.assertGreaterEqual(decisions.certainty(answers, "part_of_0"),
                                decisions.PART_OF_HOST)
        self.assertLess(decisions.certainty(answers, "part_of_1"),
                        decisions.PART_OF_HOST)

    def test_a_menu_on_a_screen_is_never_made(self):
        """
        Either its screen's or not a thing; which one is the model's to say,
        and it says the second (see `decisions.PART_OF_HOST`). What must hold
        is that one of them catches it.
        """
        answers = self.measure("a system menu", ["LG Status Monitor"])
        self.assertTrue(
            decisions.certainty(answers, "part_of_0") >= decisions.PART_OF_HOST
            or decisions.certainty(answers, "is_intangible")
            >= decisions.DENY_INTANGIBLE, answers)

    def test_a_chart_is_a_thing(self):
        """The nearest ordinary thing came to being refused as no thing."""
        answers = self.measure("a star chart")
        self.assertLess(decisions.certainty(answers, "is_intangible"),
                        decisions.DENY_INTANGIBLE)

    def test_sitting_on_something_is_not_being_part_of_it(self):
        for thing, host, room in (
                ("a chipped mug", "Oak Table", CELLAR),
                ("a coffee cup", "Main Bridge Computer", BRIDGE),
                ("a star chart", "LG Status Monitor", BRIDGE),
                ("a diagnostic tool", "Hyundai Crash Couch", BRIDGE)):
            answers = self.measure(thing, [host], room=room)
            self.assertLess(decisions.certainty(answers, "part_of_0"),
                            decisions.PART_OF_HOST, thing)

    def test_a_fixed_feature_cannot_be_picked_up(self):
        answers = self.decide(
            "the stone wall",
            takeable=decisions.noul(
                "Can the player pick up 'the stone wall'?",
                "A portable item -- a weapon, a tool, a book, a loose object.",
                "A fixed feature -- a wall, a door, the floor, or built-in or "
                "very heavy furniture."))
        self.assertLess(decisions.certainty(answers, "takeable"),
                        decisions.ALLOW_TAKEABLE)
