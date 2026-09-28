"""
A rule that writes its own words, and the world with no key that needs them.

`permits` has always allowed a world to run with no model at all: rules
somebody wrote still fire, effects still land, and the only thing missing is
the sentence. What filled that gap was `attempt._said_plainly` -- the player's
own line handed back with "You " in front of it -- and a builder had no way to
decline the trade. Everything anybody ever did in such a world read as an echo
of what they had typed.

A becomes rule never had that problem, because it never had a narrator: it
carries `report`, a template written once and rendered for each reader, since
a world's clock cannot pay a model every tick. This is that field, opened to
the two phases of an attempt that answer somebody -- carry-out and instead.

Three things follow, and they are what is held down here. It costs nothing and
asks nothing. It beats the narration cache, so editing the words changes what
the room reads at once rather than after the cache happens to miss. And the
actor reads the same sentence as everybody else, in their own words, because
what is stored is a template and not a line.

The contest at the end of the file is the other half of the same claim and is
here for the same reason: what a builder writes runs down the path a model's
answer runs down, rather than down one of its own. `attempt` reads the
carry-out rule's `contest` without caring who wrote it.
"""

from unittest import mock

from django.test import tag
from evennia import create_object

from tests.base import GameTest
from tests.support import FakeSponsor, finishing, immediately, replying
from world import rulebooks as R


class Written(GameTest):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.world_root = self.root
        self.root.db.is_world_root = True
        self.root.db.is_ai_room = True
        self.obj1.key = "Lever"
        self.watcher = create_object("typeclasses.characters.Character",
                                     key="Watcher", location=self.room1)

    def rule(self, **fields):
        fields.setdefault("action", "pull")
        fields.setdefault("phase", R.CARRY_OUT)
        fields.setdefault("scope", {"world": True})
        return R.add(self.root, R.blank(**fields))

    def pull(self, sponsor=None, replies=None):
        """
        Pull the lever, and answer with what each person in the room read.

        Delivered through `events.show`, which is what a command does with
        what an attempt hands back -- the actor's own line and the room's
        template are different things, and a test that only watched
        `on_message` would never see the second.
        """
        from world import attempt as attempt_mod
        from world import events

        mine, theirs = [], []
        answers = replies or finishing(
            declare_action={"applies_to": [{"role": "direct"}]},
            narrate={"actor": "A model wrote this.",
                     "room": "{actor} $pconj(rummage)."})
        with mock.patch.object(self.char1, "msg",
                               side_effect=lambda text=None, **kw:
                               mine.append(str(text))), \
             mock.patch.object(self.watcher, "msg",
                               side_effect=lambda text=None, **kw:
                               theirs.append(str(text))):
            with immediately(), replying(answers):
                attempt_mod.attempt(
                    self.char1, "pull lever",
                    sponsor if sponsor is not None else FakeSponsor(),
                    on_message=lambda text, event=None: events.show(
                        text, event, self.char1))
        return "\n".join(mine), "\n".join(theirs)


@tag("world")
class WordsAWorldWroteForItself(Written):

    def test_the_room_reads_them_and_the_actor_reads_them_too(self):
        """
        One template, two readings. `show_the_room` leaves the actor out, so
        without rendering it for them as well they would read nothing at all.
        """
        self.rule(name="pulling", report="{actor} $pconj(pull) the lever.",
                  effects=[{"type": "set_state", "role": "direct",
                            "add": ["pulled"]}])
        mine, theirs = self.pull()
        self.assertIn("You pull the lever.", mine)
        self.assertIn("Char pulls the lever.", theirs)

    def test_and_no_model_is_asked(self):
        """
        The whole point. A world paying nothing must be charged nothing, and
        the narrator is the call every attempt would otherwise make.
        """
        from world import attempt as attempt_mod
        from world import events

        self.rule(name="pulling", report="{actor} $pconj(pull) the lever.")
        with immediately(), replying(finishing(
                declare_action={"applies_to": [{"role": "direct"}]},
                narrate={"actor": "should not be asked",
                         "room": "should not be asked"})) as recorder:
            attempt_mod.attempt(
                self.char1, "pull lever", FakeSponsor(),
                on_message=lambda text, event=None: events.show(
                    text, event, self.char1))
        asked = [schema["function"]["name"]
                 for index in range(recorder.count)
                 for schema in recorder.tools(index) or ()]
        self.assertNotIn("narrate", asked)

    def test_a_world_with_no_key_reads_prose_rather_than_an_echo(self):
        """
        The case this exists for. Without a report such a world answers "You
        pull lever." -- the sentence typed, handed back. `permits` says that
        is the trade a keyless world makes; this is how its builder declines
        it, one rule at a time.
        """
        self.rule(name="pulling",
                  report="{actor} $pconj(haul) the lever down, and it gives.")
        keyless = FakeSponsor(key="")
        mine, theirs = self.pull(sponsor=keyless)
        self.assertIn("You haul the lever down", mine)
        self.assertNotIn("You pull lever.", mine)
        self.assertIn("Char hauls the lever down", theirs)

    def test_the_effect_lines_follow_it_as_they_follow_a_narration(self):
        """
        The room reads both; the actor reads only the narration, which is
        what a model-narrated attempt does too. Shape held level on purpose:
        a world that writes its own prose should not read differently from
        one that pays for it.
        """
        self.rule(name="pulling", report="{actor} $pconj(pull) the lever.",
                  effects=[{"type": "create_object", "name": "Brass Token",
                            "location": "room"}])
        mine, theirs = self.pull()
        self.assertIn("Brass Token", theirs)
        self.assertNotIn("Brass Token", mine)

    def test_the_effects_still_land(self):
        """
        A narration is a sentence, never a substitute for what happened. This
        is the failure the early-return cache once had, asserted for the path
        that skips the narrator on purpose.
        """
        from world import verbs

        self.rule(name="pulling", report="{actor} $pconj(pull) the lever.",
                  effects=[{"type": "set_state", "role": "direct",
                            "add": ["pulled"]}])
        self.pull()
        self.assertIn("pulled", verbs.states(self.obj1))


