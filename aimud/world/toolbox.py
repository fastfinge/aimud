"""
The tools a model is offered for one call, and what becomes of each use.

Phase 3 of docs/generator-tool-loops.md. `llm.converse` is the loop; this is
what it runs. Nothing here imports a game module: a tool's description, its
parameters and whether it is offered at all are worked out from a context at
call time, by whoever defines the tool, which keeps each schema beside the
record it describes.

Three kinds of tool, told apart by two flags:

* **A lookup** (`looks=True`) answers a question. The loop goes round again so
  the model can use the answer, and a lookup asked twice with the same
  arguments is answered from what it said the first time.
* **A finish tool** (`finishes=True`) is how a generator answers. Its handler
  accepts the answer or complains about it, and a complaint is sent back for
  the model to put right.
* **Anything else acts.** A round that only acted, with no finish tool
  waiting, ends the conversation: the acts have happened, and asking again
  would only buy more of them.

A handler is `handler(ctx, args, answer)` and calls `answer` exactly once,
now or later: with text, with `accept(value)`, or with `complain(text)`. A
tool marked `threaded` is `handler(ctx, args)`, runs off the reactor through
`llm.fetch`, and returns its text.
"""

import json

from evennia.utils import logger

#: The most a single tool result may say, in characters. Anything longer is
#: cut, and says so: every list tool takes a query, a limit and an offset, so
#: a model can always ask again more precisely.
MOST_RESULT = 4000

#: The most tool calls run from one reply. A small model that answers with
#: twenty lookups at once is told to ask again rather than being obliged.
MOST_CALLS_PER_ROUND = 8

CUT_SHORT = "\n[... cut short: ask again for less, or for the rest]"


class ToolContext:
    """Everything a tool may need to know about the call it is part of."""

    def __init__(self, world_root=None, room=None, actor=None, bound=None,
                 sponsor=None, job="", wait=None, **extra):
        self.world_root = world_root
        self.room = room
        self.actor = actor
        self.bound = dict(bound or {})
        self.sponsor = sponsor
        self.job = job
        self.wait = wait
        self.extra = extra


class Accepted:
    """A finish tool's answer, taken. `said` is what the model is told."""

    __slots__ = ("value", "said")

    def __init__(self, value, said="Accepted."):
        self.value = value
        self.said = said


class Complaint:
    """
    A finish tool's answer, sent back. `value` is what was answered, kept in
    case the rounds run out and the generator decides to take it as it stands.
    """

    __slots__ = ("text", "value")

    def __init__(self, text, value=None):
        self.text = str(text or "That was not accepted.")
        self.value = value

    def __str__(self):
        return self.text


def accept(value, said="Accepted."):
    return Accepted(value, said)


def complain(text, value=None):
    return Complaint(text, value)


class Tool:
    """
    One tool. `description` and `parameters` may be callables taking the
    context, for anything that has to be filled in at call time.
    """

    def __init__(self, name, description="", parameters=None, handler=None,
                 doing="", looks=False, finishes=False, threaded=False,
                 available=None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.doing = doing
        self.looks = looks
        self.finishes = finishes
        self.threaded = threaded
        self.available = available

    def offered(self, ctx):
        return True if self.available is None else bool(self.available(ctx))

    def schema(self, ctx):
        def filled(value):
            return value(ctx) if callable(value) else value

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": str(filled(self.description) or ""),
                "parameters": portable(filled(self.parameters)
                                       or {"type": "object",
                                           "properties": {}}),
            },
        }


def portable(schema):
    """
    A schema every provider will accept, as far as this game has found out.

    Enums are the sharp edge. An empty member -- which four fields offered to
    mean "leave this out" -- is refused outright by Google's validation, and
    the call fails before a tool is ever chosen. In the first soak of the tool
    loops that was every item, every character and every verb declaration,
    each failing in a third of a second, while the room schemas, which carry
    no such enum, went through on the same model.

    Dropped here, at the one point every schema passes through, rather than
    left to the dozen places that build one -- several of which fill an enum
    from the world's own names, where a blank is a data question rather than a
    spelling one. A field left with no members keeps no enum and stays open;
    its handler checks what comes back, as it did anyway.
    """
    if isinstance(schema, dict):
        cleaned = {key: portable(value) for key, value in schema.items()}
        if "enum" in cleaned:
            kept = [member for member in (cleaned.get("enum") or [])
                    if not isinstance(member, str) or member.strip()]
            if kept:
                cleaned["enum"] = kept
            else:
                cleaned.pop("enum", None)
        return cleaned
    if isinstance(schema, list):
        return [portable(member) for member in schema]
    return schema


