"""
The settings command: one place for every preference, in and out of character.
"""

from commands.command import Command
from world import menus
from world import preferences

#: Typed on the end to answer a confirmation in advance.
CONFIRMED = ("yes", "confirm")


class CmdSettings(Command):
    """
    See and change your settings, and your world's.

    Usage:
      settings
      settings list
      settings <name>
      settings <name> <value>
      settings <name> default

    On its own it opens a menu of groups: General, Confirmations, API key and
    address, Models, and, inside a world, You in this world and (if you made
    it) This world. Each group lists its settings with what they are set to.

    |wsettings list|n prints every setting at once, with the name to type for
    each. |wsettings busy|n goes straight to one setting. |wsettings busy 30|n
    sets it without a menu, and |wsettings busy default|n puts it back.

    Groups and deeper menus can be named the same way:
    |wsettings models dialogue temperature 0.9|n.

    If a change needs a yes or no first, putting |wyes|n on the end answers
    it in advance: |wsettings mode always yes|n.

    Every setting has its own help: |whelp busy|n.
    """

    key = "settings"
    aliases = ["setting"]
    locks = "cmd:all()"
    help_category = "Account"
    account_caller = True

    def func(self):
        ctx = menus.Context(self.caller, session=self.session)
        words = self.args.split()
        if words and words[0].lower() == "list":
            self.caller.msg(preferences.listing(ctx))
            return
        self._walk(ctx, preferences.SETTINGS, words, [])

    # -- following what was typed -------------------------------------------

    def _walk(self, ctx, form, words, path):
        """
        Follow the words down through groups and submenus, one at a time.

        A group that needs something fetched first (the model list) is
        prepared before going further, which is why this continues from a
        callback rather than looping.
        """
        if not words:
            return self._open(path)

        word = words[0].lower()
        item = _named(form, ctx, word)
        if item is None and not path:
            # `settings busy` rather than `settings general busy`.
            found = _anywhere(ctx, word)
            if found is not None:
                group, item = found
                path = [group.key]
                form, ctx = group.form, group.context(ctx)
        if item is None:
            where = "" if not path else f" in {' '.join(path)}"
            self.caller.msg(f"There is no setting called |w{word}|n{where}. "
                            f"|wsettings list|n shows them all.")
            return None

        rest = words[1:]
        if isinstance(item, menus.Submenu):
            child = item.context(ctx)

            def proceed():
                self._walk(child, item.form, rest, path + [item.key])

            if item.prepare is not None:
                return item.prepare(child, proceed, self.caller.msg)
            return proceed()
        if isinstance(item, menus.Field):
            if not rest:
                return self._open(path + [item.key], field=(item, ctx))
            return self._set(ctx, item, rest, path)
        if isinstance(item, menus.Action):
            return self._act(ctx, item, rest, path)
        return None

    def _open(self, path, field=None):
        if menus.interactive(self.caller):
            return menus.open_menu(self.caller, preferences.SETTINGS,
                                   session=self.session, path=path)
        # Nobody to show a menu to: say it instead, in the words that would
        # change it.
        if field is None:
            ctx = menus.Context(self.caller, session=self.session)
            self.caller.msg(preferences.listing(ctx))
            return None
        item, ctx = field
        said = [f"|w{item.label_for(ctx)}|n: {item.shown(ctx)}"]
        helped = item.help_for(ctx)
        if helped:
            said.append(helped)
        said.append(f"Type |wsettings {self.args.strip()} <value>|n to change "
                    f"it.")
        self.caller.msg("\n".join(said))
        return None

    def _set(self, ctx, field, rest, path):
        answered = rest[-1].lower() in CONFIRMED and len(rest) > 1
        if answered:
            rest = rest[:-1]
        typed = " ".join(rest)

        if typed.lower() in ("default", "clear") and not field.required:
            value, complaint = None, ""
        else:
            value, complaint = field.read(ctx, typed)
        if complaint:
            self.caller.msg(complaint)
            return

        def do():
            try:
                said = field.store(ctx, value)
            except menus.Refuse as refusal:
                self.caller.msg(str(refusal))
                return
            self.caller.msg(said or f"{field.label_for(ctx)} is now "
                                    f"{field.shown(ctx)}.")

        asking = field.confirmation(ctx, value)
        if asking and not answered:
            key, question = asking
            command = f"settings {self.args.strip()}"
            menus.confirm(self.caller, question, do, key=key,
                          session=self.session, command=command)
            return
        do()

    def _act(self, ctx, action, rest, path):
        answered = bool(rest) and rest[-1].lower() in CONFIRMED

        def do():
            said = action.run(ctx)
            if said:
                self.caller.msg(said)

        if action.confirm and not answered:
            question = action.question or f"{action.label_for(ctx)}?"
            menus.confirm(self.caller, question, do, key=action.confirm,
                          session=self.session,
                          command=f"settings {self.args.strip()}")
            return
        do()


def _named(form, ctx, word):
    for item in form.items_for(ctx):
        if word in item.names():
            return item
    return None


def _anywhere(ctx, word):
    """(group, field) for a setting named anywhere in a group's own list."""
    for group in preferences.SETTINGS.items_for(ctx):
        child = group.context(ctx)
        # A job's own settings are not searched: they need a job, and are
        # reached through `settings models <job>`.
        for item in group.form.items_for(child):
            if isinstance(item, (menus.Field, menus.Action)) \
                    and word in item.names():
                return group, item
    return None
