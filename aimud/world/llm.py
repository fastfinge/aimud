"""
Everything that talks to OpenRouter, in one place.

It was six places. `verb_gen`, `worldgen`, `npc_gen`, `item_gen`, `quest_gen`
and `fact_gen` each carried a private `_call_openrouter` of its own -- the same
twenty lines, near enough -- and `memory_cmds` reached across into `verb_gen` to
borrow that module's copy. The six had drifted in three ways, none of them
deliberate: two waited sixty seconds and four waited thirty, five returned the
text out of the reply while one returned the whole reply, and one accepted tool
definitions.

Six copies of an HTTP call is untidy. Six copies with no single seam is the
reason this game has had no repeatable tests: faking a model's answer meant
patching six private functions and knowing which one a given code path would
reach, so nobody did, and every test was written against a live model or not
written. **One module is one thing to fake**, and that is most of what this is
for.

It is also the one place an error can be explained. A key with no credit left
used to reach the player as `'choices'` -- a KeyError from indexing a reply that
was an error report rather than an answer -- and a mistyped model name as "HTTP
Error 400: Bad Request". OpenRouter says what is actually wrong, in words, in
the body of both; `_complain` below reads it and `LLMError` carries it, so what
somebody is told is "This endpoint's maximum context length is 8192 tokens"
rather than a punctuation mark.

Everything above `fetch` is synchronous, touches no database and no Evennia
object, and expects to be called from a thread -- a network round trip on the
reactor would stop the world for everybody. `fetch` is the one function here
that knows about the reactor, and it is the door: it takes the work off the
reactor and brings the answer back.

That door matters more for testing than it looks. Without a running reactor a
`deferToThread` callback never fires at all -- measured, not assumed -- so a
test that drove a generator through one would pass while asserting nothing,
which is worse than failing. One door is one thing for a test to make
synchronous.
"""

import json
import queue
import urllib.error
import urllib.request

from twisted.internet import threads

#: Where the service lives when nobody has chosen otherwise. One constant
#: rather than six, and now a default rather than the only answer: a sponsor
#: may point at another provider, and the URL follows whoever pays rather than
#: being a fact about the game. See `world.sponsor`.
BASE_URL = "https://openrouter.ai/api/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"
MODELS_URL = f"{BASE_URL}/models"


def _chat_url(base):
    return f"{str(base or BASE_URL).rstrip('/')}/chat/completions"


def _models_url(base):
    return f"{str(base or BASE_URL).rstrip('/')}/models"

#: How long to wait. Two values, because the old copies used two and the
#: difference is real rather than an oversight: a room description or a set of
#: remembered facts is a long answer from a model that may be thinking, while a
#: verb rule or a line of dialogue is short and somebody is waiting for it. Both
#: are named, so that a caller choosing the slow one is visibly choosing it.
TIMEOUT = 30
SLOW_TIMEOUT = 60

#: Listing the models is neither of those, and is not a generation call at all.
LIST_TIMEOUT = 15

#: How much of an error body to keep. These are sentences, not documents, and
#: whatever is shown has to fit in a line somebody is reading.
MAX_COMPLAINT = 300


class LLMError(Exception):
    """
    What the service said when it would not answer.

    Raised instead of letting a KeyError out of a reply that turned out to be an
    error report. Every caller already routes an exception here to its own
    `on_error`, so this changes what a player is told and not what happens next.
    """


def _complain(body):
    """
    OpenRouter's own words for why it would not answer, or "".

    The shape is `{"error": {"message": ..., "code": ...}}`, and it arrives both
    inside a 200 and as the body of a 4xx. Anything else -- a proxy's HTML, an
    empty body, a reply that is not JSON at all -- comes back empty, and the
    caller falls through to saying plainly that it does not know.
    """
    if isinstance(body, (bytes, str)):
        try:
            body = json.loads(body)
        except (ValueError, TypeError):
            return ""
    try:
        said = str((body.get("error") or {}).get("message") or "").strip()
    except AttributeError:
        return ""
    return said[:MAX_COMPLAINT]


