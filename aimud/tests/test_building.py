"""
Building a world by hand: the maker table, the picker, and every form in it.

Three things are being held down here, and they are not the same thing.

**The engine additions.** `menus.Picker` offers what a world already holds and
"none of these -- make one", and `menus.Picked` is how the form that makes one
answers the field that was waiting. Driven a line at a time through the harness
in `tests/test_menus.py`, because the keys are the contract.

**The vocabularies cover each other.** Every effect in `effects.VOCABULARY` is
reachable from the effect menu, every predicate in `conditions.PREDICATES` from
the condition menu, every goal type in `goals.CONDITION_TYPES` from the goal
menu. A vocabulary entry no menu can reach is one a hand-built world simply
cannot use, and it fails by being absent rather than by breaking -- which is
the failure this game is most careful about everywhere else.

**Nothing here calls a model.** The whole point of building by hand is that a
world can be made, and then used as a fixture, for nothing. `NoModels` patches
the LLM layer to raise, and the forms are driven to completion underneath it.
"""

from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameCommandTest, GameTest
from tests.test_menus import Driving
from world import folds, making, menus


# ---------------------------------------------------------------------------
# A world to build in
# ---------------------------------------------------------------------------

class Building(Driving):
    """A character standing in a world they made, with a menu harness."""

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.root.db.world_description = "A test world."
        self.room1.db.world_root = self.root
        self.room1.db.is_ai_room = True
        making.forget()

    def build(self, form, lines, **data):
        """Open a form, type each line, and answer with everything said."""
        data.setdefault("world_root", self.root)
        self.open(form, **data)
        said = []
        for line in lines:
            said.append(self.type(line))
        return "\n".join(said)

    def draft(self, **fields):
        """
        A context with a filled-in draft, for calling a keeper directly.

        A form is driven through the menu where the *menu* is what is being
        tested -- the picker, a group made from inside a condition. Where what
        is being tested is what gets written, typing blind numbers into a
        guided form tests the numbering rather than the writing, and breaks
        the next time a field is added above it.
        """
        return _Draft(fields, self.root, self.char1)


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

@tag("unit")
class TheTable(SimpleTestCase):

    def setUp(self):
        making.forget()

    def test_every_module_registers_something(self):
        """A maker module that fails to import is a silent hole. See making.py."""
        keys = {maker.key for maker in making.registered()}
        for wanted in ("kind", "attribute", "condition", "group", "word",
                       "action", "rule", "item", "room", "way", "person",
                       "quest"):
            self.assertIn(wanted, keys)

    def test_no_two_makers_share_a_word(self):
        seen = {}
        for maker in making.registered():
            for word in maker.words:
                self.assertNotIn(word, seen,
                                 f"{word!r} is claimed by {maker.key} and "
                                 f"{seen.get(word)}")
                seen[word] = maker.key

    def test_no_maker_word_is_a_menu_key(self):
        """Refused at registration, not found when a menu is drawn."""
        for maker in making.registered():
            for word in (maker.key,) + maker.words:
                self.assertNotIn(word, menus.RESERVED, word)

    def test_and_one_that_is_cannot_be_registered(self):
        with self.assertRaises(ValueError):
            making.Maker("exit", ("exit",), "Ways out")

    def test_every_maker_becomes_a_subject(self):
        from commands import making_subject

        subjects = {subject.key for subject in making_subject.SUBJECTS}
        for maker in making.registered():
            if any(maker.answers(verb) for verb in making.VERBS):
                self.assertIn(maker.key, subjects)

    def test_every_maker_that_can_be_made_has_a_first_field(self):
        """`create kind datapad` needs somewhere to put the word."""
        for maker in making.registered():
            if maker.new is None:
                continue
            items = maker.new.items
            items = items if isinstance(items, (list, tuple)) else []
            if not items:
                continue      # built per context; covered by its own test
            first = next((item for item in items
                          if isinstance(item, menus.Field) and item.required),
                         None)
            self.assertIsNotNone(first, maker.key)

    def test_vocabulary_cannot_be_deleted(self):
        """Not a gap: see making.py `remove`, and docs/player-building.md 3.1."""
        for key in ("kind", "attribute", "condition", "action"):
            self.assertIsNone(making.get(key).remove, key)

    def test_what_is_furnished_can_be(self):
        for key in ("rule", "item", "way", "person", "quest"):
            self.assertIsNotNone(making.get(key).remove, key)


@tag("unit")
class VocabulariesCoverEachOther(SimpleTestCase):
    """A vocabulary entry no menu can reach cannot be used by hand."""

    def test_every_effect_is_reachable(self):
        from world import effects
        from world.makers import rules

        self.assertEqual(set(effects.VOCABULARY), set(rules.EFFECT_FIELDS))

    def test_and_so_is_every_field_it_takes(self):
        """
        The gap that cost a builder the kind of the thing their rule made.

        Knowing an effect exists is not enough: `create_object` was reachable
        and asked for three of the six things it reads, so the sort of thing
        it made was guessed from the head noun of whatever it was called.
        Anything left out on purpose is in `NOT_ASKED` with its reason, which
        makes a gap a decision somebody wrote down rather than one nobody saw.
        """
        from world import effects
        from world.makers import rules

        for etype, known in effects.VOCABULARY.items():
            asked = {rules.STORED_AS.get(field, field)
                     for field in rules.EFFECT_FIELDS[etype]}
            for field in known["fields"]:
                if (etype, field) in rules.NOT_ASKED:
                    continue
                with self.subTest(effect=etype, field=field):
                    self.assertIn(field, asked)

    def test_and_nothing_is_asked_for_that_no_effect_takes(self):
        """The other direction: a field nothing reads is a field nobody fills."""
        from world import effects
        from world.makers import rules

        for etype, fields in rules.EFFECT_FIELDS.items():
            reads = set(effects.VOCABULARY[etype]["fields"])
            for field in fields:
                with self.subTest(effect=etype, field=field):
                    self.assertIn(rules.STORED_AS.get(field, field), reads)

    def test_every_deliberate_omission_says_why(self):
        from world import effects
        from world.makers import rules

        for (etype, field), why in rules.NOT_ASKED.items():
            with self.subTest(effect=etype, field=field):
                self.assertIn(etype, effects.VOCABULARY)
                self.assertIn(field, effects.VOCABULARY[etype]["fields"])
                self.assertGreater(len(why), 40, "say why, at length")

    def test_the_prose_and_the_list_agree(self):
        """`takes` is read by `help`; `fields` is read by the menu."""
        from world import effects

        for etype, known in effects.VOCABULARY.items():
            for field in known["fields"]:
                with self.subTest(effect=etype, field=field):
                    self.assertIn(field, known["takes"])

    def test_every_predicate_is_reachable(self):
        from world import conditions
        from world.makers import rules

        reachable = {predicate
                     for _key, _label, members in rules.PREDICATE_GROUPS
                     for predicate, _said, _takes in members}
        self.assertEqual(set(conditions.PREDICATES), reachable)

    def test_every_goal_type_is_reachable(self):
        from world import goals
        from world.makers import errands

        reachable = {value for value, _said, _fields in errands.GOAL_TYPES}
        plain = set(goals.CONDITION_TYPES) - set(goals.COMBINATOR_TYPES)
        self.assertEqual(plain, reachable)

    def test_a_quests_rewards_are_narrower_than_a_verbs(self):
        from world import quests
        from world.makers import errands

        class _Ctx:
            draft = {}
            data = {}

        offered = {value for value, _label in errands.reward_options(_Ctx())}
        self.assertEqual(offered, set(quests.QUEST_EFFECTS))


# ---------------------------------------------------------------------------
# The engine additions
# ---------------------------------------------------------------------------

def _colours():
    return ["red", "blue"]


PICK_ONE = menus.Form(
    key="pick-one", title="Pick a colour",
    items=[
        menus.Picker(
            "colour", "Colour",
            options=lambda ctx: [(name, name) for name in _colours()],
            make=lambda ctx: MAKE_COLOUR,
            none="None of these -- make one"),
        menus.Action("show", "Show it",
                     run=lambda ctx: f"chose {ctx.draft.get('colour')}"),
    ],
)

