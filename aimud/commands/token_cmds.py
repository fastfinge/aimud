"""
The tokens command: the word lists a world keeps, and trying them out.

A sibling of `pronouns`. Anyone may read a world's lists -- the open sandbox
means a player can see what a description is choosing between -- and try a
piece of text to see what it comes to. Whoever made the world may add and
remove lists, which is the same line `worldedit` draws: only the worlds your
own account made.
"""

from commands.command import Command
from world import token_lists


class CmdTokens(Command):
    """
    The word lists this world keeps.

    Usage:
      tokens
      tokens <list>
      tokens try <text>
      tokens add <list> = <entry> | <entry> | ...
      tokens add <list>: <what it is for> = <entry> | <entry> | ...
      tokens remove <list>

    A description that says |w{smell}|n has one entry of the |wsmell|n list
    chosen for it, and keeps that choice, so it reads the same every time.

    |wtokens try|n shows what a piece of text comes to for you, here.
    |wtokens add|n and |wtokens remove|n are for whoever made this world.
    """

    key = "tokens"
    aliases = ["token", "wordlists"]
    locks = "cmd:all()"
    help_category = "General"

    def func(self):
        caller = self.caller
        room = caller.location
        world_root = room.db.world_root if room else None
        if world_root is None:
            caller.msg("You are not in a world that keeps word lists.")
            return

        args = self.args.strip()
        head, _, rest = args.partition(" ")
        head = head.lower()

        if not args:
            self._listing(caller, world_root)
        elif head == "try":
            self._try(caller, world_root, rest)
        elif head in ("add", "new"):
            if self._may_change(caller, world_root):
                self._add(caller, world_root, rest)
        elif head in ("remove", "delete"):
            if self._may_change(caller, world_root):
                self._remove(caller, world_root, rest)
        else:
            self._show(caller, world_root, args)

    def _listing(self, caller, world_root):
        kept = token_lists.vocabulary(world_root)
        if not kept:
            caller.msg("This world keeps no word lists yet. "
                       "|wtokens add|n makes one.")
            return
        lines = ["Word lists this world keeps:", ""]
        for name, entry in sorted(kept.items()):
            lines.append(f"  |w{{{name}}}|n — {token_lists.spelled(entry)} — "
                         f"{entry.get('means', '')}")
        lines += ["", "|wtokens <list>|n for one of them, |wtokens try <text>|n "
                      "to see what some text comes to."]
        caller.msg("\n".join(lines))

    def _show(self, caller, world_root, name):
        entry = token_lists.get(world_root, name)
        if entry is None:
            caller.msg(f"This world keeps no list called |w{name}|n.")
            return
        lines = [f"|w{{{name.lower()}}}|n — {entry.get('means', '')}",
                 f"Kept: {entry.get('scope')}"
                 + (f", as a condition in the group |w{entry['group']}|n"
                    if entry.get("group") else ""), ""]
        for item in entry["entries"]:
            weight = item.get("weight", 1)
            sets = (item.get("sets") or {}).get("states") or []
            lines.append(
                f"  {item['text']}"
                + (f"  (weight {weight:g})" if weight != 1 else "")
                + (f"  sets {', '.join(sets)}" if sets else ""))
        caller.msg("\n".join(lines))

    def _try(self, caller, world_root, text):
        from world import tokens

        if not text.strip():
            caller.msg("Try what? |wtokens try It smells of {smell}.|n")
            return
        shown = tokens.text(text, tokens.Context(
            viewer=caller, world_root=world_root, purpose="display"))
        caller.msg(f"That comes to: {shown}")

    def _may_change(self, caller, world_root):
        from world import sponsor

        account = getattr(caller, "account", None)
        if account is not None and (account.is_superuser
                                    or sponsor.creator_of(world_root) == account):
            return True
        caller.msg("Only whoever made this world can change its word lists.")
        return False

    def _add(self, caller, world_root, rest):
        left, sep, right = rest.partition("=")
        name, _, means = left.partition(":")
        name = name.strip().lower()
        entries = [part.strip() for part in right.split("|") if part.strip()]
        if not sep or not name or not entries:
            caller.msg("Usage: |wtokens add <list> = <entry> | <entry>|n")
            return
        used = token_lists.register(world_root, name, {
            "means": means.strip() or f"a word list called {name}",
            "entries": entries,
        })
        if not used:
            caller.msg(f"|w{name}|n could not be kept. A list needs a name "
                       f"nothing else here uses, and entries that finish.")
        elif used != name:
            caller.msg(f"This world already keeps |w{used}|n, which is the "
                       f"same list. Nothing changed.")
        else:
            caller.msg(f"This world now keeps |w{{{used}}}|n.")

    def _remove(self, caller, world_root, name):
        removed, complaint = token_lists.unregister(world_root, name.strip())
        caller.msg(f"|w{name.strip()}|n is gone." if removed else complaint)
