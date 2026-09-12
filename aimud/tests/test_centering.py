"""
Who is "she", and when.

The rule is centering theory's, and it tests without a model: two ranked
participant lists go in and which slot pronominalises comes out. The three
rows of the plan's table (§5.2) are the three classes below, and the third --
nothing carries over, therefore nobody is a pronoun -- is the one a
most-recently-mentioned implementation gets wrong.

Everything here is `world` tier because a participant has to be somebody
with a pronoun set and a viewer has to be somebody with an `ndb`. Nothing
here needs a key.
"""

from django.test import tag
from evennia.utils.test_resources import EvenniaTest

from world import events, pronouns, referents


class Stage(EvenniaTest):
    """Jessica, Britney, a sword and somebody watching all three."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1
        self.jessica = self.char1
        self.jessica.key = "Jessica"
        self.britney = self.char2
        self.britney.key = "Britney"
        self.watcher = self.create_character("Watcher")
        self.sword = self.obj1
        self.sword.key = "sword"
        pronouns.give(self.jessica, "she", self.room1)
        pronouns.give(self.britney, "she", self.room1)
        for who in (self.jessica, self.britney, self.watcher):
            referents.clear(who)

    def create_character(self, key):
        from evennia import create_object
        from typeclasses.characters import Character

        return create_object(Character, key=key, location=self.room1)

    def hands(self, actor=None, target=None):
        return events.Event(
            actor=actor or self.jessica, room=self.room1, verb="hand",
            roles={"direct": self.sword, "target": target or self.britney},
            room_template="{actor} $pconj(hand) {target} {direct}.")

    def picks_up(self, actor=None):
        return events.Event(
            actor=actor or self.jessica, room=self.room1, verb="get",
            roles={"direct": self.sword},
            room_template="{actor} $pconj(pick) up {direct}.")

    def shown(self, event, viewer=None):
        """Render for the watcher, and record what they saw, as delivery does."""
        return events.render(events.repair(event.room_template),
                             viewer or self.watcher, event)


@tag("world")
class TheCentreCarriesIntoTheSubject(Stage):
    """"Jessica picks up the sword." then "She hands Britney the sword.\""""

    def test_the_actor_becomes_she(self):
        self.shown(self.picks_up())
        self.assertEqual(self.shown(self.hands()),
                         "She hands Britney the sword.")

    def test_the_verb_agrees_with_a_they_them_actor(self):
        pronouns.give(self.jessica, "they", self.room1)
        self.shown(self.picks_up())
        self.assertEqual(self.shown(self.hands()),
                         "They hand Britney the sword.")

    def test_and_with_a_name(self):
        self.assertEqual(self.shown(self.picks_up()),
                         "Jessica picks up the sword.")

    def test_a_first_sentence_names_everybody(self):
        """Nothing has been read yet, so there is nothing to be thinking about."""
        self.assertEqual(self.shown(self.hands()),
                         "Jessica hands Britney the sword.")


@tag("world")
class TheCentreCarriesIntoTheObject(Stage):
    """"Britney examines the sword." then "Jessica hands her the sword.\""""

    def test_the_target_becomes_her(self):
        self.shown(events.Event(
            actor=self.britney, room=self.room1, verb="examine",
            roles={"direct": self.sword},
            room_template="{actor} $pconj(examine) {direct}."))
        self.assertEqual(self.shown(self.hands()),
                         "Jessica hands her the sword.")

    def test_a_thing_can_be_the_centre_too(self):
        """
        "The sword" was the only thing in the last sentence that is in this
        one, so "Jessica picks it up."
        """
        self.shown(events.Event(
            actor=self.britney, room=self.room1, verb="drop",
            roles={"direct": self.sword},
            room_template="{actor} drops {direct}."))
        self.britney.location = self.room2
        takes = events.Event(actor=self.jessica, room=self.room1, verb="take",
                             roles={"direct": self.sword},
                             room_template="{actor} $pconj(take) {direct}.")
        self.assertEqual(self.shown(takes), "Jessica takes it.")