MAKE_COLOUR = menus.Form(
    key="make-colour", title="A new colour", guided=True,
    items=[
        menus.Field("name", "Name", required=True),
        menus.Action("keep", "Keep it", run=lambda ctx: menus.Picked(
            _colours().append(ctx.draft["name"]) or ctx.draft["name"],
            f"{ctx.draft['name']} it is.")),
    ],
)


@tag("unit")
class PickingOrMakingOne(Driving):

    def test_a_picker_offers_what_is_there(self):
        self.open(PICK_ONE)
        shown = self.type("1")
        self.assertIn("red", shown)
        self.assertIn("blue", shown)

    def test_and_the_chance_to_make_one(self):
        self.open(PICK_ONE)
        self.assertIn("make one", self.type("1"))

    def test_making_one_comes_back_with_it(self):
        self.open(PICK_ONE)
        self.type("1")            # the picker
        self.type("3")            # none of these -- make one
        self.type("green")        # its name
        self.type("keep")
        self.assertIn("green it is", "\n".join(self.said))
        # And the field it came back to is set, so the form can finish.
        self.assertIn("chose green", self.type("show"))

    def test_the_make_entry_survives_a_filter_that_matches_nothing(self):
        """Somebody who narrowed a long list to nothing most needs it."""
        long_one = menus.Form(
            key="pick-many", title="Pick",
            items=[menus.Picker(
                "colour", "Colour",
                options=lambda ctx: [(f"c{n}", f"colour {n}")
                                     for n in range(20)],
                make=lambda ctx: MAKE_COLOUR,
                none="None of these -- make one")])
        self.open(long_one)
        self.type("1")
        shown = self.type("zzz")
        self.assertIn("make one", shown)

    def test_a_picked_with_nobody_waiting_simply_goes_back(self):
        self.open(MAKE_COLOUR, draft={"name": "puce"})
        self.type("keep")
        self.assertIn("puce it is", "\n".join(self.said))

    def test_a_submenu_can_answer_a_list_in_the_draft(self):
        adder = menus.Form(
            key="add-one", title="Add", guided=True,
            items=[menus.Field("word", "Word", required=True),
                   menus.Action("keep", "Keep",
                                run=lambda ctx: menus.Picked(
                                    ctx.draft["word"], "added"))])
        holder = menus.Form(
            key="holder", title="Holder",
            items=[menus.Submenu("words", "Words", adder, into="words",
                                 append=True),
                   menus.Action("show", "Show",
                                run=lambda ctx: str(ctx.draft.get("words")))])
        self.open(holder)
        self.type("1")
        self.type("alpha")
        self.type("keep")
        self.type("1")
        self.type("beta")
        self.type("keep")
        shown = self.type("show")
        self.assertIn("alpha", shown)
        self.assertIn("beta", shown)

    def test_a_list_field_can_take_one_out_again(self):
        dropper = making.listing_field(
            "words", "Words",
            menus.Form(key="add", title="Add", guided=True,
                       items=[menus.Field("word", "Word", required=True),
                              menus.Action("keep", "Keep",
                                           run=lambda ctx: menus.Picked(
                                               ctx.draft["word"], "added"))]),
            lambda ctx, entry: str(entry))
        holder = menus.Form(key="holder2", title="Holder", items=[dropper])
        self.open(holder, draft={"words": ["alpha"]})
        shown = self.type("1")
        self.assertIn("alpha", shown)
        self.assertIn("Take out", shown)
        self.assertIn("Taken out", self.type("2"))


# ---------------------------------------------------------------------------
# Nothing here costs anything
# ---------------------------------------------------------------------------

@tag("unit")
class NoModels(Building):
    """
    The constraint the whole plan exists to keep: building calls no model.

    Not a preference. A world somebody typed is meant to be a fixture that
    later features are tested against -- for nothing, and the same every time
    -- and the moment one of these forms reaches for a model that stops being
    true. See docs/player-building.md 12.
    """

    def setUp(self):
        super().setUp()
        from world import llm

        def refuse(*args, **kwargs):
            raise AssertionError("building must never call a model")

        for name in ("fetch", "converse", "complete"):
            if hasattr(llm, name):
                patcher = mock.patch.object(llm, name, refuse)
                patcher.start()
                self.addCleanup(patcher.stop)

    def test_a_kind_can_be_made(self):
        from world import kinds
        from world.makers import vocabulary

        settled, said = vocabulary.keep_kind(self.draft(
            word="cup", sense="cup.n.01",
            affordances=[{"verb": "drink", "yes": True}]))
        self.assertEqual(settled, "cup.n.01")
        self.assertIsNotNone(kinds.spec(self.root, "cup.n.01"))
        self.assertIn("drink", said)

    def test_an_attribute_can_be_made(self):
        from world import traits
        from world.makers import vocabulary

        slug, _said = vocabulary.keep_attribute(self.draft(
            slug="discoveries", name="Discoveries",
            means="what they have found", trait_type="counter", base=0))
        self.assertEqual(slug, "discoveries")
        self.assertIn("discoveries", traits.vocabulary(self.root))

    def test_a_rule_can_be_filed(self):
        from world import rulebooks
        from world.makers import rules

        rule_id, _said = rules.keep_rule(self.draft(
            name="a lit lamp cannot be lit again", action="light",
            phase="check", scope="world",
            conditions=[{"subject": "direct", "lacks": ["lit"]}]))
        self.assertIsNotNone(rulebooks.get(self.root, rule_id))

    def test_an_errand_can_be_written(self):
        from world import quests
        from world.makers import errands

        spec_id, _said = errands.keep_quest(self.draft(
            title="Fetch the chalk",
            goal=[{"type": "holds", "object": "chalk"}], wire=False))
        self.assertIsNotNone(quests.spec(self.root, spec_id))

    def test_a_condition_and_its_group_can_be_made_together(self):
        """The picker's whole point: the group is made from inside the form."""
        from world import verbs
        from world.makers import vocabulary

        self.open(vocabulary.NEW_CONDITION_STATE, world_root=self.root,
                  interactive_only=False)
        # Not `lit`: the game seeds that one into a group of its own, and a
        # seeded group is not a world's to redefine. An invented condition is
        # the case this exists for.
        self.type("brewed")                   # the one required field
        shown = self.type("group")            # open the group picker
        self.assertIn("make a new group", shown)
        self.type("new")                      # none of these -- make one
        self.type("brewing")                  # what the group is called
        self.type("yes")                      # only one at a time
        self.type("keep")
        self.assertIn("brewing", verbs.groups(self.root))
        # And the picker it came back to is now set to it, so the condition
        # can be kept without ever leaving the form.
        self.type("keep")
        self.assertEqual(
            (verbs.vocabulary(self.root).get("brewed") or {}).get("group"),
            "brewing")


@tag("unit")
class MakingVocabulary(Building):

    def test_a_kind_keeps_what_can_be_done_to_it(self):
        from world import affordances as af
        from world import kinds
        from world.makers import vocabulary

        settled, _said = vocabulary.keep_kind(self.draft(
            word="lantern", sense="",
            affordances=[{"verb": "light", "yes": True},
                         {"verb": "eat", "yes": False}]))
        spec = kinds.spec(self.root, settled)
        self.assertIn("light", af.afforded(spec["affordances"]))
        self.assertIn("eat", af.refused(spec["affordances"]))

    def test_a_kind_already_settled_is_not_quietly_revised(self):
        """First answer stands: the rules filed against it were written on it."""
        from world import kinds
        from world.makers import vocabulary

        kinds.remember(self.root, "lantern", {"light": True})
        with self.assertRaises(menus.Refuse) as caught:
            vocabulary.keep_kind(self.draft(word="lantern", sense=""))
        self.assertIn("already knows", str(caught.exception))

    def test_an_attribute_refuses_a_word_a_condition_holds(self):
        """Both say what is true of a thing now; two answers is no answer."""
        from world import verbs
        from world.makers import vocabulary

        verbs.register_state(self.root, "warm", means="it is warm")
        with self.assertRaises(menus.Refuse) as caught:
            vocabulary.keep_attribute(self.draft(slug="warm"))
        self.assertIn("cannot be both", str(caught.exception))

    def test_a_word_fold_reaches_a_kind(self):
        from world import kinds

        kinds.remember(self.root, "raygun", {"fire": True},
                       under="weapon.n.01")
        said = folds.add(self.root, "blaster", "raygun")
        self.assertIn("now reads", said)
        self.assertEqual(folds.nouns_of(self.root).get("blaster"), "raygun")

    def test_a_fold_may_not_move_english(self):
        said = folds.add(self.root, "get", "look")
        self.assertIn("already English", said)

    def test_a_fold_onto_nothing_says_so(self):
        said = folds.add(self.root, "blaster", "nonesuch")
        self.assertIn("knows nothing", said)