def from_schema(schema, handler, **flags):
    """A tool for a schema somebody has already built, such as an NPC's."""
    function = schema["function"]
    return Tool(function["name"], function.get("description", ""),
                function.get("parameters"), handler, **flags)


def problems_with(args, parameters):
    """
    What is wrong with a tool call's arguments, by the schema's own promises.

    Cheap on purpose, and only what the schema itself says: required fields
    present, enum members real, numbers whole and in range, booleans boolean.
    A provider that honours the schema never trips this, and one that does not
    is caught before a handler has to be defensive about it.
    """
    if not isinstance(args, dict):
        return ["the arguments have to be an object"]
    parameters = parameters or {}
    properties = parameters.get("properties") or {}
    found = []
    for name in parameters.get("required") or []:
        if args.get(name) in (None, ""):
            found.append(f"{name} is required")
    for name, value in args.items():
        spec = properties.get(name)
        if spec is None or value is None:
            continue
        # A field left out is now said by leaving it out, but a model taught
        # by every other schema it has read sends "" instead, and refusing
        # that would cost a round over nothing. An optional field given
        # nothing is a field nobody filled in.
        if value == "" and name not in (parameters.get("required") or []):
            continue
        if "enum" in spec and value not in spec["enum"]:
            shown = ", ".join(str(choice) for choice in spec["enum"][:20])
            found.append(f"{name} has to be one of: {shown}")
            continue
        kind = spec.get("type")
        if kind == "boolean" and not isinstance(value, bool):
            found.append(f"{name} has to be true or false")
        elif kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                found.append(f"{name} has to be a whole number")
                continue
            if "minimum" in spec and value < spec["minimum"]:
                found.append(f"{name} has to be at least {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                found.append(f"{name} has to be at most {spec['maximum']}")
    return found


def params(properties=None, required=()):
    """A tool's parameters, in the conservative dialect every provider honours."""
    return {"type": "object", "properties": dict(properties or {}),
            "required": list(required), "additionalProperties": False}


#: The paging arguments every list tool takes, so a model can always ask for
#: less, or for the rest.
PAGE = {
    "query": {"type": "string",
              "description": "Optional. Only entries containing these words"},
    "limit": {"type": "integer", "minimum": 1, "maximum": 50,
              "description": "Optional. How many to show; 20 unless said"},
    "offset": {"type": "integer", "minimum": 0,
               "description": "Optional. How many to skip, to see more"},
}


#: The most values a field is closed to by an enum. An enum is a list too, and
#: it sits in the tool schema, which is part of every round's prompt; past
#: this, a field is left open and its handler checks membership instead. A
#: starting point for the soak to revisit (§4.1).
ENUM_MOST = 50


def choice(values, description="", most=ENUM_MOST, ask=""):
    """
    A string field closed to `values` while there are few enough to list.

    Past `most` the field is open, and its description says how many there are
    and which lookup lists them, so a model can still find the one it wants.
    The handler is then what refuses a value that is not one of them.
    """
    values = list(dict.fromkeys(str(value) for value in values
                                if str(value)))
    field = {"type": "string", "description": str(description or "")}
    if values and len(values) <= most:
        field["enum"] = values
    elif values and ask:
        field["description"] = (f"{field['description']} There are "
                                f"{len(values)} to choose from; {ask} lists "
                                f"them.").strip()
    return field


def paged(entries, args, noun="entries", most=20):
    """A list, filtered by `query` and cut to `limit` from `offset`, as text."""
    entries = [str(entry) for entry in entries]
    query = str((args or {}).get("query") or "").lower().strip()
    if query:
        entries = [entry for entry in entries if query in entry.lower()]
    try:
        limit = max(1, int((args or {}).get("limit") or most))
        offset = max(0, int((args or {}).get("offset") or 0))
    except (TypeError, ValueError):
        limit, offset = most, 0
    matching = f" matching '{query}'" if query else ""
    shown = entries[offset:offset + limit]
    if not shown:
        return (f"No {noun}{matching}" + (" past that offset" if offset else "")
                + ".")
    lines = [f"{len(entries)} {noun}{matching}; showing {offset + 1} to "
             f"{offset + len(shown)}:"] + shown
    if offset + len(shown) < len(entries):
        lines.append(f"(Ask again with offset={offset + len(shown)} for more.)")
    return "\n".join(lines)


def answering(work):
    """A handler for a lookup that answers at once: `work(ctx, args)` -> text."""
    def handler(ctx, args, answer):
        answer(work(ctx, args))

    return handler


def said(result):
    """What a tool result tells the model, cut to size."""
    text = result.text if isinstance(result, Complaint) else (
        result.said if isinstance(result, Accepted) else str(result or "Done."))
    if len(text) > MOST_RESULT:
        text = text[:MOST_RESULT - len(CUT_SHORT)] + CUT_SHORT
    return text


class Toolbox:
    """The tools for one call, and the bookkeeping of how they were used."""

    def __init__(self, tools, ctx=None):
        self.ctx = ctx or ToolContext()
        self.tools = [tool for tool in tools if tool.offered(self.ctx)]
        self.by_name = {tool.name: tool for tool in self.tools}
        # Worked out once, when the loop starts, and never between rounds:
        # an unchanging tool list is a prefix a provider can cache, and
        # nothing a generator registers is written before its answer is
        # accepted, so there is nothing new to show mid-loop.
        self.schemas = [tool.schema(self.ctx) for tool in self.tools]
        self._parameters = {schema["function"]["name"]:
                            schema["function"].get("parameters")
                            for schema in self.schemas}
        self.finish = next((tool for tool in self.tools if tool.finishes),
                           None)
        self._remembered = {}
        #: How often each tool was called, and how many complaints were sent
        #: back. Read by the measurement line when the loop ends.
        self.used = {}
        self.complaints = 0

    def run(self, call, answer):
        """
        Run one tool call from a reply, and hand `answer` what came of it:
        text, an `Accepted` or a `Complaint`. Never raises, and answers once.
        """
        answered = []

        def once(result):
            if answered:
                return
            answered.append(True)
            if isinstance(result, Complaint):
                self.complaints += 1
            answer(result)

        function = (call or {}).get("function") or {}
        name = str(function.get("name") or "")
        tool = self.by_name.get(name)
        if tool is None:
            return once(f"There is no tool called {name!r}. The tools are: "
                        f"{', '.join(self.by_name) or 'none'}.")
        self.used[name] = self.used.get(name, 0) + 1

        from world.model_json import parse_object

        try:
            args = parse_object(function.get("arguments") or "{}")
        except ValueError:
            return once(self._refusal(tool, "those arguments could not be "
                                            "read; send them again as JSON"))
        wrong = problems_with(args, self._parameters.get(name))
        if wrong:
            return once(self._refusal(tool, "; ".join(wrong)))

        key = (name, json.dumps(args, sort_keys=True, default=str))
        if tool.looks and key in self._remembered:
            return once(self._remembered[key]
                        + "\n(Asked already: this is the same answer.)")

        def settled(result):
            if tool.looks and isinstance(result, str):
                self._remembered[key] = result
            once(result)

        if self.ctx.wait is not None and tool.doing:
            self.ctx.wait.stage(tool.doing)

        if tool.threaded:
            from world import llm

            def failed(failure):
                logger.log_err(f"toolbox: {name} failed: "
                               f"{failure.getErrorMessage()}")
                once("That lookup failed.")

            return llm.fetch(tool.handler, self.ctx, args,
                             on_success=settled, on_error=failed)
        try:
            tool.handler(self.ctx, args, settled)
        except Exception:
            logger.log_trace(f"toolbox: {name} raised")
            once("That failed, and nothing was done.")
        return None

    @staticmethod
    def _refusal(tool, why):
        if tool.finishes:
            return Complaint(why[:1].upper() + why[1:] + ".")
        return f"Not done: {why}."
