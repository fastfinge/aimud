"""
Account-level commands available to all logged-in players.
"""

from evennia.accounts.accounts import DefaultAccount

from commands.command import Command


def _get_account(caller):
    return caller if isinstance(caller, DefaultAccount) else caller.account


def _mask_key(key):
    """Show only first 4 and last 4 characters of an API key."""
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + ("*" * (len(key) - 8)) + key[-4:]


class CmdApiKey(Command):
    """
    Manage your OpenRouter API key for AI content generation.

    Usage:
      apikey
      apikey set <key>
      apikey delete

    Your API key is stored on your account and used whenever you trigger
    AI content generation. Other players cannot see or use your key.

    Note: the key is transmitted as plain text when you type it. Connect
    over a secure connection and do not share your session.
    """

    key = "apikey"
    locks = "cmd:all()"
    help_category = "Account"
    account_caller = True

    def parse(self):
        parts = self.args.strip().split(None, 1)
        self.subcmd = parts[0].lower() if parts else ""
        self.value = parts[1].strip() if len(parts) > 1 else ""

    def func(self):
        account = _get_account(self.caller)

        if self.subcmd == "set":
            if not self.value:
                self.caller.msg("Usage: apikey set <key>")
                return
            account.db.openrouter_api_key = self.value
            self.caller.msg("OpenRouter API key saved.")

        elif self.subcmd == "delete":
            if account.db.openrouter_api_key:
                account.attributes.remove("openrouter_api_key")
                self.caller.msg("OpenRouter API key removed.")
            else:
                self.caller.msg("No API key is currently set.")

        elif self.subcmd == "":
            key = account.db.openrouter_api_key
            if key:
                self.caller.msg(f"OpenRouter API key is set: {_mask_key(key)}")
            else:
                self.caller.msg(
                    "No OpenRouter API key is set. Use |wapikey set <key>|n to add one."
                )

        else:
            self.caller.msg(f"Unknown subcommand '{self.subcmd}'. Use: apikey, apikey set <key>, apikey delete")


class CmdModels(Command):
    """
    Choose which AI model answers for each part of the game, and how.

    Usage:
      models
      models refresh

    Opens a menu with a screen for each job the game asks a model to do --
    room descriptions, NPC dialogue, deciding what a verb means, and so on.
    Each screen sets two things:

      |wthe model|n     picked from everything your OpenRouter key can reach.
      |wits settings|n  temperature, top P, the penalties, and whatever else
                    that particular model accepts.

    Every setting shows what it is currently at even when you have not
    touched it, and where that figure came from -- the model's own default,
    OpenRouter's, or something you set for |wdefault|n and inherited here. Only
    settings you changed yourself are sent; the rest are left out so the
    provider applies its own.

    This is what lets one world be tuned differently from another, and one job
    differently from the next: dialogue is usually better loose and surprising,
    while the rules that decide what an action does want to be dull and
    repeatable.

    Requires an API key (see |wapikey|n). Use |wmodels refresh|n to re-fetch
    the model list from OpenRouter.
    """

    key = "models"
    locks = "cmd:all()"
    help_category = "Account"
    account_caller = True

    def func(self):
        from commands.model_menu import start_model_menu

        if self.args.strip().lower() == "refresh":
            _get_account(self.caller).ndb.openrouter_models_cache = None
            self.caller.msg("Model cache cleared.")

        start_model_menu(self.caller)
