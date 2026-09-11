"""
Rules a world derives about itself, and the six rails that keep the queue honest.

`rulecheck` finds faults; this proposes fixes. The difference is why it is a queue
and not a repair: a one-way state is a fact, and the rule that would settle it is
a guess about meaning. So nothing here is ever in force until somebody says so.

`TheRails` is the class to read. Each of the six exists because of a specific way
this goes wrong, and the fourth is the one that matters most -- an `instead`
proposal at equal or wider scope than the rule it means to refine would shadow it
instead, and a wrong `instead` silently changes what a verb means.
"""

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeSponsor, as_json, immediately, replying
from world import attempt as attempt_mod
from world import actions, counters, kinds, rulebooks as R
from world import standard_rules, suggest, verbs


@tag("unit")
class WhatMakesTwoProposalsTheSame(SimpleTestCase):
    """
    Not the id, which changes every time one is generated, and not the record,
    which carries a timestamp. A person declines a meaning, and that is what has
    to be remembered.
    """

    def rule(self, **over):
        base = dict(R.blank(
            action="close", phase=R.CARRY_OUT, scope={"kind": "door.n.01"},
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["closed"], "remove": ["open"]}]))
        base.update(over)
        return base

    def test_the_same_meaning_fingerprints_the_same(self):
        one, two = self.rule(id="d1"), self.rule(id="d9", name="different words")
        self.assertEqual(suggest.fingerprint(one), suggest.fingerprint(two))

    def test_a_different_scope_does_not(self):
        self.assertNotEqual(
            suggest.fingerprint(self.rule()),
            suggest.fingerprint(self.rule(scope={"kind": "gate.n.01"})))

    def test_nor_does_a_different_effect(self):
        self.assertNotEqual(
            suggest.fingerprint(self.rule()),
            suggest.fingerprint(self.rule(
                effects=[{"type": "set_state", "role": "direct",
                          "add": ["locked"]}])))

    def test_nor_a_different_phase(self):
        self.assertNotEqual(suggest.fingerprint(self.rule()),
                            suggest.fingerprint(self.rule(phase=R.INSTEAD)))


