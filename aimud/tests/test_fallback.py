"""
A fallback model per job: asked when the job's own model fails.

A fast model that sometimes refuses, with a steadier one behind it, is the
case this is for: Inception's Mercury refuses some NPC turns with "Upstream
error ... I'm sorry, but I can't help with that request", and each one left a
character with no reaction at all. The fallback is asked with the same
request before anybody is told, and it is the same round of a conversation,
so a model's error never costs the job one of its rounds.
"""

import io
import json
import urllib.error
from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameCommandTest
from tests.support import FakeSponsor, immediately
from world import llm
from world import toolbox as tb
from world.model_params import ModelChoice

SPONSOR = FakeSponsor(key="sk-key", base_url=llm.BASE_URL)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answering(*outcomes):
    """
    Patch the network to give each outcome in turn: a dict is a reply body, an
    exception is raised. Records the model each request was sent for.
    """
    asked = []
    queue = list(outcomes)

    def urlopen(request, timeout=None):
        asked.append(json.loads(request.data.decode())["model"])
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(json.dumps(outcome).encode())

    return mock.patch.object(llm.urllib.request, "urlopen", urlopen), asked


def text(content):
    return {"choices": [{"message": {"content": content}}]}


REFUSAL = {"error": {"message": "Upstream error from Inception: I'm sorry, "
                                "but I can't help with that request."}}


def refused_over_http():
    body = json.dumps(REFUSAL).encode()
    return urllib.error.HTTPError(llm.CHAT_URL, 502, "Bad Gateway", {},
                                  io.BytesIO(body))


def with_fallback():
    return ModelChoice("fast/model", job="dialogue",
                       fallback=ModelChoice("steady/model", job="dialogue"))


@tag("unit")
class FallingBack(SimpleTestCase):

    def test_an_error_goes_to_the_fallback_with_the_same_request(self):
        patch, asked = answering(REFUSAL, text("Hello."))
        with patch:
            said = llm.ask(SPONSOR, with_fallback(), [{"role": "user",
                                                       "content": "hi"}])
        self.assertEqual(said, "Hello.")
        self.assertEqual(asked, ["fast/model", "steady/model"])

    def test_so_does_an_http_error(self):
        patch, asked = answering(refused_over_http(), text("Hello."))
        with patch:
            self.assertEqual(llm.ask(SPONSOR, with_fallback(), []), "Hello.")
        self.assertEqual(asked, ["fast/model", "steady/model"])

    def test_and_a_timeout(self):
        patch, asked = answering(TimeoutError("timed out"), text("Hello."))
        with patch:
            self.assertEqual(llm.ask(SPONSOR, with_fallback(), []), "Hello.")

    def test_an_answer_never_reaches_the_fallback(self):
        patch, asked = answering(text("Hello."))
        with patch:
            llm.ask(SPONSOR, with_fallback(), [])
        self.assertEqual(asked, ["fast/model"])

    def test_when_both_fail_the_error_names_both(self):
        patch, _asked = answering(REFUSAL, {"error": {"message": "overloaded"}})
        with patch, self.assertRaises(llm.LLMError) as caught:
            llm.ask(SPONSOR, with_fallback(), [])
        said = str(caught.exception)
        self.assertIn("fast/model", said)
        self.assertIn("can't help", said)
        self.assertIn("steady/model", said)
        self.assertIn("overloaded", said)

    def test_with_no_fallback_the_error_is_as_it_was(self):
        patch, asked = answering(REFUSAL)
        with patch, self.assertRaises(llm.LLMError):
            llm.ask(SPONSOR, ModelChoice("fast/model", job="dialogue"), [])
        self.assertEqual(asked, ["fast/model"])

    def test_the_fallback_is_logged(self):
        patch, _asked = answering(REFUSAL, text("Hello."))
        with patch, mock.patch("evennia.utils.logger.log_info") as logged:
            llm.ask(SPONSOR, with_fallback(), [])
        line = logged.call_args[0][0]
        self.assertIn("llm: fallback job=dialogue from=fast/model "
                      "to=steady/model", line)

    def test_it_is_asked_with_the_jobs_own_settings(self):
        sent = []

        def urlopen(request, timeout=None):
            payload = json.loads(request.data.decode())
            sent.append(payload)
            if len(sent) == 1:
                return FakeResponse(json.dumps(REFUSAL).encode())
            return FakeResponse(json.dumps(text("Hello.")).encode())

        model = ModelChoice("fast/model", {"temperature": 0.9}, job="dialogue",
                            fallback=ModelChoice("steady/model",
                                                 {"temperature": 0.9},
                                                 job="dialogue"))
        with mock.patch.object(llm.urllib.request, "urlopen", urlopen):
            llm.ask(SPONSOR, model, [])
        self.assertEqual(sent[1]["temperature"], 0.9)


