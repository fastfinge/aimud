"""
The loop every generator shares, driven by scripted replies.

Phase 3 of docs/generator-tool-loops.md. Nothing here is a game: a finish tool
that wants a number, a lookup that counts, an act that does nothing. What is
held still is how a conversation goes round and how it ends.
"""

from unittest import mock

from django.test import SimpleTestCase, tag
from twisted.python.failure import Failure

from tests.support import FakeSponsor, immediately, replying, tool_call, tool_reply
from world import llm
from world import toolbox as tb

SPONSOR = FakeSponsor()


def answer_tool(wanted=2):
    """A finish tool that accepts only `wanted`, and complains otherwise."""
    def handler(ctx, args, answer):
        if args.get("n") == wanted:
            answer(tb.accept(args["n"]))
        else:
            answer(tb.complain(f"n has to be {wanted}", value=args.get("n")))

    return tb.Tool("answer", "Give the number.", {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }, handler, finishes=True)


def lookup_tool(calls=None, doing="counting"):
    def handler(ctx, args, answer):
        if calls is not None:
            calls.append(args)
        answer("3")

    return tb.Tool("count", "Count something.", {
        "type": "object",
        "properties": {"what": {"type": "string", "enum": ["apples", "pears"]}},
        "required": ["what"],
    }, handler, looks=True, doing=doing)


def act_tool(done=None):
    def handler(ctx, args, answer):
        if done is not None:
            done.append(args)
        answer("Done.")

    return tb.Tool("wave", "Wave.", None, handler)


class _Conversing:

    def converse(self, tools, *replies, rounds=8, **kwargs):
        got = {"done": [], "error": [], "exhausted": []}
        box = tb.Toolbox(tools)
        with immediately(), replying(*replies) as asked:
            llm.converse(SPONSOR, "test/model",
                         [{"role": "user", "content": "go"}], box,
                         on_done=got["done"].append,
                         on_error=got["error"].append,
                         rounds=rounds, **kwargs)
        return got, asked, box