@tag("world")
class AWorldWithFaults(EvenniaTest):
    """
    A door that can be opened and never closed -- the pair the development
    corpus produces five of -- and a ship nobody can launch bare.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.char1.move_to(self.room2, quiet=True)
        standard_rules.seed(self.root)

        self.door = self.obj1
        self.door.key = "Hatch"
        self.door.db.kinds = ["door.n.01"]
        self.door.move_to(self.room2, quiet=True)

        # The world's own grouping says open and closed answer one question.
        verbs.register_state(self.root, "open", means="standing open",
                             group="openness")
        verbs.register_state(self.root, "closed", means="shut",
                             group="openness")
        # And it wrote a rule that only ever moves it one way.
        self.opener = R.add(self.root, R.blank(
            action="open", phase=R.CARRY_OUT, scope={"kind": "door.n.01"},
            about="direct", name="opening a door opens it",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["open"]}]))
        # Plus a rule that wants the state nothing can bring about.
        R.add(self.root, R.blank(
            action="lock", phase=R.CHECK, scope={"kind": "door.n.01"},
            about="direct", name="you can only lock a closed door",
            conditions=[{"subject": "direct", "is": ["closed"]}]))


@tag("world")
class FromAPairOfStates(AWorldWithFaults):
    """
    One missing rule, seen from both ends. The evidence is the world's own
    grouping, not a dictionary: it said those two states answer one question and
    then only ever moved it one way.
    """

    def test_a_proposal_is_made(self):
        made = [r for r in suggest.from_pairs(self.root) if r]
        self.assertEqual(len(made), 1)
        rule = made[0]
        self.assertEqual(rule["phase"], R.CARRY_OUT)
        self.assertEqual(rule["action"], "close")
        self.assertEqual(rule["scope"], {"kind": "door.n.01"})

    def test_it_would_move_the_state_both_ways(self):
        rule = [r for r in suggest.from_pairs(self.root) if r][0]
        effect = rule["effects"][0]
        self.assertEqual(effect["add"], ["closed"])
        self.assertEqual(effect["remove"], ["open"])

    def test_it_is_scoped_where_the_one_way_rule_was(self):
        """
        Not guessed. The rule that can only open a door says which sort of thing
        this is about, so the inverse is filed in the same place.
        """
        rule = [r for r in suggest.from_pairs(self.root) if r][0]
        self.assertEqual(rule["scope"], self.opener["scope"])
        self.assertIn(self.opener["id"], rule["why"])

    def test_and_it_cites_this_world_rather_than_english(self):
        rule = [r for r in suggest.from_pairs(self.root) if r][0]
        self.assertIn("openness", rule["why"])
        self.assertTrue(rule["evidence"].get("one_way_state"))
        self.assertEqual(rule["evidence"].get("rules_wanting_it"), 1)

    def test_a_state_with_no_verb_behind_it_proposes_nothing(self):
        """
        `unlit` lemmatises to `unlit`, which is an adjective and nothing else.
        Proposing that a world needs a rule about "unlitting" things would be
        the plausible nonsense rail 1 exists to keep out.
        """
        self.assertEqual(suggest._verb_for_state("unlit"), "")
        self.assertEqual(suggest._verb_for_state("in_flight"), "")
        self.assertEqual(suggest._verb_for_state("closed"), "close")
        self.assertEqual(suggest._verb_for_state("lit"), "light")

    def test_it_is_not_offered_twice(self):
        suggest.from_pairs(self.root)
        again = [r for r in suggest.from_pairs(self.root) if r]
        self.assertEqual(again, [])
        self.assertEqual(len(suggest.queue(self.root)), 1)


@tag("world")
class FromRefusedAttempts(AWorldWithFaults):
    """
    The row the whole of §10.1 was written for: the `power`-aboard-a-ship case
    arising by itself instead of being anticipated.
    """

    def refuse(self, times, action="launch"):
        for _ in range(times):
            counters.note(self.root, action, {}, self.char1,
                          counters.NO_OBJECT)

    def test_a_habit_is_proposed_about(self):
        self.refuse(suggest.LEAST)
        made = [r for r in suggest.from_unbound_refusals(self.root) if r]
        self.assertEqual(len(made), 1)
        rule = made[0]
        self.assertEqual(rule["phase"], R.INSTEAD)
        self.assertEqual(rule["scope"], {"kind": "spacecraft.n.01"})

    def test_the_proposal_is_the_redirect_the_spaceship_needed(self):
        self.refuse(suggest.LEAST)
        rule = [r for r in suggest.from_unbound_refusals(self.root) if r][0]
        self.assertEqual(rule["when"], [{"subject": "direct", "unbound": True}])
        effect = rule["effects"][0]
        self.assertEqual(effect["type"], "try")
        self.assertEqual(effect["roles"]["direct"],
                         {"enclosure": "spacecraft.n.01"})

    def test_it_cites_the_count(self):
        self.refuse(7)
        rule = [r for r in suggest.from_unbound_refusals(self.root) if r][0]
        self.assertEqual(rule["evidence"]["attempts_refused"], 7)
        self.assertIn("7 times", rule["why"])

    def test_an_accident_is_not_a_habit(self):
        self.refuse(suggest.LEAST - 1)
        self.assertEqual(
            [r for r in suggest.from_unbound_refusals(self.root) if r], [])

    def test_a_refusal_with_no_place_behind_it_proposes_nothing(self):
        """
        A verb refused in a room of no particular kind has nothing to redirect
        to: there is no sort of place to file the rule against.
        """
        self.room2.db.kinds = []
        self.refuse(suggest.LEAST + 2)
        self.assertEqual(
            [r for r in suggest.from_unbound_refusals(self.root) if r], [])

    def test_and_a_refusal_about_a_named_thing_is_a_different_question(self):
        for _ in range(suggest.LEAST + 2):
            counters.note(self.root, "launch", {"direct": self.door},
                          self.char1, counters.NO_OBJECT)
        self.assertEqual(
            [r for r in suggest.from_unbound_refusals(self.root) if r], [])


@tag("world")
class FromSiblingKinds(EvenniaTest):
    """
    The only generator that makes a world simpler. Two kinds affording exactly
    the same things, one with a rule and one without, and the proposal widens the
    rule rather than copying it.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.char1.move_to(self.room1, quiet=True)
        standard_rules.seed(self.root)

        for kind in ("sword.n.01", "dagger.n.01"):
            for verb in ("sharpen", "wield"):
                kinds.admit(self.root, [kind], verb, True)

        self.rule = R.add(self.root, R.blank(
            action="sharpen", phase=R.CARRY_OUT, scope={"kind": "sword.n.01"},
            about="direct", name="sharpening a sword hones it",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["sharp"], "remove": ["blunt"]}]))

    def test_a_rule_is_proposed_at_the_shared_parent(self):
        made = [r for r in suggest.from_siblings(self.root) if r]
        self.assertTrue(made)
        rule = made[0]
        self.assertEqual(rule["action"], "sharpen")
        parent = rule["scope"]["kind"]
        self.assertTrue(kinds.is_a(self.root, "sword.n.01", parent))
        self.assertTrue(kinds.is_a(self.root, "dagger.n.01", parent))

    def test_it_names_both_kinds_and_the_rule_it_widens(self):
        rule = [r for r in suggest.from_siblings(self.root) if r][0]
        self.assertIn("dagger.n.01", rule["why"])
        self.assertIn(self.rule["id"], rule["why"])

    def test_never_above_the_scope_ceiling(self):
        """A widening that files a rule near the root is a rule about everything."""
        from world import rule_gen

        for rule in [r for r in suggest.from_siblings(self.root) if r]:
            self.assertFalse(rule_gen.too_general(rule["scope"]), rule["scope"])

    def test_kinds_that_afford_different_things_are_not_siblings(self):
        kinds.admit(self.root, ["dagger.n.01"], "throw", True)
        self.assertEqual([r for r in suggest.from_siblings(self.root) if r], [])

    def test_and_nothing_is_proposed_when_both_already_have_a_rule(self):
        R.add(self.root, R.blank(
            action="sharpen", phase=R.CARRY_OUT, scope={"kind": "dagger.n.01"},
            about="direct", name="sharpening a dagger hones it",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["sharp"]}]))
        self.assertEqual([r for r in suggest.from_siblings(self.root) if r], [])


