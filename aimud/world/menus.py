"""
Menus: the one way this game asks a player to choose.

Every command that needs something the player did not type opens one of these
instead of printing its usage, and every menu has the same keys -- which is the
point of there being one engine rather than a menu per command. A player who
has learned `b`, `q` and `?` in `settings` knows them in `create world`, in a
yes/no, and in whatever a plugin adds next year. See
docs/commands-and-settings.md §3.

**A menu is data.** A `Form` lists `Field`s, `Action`s and `Submenu`s, and
the engine draws it, reads what is typed, and keeps the stack of where the
player has been. Nothing outside this module builds an `EvMenu` node by hand.
That is what lets one description serve three readers: a player moving through
it, a command line that reaches the same point in one go, and later a model
filling a field in (`~`), which needs every field's label, help and value.

**A form may grow what it offers while it is open.** A `Picker` lists what a
world already holds and ends with "none of these -- make one", which opens the
form that makes one; that form answers with `Picked`, and the engine sets the
picker to what came back. A `Submenu` opened with `into=` answers its opener's
draft the same way, adding to a list there when `append`. Those two are the
whole of it, and they are here rather than in a helper because a register that
can be added to from inside a menu is what
docs/player-building.md is built on -- a rule's scope, a condition's state, an
item's kind, an NPC's pronouns.

**Two kinds of form.** An *edit* form changes something over several steps,
and holds the player's input until they finish or quit. A *view* form is
there to be read -- `score`, `quests` -- and shows what it is for at once,
then gets out of the way however the player has chosen (§3.9): by closing
the moment they type something that is not its own, by never opening, or by
staying like an edit form.

**Keys.** Checked in the order `GameMenu.parse_input` checks them. A choice,
by number or by name, wins; then `b`, `q`, `l`, `?` and `~`; then paging; then, on a
long list, anything else filters it. `/` in front of anything means "this is
text, not a key", which is how `b` gets typed into a field or filtered for.

**Built on EvMenu, not beside it.** EvMenu already owns the part that is hard
to get right: a cmdset that takes over input, finding the menu again from
whichever of session, account or character the input arrived on, and closing
cleanly. `GameMenu` keeps all of that and replaces what a menu looks like and
how input is read.

**Nobody without a session is shown a menu.** An NPC, a script, a batch file
or an agent driving a command gets told what the command needed and what it
could have been, in words it can act on. `open_menu` makes that decision, so
no command has to.

Sounds, MXP and OOB come later, through `PRESENTER`. Every place a protocol
would want to hear from a menu calls it, and today every call does nothing.
"""

from evennia.utils.ansi import strip_ansi
from evennia.utils.evmenu import EvMenu

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: The two kinds of form.
EDIT = "edit"
VIEW = "view"

#: What an action does to the menu once it has run.
STAY = "stay"
BACK = "back"
CLOSE = "close"

#: The kinds of field.
TEXT = "text"
LONG_TEXT = "long_text"
NUMBER = "number"
BOOLEAN = "boolean"
CHOICE = "choice"
SECRET = "secret"

#: How a view menu behaves after showing what it is for. §3.9.
WALK_AWAY = "walk_away"
CLOSE_VIEW = "close"
STAY_OPEN = "stay"
VIEW_MODES = (WALK_AWAY, CLOSE_VIEW, STAY_OPEN)

#: How many entries a list shows at once, until the player says otherwise
#: with the `pagesize` setting. 0 there means every entry on one page.
PAGE_SIZE = 10

#: A list longer than this can be narrowed by typing, however it is paged --
#: a list of three hundred models is worth filtering even shown whole.
FILTER_FROM = 10

#: Put in front of input to have it read as text rather than as a key.
ESCAPE = "/"

#: Above the puppet's exits (101), so a menu run on the account is not robbed
#: of `n` and `p` by an exit called north. Found the hard way by the models
#: menu; kept here so no menu has to find it again.
PRIORITY = 110

#: Said when the player closes a menu themselves, with `q` or by backing out.
CLOSED = "Menu closed. You are back in the game."

QUIT_WORDS = ("q", "quit", "exit")
BACK_WORDS = ("b", "back")
LOOK_WORDS = ("l", "look")
HELP_WORDS = ("?", "h", "help")
SUGGEST_WORDS = ("~",)
NEXT_WORDS = ("n", "next")
PREV_WORDS = ("p", "prev", "previous")
YES_WORDS = ("yes", "y")
NO_WORDS = ("no", "n")
BOOLEAN_YES = ("yes", "y", "on", "true")
BOOLEAN_NO = ("no", "off", "false")
CLEAR_WORDS = ("clear",)

#: Every word a form may not use as a choice's name, because it already means
#: something in every menu.
RESERVED = frozenset(QUIT_WORDS + BACK_WORDS + LOOK_WORDS + HELP_WORDS
                     + SUGGEST_WORDS + NEXT_WORDS + PREV_WORDS)

#: Where a player's menu preferences are kept, on the account. Read here
#: rather than through the settings registry so that the engine does not
#: depend on it; the registry points at the same attributes.
VIEW_MODE_ATTR = "menu_view_mode"
SHOW_COMMAND_ATTR = "menu_show_command"
PAGE_SIZE_ATTR = "menu_page_size"
CONFIRMATIONS_ATTR = "confirmations"


class Refuse(Exception):
    """
    Raised by an action, a parser or a lock to say no and stay where it is.

    The message is shown to the player as it stands, so it should say what to
    do instead.
    """


# ---------------------------------------------------------------------------
# Where a menu reports to protocols
# ---------------------------------------------------------------------------

class Presenter:
    """
    Every point a sound, an MXP link or an OOB message would want to know about.

    Today each does nothing except `shown`, which hands back the text it was
    given. A protocol replaces `PRESENTER` with a subclass; nothing in a form
    or a command changes when it does.
    """

    def opened(self, menu):
        """The menu has opened, before anything is drawn."""

    def shown(self, menu, text):
        """A screen is about to be drawn. Returns the text to send."""
        return text

    def chose(self, menu, item):
        """The player chose `item`: a field, an action, a submenu."""

    def refused(self, menu, text):
        """Input matched nothing; `text` is what the player is being told."""

    def confirmed(self, menu, key, answer):
        """A yes/no was answered. `key` names the confirmation, if any."""

    def closed(self, menu, why):
        """The menu has closed: "quit", "back", "finished" or "walked away"."""


PRESENTER = Presenter()


# ---------------------------------------------------------------------------
# Preferences the engine reads
# ---------------------------------------------------------------------------

def account_of(who):
    """The account behind `who`, or None."""
    from evennia.accounts.accounts import DefaultAccount

    if isinstance(who, DefaultAccount):
        return who
    return getattr(who, "account", None)


def _preference(who, attr, default):
    account = account_of(who)
    if account is None:
        return default
    stored = account.attributes.get(attr)
    return default if stored is None else stored


def view_mode(who):
    """How `who` wants view menus to behave. §3.9."""
    mode = _preference(who, VIEW_MODE_ATTR, WALK_AWAY)
    return mode if mode in VIEW_MODES else WALK_AWAY


def page_size(who):
    """How many entries `who` wants on a page: 0 for all of them at once."""
    try:
        return max(0, int(_preference(who, PAGE_SIZE_ATTR, PAGE_SIZE)))
    except (TypeError, ValueError):
        return PAGE_SIZE


def shows_commands(who):
    """Whether finishing something through a menu says how to type it."""
    return bool(_preference(who, SHOW_COMMAND_ATTR, True))