@tag("unit")
class HowALoopEnds(_Conversing, SimpleTestCase):

    def test_an_accepted_answer_ends_it(self):
        got, asked, _box = self.converse(
            [answer_tool()], tool_reply(tool_call("answer", n=2)))
        self.assertEqual(got["done"], [2])
        self.assertEqual(asked.count, 1)

    def test_a_complaint_goes_back_and_the_correction_is_taken(self):
        got, asked, box = self.converse(
            [answer_tool()],
            tool_reply(tool_call("answer", n=1)),
            tool_reply(tool_call("answer", n=2)))
        self.assertEqual(got["done"], [2])
        self.assertEqual(asked.count, 2)
        self.assertIn("n has to be 2",
                      asked.tool_results(1)[0]["content"])
        self.assertEqual(box.complaints, 1)

    def test_a_lookup_is_answered_and_the_loop_goes_round(self):
        got, asked, _box = self.converse(
            [answer_tool(), lookup_tool()],
            tool_reply(tool_call("count", what="apples")),
            tool_reply(tool_call("answer", n=2)))
        self.assertEqual(got["done"], [2])
        self.assertEqual(asked.tool_results(1)[0]["content"], "3")

    def test_words_instead_of_a_tool_are_told_to_use_it(self):
        got, asked, _box = self.converse(
            [answer_tool()], {"choices": [{"message": {"content": "It is 2."}}]},
            tool_reply(tool_call("answer", n=2)))
        self.assertEqual(got["done"], [2])
        self.assertIn("Answer by calling answer", asked.sent(1))

    def test_each_round_of_lookups_is_told_what_is_left(self):
        _got, asked, _box = self.converse(
            [answer_tool(), lookup_tool()],
            tool_reply(tool_call("count", what="apples")),
            tool_reply(tool_call("count", what="pears")),
            tool_reply(tool_call("answer", n=2)), rounds=3)
        self.assertEqual(asked.prompts[1][-1],
                         {"role": "user", "content":
                          "2 replies left, and the last of them must answer "
                          "with answer. Several lookups can go in one reply."})
        self.assertEqual(asked.prompts[2][-1]["content"],
                         "Your next reply is the last one: answer with answer.")

    def test_a_loop_with_no_finish_tool_is_not_counted_down(self):
        _got, asked, _box = self.converse(
            [lookup_tool(), act_tool()],
            tool_reply(tool_call("count", what="apples")),
            tool_reply(tool_call("wave")))
        self.assertEqual(asked.prompts[1][-1]["role"], "tool")

    def test_the_models_reasoning_is_handed_back(self):
        details = [{"type": "reasoning.encrypted", "data": "abc"}]
        reply = tool_reply(tool_call("count", what="apples"))
        reply["choices"][0]["message"]["reasoning_details"] = details
        _got, asked, _box = self.converse(
            [answer_tool(), lookup_tool()], reply,
            tool_reply(tool_call("answer", n=2)))
        spoken = [m for m in asked.prompts[1] if m["role"] == "assistant"]
        self.assertEqual(spoken[0]["reasoning_details"], details)

    def test_the_last_round_names_the_finish_tool(self):
        _got, asked, _box = self.converse(
            [answer_tool(), lookup_tool()],
            tool_reply(tool_call("count", what="apples")),
            tool_reply(tool_call("answer", n=2)), rounds=2)
        self.assertEqual(asked.tool_choice(0), None)
        self.assertEqual(asked.tool_choice(1),
                         {"type": "function", "function": {"name": "answer"}})

    def test_running_out_is_an_error_by_default(self):
        got, _asked, _box = self.converse(
            [answer_tool()], tool_reply(tool_call("answer", n=1)), rounds=2)
        self.assertEqual(got["done"], [])
        self.assertIn("never answered", got["error"][0])

    def test_or_hands_back_the_last_answer_that_was_refused(self):
        taken = []
        self.converse([answer_tool()], tool_reply(tool_call("answer", n=1)),
                      rounds=2, on_exhausted=taken.append)
        self.assertEqual(taken, [1])

    def test_with_no_finish_tool_a_reply_that_calls_nothing_ends_it(self):
        got, _asked, _box = self.converse(
            [act_tool()], {"choices": [{"message": {"content": "Hm."}}]})
        self.assertEqual(got["done"], ["Hm."])

    def test_and_a_round_that_only_acted_ends_it_too(self):
        done = []
        got, asked, _box = self.converse(
            [act_tool(done)], tool_reply(tool_call("wave")))
        self.assertEqual(len(done), 1)
        self.assertEqual(asked.count, 1)
        self.assertEqual(got["done"], [None])

    def test_but_a_round_that_looked_goes_round_for_the_answer(self):
        done = []
        _got, asked, _box = self.converse(
            [act_tool(done), lookup_tool()],
            tool_reply(tool_call("count", what="pears"), tool_call("wave")),
            {"choices": [{"message": {"content": ""}}]})
        self.assertEqual(asked.count, 2)

    def test_a_failed_round_is_an_error_in_words(self):
        got, _asked, _box = self.converse(
            [answer_tool()], llm.LLMError("Rate limit exceeded"))
        self.assertIn("Rate limit exceeded", got["error"][0])


@tag("unit")
class WhatTheToolsAreProtectedFrom(_Conversing, SimpleTestCase):

    def test_arguments_the_schema_forbids_never_reach_the_handler(self):
        calls = []
        _got, asked, _box = self.converse(
            [answer_tool(), lookup_tool(calls)],
            tool_reply(tool_call("count", what="plums")),
            tool_reply(tool_call("answer", n=2)))
        self.assertEqual(calls, [])
        self.assertIn("has to be one of: apples, pears",
                      asked.tool_results(1)[0]["content"])

    def test_a_repeated_lookup_is_answered_from_before(self):
        calls = []
        _got, asked, _box = self.converse(
            [answer_tool(), lookup_tool(calls)],
            tool_reply(tool_call("count", what="apples")),
            tool_reply(tool_call("count", what="apples")),
            tool_reply(tool_call("answer", n=2)))
        self.assertEqual(len(calls), 1)
        self.assertIn("Asked already", asked.tool_results(2)[-1]["content"])

    def test_too_many_calls_at_once_are_not_all_run(self):
        calls = []
        _got, asked, _box = self.converse(
            [answer_tool(), lookup_tool(calls)],
            tool_reply(*[tool_call("count", what=f)
                         for f in ["apples", "pears"] * 5]),
            tool_reply(tool_call("answer", n=2)))
        results = asked.tool_results(1)
        self.assertEqual(len(results), 10)
        self.assertIn("too many at once", results[-1]["content"])

    def test_a_handler_that_raises_is_an_answer_not_a_crash(self):
        def broken(ctx, args, answer):
            raise RuntimeError("no")

        got, asked, _box = self.converse(
            [answer_tool(), tb.Tool("count", "", None, broken, looks=True)],
            tool_reply(tool_call("count")),
            tool_reply(tool_call("answer", n=2)))
        self.assertEqual(got["done"], [2])
        self.assertIn("failed", asked.tool_results(1)[0]["content"])

    def test_a_tool_nobody_offered(self):
        _got, asked, _box = self.converse(
            [answer_tool()], tool_reply(tool_call("fly")),
            tool_reply(tool_call("answer", n=2)))
        self.assertIn("no tool called 'fly'",
                      asked.tool_results(1)[0]["content"])

    def test_a_long_result_is_cut_short_and_says_so(self):
        long = tb.Tool("count", "", None,
                       lambda ctx, args, answer: answer("x" * 10000),
                       looks=True)
        _got, asked, _box = self.converse(
            [answer_tool(), long], tool_reply(tool_call("count")),
            tool_reply(tool_call("answer", n=2)))
        content = asked.tool_results(1)[0]["content"]
        self.assertEqual(len(content), tb.MOST_RESULT)
        self.assertTrue(content.endswith(tb.CUT_SHORT))


