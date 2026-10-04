"""
The `call_tool` effect: a rule asking a service something, or having it act.

A tool reaches a world only through this effect, so players, characters and
agents all reach one the same way: by using a verb whose rule calls it. See
docs/mcp-client.md §6 and §7. `world/services.py` is the register and the
wire; this module is what a rule says about a call and what becomes of the
answer.

**Stored flat.** A rule is a list of effects inside a list of rules, so an
effect holding a list of spelled-out objects would be three deep, which
Google refuses on a tool call (`tests/test_schema_portability.py`). Both
halves are mappings of strings instead, the shape `try`'s `roles` already has:

    {"type": "call_tool", "tool": "weather.forecast",
     "args": {"city": "word:direct", "units": "value:metric"},
     "results": {"conditions": "state:here", "text": "actor"},
     "does": "Gets today's forecast for a city."}

**Where an argument comes from** (§7.2):

    value:<text>          fixed when the rule was written
    word:<role>           the word typed for a role: `forecast london`
    name:<role>           the bound thing's name
    trait:<role>:<trait>  a figure kept about a role
    state:<role>:<group>  which of a group's conditions a role is in
    ask                   asked when the verb is used

**Where an answer goes** (§7.4). A key is a field of the answer's structure,
or `text` for the whole of what it said:

    state:<role>          a bounded field (an enum or a boolean) as a condition
    trait:<role>:<trait>  a numeric field as a figure
    description:<role>    text, as what the thing looks like
    actor                 text, told privately to whoever used the verb

A result lands in the world, or with whoever asked. It is never narration:
the narrator sees the world after the batch has run, and says it is raining
because it is raining.

**Running.** `effects.apply` is synchronous and a call takes seconds, so a
rule holding a `call_tool` runs in two halves: `prepare` makes the calls,
through `llm.fetch`, and hands back copies of the effects with each answer
attached; then the rule's effects run as one batch, and `apply` here reads
the answer it was handed. If a call fails, nothing in the batch is applied.
"""

from collections.abc import Mapping

from evennia.utils import logger

#: Where an argument may come from.
SOURCES = (
    ("value", "a fixed value, written now"),
    ("word", "the word somebody typed for a part of the sentence"),
    ("name", "the name of a thing in the sentence"),
    ("trait", "a figure kept about somebody"),
    ("state", "which condition of a group something is in"),
    ("ask", "asked whenever the verb is used"),
)
SOURCE_NAMES = tuple(name for name, _said in SOURCES)

#: Where an answer may go.
TARGETS = (
    ("state", "a condition of something, from a field with set answers"),
    ("trait", "a figure kept about somebody, from a number"),
    ("description", "what something looks like, from text"),
    ("actor", "told privately to whoever used the verb, from text"),
)
TARGET_NAMES = tuple(name for name, _said in TARGETS)

#: The answer's key for everything it said, rather than one field of it.
TEXT = "text"

#: How much told text a character's prompt is given. Search results run long,
#: and the whole page is still remembered; this is what it reads now.
TOLD_CAP = 1500

#: The roles an argument or answer may name. `here` is the room, which effects
#: resolve themselves; nothing ever binds it.
ROLES = ("actor", "direct", "instrument", "target", "container", "source",
         "here")

#: What a `call_tool` effect is told back by `prepare`, on a copy of it.
ANSWER = "_answer"
CALLED = "_called"


# ---------------------------------------------------------------------------
# Reading what a rule says
# ---------------------------------------------------------------------------

def read_source(text):
    """
    {"from", "role", "name", "value"} for one argument's source, or None.

    `value:` keeps everything after the first colon, so a fixed value may
    itself hold colons.
    """
    text = str(text or "").strip()
    if text == "ask":
        return {"from": "ask"}
    kind, _colon, rest = text.partition(":")
    kind = kind.strip().lower()
    if kind == "value":
        return {"from": "value", "value": rest}
    parts = [part.strip() for part in rest.split(":")]
    role = parts[0].lower() if parts and parts[0] else ""
    if kind in ("word", "name") and role in ROLES:
        return {"from": kind, "role": role}
    if kind in ("trait", "state") and role in ROLES and len(parts) > 1 and parts[1]:
        return {"from": kind, "role": role, "name": parts[1]}
    return None


def read_target(text):
    """{"to", "role", "name"} for one answer's destination, or None."""
    text = str(text or "").strip().lower()
    if text == "actor":
        return {"to": "actor"}
    kind, _colon, rest = text.partition(":")
    parts = [part.strip() for part in rest.split(":")]
    role = parts[0] if parts and parts[0] else ""
    if kind in ("state", "description") and role in ROLES:
        return {"to": kind, "role": role}
    if kind == "trait" and role in ROLES and len(parts) > 1 and parts[1]:
        return {"to": "trait", "role": role, "name": parts[1]}
    return None


