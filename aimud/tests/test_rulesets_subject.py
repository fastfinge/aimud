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


@tag("world")
class UntickingOneAndSaving(_InAWorld):
    """
    The soak bug: unticking a ruleset in `edit world` appeared to work and
    changed nothing, so the menu showed it on again next time.

    `seed` only ever adds, which is right for it -- it is what a world calls
    on its way past to be sure its rules are there, and must not take anything
    away by being asked twice. Saying which set a world should hold is a
    different act, and it was being done in two places that each did half of
    it: `edit rulesets` forgot what was dropped and the wizard did not.
    """

    def test_the_wizard_save_drops_what_was_unticked(self):
        rulesets.seed(self.root, ["crafting"])
        spec = lore.spec_of(self.root)
        spec["rulesets"] = [n for n in spec["rulesets"] if n != "crafting"]
        lore.store(self.root, spec)
        self.assertNotIn("crafting", rulesets.chosen(self.root))

    def test_and_the_menu_then_shows_it_off(self):
        """What the player actually saw: it came back ticked."""
        rulesets.seed(self.root, ["crafting"])
        spec = lore.spec_of(self.root)
        spec["rulesets"] = [n for n in spec["rulesets"] if n != "crafting"]
        lore.store(self.root, spec)
        items = {item.key: item
                 for item in rulesets_subject.FORM.items_for(self.ctx())}
        self.assertFalse(items["crafting"].get(self.ctx()))

    def test_both_doors_do_the_same_thing(self):
        """One function behind them, so they cannot differ again."""
        rulesets.seed(self.root, ["crafting"])
        rulesets.apply_choice(self.root, [rulesets.DEFAULT])
        self.assertNotIn("crafting", rulesets.chosen(self.root))

    def test_what_something_kept_still_requires_is_kept(self):
        """
        Unticking what a ruleset you are keeping rests on is not a thing
        anybody can mean, so `default` survives being left out.
        """
        rulesets.seed(self.root, ["crafting"])
        rulesets.apply_choice(self.root, ["crafting"])
        self.assertIn(rulesets.DEFAULT, rulesets.chosen(self.root))


@tag("world")
class AskingBeforeChangingAWorldThatExists(_InAWorld):

    def toggle(self, ctx=None):
        items = {item.key: item for item
                 in rulesets_subject.FORM.items_for(ctx or self.ctx())}
        return items["crafting"]

    def test_a_world_being_made_is_not_asked(self):
        """There is no history to lose, so the wizard stays out of the way."""
        ctx = self.ctx(draft=world_subject.new_draft("A harbour town."))
        self.assertIsNone(self.toggle(ctx).confirmation(ctx, True))

    def test_a_world_already_built_is(self):
        rulesets.seed(self.root)
        asked = self.toggle().confirmation(self.ctx(), True)
        self.assertIsNotNone(asked)
        self.assertEqual(asked[0], "change_ruleset")

    def test_and_switching_one_off_says_what_stays(self):
        rulesets.seed(self.root, ["crafting"])
        _key, question = self.toggle().confirmation(self.ctx(), False)
        self.assertIn("stop at once", question)
        self.assertIn("reset world", question)

    def test_the_confirmation_is_one_a_player_can_switch_off(self):
        """Every `confirm` key needs an entry, or nobody can stop being asked."""
        from world import preferences

        self.assertIn("change_ruleset",
                      [key for key, _label, _why in preferences.CONFIRMATIONS])