@tag("world")
class TheRails(AWorldWithFaults):
    """Six, and each exists because of a specific way this goes wrong."""

    def a_proposal(self, **over):
        base = dict(R.blank(
            action="close", phase=R.CARRY_OUT, scope={"kind": "door.n.01"},
            about="direct", name="closing a door shuts it",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["closed"]}]))
        base.update(over)
        return base

    # 1 -----------------------------------------------------------------
    def test_one_no_evidence_no_proposal(self):
        self.assertIsNone(suggest.propose(
            self.root, self.a_proposal(), why="it seems likely", evidence={}))
        self.assertEqual(suggest.queue(self.root), [])

    def test_one_and_evidence_that_counts_nothing_is_no_evidence(self):
        self.assertIsNone(suggest.propose(
            self.root, self.a_proposal(), why="because",
            evidence={"vibes": "strong"}))

    # 2 -----------------------------------------------------------------
    def test_two_a_rejection_is_remembered(self):
        rule = suggest.propose(self.root, self.a_proposal(), why="one way",
                              evidence={"one_way_state": 1})
        self.assertIsNotNone(rule)
        suggest.reject(self.root, rule["id"])
        self.assertEqual(suggest.queue(self.root), [])
        self.assertIsNone(suggest.propose(
            self.root, self.a_proposal(), why="one way",
            evidence={"one_way_state": 1}))

    def test_two_and_the_generator_stops_offering_it(self):
        made = [r for r in suggest.from_pairs(self.root) if r]
        suggest.reject(self.root, made[0]["id"])
        self.assertEqual([r for r in suggest.from_pairs(self.root) if r], [])

    # 3 -----------------------------------------------------------------
    def test_three_no_chains(self):
        """
        A world that may reason from its own guesses reasons its way into
        fiction, and the second derivation looks as well evidenced as the first.
        """
        accepted = suggest.propose(
            self.root,
            self.a_proposal(action="seal", scope={"kind": "door.n.01"},
                            effects=[{"type": "set_state", "role": "direct",
                                      "add": ["sealed"]}]),
            why="made up", evidence={"one_way_state": 1})
        suggest.accept(self.root, accepted["id"])
        self.assertNotIn(accepted["id"],
                         [r.get("id") for r in suggest._world_rules(self.root)])

    # 4 -----------------------------------------------------------------
    def test_four_an_instead_must_be_more_specific_than_what_it_overrides(self):
        wider = R.add(self.root, R.blank(
            action="launch", phase=R.INSTEAD, scope={"kind": "door.n.01"},
            about="direct", name="a door does not launch"))
        self.assertIsNone(suggest.propose(
            self.root,
            self.a_proposal(action="launch", phase=R.INSTEAD,
                            scope={"kind": "door.n.01"}, effects=[]),
            why="same scope", evidence={"attempts_refused": 9},
            overrides=wider["id"]))

    def test_four_and_it_names_the_rule_it_overrides(self):
        world_wide = R.add(self.root, R.blank(
            action="launch", phase=R.INSTEAD, scope={"world": True},
            name="nothing launches here"))
        rule = suggest.propose(
            self.root,
            self.a_proposal(action="launch", phase=R.INSTEAD,
                            scope={"kind": "spacecraft.n.01"}, effects=[]),
            why="narrower", evidence={"attempts_refused": 9},
            overrides=world_wide["id"])
        self.assertIsNotNone(rule)
        self.assertIn(world_wide["id"], rule["why"])

    def test_four_an_override_that_is_not_there_is_refused(self):
        self.assertIsNone(suggest.propose(
            self.root,
            self.a_proposal(phase=R.INSTEAD, effects=[]),
            why="overriding a ghost", evidence={"attempts_refused": 9},
            overrides="r999"))

    # 5 -----------------------------------------------------------------
    def test_five_the_queue_is_capped_and_sheds_its_weakest(self):
        for n in range(suggest.MAX_QUEUE + 4):
            suggest.propose(
                self.root,
                self.a_proposal(action=f"verb{n}",
                                effects=[{"type": "set_state",
                                          "role": "direct",
                                          "add": [f"state{n}"]}]),
                why=f"number {n}", evidence={"attempts_refused": n + 1})
        standing = suggest.queue(self.root)
        self.assertEqual(len(standing), suggest.MAX_QUEUE)
        kept = {r["action"] for r in standing}
        self.assertNotIn("verb0", kept, "the weakest evidence goes first")
        self.assertIn(f"verb{suggest.MAX_QUEUE + 3}", kept)

    # 6 -----------------------------------------------------------------
    def test_six_the_derived_mark_is_permanent(self):
        rule = suggest.propose(self.root, self.a_proposal(), why="one way",
                               evidence={"one_way_state": 1})
        taken = suggest.accept(self.root, rule["id"])
        self.assertTrue(taken["listed"])
        self.assertEqual(taken["source"], suggest.DERIVED)
        self.assertIn(taken["id"], [r["id"] for r in suggest.accepted(self.root)])