def write_source(source):
    kind = source.get("from")
    if kind == "ask":
        return "ask"
    if kind == "value":
        return f"value:{source.get('value', '')}"
    if kind in ("trait", "state"):
        return f"{kind}:{source.get('role')}:{source.get('name')}"
    return f"{kind}:{source.get('role')}"


def write_target(target):
    kind = target.get("to")
    if kind == "actor":
        return "actor"
    if kind == "trait":
        return f"trait:{target.get('role')}:{target.get('name')}"
    return f"{kind}:{target.get('role')}"


def _role_said(role):
    from world import conditions

    return {"here": "this place"}.get(role) or conditions._SUBJECT_WORDS.get(role, role)


def said_source(text):
    """One argument's source as words."""
    source = read_source(text)
    if source is None:
        return f"something unreadable ({text})"
    kind = source["from"]
    if kind == "ask":
        return "asked when the verb is used"
    if kind == "value":
        return repr(source.get("value", ""))
    role = _role_said(source.get("role"))
    if kind == "word":
        return f"the word typed for {role}"
    if kind == "name":
        return f"the name of {role}"
    if kind == "trait":
        return f"{role}'s {source.get('name')}"
    return f"which {source.get('name')} condition {role} is in"


def said_target(text):
    """One answer's destination as words."""
    target = read_target(text)
    if target is None:
        return f"somewhere unreadable ({text})"
    kind = target["to"]
    if kind == "actor":
        return "told to whoever used the verb"
    role = _role_said(target.get("role"))
    if kind == "state":
        return f"a condition of {role}"
    if kind == "trait":
        return f"{role}'s {target.get('name')}"
    return f"what {role} looks like"


def args_of(effect):
    try:
        return {str(k): str(v) for k, v in dict(effect.get("args") or {}).items()}
    except (TypeError, ValueError, AttributeError):
        return {}


def results_of(effect):
    try:
        return {str(k): str(v) for k, v in dict(effect.get("results") or {}).items()}
    except (TypeError, ValueError, AttributeError):
        return {}


def say(effect):
    """`effects.say` for a `call_tool`: what using the verb will do."""
    from world import services

    tool = str(effect.get("tool") or "a service")
    _record, info = services.find(tool)
    level = (info or {}).get("level")
    if level == services.ACTS:
        head = f"has {tool} act outside the game"
    else:
        head = f"asks {tool}"
    landed = [f"{field if field != TEXT else 'what it says'} as {said_target(where)}"
              for field, where in results_of(effect).items()]
    if landed:
        head += ", with " + "; ".join(landed)
    return head


# ---------------------------------------------------------------------------
# Whether a rule's call is one that can be made
# ---------------------------------------------------------------------------

def complaints(effect, records=None, by_model=False):
    """
    Everything wrong with one `call_tool` effect, as sentences. [] when none.

    The same checks for a person's rule and a model's: the tool exists and is
    on, every required parameter has a source and every source reads, and
    every answer lands where its field can go. A model may not `ask`, because
    a rule it writes is used by characters and the planner, who cannot always
    be asked. §7.6.
    """
    from world import services

    wanted = str(effect.get("tool") or "").strip()
    record, info = services.find(wanted, records)
    if record is None:
        return [f"there is no service for {wanted or 'that tool'} on this server"]
    if info is None:
        return [f"{record['name']} has no tool called {services.split_id(wanted)[1]}"]
    if info.get("refused"):
        return [f"{wanted} cannot be called by a rule: {info['refused']}"]
    if not info.get("on"):
        return [f"{wanted} is switched off on this server"]

    said = []
    args = args_of(effect)
    params = {name: (schema, required)
              for name, schema, required in services.parameters(info.get("input"))}
    unusable = dict(services.left_out(info.get("input")))
    for name, text in args.items():
        if name in unusable:
            said.append(f"{name} cannot be given by a rule: {unusable[name]}")
            continue
        if name not in params:
            said.append(f"{wanted} takes nothing called {name}")
            continue
        source = read_source(text)
        if source is None:
            said.append(f"{name}'s source, {text!r}, is not one this game reads")
        elif source["from"] == "ask" and by_model:
            said.append(f"{name} cannot be asked in a rule a model writes")
    for name, (_schema, required) in params.items():
        if required and name not in args:
            said.append(f"{wanted} needs {name}, and nothing says where it comes from")

    fields = dict(services.outputs(info.get("output")))
    for field, text in results_of(effect).items():
        target = read_target(text)
        if target is None:
            said.append(f"where {field} goes, {text!r}, is not one this game reads")
            continue
        schema = fields.get(field)
        if field == TEXT:
            if target["to"] not in ("description", "actor"):
                said.append("what a tool says in words can only become a "
                            "description or be told to whoever asked")
            continue
        if schema is None:
            said.append(f"{wanted} gives nothing called {field}")
            continue
        kind = target["to"]
        if kind == "state" and not services.is_bounded(schema):
            said.append(f"{field} is not one of a set of answers, so it cannot "
                        f"be a condition -- every answer would be a new one")
        elif kind == "trait" and not services.is_numeric(schema):
            said.append(f"{field} is not a number, so it cannot be a figure")
        elif kind in ("description", "actor") and not services.is_text(schema):
            said.append(f"{field} is not text, so it cannot be told or described")
    return said


