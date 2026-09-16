"""
The verb pipeline on finish tools: phase 5 of docs/generator-tool-loops.md.

What a new verb costs -- what it takes, what it does, whether a sort of thing
admits it, what happened -- is four tool loops now, and what a model got wrong
is sent back to it rather than dropped. These hold the parts that are new: a
rule refused in one round and put right in the next is kept, a word the world
already has is pointed at, a proposal can be adopted, and the prompt is told
about wants and faults instead of being handed the registers.
"""

from unittest import mock

from django.test import tag

from tests.base import GameTest
from tests.support import (FakeSponsor, finishing, immediately, replying,
                           tool_call, tool_reply)
from world import actions, kinds, planner, rule_gen, suggest, verb_gen, verbs
from world import rulebooks as R


def _offered(recorder, index, name):
    """The schema of one tool a call offered, or None."""
    for schema in recorder.tools(index) or ():
        if schema["function"]["name"] == name:
            return schema["function"]
    return None


def _results(recorder, index):
    return "\n".join(message["content"]
                     for message in recorder.tool_results(index))


class _Datapad(GameTest):

    #: One rule, filed against the kind rather than this one datapad.
    loose_objects = 1

    RULE = {"phase": "carry_out", "scope": "datapad", "about": "direct",
            "name": "powering a datapad wakes it",
            "effects": [{"type": "set_state", "role": "direct",
                         "add": ["powered"]}]}

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_root = self.root
        self.pad = self.obj1
        self.pad.key = "Datapad"
        self.pad.db.kinds = ["datapad"]
        self.pad.db.affordances = {"power": True}
        kinds.admit(self.root, ["datapad"], "power", True)
        actions.declare(self.root, "power",
                        [{"role": "direct", "optional": True}])

    def learn(self, *replies):
        kept, failed = [], []
        with immediately(), replying(*replies) as recorder:
            rule_gen.learn(FakeSponsor(), self.root, "power",
                           {"direct": self.pad}, self.char1,
                           on_success=kept.extend, on_error=failed.append)
        self.assertEqual(failed, [])
        return kept, recorder


@tag("world")
class FilingRules(_Datapad):

    def test_a_rule_refused_and_then_put_right_is_kept(self):
        """The phase's finish line: the second answer is filed, not dropped."""
        wrong = dict(self.RULE, scope="physical_entity.n.01")
        kept, recorder = self.learn(
            tool_reply(tool_call("file_rules", rules=[wrong])),
            tool_reply(tool_call("file_rules", rules=[self.RULE])))
        self.assertEqual(recorder.count, 2)
        self.assertIn("was not one of the scopes offered", _results(recorder, 1))
        self.assertEqual([rule["scope"] for rule in kept], [{"kind": "datapad"}])
        self.assertEqual(rule_gen.fruitless(self.root, "power"), 0)

    def test_the_scope_is_closed_to_the_menu(self):
        _kept, recorder = self.learn(finishing(file_rules={"rules": [self.RULE]}))
        rules = _offered(recorder, 0, "file_rules")["parameters"]
        scope = rules["properties"]["rules"]["items"]["properties"]["scope"]
        self.assertIn("datapad", scope["enum"])
        self.assertIn("world", scope["enum"])

    def test_the_registers_are_looked_up_rather_than_pasted_in(self):
        verbs.register_state(self.root, "tarnished", means="dulled")
        _kept, recorder = self.learn(finishing(file_rules={"rules": [self.RULE]}))
        self.assertIsNotNone(_offered(recorder, 0, "list_states"))
        self.assertNotIn("tarnished", recorder.sent(0))

    def test_a_word_the_world_already_has_is_pointed_at(self):
        verbs.register_state(self.root, "closed", means="not open",
                             group="openness")
        shut = dict(self.RULE, effects=[{"type": "set_state", "role": "direct",
                                         "add": ["shut"]}])
        closed = dict(self.RULE, effects=[{"type": "set_state",
                                           "role": "direct",
                                           "add": ["closed"]}])
        kept, recorder = self.learn(
            tool_reply(tool_call("file_rules", rules=[shut],
                                 new_states=[{"slug": "shut",
                                              "means": "not open"}])),
            tool_reply(tool_call("file_rules", rules=[closed])))
        self.assertIn("already has the state 'closed' (group: openness)",
                      _results(recorder, 1))
        self.assertNotIn("shut", verbs.vocabulary(self.root))
        self.assertEqual(len(kept), 1)

    def test_an_answer_that_files_nothing_is_asked_about_once_more(self):
        _kept, recorder = self.learn(
            tool_reply(tool_call("file_rules", rules=[])),
            tool_reply(tool_call("file_rules", rules=[],
                                 cannot_say="no effect powers a thing")))
        self.assertIn("files nothing", _results(recorder, 1))
        self.assertEqual(rule_gen.fruitless(self.root, "power"), 1)

    def test_a_rule_already_worked_out_can_be_adopted(self):
        proposal = R.add(self.root, R.blank(
            action="power", phase=R.CARRY_OUT, scope={"kind": "datapad"},
            about="direct", name="powering a datapad wakes it",
            effects=self.RULE["effects"], source=suggest.DERIVED))
        R.set_listed(self.root, proposal["id"], False)

        kept, recorder = self.learn(finishing(
            file_rules={"rules": [], "adopt": [proposal["id"]]}))
        adopt = _offered(recorder, 0, "file_rules")["parameters"]["properties"]
        self.assertEqual(adopt["adopt"]["items"]["enum"], [proposal["id"]])
        self.assertIn("waiting to be adopted", recorder.sent(0))
        self.assertTrue(R.get(self.root, proposal["id"]).get("listed"))
        self.assertEqual([rule["id"] for rule in kept], [proposal["id"]])
        self.assertEqual(rule_gen.fruitless(self.root, "power"), 0)

    def test_without_proposals_there_is_nothing_to_adopt(self):
        _kept, recorder = self.learn(finishing(file_rules={"rules": [self.RULE]}))
        properties = _offered(recorder, 0, "file_rules")["parameters"]["properties"]
        self.assertNotIn("adopt", properties)