def confirmation_wanted(who, key):
    """Whether `who` wants to be asked before the action `key`. On unless off."""
    if not key:
        return True
    return bool((_preference(who, CONFIRMATIONS_ATTR, {}) or {}).get(key, True))


def interactive(who):
    """Whether anybody is connected to `who` to be shown a menu."""
    try:
        return bool(who.sessions.count())
    except AttributeError:
        return False


# ---------------------------------------------------------------------------
# What a form is made of
# ---------------------------------------------------------------------------

def _call(value, ctx, default=None):
    """A value that may be given as it is or as a function of the context."""
    if callable(value):
        return value(ctx)
    return default if value is None else value


class Context:
    """
    Everything a form's functions are handed: who, where, and the draft.

    `caller` is whoever typed the command, `character` the body they are
    playing (if any), `account` the person. Anything the command passed when
    it opened the menu -- a world, a rule -- is readable as an attribute:
    `ctx.world_root`.
    """

    def __init__(self, caller, session=None, draft=None, **data):
        from evennia.objects.objects import DefaultObject

        self.caller = caller
        self.session = session
        self.account = account_of(caller)
        if isinstance(caller, DefaultObject):
            self.character = caller
        else:
            puppet = None
            if self.account is not None and session is not None:
                try:
                    puppet = self.account.get_puppet(session)
                except Exception:
                    puppet = None
            self.character = puppet
        self.draft = dict(draft or {})
        self.dirty = False
        self.data = dict(data)

    def __getattr__(self, name):
        data = self.__dict__.get("data") or {}
        if name in data:
            return data[name]
        raise AttributeError(name)

    def child(self, **data):
        """The context a submenu gets: the same people and draft, more data."""
        merged = dict(self.data)
        merged.update(data)
        child = Context.__new__(Context)
        child.__dict__.update(self.__dict__)
        child.data = merged
        return child


class Item:
    """What every entry in a form has: a name, a label, help and a lock."""

    def __init__(self, key, label, help="", lock=None, aliases=(),
                 default=False, command=None, topic=None):
        self.key = str(key).lower()
        self.label = label
        self.help = help
        # A help topic to read when there is no help text of its own, so `?`
        # says what `help <topic>` says rather than a second version of it.
        self.topic = topic
        self.lock = lock
        self.aliases = tuple(str(alias).lower() for alias in aliases)
        self.default = default
        self.command = command
        for name in (self.key,) + self.aliases:
            if name in RESERVED:
                raise ValueError(f"{name!r} is a menu key in every menu and "
                                 f"cannot name a choice.")

    def names(self):
        return (self.key,) + self.aliases

    def allowed(self, ctx):
        return self.lock is None or bool(self.lock(ctx))

    def label_for(self, ctx):
        return str(_call(self.label, ctx, ""))

    def help_for(self, ctx):
        text = str(_call(self.help, ctx, "") or "").strip()
        if text or not self.topic:
            return text
        from commands.help_cmds import topic_text

        return topic_text(ctx.character or ctx.caller,
                          _call(self.topic, ctx, ""))

    def command_for(self, ctx):
        return str(_call(self.command, ctx, "") or "").strip()


class Choice:
    """One of the values a choice field can take."""

    def __init__(self, value, label, help="", keys=()):
        self.value = value
        self.label = label
        self.help = help
        self.keys = tuple(str(key).lower() for key in keys)


class Field(Item):
    """
    A value somebody can set: typed, picked from a list, or written at length.

    With no `get` and `set` a field lives in the form's draft, which is what a
    wizard wants: nothing is written anywhere until an action says so. A
    setting passes both, and is written the moment it changes.

    `parse(ctx, text)` returns `(value, complaint)`, the shape
    `busy.parse_interval` and `model_params.parse` already have. A complaint
    is shown and the field stays open for another try.
    """

    def __init__(self, key, label, kind=TEXT, help="", get=None, set=None,
                 parse=None, choices=None, show=None, prompt=None,
                 required=False, minimum=None, maximum=None,
                 suggestible=False, empty="not set", confirm=None,
                 after=STAY, **kwargs):
        super().__init__(key, label, help=help, **kwargs)
        self.kind = kind
        # What setting it does to the menu. `CLOSE` is for a field that is the
        # whole point of its form: what you want to remember, a new goal.
        self.after = after
        # `confirm(ctx, value)` returns (key, question) when that value needs
        # asking about first -- putting a world into `always`, clearing a key.
        self.confirm = confirm
        self.get = get
        self.set = set
        self.parse = parse
        self.choices = choices
        self.show = show
        self.prompt = prompt
        self.required = required
        self.minimum = minimum
        self.maximum = maximum
        self.empty = empty
        # A secret is never offered to a model, whatever the form says.
        self.suggestible = suggestible and kind != SECRET

    def value(self, ctx):
        if self.get is not None:
            return self.get(ctx)
        return ctx.draft.get(self.key)

    def is_set(self, ctx):
        value = self.value(ctx)
        return value is not None and value != ""

    def store(self, ctx, value):
        """
        Keep a value. Returns whatever `set` said about it, to be shown.

        Only a draft marks the form as changed: a live setting is already
        written, so there is nothing to throw away by quitting.
        """
        if self.set is not None:
            return self.set(ctx, value)
        if value is None:
            ctx.draft.pop(self.key, None)
        else:
            ctx.draft[self.key] = value
        ctx.dirty = True
        return None

    def confirmation(self, ctx, value):
        """(key, question) when setting `value` has to be asked about first."""
        if self.confirm is None:
            return None
        return self.confirm(ctx, value)

    def choices_for(self, ctx):
        if self.kind == BOOLEAN:
            return [Choice(True, "Yes", keys=BOOLEAN_YES),
                    Choice(False, "No", keys=BOOLEAN_NO)]
        return list(_call(self.choices, ctx, []) or [])

    def choose_value(self, ctx, text):
        """(value, complaint) for a choice named by what somebody typed."""
        said = text.strip().lower()
        for choice in self.choices_for(ctx):
            label = strip_ansi(str(_call(choice.label, ctx, ""))).lower()
            if said in choice.keys or said == label \
                    or said == str(choice.value).lower():
                return choice.value, ""
        return None, f"{text.strip()} is not one of the choices."

    def shown(self, ctx):
        """The value as one line, for a summary."""
        value = self.value(ctx)
        if self.show is not None:
            return str(self.show(ctx, value))
        if value is None or value == "":
            return self.empty
        if self.kind == SECRET:
            return "set"
        if self.kind in (CHOICE, BOOLEAN):
            for choice in self.choices_for(ctx):
                if choice.value == value:
                    return _call(choice.label, ctx, "")
        text = str(value)
        first = text.splitlines()[0] if text else ""
        more = len(text.splitlines()) - 1
        if len(first) > 60:
            first = first[:57].rstrip() + "..."
        return first + (f" (and {more} more lines)" if more > 0 else "")

    def read(self, ctx, text):
        """(value, complaint) for what somebody typed into this field."""
        if self.parse is not None:
            return self.parse(ctx, text)
        if self.kind in (CHOICE, BOOLEAN):
            return self.choose_value(ctx, text)
        if self.kind == NUMBER:
            try:
                number = float(text) if "." in text else int(text)
            except ValueError:
                return None, "That has to be a number."
            if self.minimum is not None and number < self.minimum:
                return None, f"That has to be at least {self.minimum}."
            if self.maximum is not None and number > self.maximum:
                return None, f"That has to be at most {self.maximum}."
            return number, ""
        if not text and self.required:
            return None, "This one cannot be left empty."
        return text, ""