def complete(effect, records=None, world_root=None):
    """
    The effect as it is kept: `does` copied from the service, never written.

    Copied when the rule is written, not read live, so a service rewording its
    description cannot change what a rule means; the fingerprint catches a
    real change (§10.4). And an enum mapped onto a condition registers its
    values with this world now, so the rules about rain can be written before
    it rains.
    """
    from world import services

    kept = dict(effect)
    record, info = services.find(kept.get("tool"), records)
    if info is not None:
        kept["does"] = services.does(info)
        kept["fingerprint"] = info.get("fingerprint") or ""
        if world_root is not None:
            _register_states(world_root, info, kept)
    kept["args"] = args_of(kept)
    kept["results"] = results_of(kept)
    return kept


def _register_states(world_root, info, effect):
    from world import services, verbs

    fields = dict(services.outputs(info.get("output")))
    for field, text in results_of(effect).items():
        target = read_target(text)
        schema = fields.get(field)
        if not target or target["to"] != "state" or schema is None:
            continue
        group = verbs.plain(field).replace(" ", "_") or field
        for value in _state_values(field, schema):
            try:
                verbs.register_state(world_root, value, group=group,
                                     means=f"what {field} came back as")
            except Exception as exc:
                logger.log_info(f"tool_calls: could not register {value}: {exc}")


def _slug(value):
    from world import verbs

    return verbs.plain(str(value)).strip().lower().replace(" ", "_")


def _state_values(field, schema):
    """The conditions a bounded field can put something in."""
    if "enum" in schema:
        return [_slug(value) for value in schema["enum"] if str(value).strip()]
    return [_slug(field)]


def tool_ids(effects):
    """Every tool a list of effects calls, as 'service.tool'."""
    found = []
    for effect in effects or []:
        try:
            if str(effect.get("type") or "") == "call_tool" and effect.get("tool"):
                found.append(str(effect["tool"]))
        except AttributeError:
            continue
    return found


def is_call(effect):
    """
    Whether an effect is a `call_tool`. A Mapping test, never a dict one:
    rules come back from a world's attributes as Evennia's _SaverDict.
    """
    return isinstance(effect, Mapping) and effect.get("type") == "call_tool"


def calls_in(effects):
    return [effect for effect in effects or [] if is_call(effect)]


def takes_word(effect, roles=()):
    """Whether this call takes the word typed for one of these roles."""
    roles = set(roles or [])
    for text in args_of(effect).values():
        source = read_source(text)
        if source and source["from"] == "word" and (
                not roles or source.get("role") in roles):
            return True
    return False


def asks(effect):
    """The parameters a call asks for when the verb is used."""
    return [name for name, text in args_of(effect).items()
            if (read_source(text) or {}).get("from") == "ask"]


# ---------------------------------------------------------------------------
# Working out the arguments
# ---------------------------------------------------------------------------

def _thing(role, actor, bound, room):
    if role == "actor":
        return actor
    if role == "here":
        return room
    return (bound or {}).get(role)


def _coerce(value, schema):
    """A value as the parameter's type wants it, or the value as it was."""
    from world import services

    kind = services._type_of(schema or {})
    if kind == "integer":
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value
    if kind == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("yes", "y", "true", "on", "1")
    if kind == "array":
        if isinstance(value, (list, tuple)):
            return list(value)
        return [part for part in str(value).replace(",", " ").split() if part]
    return value if isinstance(value, str) else str(value)


