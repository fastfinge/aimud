"""
The consistency scan: each finder on its own, then the whole corpus.

Two kinds of test here, and the plan's §3, 0.6 turns on the difference.

The synthetic ones build a five-line world and assert exactly what one finder
does with it. They are about the code and they will outlive any corpus.

The corpus ones read the 326 exported rules and assert *properties* -- that
every rule can be read, that the scan is deterministic, that a report renders --
plus one ratchet against the recorded baselines, which asserts a direction of
travel rather than an equality. When the rulebook change lands and the numbers
improve, the ratchet stays green and `baselines.json` gets rewritten. Nothing
here has to be edited for that, which is the whole reason it is written this way.
"""

import json

from django.test import SimpleTestCase, tag

from tests.support import FIXTURES, worlds
from world import rulecheck


def world(rules=None, vocabulary=None, groups=None, filed=None):
    """A world's registers, small enough to reason about."""
    return {
        "verb_rules": rules or {},
        "rules": filed or {},
        "state_vocabulary": vocabulary or {},
        "state_groups": groups or {},
        "kind_specs": {},
    }


def filed(action="power", phase="carry_out", conditions=None, effects=None,
          listed=True, contest=None):
    """One rulebook rule, in the shape `rulebooks.blank` makes."""
    return {"action": action, "phase": phase, "scope": {"world": True},
            "conditions": list(conditions or []),
            "effects": list(effects or []),
            "contest": contest, "listed": listed}


def sets(*states):
    return [{"type": "set_state", "role": "direct", "add": list(states)}]


def unsets(*states):
    return [{"type": "set_state", "role": "direct", "remove": list(states)}]


def rule(adds=(), removes=(), needs=(), lacks=(), valid=True, reason="",
         effects=None, check=None):
    """One rule in the shape the corpus stores them in."""
    body = {"valid": valid, "reason": reason}
    if check:
        body["check"] = check
    if effects is not None:
        body["effects"] = effects
    else:
        body["effects"] = [{"type": "set_state", "role": "direct",
                            "add": list(adds), "remove": list(removes)}] \
            if (adds or removes) else []
    if needs or lacks:
        body["requires"] = {"direct": {"is": list(needs), "lacks": list(lacks)}}
    return body


