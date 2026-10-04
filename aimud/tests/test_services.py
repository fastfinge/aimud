"""
Services: the register, the owner's classification, the gate, and the wire.

docs/mcp-client.md is the plan. These hold the parts of it that are about the
server rather than about a world: what a tool is guessed to be and how the
owner's answer outlives a relisting, the one gate (§5.3) as one test per cell,
the addresses refused, and the manager actually talking to a server -- in
process for most of them, through `tests.support.serving`, and as a real
process for one, because stdio is where process lifetime goes wrong.
"""

import sys
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings, tag

from tests.base import GameTest
from tests.support import serving
from world import services


# ---------------------------------------------------------------------------
# Reading what a service says
# ---------------------------------------------------------------------------

@tag("unit")
class TheFirstGuess(SimpleTestCase):
    """Annotations are hints, and saying nothing means assume the worst."""

    def test_saying_nothing_is_acting_outward(self):
        self.assertEqual(services.guess_level({}), services.ACTS)
        self.assertEqual(services.guess_level(None), services.ACTS)

    def test_a_closed_world_is_contained(self):
        self.assertEqual(services.guess_level({"openWorldHint": False}),
                         services.CONTAINED)

    def test_read_only_on_the_open_world_looks_outward(self):
        self.assertEqual(services.guess_level({"readOnlyHint": True}),
                         services.LOOKS)

    def test_read_only_and_closed_is_still_contained(self):
        self.assertEqual(
            services.guess_level({"readOnlyHint": True, "openWorldHint": False}),
            services.CONTAINED)

    def test_an_openapi_method_decides_instead(self):
        self.assertEqual(services.guess_level(method="get"), services.LOOKS)
        self.assertEqual(services.guess_level(method="HEAD"), services.LOOKS)
        self.assertEqual(services.guess_level(method="post"), services.ACTS)
        self.assertEqual(services.guess_level(method="DELETE"), services.ACTS)


@tag("unit")
class TheFingerprint(SimpleTestCase):

    def test_key_order_does_not_change_it(self):
        one = services.fingerprint({"a": 1, "b": 2}, None)
        two = services.fingerprint({"b": 2, "a": 1}, None)
        self.assertEqual(one, two)

    def test_a_changed_shape_does(self):
        self.assertNotEqual(
            services.fingerprint({"properties": {"city": {"type": "string"}}}, None),
            services.fingerprint({"properties": {"town": {"type": "string"}}}, None))

    def test_the_output_counts_too(self):
        self.assertNotEqual(services.fingerprint({}, {"type": "object"}),
                            services.fingerprint({}, None))