def arguments(effect, info, actor, bound, room, words, answers, world_root):
    """
    (arguments, unanswered) for one call, read off the world as it is now.

    `unanswered` names the `ask` parameters nobody has answered yet, and the
    required ones whose source found nothing -- a word that was not typed, a
    figure nobody keeps. Optional ones that find nothing are left out.
    """
    from world import services, traits, verbs

    params = {name: (schema, required)
              for name, schema, required in services.parameters(info.get("input"))}
    found, unanswered = {}, []
    for name, text in args_of(effect).items():
        source = read_source(text)
        schema, required = params.get(name, ({}, False))
        value = None
        if source is None:
            pass
        elif source["from"] == "value":
            value = source.get("value")
        elif source["from"] == "ask":
            value = (answers or {}).get(name)
        elif source["from"] == "word":
            value = (words or {}).get(source["role"])
            if not value:
                thing = _thing(source["role"], actor, bound, room)
                value = getattr(thing, "key", None) if thing is not None else None
            value = verbs.plain(str(value)) if value else None
        elif source["from"] == "name":
            thing = _thing(source["role"], actor, bound, room)
            value = getattr(thing, "key", None) if thing is not None else None
        elif source["from"] == "trait":
            thing = _thing(source["role"], actor, bound, room)
            if thing is not None and traits.has_traits(thing):
                value = traits.value(thing, source["name"])
        elif source["from"] == "state":
            thing = _thing(source["role"], actor, bound, room)
            if thing is not None:
                members = set(verbs.group_members(world_root, source["name"]) or [])
                held = [slug for slug in verbs.states(thing) if slug in members]
                value = held[0] if held else None
        if value is None or value == "":
            if required or (source or {}).get("from") == "ask":
                unanswered.append(name)
            continue
        found[name] = _coerce(value, schema)
    return found, unanswered


def ask_form(names, info, on_answered, on_quit):
    """
    The form a player is shown for what a call asks, built from its schema.

    An enum is a choice, a boolean is yes or no, a string or number is a field
    with the schema's limits. Its keys are the parameter names, so it is
    reachable by typing like every other form -- and the bracketed answers in
    `answers_in` are the same answers in a line, for whoever has no menu.
    """
    from world import menus, services

    schemas = {name: schema for name, schema, _req in services.parameters(info.get("input"))}
    items = []
    for name in names:
        schema = schemas.get(name) or {}
        help_text = str(schema.get("description") or "")
        if "enum" in schema:
            items.append(menus.Field(
                name, name.replace("_", " "), kind=menus.CHOICE, required=True,
                choices=[menus.Choice(value, str(value))
                         for value in schema["enum"]], help=help_text))
        elif services._type_of(schema) == "boolean":
            items.append(menus.Field(name, name.replace("_", " "),
                                     kind=menus.BOOLEAN, required=True,
                                     help=help_text))
        elif services._type_of(schema) in ("number", "integer"):
            items.append(menus.Field(
                name, name.replace("_", " "), kind=menus.NUMBER, required=True,
                minimum=schema.get("minimum"), maximum=schema.get("maximum"),
                help=help_text))
        else:
            items.append(menus.Field(name, name.replace("_", " "),
                                     required=True, help=help_text))

    # Quitting the form is leaving it, and whoever is waiting on the call has
    # to be told so, or the attempt holds them for ever.
    answered = {"done": False}

    def go(ctx):
        answered["done"] = True
        ctx.dirty = False
        on_answered({name: ctx.draft.get(name) for name in names})
        return ""

    def closed(ctx, _why=None):
        if not answered["done"]:
            on_quit()

    items.append(menus.Action("go", "Go ahead", go, after=menus.CLOSE))
    return menus.Form(
        key="tool-answers", title="It needs to know", guided=True,
        intro=str(info.get("description") or ""), items=items, on_close=closed)


def answers_in(raw):
    """
    (the line without them, {param: value}) for answers typed in brackets.

    `forecast london [units=metric days=3]` -- the one way to answer what a
    call asks without a menu, which is every agent and every character. The
    bracket must close the line.
    """
    import shlex

    text = str(raw or "").rstrip()
    if not text.endswith("]") or "[" not in text:
        return text, {}
    head, _bracket, inside = text.rpartition("[")
    inside = inside[:-1]
    try:
        parts = shlex.split(inside)
    except ValueError:
        return text, {}
    found = {}
    for part in parts:
        name, eq, value = part.partition("=")
        if not eq or not name.strip():
            return text, {}
        found[name.strip()] = value.strip()
    return head.rstrip(), found


def unanswered_said(names, info):
    """What a call still needs, for whoever has no menu to be asked it in."""
    from world import services

    schemas = {name: schema for name, schema, _req in services.parameters(info.get("input"))}
    parts = []
    for name in names:
        schema = schemas.get(name) or {}
        if "enum" in schema:
            kind = "one of " + ", ".join(str(v) for v in schema["enum"])
        else:
            kind = schema.get("type") or "a value"
        parts.append(f"{name} ({kind})")
    example = " ".join(f"{name}=..." for name in names)
    return (f"That needs to know {', '.join(parts)}. Say it on the end in "
            f"brackets: [{example}].")