@tag("unit")
class OneFinderAtATime(SimpleTestCase):

    def test_a_state_set_and_never_unset_is_one_way(self):
        found = rulecheck.scan(world({
            "light": rule(adds=["lit"]),
            "wet": rule(adds=["wet"], removes=["dry"]),
        }))
        self.assertEqual(found["one_way"], ["lit", "wet"])

    def test_a_state_some_rule_can_unset_is_not_one_way(self):
        found = rulecheck.scan(world({
            "light": rule(adds=["lit"]),
            "douse": rule(adds=["unlit"], removes=["lit"]),
        }))
        self.assertNotIn("lit", found["one_way"])

    def test_a_state_required_and_never_settable_is_unsettable(self):
        found = rulecheck.scan(world({
            "read": rule(needs=["open"], adds=["read"]),
        }))
        self.assertEqual(found["unsettable"], ["open"])

    def test_a_state_something_can_set_is_not_unsettable(self):
        found = rulecheck.scan(world({
            "open": rule(adds=["open"]),
            "read": rule(needs=["open"], adds=["read"]),
        }))
        self.assertEqual(found["unsettable"], [])

    def test_a_word_no_rule_touches_is_dead_vocabulary(self):
        found = rulecheck.scan(world(
            {"light": rule(adds=["lit"])},
            vocabulary={"lit": {}, "dusty": {}, "damp": {}},
        ))
        self.assertEqual(found["dead_vocabulary"], ["damp", "dusty"])

    def test_a_word_only_ever_forbidden_still_counts_as_used(self):
        """`lacks` is a use. A rule refuses to fire on it, so somebody meant it."""
        found = rulecheck.scan(world(
            {"light": rule(adds=["lit"], lacks=["broken"])},
            vocabulary={"lit": {}, "broken": {}},
        ))
        self.assertEqual(found["dead_vocabulary"], [])

    def test_the_two_halves_of_one_missing_rule_are_paired(self):
        found = rulecheck.scan(world(
            {"open": rule(adds=["open"]),
             "read": rule(needs=["closed"], adds=["read"])},
            vocabulary={"open": {"group": "openness"},
                        "closed": {"group": "openness"}},
            groups={"openness": {"exclusive": True}},
        ))
        self.assertEqual(found["pairs"], [("open", "closed", "openness")])

    def test_states_in_different_groups_are_not_a_pair(self):
        found = rulecheck.scan(world(
            {"open": rule(adds=["open"]),
             "read": rule(needs=["dry"], adds=["read"])},
            vocabulary={"open": {"group": "openness"},
                        "dry": {"group": "wetness"}},
            groups={"openness": {"exclusive": True},
                    "wetness": {"exclusive": True}},
        ))
        self.assertEqual(found["pairs"], [])

    def test_a_group_that_is_not_exclusive_is_not_a_pair(self):
        found = rulecheck.scan(world(
            {"open": rule(adds=["open"]),
             "read": rule(needs=["closed"], adds=["read"])},
            vocabulary={"open": {"group": "flags"},
                        "closed": {"group": "flags"}},
            groups={"flags": {"exclusive": False}},
        ))
        self.assertEqual(found["pairs"], [])

    def test_a_rule_with_no_effects_is_inert(self):
        found = rulecheck.scan(world({
            "smell": rule(),
            "light": rule(adds=["lit"]),
        }))
        self.assertEqual(found["inert"], ["smell"])

    def test_a_contested_rule_keeps_its_effects_by_outcome(self):
        """
        The trap this finder had to avoid.

        A rule with a check stores effects keyed by outcome, so reading only
        the list form would call every contested rule inert -- and those are
        the rules that change the most.
        """
        found = rulecheck.scan(world({
            "force": rule(
                check={"trait": "strength", "difficulty": 12},
                effects={"success": [{"type": "set_state", "role": "direct",
                                      "add": ["open"]}],
                         "failure": [{"type": "set_trait", "role": "actor",
                                      "trait": "stamina", "change": -5}]}),
        }))
        self.assertEqual(found["inert"], [])
        self.assertEqual(found["one_way"], ["open"])
        self.assertEqual(found["counts"]["contested"], 1)

    def test_refusals_are_sorted_by_what_they_say(self):
        found = rulecheck.scan(world({
            "get": rule(valid=False, reason="The engine already handles this."),
            "fill": rule(valid=False,
                         reason="Only makes sense in specific locations."),
            "smooth": rule(valid=False,
                           reason="A lamppost cannot be smoothed."),
        }))
        engine, place, silly = rulecheck.REFUSAL_KINDS
        self.assertEqual(found["refusals"][engine], ["get"])
        self.assertEqual(found["refusals"][place], ["fill"])
        self.assertEqual(found["refusals"][silly], ["smooth"])
        self.assertEqual(found["counts"]["refused"], 3)
        self.assertEqual(found["counts"]["accepted"], 0)

    def test_a_verb_whose_rules_disagree_is_forked(self):
        found = rulecheck.scan(world({
            "wash#a": rule(adds=["clean"]),
            "wash#b": rule(adds=["clean"], removes=["dirty"]),
            "read#a": rule(adds=["read"]),
        }))
        self.assertEqual(found["forked"], [("wash", 2, 2)])

    def test_a_verb_whose_rules_agree_is_not_forked(self):
        found = rulecheck.scan(world({
            "wash#a": rule(adds=["clean"]),
            "wash#b": rule(adds=["clean"]),
        }))
        self.assertEqual(found["forked"], [])

    def test_a_world_with_nothing_wrong_says_so(self):
        found = rulecheck.scan(world(
            {"light": rule(adds=["lit"], removes=["unlit"]),
             "douse": rule(adds=["unlit"], removes=["lit"])},
            vocabulary={"lit": {"group": "fire"}, "unlit": {"group": "fire"}},
            groups={"fire": {"exclusive": True}},
        ))
        for finding in ("one_way", "unsettable", "dead_vocabulary", "pairs",
                        "inert", "forked"):
            self.assertEqual(found[finding], [], finding)
        self.assertIn("Nothing amiss", rulecheck.report(found))

    def test_an_empty_world_scans_without_complaint(self):
        found = rulecheck.scan(world())
        self.assertEqual(found["counts"]["rules"], 0)
        self.assertIn("Nothing amiss", rulecheck.report(found))


