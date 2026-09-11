"""
What happened, said once and rendered per person.

Every delivery site in this game used to melt the facts of an action into
prose at the moment it had them, and throw the facts away:

    on_message(f"You put {label} {preposition} {where}.",
               f"{name} puts {label} {preposition} {where}.")

The verb, the roles, the preposition, the outcome and the effects that fired
are all on that line and none of them survives it. Six things want exactly
those facts -- sound, two out-of-band protocols, the web client, shared
worlds, and the renderer that will choose between "she" and "Jessica" -- so
what travels now is the event, and the prose is one rendering of it.

The structural test at the bottom is the one that matters most. A missed
delivery site does not fail: it shows somebody a raw `{actor}` in the middle
of a sentence, which no assertion about behaviour would catch.
"""

import ast
import pathlib

from django.test import SimpleTestCase, tag
from evennia.utils.test_resources import EvenniaTest

from world import events

GAME = pathlib.Path(__file__).resolve().parent.parent


@tag("world")
class WhatAnEventCarries(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1

    def make(self, **overrides):
        fields = dict(actor=self.char1, room=self.room1, verb="put",
                      roles={"direct": self.obj1, "target": self.obj2},
                      outcome="success",
                      actor_text="You put the mug on the table.",
                      room_template="{actor} puts {direct} on {target}.")
        fields.update(overrides)
        return events.Event(**fields)

    def test_it_keeps_the_facts_rather_than_the_sentence(self):
        event = self.make()
        self.assertEqual(event.verb, "put")
        self.assertIs(event.roles["direct"], self.obj1)
        self.assertEqual(event.outcome, "success")

    def test_the_mapping_names_every_participant(self):
        """
        What `msg_contents` renders per recipient. The actor is in it under
        its own name as well as the roles, because the template says
        {actor} and nothing else knows who that is.
        """
        mapping = self.make().mapping()
        self.assertIs(mapping["actor"], self.char1)
        self.assertIs(mapping["direct"], self.obj1)
        self.assertIs(mapping["target"], self.obj2)

    def test_a_role_nobody_filled_is_not_in_the_mapping(self):
        event = self.make(roles={"direct": self.obj1})
        self.assertNotIn("target", event.mapping())

    def test_participants_come_back_ranked(self):
        """
        actor before direct before the rest. P4's centering rule reads this
        order and nothing else does yet, which is why it is asserted now --
        a ranking nobody checks is a ranking that drifts.
        """
        event = self.make()
        self.assertEqual(event.participants()[0], self.char1)
        self.assertEqual(event.participants()[1], self.obj1)

    def test_an_event_with_no_room_line_is_still_an_event(self):
        """
        Reading a letter alone changes the world and is seen by nobody. The
        facts are worth having even when there is no sentence.
        """
        event = self.make(room_template="")
        self.assertFalse(event.seen)
        self.assertEqual(event.verb, "put")


@tag("world")
class Rendering(EvenniaTest):

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1

    def test_a_fragment_gets_its_subject_back(self):
        """
        A model that answers with "lights the candle." must not be broadcast
        with nobody attached to it. Repaired rather than refused, because the
        alternative is losing an action that really happened.
        """
        self.assertTrue(
            events.repair("lights the candle.").startswith("{actor}"))

    def test_a_whole_sentence_is_left_alone(self):
        text = "{actor} lights the candle."
        self.assertEqual(events.repair(text), text)

    def test_nothing_stays_nothing(self):
        self.assertEqual(events.repair(""), "")


@tag("unit")
class NoSiteBuildsItsOwnSentence(SimpleTestCase):
    """
    The structural guard, and the reason it exists rather than a behavioural
    one: a delivery site that was missed does not raise. It shows a player a
    raw `{actor}` in the middle of a sentence, and only reading every site
    would have found it.

    What is banned is a finished sentence arriving where an event belongs. A
    sentence has already chosen every name in it, once, for everybody -- which
    is precisely what per-recipient rendering exists to stop.
    """

    #: Where an action is narrated. Deliberately not every module: a quest
    #: announcement and a room's "you notice a lamp here" are the game telling
    #: somebody something rather than an action happening, they carry no verb
    #: and no roles, and an event would be a costume on them.
    NARRATING = (
        "world/attempt.py", "world/relations.py", "world/clothing.py",
        "world/gear.py", "world/events.py",
        "commands/drop_cmds.py", "commands/unknown_cmd.py",
        "commands/clothing_cmds.py",
    )

    def test_nothing_broadcast_is_built_as_a_sentence(self):
        """
        The precise form of the defect, and the reason an earlier draft of this
        test was useless: it banned naming anything inside any f-string, which
        also caught `describe_outfit`, where the name is chosen FOR the one
        person being shown it and is exactly right.

        What is actually wrong is a finished sentence going where an event
        belongs -- the second argument to `on_message`, or the text handed to
        `msg_contents` -- because a sentence has already chosen everybody's
        names, once, for all of them.
        """
        offences = []
        for name in self.NARRATING:
            tree = ast.parse((GAME / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                called = node.func
                label = getattr(called, "attr", getattr(called, "id", ""))
                if label == "on_message" and len(node.args) > 1:
                    suspect = node.args[1]
                elif label == "msg_contents" and node.args:
                    suspect = node.args[0]
                else:
                    continue
                if isinstance(suspect, ast.JoinedStr):
                    offences.append(
                        f"{name}:{node.lineno} broadcasts a built sentence "
                        f"where an event belongs")
        self.assertEqual(offences, [], "\n" + "\n".join(offences))
