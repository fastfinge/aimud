"""
Services, as a subject of the verbs: what the server owner lets the game reach.

  view services                         every service, and how its tools are classed
  view service <name>                   one, in full: every description, every shape
  create service                        add one (a form)
  create service <name> <kind> <where>  add one in a line: url, command or openapi
  edit service <name>                   change one (a form)
  edit service <name> <field> <value>   change one setting in a line
  edit service <name> tool <tool> <contained|looks|acts|on|off>
  edit service <name> refresh           connect again and relist its tools
  delete service <name> [yes]           forget it

Who: reading is everybody's -- players should be able to see what the game can
reach and what each tool does, because it is an open sandbox, and secrets are
masked. Adding or changing a service is an admin's; one that runs a command is
a developer's, because starting a process is running code and `py` already
needs that permission. See docs/archived/mcp-client.md §4.
"""

from commands.subjects import Subject, Use, answered, asking
from world import menus, services
from world.preferences import mask


def _caller(ctx):
    return ctx.character or ctx.caller


def _has_perm(caller, perm):
    try:
        return bool(caller.locks.check_lockstring(caller, f"dummy:perm({perm})"))
    except Exception:
        return False


def is_admin(caller):
    return _has_perm(caller, "Admin")


def may_run_kind(caller, kind):
    """Whether this caller may add or change a service of this kind."""
    return _has_perm(caller, services.permission_for(kind))


def admin(ctx):
    """For `Use.offered`: only for an admin."""
    return is_admin(_caller(ctx))


def _refuse_kind(caller, kind):
    if may_run_kind(caller, kind):
        return ""
    perm = services.permission_for(kind)
    if kind == services.COMMAND:
        return (f"Adding a service that runs a command needs {perm}, the "
                f"permission that already lets somebody run Python here: "
                f"starting a process is running code.")
    return f"Adding a service needs {perm}."


# ---------------------------------------------------------------------------
# Saying what a service is
# ---------------------------------------------------------------------------

def where(record):
    """Where a service is, with nothing secret in it."""
    kind = record.get("kind")
    if kind == services.COMMAND:
        line = " ".join([record.get("command") or "?"] + list(record.get("args") or []))
        env = record.get("env") or {}
        if env:
            line += f" (with {services.said_pairs(env)} set)"
        return line
    if kind == services.URL:
        return record.get("url") or "?"
    return record.get("spec") or "?"


def auth_line(record):
    auth = record.get("auth") or services.NO_AUTH
    if record.get("kind") == services.COMMAND:
        return "whatever its environment gives it"
    if auth == services.KEY_AUTH:
        place = record.get("key_place") or services.HEADER
        named = record.get("key_name") or ""
        how = {"header": f"in the header {named or 'X-API-Key'}",
               "query": f"as ?{named or 'api_key'}=",
               "bearer": "as a bearer token"}.get(place, place)
        return f"an API key, {how} ({mask(record.get('key')) or 'not set'})"
    if auth == services.OAUTH:
        held = (record.get("oauth") or {}).get("tokens")
        return "OAuth, " + ("authorised" if held else "not authorised yet")
    return "none"


def tool_line(name, info):
    state = "on" if info.get("on") else "off"
    if info.get("refused"):
        state = f"refused: {info['refused']}"
    decided = "" if info.get("decided") else " (guessed)"
    return f"{name} -- {services.said_level(info.get('level'))}{decided}, {state}"


def summary(record):
    tools = record.get("tools") or {}
    lines = [f"|w{record['name']}|n -- {services.said_kind(record.get('kind'))}",
             f"  at {where(record)}"]
    if record.get("status"):
        lines.append(f"  |rCould not be reached:|n {record['status']}")
    on = [name for name, info in tools.items() if info.get("on")]
    lines.append(f"  {len(tools)} tools, {len(on)} on")
    for name, info in sorted(tools.items()):
        lines.append(f"    {tool_line(name, info)}")
    return "\n".join(lines)