@tag("unit")
class OverTheWholeCorpus(SimpleTestCase):
    """326 real rules, seven worlds, and nothing invented for the occasion."""

    def test_every_world_scans(self):
        for label, record in worlds().items():
            found = rulecheck.scan(rulecheck.of_record(record))
            self.assertIn("counts", found, label)

    def test_every_rule_can_be_read_for_its_effects(self):
        """`effects_of` meets both stored shapes and some malformed ones."""
        seen = 0
        for _label, record in worlds().items():
            for _key, body in record["verb_rules"].items():
                for effect in rulecheck.effects_of(body):
                    self.assertTrue(hasattr(effect, "get"))
                    seen += 1
        self.assertGreater(seen, 100, "the corpus should have effects in it")

    def test_the_scan_is_deterministic(self):
        record = worlds()["world-01"]
        first = rulecheck.scan(rulecheck.of_record(record))
        second = rulecheck.scan(rulecheck.of_record(record))
        self.assertEqual(first, second)

    def test_every_finding_list_is_sorted(self):
        for label, record in worlds().items():
            found = rulecheck.scan(rulecheck.of_record(record))
            for name in ("one_way", "unsettable", "dead_vocabulary", "inert"):
                self.assertEqual(found[name], sorted(found[name]),
                                 f"{label}.{name}")

    def test_a_report_renders_for_every_world(self):
        for label, record in worlds().items():
            found = rulecheck.scan(rulecheck.of_record(record))
            said = rulecheck.report(found, label)
            self.assertIn(label, said)
            self.assertTrue(said.strip())

    def test_the_report_names_the_missing_rule_for_a_known_pair(self):
        """world-01 cannot close anything it can open. Said out loud."""
        found = rulecheck.scan(rulecheck.of_record(worlds()["world-01"]))
        said = rulecheck.report(found, "world-01")
        self.assertIn("Nothing can make anything closed", said)
        self.assertIn("openness", said)


@tag("unit")
class TheRatchet(SimpleTestCase):
    """
    Recorded numbers, asserted as a direction rather than as an equality.

    `down` may not rise, `zero` may not rise and is meant to reach nought, and
    `any` is recorded for interest. So this stays green while the rulebook
    change improves things, and goes red if a change makes a world worse --
    which is the only thing worth being told automatically.
    """

    def setUp(self):
        self.baseline = json.loads(
            (FIXTURES / "baselines.json").read_text(encoding="utf-8"))

    def measured(self):
        from tests.fixtures.baseline import measure

        _per_world, totals = measure()
        return totals

    def test_nothing_has_got_worse(self):
        totals = self.measured()
        for name, direction in self.baseline["directions"].items():
            was, now = self.baseline["totals"][name], totals[name]
            if direction in ("down", "zero"):
                self.assertLessEqual(
                    now, was,
                    f"{name} rose from {was} to {now}; if that is intended, "
                    f"re-run tests/fixtures/baseline.py")

    def test_the_baseline_still_describes_this_corpus(self):
        """
        Equality, but on purpose and in one place.

        If the fixtures are re-exported and the baseline is not, every ratchet
        above is comparing against the wrong corpus. This is the test that says
        so, and its fix is one command rather than an edit.
        """
        self.assertEqual(
            self.measured(), self.baseline["totals"],
            "the corpus and the baseline disagree; re-run "
            "tests/fixtures/baseline.py")

    def test_the_faults_the_plan_was_written_about_are_still_there(self):
        """
        The measurements the design notes quote, asserted from the corpus.

        Not a ratchet: these are the numbers `docs/` cites, and a test that
        reproduces them is what stops a document quoting a figure nothing can
        still produce.
        """
        totals = self.measured()
        self.assertEqual(totals["rules"], 326)
        self.assertEqual(totals["refused"], 85)
        self.assertEqual(totals["one_way"], 45)
        self.assertEqual(totals["unsettable"], 7)
        self.assertEqual(totals["refused_needs_a_place"], 7)