@tag("world")
class WhatTheRuleWriterIsTold(_Datapad):
    characters = 2

    def want(self, **overrides):
        return dict({"who": self.char2, "whose": "goal", "player": False,
                     "reason": planner.NO_RULE, "what": "Datapad",
                     "condition": {"type": "state", "object": "Datapad",
                                   "is": ["powered"]},
                     "words": "", "avoid": set()}, **overrides)

    def test_a_want_nothing_can_bring_about_is_a_hint(self):
        with mock.patch("world.goals.blocked_wants",
                        return_value=[self.want()]):
            lines = rule_gen.want_lines(self.root, "power",
                                        {"direct": self.pad})
            _kept, recorder = self.learn(
                finishing(file_rules={"rules": [self.RULE]}))
        self.assertEqual(lines, [f"{self.char2.key} wants the Datapad to be "
                                 f"powered, and nothing this world knows how "
                                 f"to do brings that about."])
        self.assertIn("wants the Datapad to be powered", recorder.sent(0))

    def test_a_want_about_something_else_is_not(self):
        other = self.want(what="lantern",
                          condition={"type": "state", "object": "lantern",
                                     "is": ["lit"]})
        with mock.patch("world.goals.blocked_wants", return_value=[other]):
            self.assertEqual(rule_gen.want_lines(self.root, "power",
                                                 {"direct": self.pad}), [])

    def test_a_missing_thing_needs_the_corpus_to_relate_it(self):
        missing = self.want(reason=planner.MISSING_THING, what="raw ore",
                            words="named so that the name contains 'raw ore'",
                            condition={"type": "holds", "object": "raw ore"})
        with mock.patch("world.goals.blocked_wants", return_value=[missing]), \
                mock.patch("world.commonsense.available", return_value=False):
            self.assertEqual(rule_gen.want_lines(self.root, "power",
                                                 {"direct": self.pad}), [])
        with mock.patch("world.goals.blocked_wants", return_value=[missing]), \
                mock.patch("world.commonsense.available", return_value=True), \
                mock.patch("world.commonsense.forward",
                           side_effect=lambda word, relation, limit=12:
                           ["datapad"] if relation == "PartOf" else []):
            lines = rule_gen.want_lines(self.root, "power",
                                        {"direct": self.pad})
        self.assertEqual(len(lines), 1)
        self.assertIn("contains 'raw ore'", lines[0])


