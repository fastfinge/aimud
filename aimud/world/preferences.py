"""
Settings: every preference a player or a world keeps, in one register.

Before this, each preference was a command of its own -- `busy`, `apikey`,
`models` -- with its own way of showing a value, its own words for "back to
the default", and nowhere that listed them all. Now each is a `menus.Field`
with a group and a scope, and the `settings` command, its menu, `help`, and
later `~` all read the same description. See docs/commands-and-settings.md §5.

**Three scopes.** A setting belongs to the *account* (the person, everywhere),
to the *character in this world* (who you are here), or to the *world* (how
it runs, for everyone in it). A group only appears where its scope makes
sense: "You in this world" inside a world, "This world" to its creator.

**Nothing is migrated.** Every setting reads and writes the attribute the old
command did -- `busy_interval`, `openrouter_api_key`, `ai_models` -- so an
account set up before this reads back exactly as it was. The new stores are
`confirmations`, which the menu engine reads, and `ai_fallbacks`, the model
each job falls back to when its own fails, which `Account.model_for` reads.

**The API URL lives beside the key.** A key only works with the provider that
issued it, so a world choosing its own URL would send its creator's key
somewhere it means nothing. See §5.1.

Named `preferences` rather than `settings` because this codebase imports
Django's `settings` in a great many places, and two modules of that name
would be a trap.
"""

from evennia.help.filehelp import FileHelpEntry

from world import menus as m

# ---------------------------------------------------------------------------
# Scopes and the jobs models are chosen for
# ---------------------------------------------------------------------------

ACCOUNT = "account"
CHARACTER_IN_WORLD = "character_in_world"
WORLD = "world"

#: Every job the game asks a *chat* model to do, in the order the models menu
#: lists them. Moved here from the old models menu, which was its only reader.
#:
#: There was a "validation" entry, for deciding whether a thing could be in a
#: room and whether it could be picked up. Those go to a decision model now
#: (`world.decisions`), which is pinned rather than chosen: its thresholds are
#: calibrated against one version, and there is no other model whose
#: probabilities would mean the same thing. Listing it here would offer a
#: choice that changed nothing, so it is not listed. The world's *rules* text
#: is still called validation and is still a thing a player writes -- that is
#: `lore.FACETS`, and it feeds what the decision model is told.
JOBS = [
    ("default", "Default model when no function-specific model is set"),
    ("rooms", "Room descriptions and world planning"),
    ("naming", "Room names, types and exits (short, frequent calls)"),
    ("contents", "Items and NPCs placed in a finished room"),
    ("items", "Item creation"),
    ("npcs", "NPC creation"),
    ("dialogue", "NPC dialogue generation"),
    ("memory", "Answering the remember command"),
    ("quests", "Turning an NPC's request into a checkable quest"),
    ("commands", "Command and object behavior creation"),
    ("menus", "Filling in a menu field for you, when you type ~"),
]
JOB_NAMES = dict(JOBS)

#: Where the model list is kept once fetched, for the length of a session.
MODELS_CACHE = "openrouter_models_cache"