@tag("world")
class NothingCarriesOver(Stage):
    """"The lamp gutters." then "Jessica hands Britney the sword.\""""

    def test_then_nobody_is_a_pronoun(self):
        """
        The row a naive implementation fails. The watcher was last told about
        a lamp; a "she" now would have no antecedent in their attention, and
        a name is strictly better than a pronoun nobody can resolve.
        """
        lamp = self.obj2
        lamp.key = "lamp"
        self.shown(events.Event(actor=lamp, room=self.room1, verb="gutter",
                                room_template="{actor} gutters."))
        self.assertEqual(self.shown(self.hands()),
                         "Jessica hands Britney the sword.")

    def test_the_most_recently_mentioned_is_not_the_rule(self):
        """
        Britney was mentioned last time and Jessica outranked her. Attention
        follows the ranking of the PREVIOUS sentence, so Jessica is the
        centre now even though Britney was the more recent word.
        """
        self.shown(self.hands())
        self.assertEqual(self.shown(self.picks_up()),
                         "She picks up the sword.")


@tag("world")
class OnePronounPerSurfaceForm(Stage):

    def test_she_and_her_do_not_both_appear(self):
        """
        Jessica is the centre and Britney is not, so only Jessica is a
        pronoun. The budget is per FORM, not per sentence: the sword may
        still be "it" beside "she", because nothing could confuse them.
        """
        self.shown(self.picks_up())
        self.assertEqual(self.shown(self.hands()),
                         "She hands Britney the sword.")

    def test_a_possessive_spends_the_form(self):
        """
        "She hands Britney her sword" is two "her"s about two people. The
        possessor is a participant, and the subject slot already spent the
        set's forms, so the possessive falls back to the name.
        """
        self.shown(self.picks_up())
        event = events.Event(
            actor=self.jessica, room=self.room1, verb="hand",
            roles={"direct": self.sword, "target": self.britney},
            room_template="{actor} $pconj(hand) {target} {target's} own {direct}.")
        # Britney is not the centre, so her possessive is her name.
        self.assertEqual(self.shown(event),
                         "She hands Britney Britney's own sword.")

    def test_the_centre_as_possessor(self):
        self.shown(self.picks_up())
        event = events.Event(
            actor=self.britney, room=self.room1, verb="admire",
            roles={"direct": self.sword, "target": self.jessica},
            room_template="{actor} admires {target's} {direct}.")
        self.assertEqual(self.shown(event), "Britney admires her sword.")


@tag("world")
class SecondPersonIsFree(Stage):

    def test_the_reader_is_you_in_any_slot(self):
        self.assertEqual(self.shown(self.hands(), viewer=self.britney),
                         "Jessica hands you the sword.")

    def test_and_does_not_spend_the_budget(self):
        """"She hands you the sword": one third-person pronoun and one you."""
        self.shown(self.picks_up(), viewer=self.britney)
        self.assertEqual(self.shown(self.hands(), viewer=self.britney),
                         "She hands you the sword.")

    def test_the_reader_is_never_the_centre(self):
        """
        Britney hands Jessica the sword, then picks it up. Britney is reading.
        She is "you" both times, and Jessica -- second-ranked last time -- is
        the centre, not Britney.
        """
        self.shown(self.hands(actor=self.britney, target=self.jessica),
                   viewer=self.britney)
        event = events.Event(
            actor=self.jessica, room=self.room1, verb="thank",
            roles={"target": self.britney},
            room_template="{actor} $pconj(thank) {target}.")
        self.assertEqual(self.shown(event, viewer=self.britney),
                         "She thanks you.")

    def test_the_reader_as_actor_conjugates_second_person(self):
        event = events.Event(
            actor=self.britney, room=self.room1, verb="pick",
            roles={"direct": self.sword},
            room_template="{actor} $pconj(pick) up {direct}.")
        self.assertEqual(self.shown(event, viewer=self.britney),
                         "You pick up the sword.")