# ---------------------------------------------------------------------------
# Making the calls
# ---------------------------------------------------------------------------

def prepare(caller, sponsor, world_root, room, bound, words, effects,
            on_ready, on_fail, waiter=None, session=None):
    """
    Make every call a rule's effects hold, then hand the effects back.

    `on_ready(effects)` gets copies with each answer attached; `on_fail(text)`
    is told why not, and nothing in the batch should then be applied. Calls
    that need asking are asked first: a player with a menu gets a form, and
    anybody else is told what to put in brackets. The gate is asked before
    anything leaves the machine. §5.3, §7.3.
    """
    from world import services

    records = services.register()
    typed = dict(getattr(caller.ndb, "tool_answers", None) or {})
    plans = []
    for index, effect in enumerate(effects or []):
        if not is_call(effect):
            continue
        wanted = str(effect.get("tool") or "")
        record, info = services.find(wanted, records)
        if record is None or info is None or not info.get("on") or info.get("refused"):
            on_fail(f"Nothing here can reach {wanted or 'that'} any more.")
            return
        if info.get("fingerprint") and effect.get("fingerprint") and \
                effect["fingerprint"] != info["fingerprint"]:
            on_fail(f"{wanted} is not what this rule was written for any more.")
            return
        refused = services.refusal(sponsor, caller, info.get("level"))
        if refused:
            on_fail(refused)
            return
        plans.append((index, effect, record, info))

    if not plans:
        on_ready(list(effects or []))
        return

    # Everything the calls ask, from what was typed in brackets first.
    missing = {}
    for index, effect, record, info in plans:
        _args, unanswered = arguments(effect, info, caller, bound, room, words,
                                      typed, world_root)
        asked_here = [name for name in unanswered if name in asks(effect)]
        hard = [name for name in unanswered if name not in asks(effect)]
        if hard:
            on_fail(f"That needs {', '.join(hard)}, and nothing here says "
                    f"what it should be.")
            return
        if asked_here:
            missing[index] = (asked_here, info)

    def run(answers):
        _run(caller, sponsor, world_root, room, bound, words, effects, plans,
             answers, on_ready, on_fail, waiter)

    if not missing:
        run(typed)
        return

    names, info = next(iter(missing.values()))
    if not services.is_character(caller) and session is not None:
        from world import menus

        form = ask_form(names, info,
                        on_answered=lambda got: run({**typed, **got}),
                        on_quit=lambda: on_fail("You leave it."))
        if menus.open_menu(caller, form, session=session) is not None:
            return
    on_fail(unanswered_said(names, info))


def _run(caller, sponsor, world_root, room, bound, words, effects, plans,
         answers, on_ready, on_fail, waiter):
    from world import llm, services

    jobs = []
    for index, effect, record, info in plans:
        args, unanswered = arguments(effect, info, caller, bound, room, words,
                                     answers, world_root)
        if unanswered:
            on_fail(unanswered_said(unanswered, info))
            return
        _service, tool = services.split_id(effect.get("tool"))
        retry = bool((info.get("annotations") or {}).get("idempotentHint"))
        jobs.append((index, record, tool, args, retry, info))

    if waiter:
        waiter("asking " + ", ".join(services.tool_id(r["name"], t)
                                     for _i, r, t, _a, _r, _n in jobs))

    def work(jobs):
        # In order, and stopping at the first that fails: a rule whose first
        # call failed applies nothing, so there is no reason to make the rest.
        answers = []
        for index, record, tool, args, retry, info in jobs:
            answer = services.call(record, tool, args, retry=retry)
            answers.append((index, record, tool, args, info, answer))
            if not answer.ok:
                break
        return answers

    def done(results):
        copies = [dict(effect) if isinstance(effect, Mapping) else effect
                  for effect in effects]
        for index, record, tool, args, info, answer in results:
            if info.get("level") == services.ACTS:
                services.note_outward(record["name"], tool, caller, world_root,
                                      sponsor, args, answer)
                if services.is_character(caller):
                    note_acted(caller, effects[index])
            if answer.ok and services.is_character(caller):
                note_found_out(caller, call_key(effects[index]))
            if not answer.ok:
                if answer.reached:
                    on_fail(f"{services.tool_id(record['name'], tool)} "
                            f"said no: {answer.error}")
                else:
                    on_fail(f"{services.tool_id(record['name'], tool)} "
                            f"cannot be reached right now.")
                return
            copies[index][ANSWER] = answer
            copies[index][CALLED] = {"service": record["name"], "tool": tool,
                                     "level": info.get("level")}
        on_ready(copies)

    def failed(failure):
        logger.log_info(f"tool_calls: calls failed: {failure}")
        on_fail("Something went wrong reaching outside the game.")

    llm.fetch(work, jobs, on_success=done, on_error=failed)