#: Every confirmation, in the order the menu lists them: key, what it guards,
#: and why it asks. docs/commands-and-settings.md §8.
CONFIRMATIONS = [
    ("delete_world", "Deleting a world", "A deleted world cannot be brought back."),
    ("reset_world", "Resetting a world", "Every room is destroyed and built again."),
    ("world_always", "Putting a world into always mode",
     "Every character acts all the time, and each of them costs a model call."),
    ("spend", "Asking a model for something on purpose",
     "Things like judging suggestions cost money when you ask for them."),
    ("bulk_rules", "Changing many rules at once",
     "Suspending every dead rule touches a great many rules in one go."),
    ("reset_verb", "Resetting what a verb takes",
     "The world will be asked afresh what the verb means."),
    ("delete_tokens", "Deleting a word list",
     "Descriptions that use the list lose it."),
    ("sweep_memory", "Sweeping memory banks", "Deleted memories are gone for good."),
    ("download", "Large downloads", "Some downloads take a long time and a lot of space."),
    ("clear_apikey", "Removing your API key",
     "Nothing new can be generated until you set another."),
    ("reset_rounds", "Clearing round counts", "What was measured is discarded."),
    ("abandon_quest", "Abandoning a quest", "Whoever asked is told you gave up."),
    ("discard", "Leaving a form with unsaved changes", "What you entered is lost."),
    ("suggestion", "Using what a model filled in for you",
     "Shows what was written before it replaces anything."),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def world_root_of(ctx):
    """The world the character is standing in, or None."""
    room = getattr(ctx.character, "location", None)
    return getattr(room.db, "world_root", None) if room is not None else None


def owns_world(ctx):
    """Whether this account may change how the world it is in runs."""
    from world import sponsor

    root = world_root_of(ctx)
    account = ctx.account
    if root is None or account is None:
        return False
    return bool(account.is_superuser or sponsor.creator_of(root) == account)


def _has_account(ctx):
    return ctx.account is not None


def _default_mark(stored):
    return " (the default)" if stored is None else ""


def mask(key):
    """Only the first and last four characters of an API key."""
    key = str(key or "")
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + ("*" * (len(key) - 8)) + key[-4:]


# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------

def _busy_show(ctx, stored):
    from world import busy

    seconds = busy.DEFAULT_INTERVAL if stored is None else int(stored)
    said = "never" if seconds == 0 else f"every {seconds} seconds"
    return said + _default_mark(stored)


def _busy_set(ctx, seconds):
    from world import busy

    busy.set_interval(ctx.account, seconds)
    if seconds is None:
        return f"Back to the default: every {busy.DEFAULT_INTERVAL} seconds."
    if seconds == 0:
        return "You will not be told when a model is still working."
    return f"You will be told every {seconds} seconds."


def _busy_get(ctx):
    from world import busy

    return busy.chosen(ctx.account)


def _busy_parse(ctx, text):
    from world import busy

    return busy.parse_interval(text)


BUSY = m.Field(
    "busy", "Still-working notices",
    get=_busy_get, set=_busy_set, parse=_busy_parse,
    show=_busy_show,
    prompt="Type a number of seconds from 5 to 120, off, or default",
    help=("Some of what you do has to wait for a model: a verb this world has "
          "never seen, a room being built behind a door. Every so often you "
          "are told it is still going, and what it is doing, so a long wait "
          "does not look like the game has stopped. This is how often, or "
          "off. It follows you into every character and every world."),
)

VIEW_MODE_CHOICES = [
    m.Choice(m.WALK_AWAY, "Close when I type something else",
             keys=("walk_away", "walk")),
    m.Choice(m.CLOSE_VIEW, "Never open, show the commands instead",
             keys=("close", "never")),
    m.Choice(m.STAY_OPEN, "Stay open until I quit", keys=("stay",)),
]


def _attribute_setting(key, label, attr, default, help, kind, choices=None,
                       said=None, confirm=None):
    """A setting kept in one account attribute, where unset means default."""

    def get(ctx):
        return ctx.account.attributes.get(attr)

    def put(ctx, value):
        if value is None or value == default:
            ctx.account.attributes.remove(attr)
        else:
            ctx.account.attributes.add(attr, value)
        return said(ctx, value) if said else None

    def show(ctx, stored):
        value = default if stored is None else stored
        if kind == m.BOOLEAN:
            text = "on" if value else "off"
        else:
            text = next((choice.label for choice in (choices or [])
                         if choice.value == value), str(value))
        return text + _default_mark(stored)

    return m.Field(key, label, kind=kind, get=get, set=put, show=show,
                   choices=choices, help=help, confirm=confirm)


VIEW_MENUS = _attribute_setting(
    "viewmenus", "Menus that only show you something", m.VIEW_MODE_ATTR,
    m.WALK_AWAY, kind=m.CHOICE, choices=VIEW_MODE_CHOICES,
    help=("Commands like score show what they are for straight away and then "
          "offer choices. Close when I type something else lets the next "
          "command you type just happen. Never open shows the commands "
          "to type instead of a menu. Stay open keeps the menu until you "
          "type q, for browsing a long list."),
    said=lambda ctx, value: "Menus that only show you something will now "
    + {m.WALK_AWAY: "close when you type something else.",
       m.CLOSE_VIEW: "never open.",
       m.STAY_OPEN: "stay open until you quit."}[value or m.WALK_AWAY],
)

def _page_size_parse(ctx, text):
    said = text.strip().lower()
    if said in ("default", "clear", "reset"):
        return None, ""
    if said in ("all", "unlimited", "none", "off"):
        return 0, ""
    try:
        size = int(said)
    except ValueError:
        return None, "Give a number of choices, or 0 for all of them at once."
    if size < 0:
        return None, "That has to be 0 or more."
    return size, ""


def _page_size_set(ctx, size):
    if size is None or size == m.PAGE_SIZE:
        ctx.account.attributes.remove(m.PAGE_SIZE_ATTR)
    else:
        ctx.account.attributes.add(m.PAGE_SIZE_ATTR, size)
    if size == 0:
        return "Menus will show every choice at once."
    return (f"Menus will show {size if size is not None else m.PAGE_SIZE} "
            f"choices at a time.")


def _page_size_show(ctx, stored):
    size = m.PAGE_SIZE if stored is None else stored
    shown = "all at once" if size == 0 else f"{size} at a time"
    return shown + _default_mark(stored)


PAGE_SIZE = m.Field(
    "pagesize", "Choices per page",
    get=lambda ctx: ctx.account.attributes.get(m.PAGE_SIZE_ATTR),
    set=_page_size_set, parse=_page_size_parse, show=_page_size_show,
    prompt="Type how many choices to show at a time, 0 for all of them, or "
           "default",
    help=("How many choices every menu shows before the rest go on another "
          "page, which n and p turn. 0 shows every choice at once, however "
          "long the list, which suits reading with a screen reader or a "
          "client that scrolls back. A long list can be narrowed by typing "
          "either way."),
)


SHOW_COMMANDS = _attribute_setting(
    "showcommands", "Say what to type next time", m.SHOW_COMMAND_ATTR, True,
    kind=m.BOOLEAN,
    help=("When you finish something through a menu, you are told the command "
          "that would have done it in one line."),
    said=lambda ctx, value: ("You will be told what to type next time."
                             if value is None or value
                             else "You will not be told what to type."),
)

GENERAL = m.Form(
    key="general", title="General",
    items=[BUSY, VIEW_MENUS, PAGE_SIZE, SHOW_COMMANDS],
)


# ---------------------------------------------------------------------------
# Confirmations
# ---------------------------------------------------------------------------

def _confirmation_field(key, label, why):
    def get(ctx):
        return (ctx.account.attributes.get(m.CONFIRMATIONS_ATTR) or {}).get(key)

    def put(ctx, value):
        stored = dict(ctx.account.attributes.get(m.CONFIRMATIONS_ATTR) or {})
        if value is None or value:
            stored.pop(key, None)
        else:
            stored[key] = False
        ctx.account.attributes.add(m.CONFIRMATIONS_ATTR, stored)
        on = value is None or value
        return (f"You will be asked before {label[0].lower() + label[1:]}."
                if on else
                f"You will not be asked before {label[0].lower() + label[1:]}.")

    def show(ctx, stored):
        return ("on" if stored is None or stored else "off") \
            + _default_mark(stored)

    return m.Field(key, label, kind=m.BOOLEAN, get=get, set=put, show=show,
                   help=f"{why} On asks yes or no first; off just does it.")


def _all_confirmations(on):
    def run(ctx):
        if on:
            ctx.account.attributes.remove(m.CONFIRMATIONS_ATTR)
            return "Every confirmation is on."
        ctx.account.attributes.add(m.CONFIRMATIONS_ATTR,
                                   {key: False for key, _, _ in CONFIRMATIONS})
        return "Every confirmation is off. Nothing will ask before it acts."
    return run


CONFIRMATIONS_FORM = m.Form(
    key="confirmations", title="Confirmations",
    intro="Whether you are asked yes or no before each of these. All are on "
          "until you turn them off.",
    items=[
        *(_confirmation_field(key, label, why)
          for key, label, why in CONFIRMATIONS),
        m.Action("allon", "Turn every confirmation on",
                 run=_all_confirmations(True)),
        m.Action("alloff", "Turn every confirmation off",
                 run=_all_confirmations(False)),
    ],
)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _key_set(ctx, value):
    if value is None:
        ctx.account.attributes.remove("openrouter_api_key")
        return "Your API key is removed."
    ctx.account.attributes.add("openrouter_api_key", value)
    return "Your API key is saved."


def _key_confirm(ctx, value):
    if value is None and ctx.account.attributes.get("openrouter_api_key"):
        return ("clear_apikey", "Remove your API key? Nothing new can be "
                                "generated until you set another.")
    return None


API_KEY = m.Field(
    "apikey", "API key", kind=m.SECRET,
    get=lambda ctx: ctx.account.attributes.get("openrouter_api_key"),
    set=_key_set, confirm=_key_confirm,
    show=lambda ctx, value: mask(value) if value else "not set",
    help=("The key your model calls are paid with. It is kept on your account, "
          "and other players cannot see or use it. What you type is sent as "
          "plain text, so connect securely and do not share your session."),
)


def _url_parse(ctx, text):
    said = text.strip()
    if said.lower() in ("default", "clear", "reset"):
        return None, ""
    if not said.lower().startswith(("http://", "https://")):
        return None, "An address starts with https:// or http://."
    return said.rstrip("/"), ""


def _url_set(ctx, value):
    account = ctx.account
    if value is None:
        account.attributes.remove("api_base_url")
    else:
        account.attributes.add("api_base_url", value)
    # The list belongs to the provider it came from.
    setattr(account.ndb, MODELS_CACHE, None)
    where = value or _default_url()
    said = f"Models will be asked for at {where}."
    if account.attributes.get("openrouter_api_key"):
        said += (" Your API key was set for the old address; if this provider "
                 "gives out its own keys, set that too with |wsettings "
                 "apikey|n.")
    return said


def _default_url():
    from world import llm

    return llm.BASE_URL


API_URL = m.Field(
    "apiurl", "API address",
    get=lambda ctx: ctx.account.attributes.get("api_base_url"),
    set=_url_set, parse=_url_parse,
    show=lambda ctx, value: value or f"{_default_url()} (the default)",
    prompt="Type the provider's address, or default",
    help=("Where model calls are sent. Any provider that speaks the same "
          "protocol as OpenRouter works. It sits beside your API key because "
          "a key only works with the provider that gave it out. Changing it "
          "fetches the list of models again."),
)

API = m.Form(key="api", title="API key and address", items=[API_KEY, API_URL])


# ---------------------------------------------------------------------------
# Models: one form per job
# ---------------------------------------------------------------------------

def cached_models(account):
    return getattr(account.ndb, MODELS_CACHE, None)


def _model_record(account, model_id):
    for record in (cached_models(account) or []):
        if record.get("id") == model_id:
            return record
    return {}


def _stored_params(account, job):
    return dict((account.attributes.get("ai_params") or {}).get(job) or {})


def _save_param(account, job, key, value):
    everything = dict(account.attributes.get("ai_params") or {})
    mine = dict(everything.get(job) or {})
    if value is None:
        mine.pop(key, None)
    else:
        mine[key] = value
    if mine:
        everything[job] = mine
    else:
        everything.pop(job, None)
    account.attributes.add("ai_params", everything)


def _chosen_model(account, job):
    """(model id, where it came from) for a job."""
    cfg = account.attributes.get("ai_models") or {}
    if cfg.get(job):
        return cfg[job], ""
    if job != "default" and cfg.get("default"):
        return cfg["default"], "the same as default"
    return account.DEFAULT_MODEL, "the game's fallback"


def _params_in_force(account, job, model_id):
    """(every setting to list, those listed only because somebody set them)."""
    from world import model_params

    record = _model_record(account, model_id)
    mine = _stored_params(account, job)
    inherited = _stored_params(account, "default") if job != "default" else {}
    offered = model_params.supported_params(record)
    offered_keys = {param.key for param in offered}
    in_force = set(mine) | set(inherited)
    unsupported = [param for param in model_params.PARAMS
                   if param.key in in_force and param.key not in offered_keys]
    return offered + unsupported, unsupported


def fetch_models(ctx, on_done, on_fail):
    """
    Fetch the model list for this account, then call `on_done()`.

    `on_fail(text)` is told why when it cannot be fetched -- most often,
    because there is no key to ask with.
    """
    from world import busy, llm, sponsor

    account = ctx.account
    payer = sponsor.of_account(account)
    try:
        payer.key()
    except ValueError:
        # Said here rather than taken from the sponsor, which words it for
        # whoever is standing in a world. This is always your own key.
        return on_fail("You have no API key set, so there is no list of "
                       "models to fetch. Use |wsettings apikey <key>|n to "
                       "add one.")

    teller = account or ctx.caller
    teller.msg("Fetching the list of models...")

    def fetched(models):
        setattr(account.ndb, MODELS_CACHE, models)
        on_done()

    def failed(failure):
        on_fail(f"|rCould not fetch models: {failure.getErrorMessage()}|n")

    wait = busy.start(teller, "fetching the list of models")
    llm.fetch(llm.models, payer, on_success=busy.closing(wait, fetched),
              on_error=busy.closing(wait, failed))


def _models_ready(ctx, proceed, fail):
    if cached_models(ctx.account) is not None:
        return proceed()
    return fetch_models(ctx, proceed, fail)


def _model_choices(ctx):
    from world import model_params

    listed = cached_models(ctx.account) or []
    choices = []
    for record in listed:
        if not model_params.supports_tools(record):
            continue
        size = record.get("context_length", 0) or 0
        size = f"{size // 1000}k context" if size >= 1000 else f"{size} context"
        name = record.get("name", "")
        about = f"{name}, {size}" if name and name != record["id"] else size
        choices.append(m.Choice(record["id"], f"{record['id']} ({about})",
                                keys=(record["id"].lower(),)))
    return choices


def _model_prompt(ctx):
    from world import model_params

    listed = cached_models(ctx.account) or []
    hidden = sum(1 for record in listed
                 if not model_params.supports_tools(record))
    if not hidden:
        return ""
    return (f"{hidden} {'model that cannot use tools is' if hidden == 1 else 'models that cannot use tools are'} "
            f"not listed.")


def _model_set(ctx, value):
    account, job = ctx.account, ctx.job
    cfg = dict(account.attributes.get("ai_models") or {})
    if value is None:
        cfg.pop(job, None)
        said = f"Cleared the model for {job}."
    else:
        cfg[job] = value
        said = f"{job} now uses {value}."
    account.attributes.add("ai_models", cfg)
    return said


def _model_show(ctx, value):
    model_id, source = _chosen_model(ctx.account, ctx.job)
    return value if value else f"{model_id}, {source}"


MODEL = m.Field(
    "model", "Model", kind=m.CHOICE, choices=_model_choices,
    get=lambda ctx: (ctx.account.attributes.get("ai_models") or {}).get(ctx.job),
    set=_model_set, show=_model_show, prompt=_model_prompt,
    help=("Which model answers for this job. Only models that can use tools "
          "are listed, because every job hands the model tools to look things "
          "up and to give its answer."),
)


def _fallback_set(ctx, value):
    account, job = ctx.account, ctx.job
    cfg = dict(account.attributes.get("ai_fallbacks") or {})
    if value is None:
        cfg.pop(job, None)
        said = f"{job} has no fallback of its own now."
    else:
        cfg[job] = value
        said = f"When {job}'s model fails, {value} is asked instead."
    if cfg:
        account.attributes.add("ai_fallbacks", cfg)
    else:
        account.attributes.remove("ai_fallbacks")
    return said


def _fallback_show(ctx, value):
    if value:
        return value
    inherited = (ctx.account.attributes.get("ai_fallbacks") or {}).get("default")
    if ctx.job != "default" and inherited:
        return f"{inherited}, the same as default"
    return "none"


FALLBACK = m.Field(
    "fallback", "Fallback model", kind=m.CHOICE, choices=_model_choices,
    get=lambda ctx: (ctx.account.attributes.get("ai_fallbacks") or {}).get(ctx.job),
    set=_fallback_set, show=_fallback_show,
    help=("Asked instead when this job's model fails: the provider refuses, "
          "errors or times out. The same request goes to the fallback before "
          "anybody is told, and it does not use up one of the job's rounds. "
          "A fast, cheap model that sometimes refuses, with a steadier one "
          "behind it, is what this is for. Set on default, it covers every "
          "job without one of its own."),
)


def _param_field(param):
    from world import model_params

    def get(ctx):
        return _stored_params(ctx.account, ctx.job).get(param.key)

    def put(ctx, value):
        _save_param(ctx.account, ctx.job, param.key, value)
        if value is None:
            return f"{param.label} for {ctx.job} is back to its default."
        return f"{param.label} for {ctx.job} is now {model_params.show(value)}."

    def show(ctx, value):
        account, job = ctx.account, ctx.job
        model_id, _source = _chosen_model(account, job)
        record = _model_record(account, model_id)
        inherited = (_stored_params(account, "default")
                     if job != "default" else {})
        if value is not None:
            said, source = value, "yours"
        elif param.key in inherited:
            said, source = inherited[param.key], "from default"
        else:
            said, origin = model_params.default_for(param, record)
            source = {"model": "model default", "api": "provider default",
                      "unset": "left out"}[origin]
        text = f"{model_params.show(said)} ({source}"
        if not model_params.supported(param, record):
            text += ", not offered by this model"
        return text + ")"

    def helped(ctx):
        lines = [param.note]
        limits = model_params.range_note(param)
        if limits:
            lines.append(f"Accepted range: {limits}.")
        lines.append("Only settings you change are sent. Type default to stop "
                     "overriding it.")
        return " ".join(lines)

    return m.Field(param.key, param.label, get=get, set=put, show=show,
                   help=helped,
                   parse=lambda ctx, text: _param_parse(param, text),
                   prompt=f"Type a value for {param.label}, or default")


def _param_parse(param, text):
    from world import model_params

    value, complaint = model_params.parse(param, text)
    return value, complaint or ""


def _drop_unsupported(ctx):
    account, job = ctx.account, ctx.job
    model_id, _ = _chosen_model(account, job)
    _all, unsupported = _params_in_force(account, job, model_id)
    mine = _stored_params(account, job)
    dropped = [param.key for param in unsupported if param.key in mine]
    for key in dropped:
        _save_param(account, job, key, None)
    return (f"Cleared {len(dropped)} setting{'s' if len(dropped) != 1 else ''} "
            f"for {job} that this model does not list.")


def _reset_job(ctx):
    everything = dict(ctx.account.attributes.get("ai_params") or {})
    everything.pop(ctx.job, None)
    ctx.account.attributes.add("ai_params", everything)
    return f"Every setting for {ctx.job} is back to its default."


def _job_items(ctx):
    account, job = ctx.account, ctx.job
    model_id, _ = _chosen_model(account, job)
    params, unsupported = _params_in_force(account, job, model_id)
    items = [MODEL, FALLBACK] + [_param_field(param) for param in params]
    mine = _stored_params(account, job)
    if any(param.key in mine for param in unsupported):
        items.append(m.Action("drop", "Clear the settings this model does not "
                                      "list", run=_drop_unsupported))
    if mine:
        items.append(m.Action("reset", "Put every setting for this job back "
                                       "to its default", run=_reset_job))
    return items


def _job_intro(ctx):
    account, job = ctx.account, ctx.job
    model_id, _ = _chosen_model(account, job)
    _params, unsupported = _params_in_force(account, job, model_id)
    lines = [JOB_NAMES.get(job, ""),
             "Only settings you have changed yourself are sent; the rest are "
             "left out so the model or provider applies its own."]
    if unsupported:
        count = len(unsupported)
        lines.append(f"{count} setting{'s are' if count != 1 else ' is'} set "
                     f"but not listed by this model. Most providers ignore "
                     f"what they do not use.")
    return "\n".join(lines)


JOB = m.Form(key="job", title=lambda ctx: f"Models: {ctx.job}",
             intro=_job_intro, items=_job_items)


def _job_label(job):
    def label(ctx):
        model_id, source = _chosen_model(ctx.account, job)
        shown = f"{model_id}, {source}" if source else model_id
        tuned = len(_stored_params(ctx.account, job))
        extra = f", {tuned} setting{'s' if tuned != 1 else ''} changed" if tuned else ""
        return f"{job}: {shown}{extra}"
    return label


def _refresh_models(ctx):
    setattr(ctx.account.ndb, MODELS_CACHE, None)
    fetch_models(ctx, lambda: ctx.account.msg(
        f"Fetched {len(cached_models(ctx.account) or [])} models."),
        ctx.account.msg)
    return None


MODELS = m.Form(
    key="models", title="Models",
    intro=("Which model answers for each job the game asks a model to do, and "
           "how it is asked. Dialogue is usually better loose and surprising; "
           "the rules that decide what an action does want to be steady."),
    items=[
        *(m.Submenu(job, _job_label(job), JOB, data={"job": job}, help=about)
          for job, about in JOBS),
        m.Action("refresh", "Fetch the list of models again",
                 run=_refresh_models),
    ],
)


# ---------------------------------------------------------------------------
# You in this world
# ---------------------------------------------------------------------------

def _name_set(ctx, value):
    from commands.name_cmds import announce
    from world import lore

    character, root = ctx.character, world_root_of(ctx)
    current = character.world_name(root)
    previous = current or character.key
    character.set_world_name(root, value)
    now = value or character.key
    announce(character, previous, now)
    if value is None:
        return f"You go back to being |w{character.key}|n here."
    return f"In |w{lore.title(root)}|n you are now |w{value}|n."


def _name_parse(ctx, text):
    from commands.name_cmds import problem

    said = problem(ctx.character, text.strip())
    return (None, said) if said else (text.strip(), "")


NAME = m.Field(
    "name", "Your name here",
    get=lambda ctx: ctx.character.world_name(world_root_of(ctx)),
    set=_name_set, parse=_name_parse,
    show=lambda ctx, value: value or f"{ctx.character.key}, your account name",
    help=("What characters in this world call you. Each world remembers you "
          "separately. Changing it is announced to whoever is in the room."),
)


def _looks_get(ctx):
    root = world_root_of(ctx)
    return (ctx.character.db.world_descs or {}).get(str(root.id))


def _looks_set(ctx, value):
    ctx.character.set_world_desc(world_root_of(ctx), value or "")
    return ("Your looks here are cleared." if not value
            else "Your looks here are saved.")


LOOKS = m.Field(
    "looks", "How you look here", kind=m.LONG_TEXT, suggestible=True,
    get=_looks_get, set=_looks_set,
    help="What other characters see when they look at you in this world.",
)


def _pronoun_choices(ctx):
    from world import pronouns

    root = world_root_of(ctx)
    return [m.Choice(slug, f"{pronouns.spelled(entry)}: {entry.get('means', '')}",
                     keys=(slug,))
            for slug, entry in sorted(pronouns.vocabulary(root).items())]


def _pronouns_set(ctx, slug):
    from world import pronouns

    root = world_root_of(ctx)
    given = pronouns.give(ctx.character, slug, root)
    if not given:
        raise m.Refuse(f"This world keeps no pronoun set called {slug}.")
    return (f"People here will call you "
            f"|w{pronouns.spelled(pronouns.get(root, given))}|n.")


def _pronouns_get(ctx):
    from world import pronouns

    return pronouns.of(ctx.character, world_root_of(ctx)).get("subject")


def _pronouns_show(ctx, value):
    from world import pronouns

    return pronouns.spelled(pronouns.of(ctx.character, world_root_of(ctx)))


PRONOUNS = m.Field(
    "pronouns", "Your pronouns", kind=m.CHOICE, required=True,
    choices=_pronoun_choices, get=_pronouns_get, set=_pronouns_set,
    show=_pronouns_show,
    help=("What people use when they talk about you. Each world keeps its own "
          "sets, and anybody here can use a set once it exists."),
)


def _you_here_items(ctx):
    from commands.pronoun_cmds import NEW_SET

    return [NAME, LOOKS, PRONOUNS,
            m.Submenu("newpronouns", "Add a pronoun set this world does not "
                                     "have", NEW_SET, fresh_draft=True,
                      data=lambda ctx: {"world_root": world_root_of(ctx)},
                      help="Walks through the five forms and the verb after "
                           "them. The new set is then there for everybody.")]


def _world_title(ctx):
    from world import lore

    return lore.title(world_root_of(ctx))


def _you_here_context(ctx):
    root = world_root_of(ctx)
    return (f"The world is {_world_title(ctx)}: "
            f"{(root.db.world_description or '').strip()}")


def _you_here_sponsor(ctx):
    from world import sponsor

    return sponsor.of(ctx.character)


YOU_HERE = m.Form(
    key="you", title=lambda ctx: f"You in {_world_title(ctx)}",
    items=_you_here_items, sponsor=_you_here_sponsor,
    context=_you_here_context,
)


# ---------------------------------------------------------------------------
# This world
# ---------------------------------------------------------------------------

MODE_CHOICES = [
    m.Choice("normal", "normal, where characters act while somebody is with them",
             keys=("normal",)),
    m.Choice("always", "always, where every character acts all the time",
             keys=("always",)),
]


def _mode_set(ctx, wanted):
    from world import activity, lore

    root = world_root_of(ctx)
    name = lore.title(root)
    activity.set_mode(root, wanted)
    if wanted == activity.ALWAYS:
        return (f"|w{name}|n is now running |walways|n. Everybody in it acts "
                f"from now on, wherever you are and whether or not you are "
                f"typing. It costs a model call every time any of them does, "
                f"so put it back to |wnormal|n when you have seen enough -- "
                f"and it does that itself when you log out.")
    return (f"|w{name}|n is back to |wnormal|n. Characters you have just been "
            f"with stay live for a few more minutes, and then the world goes "
            f"quiet until you are watching it again.")


def _mode_get(ctx):
    from world import activity

    return activity.mode(world_root_of(ctx))


def _mode_confirm(ctx, wanted):
    from world import activity

    if wanted == activity.ALWAYS and activity.mode(world_root_of(ctx)) != wanted:
        return ("world_always",
                "Run this world always? Every character in it acts all the "
                "time, and each of them costs a model call, until you put it "
                "back or log out.")
    return None


MODE = m.Field(
    "mode", "How the world runs", kind=m.CHOICE, required=True,
    choices=MODE_CHOICES,
    get=_mode_get,
    set=_mode_set, confirm=_mode_confirm,
    help=("normal is careful with your money: characters act while somebody is "
          "in the room with them, and the world goes still when nobody is "
          "typing. always has every character act on every turn, watched or "
          "not, which is for watching a world run and costs a model call each "
          "time any of them acts. Every world goes back to normal when the "
          "last player logs out."),
)

THIS_WORLD = m.Form(key="world", title=_world_title, items=[MODE])


# ---------------------------------------------------------------------------
# The whole register
# ---------------------------------------------------------------------------

#: (key, label, scope, form, help, visible). The order is the menu's.
GROUPS = [
    ("general", "General", ACCOUNT, GENERAL,
     "How the game talks to you: still-working notices and menus.",
     _has_account),
    ("confirmations", "Confirmations", ACCOUNT, CONFIRMATIONS_FORM,
     "Whether you are asked yes or no before each thing that asks.",
     _has_account),
    ("api", "API key and address", ACCOUNT, API,
     "The key your model calls are paid with, and where they are sent.",
     _has_account),
    ("models", "Models", ACCOUNT, MODELS,
     "Which model answers for each job, and how it is asked.",
     _has_account),
    ("you", "You in this world", CHARACTER_IN_WORLD, YOU_HERE,
     "Your name, looks and pronouns in the world you are standing in.",
     lambda ctx: ctx.character is not None and world_root_of(ctx) is not None),
    ("world", "This world", WORLD, THIS_WORLD,
     "How the world you are standing in runs. Only its creator sees this.",
     owns_world),
]


def _group_items(ctx):
    items = []
    for key, label, _scope, form, about, visible in GROUPS:
        if not visible(ctx):
            continue
        prepare = _models_ready if key == "models" else None
        items.append(m.Submenu(key, label, form, help=about, prepare=prepare))
    return items


SETTINGS = m.Form(
    key="settings", title="Settings",
    intro="Choose a group to see its settings and what each is set to.",
    items=_group_items,
    command=lambda ctx: "settings",
)


def listing(ctx):
    """
    Every setting `ctx` can see, by group, with what it is set to.

    What `settings list` prints, and what anybody who cannot be shown a menu
    is told.
    """
    lines = ["|wSettings|n"]
    for item in SETTINGS.items_for(ctx):
        form, child = item.form, item.context(ctx)
        lines += ["", f"|w{item.label_for(ctx)}|n"]
        for entry in form.items_for(child):
            if isinstance(entry, m.Field):
                lines.append(f"  {entry.label_for(child)}: {entry.shown(child)}"
                             f"  |x(settings {entry.key})|n")
            elif isinstance(entry, m.Submenu) and item.key == "models":
                lines.append(f"  {entry.label_for(child)}")
    lines += ["", "Type |wsettings <name> <value>|n to change one, or "
                  "|wsettings <name> default|n to put it back."]
    return "\n".join(lines)


def static_fields():
    """(group key, field) for every setting whose description needs no context."""
    for key, _label, _scope, form, _about, _visible in GROUPS:
        if callable(form.items):
            continue
        for item in form.items:
            if isinstance(item, m.Field):
                yield key, item
    yield "you", NAME
    yield "you", LOOKS
    yield "you", PRONOUNS


def help_entries():
    """
    A help topic for every setting, so `help busy` answers.

    Built rather than written, like `effects`: a setting added to the register
    documents itself. Readable by name and kept out of the index, because
    fourteen confirmations at the top of `help` would bury the commands.
    """
    for group, field in static_fields():
        label = field.label if isinstance(field.label, str) else field.key
        about = field.help if isinstance(field.help, str) else ""
        text = (f"{label}\n\n{about}\n\n"
                f"Type |wsettings {field.key}|n to see or change it, or "
                f"|wsettings {field.key} default|n to put it back.")
        yield field.key, FileHelpEntry(
            key=field.key, aliases=[f"settings {field.key}"],
            help_category="settings", entrytext=text,
            lock_storage="view:false();read:all()",
        )