@tag("world")
class WhatRenderingWritesDown(Stage):

    def test_the_viewer_is_told_what_they_saw(self):
        self.shown(self.hands())
        self.assertEqual(referents.told(self.watcher)[:2],
                         [self.jessica, self.sword])

    def test_and_their_pronouns_now_mean_what_they_read(self):
        """
        The two halves of the referent table are one table: having watched
        Jessica hand Britney the sword, "hug her" means Jessica -- the actor
        outranks the target -- and "get it" means the sword.
        """
        self.shown(self.hands())
        self.assertIs(referents.recall(self.watcher, "her"), self.jessica)
        self.assertIs(referents.recall(self.watcher, "it"), self.sword)

    def test_but_all_of_them_means_the_things(self):
        """
        Watching Jessica pick up a wrench and then typing "get all of them"
        means wrenches. The actor is noted under her words and not as the
        last thing referred to.
        """
        self.shown(self.picks_up())
        self.assertIs(referents.last(self.watcher), self.sword)

    def test_rendering_for_nobody_records_nothing(self):
        line = events.render("{actor} picks up {direct}.", None, self.picks_up())
        self.assertEqual(line, "Jessica picks up the sword.")

    def test_the_actor_is_not_told_their_own_line(self):
        """
        Delivery skips the actor. Their line is second person throughout and
        establishes no centre: somebody acting alone in a room has nothing
        to be "she" about.
        """
        self.watcher.location = self.room2
        self.britney.location = self.room2
        events.deliver(self.picks_up())
        self.assertEqual(referents.told(self.jessica), [])

    def test_a_bulk_delivery_reads_in_order(self):
        """
        Two drops, one message: the second line knows the first was read.
        """
        plate = self.obj2
        plate.key = "plate"
        self.britney.location = self.room2
        first = events.Event(actor=self.jessica, room=self.room1, verb="drop",
                             roles={"direct": self.sword},
                             room_template="{actor} drops {direct}.")
        second = events.Event(actor=self.jessica, room=self.room1, verb="drop",
                              roles={"direct": plate},
                              room_template="{actor} drops {direct}.")
        heard = []
        self.watcher.msg = lambda text="", **kw: heard.append(text)
        events.deliver_many([first, second])
        self.assertEqual(heard, ["Jessica drops the sword. She drops the plate."])


@tag("world")
class Agreement(Stage):

    def test_a_plural_thing_takes_a_plural_verb(self):
        coins = self.obj2
        coins.key = "coins"
        event = events.Event(actor=coins, room=self.room1, verb="scatter",
                             room_template="{actor} $pconj(scatter).")
        self.assertEqual(self.shown(event), "The coins scatter.")

    def test_a_named_subject_conjugates_the_verb(self):
        event = events.Event(
            actor=self.jessica, room=self.room1, verb="hand",
            roles={"direct": self.sword, "target": self.britney},
            room_template="{actor} $pconj(hand, actor) {direct} to {target}.")
        self.assertEqual(self.shown(event),
                         "Jessica hands the sword to Britney.")

    def test_a_verb_with_no_subject_named_is_left_bare(self):
        self.assertEqual(events.conjugate("", self.jessica, None), "")

    def test_the_pure_rule(self):
        """The rule as a function: two ranked lists in, the centre out."""
        a, b, c = object(), object(), object()
        self.assertIs(events.centre([a, b], [c, b, a]), a)
        self.assertIs(events.centre([a, b], [b]), b)
        self.assertIsNone(events.centre([a, b], [c]))
        self.assertIsNone(events.centre([], [a]))
        self.assertIs(events.centre([a, b], [a, b], viewer=a), b)


