"""
The sampling settings a generator may be tuned with.

Every call this game makes is one of a dozen or so jobs -- naming a room,
speaking in character, deciding whether a verb is possible -- and they do not
want the same settings. Dialogue is better loose and surprising; a rule that
decides what "light" does to a candle wants to be dull and repeatable. So the
settings are per job, alongside the model choice, and this module is what the
menu shows and what the request carries.

Three sources of truth, in order:

* what the player set for that job, which is the only thing ever sent;
* what the model itself publishes as its default (`default_parameters` in
  OpenRouter's model list), which only some models give;
* OpenRouter's own documented default for the parameter, which applies when
  the model says nothing.

The second and third are shown but never sent. Sending a value identical to
the default is not the same as leaving it out -- a provider may treat the
absent case differently -- and it would also freeze today's default into a
world forever.
"""

from collections import namedtuple

#: One tunable setting.
#:
#: key      — what OpenRouter calls it, and how it is stored and sent
#: label    — what the menu calls it
#: kind     — int or float; what a typed value is parsed as
#: low/high — the range OpenRouter accepts, or None for unbounded
#: default  — OpenRouter's documented default when the model publishes none
#: note     — one line on what turning it up actually does
Param = namedtuple("Param", "key label kind low high default note")

PARAMS = (
    Param("temperature", "Temperature", float, 0.0, 2.0, 1.0,
          "How adventurous the wording is. Lower is steadier and more "
          "repetitive; higher is more surprising and less reliable."),
    Param("top_p", "Top P", float, 0.0, 1.0, 1.0,
          "Keeps only the likeliest words that add up to this share of the "
          "probability. 0.9 trims the long tail; 1.0 keeps everything."),
    Param("top_k", "Top K", int, 0, None, 0,
          "Keeps only this many candidate words at each step. 0 turns it off."),
    Param("frequency_penalty", "Frequency penalty", float, -2.0, 2.0, 0.0,
          "Pushes down words it has already used a lot. Raise it when a "
          "generator keeps reaching for the same adjective."),
    Param("presence_penalty", "Presence penalty", float, -2.0, 2.0, 0.0,
          "Pushes down words it has used at all, however rarely. Raise it to "
          "force new subject matter rather than new phrasing."),
    Param("repetition_penalty", "Repetition penalty", float, 0.0, 2.0, 1.0,
          "The same idea again, scaled rather than subtracted. 1.0 is off; "
          "1.1 is a light touch. Not every model offers it."),
    Param("min_p", "Min P", float, 0.0, 1.0, 0.0,
          "Drops any word less likely than this share of the best one. A "
          "gentler trim than Top P. 0 turns it off."),
    Param("top_a", "Top A", float, 0.0, 1.0, 0.0,
          "Trims harder when the model is confident and less when it is not. "
          "0 turns it off."),
    Param("max_tokens", "Maximum length", int, 1, None, None,
          "The longest reply allowed, in tokens. Unset lets the model decide, "
          "which is usually right -- everything here asks for short answers."),
    Param("seed", "Seed", int, None, None, None,
          "Ask for the same answer every time from the same prompt. Useful "
          "for telling a prompt change from ordinary variation."),
)

PARAMS_BY_KEY = {param.key: param for param in PARAMS}

#: What a model has to list in `supported_parameters` for a setting to be
#: offered. Most match their own name; these do not.
_ALIASES = {
    "max_tokens": ("max_tokens", "max_completion_tokens"),
}


def supported(param, model_record):
    """
    True when this model accepts this setting.

    A model that has not published its parameter list at all is given the
    benefit of the doubt: refusing to show a setting is worse than showing one
    the provider quietly ignores.
    """
    listed = (model_record or {}).get("supported_parameters")
    if not listed:
        return True
    names = _ALIASES.get(param.key, (param.key,))
    return any(name in listed for name in names)


def supported_params(model_record):
    """Every setting this model will take, in menu order."""
    return [param for param in PARAMS if supported(param, model_record)]


def default_for(param, model_record):
    """
    (value, source) for a setting nobody has overridden.

    source is "model" when the model publishes its own default, "api" when
    OpenRouter's documented default applies, and "unset" when there is no
    default at all and leaving it out is the whole meaning.
    """
    published = (model_record or {}).get("default_parameters") or {}
    value = published.get(param.key)
    if value is not None:
        return value, "model"
    if param.default is None:
        return None, "unset"
    return param.default, "api"


def parse(param, text):
    """
    (value, complaint) for something a player typed. value is None on refusal.

    An empty string, "default" or "clear" all mean "stop overriding this",
    which is reported as (None, None) -- no value and nothing wrong.
    """
    text = (text or "").strip().lower()
    if text in ("", "default", "clear", "unset", "none"):
        return None, None
    try:
        value = param.kind(text)
    except (TypeError, ValueError):
        want = "a whole number" if param.kind is int else "a number"
        return None, f"{param.label} needs {want}."
    if param.low is not None and value < param.low:
        return None, f"{param.label} cannot go below {_show(param.low)}."
    if param.high is not None and value > param.high:
        return None, f"{param.label} cannot go above {_show(param.high)}."
    return value, None


def _show(value):
    """Numbers as a person writes them: 2 rather than 2.0."""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def show(value):
    """
    A value as it should appear in the menu -- plain text, no markup.

    Plain on purpose: the menu pads these into columns, and Evennia's colour
    codes count towards a string's length while taking up no width on screen,
    so a marked-up cell silently breaks the alignment of every row after it.
    Colour is the caller's business, applied after padding.
    """
    return "unset" if value is None else _show(value)


def range_note(param):
    """"0.0 to 2.0", or "" when the setting is unbounded."""
    if param.low is None and param.high is None:
        return ""
    if param.high is None:
        return f"{_show(param.low)} or above"
    return f"{_show(param.low)} to {_show(param.high)}"


class ModelChoice(str):
    """
    A model id that carries the settings chosen for the job it was picked for,
    and the name of that job.

    It is a string, so every existing use of it -- the payload, the `or`
    fallback chains, log lines -- goes on working untouched. The settings ride
    along because the job's name is known where the model is resolved and not
    where the request is built, and threading it through every call site would
    be a great deal of noise for one dictionary.

    The job's *name* rides along for the same reason and one more: the ledger
    wants to say what a call was for, and "commands" or "dialogue" is known
    only here. Without it every recorded call would say it was for a model,
    which nobody needs telling.
    """

    __slots__ = ("params", "job")

    def __new__(cls, model_id, params=None, job=""):
        choice = super().__new__(cls, model_id or "")
        choice.params = dict(params or {})
        choice.job = str(job or "")
        return choice


def of(model):
    """The settings a model choice carries, or {} for a plain string."""
    return dict(getattr(model, "params", None) or {})


def clean(raw):
    """A stored parameter mapping with only settings that exist and parse."""
    kept = {}
    for key, value in (raw or {}).items():
        param = PARAMS_BY_KEY.get(key)
        if param is None or value is None:
            continue
        try:
            kept[key] = param.kind(value)
        except (TypeError, ValueError):
            continue
    return kept
