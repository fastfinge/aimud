"""
What a test needs in order not to call a model.

Three pieces, and between them they are what turns most of this game's
untestable half into tier `world`: a way to make the one async door
synchronous, a way to answer as a model would, and a stand-in for a sponsor so
a generator can be called without a world or an account behind it.

And, for code that offers tools, a way to write the tool calls a model would
send back (`tool_call`, `tool_reply`), and a clock a test can move by hand.

`deciding` is `replying`'s sibling for the decision model, which is asked
through the same door and answers a different shape -- numbers rather than
anything said. See `world.decisions`.

The door is `world.llm.fetch`. Without a running reactor a `deferToThread`
callback never fires -- so a test that drove a generator through one would pass
having asserted nothing, which is the worst way for a test to behave.
`immediately()` replaces the door with one that runs the work and calls back
before it returns, so a test can assert on what happened by the time the call
is over.
"""

import contextlib
import itertools
import json
import pathlib
from unittest import mock

from twisted.python.failure import Failure

from world import llm


@contextlib.contextmanager
def immediately():
    """
    Run model work in this thread, and call back before returning.

    The same contract `fetch` has, minus the thread: `on_success` gets what the
    work returned, `on_error` gets a Failure, and exactly one of them is called.
    """
    def fetch(work, *args, on_success, on_error):
        try:
            answer = work(*args)
        except Exception:
            return on_error(Failure())
        return on_success(answer)

    with mock.patch.object(llm, "fetch", fetch):
        yield