@tag("unit")
class FoldedWordsAreFound(GameTest):
    """A folded noun reads as another name the thing answers to."""

    loose_objects = 1

    def setUp(self):
        super().setUp()
        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root

    def a_raygun(self):
        """Named nothing like "blaster", so only the fold can reach it."""
        from world import kinds

        kinds.remember(self.root, "raygun", {}, under="weapon.n.01")
        self.obj1.key = "Old Service Pistol"
        self.obj1.db.kinds = ["raygun"]
        return self.obj1

    def test_a_folded_word_matches_a_thing_of_that_kind(self):
        from world import naming

        gun = self.a_raygun()
        folds.fold(self.root, "blaster", "raygun", noun=True)
        found, score = naming.best_match(self.char1, "blaster",
                                         candidates=[gun])
        self.assertIs(found, gun)
        self.assertGreater(score, 0)

    def test_and_the_fold_is_what_makes_it_certain(self):
        """
        Without one, "blaster" reaches a pistol only the way a typo does.

        `naming` scores a merely plausible match low on purpose and a real
        name at the top, and the difference is what decides whether the game
        acts on it or asks. A fold puts an invented word in the second class.
        """
        from world import naming

        gun = self.a_raygun()
        _found, loose = naming.best_match(self.char1, "blaster",
                                          candidates=[gun])
        folds.fold(self.root, "blaster", "raygun", noun=True)
        _found, certain = naming.best_match(self.char1, "blaster",
                                            candidates=[gun])
        self.assertEqual(certain, 1.0)
        self.assertGreater(certain, loose)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@tag("unit")
class MakingARule(Building):

    def test_a_condition_comes_out_in_the_stored_shape(self):
        from world.makers import rules

        ctx = self.draft(subject="direct", group="state", predicate="is",
                         states=["lit"])
        clause, said = rules.keep_condition(ctx)
        self.assertEqual(clause["subject"], "direct")
        self.assertEqual(clause["is"], ["lit"])
        self.assertIn("lit", said)

    def test_a_condition_that_cannot_be_stored_is_refused(self):
        from world.makers import rules

        ctx = self.draft(subject="direct", group="state", predicate="is",
                         states=[])
        with self.assertRaises(menus.Refuse):
            rules.keep_condition(ctx)

    def test_an_effect_is_refused_a_name_that_is_a_condition(self):
        from world import verbs
        from world.makers import rules

        verbs.register_state(self.root, "broken", means="it is broken")
        ctx = self.draft(type="create_object", name="Broken Cup")
        with self.assertRaises(menus.Refuse):
            rules.keep_effect(ctx)

    def test_an_effect_is_refused_a_word_list_the_world_has_not_got(self):
        from world.makers import rules

        ctx = self.draft(type="create_object", name="Brass Cup",
                         description="It smells of {brine}.")
        with self.assertRaises(menus.Refuse):
            rules.keep_effect(ctx)

    def test_an_effect_field_asked_under_another_name_is_stored_right(self):
        """`exit` quits every menu, so the field is `way` and stores as exit."""
        from world.makers import rules

        ctx = self.draft(type="set_exit", way="north", to="Kitchen")
        effect, _said = rules.keep_effect(ctx)
        self.assertEqual(effect["exit"], "north")
        self.assertNotIn("way", effect)

    def test_a_rule_is_filed_through_rulebooks(self):
        from world import rulebooks
        from world.makers import rules

        ctx = self.draft(name="a lit lamp cannot be lit again",
                         action="light", phase="check", scope="world",
                         about="direct",
                         conditions=[{"subject": "direct", "lacks": ["lit"]}])
        rule_id, said = rules.keep_rule(ctx)
        stored = rulebooks.get(self.root, rule_id)
        self.assertEqual(stored["phase"], "check")
        self.assertEqual(stored["action"], "light")
        self.assertIn("filed", said)

    def test_a_rule_that_asks_and_does_nothing_is_refused(self):
        from world.makers import rules

        ctx = self.draft(name="nothing at all", phase="check", scope="world")
        with self.assertRaises(menus.Refuse):
            rules.keep_rule(ctx)

    def test_a_becomes_rule_drops_the_verb(self):
        from world import rulebooks
        from world.makers import rules

        ctx = self.draft(name="at ten discoveries", action="light",
                         phase="becomes", scope="world",
                         conditions=[{"subject": "actor",
                                      "trait": "discoveries", "min": 10}],
                         effects=[{"type": "narrate"}])
        rule_id, _said = rules.keep_rule(ctx)
        self.assertIsNone(rulebooks.get(self.root, rule_id)["action"])

    def test_the_phase_nudges_without_choosing(self):
        from world.makers import rules

        checking = self.draft(phase="check", action="light",
                              effects=[{"type": "narrate"}])
        self.assertIn("changes something", rules.phase_nudge(checking))

        empty = self.draft(phase="carry_out", action="light", effects=[])
        self.assertIn("does nothing", rules.phase_nudge(empty))

        anonymous = self.draft(phase="check", action="", effects=[])
        self.assertIn("every action", rules.phase_nudge(anonymous))

    def test_the_phase_shows_where_the_rule_would_sit(self):
        from world import rulebooks
        from world.makers import rules

        rulebooks.add(self.root, rulebooks.blank(
            action="light", phase="check", name="you must be holding it"))
        ctx = self.draft(name="mine", action="light", phase="check",
                         scope="world")
        order = rules.firing_order(ctx)
        self.assertIn("you must be holding it", order)
        self.assertIn("mine", order)

    def test_a_scope_is_offered_most_particular_first(self):
        from world.makers import rules

        class _Ctx:
            draft = {}
            data = {}

            def __init__(self, caller):
                self.caller = caller
                self.character = caller

        offered = [value for value, _label
                   in rules.scope_options(_Ctx(self.char1))]
        self.assertEqual(offered[-1], "world")


# ---------------------------------------------------------------------------
# What a world is furnished with
# ---------------------------------------------------------------------------

@tag("unit")
class MakingThings(Building):
    loose_objects = 1

    def test_an_item_is_made_through_the_same_writer_a_model_uses(self):
        from world import kinds
        from world.makers import things

        kinds.remember(self.root, "cup.n.01", {"drink": True})
        things.keep_item(self.draft(
            name="Blue Ceramic Cup", description="A plain blue cup.",
            kind="cup.n.01", where="room"))
        made = [obj for obj in self.room1.contents
                if obj.key == "Blue Ceramic Cup"]
        self.assertTrue(made)
        self.assertIn("cup.n.01", kinds.of(made[0]))

    def test_an_item_is_refused_a_name_that_is_a_condition(self):
        """One checker for a rule's effect and for somebody typing alike."""
        from world import kinds, verbs
        from world.makers import things

        verbs.register_state(self.root, "broken", means="it is broken")
        kinds.remember(self.root, "cup.n.01", {})
        with self.assertRaises(menus.Refuse) as caught:
            things.keep_item(self.draft(
                name="Broken Cup", description="A cup.",
                kind="cup.n.01", where="room"))
        self.assertIn("condition", str(caught.exception))

    def test_an_item_is_refused_a_word_list_this_world_has_not_got(self):
        from world import kinds
        from world.makers import things

        kinds.remember(self.root, "cup.n.01", {})
        with self.assertRaises(menus.Refuse) as caught:
            things.keep_item(self.draft(
                name="Brass Cup", description="It smells of {brine}.",
                kind="cup.n.01", where="room"))
        self.assertIn("brine", str(caught.exception))

    def test_editing_reaches_only_what_is_in_front_of_you(self):
        from commands.subjects import thing_here

        found, complaint = thing_here(self.char1, "nonesuch")
        self.assertIsNone(found)
        self.assertIn("in front of you", complaint)

    def test_a_room_opens_off_this_one(self):
        from world import coords, worldgen
        from world.makers import things

        coords.place(self.root, self.room1, coords.ORIGIN)
        free = worldgen.openable_directions(self.root, self.room1)
        self.assertTrue(free)
        ctx = _Draft({"direction": free[0], "name": "The Cellar",
                      "description": "Cold and dark.", "zone": "",
                      "room_type": "cellar"}, self.root, self.char1)
        room_id, said = things.keep_room(ctx)
        self.assertIn("The Cellar", said)
        ways = [obj.key for obj in self.room1.contents
                if getattr(obj, "destination", None)]
        self.assertIn(free[0], ways)

    def test_a_person_is_made_without_a_model(self):
        from world.makers import things

        ctx = _Draft({"name": "Hob the Alchemist",
                      "description": "Ink-stained and cheerful."},
                     self.root, self.char1)
        npc_id, said = things.keep_npc(ctx)
        self.assertIn("Hob the Alchemist", said)
        here = [obj.key for obj in self.room1.contents]
        self.assertIn("Hob the Alchemist", here)