@tag("world")
class WhichWordsWin(Written):

    def test_a_rule_edited_is_read_at_once(self):
        """
        Ahead of the cache, and this is why. A world that paid for prose and
        has since written its own must not go on reading the sentence it
        bought -- and a builder who changes the words has to see the change,
        rather than waiting for a cache to miss.
        """
        rule = self.rule(name="pulling")
        self.pull()             # a model narrates it, and it is cached

        store = dict(getattr(self.root.db, R.ATTR, None) or {})
        store[rule["id"]] = dict(store[rule["id"]],
                                 report="{actor} $pconj(pull). Nothing gives.")
        self.root.db.rules = store

        mine, _theirs = self.pull()
        self.assertIn("Nothing gives", mine)
        self.assertNotIn("rummage", mine)

    def test_and_nothing_is_cached_from_it(self):
        """
        There is no model reply to save, and a saved template would be read
        after the rule it came from had been edited -- which is the bug the
        test above is the other half of.
        """
        from world import attempt as attempt_mod

        self.rule(name="pulling", report="{actor} $pconj(pull) the lever.")
        self.pull()
        self.assertIsNone(attempt_mod._cached_narration(
            {"direct": self.obj1}, "pull", "success", self.char1))

    def test_but_not_for_a_roll_that_went_badly(self):
        """
        A report is one sentence and a contest has four answers. Reading the
        words written for success after a failed roll would say the lever
        came down while `checks.effects_for` fired nothing -- a silent lie
        with prose on top. The narrator takes it instead.

        Not reachable from the menu, which asks for no contest, and no model
        may write a report -- so this is about a document somebody edited,
        which is a door this game leaves open on purpose.
        """
        self.rule(name="pulling",
                  report="{actor} $pconj(pull) the lever, and it gives.",
                  contest={"trait": "might", "difficulty": 99},
                  effects=[{"type": "set_state", "role": "direct",
                            "add": ["pulled"]}])
        # The die, not the arithmetic: `_band` lets a natural twenty succeed
        # however outmatched the actor is, which is the point of rolling and
        # would make this test pass one time in twenty.
        from world import checks, verbs

        with mock.patch.object(checks.random, "randint", return_value=1):
            mine, _theirs = self.pull(replies=finishing(
                declare_action={"applies_to": [{"role": "direct"}]},
                narrate={"actor": "You strain at it, and it holds.",
                         "room": "{actor} $pconj(strain) at it."}))
        self.assertNotIn("pulled", verbs.states(self.obj1))
        self.assertNotIn("and it gives", mine)
        self.assertIn("it holds", mine)

    def test_a_rule_that_speaks_for_itself_still_does(self):
        """
        `describe` returns the appearance and is the whole of the answer;
        words written over the top would talk across the thing being
        described. Unchanged, and asserted so it stays that way.
        """
        self.rule(name="looking at it", action="look",
                  report="{actor} $pconj(pull) the lever.",
                  effects=[{"type": "describe", "role": "direct"}])
        from world import effects as fx

        self.assertTrue(fx.speaks_for_itself([{"type": "describe",
                                               "role": "direct"}]))