@tag("unit")
class WhatInputARuleCanFill(SimpleTestCase):

    def test_scalars_enums_and_lists_of_scalars(self):
        self.assertEqual(services.input_complaint({"properties": {
            "city": {"type": "string"},
            "days": {"type": "integer"},
            "units": {"enum": ["metric", "imperial"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "maybe": {"type": ["string", "null"]},
        }}), "")

    def test_a_nested_object_is_refused_and_named(self):
        said = services.input_complaint(
            {"properties": {"entry": {"type": "object"}}})
        self.assertIn("entry", said)

    def test_several_shapes_are_refused(self):
        self.assertIn("several", services.input_complaint(
            {"properties": {"x": {"oneOf": [{"type": "string"}]}}}))

    def test_nothing_to_fill_is_fine(self):
        self.assertEqual(services.input_complaint({}), "")


@tag("unit")
class TheOwnersAnswerOutlivesARelisting(SimpleTestCase):
    """§5.2: the owner's decision stands until the tool is not what they saw."""

    def listed(self, fingerprint="sha256:a", level=services.LOOKS):
        return {"forecast": {"fingerprint": fingerprint, "level": level,
                             "refused": ""}}

    def test_a_new_mcp_tool_is_on_with_its_guess(self):
        merged = services.merge_tools({}, self.listed())
        self.assertTrue(merged["forecast"]["on"])
        self.assertEqual(merged["forecast"]["level"], services.LOOKS)
        self.assertFalse(merged["forecast"]["decided"])

    def test_a_new_openapi_operation_is_off(self):
        merged = services.merge_tools({}, self.listed(), openapi=True)
        self.assertFalse(merged["forecast"]["on"])

    def test_the_owners_level_and_switch_survive(self):
        old = {"forecast": {"fingerprint": "sha256:a", "level": services.ACTS,
                            "on": False, "decided": True}}
        merged = services.merge_tools(old, self.listed())
        self.assertEqual(merged["forecast"]["level"], services.ACTS)
        self.assertFalse(merged["forecast"]["on"])
        self.assertTrue(merged["forecast"]["decided"])

    def test_a_changed_shape_goes_back_to_its_guess_and_off(self):
        old = {"forecast": {"fingerprint": "sha256:a", "level": services.CONTAINED,
                            "on": True, "decided": True}}
        merged = services.merge_tools(old, self.listed(fingerprint="sha256:b"))
        self.assertEqual(merged["forecast"]["level"], services.LOOKS)
        self.assertFalse(merged["forecast"]["on"])
        self.assertFalse(merged["forecast"]["decided"])

    def test_a_refused_tool_is_never_on(self):
        listed = self.listed()
        listed["forecast"]["refused"] = "entry is object"
        self.assertFalse(services.merge_tools({}, listed)["forecast"]["on"])


# ---------------------------------------------------------------------------
# The gate, one test per cell (§5.3)
# ---------------------------------------------------------------------------

class _Body:
    def __init__(self, npc):
        self.db = mock.Mock(is_npc=npc)


@tag("unit")
class TheOneGate(SimpleTestCase):

    def paying(self, answers):
        return mock.Mock(answers=answers)

    def check(self, npc, level, answers, expected):
        self.assertEqual(
            services.allowed(self.paying(answers), _Body(npc), level), expected,
            f"npc={npc} level={level} answers={answers}")

    def test_a_player_contained(self):
        self.check(False, services.CONTAINED, False, True)

    def test_a_player_looks_outward(self):
        self.check(False, services.LOOKS, False, True)

    def test_a_player_acts_outward_with_somebody_paying(self):
        self.check(False, services.ACTS, True, True)

    def test_a_player_acts_outward_with_nobody_paying(self):
        self.check(False, services.ACTS, False, False)

    def test_a_character_at_every_level_with_somebody_paying(self):
        for level in services.LEVEL_NAMES:
            self.check(True, level, True, True)

    def test_a_character_at_every_level_with_nobody_paying(self):
        for level in services.LEVEL_NAMES:
            self.check(True, level, False, False)

    @override_settings(LOCKDOWN_MODE=True)
    def test_nothing_reaches_out_in_lockdown(self):
        for npc in (True, False):
            for level in services.LEVEL_NAMES:
                self.check(npc, level, True, False)

    def test_the_refusal_says_who_is_not_paying(self):
        said = services.refusal(self.paying(False), _Body(True), services.LOOKS)
        self.assertIn("paying", said)
        self.assertEqual(
            services.refusal(self.paying(True), _Body(True), services.LOOKS), "")


# ---------------------------------------------------------------------------
# Addresses and names
# ---------------------------------------------------------------------------

@tag("unit")
class AddressesRefused(SimpleTestCase):

    @override_settings(MCP_PORT=4007, MCP_INTERFACE="127.0.0.1")
    def test_this_games_own_endpoint(self):
        for url in ("http://127.0.0.1:4007/mcp", "http://localhost:4007/",
                    "https://[::1]:4007/mcp"):
            with self.subTest(url=url):
                self.assertIn("own MCP endpoint",
                              services.address_complaint(url))

    @override_settings(MCP_PORT=4007)
    def test_another_local_port_is_fine(self):
        self.assertEqual(services.address_complaint("http://127.0.0.1:8765/mcp"), "")

    def test_not_a_web_address(self):
        self.assertTrue(services.address_complaint("ftp://example.com"))
        self.assertTrue(services.address_complaint("weather"))


@tag("unit")
class Names(SimpleTestCase):

    def test_one_lower_case_word(self):
        self.assertEqual(services.name_complaint("weather"), "")
        self.assertEqual(services.name_complaint("open-meteo_2"), "")
        self.assertTrue(services.name_complaint("Two words"))
        self.assertTrue(services.name_complaint("9lives"))
        self.assertTrue(services.name_complaint(""))

    def test_taken(self):
        self.assertIn("already", services.name_complaint("weather", {"weather": {}}))


@tag("unit")
class ReadingWhatWasTyped(SimpleTestCase):

    def test_arguments_split_like_a_shell(self):
        self.assertEqual(services.read_args('server.py --name "my thing"'),
                         (["server.py", "--name", "my thing"], ""))

    def test_pairs(self):
        self.assertEqual(services.read_pairs("A=1; B=x=y\nC = 3"),
                         ({"A": "1", "B": "x=y", "C": "3"}, ""))
        pairs, said = services.read_pairs("nonsense")
        self.assertIsNone(pairs)
        self.assertTrue(said)

    def test_pairs_are_said_by_name_only(self):
        self.assertEqual(services.said_pairs({"TOKEN": "s3cret", "A": "1"}),
                         "A, TOKEN")


# ---------------------------------------------------------------------------
# The register, and the wire
# ---------------------------------------------------------------------------

@tag("world")
class TheRegister(GameTest):

    def test_it_starts_empty(self):
        self.assertEqual(services.register(), {})

    def test_put_get_and_remove(self):
        record = services.blank("weather", services.URL)
        record["url"] = "http://example.com/mcp"
        services.put(record)
        self.assertEqual(services.get("weather")["url"], "http://example.com/mcp")
        self.assertEqual(services.names(), ["weather"])
        self.assertTrue(services.remove("weather"))
        self.assertIsNone(services.get("weather"))
        self.assertFalse(services.remove("weather"))

    def test_a_copy_is_not_the_register(self):
        services.put(services.blank("weather"))
        services.get("weather")["url"] = "changed"
        self.assertEqual(services.get("weather")["url"], "")


@tag("world")
class ListingAServer(GameTest):
    """The real manager and the real SDK, against a server in this process."""

    def test_every_tool_is_listed_with_its_guess(self):
        with serving() as record:
            tools = record["tools"]
            self.assertEqual(record["status"], "")
            self.assertEqual(tools["forecast"]["level"], services.LOOKS)
            self.assertEqual(tools["roll"]["level"], services.CONTAINED)
            self.assertEqual(tools["send_postcard"]["level"], services.ACTS)
            self.assertEqual(tools["pubs"]["level"], services.LOOKS)

    def test_a_tool_no_rule_can_fill_is_refused_and_off(self):
        with serving() as record:
            ledger = record["tools"]["ledger"]
            self.assertIn("entry", ledger["refused"])
            self.assertFalse(ledger["on"])

    def test_the_output_schema_is_kept(self):
        with serving() as record:
            output = record["tools"]["forecast"]["output"]
            self.assertEqual(output["properties"]["conditions"]["enum"],
                             ["sunny", "rain", "storm"])

    def test_usable_is_what_a_rule_may_name(self):
        with serving():
            ids = [found for found, _record, _info in services.usable()]
            self.assertIn("weather.forecast", ids)
            self.assertNotIn("weather.ledger", ids)

    @override_settings(LOCKDOWN_MODE=True)
    def test_nothing_is_usable_in_lockdown(self):
        with serving():
            self.assertEqual(services.usable(), [])


@tag("world")
class CallingATool(GameTest):

    def test_a_structured_answer(self):
        with serving() as record:
            answer = services.call(record, "forecast", {"city": "London"})
            self.assertTrue(answer.ok)
            self.assertEqual(answer.field("conditions"), "rain")
            self.assertEqual(answer.field("high_c"), 12.0)

    def test_a_text_answer(self):
        with serving() as record:
            answer = services.call(record, "pubs", {"near": "London"})
            self.assertTrue(answer.ok)
            self.assertIn("The Lamb", answer.text)

    def test_a_tool_that_says_it_failed_was_still_reached(self):
        with serving() as record:
            answer = services.call(record, "flaky", {"why": "no"})
            self.assertFalse(answer.ok)
            self.assertTrue(answer.reached)

    def test_one_session_serves_many_calls(self):
        with serving() as record:
            for _ in range(3):
                self.assertTrue(services.call(record, "roll", {"sides": 4}).ok)
            self.assertEqual(len(services._manager().connections), 1)


@tag("world")
class AServiceThatCannotBeReached(GameTest):

    def broken(self, *_args):
        raise ConnectionError("refused")

    def test_the_answer_says_so_and_was_not_reached(self):
        record = services.blank("down", services.URL)
        with mock.patch.object(services, "target", self.broken):
            answer = services.call(record, "anything", {})
        self.assertFalse(answer.ok)
        self.assertFalse(answer.reached)

    def test_it_is_tried_once_unless_it_is_idempotent(self):
        """§7.5: retrying an email sends it twice."""
        record = services.blank("down", services.URL)
        tries = []

        def counting(wanted):
            tries.append(wanted)
            raise ConnectionError("refused")

        old = services._MANAGER
        services._MANAGER = services._Manager()
        try:
            with mock.patch.object(services, "target", counting):
                services.call(record, "send", {}, retry=False)
                once = len(tries)
                services.call(record, "send", {}, retry=True)
        finally:
            services._MANAGER = old
        self.assertEqual(once, 1)
        self.assertEqual(len(tries), 3)

    def test_listing_never_raises(self):
        record = services.blank("down", services.URL)
        with mock.patch.object(services, "target", self.broken):
            tools, status = services.connect_and_list(record)
        self.assertIsNone(tools)
        self.assertIn("refused", status)


@tag("world")
class OverStdio(GameTest):
    """
    The one test that starts a real process, because stdio is where process
    lifetime goes wrong: a session must be started once and reused.
    """

    def test_a_command_is_started_once_and_answers(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "weather_server.py"
        record = services.blank("local", services.COMMAND)
        record["command"] = sys.executable
        record["args"] = [str(fixture)]
        old = services._MANAGER
        services._MANAGER = services._Manager()
        try:
            tools, status = services.connect_and_list(record)
            self.assertEqual(status, "")
            self.assertIn("forecast", tools)
            first = services.call(record, "forecast", {"city": "Lisbon"})
            second = services.call(record, "roll", {"sides": 3})
            self.assertEqual(first.field("conditions"), "sunny")
            self.assertEqual(second.text, "3")
            self.assertEqual(len(services._manager().connections), 1)
        finally:
            manager = services._MANAGER
            for name in list(manager.connections):
                manager.drop(name)
            services._MANAGER = old


# ---------------------------------------------------------------------------
# The subject: create, edit, delete and view service
# ---------------------------------------------------------------------------

from commands import services_subject, subjects  # noqa: E402
from commands.verbs import CmdCreate, CmdDelete, CmdEdit, CmdView  # noqa: E402
from tests.base import GameCommandTest  # noqa: E402
from tests.support import immediately  # noqa: E402


class _AsSomebody(GameCommandTest):

    def be(self, *perms):
        self.char1.permissions.clear()
        for perm in perms:
            self.char1.permissions.add(perm)
        self.char1.locks.reset()


@tag("world")
class WhoMayAddAService(_AsSomebody):

    def test_a_player_may_read_but_not_add(self):
        self.be("Player")
        self.assertIn("nothing outside", self.call(CmdView(), "services").lower())
        said = self.call(CmdCreate(), "service weather url http://w.example/mcp")
        self.assertIn("Admin", said)
        self.assertIsNone(services.get("weather"))

    def test_an_admin_may_add_a_url(self):
        self.be("Admin")
        with immediately(), mock.patch.object(services, "connect_and_list",
                                              lambda record: ({}, "")):
            self.call(CmdCreate(), "service weather url http://w.example/mcp")
        self.assertEqual(services.get("weather")["url"], "http://w.example/mcp")

    def test_but_not_a_command(self):
        self.be("Admin")
        said = self.call(CmdCreate(), "service local command python server.py")
        self.assertIn("Developer", said)
        self.assertIsNone(services.get("local"))

    def test_a_developer_may_add_a_command(self):
        self.be("Developer")
        with immediately(), mock.patch.object(services, "connect_and_list",
                                              lambda record: ({}, "")):
            self.call(CmdCreate(), 'service local command python "my server.py" --x')
        record = services.get("local")
        self.assertEqual(record["command"], "python")
        self.assertEqual(record["args"], ["my server.py", "--x"])

    def test_the_create_entry_is_only_offered_to_an_admin(self):
        from world import menus

        self.be("Player")
        keys = [item.key for item in
                subjects.verb_form("create").items_for(menus.Context(self.char1))]
        self.assertNotIn("service", keys)
        self.be("Admin")
        keys = [item.key for item in
                subjects.verb_form("create").items_for(menus.Context(self.char1))]
        self.assertIn("service", keys)

    @override_settings(MCP_PORT=4007)
    def test_this_games_own_endpoint_is_refused(self):
        self.be("Developer")
        said = self.call(CmdCreate(), "service me url http://127.0.0.1:4007/mcp")
        self.assertIn("own MCP endpoint", said)
        self.assertIsNone(services.get("me"))


@tag("world")
class ClassifyingByTyping(_AsSomebody):
    """Every point in the tool list is reachable by typing, for an agent."""

    def test_a_level_and_a_switch(self):
        self.be("Admin")
        with serving():
            self.call(CmdEdit(), "service weather tool forecast acts")
            info = services.get("weather")["tools"]["forecast"]
            self.assertEqual(info["level"], services.ACTS)
            self.assertTrue(info["decided"])
            self.call(CmdEdit(), "service weather tool forecast off")
            self.assertFalse(services.get("weather")["tools"]["forecast"]["on"])

    def test_a_refused_tool_cannot_be_switched_on(self):
        self.be("Admin")
        with serving():
            said = self.call(CmdEdit(), "service weather tool ledger on")
            self.assertIn("cannot be switched on", said)
            self.assertFalse(services.get("weather")["tools"]["ledger"]["on"])

    def test_a_setting_in_a_line_and_its_secret_is_not_said(self):
        self.be("Admin")
        with serving():
            said = self.call(CmdEdit(), "service weather key sk-very-secret-key")
            self.assertNotIn("sk-very-secret-key", said)
            self.assertEqual(services.get("weather")["key"], "sk-very-secret-key")

    def test_a_player_may_not_change_one(self):
        self.be("Player")
        with serving():
            self.call(CmdEdit(), "service weather tool forecast acts")
            self.assertEqual(services.get("weather")["tools"]["forecast"]["level"],
                             services.LOOKS)


@tag("world")
class ReadingAService(_AsSomebody):

    def test_view_service_says_every_description_in_full(self):
        self.be("Player")
        with serving():
            said = self.call(CmdView(), "service weather")
        self.assertIn("Gets today's forecast for a city.", said)
        self.assertIn("one of sunny, rain, storm", said)
        self.assertIn("refused", said)

    def test_a_key_is_masked(self):
        self.be("Player")
        with serving(auth=services.KEY_AUTH, key="sk-abcdefghijklmnop"):
            said = self.call(CmdView(), "service weather")
        self.assertNotIn("sk-abcdefghijklmnop", said)
        self.assertIn("sk-a", said)


@tag("world")
class ForgettingAService(_AsSomebody):

    def test_delete_with_yes(self):
        self.be("Admin")
        with serving():
            self.call(CmdDelete(), "service weather yes")
            self.assertIsNone(services.get("weather"))