@tag("unit")
class NotARound(SimpleTestCase):
    """A model's error does not spend one of the job's rounds."""

    def test_a_turn_that_fell_back_is_still_one_round(self):
        finish = tb.Tool("answer", "", tb.params({"n": {"type": "integer"}}),
                         lambda ctx, args, done: done(tb.accept(args["n"])),
                         finishes=True)
        box = tb.Toolbox([finish])
        called = {"id": "c1", "type": "function",
                  "function": {"name": "answer", "arguments": '{"n": 3}'}}
        answered = {"choices": [{"message": {"content": None,
                                             "tool_calls": [called]}}]}
        got = []
        patch, asked = answering(REFUSAL, answered)
        with patch, immediately(), \
                mock.patch("world.ledger.note_loop") as noted:
            llm.converse(SPONSOR, with_fallback(), [], box,
                         on_done=got.append, on_error=got.append, rounds=2)
        self.assertEqual(got, [3])
        self.assertEqual(asked, ["fast/model", "steady/model"])
        self.assertEqual(noted.call_args.args[2]["rounds"], 1)


@tag("world")
class ChoosingAFallback(GameCommandTest):
    accounts = True

    def settings(self, args):
        from commands.settings_cmds import CmdSettings

        return self.call(CmdSettings(), args)

    def setUp(self):
        super().setUp()
        self.account.db.openrouter_api_key = "sk-abcdefgh12345678"
        self.account.ndb.openrouter_models_cache = [
            {"id": "fast/model", "supported_parameters": ["tools"]},
            {"id": "steady/model", "supported_parameters": ["tools"]},
        ]

    def test_a_job_gets_its_own(self):
        self.settings("models dialogue model fast/model")
        self.settings("models dialogue fallback steady/model")
        choice = self.account.model_for("dialogue")
        self.assertEqual(choice, "fast/model")
        self.assertEqual(choice.fallback, "steady/model")
        self.assertEqual(choice.fallback.job, "dialogue")

    def test_default_covers_a_job_without_one(self):
        self.settings("models default fallback steady/model")
        self.assertEqual(self.account.model_for("rooms").fallback,
                         "steady/model")

    def test_a_fallback_the_same_as_the_model_is_none(self):
        self.settings("models dialogue model steady/model")
        self.settings("models dialogue fallback steady/model")
        self.assertIsNone(self.account.model_for("dialogue").fallback)

    def test_cleared_again(self):
        self.settings("models dialogue fallback steady/model")
        self.settings("models dialogue fallback clear")
        self.assertIsNone(self.account.model_for("dialogue").fallback)

    def test_the_job_menu_says_so(self):
        self.assertIn("Fallback model: none",
                      self.settings("list") + self._job_listing())

    def _job_listing(self):
        from world import menus, preferences

        ctx = menus.Context(self.char1).child(job="dialogue")
        return "\n".join(f"{field.label}: {field.shown(ctx)}"
                         for field in preferences._job_items(ctx)
                         if isinstance(field, menus.Field))
