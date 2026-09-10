"""
The attempt pipeline, running rulebooks.

Everything here goes through `attempt.attempt` with a scripted model reply, so
what is tested is the road a real command takes: gather, instead, check, carry
out, after, report.

The one to read first is `TheGuardThatBecameARule`. "You must be able to act"
was a hard-coded line at the top of the pipeline, because there was nowhere for
a rule about every verb to live. It is now a world-scope check rule with no
action, seeded into every world, and it refuses exactly as it used to -- which
is the composition win showing up as deleted code rather than as an argument.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from tests.support import FakeAccount, as_json, immediately, replying
from world import rulebooks as R
from world import attempt as attempt_mod
from world import kinds, standard_rules, verbs


@tag("world")
class RunningTheAttempt(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        self.obj1.key = "Book"
        self.obj1.db.affordances = {"read": True}
        # Settle what a book admits up front. Otherwise the pipeline asks a
        # model whether this sort of thing can be read at all -- correctly,
        # and it is tested where it belongs -- and every script here would
        # need an extra reply that has nothing to do with what is being
        # tested.
        self.obj1.db.kinds = ["book.n.01"]
        for verb in ("read", "order"):
            kinds.admit(self.root, self.obj1.db.kinds, verb, True)

    def try_it(self, raw, *replies):
        """One attempt, with the model answering from a script."""
        said = []
        answers = replies or (as_json({"valid": True, "effects": []}),
                              as_json({"actor": "You do it.",
                                       "room": "{actor} does it."}))
        with immediately(), replying(*answers):
            attempt_mod.attempt(
                self.char1, raw, FakeAccount(),
                on_message=lambda actor_text, room_text=None:
                    said.append(actor_text or ""))
        return " ".join(s for s in said if s)


@tag("world")
class TheGuardThatBecameARule(RunningTheAttempt):

    def test_the_standard_rules_are_seeded_on_first_use(self):
        self.try_it("read book")
        names = [r["name"] for r in R.all_rules(self.root)
                 if standard_rules.is_standard(r)]
        self.assertIn("you must be able to act", names)

    def test_seeding_twice_adds_nothing(self):
        standard_rules.seed(self.root)
        before = len(R.all_rules(self.root))
        standard_rules.seed(self.root)
        self.assertEqual(len(R.all_rules(self.root)), before)

    def test_a_dead_actor_is_refused_by_a_rule_rather_than_by_a_guard(self):
        verbs.register_state(self.root, "dead", group="life_status")
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        said = self.try_it("read book")
        self.assertTrue(said)
        self.assertNotIn("You do it", said)

    def test_and_is_allowed_again_once_it_is_not_true(self):
        verbs.register_state(self.root, "dead", group="life_status")
        verbs.apply_states(self.char1, add=["dead"], world_root=self.root)
        verbs.apply_states(self.char1, remove=["dead"], world_root=self.root)
        self.assertIn("You do it", self.try_it("read book"))

    def test_something_out_of_reach_is_refused(self):
        """
        Inform's basic accessibility rule, and the second thing every world
        now knows without anybody restating it.

        Asserted at the condition rather than through a typed command, and
        the reason is worth recording: `verbs.bind` only ever searches what
        is reachable, so a player cannot name a book inside a shut box in the
        first place -- the attempt never gets a direct object and never
        reaches the check phase. Where the rule earns its keep is a binding
        somebody else supplied: an NPC acting on a remembered thing, or an
        `instead` rule redirecting to the enclosure.
        """
        from world import conditions, relations

        shut = self.obj2
        shut.key = "Strongbox"
        verbs.apply_states(shut, add=["closed"], world_root=self.root)
        self.obj1.move_to(shut, quiet=True)

        self.assertNotIn(self.obj1, relations.reachable(self.char1))
        self.assertIsNone(verbs.bind(self.char1, "book"),
                          "a player cannot name what they cannot reach")

        standard_rules.seed(self.root)
        ctx = conditions.context({"direct": self.obj1}, self.char1, self.root)
        reach = next(r for r in R.all_rules(self.root)
                     if "reach" in r["name"])
        self.assertEqual(
            conditions.unmet(reach["conditions"], ctx),
            "Book is out of reach.")


@tag("world")
class ThePhasesInOrder(RunningTheAttempt):

    def test_a_precondition_from_the_learned_rule_refuses(self):
        said = self.try_it(
            "read book",
            as_json({"valid": True,
                     "requires": {"direct": {"is": ["open"]}},
                     "effects": []}))
        self.assertIn("not open", said)

    def test_a_verb_the_world_refused_says_why(self):
        said = self.try_it(
            "order obj",
            as_json({"valid": False,
                     "reason": "Ordering only makes sense in a tavern."}))
        self.assertIn("tavern", said)

    def test_an_instead_rule_replaces_the_action(self):
        R.add(self.root, R.blank(
            action="read", phase=R.INSTEAD, scope={"world": True},
            name="The letters swim and will not hold still."))
        said = self.try_it("read book")
        self.assertIn("swim", said)
        self.assertNotIn("You do it", said, "processing should have ended")

    def test_a_check_rule_of_the_worlds_own_refuses(self):
        R.add(self.root, R.blank(
            action="read", phase=R.CHECK, scope={"world": True},
            about="direct",
            conditions=[{"subject": "direct", "is": ["legible"]}]))
        self.assertIn("not legible", self.try_it("read book"))

    def test_a_more_specific_check_rule_speaks_first(self):
        """The order is the design; here it decides which refusal is read."""
        R.add(self.root, R.blank(
            action="read", phase=R.CHECK, scope={"world": True},
            conditions=[{"subject": "direct", "is": ["general"]}]))
        R.add(self.root, R.blank(
            action="read", phase=R.CHECK, scope={"kind": "book.n.01"},
            about="direct",
            conditions=[{"subject": "direct", "is": ["specific"]}]))
        said = self.try_it("read book")
        self.assertIn("not specific", said)
        self.assertNotIn("not general", said)

    def test_an_after_rule_fires_once_it_has_worked(self):
        """
        Consequence without a tick. The rule lives on the sort of thing rather
        than inside the verb, which is how a world adds one later.
        """
        R.add(self.root, R.blank(
            action="read", phase=R.AFTER, scope={"world": True},
            name="reading leaves a mark",
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["dog_eared"]}]))
        self.try_it("read book")
        self.assertIn("dog_eared", verbs.states(self.obj1))

    def test_an_after_rule_does_not_fire_when_the_check_refused(self):
        R.add(self.root, R.blank(
            action="read", phase=R.CHECK, scope={"world": True},
            about="direct",
            conditions=[{"subject": "direct", "is": ["legible"]}]))
        R.add(self.root, R.blank(
            action="read", phase=R.AFTER, scope={"world": True},
            effects=[{"type": "set_state", "role": "direct",
                      "add": ["dog_eared"]}]))
        self.try_it("read book")
        self.assertNotIn("dog_eared", verbs.states(self.obj1))

    def test_the_learned_rules_effects_still_land(self):
        self.try_it(
            "read book",
            as_json({"valid": True,
                     "effects": [{"type": "set_state", "role": "direct",
                                  "add": ["read"]}]}),
            as_json({"actor": "You read it.", "room": "{actor} reads."}))
        self.assertIn("read", verbs.states(self.obj1))