# ---------------------------------------------------------------------------
# Landing an answer
# ---------------------------------------------------------------------------

def label(called, text):
    """Told text as a character's model reads it: from outside, and from where."""
    where = f"{called.get('service')}.{called.get('tool')}" if called else "a service"
    return f"(From outside the game, by {where}:) {text}"


def apply(actor, room, effect, bound, world_root, told=None):
    """
    Land one answered call in the world. Returns lines for the room, if any.

    The answer was attached by `prepare`; an effect without one -- a rule run
    some other way than an attempt -- does nothing, rather than calling out
    from a place nobody gated.
    """
    from world import effects as effects_mod
    from world import services

    answer = effect.get(ANSWER)
    called = effect.get(CALLED) or {}
    if answer is None:
        logger.log_info(f"tool_calls: {effect.get('tool')} reached apply "
                        f"without having been called; nothing done")
        return []
    _record, info = services.find(effect.get("tool"))
    fields = dict(services.outputs((info or {}).get("output")))
    lines = []
    for field, text in results_of(effect).items():
        target = read_target(text)
        if target is None:
            continue
        value = answer.text if field == TEXT else answer.field(field)
        if value is None or value == "":
            continue
        kind = target["to"]
        if kind == "actor":
            _tell(actor, called, str(value), told)
            continue
        thing = _thing(target.get("role"), actor, bound, room)
        if thing is None:
            continue
        lent = dict(bound or {})
        lent["__answered"] = thing
        if kind == "state":
            schema = fields.get(field) or {}
            values = _state_values(field, schema)
            if "enum" in schema:
                now = _slug(value)
                sub = {"type": "set_state", "role": "__answered",
                       "add": [now], "remove": [v for v in values if v != now]}
            else:
                truth = value if isinstance(value, bool) else \
                    str(value).strip().lower() in ("true", "yes", "1")
                sub = {"type": "set_state", "role": "__answered",
                       ("add" if truth else "remove"): values}
        elif kind == "trait":
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            sub = {"type": "set_trait", "role": "__answered",
                   "trait": target.get("name"), "set_to": number}
        else:
            sub = {"type": "modify_object", "name_role": "__answered",
                   "new_description": str(value).strip()}
        lines += effects_mod.apply(actor, room, [sub], bound=lent,
                                   world_root=world_root)
    return lines


def _tell(actor, called, text, told):
    """
    Text somebody used a verb to find out, to them and nobody else.

    A player reads it as the private result of their verb. A character has
    it in front of it on its next turn -- where an attempt's outcome already
    goes -- labelled as coming from outside, and remembered, so it can recall
    it later. The room sees the verb, never what came back. §7.4.
    """
    from world import services

    text = text.strip()
    if not text or actor is None:
        return
    if services.is_character(actor):
        shown = text if len(text) <= TOLD_CAP else text[:TOLD_CAP - 3].rstrip() + "..."
        noting = getattr(actor, "_note_to_self", None)
        if noting is not None:
            noting(label(called, shown))
        from world import memory

        memory.remember(actor, label(called, text), kind="learned",
                        importance=0.6)
        return
    if told is not None:
        told.append(text)
    else:
        actor.msg(text)


# ---------------------------------------------------------------------------
# What the rule generator may read about the server's tools (§7.6)
# ---------------------------------------------------------------------------

def tool_said(found, info):
    """One tool, in full, as a model writing a rule needs it."""
    from world import services

    lines = [f"{found} ({services.said_level(info.get('level'))})",
             f"does: {services.does(info) or 'it says nothing about itself'}"]
    for name, schema, required in services.parameters(info.get("input")):
        kind = schema.get("type") or ""
        if "enum" in schema:
            kind = "one of " + ", ".join(str(v) for v in schema["enum"])
        lines.append(f"takes {name}: {kind}"
                     f"{'' if required else ' (optional)'}"
                     + (f" -- {schema['description']}" if schema.get("description") else ""))
    for name, schema in services.outputs(info.get("output")):
        if services.is_bounded(schema):
            where = "can be a condition"
        elif services.is_numeric(schema):
            where = "can be a figure"
        elif services.is_text(schema):
            where = "can be told or described"
        else:
            where = "cannot be kept"
        kind = ("one of " + ", ".join(str(v) for v in schema["enum"])
                if "enum" in schema else schema.get("type") or "")
        lines.append(f"gives {name}: {kind} -- {where}")
    lines.append("gives text: everything it says -- can be told or described")
    return "\n".join(lines)


