"""
Reaching a real model from a test, paid for by this machine's own admin.

Tests tagged `llm` talk to a real provider, so they need a key, an address and
a model. Rather than a separate file of secrets, they read what the admin
account of the local game already has set: `settings apikey`, `settings
apiurl` and `settings models`. Anywhere somebody has set the mud up to play or
develop on, the live tests can run; anywhere they have not, each one skips
itself and says why.

**The local game database, not the test one.** A test runs against a fresh
database with nobody in it, so the admin is read from `server/evennia.db3`
directly -- read-only, one query per value, and nothing is written back.
`AIMUD_LIVE_DB` points somewhere else when the game database lives elsewhere.

**Nothing here prints a key.** It is handed to the sponsor, and the sponsor
hands it to `world.llm`, which is the only thing that ever sends it.

Run them with `evennia test --settings settings.py --tag=llm tests`. They cost
money: a few small calls each.
"""

import os
import sqlite3
from pathlib import Path

from django.conf import settings


def game_database():
    """Where the local game keeps its database."""
    chosen = os.environ.get("AIMUD_LIVE_DB")
    if chosen:
        return Path(chosen)
    return Path(settings.GAME_DIR) / "server" / "evennia.db3"


_QUERY = """
    select a.db_value from typeclasses_attribute a
    join accounts_accountdb_db_attributes link on link.attribute_id = a.id
    join accounts_accountdb account on account.id = link.accountdb_id
    where account.is_superuser = 1 and a.db_key = ? and a.db_category is null
    order by account.id limit 1
"""


def _admin_attribute(connection, key):
    """One attribute of the admin account, decoded as Evennia stores it."""
    from evennia.utils.picklefield import dbsafe_decode

    row = connection.execute(_QUERY, (key,)).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return dbsafe_decode(row[0])
    except Exception:
        return None


def admin_provider():
    """
    {"key", "base_url", "models", "params"} from the local admin, or None.

    None when there is no game database here, no admin in it, or no key set.
    """
    path = game_database()
    if not path.exists():
        return None
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        key = _admin_attribute(connection, "openrouter_api_key")
        if not key:
            return None
        return {
            "key": str(key),
            "base_url": _admin_attribute(connection, "api_base_url") or "",
            "models": dict(_admin_attribute(connection, "ai_models") or {}),
            "params": dict(_admin_attribute(connection, "ai_params") or {}),
        }
    except sqlite3.Error:
        return None
    finally:
        connection.close()


class LiveSponsor:
    """
    A sponsor that pays with the local admin's own key, address and models.

    The same four answers as `tests.support.FakeSponsor`, read from the game
    instead of made up, so anything a generator does with a fake it does with
    this.
    """

    def __init__(self, provider):
        from world import llm

        self._provider = provider
        self.base_url = str(provider["base_url"] or llm.BASE_URL).rstrip("/")
        self.account = None
        self.actor = None
        self.world_root = None

    @property
    def payer(self):
        return None

    @property
    def answers(self):
        return True

    def key(self):
        return self._provider["key"]

    def model_for(self, *jobs):
        """The admin's choice for the first job that has one, as an account does."""
        from typeclasses.accounts import Account
        from world import model_params
        from world.model_params import ModelChoice

        models = self._provider["models"]
        chosen = next((models[job] for job in jobs if models.get(job)), None)
        chosen = chosen or models.get("default") or Account.DEFAULT_MODEL
        primary = jobs[0] if jobs else "default"
        stored = self._provider["params"]
        params = model_params.clean({**(stored.get("default") or {}),
                                     **(stored.get(primary) or {})})
        return ModelChoice(chosen, params, job=primary)


def live_sponsor(test):
    """A `LiveSponsor` for `test`, or skip the test saying what is missing."""
    provider = admin_provider()
    if provider is None:
        test.skipTest(f"No admin API key in the local game database at "
                      f"{game_database()}. Set one with settings apikey to "
                      f"run live tests.")
    return LiveSponsor(provider)