class Picker(Field):
    """
    A field answered from what the world already has, or by making one.

    `options(ctx)` is what exists -- `(value, label)` or `(value, label, help)`
    -- and the entry after them opens `make`, whose own last action answers
    with a `Picked`. The engine then sets this field to what came back.

    That is the whole of "offer what is there, and the chance to make one when
    none of it fits", and it is engine work rather than a helper in one module
    because six forms in docs/player-building.md want it: a rule's scope, a
    condition's state, an item's kind, an NPC's pronouns, a quest's giver, an
    attribute's group. Each lists a register that is allowed to grow while
    somebody is standing in the middle of using it, which is exactly the case
    a fixed `choices` list cannot serve.
    """

    def __init__(self, key, label, options=None, make=None, make_data=None,
                 make_draft=None, none="None of these -- make a new one",
                 **kwargs):
        kwargs.setdefault("kind", CHOICE)
        super().__init__(key, label, **kwargs)
        self.options = options
        # `make(ctx)` is the form that makes one. None -- or a function
        # answering None -- means this picker only offers what is there, which
        # is right for a register somebody else fills.
        self.make = make
        self.make_data = make_data
        self.make_draft = make_draft
        self.none = none

    def choices_for(self, ctx):
        found = []
        for option in _call(self.options, ctx, []) or []:
            if isinstance(option, Choice):
                found.append(option)
                continue
            value, label, helped = (tuple(option) + ("", ""))[:3]
            found.append(Choice(value, label, help=helped))
        return found

    def make_form(self, ctx):
        return _call(self.make, ctx, None)

    def none_label(self, ctx):
        return str(_call(self.none, ctx, "") or "")


class Picked:
    """
    What an action answers with when something below it was waiting for a value.

    A `Picker` opens a maker's own form from inside a field; that form finishes
    with an action returning one of these, and the engine writes the value
    where the picker was waiting and comes back to it. A `Submenu` opened with
    `into=` does the same into its opener's draft.

    Returned with nothing waiting, it behaves as `after=BACK` with a message,
    which is what it means: the form answered, and there was nobody to answer.
    """

    def __init__(self, value, said=""):
        self.value = value
        self.said = said


#: Stands in a picker's list for "none of these -- make one". One object for
#: every picker; the label lives on the entry, as every other label does.
MAKE_NEW = "__make_new__"

#: What `_answer` says when a `Picked` came back and nothing had asked for it.
#: Not None, which is what every other handler here returns to mean "drawn".
_NOBODY_WAITING = object()


class Action(Item):
    """
    Something that happens when chosen.

    `run(ctx)` returns what to tell the player, or nothing, and raises
    `Refuse` to stay put with a message. `confirm` names the confirmation
    that guards it (docs/commands-and-settings.md §8); `question` is what is
    asked. `after` says where the player is left.
    """

    def __init__(self, key, label, run, confirm=None, question=None,
                 after=STAY, **kwargs):
        super().__init__(key, label, **kwargs)
        self.run = run
        self.confirm = confirm
        self.question = question
        self.after = after


class Submenu(Item):
    """
    Another form, opened from this one, with more context passed down.

    `fresh_draft` gives the submenu a draft of its own, for a wizard opened
    from inside another form. `prepare(ctx, proceed, fail)` runs first, for a
    submenu that needs something fetched before it can be drawn -- the list
    of models -- and calls `proceed()` when it has it or `fail(text)` when it
    cannot. It may call either later, from a callback.
    """

    def __init__(self, key, label, form, data=None, fresh_draft=False,
                 prepare=None, draft=None, into=None, append=False, **kwargs):
        super().__init__(key, label, **kwargs)
        self.form = form
        self.data = data
        self.fresh_draft = fresh_draft or draft is not None or into is not None
        self.prepare = prepare
        # `draft(ctx)` fills the fresh draft in: editing a world starts from
        # what the world was set up with.
        self.draft = draft
        # `into` names a key in the OPENER's draft that this submenu answers,
        # with `Picked`. `append` adds to a list there rather than replacing
        # it, which is how a rule collects conditions one at a time.
        self.into = into
        self.append = append

    def context(self, ctx):
        data = _call(self.data, ctx, {}) or {}
        child = ctx.child(**data)
        if self.fresh_draft:
            child.draft = dict(self.draft(child) if self.draft else {})
            child.dirty = False
        return child


class Form:
    """
    A menu, as data. See the module docstring.

    `intro` is shown under the title. For a view form it is the whole point:
    what `score` prints is the intro of the score form.

    `guided` walks a new draft through its required fields one at a time
    before showing the summary, which is how a wizard feels without being a
    different thing from a form.
    """

    def __init__(self, key, title, items=(), intro="", kind=EDIT,
                 guided=False, command=None, on_close=None,
                 discard="Throw away what you have entered?",
                 choices_line="For one of them:",
                 sponsor=None, context=None):
        self.key = key
        # `sponsor(ctx)` is who pays when `~` asks a model to fill a field in;
        # a form without one cannot be filled in. `context(ctx)` is anything
        # the model should know beyond the fields themselves.
        self.sponsor = sponsor
        self.context = context
        self.title = title
        self.items = items
        self.intro = intro
        self.kind = kind
        self.guided = guided
        self.command = command
        self.on_close = on_close
        self.discard = discard
        self.choices_line = choices_line

    def items_for(self, ctx):
        found = _call(self.items, ctx, []) or []
        return [item for item in found if item.allowed(ctx)]

    def title_for(self, ctx):
        return str(_call(self.title, ctx, ""))

    def intro_for(self, ctx):
        return str(_call(self.intro, ctx, "") or "").rstrip()

    def unset_required(self, ctx):
        """The first required field with no value, or None."""
        for item in self.items_for(ctx):
            if isinstance(item, Field) and item.required and not item.is_set(ctx):
                return item
        return None


# ---------------------------------------------------------------------------
# Lists: numbering, paging and filtering, for forms and for choice fields
# ---------------------------------------------------------------------------

class _Entry:
    """One line of a list: what it stands for, what it is called, and names."""

    def __init__(self, target, label, names):
        self.target = target
        self.label = label
        self.names = tuple(name for name in names if name)


def _filtered(entries, text):
    text = text.lower().strip()
    if not text:
        return entries
    return [entry for entry in entries
            # A picker's "make one" survives every filter. Somebody who has
            # narrowed a long list down to nothing is the likeliest person in
            # the game to need it.
            if entry.target is MAKE_NEW
            or text in strip_ansi(entry.label).lower()
            or any(text in name for name in entry.names)]


def _pick(entries, text):
    """The entry `text` names, by number or by name, or None."""
    said = text.lower().strip()
    if said.isdigit():
        index = int(said) - 1
        return entries[index] if 0 <= index < len(entries) else None
    for entry in entries:
        if said in entry.names or said == strip_ansi(entry.label).lower():
            return entry
    return None


def _step_of(form, ctx, field):
    """
    "(2 of 5)" for a field in a wizard, or None.

    Found **by key** and not by identity. A form whose `items` is a function
    of the context builds a fresh `Field` every time it is asked, so the field
    a caller is holding is never the same object as the one in the next
    listing -- which made this raise on `open_menu` and quietly give up on the
    step count everywhere else. Every form in world/makers builds its items
    that way, because what they offer depends on what the world holds.
    """
    if not form.guided:
        return None
    required = [item for item in form.items_for(ctx)
                if isinstance(item, Field) and item.required]
    for number, item in enumerate(required, 1):
        if item.key == field.key:
            return (number, len(required))
    return None