def _schema_lines(info):
    lines = []
    for name, param, required in services.parameters(info.get("input")):
        kind = param.get("type") or ("one of " + ", ".join(
            str(v) for v in param.get("enum") or []))
        lines.append(f"      takes {name}: {kind}"
                     f"{'' if required else ' (optional)'}"
                     + (f" -- {param['description']}" if param.get("description") else ""))
    for name, why in services.left_out(info.get("input")):
        lines.append(f"      leaves out {name}, which no rule can give: {why}")
    for name, field in services.outputs(info.get("output")):
        kind = field.get("type") or ""
        if "enum" in field:
            kind = "one of " + ", ".join(str(v) for v in field["enum"])
        lines.append(f"      gives {name}: {kind}")
    if not info.get("output"):
        lines.append("      gives text")
    return lines


def detail(record, caller=None):
    """One service, in full: the owner should read what a tool will say."""
    lines = [summary(record).split("\n")[0],
             f"  at {where(record)}",
             f"  authorisation: {auth_line(record)}",
             f"  timeout: {record.get('timeout') or services.TIMEOUT} seconds"]
    headers = record.get("headers") or {}
    if headers:
        lines.append(f"  headers: {services.said_pairs(headers)}")
    if record.get("status"):
        lines.append(f"  |rCould not be reached:|n {record['status']}")
    for name, info in sorted((record.get("tools") or {}).items()):
        lines.append("")
        lines.append(f"  |w{tool_line(name, info)}|n")
        description = str(info.get("description") or "").strip()
        lines.append("    " + (description or "It says nothing about itself."))
        hints = info.get("annotations") or {}
        if hints:
            lines.append("    It says: " + ", ".join(
                f"{key}={value}" for key, value in sorted(hints.items())
                if key.endswith("Hint")))
        if info.get("method"):
            lines.append(f"    An HTTP {info['method']}.")
        lines += _schema_lines(info)
    recent = record.get("recent") or []
    if recent and caller is not None and is_admin(caller):
        lines.append("")
        lines.append("  |wRecent calls that acted outward|n")
        for entry in recent[-10:]:
            who = entry.get("actor") or "somebody"
            whose = " (a character)" if entry.get("is_character") else ""
            ok = "ok" if entry.get("ok") else f"failed: {entry.get('error')}"
            lines.append(f"    {entry.get('tool')} by {who}{whose} in "
                         f"{entry.get('world') or 'no world'}, paid for by "
                         f"{entry.get('payer') or 'nobody'}: {ok}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The form
# ---------------------------------------------------------------------------

def _kind(ctx):
    return str(ctx.draft.get("kind") or "")


def _creating(ctx):
    return not bool(ctx.data.get("existing"))


def _is(kind):
    return lambda ctx: _kind(ctx) == kind


def _not_command(ctx):
    return _kind(ctx) not in ("", services.COMMAND)


def _key_auth(ctx):
    return _not_command(ctx) and ctx.draft.get("auth") == services.KEY_AUTH


def _named_key(ctx):
    return _key_auth(ctx) and ctx.draft.get("key_place") != services.BEARER


def _command(field):
    return lambda ctx: (f"edit service {ctx.draft.get('name')} {field}"
                        if not _creating(ctx) else "")


def _read_name(ctx, text):
    name = str(text or "").strip().lower()
    complaint = services.name_complaint(name, services.register())
    return (None, complaint) if complaint else (name, "")


def _read_kind(ctx, text):
    value, complaint = KIND_FIELD.choose_value(ctx, text)
    if complaint:
        return None, complaint
    refused = _refuse_kind(_caller(ctx), value)
    return (None, refused) if refused else (value, "")


def _read_url(ctx, text):
    complaint = services.address_complaint(text)
    return (None, complaint) if complaint else (str(text).strip(), "")


def _read_args(ctx, text):
    value, complaint = services.read_args(text)
    return value, complaint


def _read_pairs(ctx, text):
    return services.read_pairs(text)


KIND_FIELD = menus.Field(
    "kind", "How it is reached", kind=menus.CHOICE, required=True,
    choices=lambda ctx: [menus.Choice(kind, said)
                         for kind, said, _perm in services.KINDS
                         if may_run_kind(_caller(ctx), kind)],
    parse=_read_kind, lock=_creating,
    help="A command is a process this server runs, and needs Developer. A "
         "web address or an OpenAPI spec needs Admin.")


def _keep(ctx):
    record = _save(ctx)
    caller = _caller(ctx)
    _connect(caller, record["name"])
    ctx.dirty = False
    return f"Saved {record['name']}. Connecting to list its tools..."


def _save(ctx):
    """Write the draft to the register, keeping what only listing writes."""
    draft = dict(ctx.draft)
    name = str(draft.get("name") or "").strip().lower()
    caller = _caller(ctx)
    if _creating(ctx):
        complaint = services.name_complaint(name, services.register())
        if complaint:
            raise menus.Refuse(complaint)
    kind = draft.get("kind")
    if kind not in services.KIND_NAMES:
        raise menus.Refuse("Say how it is reached.")
    refused = _refuse_kind(caller, kind)
    if refused:
        raise menus.Refuse(refused)
    if kind == services.COMMAND and not str(draft.get("command") or "").strip():
        raise menus.Refuse("Say what command to run.")
    if kind == services.URL:
        complaint = services.address_complaint(draft.get("url"))
        if complaint:
            raise menus.Refuse(complaint)
    if kind == services.OPENAPI and not str(draft.get("spec") or "").strip():
        raise menus.Refuse("Say where its spec is: a web address, or a file "
                           "in the game directory.")
    record = services.get(name) or services.blank(name, kind)
    for field in ("kind", "command", "args", "env", "url", "spec", "headers",
                  "auth", "key_place", "key_name", "key", "timeout"):
        if field in draft and draft[field] is not None:
            record[field] = draft[field]
    record["name"] = name
    services.put(record)
    return record


def _connect(caller, name):
    """Connect and list, and tell whoever asked how it went."""
    def done(record):
        if record is None:
            caller.msg(f"{name} is gone.")
            return
        if record.get("status"):
            caller.msg(f"|w{name}|n is saved, but could not be reached: "
                       f"{record['status']}. |wedit service {name} refresh|n "
                       f"tries again.")
            return
        caller.msg(summary(record) + "\n|xEach tool's level is a guess until "
                   f"you confirm it: |wedit service {name}|x, or "
                   f"|wview service {name}|x to read what each says.|n")

    services.refresh(name, on_done=done)


def _authorise(ctx):
    from world import service_auth

    return service_auth.begin(ctx.draft.get("name"), _caller(ctx))


def _refresh(ctx):
    _connect(_caller(ctx), ctx.draft.get("name"))
    return "Connecting again..."


SERVICE = menus.Form(
    key="service", title=lambda ctx: (
        "A new service" if _creating(ctx) else f"The service {ctx.draft.get('name')}"),
    guided=True,
    intro=lambda ctx: (
        "Something this game may reach outside itself for. Whatever it does "
        "out there, it does on behalf of a multiplayer game, with this "
        "server's credentials -- never a player's."
        if _creating(ctx) else summary(services.get(ctx.draft.get("name"))
                                       or ctx.draft)),
    items=lambda ctx: [
        menus.Field("name", "Its name", required=True, parse=_read_name,
                    lock=_creating,
                    help="One word. Worlds that use it name it by this."),
        KIND_FIELD,
        menus.Field("command", "The command to run", lock=_is(services.COMMAND),
                    required=True, command=_command("command"),
                    help="The program: python, node, uvx, a path."),
        menus.Field("args", "Its arguments", lock=_is(services.COMMAND),
                    parse=_read_args, command=_command("args"),
                    show=lambda ctx, value: " ".join(value or []) or "none",
                    help="Split the way a shell would; quote anything with "
                         "spaces in it."),
        menus.Field("env", "Environment variables", kind=menus.SECRET,
                    lock=_is(services.COMMAND), parse=_read_pairs,
                    command=_command("env"),
                    show=lambda ctx, value: services.said_pairs(value),
                    help="NAME=value, separated by semicolons. Where a key "
                         "for a command usually goes. Only the names are "
                         "ever shown."),
        menus.Field("url", "Its web address", lock=_is(services.URL),
                    required=True, parse=_read_url, command=_command("url"),
                    help="The MCP endpoint, starting with http:// or https://."),
        menus.Field("spec", "Where its spec is", lock=_is(services.OPENAPI),
                    required=True, command=_command("spec"),
                    help="A web address, or a JSON or YAML file in the game "
                         "directory. Every operation starts switched off; you "
                         "choose what the game may use."),
        menus.Field("headers", "Extra headers", kind=menus.SECRET,
                    lock=_not_command, parse=_read_pairs,
                    command=_command("headers"),
                    show=lambda ctx, value: services.said_pairs(value),
                    help="NAME=value, separated by semicolons. Only the names "
                         "are ever shown."),
        menus.Field("auth", "How it is authorised", kind=menus.CHOICE,
                    lock=_not_command, command=_command("auth"),
                    choices=lambda ctx: [menus.Choice(v, said)
                                         for v, said in services.AUTHS]),
        menus.Field("key_place", "Where the key goes", kind=menus.CHOICE,
                    lock=_key_auth, command=_command("keyplace"),
                    choices=lambda ctx: [menus.Choice(v, said)
                                         for v, said in services.KEY_PLACES]),
        menus.Field("key_name", "The header or parameter it goes in",
                    lock=_named_key, command=_command("keyname"),
                    help="X-API-Key, api_key, whatever the service asks for."),
        menus.Field("key", "The API key", kind=menus.SECRET, lock=_key_auth,
                    command=_command("key"),
                    show=lambda ctx, value: mask(value) or "not set",
                    help="This server's own key. Never a player's: whatever "
                         "the game does with it, it does as the game."),
        menus.Field("timeout", "Seconds a call may take", kind=menus.NUMBER,
                    minimum=1, maximum=600, command=_command("timeout")),
        menus.Submenu("tools", "Its tools, and what each does outside",
                      TOOLS, lock=lambda ctx: not _creating(ctx),
                      command=lambda ctx: f"edit service {ctx.draft.get('name')} tool",
                      help="Confirm or change what each tool does outside the "
                           "game, and switch off any the game should not use."),
        menus.Action("authorise", "Authorise it, as this server",
                     lambda ctx: _authorise(ctx),
                     lock=lambda ctx: not _creating(ctx)
                     and ctx.draft.get("auth") == services.OAUTH,
                     command=lambda ctx: f"edit service {ctx.draft.get('name')} authorise",
                     help="Gives you an address to open in a browser. What you "
                          "agree to there, you agree to for this whole server: "
                          "whatever the game does with it, it does as the game."),
        menus.Action("refresh", "Connect again and relist its tools", _refresh,
                     lock=lambda ctx: not _creating(ctx),
                     command=lambda ctx: f"edit service {ctx.draft.get('name')} refresh"),
        menus.Action("keep", "Save, and connect", _keep, after=menus.CLOSE),
    ],
)


# ---------------------------------------------------------------------------
# The tool list: where the owner classifies
# ---------------------------------------------------------------------------

def _service_of(ctx):
    return services.get(ctx.data.get("service") or ctx.draft.get("name")) or {}


def _tool_of(ctx):
    return (_service_of(ctx).get("tools") or {}).get(ctx.data.get("tool")) or {}


def _set_tool(ctx, **changes):
    record = services.get(ctx.data.get("service") or ctx.draft.get("name"))
    if record is None:
        raise menus.Refuse("That service is gone.")
    info = dict((record.get("tools") or {}).get(ctx.data.get("tool")) or {})
    if not info:
        raise menus.Refuse("That tool is gone.")
    if changes.get("on") and info.get("refused"):
        raise menus.Refuse(f"It cannot be switched on: {info['refused']}.")
    info.update(changes)
    info["decided"] = True
    record["tools"][ctx.data.get("tool")] = info
    services.put(record)
    return ""


def _tool_intro(ctx):
    info = _tool_of(ctx)
    lines = [str(info.get("description") or "It says nothing about itself.")]
    lines += [line.strip() for line in _schema_lines(info)]
    hints = info.get("annotations") or {}
    if hints:
        lines.append("It says about itself: " + ", ".join(
            f"{key}={value}" for key, value in sorted(hints.items())
            if key.endswith("Hint")))
    if info.get("refused"):
        lines.append(f"|rNo rule can use it:|n {info['refused']}.")
    lines.append("Its level is " + ("your answer." if info.get("decided")
                                    else "a guess until you confirm it."))
    return "\n".join(lines)


TOOL = menus.Form(
    key="service-tool", title=lambda ctx: f"{ctx.data.get('tool')}",
    intro=_tool_intro,
    items=[
        menus.Field(
            "level", "What it does outside the game", kind=menus.CHOICE,
            choices=lambda ctx: [menus.Choice(v, f"{said} -- {why}")
                                 for v, said, why in services.LEVELS],
            get=lambda ctx: _tool_of(ctx).get("level"),
            set=lambda ctx, value: _set_tool(ctx, level=value),
            command=lambda ctx: (f"edit service {ctx.data.get('service')} tool "
                                 f"{ctx.data.get('tool')}"),
            help="Contained and looks-outward tools are open to players "
                 "anywhere; acting outward needs somebody paying, as a model "
                 "call does. A character needs somebody paying at every "
                 "level."),
        menus.Field(
            "on", "May the game use it?", kind=menus.BOOLEAN,
            get=lambda ctx: bool(_tool_of(ctx).get("on")),
            set=lambda ctx, value: _set_tool(ctx, on=bool(value)),
            command=lambda ctx: (f"edit service {ctx.data.get('service')} tool "
                                 f"{ctx.data.get('tool')} on")),
    ],
)


def _tool_entries(ctx):
    record = _service_of(ctx)
    found = []
    for name, info in sorted((record.get("tools") or {}).items()):
        found.append(menus.Submenu(
            name, tool_line(name, info), TOOL,
            data={"service": record.get("name"), "tool": name},
            command=f"edit service {record.get('name')} tool {name}"))
    return found


TOOLS = menus.Form(
    key="service-tools", title="Its tools",
    intro=lambda ctx: (
        "What each tool does outside the game: contained (nothing leaves the "
        "machine), looks outward (a query goes out), or acts outward "
        "(something out there changes). The service's own hints filled in the "
        "first guess; yours is the answer."
        if (_service_of(ctx).get("tools")) else
        "No tools listed yet. Connect again to list them."),
    items=_tool_entries,
)


# ---------------------------------------------------------------------------
# The verbs
# ---------------------------------------------------------------------------

def view_run(cmd, ctx, words):
    caller = cmd.caller
    records = services.register()
    if words:
        record = records.get(words[0].lower())
        if record is None:
            caller.msg(f"There is no service called {words[0]}. "
                       f"|wview services|n lists them.")
            return
        caller.msg(detail(record, caller))
        return
    if not records:
        caller.msg("This server reaches nothing outside the game: no services "
                   "have been added. An admin adds one with |wcreate service|n.")
        return
    lines = [f"|w{len(records)} services|n this server may reach. "
             f"|wview service <name>|n says what each tool does in full."]
    for name in sorted(records):
        lines.append(summary(records[name]))
    caller.msg("\n".join(lines))


def _view_form():
    return menus.Form(
        key="services", title="Services", kind=menus.VIEW,
        intro=lambda ctx: "\n\n".join(
            summary(record) for _name, record in sorted(services.register().items()))
        or "No services have been added.",
        items=[])


def view_items(ctx):
    return [menus.Submenu("services", "What this server may reach outside",
                          _view_form(),
                          help="Services the server owner added, and what "
                               "each tool does outside the game.")]


#: The settings `edit service <name> <field> <value>` may change, as
#: {typed word: (field, reader)}.
def _typed_fields():
    return {
        "command": ("command", lambda text: (text.strip(), "")),
        "args": ("args", services.read_args),
        "env": ("env", services.read_pairs),
        "url": ("url", lambda text: (
            (None, services.address_complaint(text)) if services.address_complaint(text)
            else (text.strip(), ""))),
        "spec": ("spec", lambda text: (text.strip(), "")),
        "headers": ("headers", services.read_pairs),
        "auth": ("auth", lambda text: _one_of(text, [v for v, _s in services.AUTHS])),
        "keyplace": ("key_place",
                     lambda text: _one_of(text, [v for v, _s in services.KEY_PLACES])),
        "keyname": ("key_name", lambda text: (text.strip(), "")),
        "key": ("key", lambda text: (text.strip(), "")),
        "timeout": ("timeout", _read_timeout),
    }


def _one_of(text, allowed):
    said = str(text or "").strip().lower()
    if said in allowed:
        return said, ""
    return None, f"That is one of: {', '.join(allowed)}."


def _read_timeout(text):
    try:
        seconds = int(float(text))
    except (TypeError, ValueError):
        return None, "That has to be a number of seconds."
    if not 1 <= seconds <= 600:
        return None, "Between 1 and 600 seconds."
    return seconds, ""


def _edit_tool(caller, record, words):
    """`edit service <name> tool <tool> <level|on|off>`, in a line."""
    tools = record.get("tools") or {}
    if not words:
        caller.msg(summary(record))
        return
    tool = words[0]
    if tool not in tools:
        caller.msg(f"{record['name']} has no tool called {tool}.")
        return
    if len(words) < 2:
        caller.msg(f"{tool_line(tool, tools[tool])}. Say a level "
                   f"({', '.join(services.LEVEL_NAMES)}), on, or off.")
        return
    said = words[1].lower()
    info = dict(tools[tool])
    if said in services.LEVEL_NAMES:
        info["level"] = said
    elif said in ("on", "off"):
        if said == "on" and info.get("refused"):
            caller.msg(f"It cannot be switched on: {info['refused']}.")
            return
        info["on"] = said == "on"
    else:
        caller.msg(f"Say a level ({', '.join(services.LEVEL_NAMES)}), on, or off.")
        return
    info["decided"] = True
    record["tools"][tool] = info
    services.put(record)
    caller.msg(f"{tool_line(tool, info)}.")


def edit_run(cmd, ctx, words):
    caller = cmd.caller
    if not words:
        caller.msg("Which service? |wview services|n lists them.")
        return
    record = services.get(words[0])
    if record is None:
        caller.msg(f"There is no service called {words[0]}.")
        return
    refused = _refuse_kind(caller, record.get("kind"))
    if refused:
        caller.msg(refused.replace("Adding", "Changing"))
        return
    rest = words[1:]
    if not rest:
        draft = {field: record.get(field) for field in record
                 if field not in ("tools", "recent", "status", "oauth")}
        menus.open_menu(caller, SERVICE, session=cmd.session, draft=draft,
                        existing=True)
        return
    what = rest[0].lower()
    if what == "refresh":
        caller.msg(f"Connecting to {record['name']} again...")
        _connect(caller, record["name"])
        return
    if what == "tool":
        _edit_tool(caller, record, rest[1:])
        return
    if what == "authorise" or what == "authorize":
        from world import service_auth

        caller.msg(service_auth.begin(record["name"], caller))
        return
    fields = _typed_fields()
    if what not in fields:
        caller.msg(f"A service has no setting called {what}. It has: "
                   f"{', '.join(sorted(fields))}, and |wtool|n, |wrefresh|n.")
        return
    field, reader = fields[what]
    value, complaint = reader(" ".join(rest[1:]))
    if complaint:
        caller.msg(complaint)
        return
    record[field] = value
    services.put(record)
    shown = ("set" if field in ("key", "env", "headers") else value)
    caller.msg(f"{record['name']}: {what} is now {shown}. "
               f"|wedit service {record['name']} refresh|n connects with it.")


def edit_items(ctx):
    found = []
    for name in services.names():
        record = services.get(name)
        if not may_run_kind(_caller(ctx), record.get("kind")):
            continue
        draft = {field: record.get(field) for field in record
                 if field not in ("tools", "recent", "status", "oauth")}
        found.append(menus.Submenu(
            f"service-{name}", f"The service {name}", SERVICE,
            data={"existing": True}, draft=lambda ctx, d=draft: dict(d),
            command=f"edit service {name}"))
    return found


def create_run(cmd, ctx, words):
    caller = cmd.caller
    if not words:
        menus.open_menu(caller, SERVICE, session=cmd.session, draft={
            "auth": services.NO_AUTH, "key_place": services.HEADER,
            "timeout": services.TIMEOUT})
        return
    name = words[0].lower()
    complaint = services.name_complaint(name, services.register())
    if complaint:
        caller.msg(complaint)
        return
    if len(words) < 3:
        caller.msg("|wcreate service <name> <url|command|openapi> <where>|n -- "
                   "a web address, the command and its arguments, or where the "
                   "spec is. |wcreate service|n alone opens the form.")
        return
    kind = words[1].lower()
    if kind not in services.KIND_NAMES:
        caller.msg(f"How it is reached is one of: {', '.join(services.KIND_NAMES)}.")
        return
    refused = _refuse_kind(caller, kind)
    if refused:
        caller.msg(refused)
        return
    record = services.blank(name, kind)
    rest = " ".join(words[2:])
    if kind == services.URL:
        complaint = services.address_complaint(rest)
        if complaint:
            caller.msg(complaint)
            return
        record["url"] = rest.strip()
    elif kind == services.COMMAND:
        parts, complaint = services.read_args(rest)
        if complaint or not parts:
            caller.msg(complaint or "Say what command to run.")
            return
        record["command"], record["args"] = parts[0], parts[1:]
    else:
        record["spec"] = rest.strip()
    services.put(record)
    caller.msg(f"Added {name}. Connecting to list its tools...")
    _connect(caller, name)


def create_items(ctx):
    return [menus.Submenu("service", "A service this game may reach", SERVICE,
                          fresh_draft=True,
                          draft=lambda ctx: {"auth": services.NO_AUTH,
                                             "key_place": services.HEADER,
                                             "timeout": services.TIMEOUT},
                          command="create service")]


def delete_run(cmd, ctx, words):
    caller = cmd.caller
    words, already = answered(words)
    if not words:
        caller.msg("Which service? |wview services|n lists them.")
        return
    record = services.get(words[0])
    if record is None:
        caller.msg(f"There is no service called {words[0]}.")
        return
    refused = _refuse_kind(caller, record.get("kind"))
    if refused:
        caller.msg(refused.replace("Adding", "Removing"))
        return
    name = record["name"]

    def do():
        services.remove(name)
        caller.msg(f"Forgot {name}. A rule that calls one of its tools now "
                   f"says it cannot be reached; what its tools already did "
                   f"stays done.")

    asking(cmd, f"Forget the service {name}? Worlds whose rules call its "
                f"tools will stop being able to, and will not import on a "
                f"server without it.",
           "delete_service", f"delete service {name}", do, already)


def delete_items(ctx):
    return [menus.Action(f"service-{name}", f"The service {name}",
                         run=lambda c, n=name: (services.remove(n) and f"Forgot {n}.") or "",
                         confirm="delete_service",
                         question=f"Forget the service {name}?",
                         command=f"delete service {name}")
            for name in services.names()
            if may_run_kind(_caller(ctx), (services.get(name) or {}).get("kind"))]


SUBJECTS = [
    Subject(
        "services", ("services", "service"),
        uses={"view": Use(view_run, view_items),
              "edit": Use(edit_run, edit_items, offered=admin),
              "create": Use(create_run, create_items, offered=admin),
              "delete": Use(delete_run, delete_items, offered=admin)},
        help="What this server may reach outside the game: MCP servers and "
             "OpenAPI services the owner added, and what each tool does out "
             "there.",
    ),
]