def _request(url, api_key, payload=None, timeout=TIMEOUT):
    """
    One HTTP round trip. Blocking: call it from a thread.

    An HTTP error is turned into an `LLMError` carrying whatever the service
    said, because the status line alone is never the useful half: "400" covers a
    model that does not exist, a context window overrun and a malformed tool
    definition, and the body says which.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {api_key}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=data, headers=headers,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:
        # The body is readable exactly once, and only before the handler is
        # disposed of -- so it is read here or not at all.
        try:
            said = _complain(err.read())
        except Exception:
            said = ""
        raise LLMError(said or f"the model service refused the request "
                               f"({err.code})") from err


def call(sponsor, model, messages, tools=None, timeout=TIMEOUT):
    """
    Ask a model, and answer with the whole reply.

    For the callers that need more than the text: a reply carrying tool calls
    has nothing in its `content` at all, and the calls are the answer.
    Everything else wants `ask`.

    Takes a sponsor rather than a key. The key is the smallest part of what it
    carries -- the service to talk to and who to charge come with it -- and
    unpacking it into a key at the top of every generator is what left the
    other two with nowhere to travel.
    """
    # The sampling settings chosen for this job ride on the model choice. See
    # world.model_params: only what the player actually set is sent.
    from world.model_params import of as settings

    payload = {"model": model, "messages": messages}
    payload.update(settings(model))
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    reply = _request(_chat_url(sponsor.base_url), sponsor.key(), payload,
                     timeout)
    _spent(sponsor, model, reply)
    return reply


def content(reply):
    """
    The text a reply carries, or "" if it carries none.

    Tolerant on purpose. A reply with tool calls and no text, a reply whose
    `content` is null, and a reply that arrived in pieces are all the same
    answer to the only question being asked here; a caller that needs to tell
    them apart has the whole reply from `call`.
    """
    try:
        return reply["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def ask(sponsor, model, messages, timeout=TIMEOUT):
    """
    Ask a model, and answer with the text. What almost everything wants.

    Empty is not a usable answer for any caller here -- all of them go straight
    on to read JSON out of it -- so it is reported rather than returned, with
    whatever the service said about why.
    """
    reply = call(sponsor, model, messages, timeout=timeout)
    text = content(reply)
    if text:
        return text
    raise LLMError(_complain(reply) or "the model returned no text")


def models(sponsor, timeout=LIST_TIMEOUT):
    """Every model this key can reach, ordered by id. For the `models` menu."""
    listed = _request(_models_url(sponsor.base_url), sponsor.key(),
                      timeout=timeout)
    try:
        return sorted(listed["data"], key=lambda record: record["id"])
    except (KeyError, TypeError) as err:
        raise LLMError(_complain(listed)
                       or "the model service sent no list of models") from err


#: Calls that have happened but have not been written down yet.
#:
#: A reply arrives in a worker thread, where the token counts are, and the
#: ledger is an Evennia attribute, which may only be written on the reactor.
#: So the thread leaves the figures here and `fetch` picks them up on the way
#: back -- a queue rather than a thread-local, because the hand-off crosses
#: exactly that boundary and a thread-local does not.
#:
#: Unbounded is deliberate: entries are drained by the very next callback, and
#: a cap here would silently discard the record of money that was spent, which
#: is the one thing this must not do.
_spending = queue.Queue()


def _spent(sponsor, model, reply):
    """
    Note what a reply cost, from inside the thread that received it.

    Never raises and never touches the database. Bookkeeping must not be able
    to lose an answer somebody is waiting for.
    """
    try:
        _spending.put_nowait((sponsor, model, (reply or {}).get("usage")))
    except Exception:
        pass


def _write_down_spending():
    """Drain what the threads left, on the reactor, where writing is allowed."""
    from world import ledger

    while True:
        try:
            sponsor, model, usage = _spending.get_nowait()
        except queue.Empty:
            return
        ledger.note(sponsor, model, usage)


def fetch(work, *args, on_success, on_error):
    """
    Do `work(*args)` off the reactor, and hand what it returns back on it.

    A pass-through, deliberately: `on_error` is given the Failure exactly as
    `addCallbacks` would, because this arrived as a refactor of twenty call
    sites and a refactor that also changed what a handler receives would be two
    changes wearing one hat. What it buys is the seam -- one function to make
    synchronous, instead of twenty `deferToThread` calls to find and patch.

    The callbacks are keyword-only so that a call reads in the order it happens:
    the work and its arguments first, then what becomes of the answer.

    Both paths write the ledger down first. A call that failed on the way back
    -- a reply that parsed badly, a generator that threw -- was still paid for,
    and recording only the successes would make the figures quietly wrong in
    exactly the direction nobody would notice.
    """
    def _succeeded(result):
        _write_down_spending()
        return on_success(result)

    def _failed(failure):
        _write_down_spending()
        return on_error(failure)

    return threads.deferToThread(work, *args).addCallbacks(_succeeded, _failed)