def lookup_tools():
    """
    `list_tools` and `show_tool`: what this server lets a rule call.

    Offered to the rule loop alone (`rule_gen.TOOL_LOOKUPS`). Available only
    where there is a tool to call, so a world on a server that reaches nothing
    is never shown the idea.
    """
    from world import services
    from world import toolbox as tb

    def listing(ctx, args):
        lines = [f"{found} ({services.said_level(info.get('level'))}): "
                 f"{services.does(info)[:160] or 'says nothing about itself'}"
                 for found, _record, info in services.usable()]
        return tb.paged(lines, args, "tools")

    def showing(ctx, args):
        wanted = str(args.get("tool") or "").strip()
        for found, _record, info in services.usable():
            if found == wanted:
                return tool_said(found, info)
        return (f"This server offers no tool called {wanted}. list_tools "
                f"says what there is.")

    def available(ctx):
        return bool(services.usable())

    return [
        tb.Tool("list_tools",
                "The tools this server lets a rule call outside the game, and "
                "what each does there.",
                tb.params(tb.PAGE), tb.answering(listing),
                doing="looking up the tools this server offers", looks=True,
                available=available),
        tb.Tool("show_tool",
                "What one tool takes, what it gives back, and where each part "
                "of its answer can go.",
                tb.params({"tool": {"type": "string",
                                    "description": "The tool, as service.tool"}},
                          ["tool"]),
                tb.answering(showing), doing="looking up a tool", looks=True,
                available=available),
    ]


# ---------------------------------------------------------------------------
# The planner's three questions about a call (§9)
# ---------------------------------------------------------------------------

#: Where a character keeps how its reaching outside is going for the goal it
#: has now: the acts-outward calls already made for it, and when it last found
#: something out. Keyed by the goal, so a new goal starts clean without
#: anything having to remember to clear it. How a plan is going, not what it
#: is -- `exchange.LEFT`, beside `goal_stalls`.
GOAL_ATTR = "goal_reaching"

#: Seconds before a character may find out the same thing again for one goal.
#: Once and never again would leave a sailor who saw a storm waiting for ever
#: for weather it can no longer look at; every turn would spend a call to
#: learn what it learned a moment ago. Long enough that weather can change.
FIND_OUT_EVERY = 15 * 60


