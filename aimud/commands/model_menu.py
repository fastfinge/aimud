"""
EvMenu nodes for configuring per-function AI model selections.

Storage layout on account.db.ai_models:
    {
        "default":    "openai/gpt-4o",
        "rooms":      "anthropic/claude-3-haiku-20240307",
        "items":      None,   # key absent or None → fall back to "default"
        ...
    }

The model list is fetched once per session from OpenRouter and cached on
account.ndb.openrouter_models_cache.  `models refresh` clears the cache.
"""

import json
import urllib.request

from twisted.internet import threads
from evennia.utils.evmenu import EvMenu

FUNCTIONS = [
    ("default",    "Default model when no function-specific model is set"),
    ("rooms",      "Room and exit generation"),
    ("items",      "Item creation"),
    ("npcs",       "NPC creation"),
    ("dialogue",   "NPC dialogue generation"),
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
    default = cfg.get("default")
    lines = []
    for func, _ in FUNCTIONS:
        val = cfg.get(func)
        if val:
            lines.append(f"  |w{func:<12}|n {val}")
        elif func == "default":
            lines.append(f"  |w{func:<12}|n |x(not set)|n")
        elif default:
            lines.append(f"  |w{func:<12}|n |x(using default: {default})|n")
        else:
            lines.append(f"  |w{func:<12}|n |x(not set)|n")
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
        return "node_main", {}
    return _set


def _make_clear_goto(function):
    def _clear(caller, raw_string):
        acct = _get_account(caller)
        cfg = acct.db.ai_models or {}
        cfg.pop(function, None)
        acct.db.ai_models = cfg
        caller.msg(f"|gCleared model override for {function}.|n")
        return "node_main", {}
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
    text = "|wConfigure AI Models|n\n\n" + _current_display(account) + "\n\nSelect a function to configure:"
    options = []
    for i, (func, desc) in enumerate(FUNCTIONS, 1):
        options.append({
            "key": str(i),
            "desc": f"{func} — {desc}",
            "goto": ("node_select_model", {"function": func, "page": 0, "search": ""}),
        })
    options.append({"key": ("q", "quit"), "desc": "Quit", "goto": "node_quit"})
    return text, options


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
        "desc": "Back to function list",
        "goto": "node_main",
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