@tag("unit")
class HandlersThatTakeTheirTime(SimpleTestCase):

    def test_an_answer_that_comes_later_resumes_the_loop(self):
        later = []

        def slow(ctx, args, answer):
            later.append(answer)

        got = []
        box = tb.Toolbox([answer_tool(), tb.Tool("count", "", None, slow,
                                                 looks=True)])
        with immediately(), replying(tool_reply(tool_call("count")),
                                     tool_reply(tool_call("answer", n=2))) as asked:
            llm.converse(SPONSOR, "m", [], box, on_done=got.append,
                         on_error=got.append)
            self.assertEqual(asked.count, 1, "waiting on the lookup")
            later[0]("3")
        self.assertEqual(got, [2])

    def test_a_threaded_lookup_goes_through_the_door(self):
        box = tb.Toolbox([
            answer_tool(),
            tb.Tool("count", "", None, lambda ctx, args: "7", looks=True,
                    threaded=True)])
        got = []
        with immediately(), replying(tool_reply(tool_call("count")),
                                     tool_reply(tool_call("answer", n=2))) as asked:
            llm.converse(SPONSOR, "m", [], box, on_done=got.append,
                         on_error=got.append)
        self.assertEqual(asked.tool_results(1)[0]["content"], "7")
        self.assertEqual(got, [2])


@tag("unit")
class WhatALoopReports(_Conversing, SimpleTestCase):

    def test_each_tool_says_what_it_is_doing_to_whoever_waits(self):
        wait = mock.Mock()
        self.converse([answer_tool(), lookup_tool(doing="counting apples")],
                      tool_reply(tool_call("count", what="apples")),
                      tool_reply(tool_call("answer", n=2)), wait=wait)
        wait.stage.assert_called_with("counting apples")

    def test_every_loop_leaves_one_measurement_line(self):
        with mock.patch("evennia.utils.logger.log_info") as logged:
            self.converse([answer_tool(), lookup_tool()],
                          tool_reply(tool_call("count", what="apples")),
                          tool_reply(tool_call("answer", n=1)),
                          tool_reply(tool_call("answer", n=2)))
        lines = [c.args[0] for c in logged.call_args_list
                 if str(c.args[0]).startswith("llm: loop")]
        self.assertEqual(len(lines), 1)
        self.assertIn("rounds=3/8", lines[0])
        self.assertIn("complaints=1", lines[0])
        self.assertIn("outcome=accepted", lines[0])
        self.assertIn("count x1".replace(" ", ""), lines[0])