class _Frame:
    """One level of the stack: a form, a field being set, a question."""

    def __init__(self, kind, form, ctx, item=None, step=None, into=None):
        self.kind = kind          # "form", "field", "confirm" or "help"
        self.form = form
        self.ctx = ctx
        self.item = item
        self.step = step
        # What this frame answers when an action in it returns `Picked`:
        # ("field", the field frame) or ("draft", the form frame, key, append).
        self.into = into
        self.filter = ""
        self.page = 0
        self.question = None      # what a confirmation asks
        self.pending = None       # the action a confirmation guards
        self.pending_run = None   # what it does on yes
        self.on_no = None         # what it does on no, if not the usual


# ---------------------------------------------------------------------------
# The menu
# ---------------------------------------------------------------------------

class GameMenu(EvMenu):
    """
    EvMenu, drawing and reading forms.

    Only one node exists as far as EvMenu knows: `show`, which draws whatever
    is on top of the stack. Everything else is `parse_input` deciding what to
    push or pop, and then drawing once.
    """

    def __init__(self, runner, stack, session=None, resumed=False):
        self.stack = list(stack)
        self._resumed = resumed
        self._opened = False
        # Set when the menu closes for a reason other than the player leaving
        # it: to make way for the line editor, which reopens it afterwards.
        self._handing_on = None
        super().__init__(
            runner, {"show": _show_node}, startnode="show",
            cmd_on_exit=None, cmdset_priority=PRIORITY, auto_quit=False,
            auto_look=False, auto_help=False, persistent=False,
            session=session,
        )

    # -- drawing -----------------------------------------------------------

    @property
    def top(self):
        return self.stack[-1]

    def refresh(self):
        """Draw the top of the stack again."""
        self.goto("show", "")

    def render(self):
        frame = self.top
        if frame.kind == "field":
            text = self._render_field(frame)
        elif frame.kind == "confirm":
            text = self._render_confirm(frame)
        elif frame.kind == "help":
            text = self._render_help(frame)
        elif frame.kind == "suggest":
            text = self._render_suggest(frame)
        elif frame.kind == "proposal":
            text = self._render_proposal(frame)
        elif frame.form.kind == VIEW:
            text = self._render_view(frame)
        else:
            text = self._render_form(frame)
        return PRESENTER.shown(self, text)

    def nodetext_formatter(self, nodetext):
        return nodetext

    def options_formatter(self, optionlist):
        return ""

    def node_formatter(self, nodetext, optionstext):
        # EvMenu rules lines above and below every node. A screen reader
        # reads them out character by character, so there are none.
        return nodetext

    def say(self, text):
        if text:
            self.msg(text)

    def _form_entries(self, frame):
        entries = []
        for item in frame.form.items_for(frame.ctx):
            label = item.label_for(frame.ctx)
            names = item.names() + (strip_ansi(label).lower(),)
            entries.append(_Entry(item, label, names))
        return entries

    def _choice_entries(self, frame):
        entries = []
        # Where a broken list of choices stops. A field's choices are worked
        # out from whatever the game holds, and one that raises used to take
        # the menu down in front of whoever chose that line -- and leave it
        # open, so everything typed afterwards hit the same wall and even
        # quitting looked broken. Logged loudly and drawn short instead.
        # Nothing else guards this: a caller asking a field what it offers
        # gets the exception, which is what a test wants.
        try:
            offered = frame.item.choices_for(frame.ctx)
        except Exception:
            from evennia.utils import logger

            logger.log_trace(f"menus: {frame.item.key} could not work out "
                             f"what it offers")
            offered = []
        for choice in offered:
            label = str(_call(choice.label, frame.ctx, ""))
            names = choice.keys + (str(choice.value).lower(),)
            entries.append(_Entry(choice, label, names))
        field = frame.item
        # A picker's last entry, always last however the list is filtered:
        # somebody who has typed to narrow a long list to nothing is exactly
        # the person who needs to be able to make one.
        if isinstance(field, Picker) and field.make_form(frame.ctx) is not None:
            entries.append(_Entry(MAKE_NEW, field.none_label(frame.ctx),
                                  ("new", "make", "none", "other")))
        return entries

    def _size(self, frame=None):
        """
        How many entries a list shows at once: the player's `pagesize`, the
        same in every menu. 0 is every entry on one page.
        """
        return page_size(self.caller)

    def _paged(self, count):
        """Whether a list of `count` entries runs to more than one page."""
        size = self._size()
        return bool(size) and count > size

    def _page(self, frame, entries):
        """(shown, numbered from, footer lines) for one page of a list."""
        visible = _filtered(entries, frame.filter)
        size = self._size()
        if not size:
            frame.page = 0
            pages, start, shown = 1, 0, visible
        else:
            pages = max(1, -(-len(visible) // size))
            frame.page = max(0, min(frame.page, pages - 1))
            start = frame.page * size
            shown = visible[start:start + size]
        notes = []
        if frame.filter:
            matched = len(visible)
            notes.append(f"Showing what matches {frame.filter}: {matched} "
                         f"{'match' if matched == 1 else 'matches'}. An empty "
                         f"line shows everything again.")
        if pages > 1:
            notes.append(f"Page {frame.page + 1} of {pages}.")
        return visible, shown, start, notes

    def _keys_line(self, frame, paged, filterable, entry=False):
        said = ["b goes back", "q quits"]
        if self._has_help(frame):
            said.append("? explains a choice")
        if self._suggestible(frame):
            said.append("~ fills it in for you" if entry
                        else "~ fills one in for you")
        if paged and isinstance(frame.item, Picker) \
                and frame.item.make_form(frame.ctx) is not None:
            # On the last page, where the entry itself is. Said anyway,
            # because the entry is numbered on one page out of twenty and the
            # word works from all of them.
            said.append("new makes one that is not listed")
        if paged:
            said.append("n and p turn the page")
        if filterable:
            said.append("anything else filters the list")
        if entry and "? explains a choice" in said:
            said[said.index("? explains a choice")] = "? says more about it"
        line = "Choose by number. " if not entry else ""
        line += ", ".join(said[:-1]) + " and " + said[-1] + "."
        return line

    def _render_form(self, frame):
        ctx = frame.ctx
        lines = [f"|w{frame.form.title_for(ctx)}|n"]
        intro = frame.form.intro_for(ctx)
        if intro:
            lines += [intro]
        entries = self._form_entries(frame)
        filterable = len(entries) > FILTER_FROM
        visible, shown, start, notes = self._page(frame, entries)
        lines.append("")
        if not shown:
            lines.append("Nothing matches.")
        for number, entry in enumerate(shown, start + 1):
            lines.append(f"{number}. {self._item_line(ctx, entry)}")
        lines += [""] + notes if notes else [""]
        lines.append(self._keys_line(frame, self._paged(len(visible)),
                                     filterable))
        return "\n".join(lines)

    def _item_line(self, ctx, entry):
        item = entry.target
        line = entry.label
        if isinstance(item, Field):
            # A field with nothing to show -- a question, not a setting -- is
            # just its label, not a label and a colon read out before nothing.
            shown = item.shown(ctx)
            if shown:
                line += f": {shown}"
        if item.default:
            line += " (the default)"
        return line

    def _render_view(self, frame):
        ctx = frame.ctx
        lines = []
        intro = frame.form.intro_for(ctx)
        if intro:
            lines.append(intro)
        choices = self._choices_line(frame)
        if choices:
            lines += ["", choices]
        return "\n".join(lines)

    def _choices_line(self, frame):
        entries = self._form_entries(frame)
        if not entries:
            return ""
        visible, shown, start, notes = self._page(frame, entries)
        listed = ", ".join(f"{number} {strip_ansi(entry.label)}"
                           for number, entry in enumerate(shown, start + 1))
        line = f"{frame.form.choices_line} {listed}."
        if self._paged(len(visible)):
            line += " Type next or prev for more."
        return line

    def _render_field(self, frame):
        ctx, field = frame.ctx, frame.item
        heading = f"|w{field.label_for(ctx)}|n"
        if frame.step:
            heading += f" ({frame.step[0]} of {frame.step[1]})"
        lines = [heading]
        helped = field.help_for(ctx)
        if helped:
            lines.append(helped)
        lines.append("")
        if field.is_set(ctx):
            lines.append(f"Currently: {field.shown(ctx)}.")

        if field.kind in (CHOICE, BOOLEAN):
            asked = _call(field.prompt, ctx, "")
            if asked:
                lines.insert(1, asked)
            entries = self._choice_entries(frame)
            filterable = len(entries) > FILTER_FROM
            visible, shown, start, notes = self._page(frame, entries)
            if not entries:
                lines.append("|yThere is nothing to choose from here.|n")
            for number, entry in enumerate(shown, start + 1):
                lines.append(f"{number}. {entry.label}")
            lines += [""] + notes if notes else [""]
            keys = self._keys_line(frame, self._paged(len(visible)), filterable)
            if not field.required and field.is_set(ctx):
                keys += " clear removes it."
            lines.append(keys)
            return "\n".join(lines)

        typed = _call(field.prompt, ctx, "")
        if not typed:
            label = strip_ansi(field.label_for(ctx)).lower()
            typed = (f"Type the {label}" if field.kind != LONG_TEXT
                     else "Type it")
        typed = typed.rstrip(".")
        if not field.required and field.is_set(ctx):
            typed += ", or clear to remove it"
        lines.append(typed + ".")
        lines.append(self._keys_line(frame, False, False, entry=True)
                     + " To type one of those as it is, start with /.")
        return "\n".join(lines)

    def _render_confirm(self, frame):
        question = _call(frame.question, frame.ctx, "") or "Are you sure?"
        return "\n".join([question, "", "1. No (the default)", "2. Yes", "",
                          "Choose by number, or type yes or no."])

    def _render_help(self, frame):
        lines = ["|wHelp on which?|n", ""]
        for number, entry in enumerate(self._helped_entries(frame), 1):
            lines.append(f"{number}. {entry.label}")
        lines += ["", "Choose by number. b goes back and q quits."]
        return "\n".join(lines)

    # -- what can be asked for -----------------------------------------------

    def _underlying(self, frame):
        """The form frame a help or confirm frame is sitting on."""
        for below in reversed(self.stack):
            if below.kind == "form":
                return below
        return frame

    def _helped_entries(self, frame):
        base = self._underlying(frame)
        return [entry for entry in self._form_entries(base)
                if entry.target.help_for(base.ctx)]

    def _has_help(self, frame):
        if frame.kind == "field":
            return bool(frame.item.help_for(frame.ctx))
        return bool(self._helped_entries(frame))

    def _suggestible(self, frame):
        """Whether `~` means anything here."""
        base = self._underlying(frame)
        if base.form.sponsor is None:
            return False
        if frame.kind == "field":
            return frame.item.suggestible
        from world import suggesting

        return bool(suggesting.fillable(base.ctx, base.form))

    # -- filling in with a model --------------------------------------------

    def _suggest(self, frame, asked):
        """`~`, `~2` or `~ title`: choose what to fill, or fill it."""
        from world import suggesting

        base = self._underlying(frame)
        if not self._suggestible(frame):
            return self.say("Nothing here can be filled in for you.")
        if frame.kind == "field" and not asked:
            return self._fill(base, [frame.item])

        fields = suggesting.fillable(base.ctx, base.form)
        if asked:
            if asked in ("all", "empty"):
                return self._fill_empty(base, fields)
            entries = self._form_entries(base)
            chosen = _pick(_filtered(entries, base.filter), asked)
            if chosen is None or chosen.target not in fields:
                return self._refuse(f"{asked} is not something that can be "
                                    f"filled in for you here.")
            return self._fill(base, [chosen.target])
        if len(fields) == 1:
            return self._fill(base, fields)
        self.stack.append(_Frame("suggest", base.form, base.ctx))
        self.refresh()

    def _fill_empty(self, base, fields):
        empty = [field for field in fields if not field.is_set(base.ctx)]
        if not empty:
            return self.say("Every field that can be filled in already has "
                            "something in it.")
        return self._fill(base, empty)

    def _suggest_entries(self, frame):
        from world import suggesting

        base = self._underlying(frame)
        fields = suggesting.fillable(base.ctx, base.form)
        entries = [_Entry(field, field.label_for(base.ctx), field.names())
                   for field in fields]
        entries.append(_Entry("all", "All empty fields", ("all", "empty")))
        return entries

    def _render_suggest(self, frame):
        lines = ["|wFill in which?|n", ""]
        for number, entry in enumerate(self._suggest_entries(frame), 1):
            lines.append(f"{number}. {entry.label}")
        lines += ["", "Choose by number. A model writes a first draft for you "
                      "to keep or not. b goes back and q quits."]
        return "\n".join(lines)

    def _suggest_input(self, frame, text):
        if self._navigate_minimal(text):
            return None
        chosen = _pick(self._suggest_entries(frame), text)
        if chosen is None:
            return self._refuse()
        self.stack.pop()
        base = self._underlying(frame)
        if chosen.target == "all":
            from world import suggesting

            return self._fill_empty(base, suggesting.fillable(base.ctx,
                                                              base.form))
        return self._fill(base, [chosen.target])

    def _fill(self, base, fields):
        """
        Ask a model for values, and offer them when they come.

        The menu stays usable meanwhile. An answer that arrives after the menu
        has closed is not used, and the player is told so.
        """
        from world import busy, suggesting

        labels = ", ".join(strip_ansi(field.label_for(base.ctx))
                           for field in fields)
        runner = self.caller
        teller = base.ctx.character or runner
        self.say(f"Asking a model to fill in {labels}...")
        wait = busy.start(teller, f"filling in {labels}")

        def arrived(values):
            if runner.ndb._evmenu is not self:
                return teller.msg(f"The suggestion for {labels} arrived after "
                                  f"the menu closed, so it was not used.")
            self._offer(base, fields, values)

        def failed(why):
            if runner.ndb._evmenu is not self:
                return teller.msg(f"Filling in {labels} failed: {why}")
            self.say(f"|rCould not fill in {labels}: {why}|n")

        suggesting.fill(base.ctx, base.form, fields,
                        on_done=busy.closing(wait, arrived),
                        on_error=busy.closing(wait, failed), wait=wait)

    def _offer(self, base, fields, values):
        """A proposal: shown to be kept, refused or tried again."""
        if not confirmation_wanted(self.caller, "suggestion"):
            return self._keep(base, fields, values)
        offer = _Frame("proposal", base.form, base.ctx)
        offer.pending = (base, fields, values)
        self.stack.append(offer)
        self.refresh()

    def _keep(self, base, fields, values):
        said = []
        for field in fields:
            if field.key in values:
                PRESENTER.chose(self, field)
                said.append(field.store(base.ctx, values[field.key]))
        for text in said:
            self.say(text)
        # Filled from inside the field itself: back to the form, as a typed
        # value would have gone.
        while self.top.kind == "field" and self.top.item in fields:
            self.stack.pop()
        self.refresh()

    def _render_proposal(self, frame):
        base, fields, values = frame.pending
        lines = ["|wSuggested|n", ""]
        for field in fields:
            if field.key not in values:
                continue
            value = values[field.key]
            if field.kind in (CHOICE, BOOLEAN):
                shown = next((str(_call(choice.label, base.ctx, ""))
                              for choice in field.choices_for(base.ctx)
                              if choice.value == value), str(value))
            else:
                shown = str(value)
            lines += [f"|w{strip_ansi(field.label_for(base.ctx))}|n", shown, ""]
        lines += ["Use this?", "", "1. No (the default)", "2. Yes",
                  "3. Try again", "", "Choose by number."]
        return "\n".join(lines)

    def _proposal_input(self, frame, text):
        base, fields, values = frame.pending
        word = text.lower()
        if word in ("2",) + YES_WORDS:
            PRESENTER.confirmed(self, "suggestion", True)
            self.stack.pop()
            return self._keep(base, fields, values)
        if word in ("3", "again", "try", "retry"):
            self.stack.pop()
            return self._fill(base, fields)
        if word in ("1",) + NO_WORDS + QUIT_WORDS + BACK_WORDS:
            PRESENTER.confirmed(self, "suggestion", False)
            self.stack.pop()
            self.say("Nothing changed.")
            return self.refresh()
        if word in LOOK_WORDS or not word:
            return self.display_nodetext()
        return self._refuse("Choose 1 for no, 2 for yes or 3 to try again.")

    # -- reading input -------------------------------------------------------

    def parse_input(self, raw_string):
        text = strip_ansi(raw_string or "").strip()
        frame = self.top
        try:
            if frame.kind == "form" and frame.form.kind == VIEW:
                self._view_input(frame, text, raw_string)
            elif frame.kind == "form":
                self._form_input(frame, text)
            elif frame.kind == "field":
                self._field_input(frame, text)
            elif frame.kind == "confirm":
                self._confirm_input(frame, text)
            elif frame.kind == "help":
                self._help_input(frame, text)
            elif frame.kind == "suggest":
                self._suggest_input(frame, text)
            elif frame.kind == "proposal":
                self._proposal_input(frame, text)
        except Refuse as refusal:
            self.say(str(refusal))

    def _refuse(self, text=None):
        said = text or ("That is not one of the choices. l lists them again, "
                        "and ? explains them.")
        PRESENTER.refused(self, said)
        self.say(said)

    def _navigate(self, frame, text):
        """Handle a key that means the same in every menu. True if it did."""
        word = text.lower()
        if word in QUIT_WORDS:
            self.quit()
        elif word in BACK_WORDS:
            self.back()
        elif word in LOOK_WORDS:
            self.display_nodetext()
        elif word in HELP_WORDS:
            self._ask_help(frame)
        elif word[:1] == "?" or word.startswith(("help ", "h ")):
            asked = word[1:] if word[:1] == "?" else word.split(None, 1)[1]
            self._explain(frame, asked.strip())
        elif word[:1] == "~":
            self._suggest(frame, word[1:].strip())
        else:
            return False
        return True

    def _turn_page(self, frame, text, entries):
        word = text.lower()
        if not self._paged(len(_filtered(entries, frame.filter))):
            return False
        if word in NEXT_WORDS:
            frame.page += 1
        elif word in PREV_WORDS:
            frame.page -= 1
        else:
            return False
        self.refresh()
        return True

    def _form_input(self, frame, text):
        entries = self._form_entries(frame)
        filterable = len(entries) > FILTER_FROM
        if text.startswith(ESCAPE) and len(text) > 1:
            if filterable:
                return self._set_filter(frame, text[1:])
            return self._refuse()
        if not text:
            if frame.filter:
                return self._set_filter(frame, "")
            return self.display_nodetext()

        visible = _filtered(entries, frame.filter)
        chosen = _pick(visible, text)
        if chosen is not None:
            return self.choose(frame, chosen.target)
        if self._navigate(frame, text) or self._turn_page(frame, text, entries):
            return None
        if filterable:
            return self._set_filter(frame, text)
        return self._refuse()

    def _view_input(self, frame, text, raw_string):
        """
        A view menu claims only its own input. §3.9.

        Numbers, `?`, `b`, `q` and paging words are its own. In walk-away mode
        anything else closes the menu and runs as a command, which is what
        lets `north` or `say hi` follow `score` without a `q` in between.
        """
        entries = self._form_entries(frame)
        word = text.lower()
        if word.isdigit():
            chosen = _pick(_filtered(entries, frame.filter), word)
            if chosen is not None:
                return self.choose(frame, chosen.target)
            return self._refuse()
        if word in QUIT_WORDS or word in BACK_WORDS:
            return self._navigate(frame, word)
        if word[:1] == "?" or word in HELP_WORDS:
            return self._navigate(frame, text)
        if word in ("next", "prev", "previous") and self._turn_page(
                frame, word, entries):
            return None
        if not word:
            return self.say(self._choices_line(frame))

        if view_mode(self.caller) == WALK_AWAY:
            runner, session = self.caller, self._session
            self.close_menu(why="walked away")
            runner.execute_cmd(raw_string, session=session)
            return None
        if word in LOOK_WORDS:
            return self.display_nodetext()
        return self._refuse()

    def _set_filter(self, frame, text):
        frame.filter = text.strip()
        frame.page = 0
        self.refresh()

    def _field_input(self, frame, text):
        ctx, field = frame.ctx, frame.item
        escaped = text.startswith(ESCAPE) and len(text) > 1
        literal = text[1:] if escaped else text

        if field.kind in (CHOICE, BOOLEAN):
            entries = self._choice_entries(frame)
            if not escaped:
                if not text and frame.filter:
                    return self._set_filter(frame, "")
                chosen = _pick(_filtered(entries, frame.filter), text)
                if chosen is not None:
                    if chosen.target is MAKE_NEW:
                        return self._make_new(frame)
                    return self._set_field(frame, chosen.target.value)
                if (text.lower() in CLEAR_WORDS and not field.required
                        and field.is_set(ctx)):
                    return self._set_field(frame, None)
                if (self._navigate(frame, text)
                        or self._turn_page(frame, text, entries)):
                    return None
            if len(entries) > FILTER_FROM:
                return self._set_filter(frame, literal)
            return self._refuse()

        if not escaped:
            if self._navigate(frame, text):
                return None
            if text.lower() in CLEAR_WORDS and not field.required:
                return self._set_field(frame, None)
        if not literal:
            return self.display_nodetext()
        value, complaint = field.read(ctx, literal)
        if complaint:
            return self._refuse(complaint)
        return self._set_field(frame, value)

    def _enter(self, form, ctx, into=None):
        """Push a form, and its first question if it is a wizard."""
        base = _Frame("form", form, ctx, into=into)
        self.stack.append(base)
        if form.guided:
            first = form.unset_required(ctx)
            if first is not None:
                self.stack.append(self._field_frame(base, first))
        self.refresh()

    def _make_new(self, frame):
        """A picker's last entry: make one, and come back with it."""
        field = frame.item
        form = field.make_form(frame.ctx)
        if form is None:
            return self._refuse("There is no way to make one of those here.")
        child = frame.ctx.child(**(_call(field.make_data, frame.ctx, {}) or {}))
        child.draft = dict(_call(field.make_draft, frame.ctx, {}) or {})
        child.dirty = False
        return self._enter(form, child, into=("field", frame))

    def _answer(self, frame, picked, action=None):
        """
        An action supplied the value something further down was waiting for.

        Nothing waiting is not an error: a maker's form is the same form
        whether a picker opened it or `create kind` did, and answers with the
        same `Picked` either way. `_NOBODY_WAITING` says so, and the caller
        then treats the action as the ordinary action it is.
        """
        waiting = next((f.into for f in reversed(self.stack)
                        if f.into is not None), None)
        if waiting is None:
            return _NOBODY_WAITING
        target = waiting[1]
        try:
            at = self.stack.index(target)
        except ValueError:
            return _NOBODY_WAITING
        self.stack = self.stack[:at + 1]
        self.say(picked.said)
        if waiting[0] == "field":
            return self._set_field(target, picked.value)
        key, append = waiting[2], waiting[3]
        draft = target.ctx.draft
        if append:
            draft[key] = list(draft.get(key) or []) + [picked.value]
        else:
            draft[key] = picked.value
        target.ctx.dirty = True
        self.refresh()

    def _set_field(self, frame, value, confirmed=False):
        field, ctx = frame.item, frame.ctx
        asking = None if confirmed else field.confirmation(ctx, value)
        if asking and confirmation_wanted(self.caller, asking[0]):
            question = _Frame("confirm", frame.form, ctx)
            question.question = asking[1]
            question.pending = _Named(asking[0])
            question.pending_run = lambda: self._set_field(frame, value,
                                                           confirmed=True)
            self.stack.append(question)
            return self.refresh()
        PRESENTER.chose(self, field)
        self.say(field.store(ctx, value))
        if field.after == CLOSE:
            return self.close_menu(why="finished")
        self.stack.pop()
        base = self.top
        if base.kind == "form" and base.form.guided:
            following = base.form.unset_required(ctx)
            if following is not None:
                self.stack.append(self._field_frame(base, following))
        self.refresh()

    def _confirm_input(self, frame, text):
        word = text.lower()
        if word in ("2",) + YES_WORDS:
            PRESENTER.confirmed(self, _confirm_key(frame), True)
            self.stack.pop()
            return frame.pending_run()
        if word in ("1",) + NO_WORDS + QUIT_WORDS + BACK_WORDS:
            PRESENTER.confirmed(self, _confirm_key(frame), False)
            self.stack.pop()
            if frame.on_no is not None:
                return frame.on_no()
            self.say("Nothing changed.")
            if not self.stack:
                return self.close_menu()
            return self.refresh()
        if word in LOOK_WORDS or not word:
            return self.display_nodetext()
        return self._refuse("Choose 1 for no or 2 for yes.")

    def _help_input(self, frame, text):
        if self._navigate_minimal(text):
            return None
        chosen = _pick(self._helped_entries(frame), text)
        if chosen is None:
            return self._refuse()
        base = self._underlying(frame)
        self.stack.pop()
        self.say(f"|w{chosen.label}|n\n{chosen.target.help_for(base.ctx)}")
        self._redraw()

    def _navigate_minimal(self, text):
        word = text.lower()
        if word in QUIT_WORDS:
            self.quit()
        elif word in BACK_WORDS:
            self.stack.pop()
            self.refresh()
        elif word in LOOK_WORDS or not word:
            self.display_nodetext()
        else:
            return False
        return True

    # -- help ----------------------------------------------------------------

    def _ask_help(self, frame):
        if frame.kind == "field":
            helped = frame.item.help_for(frame.ctx)
            self.say(helped or "There is no more to say about this one.")
            return self._redraw()
        entries = self._helped_entries(frame)
        if not entries:
            return self.say("None of these has any help.")
        if len(entries) == 1:
            return self._explain(frame, entries[0].names[0])
        self.stack.append(_Frame("help", frame.form, frame.ctx))
        self.refresh()

    def _explain(self, frame, asked):
        base = self._underlying(frame)
        if frame.kind == "field" and not asked:
            return self._ask_help(frame)
        entries = self._form_entries(base)
        chosen = _pick(_filtered(entries, base.filter), asked)
        if chosen is None:
            return self._refuse(f"There is no choice called {asked} here.")
        helped = chosen.target.help_for(base.ctx)
        self.say(f"|w{chosen.label}|n\n{helped}" if helped
                 else f"There is no help for {strip_ansi(chosen.label)}.")
        self._redraw()

    def _redraw(self):
        """
        Show where the player is again, after help has been read.

        The help has pushed the choices up and away, and the next thing
        anybody wants is to choose. A view menu repeats only its choices line:
        its whole screen is what was just read past to ask.
        """
        frame = self.top
        if frame.kind == "form" and frame.form.kind == VIEW:
            return self.say(self._choices_line(frame))
        return self.refresh()

    # -- choosing ------------------------------------------------------------

    def _field_frame(self, base, field):
        return _Frame("field", base.form, base.ctx, item=field,
                      step=_step_of(base.form, base.ctx, field))

    def choose(self, frame, item):
        # A field reports being chosen when it is set, not when it is opened.
        if not isinstance(item, Field):
            PRESENTER.chose(self, item)
        if isinstance(item, Field):
            if item.kind == LONG_TEXT:
                return self._edit_at_length(frame, item)
            self.stack.append(self._field_frame(frame, item))
            return self.refresh()
        if isinstance(item, Submenu):
            child = item.context(frame.ctx)
            into = (("draft", frame, item.into, item.append)
                    if item.into else None)
            if item.prepare is None:
                return self._enter(item.form, child, into=into)

            def proceed():
                # The fetch may finish after the player has left the menu, or
                # moved elsewhere in it. Only enter if they are still here.
                if self.caller.ndb._evmenu is self and self.top is frame:
                    self._enter(item.form, child, into=into)

            return item.prepare(child, proceed, self._refuse)
        if isinstance(item, Action):
            if item.confirm is not None and confirmation_wanted(
                    self.caller, item.confirm):
                return self._ask_first(frame, item)
            return self.run_action(frame, item)
        return self._refuse()

    def _ask_first(self, frame, action):
        asking = _Frame("confirm", frame.form, frame.ctx)
        asking.question = action.question or (
            f"{strip_ansi(action.label_for(frame.ctx))}?")
        asking.pending = action
        asking.pending_run = lambda: self.run_action(frame, action)
        self.stack.append(asking)
        self.refresh()

    def run_action(self, frame, action):
        ctx = frame.ctx
        try:
            said = action.run(ctx)
        except Refuse as refusal:
            return self.say(str(refusal))
        if isinstance(said, Picked):
            answered = self._answer(frame, said, action)
            if answered is not _NOBODY_WAITING:
                return answered
            # Nothing was waiting, so the action behaves as it says it does:
            # a maker's form opened on its own closes when it is finished and
            # hands the value back when a picker opened it, which is one
            # action doing one thing in two places rather than two actions.
            said = said.said
        self.say(said)

        if action.after == CLOSE:
            command = action.command_for(ctx)
            if command and shows_commands(self.caller):
                self.say(f"Next time you can type |w{command}|n.")
            return self.close_menu(why="finished")
        if action.after == BACK:
            return self.back()
        if frame.form.kind == VIEW:
            # The result is what was asked for. Drawing the whole view again
            # under it would bury it, so a view only repeats its choices, and
            # only when it is holding input anyway.
            if view_mode(self.caller) == STAY_OPEN:
                self.say(self._choices_line(frame))
            return None
        return self.refresh()

    def _edit_at_length(self, frame, field):
        """
        Hand the screen to the line editor, and take the menu back afterwards.

        A menu cannot share the screen with EvEditor, so it closes and a new
        one opens on the same stack when the editor quits. Nothing is lost
        because the stack, and the draft in it, is handed across.
        """
        from evennia.utils.eveditor import EvEditor

        ctx = frame.ctx
        stack, runner, session = list(self.stack), self.caller, self._session
        writer = ctx.character or runner
        self._handing_on = "editor"
        self.close_menu(why="editor")

        def load(_caller):
            return field.value(ctx) or ""

        def save(_caller, buffer):
            field.store(ctx, buffer.strip() or None)
            return True

        def reopen(_caller):
            GameMenu(runner, stack, session=session, resumed=True)

        EvEditor(writer, loadfunc=load, savefunc=save, quitfunc=reopen,
                 key=strip_ansi(field.label_for(ctx)), persistent=False)

    # -- leaving -------------------------------------------------------------

    def back(self):
        frame = self.stack[-1]
        if len(self.stack) == 1:
            return self._leave(frame, "back")
        self.stack.pop()
        self.refresh()

    def quit(self):
        return self._leave(self.stack[0], "quit")

    def _leave(self, frame, why):
        dirty = any(f.ctx.dirty for f in self.stack if f.kind == "form")
        if (dirty and frame.form.kind == EDIT
                and confirmation_wanted(self.caller, "discard")):
            asking = _Frame("confirm", frame.form, frame.ctx)
            asking.question = frame.form.discard
            asking.pending_run = lambda: self.close_menu(why=why)
            asking.on_no = self.refresh
            self.stack.append(asking)
            return self.refresh()
        return self.close_menu(why=why)

    def close_menu(self, why="quit"):
        if self._quitting:
            return
        root = self.stack[0] if self.stack else None
        super().close_menu()
        if self._handing_on == "editor":
            # The menu comes back when the editor closes. Nothing has been
            # left, so nothing is told it has.
            return
        PRESENTER.closed(self, why)
        if root is not None and root.form.on_close is not None:
            root.form.on_close(root.ctx, why)
        if why in ("quit", "back") and not self._walks_away(root):
            # Said when the player closed it themselves, so they know every
            # menu is gone and what they type next is a command again. Not
            # for a finished action, which has already said what it did, nor
            # for a view menu that closes itself when they walk away.
            self.msg(CLOSED)

    def _walks_away(self, root):
        return (root is not None and root.kind == "form"
                and root.form.kind == VIEW
                and view_mode(self.caller) == WALK_AWAY)


class _Named:
    """Stands in for an action when a confirmation guards a value instead."""

    def __init__(self, confirm):
        self.confirm = confirm


def _confirm_key(frame):
    pending = frame.pending
    return getattr(pending, "confirm", None) if pending else "discard"


def _show_node(caller, raw_string, **kwargs):
    """EvMenu's only node: draw whatever is on top of the stack."""
    menu = caller.ndb._evmenu
    if not menu._opened:
        menu._opened = True
        if not menu._resumed:
            PRESENTER.opened(menu)
    return menu.render(), [{"key": "_default"}]


# ---------------------------------------------------------------------------
# Opening one
# ---------------------------------------------------------------------------

def open_menu(caller, form, session=None, draft=None, path=(),
              interactive_only=True, **data):
    """
    Show `form` to `caller`, or tell them what it needed if nobody is there.

    `path` is a sequence of choice names to go straight to, so a command given
    part of what it needs opens partway in -- and `b` still backs up through
    everything that was skipped. Returns the menu, or None when no menu was
    opened (a view form in `close` mode, or nobody connected).

    `interactive_only=False` opens one regardless of sessions, which is for
    tests.
    """
    ctx = Context(caller, session=session, draft=draft, **data)
    runner = ctx.account or caller

    if interactive_only and not interactive(runner):
        caller.msg(describe(form, ctx))
        return None

    if form.kind == VIEW and view_mode(runner) == CLOSE_VIEW:
        caller.msg(describe(form, ctx, heading=False))
        return None

    stack = [_Frame("form", form, ctx)]
    for name in path:
        frame = stack[-1]
        entries = [_Entry(item, item.label_for(frame.ctx), item.names())
                   for item in frame.form.items_for(frame.ctx)]
        chosen = _pick(entries, str(name))
        if chosen is None:
            break
        item = chosen.target
        if isinstance(item, Submenu):
            # Anything a submenu has to fetch first is the opener's to have
            # fetched; a path is followed in one go.
            stack.append(_Frame(
                "form", item.form, item.context(frame.ctx),
                into=(("draft", frame, item.into, item.append)
                      if item.into else None)))
        elif isinstance(item, Field) and item.kind != LONG_TEXT:
            stack.append(_Frame("field", frame.form, frame.ctx, item=item))
        else:
            break

    if len(stack) == 1 and form.guided:
        first = form.unset_required(ctx)
        if first is not None:
            stack.append(_Frame("field", form, ctx, item=first,
                                step=_step_of(form, ctx, first)))

    return GameMenu(runner, stack, session=session)


def describe(form, ctx, heading=True):
    """
    A form as words, for whoever cannot be shown it as a menu.

    What it is for, and every choice it offers as the command that reaches it.
    That is enough for an agent, a script or a player who turned view menus
    off to do anything the menu could have done.
    """
    lines = []
    if heading:
        lines.append(f"|w{form.title_for(ctx)}|n")
    intro = form.intro_for(ctx)
    if intro:
        lines.append(intro)
    commands = []
    for item in form.items_for(ctx):
        command = item.command_for(ctx)
        if command:
            commands.append((strip_ansi(item.label_for(ctx)), command))
    if commands:
        lines.append("")
        if form.kind == VIEW:
            lines.append(form.choices_line + " " + ", ".join(
                f"|w{command}|n" for _label, command in commands) + ".")
        else:
            lines += [f"  |w{command}|n: {label}" for label, command in commands]
    return "\n".join(lines)


def confirm(caller, question, on_yes, key=None, on_no=None, session=None,
            command=None, interactive_only=True):
    """
    Ask a yes/no before doing something, unless the player has said not to.

    For a command that has to ask outside any menu -- `delete world 2` typed
    in full. **No** is first, because what every command does today when you
    do not confirm is nothing. `key` names the confirmation setting; `command`
    is what to type with `yes` on the end to go ahead without being asked,
    which is what somebody with no session is told.
    """
    if key and not confirmation_wanted(caller, key):
        return on_yes()

    ctx = Context(caller, session=session)
    runner = ctx.account or caller
    if interactive_only and not interactive(runner):
        typed = f" Type |w{command} yes|n to go ahead." if command else ""
        caller.msg(f"{question}{typed}")
        return None

    action = Action("yes", "Yes", run=lambda _ctx: on_yes(), confirm=key,
                    question=question, after=CLOSE)
    holder = Form(key=f"confirm:{key or ''}", title="", items=[action])
    base = _Frame("form", holder, ctx)
    asking = _Frame("confirm", holder, ctx)
    asking.question = question
    asking.pending = action

    menu_ref = {}

    def yes():
        menu = menu_ref["menu"]
        menu.close_menu(why="finished")
        on_yes()

    def no():
        menu = menu_ref["menu"]
        menu.say("Nothing changed.")
        menu.close_menu(why="declined")
        if on_no is not None:
            on_no()

    asking.pending_run = yes
    asking.on_no = no
    menu = GameMenu(runner, [base, asking], session=session)
    menu_ref["menu"] = menu
    return menu