@tag("unit")
class ReadingTheRulebookToo(SimpleTestCase):
    """
    The scan was written against one rule per verb per world. Every rule a
    world writes now goes somewhere else, so a scan that read only the old
    store would report a clean world however broken the new one was.
    """

    def test_a_rulebook_rule_can_set_a_state_one_way(self):
        found = rulecheck.scan(world(filed={
            "r1": filed(effects=sets("lit"))}))
        self.assertEqual(found["one_way"], ["lit"])

    def test_and_another_rulebook_rule_can_settle_it(self):
        found = rulecheck.scan(world(filed={
            "r1": filed(effects=sets("lit")),
            "r2": filed(action="douse", effects=unsets("lit"))}))
        self.assertEqual(found["one_way"], [])

    def test_a_check_rule_makes_a_state_wanted(self):
        found = rulecheck.scan(world(filed={
            "r1": filed(phase="check",
                        conditions=[{"subject": "direct", "is": ["powered"]}])}))
        self.assertEqual(found["unsettable"], ["powered"])

    def test_the_two_stores_answer_each_other(self):
        """A learned rule sets it; a rulebook check wants it. Nothing wrong."""
        found = rulecheck.scan(world(
            {"light": rule(adds=["lit"])},
            filed={"r1": filed(phase="check",
                               conditions=[{"subject": "direct",
                                            "is": ["lit"]}])}))
        self.assertEqual(found["unsettable"], [])

    def test_a_check_rule_is_not_called_inert_for_having_no_effects(self):
        """Refusing is its whole job."""
        found = rulecheck.scan(world(filed={
            "r1": filed(phase="check",
                        conditions=[{"subject": "direct", "is": ["lit"]}])}))
        self.assertEqual(found["inert"], [])

    def test_a_rule_taken_out_of_its_rulebook_is_not_read(self):
        found = rulecheck.scan(world(filed={
            "r1": filed(effects=sets("lit"), listed=False)}))
        self.assertEqual(found["one_way"], [])
        self.assertEqual(found["counts"]["rules"], 0)

    def test_many_rules_for_one_verb_is_not_a_fork(self):
        """
        It is what a rulebook is for. `forked` asks a question about the old
        cache key, and asking it of rulebook rules would report the design
        working as the fault it replaced.
        """
        found = rulecheck.scan(world(filed={
            "r1": filed(effects=sets("lit")),
            "r2": filed(effects=sets("warm")),
            "r3": filed(phase="check",
                        conditions=[{"subject": "direct", "is": ["intact"]}])}))
        self.assertEqual(found["forked"], [])

    def test_the_counts_say_how_the_rules_are_split(self):
        found = rulecheck.scan(world(
            {"light": rule(adds=["lit"])},
            filed={"r1": filed(effects=sets("warm"))}))
        self.assertEqual(found["counts"]["rules"], 2)
        self.assertEqual(found["counts"]["filed"], 1)

    def test_a_rule_about_every_action_is_counted_as_no_verb(self):
        found = rulecheck.scan(world(filed={
            "r1": filed(action=None, phase="check",
                        conditions=[{"subject": "actor", "is": ["alive"]}])}))
        self.assertEqual(found["counts"]["verbs"], 0)
        self.assertEqual(found["counts"]["rules"], 1)


@tag("unit")
class WhatASoakWouldCapture(SimpleTestCase):
    """
    The exporter has to know about every store the engine writes, or a run of
    phase 13 produces a corpus of the old engine taken from a world running the
    new one -- which is the one way that run could be worth nothing.

    Asserted against the modules that declare the attributes, so a store added
    later fails here rather than going quietly missing from the next export.
    """

    def exported(self):
        from tests.fixtures import export

        return set(export.REGISTERS)

    def test_the_rulebook_is_exported(self):
        from world import rulebooks

        self.assertIn(rulebooks.ATTR, self.exported())
        self.assertIn(rulebooks.COUNTER, self.exported())

    def test_the_counters_are_exported(self):
        """The plan calls these the point of the run."""
        from world import counters

        self.assertIn(counters.ATTR, self.exported())

    def test_the_declarations_are_exported(self):
        from world import actions

        self.assertIn(actions.ATTR, self.exported())

    def test_what_was_declined_and_given_up_on_is_exported(self):
        from world import rule_gen, suggest

        self.assertIn(suggest.ATTR_DECLINED, self.exported())
        self.assertIn(rule_gen.ATTR_FRUITLESS, self.exported())

    def test_the_old_registers_are_still_exported(self):
        """A world mid-cutover holds both, and both are worth having."""
        for name in ("verb_rules", "kind_specs", "state_vocabulary",
                     "state_groups", "trait_vocabulary"):
            self.assertIn(name, self.exported())

    def test_everything_the_scan_reads_is_exported(self):
        """
        The tightest version of the rule: a register the scan reads and the
        exporter skips is a measurement that cannot be taken afterwards.
        """
        self.assertTrue(set(rulecheck.REGISTERS) <= self.exported(),
                        set(rulecheck.REGISTERS) - self.exported())