def _goal_mark(actor):
    import json

    goal = getattr(getattr(actor, "db", None), "goal", None)
    if not goal:
        return ""
    try:
        return json.dumps(goal, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(goal)


def _reaching(actor):
    held = dict(getattr(actor.db, GOAL_ATTR, None) or {})
    if held.get("goal") != _goal_mark(actor):
        return {"goal": _goal_mark(actor), "acted": [], "found_out": {}}
    held.setdefault("acted", [])
    held.setdefault("found_out", {})
    return held


def call_key(effect):
    """A call as written, as one string: which tool, and with what."""
    args = ",".join(f"{k}={v}" for k, v in sorted(args_of(effect).items()))
    return f"{effect.get('tool')}({args})"


def level_of(effect, records=None):
    from world import services

    _record, info = services.find(effect.get("tool"), records)
    return (info or {}).get("level")


def reaches_outward(effects, records=None):
    """The acts-outward calls among these effects."""
    from world import services

    return [effect for effect in calls_in(effects)
            if level_of(effect, records) == services.ACTS]


def note_acted(actor, effect):
    """A character with a goal made this acts-outward call for it."""
    if not _goal_mark(actor):
        return
    held = _reaching(actor)
    key = call_key(effect)
    if key not in held["acted"]:
        held["acted"].append(key)
    setattr(actor.db, GOAL_ATTR, held)


def already_acted(actor, effects):
    """
    Whether any acts-outward call here was made already for this goal.

    The planner tries an acts-outward rule at most once per goal: a goal that
    keeps failing must not send the same email twice. A new goal may, which
    is the author's decision to give it.
    """
    if not _goal_mark(actor):
        return False
    acted = set(_reaching(actor)["acted"])
    return any(call_key(effect) in acted for effect in reaches_outward(effects))


def could_tell(effect, condition, records=None):
    """
    Whether this call's answer could put something in the wanted condition.

    Read off the result mapping: a bounded field mapped onto a condition, one
    of whose answers is what the condition wants. That is something a call can
    find out, never something it promises -- which is why `call_tool` is not
    readable backwards, and why this is a separate question. §9.
    """
    from world import conditions as C
    from world import services
    from world.model_json import listed

    _record, info = services.find(effect.get("tool"), records)
    if not info:
        return False
    fields = dict(services.outputs(info.get("output")))
    possible = set()
    for field, text in results_of(effect).items():
        target = read_target(text)
        if target and target["to"] == "state" and field in fields:
            possible |= set(_state_values(field, fields[field]))
    if not possible:
        return False
    # A goal's condition, or a rule's: both come down to leaves saying what
    # something is or is not in.
    parts = C.from_goal(condition) if "type" in (condition or {}) else [condition]
    for part in parts:
        for leaf, _optional in C.leaves(part):
            wanted = {_slug(s) for s in listed(leaf.get("is"))} \
                | {_slug(s) for s in listed(leaf.get("lacks"))}
            if wanted & possible:
                return True
    return False


def may_find_out(actor, key, now=None):
    import time

    when = _reaching(actor)["found_out"].get(key)
    now = time.time() if now is None else now
    return when is None or now - float(when) >= FIND_OUT_EVERY


def note_found_out(actor, key, now=None):
    import time

    if not _goal_mark(actor):
        return
    held = _reaching(actor)
    held["found_out"][key] = time.time() if now is None else now
    setattr(actor.db, GOAL_ATTR, held)


def find_out_wait(actor, key, now=None):
    """Seconds until this character may make this call again for its goal."""
    import time

    when = _reaching(actor)["found_out"].get(key)
    if when is None:
        return 0.0
    now = time.time() if now is None else now
    return max(0.0, FIND_OUT_EVERY - (now - float(when)))


# ---------------------------------------------------------------------------
# What a world needs, and whether this server has it (§10)
# ---------------------------------------------------------------------------

def needed(rules):
    """
    {service: {tool: fingerprint}} for every call these rules name.

    Read off the rules every time it is asked, never stored, so it cannot
    drift from them: a world needs a service when a rule *names* one of its
    tools -- suspended rules included, since a suspended rule can be brought
    back -- not when something happens to call it. A rule that has not fired
    yet still depends on its service, and calls are history: two copies of a
    world would otherwise need different things. §10.1.

    The fingerprint is the one the rule was written against, which is what the
    world needs; a rule from before fingerprints takes the server's.
    """
    from world import services

    records = services.register()
    wanted = {}
    for rule in rules or []:
        try:
            effects = rule.get("effects") or []
        except AttributeError:
            continue
        for effect in calls_in(effects):
            service, tool = services.split_id(effect.get("tool"))
            if not service:
                continue
            printed = str(effect.get("fingerprint") or "")
            if not printed:
                _record, info = services.find(effect.get("tool"), records)
                printed = str((info or {}).get("fingerprint") or "")
            wanted.setdefault(service, {})[tool] = printed
    return {service: dict(sorted(tools.items()))
            for service, tools in sorted(wanted.items())}


def missing(wanted, records=None):
    """
    Everything this server lacks of what a world or a ruleset needs, as
    sentences. [] when it has all of it. §10.3.
    """
    from world import services

    records = services.register() if records is None else records
    said = []
    for service, tools in sorted((wanted or {}).items()):
        record = records.get(str(service))
        if record is None:
            said.append(f"it uses the service {service!r}, which this server "
                        f"does not have")
            continue
        for tool, printed in sorted(dict(tools or {}).items()):
            info = (record.get("tools") or {}).get(str(tool))
            named = services.tool_id(service, tool)
            if info is None:
                said.append(f"it uses {named!r}, which this server's "
                            f"{service!r} does not offer")
            elif printed and info.get("fingerprint") != printed:
                said.append(f"{named!r} here takes different arguments from "
                            f"the one it was built with")
            elif not info.get("on") or info.get("refused"):
                said.append(f"{named!r} is switched off on this server")
    return said


def shape_complaints(effect):
    """
    What is wrong with how a call is written, without asking the server.

    For a ruleset, which is read once when the server starts -- whether a
    service is here is asked when a world switches the ruleset on, since a
    service can be added at any time and the ruleset is not read again.
    """
    from world import services

    said = []
    service, tool = services.split_id(effect.get("tool"))
    if not service:
        said.append(f"{effect.get('tool')!r} is not a tool, as service.tool")
    for name, text in args_of(effect).items():
        if read_source(text) is None:
            said.append(f"where {name} comes from, {text!r}, does not read")
    for field, text in results_of(effect).items():
        if read_target(text) is None:
            said.append(f"where {field} goes, {text!r}, does not read")
    return said
