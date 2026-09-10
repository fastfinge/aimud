"""
The one place that talks to OpenRouter, tested without talking to it.

These exist to hold the extraction in `world/llm.py` still. Six modules used to
carry a private copy of this call, differing in timeout, in what they returned
and in whether they accepted tools, and the point of one module is that those
differences are now visible and deliberate. A test per difference is what stops
them drifting back.

The last test here is structural rather than behavioural: it reads the source of
the whole game and asserts that nothing except `world.llm` names the service.
That is the seam itself, asserted, so it cannot quietly be reopened.
"""

import io
import json
import pathlib
import urllib.error
from unittest import mock

from django.test import SimpleTestCase, tag

from world import llm


def reply(content="{}", **extra):
    """A chat completion as OpenRouter sends one."""
    body = {"choices": [{"message": {"content": content}}]}
    body.update(extra)
    return body


class FakeResponse(io.BytesIO):
    """Enough of an HTTP response for `urlopen`'s context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def sending(body):
    """Patch urlopen to answer with `body`, and record what it was sent."""
    sent = {}

    def urlopen(request, timeout=None):
        sent["url"] = request.full_url
        sent["method"] = request.get_method()
        sent["headers"] = dict(request.header_items())
        sent["timeout"] = timeout
        sent["payload"] = (json.loads(request.data.decode())
                           if request.data else None)
        return FakeResponse(json.dumps(body).encode())

    return mock.patch.object(llm.urllib.request, "urlopen", urlopen), sent


@tag("unit")
class ReadingAReply(SimpleTestCase):
    """`content` is the tolerant reader; it never raises."""

    def test_takes_the_text_out(self):
        self.assertEqual(llm.content(reply("hello")), "hello")

    def test_a_reply_with_only_tool_calls_has_no_text(self):
        body = {"choices": [{"message": {"tool_calls": [{"id": "1"}]}}]}
        self.assertEqual(llm.content(body), "")

    def test_null_content_is_empty_rather_than_none(self):
        self.assertEqual(llm.content(reply(None)), "")

    def test_nonsense_is_empty_and_not_an_exception(self):
        for body in ({}, {"choices": []}, None, "", [1, 2], {"error": {}}):
            self.assertEqual(llm.content(body), "", repr(body))


@tag("unit")
class ReadingAComplaint(SimpleTestCase):
    """What the service said, when it would not answer."""

    def test_from_a_decoded_body(self):
        said = llm._complain({"error": {"message": "No credits left"}})
        self.assertEqual(said, "No credits left")

    def test_from_raw_bytes_and_from_text(self):
        raw = json.dumps({"error": {"message": "No endpoints found"}})
        self.assertEqual(llm._complain(raw.encode()), "No endpoints found")
        self.assertEqual(llm._complain(raw), "No endpoints found")

    def test_anything_unparseable_says_nothing(self):
        for body in (b"<html>502</html>", "", b"", None, {}, {"error": None},
                     [{"error": "x"}]):
            self.assertEqual(llm._complain(body), "", repr(body))

    def test_a_very_long_complaint_is_cut(self):
        said = llm._complain({"error": {"message": "x" * 1000}})
        self.assertEqual(len(said), llm.MAX_COMPLAINT)


@tag("unit")
class AskingAModel(SimpleTestCase):
    """What goes out on the wire, and what comes back."""

    def test_the_request_is_a_post_to_chat_completions(self):
        patch, sent = sending(reply("text"))
        with patch:
            llm.ask("sk-key", "some/model", [{"role": "user", "content": "hi"}])
        self.assertEqual(sent["url"], llm.CHAT_URL)
        self.assertEqual(sent["method"], "POST")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer sk-key")
        self.assertEqual(sent["headers"]["Content-type"], "application/json")
        self.assertEqual(sent["payload"]["model"], "some/model")
        self.assertEqual(sent["payload"]["messages"][0]["content"], "hi")

    def test_ask_answers_with_the_text(self):
        patch, _sent = sending(reply("the flyer is damp"))
        with patch:
            self.assertEqual(
                llm.ask("k", "m", []), "the flyer is damp")

    def test_call_answers_with_the_whole_reply(self):
        """npc_gen needs this: a tool call is not in the text."""
        patch, _sent = sending(reply("", extra_field=1))
        with patch:
            got = llm.call("k", "m", [])
        self.assertIn("choices", got)
        self.assertEqual(got["extra_field"], 1)

    def test_tools_are_sent_only_when_given(self):
        patch, sent = sending(reply())
        with patch:
            llm.call("k", "m", [])
        self.assertNotIn("tools", sent["payload"])
        self.assertNotIn("tool_choice", sent["payload"])

        tools = [{"type": "function", "function": {"name": "give"}}]
        patch, sent = sending(reply())
        with patch:
            llm.call("k", "m", [], tools=tools)
        self.assertEqual(sent["payload"]["tools"], tools)
        self.assertEqual(sent["payload"]["tool_choice"], "auto")

    def test_the_default_wait_is_thirty_seconds(self):
        patch, sent = sending(reply("x"))
        with patch:
            llm.ask("k", "m", [])
        self.assertEqual(sent["timeout"], llm.TIMEOUT)

    def test_a_caller_may_choose_to_wait_longer(self):
        """worldgen and fact_gen did, before this was one function."""
        patch, sent = sending(reply("x"))
        with patch:
            llm.ask("k", "m", [], llm.SLOW_TIMEOUT)
        self.assertEqual(sent["timeout"], llm.SLOW_TIMEOUT)
        self.assertEqual(llm.SLOW_TIMEOUT, 60)

    def test_a_plain_model_name_sends_no_sampling_settings(self):
        """`model_params.of` answers {} for a string, and must keep doing so."""
        patch, sent = sending(reply("x"))
        with patch:
            llm.ask("k", "plain/model", [])
        self.assertEqual(set(sent["payload"]), {"model", "messages"})


@tag("unit")
class WhenItWillNotAnswer(SimpleTestCase):
    """
    The reason this module exists as much as the seam does.

    A key with no credit used to reach the player as `'choices'`, and a bad
    model name as "HTTP Error 400: Bad Request". Both carry a sentence saying
    what is actually wrong.
    """

    def test_an_error_body_inside_a_200_is_explained(self):
        patch, _sent = sending({"error": {"message": "No credits left"}})
        with patch, self.assertRaises(llm.LLMError) as caught:
            llm.ask("k", "m", [])
        self.assertIn("No credits left", str(caught.exception))

    def test_an_http_error_carries_what_the_service_said(self):
        body = json.dumps({"error": {"message": "model not found"}}).encode()
        err = urllib.error.HTTPError(
            llm.CHAT_URL, 400, "Bad Request", {}, io.BytesIO(body))
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(llm.LLMError) as caught:
                llm.ask("k", "m", [])
        self.assertIn("model not found", str(caught.exception))

    def test_an_http_error_with_an_unreadable_body_still_says_something(self):
        err = urllib.error.HTTPError(
            llm.CHAT_URL, 502, "Bad Gateway", {}, io.BytesIO(b"<html>"))
        with mock.patch.object(llm.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(llm.LLMError) as caught:
                llm.ask("k", "m", [])
        self.assertIn("502", str(caught.exception))

    def test_empty_text_is_reported_rather_than_returned(self):
        """Every `ask` caller goes straight on to read JSON out of it."""
        patch, _sent = sending(reply(""))
        with patch, self.assertRaises(llm.LLMError):
            llm.ask("k", "m", [])

    def test_a_timeout_is_not_swallowed(self):
        """Only HTTP errors are translated; the rest reach the caller intact."""
        with mock.patch.object(llm.urllib.request, "urlopen",
                               side_effect=TimeoutError("timed out")):
            with self.assertRaises(TimeoutError):
                llm.ask("k", "m", [])


@tag("unit")
class ListingModels(SimpleTestCase):

    def test_models_come_back_sorted_by_id(self):
        patch, sent = sending({"data": [{"id": "z/model"}, {"id": "a/model"}]})
        with patch:
            got = llm.models("k")
        self.assertEqual([m["id"] for m in got], ["a/model", "z/model"])
        self.assertEqual(sent["url"], llm.MODELS_URL)
        self.assertEqual(sent["method"], "GET")
        self.assertIsNone(sent["payload"])

    def test_a_listing_with_no_models_in_it_is_explained(self):
        patch, _sent = sending({"error": {"message": "invalid key"}})
        with patch, self.assertRaises(llm.LLMError) as caught:
            llm.models("k")
        self.assertIn("invalid key", str(caught.exception))


@tag("unit")
class TheSeamItself(SimpleTestCase):
    """
    Structural, and the only test here that reads the game rather than runs it.

    `world.llm` exists so that there is exactly one place to fake. That is only
    true while it stays the only place that names the service, and the cheapest
    way to keep it true is to say so in a test.

    The claim is about **model calls**, which is narrower than "all networking"
    and deliberately so -- see `MAY_OPEN_URLS` below for the one other thing that
    reaches the network and why putting it behind this seam would help nobody.
    """

    def source_files(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts or path.parts[-2:-1] == ("tests",):
                continue
            yield path, path.read_text(encoding="utf-8")

    def test_only_world_llm_names_openrouter(self):
        offenders = [
            str(path.relative_to(path.parent.parent.parent))
            for path, text in self.source_files()
            if "openrouter.ai" in text and path.name != "llm.py"
        ]
        self.assertEqual(offenders, [], "these should call world.llm instead")

    #: Files allowed to open a URL without going through the seam, and why.
    #:
    #: `world/llm.py` is the seam. `world/commonsense.py` fetches a dictionary,
    #: which is a different kind of network call from a model call: it happens
    #: once ever, on a command, and what comes back is a corpus rather than an
    #: answer. Routing a gigabyte of gzip through the module that exists to make
    #: one JSON reply fakeable would make both jobs worse.
    #:
    #: The testability the seam protects is kept there by other means:
    #: `commonsense.build_from` takes an iterable of lines, so the whole builder
    #: is tested against a committed sample and only the download itself ever
    #: touches the network. An allowlist rather than a looser pattern, so that
    #: the next file to want one has to come and argue for it here.
    MAY_OPEN_URLS = ("llm.py", "commonsense.py")

    def test_nothing_opens_a_url_of_its_own(self):
        offenders = [
            str(path.relative_to(path.parent.parent.parent))
            for path, text in self.source_files()
            if "urllib.request.urlopen" in text
            and path.name not in self.MAY_OPEN_URLS
        ]
        self.assertEqual(offenders, [],
                         "these should call world.llm instead, or be added to "
                         "MAY_OPEN_URLS with a reason")

    def test_and_the_corpus_fetch_is_still_testable_without_a_network(self):
        """
        What the allowlist above costs, and why it costs nothing. The builder
        takes lines; only the fetching takes a URL. So the parsing, the index and
        every lookup are covered by a committed sample.
        """
        from world import commonsense

        found = list(commonsense.read_edges(
            ["\t".join(["x", "/r/IsA", "/c/en/a", "/c/en/b", "{}"])]))
        self.assertEqual(found, [("a", "IsA", "b", 1.0)])