@tag("world")
class TheOtherThreeQuestions(_Datapad):

    def test_what_an_action_takes(self):
        got = []
        with immediately(), replying(finishing(declare_action={
                "applies_to": [{"role": "direct", "access": "carried"}]})) \
                as recorder:
            actions.learn(FakeSponsor(), self.root, "juggle",
                          {"direct": self.pad}, self.char1,
                          on_success=got.append)
        self.assertEqual(got[0]["applies_to"][0]["access"], "carried")
        role = _offered(recorder, 0, "declare_action")["parameters"][
            "properties"]["applies_to"]["items"]["properties"]["role"]
        self.assertEqual(role["enum"], list(actions.ROLES))

    def test_a_verb_with_several_senses_offers_them(self):
        from world import lexicon

        if len(lexicon.verb_senses("launch")) < 2:
            self.skipTest("no dictionary")
        with immediately(), replying(finishing(
                declare_action={"applies_to": []})) as recorder:
            actions.learn(FakeSponsor(), self.root, "launch", {}, self.char1,
                          on_success=lambda spec: None)
        sense = _offered(recorder, 0, "declare_action")["parameters"][
            "properties"]["sense"]
        self.assertNotIn("", sense["enum"])
        self.assertGreater(len(sense["enum"]), 2)

    def test_whether_a_sort_of_thing_admits_a_verb(self):
        answers = []
        with immediately(), replying(finishing(
                admit={"allowed": False, "reason": "it has no switch"})):
            verb_gen.ask_admission(FakeSponsor(), self.root, "power", None,
                                   "datapad",
                                   on_answer=lambda *a: answers.append(a),
                                   on_error=self.fail)
        self.assertEqual(answers, [(False, "it has no switch")])

    def test_a_narration_that_names_a_thing_is_sent_back(self):
        got = []
        with immediately(), replying(
                tool_reply(tool_call("narrate", actor="It wakes.",
                                     room="{actor} $pconj(wake) Datapad.")),
                tool_reply(tool_call("narrate", actor="It wakes.",
                                     room="{actor} $pconj(wake) {direct}."))
        ) as recorder:
            verb_gen.narrate(FakeSponsor(), "power", {"direct": self.pad},
                             self.char1, "power datapad",
                             on_success=lambda *parts: got.append(parts),
                             on_error=self.fail)
        self.assertIn("names Datapad", _results(recorder, 1))
        self.assertEqual(got[0][1], "{actor} $pconj(wake) {direct}.")

    def test_a_placeholder_for_nobody_is_sent_back(self):
        from world.verb_gen import narration_complaints

        said = narration_complaints(
            {"room": "{actor} $pconj(hand) {target} {direct}."},
            {"direct": self.pad}, self.char1)
        self.assertTrue(any("{target}" in line for line in said), said)

    def test_what_repair_mends_costs_no_round(self):
        from world.verb_gen import narration_complaints

        self.assertEqual(narration_complaints(
            {"room": "{actor} wakes the {direct}."}, {"direct": self.pad},
            self.char1), [])

    def test_the_whole_road_on_finish_tools(self):
        """A verb nobody has settled, from declaration to narration."""
        from world import attempt as attempt_mod

        self.root.db.is_ai_room = True
        self.pad.db.kinds = ["slate"]
        self.pad.key = "slate"
        said = []
        with immediately(), replying(finishing(
                declare_action={"applies_to": [{"role": "direct"}]},
                file_rules={"rules": [dict(self.RULE, scope="slate",
                                           effects=[{"type": "set_state",
                                                     "role": "direct",
                                                     "add": ["buffed"]}])]},
                admit={"allowed": True, "reason": ""},
                narrate={"actor": "You buff it.",
                         "room": "{actor} $pconj(buff) {direct}."})) \
                as recorder:
            attempt_mod.attempt(self.char1, "buff slate", FakeSponsor(),
                                on_message=lambda a, r=None: said.append(a))
        asked = [schema["function"]["name"]
                 for index in range(recorder.count)
                 for schema in recorder.tools(index) or ()
                 if schema["function"]["name"] in
                 ("declare_action", "file_rules", "admit", "narrate")]
        self.assertEqual(asked, ["declare_action", "file_rules", "admit",
                                 "narrate"])
        self.assertIn("buffed", verbs.states(self.pad))
        self.assertIn("You buff it.", " ".join(s for s in said if s))
        self.assertEqual([rule["scope"] for rule in R.all_rules(self.root)
                          if rule.get("source") == "generated"],
                         [{"kind": "slate"}])