@tag("unit")
class ACallbackThatRaises(_Conversing, SimpleTestCase):
    """
    A generator's own callback raising must still end the job.

    Found on a live server: a player watched "building the way east" for four
    minutes with the reactor idle, the threadpool idle and nothing in flight.
    `exits.at_traverse` sets `ndb.generating` before asking and clears it only
    in its callbacks, so an exception in one of them stranded the door until
    the next reload -- and the exception reached a Deferred nothing had an
    errback on, which Twisted reports only when it is collected, so the log
    said nothing at all.

    The fix is at the seam rather than the 31 call sites that hand `converse`
    a callback: `llm._delivered`. Every generator already routes `on_error` to
    something that releases what it holds, so a raise arriving there is what
    makes the door open again.
    """

    def boom(self, _value):
        raise RuntimeError("the room could not be built")

    def test_a_done_callback_that_raises_becomes_an_error(self):
        got = {"done": [], "error": []}
        box = tb.Toolbox([answer_tool()])
        with immediately(), replying(tool_reply(tool_call("answer", n=2))):
            llm.converse(SPONSOR, "test/model",
                         [{"role": "user", "content": "go"}], box,
                         on_done=self.boom,
                         on_error=got["error"].append)
        self.assertEqual(len(got["error"]), 1, "nobody was told")
        self.assertIn("could not be used", got["error"][0])
        self.assertIn("the room could not be built", got["error"][0])

    def test_and_does_not_raise_into_the_reactor(self):
        """
        The whole point: it must not come back out. A raise here reaches a
        Deferred with no errback, which is the invisible half of the bug.
        """
        box = tb.Toolbox([answer_tool()])
        with immediately(), replying(tool_reply(tool_call("answer", n=2))):
            llm.converse(SPONSOR, "test/model",
                         [{"role": "user", "content": "go"}], box,
                         on_done=self.boom,
                         on_error=lambda _why: None)   # released, said nothing

    def test_an_error_callback_that_raises_is_swallowed_and_logged(self):
        """
        There is nowhere left to report it to, so it is logged and stops here
        rather than becoming the same lost Deferred one layer further out.
        """
        box = tb.Toolbox([answer_tool()])
        with immediately(), replying(Exception("the service refused")), \
                mock.patch.object(llm, "_callback_failed") as noted:
            llm.converse(SPONSOR, "test/model",
                         [{"role": "user", "content": "go"}], box,
                         on_done=lambda _v: None, on_error=self.boom)
        self.assertTrue(noted.called)

    def test_an_exhausted_callback_that_raises_becomes_an_error_too(self):
        got = {"error": []}
        box = tb.Toolbox([answer_tool()])
        with immediately(), replying(tool_reply(tool_call("answer", n=1))):
            llm.converse(SPONSOR, "test/model",
                         [{"role": "user", "content": "go"}], box,
                         on_done=lambda _v: None,
                         on_error=got["error"].append,
                         on_exhausted=self.boom, rounds=2)
        self.assertEqual(len(got["error"]), 1)

    def test_the_job_is_only_ended_once(self):
        """
        `on_error` is reached through the raise, not as well as by the loop
        ending twice -- otherwise a caller would release what it holds twice.
        """
        got = {"done": [], "error": []}
        box = tb.Toolbox([answer_tool()])
        with immediately(), replying(tool_reply(tool_call("answer", n=2))):
            llm.converse(SPONSOR, "test/model",
                         [{"role": "user", "content": "go"}], box,
                         on_done=self.boom,
                         on_error=got["error"].append)
        self.assertEqual(len(got["error"]), 1)
        self.assertEqual(got["done"], [])


@tag("unit")
class AFetchCallbackThatRaises(SimpleTestCase):
    """
    The outer net, for a caller that goes through `fetch` directly rather than
    through a tool loop -- `world.decisions` is one.
    """

    def test_a_success_callback_that_raises_reaches_the_error_path(self):
        failures = []
        with immediately():
            llm.fetch(lambda: "answer",
                      on_success=lambda _v: (_ for _ in ()).throw(
                          RuntimeError("could not use it")),
                      on_error=failures.append)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], Failure)
        self.assertIn("could not use it", failures[0].getErrorMessage())

    def test_an_error_callback_that_raises_stops_there(self):
        with immediately(), mock.patch.object(llm, "_callback_failed") as noted:
            llm.fetch(lambda: (_ for _ in ()).throw(RuntimeError("no answer")),
                      on_success=lambda _v: None,
                      on_error=lambda _f: (_ for _ in ()).throw(
                          RuntimeError("and no way to say so")))
        self.assertTrue(noted.called)


@tag("unit")
class CheckingArguments(SimpleTestCase):

    SCHEMA = {"type": "object", "required": ["n"], "properties": {
        "n": {"type": "integer", "minimum": 1, "maximum": 9},
        "yes": {"type": "boolean"},
        "pick": {"type": "string", "enum": ["a", "b"]}}}

    def test_what_is_right_passes(self):
        self.assertEqual(tb.problems_with({"n": 3, "yes": True, "pick": "a"},
                                          self.SCHEMA), [])

    def test_what_is_wrong_is_said(self):
        found = tb.problems_with({"n": 12, "yes": "yes", "pick": "c"},
                                 self.SCHEMA)
        self.assertEqual(len(found), 3)
        self.assertIn("n is required", tb.problems_with({}, self.SCHEMA))
        self.assertIn("n has to be a whole number",
                      tb.problems_with({"n": "3"}, self.SCHEMA))