@tag("world")
class RepairingWhatTheModelSent(Stage):
    """
    A narrator does not always obey the prompt, and the template it sent is
    stored and replayed for every later viewer -- so a stray article or a
    conjugated verb is not a one-off blemish, it is permanent. `repair` is
    the one place to fix it, and it runs on the template before storage as
    well as on everything already cached.
    """

    def rendered(self, template, viewer=None, actor=None):
        event = events.Event(
            actor=actor or self.jessica, room=self.room1, verb="hand",
            roles={"direct": self.sword, "target": self.britney},
            room_template=events.repair(template))
        return events.render(event.room_template, viewer, event)

    def test_an_article_before_a_placeholder_is_dropped(self):
        """
        "the {direct}" renders "the the sword". The prompt forbids it; a model
        writes it anyway, because every sentence it has ever read has the
        article there.
        """
        self.assertEqual(events.repair("{actor} $pconj(hand) {target} the {direct}."),
                         "{actor} $pconj(hand) {target} {direct}.")
        self.assertEqual(
            self.rendered("{actor} $pconj(hand) {target} the {direct}."),
            "Jessica hands Britney the sword.")

    def test_every_article_form_goes(self):
        for article in ("the", "The", "a", "an", "A"):
            self.assertEqual(
                events.repair(f"{{actor}} $pconj(drop) {article} {{direct}}."),
                "{actor} $pconj(drop) {direct}.")

    def test_but_an_article_on_real_words_stays(self):
        """Only the one immediately before a placeholder is ours to touch."""
        self.assertEqual(
            events.repair("{actor} $pconj(open) the lid of {direct}."),
            "{actor} $pconj(open) the lid of {direct}.")

    def test_a_possessive_placeholder_keeps_its_bare_noun(self):
        self.assertEqual(
            events.repair("{actor} $pconj(take) {target's} {direct}."),
            "{actor} $pconj(take) {target's} {direct}.")

    def test_a_conjugated_verb_after_the_actor_is_wrapped(self):
        """
        "{actor} hands" can never agree with anybody: it is "hands" for a
        they/them character and "hands" for the reader, who should be told
        "you hand". Wrapping it is the difference between a template that
        works for one pronoun set and one that works for all of them.
        """
        self.assertEqual(events.repair("{actor} hands {target} {direct}."),
                         "{actor} $pconj(hand) {target} {direct}.")

    def test_and_then_agrees_with_a_they_them_actor(self):
        pronouns.give(self.jessica, "they", self.room1)
        self.assertEqual(self.rendered("{actor} hands {target} {direct}."),
                         "Jessica hand Britney the sword.")

    def test_and_reads_as_second_person_for_the_actor_themselves(self):
        self.assertEqual(
            self.rendered("{actor} hands {target} {direct}.", viewer=self.jessica),
            "You hand Britney the sword.")

    def test_an_irregular_verb_is_wrapped_by_its_base_form(self):
        """`$pconj` conjugates, so what it is given must be the base form."""
        self.assertEqual(events.repair("{actor} tries {direct}."),
                         "{actor} $pconj(try) {direct}.")
        self.assertEqual(events.repair("{actor} watches {direct}."),
                         "{actor} $pconj(watch) {direct}.")

    def test_a_verb_already_wrapped_is_left_alone(self):
        self.assertEqual(events.repair("{actor} $pconj(hand) {direct}."),
                         "{actor} $pconj(hand) {direct}.")

    def test_and_a_base_form_is_left_alone(self):
        """
        "{actor} hand" is what a careless model writes when it means the
        placeholder to be second person. Not ours to guess at: wrapping only
        what is visibly third-person singular keeps the repair to the case it
        can be sure about.
        """
        self.assertEqual(events.repair("{actor} hand {direct}."),
                         "{actor} hand {direct}.")

    def test_the_subjectless_repair_still_works(self):
        self.assertEqual(events.repair("lights the candle."),
                         "{actor} $pconj(light) the candle.")

    def test_and_nothing_is_still_nothing(self):
        self.assertEqual(events.repair(""), "")
        self.assertEqual(events.repair(None), "")
