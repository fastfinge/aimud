"""
EvMenu nodes for configuring per-function AI model selections.

Two things are configured per job: which model answers, and how it is asked.

Storage layout on account.db.ai_models:
    {
        "default":    "openai/gpt-4o",
        "rooms":      "anthropic/claude-3-haiku-20240307",
        "items":      None,   # key absent or None → fall back to "default"
        ...
    }

and, alongside it, on account.db.ai_params:
    {
        "default":   {"temperature": 0.4},
        "dialogue":  {"temperature": 1.1, "presence_penalty": 0.4},
        ...
    }

A job's settings sit on top of "default"'s, and only what was actually set is
ever sent -- see world.model_params for why a value equal to the default is
not the same as leaving it out.

The model list is fetched once per session from OpenRouter and cached on
account.ndb.openrouter_models_cache.  `models refresh` clears the cache. Each
model record carries what it supports and what it defaults to, which is what
lets a job's screen offer exactly the settings that model will take.
"""

import json
import urllib.request

from twisted.internet import threads
from evennia.utils.evmenu import EvMenu

FUNCTIONS = [
    ("default",    "Default model when no function-specific model is set"),
    ("rooms",      "Room descriptions and world planning"),
    ("naming",     "Room names, types and exits (short, frequent calls)"),
    ("contents",   "Items and NPCs placed in a finished room"),
    ("items",      "Item creation"),
    ("npcs",       "NPC creation"),
    ("dialogue",   "NPC dialogue generation"),
    ("memory",     "Answering the remember command"),
    ("quests",     "Turning an NPC's request into a checkable quest"),
    ("validation", "Player input validation"),
    ("commands",   "Command and object behavior creation"),
]

MODELS_PER_PAGE = 10


# ---------------------------------------------------------------------------
# OpenRouter fetch
# ---------------------------------------------------------------------------

def _fetch_models_sync(api_key):
    """Runs in a thread; returns list of model dicts sorted by id."""
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return sorted(
            json.loads(resp.read().decode())["data"],
            key=lambda m: m["id"],
        )


def _get_account(caller):
    from evennia.accounts.accounts import DefaultAccount
    return caller if isinstance(caller, DefaultAccount) else caller.account


def start_model_menu(caller):
    """Entry point called by CmdModels.  Fetches model list if needed, then opens the menu."""
    account = _get_account(caller)
    try:
        api_key = account.get_openrouter_key()
    except ValueError as e:
        caller.msg(str(e))
        return

    if account.ndb.openrouter_models_cache is not None:
        _open_menu(account)
        return

    caller.msg("Fetching models from OpenRouter...")

    def on_success(models):
        account.ndb.openrouter_models_cache = models
        _open_menu(account)

    def on_error(failure):
        caller.msg(f"|rCould not fetch models: {failure.getErrorMessage()}|n")

    threads.deferToThread(_fetch_models_sync, api_key).addCallbacks(on_success, on_error)


