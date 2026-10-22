"""
The socials ruleset: smiling, nodding and bowing without a model.

The point of it is that a world opting in never pays to find out what a smile
looks like, so the tests that matter most are the ones that count calls. The
rest hold the list to what it promised: a hundred and fifty of them, written
from `build_socials.py`, and none taking a word the game or another ruleset
already answers.
"""

import json
import os

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import actions, rulesets
from world import rulebooks as R


def _socials():
    return rulesets.available()["socials"]


@tag("unit")
class TheList(SimpleTestCase):

    def test_it_loads(self):
        self.assertIn("socials", rulesets.available())
        self.assertEqual(rulesets.problems(_socials()), [])

    def test_there_are_a_hundred_and_fifty(self):
        self.assertGreaterEqual(len(_socials()["actions"]), 150)

    def test_it_is_not_on_unless_chosen(self):
        self.assertNotIn("socials", rulesets.defaults())

    def test_the_json_is_what_the_table_builds(self):
        """Edit the table and run the script; never the JSON by hand."""
        import importlib.util

        # Loaded by path: `world.rulesets` is the module, and the folder of
        # the same name beside it is data, not a package.
        script = os.path.join(rulesets.BUILTIN_DIR, "build_socials.py")
        spec = importlib.util.spec_from_file_location("build_socials", script)
        build_socials = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_socials)

        path = os.path.join(build_socials.HERE, "socials.json")
        with open(path, encoding="utf-8") as found:
            self.assertEqual(json.load(found), build_socials.build(),
                             "run aimud/world/rulesets/build_socials.py")

    def test_nobody_is_ever_asked_whether_a_thing_admits_one(self):
        for entry in _socials()["actions"]:
            with self.subTest(verb=entry["action"]):
                self.assertTrue(entry["admits_all"])

    def test_every_sentence_names_who_did_it(self):
        for rule in _socials()["rules"]:
            with self.subTest(rule=rule["name"]):
                self.assertTrue(rule["report"].startswith("{actor} $pconj("))


@tag("unit")
class TakingNoWordAlreadyTaken(SimpleTestCase):
    """
    A social is the weakest thing a word can mean. One that took a command's
    word would never be reached, and one that took a verb the game folds or
    another ruleset declares would be fighting it.
    """

    def verbs(self):
        return [entry["action"] for entry in _socials()["actions"]]

    def test_no_command_has_the_word(self):
        from commands.default_cmdsets import AccountCmdSet, CharacterCmdSet

        taken = set()
        for cmdset in (CharacterCmdSet(), AccountCmdSet()):
            cmdset.at_cmdset_creation()
            for command in cmdset.commands:
                taken.add(command.key.lower())
                taken |= {alias.lower() for alias in command.aliases}
        self.assertEqual(sorted(set(self.verbs()) & taken), [])

    def test_no_verb_folds_into_another(self):
        from world import verbs

        for verb in self.verbs():
            with self.subTest(verb=verb):
                self.assertEqual(verbs.canonical_verb(verb), verb)
                self.assertNotIn(verb, verbs.VERB_SYNONYMS.values())

    def test_none_is_a_verb_the_game_answers_itself(self):
        from world import clothing, verbs

        answered = set(verbs.PIPELINE_VERBS) | set(clothing.VERBS)
        self.assertEqual(sorted(set(self.verbs()) & answered), [])

    def test_no_other_ruleset_declares_one(self):
        mine = set(self.verbs())
        for name, doc in rulesets.available().items():
            if name == "socials":
                continue
            theirs = {entry.get("action") for entry in doc.get("actions") or []}
            with self.subTest(ruleset=name):
                self.assertEqual(sorted(mine & theirs), [])


@tag("world")
class SmilingInAWorld(GameTest):

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        rulesets.seed(self.root, ["socials"])

    def attempt(self, raw):
        from tests.support import FakeSponsor, immediately, replying
        from world import attempt as attempt_mod

        said = []
        with immediately(), replying("{}") as script:
            attempt_mod.attempt(
                self.char1, raw, FakeSponsor(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text))
            self.asked = script.count
        return " ".join(str(s) for s in said if s)

    def test_alone(self):
        self.assertEqual(self.attempt("smile"), "You smile.")
        self.assertEqual(self.asked, 0, "a social never asks a model")

    def test_at_somebody(self):
        self.assertEqual(self.attempt("smile at obj"), "You smile at the Obj.")
        self.assertEqual(self.asked, 0)

    def test_or_naming_them_straight(self):
        self.assertEqual(self.attempt("smile obj"), "You smile at the Obj.")

    def test_a_social_said_with_with(self):
        self.assertEqual(self.attempt("agree with obj"),
                         "You agree with the Obj.")

    def test_one_that_takes_nobody(self):
        self.assertEqual(self.attempt("yawn"), "You yawn.")
        self.assertEqual(self.asked, 0)

    def test_your_own_pronouns(self):
        self.assertEqual(self.attempt("headshake"), "You shake your head.")

    def test_a_touch_needs_reach_but_no_permission(self):
        self.assertEqual(self.attempt("hug obj"), "You hug the Obj.")
        self.assertEqual(self.asked, 0)

    def test_a_worlds_own_rule_wins(self):
        """Where kissing breaks a curse, the world says so with one rule."""
        R.add(self.root, R.blank(
            action="kiss", phase=R.CARRY_OUT, scope={"world": True},
            about="direct", name="a kiss breaks the curse",
            when=[{"subject": "direct", "unbound": False}],
            effects=[{"type": "narrate"}],
            report="{actor} $pconj(kiss) {direct}, and the curse breaks."))
        self.assertEqual(self.attempt("kiss obj"),
                         "You kiss the Obj, and the curse breaks.")

    def test_nothing_it_adds_is_a_fault(self):
        from world import rulecheck

        findings = rulecheck.scan(rulecheck.of_world(self.root))
        for finding in ("shadowed", "untested_conditions", "contradictory",
                        "inert"):
            with self.subTest(finding=finding):
                self.assertEqual(findings[finding], [])

    def test_and_the_verbs_are_declared_the_way_they_are_said(self):
        self.assertEqual(actions.missing_role(self.root, "smile", {}), "")
        self.assertTrue(actions.admits_everything(self.root, "hug"))