class _Draft:
    """A context for a keeper called directly, without a menu around it."""

    def __init__(self, draft, root, caller):
        self.draft = dict(draft)
        self.data = {"world_root": root}
        self.dirty = False
        self.caller = caller
        self.character = caller
        self.account = None
        self.session = None


# ---------------------------------------------------------------------------
# Errands
# ---------------------------------------------------------------------------

@tag("unit")
class MakingAnErrand(Building):

    def setUp(self):
        super().setUp()
        from evennia import create_object

        self.npc = create_object("typeclasses.npcs.NPC", key="Hob",
                                 location=self.room1)
        self.npc.db.is_npc = True
        self.npc.db.world_root = self.root

    def write(self, **fields):
        from world.makers import errands

        fields.setdefault("title", "Fetch the chalk")
        fields.setdefault("goal", [{"type": "holds", "object": "chalk"}])
        fields.setdefault("givers", [{"npc": str(self.npc.id),
                                      "description": ""}])
        fields.setdefault("wire", False)
        return errands.keep_quest(_Draft(fields, self.root, self.char1))

    def test_an_errand_is_written_and_kept_on_the_world(self):
        from world import quests

        spec_id, said = self.write()
        self.assertIn("is written", said)
        self.assertEqual(quests.spec(self.root, spec_id)["title"],
                         "Fetch the chalk")

    def test_an_errand_with_no_testable_goal_is_refused(self):
        with self.assertRaises(menus.Refuse):
            self.write(goal=[])

    def test_writing_it_can_write_the_rule_that_offers_it(self):
        from world import rulebooks

        _spec_id, said = self.write(wire=True)
        self.assertIn("greeting them", said)
        offered = [rule for rule in rulebooks.all_rules(self.root)
                   if any(effect.get("type") == "offer_quest"
                          for effect in rule.get("effects") or [])]
        self.assertEqual(len(offered), 1)
        self.assertEqual(offered[0]["phase"], rulebooks.INSTEAD)

    def test_the_spec_survives_its_giver(self):
        """It belongs to the world; the giver is a field on it. Docs 10.1."""
        from world import quests

        spec_id, _said = self.write()
        self.npc.delete()
        record = quests.spec(self.root, spec_id)
        self.assertIsNotNone(record)
        self.assertEqual(quests.givers_of(self.root, record), [])
        self.assertIn(record, quests.orphaned(self.root))

    def test_each_giver_keeps_its_own_words(self):
        from evennia import create_object
        from world import quests

        other = create_object("typeclasses.npcs.NPC", key="Bram",
                              location=self.room1)
        other.db.is_npc = True
        spec_id, _said = self.write(
            description="Someone should fetch the chalk.",
            givers=[{"npc": str(self.npc.id), "description": ""},
                    {"npc": str(other.id),
                     "description": "The chalk. Before the bell."}])
        record = quests.spec(self.root, spec_id)
        said = dict((npc.key, own) for npc, own
                    in quests.givers_of(self.root, record))
        self.assertEqual(said["Hob"], "")
        self.assertIn("Before the bell", said["Bram"])

    def test_an_offer_uses_the_givers_own_words(self):
        from world import quests

        spec_id, _said = self.write(
            description="The general wording.",
            givers=[{"npc": str(self.npc.id),
                     "description": "Mine, in my own voice."}])
        record = quests.spec(self.root, spec_id)
        own = quests.givers_of(self.root, record)[0][1]
        quest = quests.offer_spec(self.npc, self.char1, record,
                                  description=own)
        self.assertIsNotNone(quest)
        self.assertEqual(quest["description"], "Mine, in my own voice.")
        self.assertEqual(quest["spec"], spec_id)

    def test_and_falls_back_to_the_errands_own(self):
        from world import quests

        spec_id, _said = self.write(description="The general wording.")
        record = quests.spec(self.root, spec_id)
        quest = quests.offer_spec(self.npc, self.char1, record)
        self.assertEqual(quest["description"], "The general wording.")

    def test_a_non_repeatable_errand_is_not_offered_twice(self):
        from world import quests

        spec_id, _said = self.write(repeatable=False)
        record = quests.spec(self.root, spec_id)
        allowed, _why = quests.available(self.char1, self.root, record)
        self.assertTrue(allowed)
        quests.record_finished(self.char1, spec_id)
        allowed, why = quests.available(self.char1, self.root, record)
        self.assertFalse(allowed)
        self.assertIn("already", why)

    def test_a_repeatable_one_is(self):
        from world import quests

        spec_id, _said = self.write(repeatable=True, cooldown=0)
        record = quests.spec(self.root, spec_id)
        quests.record_finished(self.char1, spec_id)
        allowed, _why = quests.available(self.char1, self.root, record)
        self.assertTrue(allowed)

    def test_a_chain_waits_for_what_comes_first(self):
        from world import quests

        first_id, _said = self.write(title="The first")
        second_id, _said = self.write(title="The second", after=[first_id])
        second = quests.spec(self.root, second_id)
        allowed, why = quests.available(self.char1, self.root, second)
        self.assertFalse(allowed)
        self.assertIn(first_id, why)
        quests.record_finished(self.char1, first_id)
        allowed, _why = quests.available(self.char1, self.root, second)
        self.assertTrue(allowed)

    def test_the_offer_effect_hands_it_over(self):
        from world import effects, quests

        spec_id, _said = self.write()
        effects.apply(self.char1, self.room1,
                      [{"type": "offer_quest", "quest": spec_id,
                        "role": "actor", "name_role": "direct"}],
                      bound={"direct": self.npc}, world_root=self.root)
        offered = quests.offered_to(self.char1)
        self.assertIsNotNone(offered)
        self.assertEqual(offered["title"], "Fetch the chalk")

    def test_and_does_nothing_when_it_may_not(self):
        from world import effects, quests

        spec_id, _said = self.write()
        quests.record_finished(self.char1, spec_id)
        effects.apply(self.char1, self.room1,
                      [{"type": "offer_quest", "quest": spec_id,
                        "role": "actor", "name_role": "direct"}],
                      bound={"direct": self.npc}, world_root=self.root)
        self.assertIsNone(quests.offered_to(self.char1))

    def test_the_generator_is_offered_the_pool(self):
        from world import lookups

        self.write()
        self.assertIn("list_errands", lookups.all_tools())

    def test_and_a_way_to_use_one(self):
        from world import quest_gen

        spec_id, _said = self.write()
        tool = quest_gen.use_quest_tool()

        class _Ctx:
            world_root = self.root

        self.assertTrue(tool.offered(_Ctx()))
        schema = tool.parameters(_Ctx())
        self.assertIn(spec_id,
                      schema["properties"]["quest"]["enum"])


# ---------------------------------------------------------------------------
# The named way out of "first answer stands"
# ---------------------------------------------------------------------------