@tag("world")
class AnsweringTheQueue(AWorldWithFaults):

    def test_an_unanswered_proposal_applies_to_nothing(self):
        """`listed: false` already meant this. A proposal is that plus a reason."""
        made = [r for r in suggest.from_pairs(self.root) if r][0]
        book = R.for_attempt(self.root, "close", {"direct": self.door},
                             self.char1)
        self.assertNotIn(made["id"], [r.get("id") for r in book])

    def test_accepting_one_puts_it_in_force(self):
        made = [r for r in suggest.from_pairs(self.root) if r][0]
        suggest.accept(self.root, made["id"])
        book = R.for_attempt(self.root, "close", {"direct": self.door},
                             self.char1)
        self.assertIn(made["id"], [r.get("id") for r in book])

    def test_and_it_fixes_the_fault_that_prompted_it(self):
        """The plan's done-when, asserted end to end."""
        from world import rulecheck

        before = rulecheck.scan(rulecheck.of_world(self.root))
        self.assertIn("closed", before["unsettable"])

        made = [r for r in suggest.from_pairs(self.root) if r][0]
        suggest.accept(self.root, made["id"])

        after = rulecheck.scan(rulecheck.of_world(self.root))
        self.assertNotIn("closed", after["unsettable"])
        self.assertNotIn("open", after["one_way"])

    def test_rejecting_one_takes_it_out_of_the_book(self):
        made = [r for r in suggest.from_pairs(self.root) if r][0]
        suggest.reject(self.root, made["id"])
        self.assertIsNone(R.get(self.root, made["id"]))

    def test_a_rule_the_world_wrote_itself_cannot_be_accepted(self):
        self.assertIsNone(suggest.accept(self.root, self.opener["id"]))
        self.assertIsNone(suggest.reject(self.root, self.opener["id"]))

    def test_the_queue_reads_as_prose(self):
        suggest.generate(self.root)
        said = suggest.report(self.root)
        self.assertIn("close makes a thing closed", said.lower())
        self.assertIn("because", said)

    def test_and_says_so_when_there_is_nothing_to_suggest(self):
        self.assertIn("Nothing to suggest", suggest.report(self.room2))


