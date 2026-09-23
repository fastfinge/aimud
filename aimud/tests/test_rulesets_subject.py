"""
Choosing rulesets: the menu, the subject, and surviving a reset.

The choice has to be reachable three ways, and the three must agree, because
they are one form behind two doors plus the place it is stored:

* from the world wizard, where a world is being made;
* from `edit rulesets`, standing in one;
* and through `lore`, which is what `reset world` rebuilds from -- so a world
  that was built with crafting is rebuilt with crafting.

`CLAUDE.md` says every point in a menu must also be reachable by typing, so
`view rulesets` is tested as a command as well as an entry.
"""

from django.test import tag

from commands import rulesets_subject, subjects, world_subject
from commands.verbs import CmdEdit, CmdView
from tests.base import GameCommandTest
from world import lore, menus, rulesets, sponsor


class _InAWorld(GameCommandTest):
    accounts = True

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.world_description = "A harbour town."
        self.room1.db.is_ai_room = True
        sponsor.claim(self.root, self.account)

    def ctx(self, **data):
        return menus.Context(self.char1, **data)


@tag("world")
class TheSubject(_InAWorld):

    def test_it_is_offered_under_view_and_edit(self):
        for verb in ("view", "edit"):
            keys = [item.key
                    for item in subjects.verb_form(verb).items_for(self.ctx())]
            self.assertIn("rulesets", keys, verb)

    def test_view_rulesets_says_what_is_on_and_what_is_not(self):
        rulesets.seed(self.root)
        said = self.call(CmdView(), "rulesets").lower()
        self.assertIn("standard rules", said)
        self.assertIn("death", said, "what is available is worth seeing too")
        self.assertIn("off", said, "and which of them are not in use")

    def test_the_words_it_answers_to_are_the_parsers_business(self):
        """
        Inside a world the parser only hands a verb command the line when the
        next word names a subject, so `edit ruleset` has to be one of ours and
        `edit the trap` must not be.
        """
        found = next(s for s in subjects.registered()
                     if s.key == "rulesets")
        words = found.words()
        self.assertIn("rulesets", words)
        self.assertIn("ruleset", words)


@tag("world")
class TheForm(_InAWorld):

    def test_every_ruleset_this_server_offers_is_a_toggle(self):
        keys = [item.key
                for item in rulesets_subject.FORM.items_for(self.ctx())]
        self.assertEqual(sorted(keys), sorted(rulesets.available()))

    def test_a_toggle_reads_what_the_world_holds(self):
        rulesets.seed(self.root, ["death"])
        items = {item.key: item
                 for item in rulesets_subject.FORM.items_for(self.ctx())}
        self.assertTrue(items["death"].get(self.ctx()))

    def test_and_switching_one_on_seeds_it(self):
        rulesets.seed(self.root)
        items = {item.key: item
                 for item in rulesets_subject.FORM.items_for(self.ctx())}
        items["death"].set(self.ctx(), True)
        self.assertIn("death", rulesets.chosen(self.root))

    def test_and_switching_it_off_suspends_rather_than_deletes(self):
        from world import rulebooks

        rulesets.seed(self.root, ["death"])
        items = {item.key: item
                 for item in rulesets_subject.FORM.items_for(self.ctx())}
        items["death"].set(self.ctx(), False)
        self.assertNotIn("death", rulesets.chosen(self.root))
        rule = next(r for r in rulebooks.all_rules(self.root)
                    if r["name"] == "no health left is dead")
        self.assertFalse(rule["listed"])

    def test_in_the_wizard_it_writes_to_the_draft_and_no_world(self):
        """
        There is no world yet. The choice has to be collected and applied
        when one is built, which is what `lore.store` does.
        """
        # One context, kept: `menus.Context` copies the draft it is given,
        # which is what the menu does too -- the draft a wizard fills in is
        # the one on its own context, and lives as long as the menu does.
        ctx = self.ctx(draft=world_subject.new_draft("A harbour town."))
        items = {item.key: item
                 for item in rulesets_subject.FORM.items_for(ctx)}
        items["death"].set(ctx, True)
        self.assertIn("death", ctx.draft["rulesets"])
        self.assertNotIn("death", rulesets.chosen(self.root),
                         "a draft must not touch the world it was opened in")

    def test_a_new_draft_starts_with_the_defaults(self):
        self.assertEqual(world_subject.new_draft()["rulesets"],
                         rulesets.defaults())

    def test_the_wizard_offers_the_same_form(self):
        ctx = self.ctx(draft=world_subject.new_draft())
        entry = next(item for item in world_subject.WIZARD.items_for(ctx)
                     if item.key == "rulesets")
        self.assertIs(entry.form, rulesets_subject.FORM)


@tag("world")
class SurvivingAReset(_InAWorld):
    """
    What `reset world` rebuilds from is the spec, so the spec has to carry it.

    A reset is a world built again rather than the one that was there carried
    over, which is why the rulesets come back *at their defaults*: whatever
    was suspended in the old world is not a decision about the new one.
    """

    def test_the_spec_carries_what_the_world_was_built_with(self):
        rulesets.seed(self.root, ["death"])
        self.assertIn("death", lore.spec_of(self.root)["rulesets"])

    def test_a_world_with_no_choice_recorded_reads_as_the_defaults(self):
        self.assertEqual(lore.spec_of(self.root)["rulesets"],
                         rulesets.defaults())

    def test_storing_a_spec_seeds_what_it_names(self):
        lore.store(self.root, {"description": "A forge town.",
                               "rulesets": ["death"]})
        self.assertIn("death", rulesets.chosen(self.root))

    def test_a_spec_that_says_nothing_about_them_changes_nothing(self):
        """
        `lore.store` leaves a field a partial spec does not mention alone, and
        rulesets are no exception -- an older caller passing a bare
        description must not strip a world of what it was built with.
        """
        rulesets.seed(self.root, ["death"])
        lore.store(self.root, {"description": "Still a forge town."})
        self.assertIn("death", rulesets.chosen(self.root))

    def test_the_round_trip(self):
        rulesets.seed(self.root, ["death"])
        spec = lore.spec_of(self.root)
        # Rebuilt into a world of its own, the way `reset world` does it:
        # the new world is generated first and the old one removed after.
        from evennia import create_object

        fresh = create_object("typeclasses.rooms.Room", key="Rebuilt")
        fresh.db.is_world_root = True
        fresh.db.world_root = fresh
        lore.store(fresh, spec)
        self.assertEqual(rulesets.chosen(fresh), rulesets.chosen(self.root))