@tag("world")
class WhatHappensInstead(Written):
    """
    The other phase that answers somebody, and the one that most needed it:
    with no words of its own it replies with the rule's *name*, which is a
    line about the rule rather than about the room.
    """

    def test_it_reads_the_rule_name_when_nothing_is_written(self):
        self.rule(name="The lever is welded shut.", phase=R.INSTEAD)
        mine, _theirs = self.pull()
        self.assertIn("The lever is welded shut.", mine)

    def test_and_the_words_when_there_are_some(self):
        self.rule(name="welded", phase=R.INSTEAD,
                  report="{actor} $pconj(heave), and the lever does not move.")
        mine, theirs = self.pull()
        self.assertIn("You heave, and the lever does not move.", mine)
        self.assertIn("Char heaves, and the lever does not move.", theirs)
        self.assertNotIn("welded", mine)


@tag("world")
class HeldToWhatATemplateMustBe(Written):

    def test_it_is_repaired_on_the_way_in(self):
        """
        What is stored is rendered afresh for every reader for ever, so a
        blemish in it is permanent. `becomes` rules were repaired already;
        the field is no longer theirs alone.
        """
        rule = self.rule(name="pulling", report="pulls the lever.")
        stored = R.get(self.root, rule["id"])
        self.assertIn("{actor}", stored["report"])
        self.assertIn("$pconj(pull)", stored["report"])

    def test_and_survives_being_exported_and_read_back(self):
        from world import exchange

        self.rule(name="pulling", report="{actor} $pconj(pull) the lever.")
        doc = exchange.document(self.root)
        written = [rule for rule in (doc.get("vocabulary") or {}).get("rules")
                   or [] if rule.get("report")]
        self.assertTrue(written, "the words did not travel with the rule")
        self.assertIn("$pconj(pull)", written[0]["report"])


@tag("unit")
class WhatTheScanMakesOfIt(GameTest):
    """
    A carry-out that changes nothing and says something is not the silent
    success `inert` counts. The translation into the shape the scan reads has
    to carry the words across for it to see them at all -- it did not, and
    every such rule was counted as doing nothing.
    """

    def registers(self, **rule):
        rule.setdefault("phase", "carry_out")
        rule.setdefault("scope", {"world": True})
        rule.setdefault("listed", True)
        rule.setdefault("action", "smile")
        rule.setdefault("effects", [])
        return {"verb_rules": {}, "state_vocabulary": {}, "state_groups": {},
                "kind_specs": {}, "rules": {"r1": dict(rule, id="r1")}}

    def test_words_are_carried_into_the_shape_the_scan_reads(self):
        from world import rulecheck

        translated = rulecheck.as_verb_rule({"phase": "carry_out",
                                             "report": "{actor} $pconj(smile)."})
        self.assertEqual(translated["report"], "{actor} $pconj(smile).")

    def test_and_a_rule_that_says_something_is_not_inert(self):
        from world import rulecheck

        found = rulecheck.scan(self.registers(report="{actor} $pconj(smile)."))
        self.assertEqual(found["inert"], [])

    def test_while_one_that_says_nothing_still_is(self):
        from world import rulecheck

        self.assertEqual(rulecheck.scan(self.registers())["inert"],
                         ["smile#r1"])


@tag("world")
class AGambleWrittenByHand(Written):
    """
    A contest a builder declared, rolled the way a model's is.

    The point of the pair is that there is no second path: `attempt` reads
    the carry-out rule's `contest` into `checks.wanted` without caring who
    wrote it, which is what makes "everything a model can do, a builder can
    do" a fact about the code rather than a promise.
    """

    def forcing(self, **extra):
        from world import traits

        traits.register(self.root, "might", means="how strong they are")
        return self.rule(
            name="forcing it", contest={"trait": "might", "difficulty": 14},
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["pulled"]}], **extra)

    def rolled(self, die):
        from world import checks

        return mock.patch.object(checks.random, "randint", return_value=die)

    def test_a_bad_roll_runs_no_effects(self):
        from world import verbs

        self.forcing()
        with self.rolled(1):
            self.pull()
        self.assertNotIn("pulled", verbs.states(self.obj1))

    def test_a_good_roll_runs_them(self):
        from world import verbs

        self.forcing()
        with self.rolled(20):
            self.pull()
        self.assertIn("pulled", verbs.states(self.obj1))

    def test_and_the_actor_is_shown_the_numbers(self):
        """
        A world has to be examinable from inside it: a verb that always fails
        and one that is merely hard look identical until the roll is shown.
        """
        self.forcing()
        with self.rolled(20):
            mine, _theirs = self.pull()
        self.assertIn("might", mine)
        self.assertIn("14", mine)