@tag("world")
class TheWholeRoad(EvenniaTest):
    """
    The spaceship, one more time, with nobody writing a rule.

    A world that has never been told what `launch` means aboard a ship, a player
    who tries it three times, and a proposal that works when accepted.
    """

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room2.db.world_root = self.root
        self.room2.db.is_ai_room = True
        self.room2.db.kinds = ["spacecraft.n.01"]
        self.room2.db.room_title = "Bridge"
        self.char1.move_to(self.room2, quiet=True)
        standard_rules.seed(self.root)

        actions.declare(self.root, "launch",
                        [{"role": "direct", "optional": False}])
        kinds.admit(self.root, ["spacecraft.n.01"], "launch", True)
        R.add(self.root, R.blank(
            action="launch", phase=R.CARRY_OUT,
            scope={"kind": "spacecraft.n.01"}, about="direct",
            name="launching takes the ship up",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["in_flight"]}]))

    def try_it(self, raw):
        said = []
        with immediately(), replying(
                as_json({"actor": "Done.", "room": "{actor} does it."})):
            attempt_mod.attempt(
                self.char1, raw, FakeSponsor(),
                on_message=lambda a, r=None: said.append(a or ""))
        return " ".join(s for s in said if s)

    def test_trying_it_bare_is_refused_and_remembered(self):
        for _ in range(suggest.LEAST):
            said = self.try_it("launch")
            self.assertIn("what", said.lower())
        self.assertEqual(
            counters.count(self.root, "launch", "enclosure:spacecraft.n.01",
                           counters.NO_OBJECT), suggest.LEAST)

    def test_then_the_world_proposes_the_rule_it_needs(self):
        for _ in range(suggest.LEAST):
            self.try_it("launch")
        made = suggest.generate(self.root)
        redirects = [r for r in made if r["phase"] == R.INSTEAD]
        self.assertEqual(len(redirects), 1)
        self.assertIn(str(suggest.LEAST), redirects[0]["why"])

    def test_and_accepting_it_makes_the_bare_verb_work(self):
        for _ in range(suggest.LEAST):
            self.try_it("launch")
        redirect = [r for r in suggest.generate(self.root)
                    if r["phase"] == R.INSTEAD][0]

        self.assertIn("what", self.try_it("launch").lower())
        suggest.accept(self.root, redirect["id"])

        self.try_it("launch")
        self.assertIn("in_flight", verbs.states(self.room2))

    def test_nothing_was_asked_of_a_model_to_get_there(self):
        with immediately(), replying("{}") as script:
            for _ in range(suggest.LEAST):
                attempt_mod.attempt(self.char1, "launch", FakeSponsor(),
                                    on_message=lambda a, r=None: None)
            suggest.generate(self.root)
            self.assertEqual(script.count, 0,
                             "deriving a rule costs nothing; judging it is the "
                             "part that would")