@contextlib.contextmanager
def replying(*answers, tools=None):
    """
    Answer as a model would, from a script rather than from the network.

    Each argument is one reply, used in order; the last is repeated if the code
    asks more times than there are answers, because a generator that retries is
    usually retrying for a reason a test is not about. A `dict` is sent back as
    a whole reply (what `llm.call` returns), and anything else is wrapped as the
    text of one (what `llm.ask` returns), so a test writes the shape it means.

    Records what was asked, which is most of what there is to assert about a
    prompt: `recorder.prompts[0]` is the messages list of the first call. What
    each call offered is recorded too -- `recorder.tools(0)`,
    `recorder.tool_choice(0)` -- along with the tool results it was sent, which
    is what a test of a tool loop asserts on.
    """
    scripted = list(answers) or [""]
    asked = []
    offered = []        # (tools, tool_choice) for each call, in order

    def reply_for(messages):
        asked.append(messages)
        answer = scripted[min(len(asked) - 1, len(scripted) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def fake_call(sponsor, model, messages, tools=None, timeout=llm.TIMEOUT,
                  tool_choice=None):
        offered.append((tools, tool_choice))
        answer = reply_for(messages)
        if isinstance(answer, Finishing):
            return answer.reply(tools)
        if isinstance(answer, dict):
            return answer
        return {"choices": [{"message": {"content": answer}}]}

    def fake_ask(sponsor, model, messages, timeout=llm.TIMEOUT):
        offered.append((None, None))
        answer = reply_for(messages)
        if isinstance(answer, Finishing):
            return ""
        if isinstance(answer, dict):
            return llm.content(answer)
        return answer

    class Recorder:
        @property
        def prompts(self):
            return asked

        @property
        def count(self):
            return len(asked)

        def sent(self, index=0):
            """Everything in one call's messages, as a single string."""
            # `or ""`, not a default: a reply that carried only tool calls is
            # sent back with its content null, which `get` hands over as None.
            return "\n".join(m.get("content") or ""
                             for m in asked[index])

        def tools(self, index=0):
            """The tools one call offered, or None for a call that had none."""
            return offered[index][0]

        def tool_choice(self, index=0):
            """What one call said about using its tools, as the caller gave it."""
            return offered[index][1]

        def tool_results(self, index=0):
            """The `role: tool` messages one call was sent."""
            return [m for m in asked[index] if m.get("role") == "tool"]

    with mock.patch.object(llm, "call", fake_call), \
            mock.patch.object(llm, "ask", fake_ask):
        yield Recorder()


@contextlib.contextmanager
def deciding(*answers):
    """
    Answer as the decision model would, from a script rather than the network.

    The sibling of `replying` for `world.decisions`, and the same contract:
    one argument per call, used in order, the last repeated. An `Exception` is
    raised instead of answered, for a test about the error path.

    Each answer is written the way a test means it and expanded here:

    * a `dict` of {question name: number} becomes the `noul` shape the service
      sends back, which is the form almost every test wants;
    * a `dict` already carrying typed answers is sent as it stands, for a test
      about a `choice` or a `score`, or about a reply that is malformed;
    * a bare number answers whatever single question was asked, so a test with
      one question need not name it.

    Records what was asked: `recorder.state(0)` and `recorder.questions(0)`,
    which between them are everything there is to assert about a decision --
    what the model was told, and what it was asked about it.
    """
    scripted = list(answers) or [{}]
    asked = []      # (state, questions) for each call, in order

    def fake_decide(sponsor, model, state, questions,
                    timeout=llm.DECIDE_TIMEOUT):
        asked.append((state, questions))
        answer = scripted[min(len(asked) - 1, len(scripted) - 1)]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, (int, float)) and not isinstance(answer, bool):
            answer = {name: answer for name in questions}
        return {name: value if isinstance(value, dict)
                else {"type": "noul", "noul": float(value)}
                for name, value in (answer or {}).items()}

    class Recorder:
        @property
        def count(self):
            return len(asked)

        def state(self, index=0):
            """What the model was told, as the caller gave it."""
            return asked[index][0]

        def questions(self, index=0):
            """What it was asked, as the caller gave it."""
            return asked[index][1]

        def told(self, index=0):
            """Everything in one call's state, as a single string."""
            return "\n".join(str(value)
                             for value in (asked[index][0] or {}).values())

    with mock.patch.object(llm, "decide", fake_decide):
        yield Recorder()


def as_json(data):
    """A reply whose text is this object, the way a generator expects it."""
    return json.dumps(data)


#: Tool call ids, unique across a test run, so two calls to one tool in one
#: reply can still be told apart by the results that answer them.
_CALL_IDS = itertools.count(1)


def tool_call(name, /, **args):
    """
    One tool call, the way a model sends it.

    The arguments are a JSON *string*, not an object. That is the detail a
    hand-written fake most often gets wrong, and code tested against the wrong
    shape passes here and fails against a real model.

    The tool's name is positional only, so a tool whose own argument is
    called `name` -- `create`, `examine`, `name_taken` -- can still be given it.
    """
    return {"id": f"call_{next(_CALL_IDS)}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def tool_reply(*calls, content=None):
    """A whole reply carrying these tool calls, for `replying` to send back."""
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = list(calls)
    return {"choices": [{"message": message}]}


class Finishing:
    """
    A reply that answers whichever finish tool the call it is sent to offers.

    What a script needs once every generator is a tool loop. An attempt asks
    up to four questions -- what a verb takes, what it does, whether a sort of
    thing admits it, what happened -- and which of them are asked depends on
    what the world already knows. A script of replies in order has to predict
    that; this does not, so a test writes each answer once, by tool name, and
    only the questions actually asked are answered.

    A call offering none of the named tools gets a reply saying nothing, which
    a loop treats as a model that will not answer.
    """

    def __init__(self, answers):
        self.answers = dict(answers)

    def reply(self, tools):
        for schema in tools or ():
            name = ((schema or {}).get("function") or {}).get("name")
            if name in self.answers:
                return tool_reply(tool_call(name, **self.answers[name]))
        return {"choices": [{"message": {"content": ""}}]}


def finishing(**answers):
    """`Finishing`, written as `finishing(narrate={...}, admit={...})`."""
    return Finishing(answers)


def clock():
    """
    A reactor clock a test moves by hand.

    Anything that runs on a timer takes one of these, so a test can advance
    ten seconds with `clock.advance(10)` instead of waiting ten seconds.
    """
    from twisted.internet import task

    return task.Clock()


class FakeSponsor:
    """
    Enough of a sponsor to be handed to a generator.

    A generator wants four things -- which model answers for a job, the key to
    ask with, where to send it, and whether there is going to be an answer at
    all -- and a real `Sponsor` reaches a database row with a password behind
    it. This is the four, and nothing to set up.

    It was `FakeAccount`, and it is not an account any more -- which is the
    whole point of the change it was renamed for: what pays for a call
    belongs to a world rather than to whoever happens to be typing.
    """

    def __init__(self, model="test/model", key="sk-test", params=None,
                 base_url="https://example.test/v1", actor=None,
                 world_root=None, record=None):
        self._model = model
        self._key = key
        self.params = params or {}
        self.base_url = base_url
        self.account = None
        self.actor = actor
        self.world_root = world_root
        #: The model's entry in the service's model list, for code that asks
        #: what a model supports. Tools by default, because every generator
        #: needs them; pass a record without them to test a model that cannot.
        self.record = record if record is not None else {
            "id": model, "supported_parameters": ["tools", "tool_choice"]}

    @property
    def payer(self):
        return self.account

    @property
    def answers(self):
        return bool(self._key)

    def model_for(self, *jobs):
        from world.model_params import ModelChoice

        return ModelChoice(self._model, self.params,
                           job=jobs[0] if jobs else "")

    def key(self):
        if not self._key:
            raise ValueError("No OpenRouter API key set.")
        return self._key


#: Where the exported corpus lives. See tests/fixtures/export.py for what is in
#: it and why it is not the worlds themselves.
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def worlds(generation=""):
    """
    Every exported world's registers, as plain dicts, by label.

    Real generated data, which is the point: a test that asserts against an
    example somebody invented proves something about the example. These came out
    of worlds that were played.

    `generation` names a later export; without one this is the original corpus,
    exported before the reset that ended the worlds which produced it. Each
    generation is read on its own, because a ratio measured across two engines
    is an average of two different things rather than a bigger sample.

    The corpus is interim -- it was produced by the engine the rulebook change
    replaces -- so a test reading it should assert a *property* over the whole
    corpus ("every requires block evaluates") rather than a fact about one
    record ("rule 47 wants powered"). The first survives the corpus being
    replaced; the second is forty rewrites.
    """
    found = {}
    where = FIXTURES / "worlds" / generation if generation else FIXTURES / "worlds"
    for path in sorted(where.glob("world-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        found[record["label"]] = record
    return found


def all_rules():
    """(label, key, rule) for every rule in the corpus, valid or refused."""
    for label, record in worlds().items():
        for key, rule in sorted(record["verb_rules"].items()):
            yield label, key, rule