@tag("unit")
class ForgettingAKind(Building):
    loose_objects = 1

    def setUp(self):
        super().setUp()
        from world import kinds

        # `canonical` grounds it in the dictionary, so what is stored is the
        # sense and that is what everything else has to name.
        self.lantern = kinds.canonical("lantern")
        kinds.remember(self.root, "lantern", {"light": True})
        self.obj1.db.kinds = [self.lantern]
        self.obj1.db.ai_commands = {"light": "It catches."}

    def test_editing_cannot_touch_what_the_rules_were_written_against(self):
        from world.makers import vocabulary

        form = vocabulary.edit_kind(self.root, self.lantern)
        fields = {item.key for item in form.items}
        self.assertNotIn("affordances", fields)

    def test_but_it_says_where_to_go_instead(self):
        from world.makers import vocabulary

        class _Ctx:
            draft = {}
            data = {}
            caller = None
            character = None

        said = vocabulary.edit_kind(self.root, self.lantern).intro_for(_Ctx())
        self.assertIn("reset kind", said)

    def test_the_question_says_what_it_costs_first(self):
        from world.makers import vocabulary

        asked = vocabulary.reset_kind_question(self.root, self.lantern)
        self.assertIn("1 thing", asked)

    def test_and_forgetting_drops_the_narrations_written_about_it(self):
        from world import kinds
        from world.makers import vocabulary

        said = vocabulary.reset_kind(self.root, self.lantern)
        self.assertIsNone(kinds.spec(self.root, self.lantern))
        self.assertFalse(self.obj1.db.ai_commands)
        self.assertIn("rules are untouched", said)

    def test_forgetting_leaves_the_rules_alone(self):
        from world import rulebooks
        from world.makers import vocabulary

        rulebooks.add(self.root, rulebooks.blank(
            action="light", scope={"kind": self.lantern},
            name="about lanterns"))
        vocabulary.reset_kind(self.root, self.lantern)
        self.assertEqual(len(rulebooks.all_rules(self.root)), 1)


@tag("unit")
class LookingAWordUp(Building):
    """`view term`: the reading half of grounding invented vocabulary."""

    def report(self, word):
        from commands.term_subject import term_report

        return term_report(self.char1, word, self.root)

    def test_a_word_with_senses_shows_them_and_what_they_are_sorts_of(self):
        said = self.report("chest")
        self.assertIn("chest.n.02", said)
        self.assertIn("container.n.01", said)

    def test_a_word_the_dictionary_has_never_heard_of_says_so_kindly(self):
        said = self.report("cinderstone")
        self.assertIn("never heard of it", said)
        self.assertIn("hangs beneath", said)

    def test_it_says_what_this_world_has_done_with_the_word(self):
        from world import kinds

        kinds.remember(self.root, "lantern", {"light": True})
        self.assertIn("a sort of thing here", self.report("lantern"))

    def test_and_says_when_it_has_done_nothing(self):
        self.assertIn("not used it for anything", self.report("lantern"))

    def test_it_costs_nothing_and_needs_no_world(self):
        from commands.term_subject import term_report

        self.assertIn("chest", term_report(self.char1, "chest", None))


# ---------------------------------------------------------------------------
# The commands themselves
# ---------------------------------------------------------------------------

@tag("world")
class TheCommands(GameCommandTest):
    """
    Every maker on the command line, which is the half a menu test cannot see.

    The standing rule is that every point in a menu is also typeable
    (docs/commands-and-settings.md §3.5), and a maker's subject is generated
    rather than written, so what is being checked is that the generator wired
    all four verbs to the right place -- not that any one form works.
    """

    accounts = True

    def setUp(self):
        super().setUp()
        from world import sponsor

        self.root = self.room1
        self.root.db.is_world_root = True
        self.room1.db.world_root = self.root
        self.room1.db.world_description = "A test world."
        self.room1.db.is_ai_room = True
        sponsor.claim(self.root, self.account)
        making.forget()

    def offered(self, verb):
        from commands import subjects

        ctx = menus.Context(self.char1)
        return [item.key for item in subjects.verb_form(verb).items_for(ctx)]

    def test_create_offers_every_maker(self):
        offered = self.offered("create")
        for key in ("kind", "attribute", "condition", "rule", "item", "room",
                    "person", "quest", "word", "action"):
            self.assertIn(key, offered)

    def test_and_view_offers_what_can_be_read(self):
        offered = self.offered("view")
        for key in ("kind", "attribute", "condition", "rule", "quest", "term"):
            self.assertIn(key, offered)

    def test_a_listing_says_how_to_make_the_first_one(self):
        from commands.verbs import CmdView

        said = self.call(CmdView(), "kinds")
        self.assertIn("create kind", said)

    def test_a_listing_shows_what_the_world_holds(self):
        from commands.verbs import CmdView
        from world import kinds

        kinds.remember(self.root, "lantern", {"light": True})
        self.assertIn("lantern", self.call(CmdView(), "kinds"))

    def test_view_one_of_them(self):
        from commands.verbs import CmdView
        from world import kinds

        settled = kinds.canonical("lantern")
        kinds.remember(self.root, "lantern", {"light": True})
        said = self.call(CmdView(), f"kind {settled}")
        self.assertIn("can be light", said)
        self.assertIn("rule", said)        # what depends on it

    def test_somebody_else_may_read_but_not_build(self):
        from commands.verbs import CmdCreate, CmdView

        self.root.db.world_creator = self.account2
        self.assertIn("Only whoever made", self.call(CmdCreate(), "kind"))
        self.assertNotIn("Only whoever made", self.call(CmdView(), "kinds"))

    def test_view_term_costs_nothing_and_answers_anybody(self):
        from commands.verbs import CmdView

        self.root.db.world_creator = self.account2
        said = self.call(CmdView(), "term chest")
        self.assertIn("chest.n.02", said)

    def test_deleting_a_rule_asks_first(self):
        from commands.verbs import CmdDelete
        from world import rulebooks

        rule = rulebooks.add(self.root, rulebooks.blank(
            action="light", name="a rule"))
        said = self.call(CmdDelete(), f"rule {rule['id']}")
        self.assertIn("Delete the rule", said)
        self.assertIsNotNone(rulebooks.get(self.root, rule["id"]))

    def test_and_goes_ahead_when_it_is_answered_in_advance(self):
        from commands.verbs import CmdDelete
        from world import rulebooks

        rule = rulebooks.add(self.root, rulebooks.blank(
            action="light", name="a rule"))
        self.call(CmdDelete(), f"rule {rule['id']} yes")
        self.assertIsNone(rulebooks.get(self.root, rule["id"]))

    def test_resetting_a_kind_asks_and_says_what_it_costs(self):
        from commands.verbs import CmdReset
        from world import kinds

        settled = kinds.canonical("lantern")
        kinds.remember(self.root, "lantern", {"light": True})
        said = self.call(CmdReset(), f"kind {settled}")
        self.assertIn("Forget what this world settled", said)
        self.assertIsNotNone(kinds.spec(self.root, settled))

    def test_a_line_that_gives_everything_needs_no_menu(self):
        """The rule every command keeps, now kept by every maker. Docs 4."""
        from commands.verbs import CmdCreate
        from world import token_lists

        said = self.call(CmdCreate(),
                         "tokens smell: what docks smell of = brine | tar")
        self.assertIn("This world now keeps", said)
        self.assertIsNotNone(token_lists.get(self.root, "smell"))

    def test_and_a_line_that_gives_part_says_what_is_missing(self):
        """For a caller with no menu, which is what the old command did."""
        from commands.verbs import CmdCreate
        from world import token_lists

        said = self.call(CmdCreate(), "tokens smell")
        self.assertIsNone(token_lists.get(self.root, "smell"))
        self.assertIn("still needs its entries", said)
        self.assertIn("create tokens", said)

    def test_and_says_it_for_every_maker(self):
        ctx = menus.Context(self.char1, world_root=self.root)
        for maker in making.registered():
            if maker.new is None:
                continue
            with self.subTest(maker=maker.key):
                finishing = making.finisher(maker.new, ctx)
                self.assertIsNotNone(
                    finishing,
                    f"{maker.key}'s form has no finishing action, so a line "
                    f"giving everything cannot be kept without a menu")

    def test_anybody_here_may_add_a_pronoun_set(self):
        """How somebody is spoken about is theirs, not the world's. Maker.owner."""
        from commands.verbs import CmdCreate

        self.root.db.world_creator = self.account2
        self.assertNotIn("Only whoever made",
                         self.call(CmdCreate(), "pronouns"))
        self.assertIn("Only whoever made", self.call(CmdCreate(), "tokens"))

    def test_the_parser_still_lets_the_world_have_its_own_verbs(self):
        """`create kind` is ours; `create a distraction` is the world's."""
        from commands import subjects

        self.assertTrue(subjects.claims("create", "kind"))
        self.assertTrue(subjects.claims("create", "quest a name"))
        self.assertFalse(subjects.claims("create", "a distraction"))


# ---------------------------------------------------------------------------
# A hand-built world actually runs
# ---------------------------------------------------------------------------

