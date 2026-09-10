"""
What a world has been asked to do, and how it answered.

Six integers per question, not a transcript. The case they exist for is the one
the whole design was argued from: `launch` typed aboard a ship with nothing
named, eleven times, answered "launch what?" eleven times, with nothing anywhere
remembering that it had been said. A count against `(launch,
enclosure:spacecraft.n.01, no_object)` turns that into the best-evidenced
proposal a world can make.

The tests that matter most are in `EveryWayOutIsCounted`. A counter that misses
an exit does not fail loudly -- it quietly makes one kind of ending look rarer
than it is, and a suggester weighs its proposals by exactly that ratio.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeAccount, as_json, immediately, replying
from world import attempt as attempt_mod
from world import actions, counters, kinds, rulebooks as R
from world import standard_rules, verbs


@tag("unit")
class ReadingAKey(SimpleTestCase):

    def test_a_key_splits_back_into_its_three_parts(self):
        self.assertEqual(counters.split("launch|kind:datapad|refused"),
                         ("launch", "kind:datapad", "refused"))

    def test_a_short_key_still_splits(self):
        self.assertEqual(counters.split("launch"), ("launch", "", ""))
        self.assertEqual(counters.split(""), ("", "", ""))

    def test_the_kind_can_be_read_out_of_either_sort_of_token(self):
        self.assertEqual(counters.kind_in("kind:datapad"), "datapad")
        self.assertEqual(counters.kind_in("enclosure:spacecraft.n.01"),
                         "spacecraft.n.01")
        self.assertEqual(counters.kind_in("nothing"), "")

    def test_and_a_place_is_told_from_a_thing(self):
        self.assertTrue(counters.is_enclosure("enclosure:spacecraft.n.01"))
        self.assertFalse(counters.is_enclosure("kind:datapad"))


@tag("world")
class Counting(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.char1.move_to(self.room2, quiet=True)
        self.pad = self.obj1
        self.pad.key = "Datapad"
        self.pad.db.kinds = ["datapad"]
        self.pad.move_to(self.room2, quiet=True)


@tag("world")
class WhatAQuestionIs(Counting):
    """
    The token is the question, not the sentence. Two datapads in two rooms a
    week apart add up to two, which is what makes a count evidence about
    datapads rather than about one object.
    """

    def test_a_named_thing_gives_its_kind(self):
        self.assertEqual(
            counters.scope_of({"direct": self.pad}, self.char1, self.root),
            "kind:datapad")

    def test_nothing_named_gives_the_sort_of_place_you_are_in(self):
        self.assertEqual(counters.scope_of({}, self.char1, self.root),
                         "enclosure:spacecraft.n.01")

    def test_a_second_object_of_the_same_kind_is_the_same_question(self):
        other = self.obj2
        other.db.kinds = ["datapad"]
        other.move_to(self.room1, quiet=True)
        self.assertEqual(
            counters.scope_of({"direct": other}, self.char1, self.root),
            counters.scope_of({"direct": self.pad}, self.char1, self.root))

    def test_a_thing_with_no_kind_is_still_a_question(self):
        self.pad.db.kinds = []
        self.assertEqual(
            counters.scope_of({"direct": self.pad}, self.char1, self.root),
            "kind:")

    def test_and_an_attempt_nowhere_is_answered_rather_than_crashing(self):
        self.assertEqual(counters.scope_of({}, None, self.root),
                         counters.NOTHING)

    def test_the_kind_is_the_grounded_one(self):
        """
        Which matters for adding up. `kinds.prune` grounds a bare word to its
        synset, so a thing called a tablet and a thing called a `tablet.n.01`
        are one question and their counts are one count. Evidence that split
        itself across two spellings of the same kind would under-count exactly
        the thing a suggester is looking for.
        """
        slate = self.obj2
        slate.db.kinds = ["tablet"]
        self.assertEqual(
            counters.scope_of({"direct": slate}, self.char1, self.root),
            "kind:tablet.n.01")

    def test_a_role_other_than_direct_still_names_the_thing(self):
        self.assertEqual(
            counters.scope_of({"instrument": self.pad}, self.char1, self.root),
            "kind:datapad")


@tag("world")
class Storing(Counting):

    def test_a_count_goes_up(self):
        counters.note(self.root, "launch", {}, self.char1, counters.NO_OBJECT)
        counters.note(self.root, "launch", {}, self.char1, counters.NO_OBJECT)
        self.assertEqual(
            counters.count(self.root, "launch", "enclosure:spacecraft.n.01",
                           counters.NO_OBJECT), 2)

    def test_a_last_seen_is_kept(self):
        counters.note(self.root, "launch", {}, self.char1, counters.NO_OBJECT)
        self.assertGreater(
            counters.last_seen(self.root, "launch",
                               "enclosure:spacecraft.n.01",
                               counters.NO_OBJECT), 0)

    def test_different_outcomes_are_different_questions(self):
        counters.note(self.root, "power", {"direct": self.pad}, self.char1,
                      counters.DONE)
        counters.note(self.root, "power", {"direct": self.pad}, self.char1,
                      counters.REFUSED)
        self.assertEqual(counters.count(self.root, "power", "kind:datapad",
                                       counters.DONE), 1)
        self.assertEqual(counters.count(self.root, "power", "kind:datapad",
                                        counters.REFUSED), 1)

    def test_an_outcome_nobody_defined_is_not_recorded(self):
        self.assertEqual(
            counters.note(self.root, "power", {}, self.char1, "sideways"), 0)
        self.assertEqual(counters.all_counts(self.root), {})

    def test_and_neither_is_a_verb_that_is_not_one(self):
        self.assertEqual(
            counters.note(self.root, "", {}, self.char1, counters.DONE), 0)

    def test_a_world_that_is_not_one_is_no_error(self):
        self.assertEqual(
            counters.note(None, "power", {}, self.char1, counters.DONE), 0)
        self.assertEqual(counters.all_counts(None), {})

    def test_the_store_is_capped(self):
        """A suggester that can grow without bound is a second drift problem."""
        store = {f"verb{n}|kind:x|refused": {"count": 1, "last": n}
                 for n in range(counters.MAX_KEYS + 50)}
        self.root.db.attempt_counts = store
        counters.note(self.root, "power", {"direct": self.pad}, self.char1,
                      counters.DONE)
        self.assertLessEqual(len(counters.all_counts(self.root)),
                             counters.MAX_KEYS)

    def test_and_it_evicts_the_least_recently_asked(self):
        self.root.db.attempt_counts = {
            f"verb{n}|kind:x|refused": {"count": 1, "last": n}
            for n in range(counters.MAX_KEYS + 10)}
        counters.note(self.root, "power", {"direct": self.pad}, self.char1,
                      counters.DONE)
        kept = counters.all_counts(self.root)
        self.assertNotIn("verb0|kind:x|refused", kept)
        self.assertIn(f"verb{counters.MAX_KEYS + 9}|kind:x|refused", kept)


@tag("world")
class WhatASuggesterReads(Counting):

    def test_refusals_come_back_worst_first(self):
        for _ in range(3):
            counters.note(self.root, "launch", {}, self.char1,
                          counters.NO_OBJECT)
        counters.note(self.root, "power", {"direct": self.pad}, self.char1,
                      counters.REFUSED)
        rows = counters.refusals(self.root)
        self.assertEqual([r["action"] for r in rows], ["launch", "power"])
        self.assertEqual(rows[0]["count"], 3)

    def test_successes_are_not_refusals(self):
        counters.note(self.root, "power", {"direct": self.pad}, self.char1,
                      counters.DONE)
        self.assertEqual(counters.refusals(self.root), [])

    def test_one_kind_of_refusal_can_be_asked_for(self):
        counters.note(self.root, "launch", {}, self.char1, counters.NO_OBJECT)
        counters.note(self.root, "power", {"direct": self.pad}, self.char1,
                      counters.REFUSED)
        rows = counters.refusals(self.root, outcome=counters.NO_OBJECT)
        self.assertEqual([r["action"] for r in rows], ["launch"])

    def test_a_threshold_keeps_one_offs_out(self):
        counters.note(self.root, "launch", {}, self.char1, counters.NO_OBJECT)
        self.assertEqual(counters.refusals(self.root, least=2), [])

    def test_the_report_reads_as_prose(self):
        counters.note(self.root, "launch", {}, self.char1, counters.NO_OBJECT)
        counters.note(self.root, "power", {"direct": self.pad}, self.char1,
                      counters.DONE)
        said = counters.report(self.root)
        self.assertIn("launch", said)
        self.assertIn("spacecraft.n.01", said)
        self.assertIn("2 attempts", said)

    def test_and_says_so_when_there_is_nothing_to_say(self):
        self.assertIn("Nothing has been attempted", counters.report(self.root))


@tag("world")
class EveryWayOutIsCounted(Counting):
    """
    A missed exit does not fail loudly. It makes one kind of ending look rarer
    than it is, and a suggester weighs its proposals by exactly that ratio --
    so each way out of the pipeline is asserted separately.
    """

    def setUp(self):
        super().setUp()
        standard_rules.seed(self.root)
        actions.declare(self.root, "power",
                        [{"role": "direct", "optional": False}])
        kinds.admit(self.root, ["datapad"], "power", True)
        R.add(self.root, R.blank(
            action="power", phase=R.CARRY_OUT, scope={"kind": "datapad"},
            about="direct", name="powering a datapad wakes it",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["powered"]}]))

    def try_it(self, raw, *replies):
        said = []
        answers = replies or (as_json({"actor": "Done.",
                                       "room": "{actor} does it."}),)
        with immediately(), replying(*answers):
            attempt_mod.attempt(
                self.char1, raw, FakeAccount(),
                on_message=lambda a, r=None: said.append(a or ""))
        return " ".join(s for s in said if s)

    def counted(self, outcome, scope=None):
        return counters.count(self.root, "power",
                              scope or "kind:datapad", outcome)

    def test_a_verb_that_works_is_counted_done(self):
        self.try_it("power datapad")
        self.assertIn("powered", verbs.states(self.pad))
        self.assertEqual(self.counted(counters.DONE), 1)

    def test_and_again_from_the_narration_cache(self):
        """The commonest kind of working verb there is."""
        self.try_it("power datapad")
        self.try_it("power datapad")
        self.assertEqual(self.counted(counters.DONE), 2)

    def test_a_required_role_nobody_named_is_counted(self):
        said = self.try_it("power")
        self.assertIn("what", said.lower())
        self.assertEqual(
            self.counted(counters.NO_OBJECT, "enclosure:spacecraft.n.01"), 1)

    def test_a_refusal_by_a_check_rule_is_counted(self):
        R.add(self.root, R.blank(
            action="power", phase=R.CHECK, scope={"kind": "datapad"},
            about="direct", name="a cracked datapad will not wake",
            conditions=[{"subject": "direct", "lacks": ["cracked"]}]))
        verbs.apply_states(self.pad, add=["cracked"], world_root=self.root)
        self.try_it("power datapad")
        self.assertEqual(self.counted(counters.REFUSED), 1)
        self.assertEqual(self.counted(counters.DONE), 0)

    def test_a_kind_that_does_not_admit_the_verb_is_counted(self):
        """
        A different kind, because `kinds.admit` is first-answer-wins: the setUp
        has already settled that a datapad can be powered, and settling it again
        the other way is correctly a no-op.
        """
        slate = self.obj2
        slate.key = "Slate"
        slate.db.kinds = ["tablet"]
        slate.move_to(self.room2, quiet=True)
        kinds.admit(self.root, ["tablet"], "power", False)
        self.try_it("power slate")
        self.assertEqual(
            counters.count(self.root, "power", "kind:tablet.n.01",
                           counters.NOT_ADMITTED), 1)

    def test_an_instead_rule_that_replaces_the_action_is_counted_done(self):
        R.add(self.root, R.blank(
            action="power", phase=R.INSTEAD, scope={"kind": "datapad"},
            about="direct", name="The screen stays dark."))
        self.try_it("power datapad")
        self.assertEqual(self.counted(counters.DONE), 1)

    def test_the_ratio_is_what_a_suggester_weighs(self):
        """Both halves of it, in one world, from real attempts."""
        self.try_it("power datapad")
        self.try_it("power")
        self.try_it("power")
        rows = counters.refusals(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 2)
        self.assertEqual(rows[0]["outcome"], counters.NO_OBJECT)
        self.assertEqual(self.counted(counters.DONE), 1)
