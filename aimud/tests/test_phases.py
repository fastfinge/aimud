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
from world import kinds, standard_rules, verb_gen, verbs


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

    def learned(self, verb, rule, *roles):
        """
        What this world already worked out about a verb, written down.

        A learned verb rule is one rule per verb per world -- the old shape,
        which `rulebooks.from_verb_rule` bridges into phase rules. Stored
        directly here rather than scripted as a model reply, because since
        phase 8 nothing asks for that shape: a verb nobody has settled is
        asked for rulebook rules instead. What is under test is the bridge,
        and the bridge reads what is stored.
        """
        shape = {role: True for role in (roles or ("direct",))}
        verb_gen.store_rule(self.root, verbs.rule_key(verb, shape), rule)

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
        self.learned("read", {"valid": True,
                              "requires": {"direct": {"is": ["open"]}},
                              "effects": []})
        self.assertIn("not open", self.try_it("read book"))

    def test_a_verb_the_world_refused_says_why(self):
        self.learned("order", {
            "valid": False,
            "reason": "Ordering only makes sense in a tavern."})
        self.assertIn("tavern", self.try_it("order obj"))

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
        self.learned("read", {"valid": True,
                              "effects": [{"type": "set_state",
                                           "role": "direct",
                                           "add": ["read"]}]})
        self.try_it("read book",
                    as_json({"actor": "You read it.",
                             "room": "{actor} reads."}))
        self.assertIn("read", verbs.states(self.obj1))


@tag("world")
class RulesAboutAThingWhenThereIsNoThing(RunningTheAttempt):
    """
    The standard rules apply to every action, including the ones that name
    nothing.

    "You must be able to reach what you act on" has `action: null`, so a verb
    that takes no object at all gathered it -- and `reachable_by` answers a
    subject that is not there with "There is nothing here to do that to." So
    `smile` was refused, in words that read as though the game had not
    understood a word it had understood perfectly: a rule about a thing, asked
    about no thing.

    The fix is a `when` guard rather than a special case in the predicate,
    because a rule that should not apply should not be gathered. That also
    keeps `rules` honest: the guard is printable and the reason is readable.
    """

    def test_the_reach_rule_is_guarded_on_something_being_named(self):
        standard_rules.seed(self.root)
        reach = next(r for r in R.all_rules(self.root) if "reach" in r["name"])
        self.assertEqual(reach["when"],
                         [{"subject": "direct", "unbound": False}])

    def test_it_is_not_gathered_for_a_verb_that_named_nothing(self):
        standard_rules.seed(self.root)
        gathered = R.for_attempt(self.root, "smile", {}, self.char1,
                                 phase=R.CHECK)
        self.assertNotIn("you must be able to reach what you act on",
                         [r["name"] for r in gathered])

    def test_and_is_gathered_the_moment_something_is(self):
        standard_rules.seed(self.root)
        gathered = R.for_attempt(self.root, "read", {"direct": self.obj1},
                                 self.char1, phase=R.CHECK)
        self.assertIn("you must be able to reach what you act on",
                      [r["name"] for r in gathered])

    def test_smiling_is_not_refused_for_reaching_nothing(self):
        said = self.try_it("smile",
                           as_json({"applies_to": []}),
                           as_json({"rules": []}),
                           as_json({"actor": "You smile.",
                                    "room": "{actor} smiles."}))
        self.assertNotIn("nothing here to do that to", said)
        self.assertIn("You smile", said)


@tag("world")
class WhenTwoNounsAreBothStrangers(RunningTheAttempt):
    """
    A noun nothing answers to is promoted, not refused -- the room describes a
    blackboard and nothing in the database does, so reaching for it makes it
    real. That is right, and it used to be done one noun at a time: conjure the
    first, then discover the second also needs inventing, then give up.

    So "call mom on the phone", in a world with neither, left a `mom` standing
    in the dungeon and answered "You cannot make sense of that here" -- which
    both wasted a call on an object nobody wanted and blamed the player's
    sentence for the world's not having a phone in it.
    """

    def test_nothing_is_made_when_two_things_would_have_to_be(self):
        before = len(self.room1.contents)
        said = self.try_it("call mom on phone",
                           as_json({"applies_to": [{"role": "direct"}]}))
        self.assertEqual(len(self.room1.contents), before,
                         "nothing should have been conjured")
        self.assertIn("no mom", said)
        self.assertIn("no phone", said)

    def test_and_the_refusal_is_about_the_world_rather_than_the_sentence(self):
        said = self.try_it("call mom on phone",
                           as_json({"applies_to": [{"role": "direct"}]}))
        self.assertNotIn("make sense", said)


@tag("world")
class WhenTheStandardRulesThemselvesChange(RunningTheAttempt):
    """
    `worldreset` is this project's usual answer to a change in shape, and it is
    the right one for a world's *own* rules: nobody can say what a world meant
    by something it wrote, so a converted world is worth less than a fresh one.

    These are not a world's own rules. They are the engine's, written in one
    file, and a world holding last week's copy of them is holding a bug rather
    than a decision -- which is why the seed carries a number and a world a
    version behind has them replaced.
    """

    def test_a_current_world_is_left_alone(self):
        standard_rules.seed(self.root)
        before = len(R.all_rules(self.root))
        self.assertEqual(standard_rules.seed(self.root), [])
        self.assertEqual(len(R.all_rules(self.root)), before)

    def test_a_world_a_version_behind_gets_the_new_ones(self):
        standard_rules.seed(self.root)
        setattr(self.root.db, standard_rules.VERSION_ATTR,
                standard_rules.VERSION - 1)
        self.assertTrue(standard_rules.seed(self.root))
        standing = [r for r in R.all_rules(self.root)
                    if standard_rules.is_standard(r)]
        self.assertEqual(len(standing), len(standard_rules.STANDARD),
                         "the old copies should have gone, not doubled up")

    def test_and_keeps_what_it_wrote_for_itself(self):
        standard_rules.seed(self.root)
        R.add(self.root, R.blank(action="read", phase=R.CHECK,
                                 name="a rule this world wrote"))
        setattr(self.root.db, standard_rules.VERSION_ATTR,
                standard_rules.VERSION - 1)
        standard_rules.seed(self.root)
        self.assertIn("a rule this world wrote",
                      [r["name"] for r in R.all_rules(self.root)])

    def test_a_declaration_the_engine_makes_is_replaced_too(self):
        """
        `actions.declare` is first-answer-wins on purpose, so a world that
        guessed `put` before this file declared it would keep the guess for
        ever -- which is the bug rather than the fix.
        """
        from world import actions

        standard_rules.seed(self.root)
        setattr(self.root.db, standard_rules.VERSION_ATTR,
                standard_rules.VERSION - 1)
        actions.declare(self.root, "put", [])          # the stale guess
        store = dict(getattr(self.root.db, actions.ATTR, None) or {})
        store["put"] = dict(store["put"], applies_to=[
            {"role": "source", "access": "touchable", "optional": False}])
        setattr(self.root.db, actions.ATTR, store)

        standard_rules.seed(self.root)
        declared = actions.spec(self.root, "put")
        self.assertTrue(all(role["optional"]
                            for role in declared["applies_to"]))

    def test_and_a_declaration_the_world_made_is_not(self):
        from world import actions

        standard_rules.seed(self.root)
        actions.declare(self.root, "launch", [{"role": "direct"}])
        setattr(self.root.db, standard_rules.VERSION_ATTR,
                standard_rules.VERSION - 1)
        standard_rules.seed(self.root)
        self.assertIsNotNone(actions.spec(self.root, "launch"))