@tag("world")
class WhatIsBuiltIsWhatRuns(Building):
    """
    The point of the whole thing: a rule typed by a person is an ordinary rule.

    Everything above tests that the forms write the right records. This tests
    the thing that would make all of that worthless -- that the records are
    the ones the game reads. Nothing here goes near a menu; it builds through
    the keepers and then asks the rulebook.
    """

    loose_objects = 1

    def test_a_hand_built_rule_is_gathered_for_the_attempt_it_is_about(self):
        from world import kinds, rulebooks, verbs
        from world.makers import rules, vocabulary

        # A sort of thing, a condition, and a rule about both.
        settled, _said = vocabulary.keep_kind(self.draft(
            word="lantern", sense="",
            affordances=[{"verb": "light", "yes": True}]))
        verbs.register_state(self.root, "lit", means="it is giving light")
        rule_id, _said = rules.keep_rule(self.draft(
            name="a lit lamp cannot be lit again", action="light",
            phase="check", scope=f"kind:{settled}", about="direct",
            conditions=[{"subject": "direct", "lacks": ["lit"]}]))

        self.obj1.db.kinds = [settled]
        found = rulebooks.gather(self.root, "light",
                                bound={"direct": self.obj1},
                                actor=self.char1)
        self.assertIn(rule_id, [rule["id"] for rule in found])

    def test_and_is_not_gathered_for_something_else(self):
        from world import rulebooks, verbs
        from world.makers import rules, vocabulary

        settled, _said = vocabulary.keep_kind(self.draft(
            word="lantern", sense="",
            affordances=[{"verb": "light", "yes": True}]))
        verbs.register_state(self.root, "lit", means="it is giving light")
        rule_id, _said = rules.keep_rule(self.draft(
            name="about lanterns", action="light", phase="check",
            scope=f"kind:{settled}", about="direct",
            conditions=[{"subject": "direct", "lacks": ["lit"]}]))

        self.obj1.db.kinds = ["cup.n.01"]
        found = rulebooks.gather(self.root, "light",
                                 bound={"direct": self.obj1},
                                 actor=self.char1)
        self.assertNotIn(rule_id, [rule["id"] for rule in found])

    def test_a_hand_built_rules_conditions_evaluate(self):
        from world import conditions, verbs
        from world.makers import rules

        verbs.register_state(self.root, "lit", means="it is giving light")
        clause, _said = rules.keep_condition(self.draft(
            subject="direct", group="state", predicate="lacks",
            states=["lit"]))
        ctx = conditions.context(bound={"direct": self.obj1},
                                 actor=self.char1, world_root=self.root)
        self.assertTrue(conditions.evaluate(clause, ctx))
        verbs.apply_states(self.obj1, add=["lit"], world_root=self.root)
        self.assertFalse(conditions.evaluate(clause, ctx))

    def test_a_hand_built_effect_applies(self):
        from world import effects, verbs
        from world.makers import rules

        verbs.register_state(self.root, "lit", means="it is giving light")
        effect, _said = rules.keep_effect(self.draft(
            type="set_state", role="direct", add=["lit"]))
        effects.apply(self.char1, self.room1, [effect],
                      bound={"direct": self.obj1}, world_root=self.root)
        self.assertIn("lit", verbs.states(self.obj1))

    def test_a_hand_built_attribute_can_be_moved_by_a_hand_built_effect(self):
        from world import effects, traits
        from world.makers import rules, vocabulary

        vocabulary.keep_attribute(self.draft(
            slug="discoveries", means="what they have found",
            trait_type="counter", base=0))
        effect, _said = rules.keep_effect(self.draft(
            type="set_trait", role="actor", trait="discoveries", change=1))
        effects.apply(self.char1, self.room1, [effect],
                      bound={}, world_root=self.root)
        self.assertEqual(traits.value(self.char1, "discoveries"), 1)


@tag("world")
class EveryFormDraws(Building):
    """
    Every maker's form opens and draws, in an empty world and a furnished one.

    Cheap, and it catches the one class of mistake the rest of this file
    cannot: a form's `items` or a label is a function of the context, so a
    mistake in one is invisible until somebody opens that menu. An empty world
    is the case that breaks them -- a picker over a register with nothing in
    it, a listing of things that are not there.
    """

    loose_objects = 1

    def furnish(self):
        from evennia import create_object
        from world import coords, kinds, traits, verbs

        kinds.remember(self.root, "lantern", {"light": True})
        traits.register(self.root, "discoveries", means="what they found")
        verbs.register_state(self.root, "lit", means="it is giving light")
        coords.place(self.root, self.room1, coords.ORIGIN)
        npc = create_object("typeclasses.npcs.NPC", key="Hob",
                            location=self.room1)
        npc.db.is_npc = True
        from world.makers import errands

        errands.keep_quest(self.draft(
            title="An errand", goal=[{"type": "holds", "object": "chalk"}],
            givers=[{"npc": str(npc.id), "description": ""}], wire=False))

    def draw(self, form, **data):
        data.setdefault("world_root", self.root)
        menu = self.open(form, **data)
        self.assertIsNotNone(menu)
        drawn = menu.render()
        self.type("q")
        return drawn

    def test_in_an_empty_world(self):
        for maker in making.registered():
            if maker.new is None:
                continue
            with self.subTest(maker=maker.key):
                self.assertTrue(self.draw(maker.new))

    def test_and_in_a_furnished_one(self):
        self.furnish()
        for maker in making.registered():
            if maker.new is None:
                continue
            with self.subTest(maker=maker.key):
                self.assertTrue(self.draw(maker.new))

    def test_and_every_listing_draws(self):
        from commands.making_subject import _view_form

        self.furnish()
        for maker in making.registered():
            if not maker.answers("view"):
                continue
            with self.subTest(maker=maker.key):
                self.assertTrue(self.draw(_view_form(maker)))

    def test_and_every_choose_menu_draws(self):
        from commands.making_subject import _delete_menu, _edit_menu

        self.furnish()
        ctx = menus.Context(self.char1, world_root=self.root)
        for maker in making.registered():
            with self.subTest(maker=maker.key):
                if maker.answers("edit"):
                    self.assertTrue(self.draw(_edit_menu(maker, ctx)))
                if maker.answers("delete"):
                    self.assertTrue(self.draw(_delete_menu(maker)))

    def test_and_the_bare_verb_menus_draw(self):
        from commands import subjects

        self.furnish()
        for verb in ("create", "edit", "delete", "view", "reset"):
            with self.subTest(verb=verb):
                self.assertTrue(self.draw(subjects.verb_form(verb)))


@tag("world")
class OfferingAnErrandNeedsTwoPeople(Building):
    """
    Who asks and who is asked are two questions, and conflating them is silent.

    `_resolve` falls back from `name_role` to `role`, which for this effect
    would make the giver and the taker the same person -- and an effect that
    quietly does nothing is worse than one that refuses, because a refusal can
    be read.
    """

    def setUp(self):
        super().setUp()
        from evennia import create_object
        from world.makers import errands

        self.npc = create_object("typeclasses.npcs.NPC", key="Hob",
                                 location=self.room1)
        self.npc.db.is_npc = True
        self.spec_id, _said = errands.keep_quest(self.draft(
            title="Fetch the chalk",
            goal=[{"type": "holds", "object": "chalk"}],
            givers=[{"npc": str(self.npc.id), "description": ""}],
            wire=False))

    def offer(self, **effect):
        from world import effects, quests

        effects.apply(self.char1, self.room1,
                      [dict({"type": "offer_quest", "quest": self.spec_id},
                            **effect)],
                      bound={"direct": self.npc}, world_root=self.root)
        return quests.offered_to(self.char1)

    def test_the_giver_defaults_to_what_is_being_acted_on(self):
        """Which is what a rule built from the menus leaves it as."""
        offered = self.offer(role="actor")
        self.assertIsNotNone(offered)
        self.assertEqual(offered["giver"], "Hob")

    def test_and_may_be_named(self):
        offered = self.offer(role="actor", name_role="direct")
        self.assertIsNotNone(offered)

    def test_an_errand_this_world_does_not_hold_offers_nothing(self):
        from world import effects, quests

        effects.apply(self.char1, self.room1,
                      [{"type": "offer_quest", "quest": "q999",
                        "role": "actor"}],
                      bound={"direct": self.npc}, world_root=self.root)
        self.assertIsNone(quests.offered_to(self.char1))