@tag("world")
class AskingSomebodyElseToJudge(AWorldWithFaults):
    """
    The only part of this that costs anything, and the reason it is cheap: a
    model is handed a filled-in rule with this world's counts beside it, several
    to a call, and asked yes or no. It is never asked to write one.
    """

    def setUp(self):
        super().setUp()
        suggest.generate(self.root)
        self.standing = suggest.queue(self.root)
        self.assertTrue(self.standing, "the fixture should have faults")

    def ask(self, reply):
        taken, declined, errors = [], [], []
        with immediately(), replying(
                as_json(reply) if isinstance(reply, dict) else reply) as script:
            suggest.judge(FakeSponsor(), self.root,
                          on_success=lambda a, d: (taken.extend(a),
                                                   declined.extend(d)),
                          on_error=errors.append)
            self.asked = script.count
        return taken, declined, errors

    def test_the_whole_queue_rides_in_one_call(self):
        taken, _declined, errors = self.ask(
            {"verdicts": [{"id": rule["id"], "accept": True}
                          for rule in self.standing]})
        self.assertEqual(self.asked, 1, "per batch, not per rule")
        self.assertEqual(errors, [])
        self.assertEqual(sorted(taken),
                         sorted(r["id"] for r in self.standing))

    def test_an_accepted_verdict_puts_the_rule_in_force(self):
        first = self.standing[0]
        self.ask({"verdicts": [{"id": first["id"], "accept": True}]})
        self.assertTrue(R.get(self.root, first["id"])["listed"])
        self.assertEqual(R.get(self.root, first["id"])["source"],
                         suggest.DERIVED)

    def test_a_declined_one_is_remembered_as_declined(self):
        first = self.standing[0]
        mark = suggest.fingerprint(first)
        self.ask({"verdicts": [{"id": first["id"], "accept": False}]})
        self.assertIsNone(R.get(self.root, first["id"]))
        self.assertIn(mark, suggest.declined(self.root))

    def test_a_verdict_about_something_not_in_the_queue_is_ignored(self):
        """
        The one way this call could reach a rule the world decided for itself.
        Refused here rather than trusted: a judge may only answer what it was
        asked.
        """
        before = dict(self.opener)
        self.ask({"verdicts": [{"id": self.opener["id"], "accept": False}]})
        after = R.get(self.root, self.opener["id"])
        self.assertIsNotNone(after, "a world's own rule is not the queue's")
        self.assertEqual(after["name"], before["name"])

    def test_a_reply_that_is_not_a_reply_is_an_error_not_a_change(self):
        _taken, _declined, errors = self.ask("I would rather not.")
        self.assertTrue(errors)
        self.assertEqual(len(suggest.queue(self.root)), len(self.standing))

    def test_an_empty_queue_costs_nothing(self):
        for rule in self.standing:
            suggest.reject(self.root, rule["id"])
        taken, declined, errors = self.ask({"verdicts": []})
        self.assertEqual((taken, declined, errors), ([], [], []))
        self.assertEqual(self.asked, 0, "nothing to judge, nothing to pay for")

    def test_the_prompt_shows_the_evidence_and_not_a_blank_form(self):
        said = suggest.judgement_prompt(self.root)
        self.assertIn("because", said)
        self.assertIn("openness", said)
        self.assertNotIn("|w", said, "colour codes are for players, not models")

    def test_and_it_shows_what_a_redirect_would_override(self):
        wide = R.add(self.root, R.blank(
            action="board", phase=R.INSTEAD, scope={"world": True},
            name="nothing is boarded here"))
        suggest.propose(
            self.root,
            R.blank(action="board", phase=R.INSTEAD,
                    scope={"kind": "spacecraft.n.01"},
                    about=R.ENCLOSURE, name="boarding means the ship"),
            why="tried often", evidence={"attempts_refused": 6},
            overrides=wide["id"])
        said = suggest.judgement_prompt(self.root)
        self.assertIn("the rule it would override", said)
        self.assertIn("nothing is boarded here", said)