def _open_menu(account):
    # The menu runs on the account, so EvMenu's own no_exits flag does not filter
    # out the puppeted character's exit cmdsets (priority 101).  Without a higher
    # priority here, single-letter options like "n" (next page) would be swallowed
    # by exit commands like "north".
    EvMenu(
        account,
        "commands.model_menu",
        startnode="node_main",
        cmd_on_exit=None,
        cmdset_priority=110,
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _current_display(account):
    cfg = account.db.ai_models or {}
    params = account.db.ai_params or {}
    default = cfg.get("default")
    lines = []
    for func, _ in FUNCTIONS:
        val = cfg.get(func)
        if val:
            shown = val
        elif func == "default" or not default:
            shown = "|x(not set)|n"
        else:
            shown = f"|x(using default: {default})|n"
        # Tuned settings belong on this screen too: a job behaving oddly is as
        # likely to be a temperature set weeks ago as it is to be the model,
        # and this is the first place anybody would look.
        tuned = len(params.get(func) or {})
        note = f"  |y+{tuned} setting{'s' if tuned != 1 else ''}|n" if tuned else ""
        lines.append(f"  |w{func:<12}|n {shown}{note}")
    return "\n".join(lines)


def _fmt_model(idx, model):
    ctx = model.get("context_length", 0)
    ctx_str = f"{ctx // 1000}k" if ctx >= 1000 else str(ctx)
    name = model.get("name", "")
    suffix = f"{name}, {ctx_str} ctx" if name and name != model["id"] else ctx_str
    return f"|w{idx:2}.|n {model['id']} |x({suffix})|n"


# ---------------------------------------------------------------------------
# goto factories (closures keep state out of ndb)
# ---------------------------------------------------------------------------

def _make_set_goto(function, model_id):
    def _set(caller, raw_string):
        acct = _get_account(caller)
        cfg = acct.db.ai_models or {}
        cfg[function] = model_id
        acct.db.ai_models = cfg
        caller.msg(f"|g{function} → {model_id}|n")
        # Back to the function's own screen rather than the list: the settings
        # a model offers depend on the model, so this is where the player wants
        # to look next.
        return "node_function", {"function": function}
    return _set


def _make_clear_goto(function):
    def _clear(caller, raw_string):
        acct = _get_account(caller)
        cfg = acct.db.ai_models or {}
        cfg.pop(function, None)
        acct.db.ai_models = cfg
        caller.msg(f"|gCleared model override for {function}.|n")
        return "node_function", {"function": function}
    return _clear


def _make_search_goto(function):
    def _search(caller, raw_string):
        term = raw_string.strip()
        return "node_select_model", {"function": function, "page": 0, "search": term}
    return _search


# ---------------------------------------------------------------------------
# EvMenu nodes
# ---------------------------------------------------------------------------

def node_main(caller, raw_string, **kwargs):
    account = _get_account(caller)
    text = ("|wConfigure AI Models|n\n\n" + _current_display(account)
            + "\n\nSelect a function to configure its model and settings:")
    options = []
    for i, (func, desc) in enumerate(FUNCTIONS, 1):
        options.append({
            "key": str(i),
            "desc": f"{func} — {desc}",
            "goto": ("node_function", {"function": func}),
        })
    options.append({"key": ("q", "quit"), "desc": "Quit", "goto": "node_quit"})
    return text, options


# ---------------------------------------------------------------------------
# One job: its model, and how that model is asked
# ---------------------------------------------------------------------------

def _model_record(account, model_id):
    """The cached OpenRouter entry for a model, or {}."""
    for record in (account.ndb.openrouter_models_cache or []):
        if record.get("id") == model_id:
            return record
    return {}


def _stored_params(account, function):
    return dict((account.db.ai_params or {}).get(function) or {})


def _save_param(account, function, key, value):
    """Set or unset one setting for one job."""
    everything = dict(account.db.ai_params or {})
    mine = dict(everything.get(function) or {})
    if value is None:
        mine.pop(key, None)
    else:
        mine[key] = value
    if mine:
        everything[function] = mine
    else:
        everything.pop(function, None)
    account.db.ai_params = everything


def _param_rows(account, function, model_id):
    """
    One line per setting this model takes: what it is, and where that came from.

    The point of showing the default rather than a blank is that a player
    cannot tune what they cannot see. "Temperature 1.0 (OpenRouter default)"
    tells them both what is happening now and what the dial is set to.
    """
    from world import model_params

    record = _model_record(account, model_id)
    mine = _stored_params(account, function)
    inherited = _stored_params(account, "default") if function != "default" else {}

    rows, params = [], model_params.supported_params(record)
    for i, param in enumerate(params, 1):
        if param.key in mine:
            value, source = mine[param.key], "|gyours|n"
        elif param.key in inherited:
            value, source = inherited[param.key], "|yfrom default|n"
        else:
            value, source = model_params.default_for(param, record)
            source = {"model": "|xmodel default|n",
                      "api": "|xOpenRouter default|n",
                      "unset": "|xunset|n"}[source]
        shown = model_params.show(value)
        rows.append(f"  |w{i:2}.|n {param.label:<20} {shown:<10} |x(|n{source}|x)|n")
    return rows, params


def _make_param_goto(function, key):
    def _goto(caller, raw_string):
        return "node_set_param", {"function": function, "param": key}
    return _goto


def _make_reset_goto(function):
    def _reset(caller, raw_string):
        account = _get_account(caller)
        everything = dict(account.db.ai_params or {})
        everything.pop(function, None)
        account.db.ai_params = everything
        caller.msg(f"|gEvery setting for {function} is back to its default.|n")
        return "node_function", {"function": function}
    return _reset


def node_function(caller, raw_string, **kwargs):
    """Everything about one job: which model answers, and how it is asked."""
    function = kwargs.get("function", "default")
    account = _get_account(caller)

    cfg = account.db.ai_models or {}
    chosen = cfg.get(function)
    fallback = cfg.get("default")
    if chosen:
        model_id = chosen
        model_note = "|yset for this function|n"
    elif function != "default" and fallback:
        model_id = fallback
        model_note = "|xfrom default|n"
    else:
        model_id = account.DEFAULT_MODEL
        model_note = "|xnothing set, so the game's own fallback|n"

    description = dict(FUNCTIONS).get(function, "")
    rows, params = _param_rows(account, function, model_id)

    header = [
        f"|wConfigure: {function}|n  |x{description}|n",
        "",
        f"  |wModel|n  {model_id}  |x(|n{model_note}|x)|n",
        "",
        "|wSettings|n — what is sent with every request for this function:",
    ]
    if not params:
        header.append("  |x(this model publishes no tunable settings)|n")

    footer = [
        "",
        "|xOnly settings you have changed yourself are sent; the rest are left|n",
        "|xout so the model or OpenRouter applies its own.|n",
    ]

    options = [{
        "key": ("m", "model"),
        "desc": f"Change the model ({model_id})",
        "goto": ("node_select_model",
                 {"function": function, "page": 0, "search": ""}),
    }]
    for i, param in enumerate(params, 1):
        options.append({
            "key": str(i),
            "desc": f"{param.label} — {param.note}",
            "goto": _make_param_goto(function, param.key),
        })
    if _stored_params(account, function):
        options.append({
            "key": ("r", "reset"),
            "desc": "Put every setting for this function back to its default",
            "goto": _make_reset_goto(function),
        })
    options.append({"key": ("b", "back"), "desc": "Back to the function list",
                    "goto": "node_main"})

    return "\n".join(header + rows + footer), options


def node_set_param(caller, raw_string, **kwargs):
    """Type a value for one setting, or clear it back to the default."""
    from world import model_params

    function = kwargs.get("function", "default")
    key = kwargs.get("param", "")
    param = model_params.PARAMS_BY_KEY.get(key)
    if param is None:
        return "node_function", {"function": function}

    account = _get_account(caller)
    cfg = account.db.ai_models or {}
    model_id = cfg.get(function) or cfg.get("default") or account.DEFAULT_MODEL
    record = _model_record(account, model_id)

    mine = _stored_params(account, function)
    default, source = model_params.default_for(param, record)
    origin = {"model": "this model's own default",
              "api": "OpenRouter's default",
              "unset": "left out entirely"}[source]

    lines = [
        f"|w{param.label}|n for |w{function}|n",
        "",
        f"  {param.note}",
    ]
    limits = model_params.range_note(param)
    if limits:
        lines.append(f"  |xAccepted range: {limits}.|n")
    lines.append("")
    if key in mine:
        lines.append(f"  Currently |g{model_params.show(mine[key])}|n, set by you.")
    else:
        lines.append(f"  Currently |x{model_params.show(default)}|n — {origin}.")
    lines.append("")
    lines.append("Type a value, or |wdefault|n to stop overriding it.")

    def _save(caller, raw, **kw):
        value, complaint = model_params.parse(param, raw)
        if complaint:
            caller.msg(f"|r{complaint}|n")
            return "node_set_param", {"function": function, "param": key}
        _save_param(_get_account(caller), function, key, value)
        if value is None:
            caller.msg(f"|g{param.label} for {function} is back to its default.|n")
        else:
            caller.msg(f"|g{param.label} for {function} → "
                       f"{model_params.show(value)}|n")
        return "node_function", {"function": function}

    return "\n".join(lines), [
        {"key": ("b", "back"), "desc": "Back without changing it",
         "goto": ("node_function", {"function": function})},
        {"key": "_default", "desc": f"Type a value for {param.label}",
         "goto": _save},
    ]


def node_select_model(caller, raw_string, **kwargs):
    function = kwargs.get("function", "default")
    page = kwargs.get("page", 0)
    search = kwargs.get("search", "").lower().strip()

    account = _get_account(caller)
    all_models = caller.ndb.openrouter_models_cache or []

    if search:
        models = [
            m for m in all_models
            if search in m["id"].lower() or search in m.get("name", "").lower()
        ]
    else:
        models = all_models

    total = len(models)
    total_pages = max(1, (total + MODELS_PER_PAGE - 1) // MODELS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * MODELS_PER_PAGE
    page_models = models[start : start + MODELS_PER_PAGE]

    cfg = account.db.ai_models or {}
    current = cfg.get(function)
    current_str = f"|y{current}|n" if current else "|x(not set)|n"

    header = [f"|wModels for: {function}|n  (currently {current_str})"]
    if search:
        header.append(
            f"Filter: |y{search}|n  ({total} match{'es' if total != 1 else ''}) "
            "— type new text to change, |wempty|n to clear"
        )
    else:
        header.append(
            f"Page {page + 1}/{total_pages}  ({total} models) "
            "— type text to filter"
        )
    header.append("")

    rows = [_fmt_model(i, m) for i, m in enumerate(page_models, 1)] or ["|rNo models match.|n"]

    options = []
    for i, model in enumerate(page_models, 1):
        options.append({
            "key": str(i),
            "desc": model["id"],
            "goto": _make_set_goto(function, model["id"]),
        })

    if page > 0:
        options.append({
            "key": ("p", "prev"),
            "desc": "Previous page",
            "goto": ("node_select_model", {"function": function, "page": page - 1, "search": search}),
        })
    if page < total_pages - 1:
        options.append({
            "key": ("n", "next"),
            "desc": "Next page",
            "goto": ("node_select_model", {"function": function, "page": page + 1, "search": search}),
        })
    if current:
        options.append({
            "key": ("c", "clear"),
            "desc": f"Clear override for {function}",
            "goto": _make_clear_goto(function),
        })
    options.append({
        "key": ("b", "back"),
        "desc": f"Back to {function}",
        "goto": ("node_function", {"function": function}),
    })
    options.append({
        "key": "_default",
        "desc": "Type text to filter models by name or ID",
        "goto": _make_search_goto(function),
    })

    return "\n".join(header + rows), options


def node_quit(caller, raw_string, **kwargs):
    caller.msg("Exiting model configuration.")
    return "", []