@tag("world")
class TypingItAllOnOneLine(Building):
    """
    `create kind datapad` puts the word where the form wants it.

    The field is named on the maker rather than worked out from the form,
    because half these forms build their items from the context -- there is
    no list to look in, and iterating one crashed. Checked for every maker so
    a new one cannot quietly take nothing on the line.
    """

    def test_every_maker_says_where_the_line_goes(self):
        for maker in making.registered():
            if maker.new is None:
                continue
            with self.subTest(maker=maker.key):
                self.assertTrue(maker.opens_with or maker.opens,
                                f"{maker.key} takes nothing on the line")

    def test_and_it_lands_in_the_draft(self):
        for maker in making.registered():
            if maker.new is None or not maker.opens_with:
                continue
            with self.subTest(maker=maker.key):
                self.assertEqual(maker.opening_draft("something"),
                                 {maker.opens_with: "something"})

    def test_and_names_fields_the_form_actually_has(self):
        ctx = menus.Context(self.char1, world_root=self.root)
        for maker in making.registered():
            if maker.new is None:
                continue
            with self.subTest(maker=maker.key):
                keys = {item.key for item in maker.new.items_for(ctx)}
                for named in maker.opening_draft("something"):
                    self.assertIn(named, keys)



    def test_a_kind_opens_with_its_word_filled_in(self):
        kind = making.get("kind")
        self.build(kind.new, [], draft=kind.opening_draft("datapad"))
        self.assertIn("datapad", " ".join(self.said))


@tag("world")
class NoTwoChoicesShareAName(Building):
    """
    A verb's own menu gathers entries from every subject that answers it.

    Two entries answering to one word is not an error anywhere -- `_pick`
    simply takes the first -- so it has to be looked for.
    """

    def test_across_every_verb_menu(self):
        from commands import subjects

        ctx = menus.Context(self.char1, world_root=self.root)
        for verb in subjects.VERBS:
            seen = {}
            for item in subjects.verb_form(verb).items_for(ctx):
                for name in item.names():
                    with self.subTest(verb=verb, name=name):
                        self.assertNotIn(
                            name, seen,
                            f"{verb}: {name!r} is claimed by {item.key} and "
                            f"{seen.get(name)}")
                    seen[name] = item.key


@tag("world")
class WhatThePortSurfaced(Building):
    """
    Two things that were quietly broken until word lists and pronoun sets
    moved onto the table, and one that was only ever half true.

    Worth their own class because none of them is about the port: they are
    about the table being asked to carry something it did not shape, which is
    the only way to find out what it was assuming.
    """

    def test_a_form_opened_on_its_own_still_closes_when_it_says_to(self):
        """
        `Picked` used to swallow the action's `after`.

        A maker's form answers with the same `Picked` whether a picker opened
        it or `create tokens` did. With nobody waiting it has to behave as the
        ordinary action it is, or every form that said `after=CLOSE` quietly
        stopped closing.
        """
        from world.makers import vocabulary

        self.open(vocabulary.NEW_TOKENS, world_root=self.root)
        self.type("1")
        self.type("smell")
        self.type("3")
        self.type("brine | tar")
        self.type("keep")
        self.assertIn("This world now keeps", " ".join(self.said))
        self.assertFalse(self.is_open)

    def test_and_a_picker_can_make_a_pronoun_set_and_come_back_with_it(self):
        """
        Which it could not, because that form answered with a string.

        The NPC being built by hand offers this world's pronoun sets and the
        chance to add one; before the port the added set was registered and
        then dropped on the floor, and the picker stayed empty.
        """
        from world import pronouns
        from world.makers import things

        picker = next(item for item in things._npc_items(
            menus.Context(self.char1, world_root=self.root))
            if item.key == "pronouns")
        form = menus.Form(key="holder", title="Holder", items=[picker])
        self.open(form, world_root=self.root)
        self.type("1")
        self.type("new")
        for answer in ("ze", "zir", "zir", "zirs", "zirself"):
            self.type(answer)
        self.type("1")
        self.type("keep")
        self.assertIn("ze", pronouns.vocabulary(self.root))
        # And the picker is set to it, which is the half that was missing.
        shown = self.type("l")
        self.assertIn("ze", shown)

    def test_a_maker_that_is_not_the_world_owners_says_so(self):
        self.assertFalse(making.get("pronouns").owner)
        for key in ("tokens", "kind", "rule", "item", "quest"):
            self.assertTrue(making.get(key).owner, key)


@tag("unit")
class EveryConfirmationCanBeTurnedOff(SimpleTestCase):
    """
    §8 of docs/commands-and-settings.md: every confirmation has a setting.

    It was true of the hand-written ones and silently untrue of the generated
    ones -- `delete rule` asked every time and `settings confirmations` did
    not know it existed, which is the registry missing an entry rather than
    the player having chosen anything.
    """

    def setUp(self):
        making.forget()

    def test_every_maker_that_asks_is_in_the_register(self):
        from world import preferences

        known = {key for key, _label, _why in preferences.confirmations()}
        for maker in making.registered():
            for key, _label, _why in maker.confirmations():
                with self.subTest(key=key):
                    self.assertIn(key, known)

    def test_and_the_hand_written_ones_are_still_there(self):
        from world import preferences

        known = {key for key, _label, _why in preferences.confirmations()}
        for key in ("delete_world", "reset_world", "discard", "suggestion",
                    "delete_tokens"):
            self.assertIn(key, known)

    def test_no_key_is_listed_twice(self):
        from world import preferences

        keys = [key for key, _label, _why in preferences.confirmations()]
        self.assertEqual(len(keys), len(set(keys)))


@tag("world")
class EveryChoiceCanBeOpened(Building):
    """
    Every picker in every form can produce its choices, in an empty world
    and a furnished one.

    `EveryFormDraws` was not enough and the gap is worth naming. Drawing a
    form shows each field's *value*, and a picker with nothing in it yet shows
    the word "not set" without ever asking what it could be set to. So a
    listing function that raises -- one `.items()` on a register that answers
    a list -- was invisible until somebody chose that line, and then took the
    whole menu down in front of them.

    This walks into each field instead, which is what a player does.
    """

    loose_objects = 1

    def furnish(self):
        from evennia import create_object
        from world import actions, coords, kinds, traits, verbs

        kinds.remember(self.root, "lantern", {"light": True})
        traits.register(self.root, "discoveries", means="what they found")
        verbs.register_state(self.root, "lit", means="it is giving light")
        actions.declare(self.root, "combine", means="to put two together",
                        applies_to=[{"role": "direct", "access": "carried"}])
        coords.place(self.root, self.room1, coords.ORIGIN)
        npc = create_object("typeclasses.npcs.NPC", key="Hob",
                            location=self.room1)
        npc.db.is_npc = True
        from world.makers import errands

        errands.keep_quest(self.draft(
            title="An errand", goal=[{"type": "holds", "object": "chalk"}],
            givers=[{"npc": str(npc.id), "description": ""}], wire=False))

    def every_choice(self, form, ctx, seen=None, depth=0):
        """Every choice field reachable from a form, its submenus included."""
        seen = seen if seen is not None else set()
        if depth > 4 or id(form) in seen:
            return
        seen.add(id(form))
        for item in form.items_for(ctx):
            if isinstance(item, menus.Field) and item.kind == menus.CHOICE:
                yield form, item
            elif isinstance(item, menus.Submenu):
                yield from self.every_choice(item.form, item.context(ctx),
                                             seen, depth + 1)

    def check(self, ctx):
        looked = 0
        for maker in making.registered():
            for form in (maker.new,):
                if form is None:
                    continue
                for holder, field in self.every_choice(form, ctx):
                    looked += 1
                    with self.subTest(maker=maker.key, field=field.key):
                        choices = field.choices_for(ctx)
                        self.assertIsInstance(choices, list)
                        for choice in choices:
                            self.assertIsNotNone(choice.value, field.key)
        self.assertGreater(looked, 20, "nothing was actually looked at")

    def test_in_an_empty_world(self):
        self.check(menus.Context(self.char1, world_root=self.root))

    def test_and_in_a_furnished_one(self):
        self.furnish()
        self.check(menus.Context(self.char1, world_root=self.root))

    def test_a_predicate_chosen_opens_the_value_picker_it_names(self):
        """The condition builder's whole shape: the second choice narrows."""
        from world.makers import rules

        self.furnish()
        for group, _label, members in rules.PREDICATE_GROUPS:
            for predicate, _said, _takes in members:
                ctx = menus.Context(
                    self.char1, world_root=self.root,
                    draft={"subject": "direct", "group": group,
                           "predicate": predicate})
                with self.subTest(predicate=predicate):
                    for item in rules.NEW_CONDITION.items_for(ctx):
                        if isinstance(item, menus.Field) \
                                and item.kind == menus.CHOICE:
                            self.assertIsInstance(item.choices_for(ctx), list)

    def test_an_effect_chosen_opens_the_fields_it_names(self):
        from world import effects
        from world.makers import rules

        self.furnish()
        for etype in sorted(effects.VOCABULARY):
            ctx = menus.Context(self.char1, world_root=self.root,
                                draft={"type": etype})
            with self.subTest(effect=etype):
                asked = [item.key for item in rules.NEW_EFFECT.items_for(ctx)]
                for field in rules.EFFECT_FIELDS[etype]:
                    self.assertIn(field, asked)
                for item in rules.NEW_EFFECT.items_for(ctx):
                    if isinstance(item, menus.Field) \
                            and item.kind == menus.CHOICE:
                        self.assertIsInstance(item.choices_for(ctx), list)

    def test_and_a_goal_type_opens_the_fields_it_names(self):
        from world.makers import errands

        self.furnish()
        for wanted, _said, fields in errands.GOAL_TYPES:
            ctx = menus.Context(self.char1, world_root=self.root,
                                draft={"type": wanted})
            with self.subTest(goal=wanted):
                asked = [item.key for item in errands.NEW_GOAL.items_for(ctx)]
                for field in fields:
                    self.assertIn(field, asked)


