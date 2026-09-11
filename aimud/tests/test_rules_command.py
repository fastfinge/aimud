"""
`rules`, which exists so that "why did that rule win" is never a mystery.

Inform's hardest bug class is rule ordering and its answer is `RULES ON`. This
is the same answer, and the plan makes it a first-version requirement rather
than a later convenience: a world nobody can debug is worse than a world that
cannot launch a spaceship.

Plain prose, one rule to a line, no columns or box-drawing -- the same reason
`score` has none. It is read aloud at least as often as it is looked at.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaCommandTest

from commands.world_cmds import CmdRules
from world import actions
from world import rulebooks as R


@tag("world")
class ListingRules(EvenniaCommandTest):

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True

    def said(self, args=""):
        return self.call(CmdRules(), args)

    def test_outside_a_world_it_says_so(self):
        self.room1.db.is_world_root = False
        self.room1.attributes.remove("world_root")
        self.assertIn("not in a generated world", self.said())

    def test_the_standard_rules_are_there_to_be_read(self):
        said = self.said()
        self.assertIn("you must be able to act", said)
        self.assertIn("standard", said)

    def test_a_worlds_own_rule_is_listed_with_where_it_applies(self):
        R.add(self.root, R.blank(
            action="launch", phase=R.CHECK, scope={"kind": "spacecraft.n.01"},
            name="a ship only launches under power"))
        said = self.said()
        self.assertIn("a ship only launches under power", said)
        self.assertIn("any spacecraft", said)

    def test_one_verb_shows_its_phases_in_order(self):
        R.add(self.root, R.blank(action="launch", phase=R.AFTER,
                                 name="everyone aboard is thrown about"))
        R.add(self.root, R.blank(action="launch", phase=R.CHECK,
                                 name="a ship only launches under power"))
        R.add(self.root, R.blank(action="launch", phase=R.CARRY_OUT,
                                 name="launching takes the ship up"))
        said = self.said("launch")
        self.assertLess(said.index("under power"), said.index("takes the ship"))
        self.assertLess(said.index("takes the ship"),
                        said.index("thrown about"))

    def test_and_says_what_the_verb_takes(self):
        actions.declare(self.root, "launch",
                        [{"role": "direct", "access": "visible",
                          "optional": True}])
        said = self.said("launch")
        self.assertIn("direct", said)
        self.assertIn("visible", said)
        self.assertIn("optional", said)

    def test_an_undeclared_verb_says_that_too(self):
        self.assertIn("nobody has declared", self.said("launch"))

    def test_a_verb_nobody_has_written_a_rule_for_still_has_some(self):
        """
        And that is the answer, not a gap: the standard rules have no action,
        so they are about every verb including the ones nobody has thought
        about yet. A world with no rules of its own is not a world with no
        rules.
        """
        actions.declare(self.root, "launch", [])
        said = self.said("launch")
        self.assertIn("you must be able to act", said)
        self.assertIn("standard", said)

    def test_a_suspended_rule_is_shown_and_marked(self):
        rule = R.add(self.root, R.blank(action="launch",
                                        name="a rule somebody withdrew"))
        R.set_listed(self.root, rule["id"], False)
        said = self.said("launch")
        self.assertIn("a rule somebody withdrew", said)
        self.assertIn("suspended", said)

    def test_a_rule_about_every_verb_is_filed_under_that(self):
        self.assertIn("any action", self.said())

    def test_the_more_specific_rule_is_printed_first(self):
        """What the listing is for: the order, visible."""
        R.add(self.root, R.blank(action="power", scope={"world": True},
                                 name="the general one"))
        R.add(self.root, R.blank(action="power",
                                 scope={"kind": "datapad"}, about="direct",
                                 name="the datapad one"))
        said = self.said("power")
        self.assertLess(said.index("the datapad one"),
                        said.index("the general one"))

    def test_it_reads_as_sentences_rather_than_as_a_table(self):
        """No box-drawing, no aligned columns: it gets read aloud."""
        said = self.said()
        for ugly in ("|", "+--", "===", "___"):
            if ugly == "|":
                continue          # colour codes are |w and friends
            self.assertNotIn(ugly, said)


@tag("world")
class UnsayingWhatAVerbTakes(ListingRules):
    """
    `rules redeclare`, which is the deliberate exception to "first answer
    stands".

    An arity is settled once because every rule about the action was written
    against it, and revising it silently would change what those rules mean
    underneath them. But a world that settled it before the engine could ask a
    question is stuck with an answer to a question nobody put -- which is what
    happened to `respawn` and `resurrect` in the phase 13 playtest, declared
    before an action could say it happens in spite of being dead.

    So the same change, made out loud, by somebody who has decided to make it.
    """

    def test_what_a_verb_takes_can_be_unsaid(self):
        actions.declare(self.root, "respawn", [{"role": "direct"}])
        said = self.said("redeclare respawn")
        self.assertIn("undeclared", said)
        self.assertIsNone(actions.spec(self.root, "respawn"))

    def test_its_rules_are_untouched(self):
        actions.declare(self.root, "respawn", [{"role": "direct"}])
        R.add(self.root, R.blank(action="respawn", phase=R.CARRY_OUT,
                                 name="respawning brings you back"))
        self.said("redeclare respawn")
        self.assertIn("respawning brings you back", self.said("respawn"))

    def test_a_verb_nobody_declared_says_so(self):
        self.assertIn("Nothing has been declared",
                      self.said("redeclare respawn"))

    def test_it_wants_a_verb(self):
        self.assertIn("Which verb", self.said("redeclare"))

    def test_a_waiver_is_printed_where_it_is_set(self):
        """
        The one thing on a declaration that loosens rather than tightens, so
        "why did that work while I was dead" has to be answerable from here.
        """
        actions.declare(self.root, "respawn", [{"role": "direct"}],
                        despite=["acting"])
        self.assertIn("works even when you cannot act",
                      self.said("respawn"))

    def test_and_not_where_it_is_not(self):
        actions.declare(self.root, "shove", [{"role": "direct"}])
        self.assertNotIn("works even when", self.said("shove"))