@tag("world")
class FinishingClosesTheForm(Building):
    """
    When the thing exists, the form is done with you.

    Both halves were wrong and the second is the one that grates: the menu
    stayed open after writing, and then quitting asked whether to throw away
    what had been entered -- about a kind that was already in the register.
    Asking somebody to confirm the loss of something that is not lost is
    worse than not asking, because it teaches them to answer yes unread.
    """

    def test_keeping_something_closes_the_menu(self):
        from world import kinds
        from world.makers import vocabulary

        self.open(vocabulary.NEW_KIND, world_root=self.root)
        self.type("cup")                 # the one required field
        said = self.type("keep")
        self.assertIn("This world now knows", said)
        self.assertFalse(self.is_open)
        self.assertIsNotNone(kinds.spec(self.root, kinds.canonical("cup")))

    def test_and_says_how_to_type_it_next_time(self):
        from world.makers import vocabulary

        self.open(vocabulary.NEW_KIND, world_root=self.root)
        self.type("cup")
        self.type("keep")
        self.assertIn("create kind", " ".join(self.said))

    def test_nothing_is_asked_about_throwing_away_what_was_written(self):
        from world.makers import vocabulary

        self.open(vocabulary.NEW_KIND, world_root=self.root)
        self.type("cup")
        self.type("keep")
        self.assertNotIn("Throw away", " ".join(self.said))

    def test_and_a_form_left_half_filled_still_asks(self):
        """The confirmation is right when there really is something to lose."""
        from world.makers import vocabulary

        self.open(vocabulary.NEW_KIND, world_root=self.root)
        self.type("cup")
        said = self.type("q")
        self.assertIn("Throw away", said)
        self.assertTrue(self.is_open)

    def test_every_maker_closes_when_it_is_finished(self):
        ctx = menus.Context(self.char1, world_root=self.root)
        for maker in making.registered():
            if maker.new is None:
                continue
            with self.subTest(maker=maker.key):
                finishing = making.finisher(maker.new, ctx)
                self.assertIsNotNone(finishing, maker.key)
                self.assertEqual(finishing.after, menus.CLOSE, maker.key)

    def test_and_a_picker_still_gets_its_value_back(self):
        """
        Closing is what happens when nobody was waiting, and only then.

        The two used to be in tension -- the form had to stay open so a
        picker could take the value -- and `Picked` saying "nobody was
        waiting" is what let them both be true.
        """
        from world import verbs

        self.open(making.get("condition").new, world_root=self.root)
        self.type("brewed")
        self.type("group")
        self.type("new")
        self.type("brewing")
        self.type("yes")
        self.type("keep")
        # The group was made and the picker came back with it: still open, in
        # the condition's own form, with the group set.
        self.assertTrue(self.is_open)
        self.assertIn("brewing", verbs.groups(self.root))
        self.type("keep")
        self.assertFalse(self.is_open)


@tag("world")
class WhatARuleMakesIsWhatItWasTold(Building):
    """
    A rule that creates a thing can say what sort of thing it is.

    Reported from play: it could not, and so it guessed. `clothing.create`
    reads sixteen fields off a spec and the effect menu asked for three of
    them, so the sort of thing was worked out from the head noun of whatever
    it was called -- a Wisp of Steam becomes a wisp, and every rule filed
    against the sort it was meant to be misses it.

    Worse than a missing field, and worth saying: `effects.VOCABULARY` -- the
    register that exists so the sentence and the applier cannot drift apart --
    named `why`, which nothing has ever read, and named none of the ten it
    does. The menu was written from it and inherited the gap.
    """

    def effect(self, **fields):
        from world.makers import rules

        made, _said = rules.keep_effect(self.draft(type="create_object",
                                                   **fields))
        return made

    def apply(self, effect):
        from world import effects

        effects.apply(self.char1, self.room1, [effect], bound={},
                      world_root=self.root)
        return next((obj for obj in self.room1.contents
                     if obj.key == effect.get("name")), None)

    def test_the_kind_it_was_given_is_the_kind_it_gets(self):
        from world import kinds

        kinds.remember(self.root, "substance.n.01", {"drink": True})
        made = self.apply(self.effect(name="Wisp of Steam",
                                      kind="substance.n.01"))
        self.assertIsNotNone(made)
        self.assertIn("substance.n.01", kinds.of(made))

    def test_and_without_one_it_is_still_guessed_from_the_name(self):
        """The old behaviour, kept -- it is right when nobody has said."""
        from world import kinds

        made = self.apply(self.effect(name="Wisp of Steam"))
        self.assertIsNotNone(made)
        self.assertTrue(kinds.of(made))
        self.assertNotIn("substance.n.01", kinds.of(made))

    def test_what_condition_it_is_made_in(self):
        from world import verbs

        verbs.register_state(self.root, "brewed", means="it has been brewed")
        made = self.apply(self.effect(name="Green Draught",
                                      states=["brewed"]))
        self.assertIn("brewed", verbs.states(made))

    def test_and_whether_it_can_be_picked_up(self):
        # Not "Standing Stone": `standing` is a condition, and a name may not
        # carry one. The checker catching that here is the same one that
        # catches it for a hand-made item, which is the point of sharing it.
        made = self.apply(self.effect(name="Granite Boulder", takeable=False))
        self.assertFalse(made.db.ai_takeable)

    def test_the_menu_asks_for_everything_the_maker_of_things_reads(self):
        """
        The drift that caused this, caught structurally.

        `clothing.create` is the one writer, and what it reads off a spec is
        what a rule making a thing should be able to say. Not every field --
        gear bonuses and garment styles are their own shape and are left out
        on purpose -- but nothing may be *asked* for that it does not read,
        which is the direction the bug came from.
        """
        import pathlib
        import re

        from tests.test_token_lists import GAME
        from world.makers import rules

        source = pathlib.Path(GAME / "world/clothing.py").read_text(
            encoding="utf-8")
        reads = set(re.findall(r'spec\.get\(\s*"([a-z_]+)"', source))
        asked = {rules.STORED_AS.get(field, field)
                 for field in rules.EFFECT_FIELDS["create_object"]}
        self.assertEqual(asked - reads - {"location"}, set())

    def test_and_the_register_says_what_it_really_takes(self):
        """`why` was in it for as long as nothing read it."""
        from world import effects
        from world.makers import rules

        said = effects.VOCABULARY["create_object"]["takes"]
        for field in rules.EFFECT_FIELDS["create_object"]:
            self.assertIn(rules.STORED_AS.get(field, field), said)
        self.assertNotIn("why", said)
