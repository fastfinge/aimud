"""
The live half of `~`, and the helper that pays for live tests.

`FillingInForReal` is tagged `llm`: it asks a real model, with the key, address
and models of this machine's admin account (see `tests/live.py`), and costs a
little money each run. It is skipped wherever no admin has set a key. Run it
with `evennia test --settings settings.py --tag=llm tests.test_live_models`.

`ReadingTheAdmin` is free: it builds a throwaway database shaped like the
game's and reads that, so the helper is tested without anybody's key.
"""

import os
import sqlite3
import tempfile
from unittest import mock

from django.test import SimpleTestCase, tag

from tests import live
from tests.base import GameTest
from tests.support import immediately
from world import menus, suggesting


def _stored(value):
    """
    A plain value as an Evennia attribute stores it: a base64 pickle.

    Written out here rather than with `dbsafe_encode`, which looks up database
    models first -- and a unit test may not touch the database.
    """
    from base64 import b64encode
    from pickle import dumps

    from evennia.utils.picklefield import DEFAULT_PROTOCOL

    return b64encode(dumps(value, protocol=DEFAULT_PROTOCOL)).decode()


@tag("unit")
class ReadingTheAdmin(SimpleTestCase):

    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db3")
        os.close(handle)
        self.addCleanup(os.remove, self.path)
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        connection.executescript("""
            create table accounts_accountdb (id integer primary key,
                                             is_superuser integer);
            create table typeclasses_attribute (id integer primary key,
                db_key text, db_value text, db_category text);
            create table accounts_accountdb_db_attributes (
                accountdb_id integer, attribute_id integer);
            insert into accounts_accountdb values (1, 1), (2, 0);
        """)
        rows = [(1, "openrouter_api_key", "sk-admin", 1),
                (2, "ai_models", {"default": "a/model", "menus": "b/model"}, 1),
                (3, "ai_params", {"menus": {"temperature": 0.2}}, 1),
                (4, "openrouter_api_key", "sk-somebody-else", 2)]
        for attr_id, key, value, account in rows:
            connection.execute(
                "insert into typeclasses_attribute values (?, ?, ?, null)",
                (attr_id, key, _stored(value)))
            connection.execute(
                "insert into accounts_accountdb_db_attributes values (?, ?)",
                (account, attr_id))
        connection.commit()
        patcher = mock.patch.dict(os.environ, {"AIMUD_LIVE_DB": self.path})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_admins_key_and_not_anybody_elses(self):
        self.assertEqual(live.admin_provider()["key"], "sk-admin")

    def test_its_models_are_used_job_by_job(self):
        sponsor = live.LiveSponsor(live.admin_provider())
        self.assertEqual(sponsor.model_for("menus"), "b/model")
        self.assertEqual(sponsor.model_for("rooms"), "a/model")
        self.assertEqual(sponsor.model_for("menus").params,
                         {"temperature": 0.2})

    def test_with_no_address_set_it_is_the_default_one(self):
        from world import llm

        self.assertEqual(live.LiveSponsor(live.admin_provider()).base_url,
                         llm.BASE_URL.rstrip("/"))

    def test_nowhere_to_read_is_none(self):
        with mock.patch.dict(os.environ, {"AIMUD_LIVE_DB":
                                          self.path + ".missing"}):
            self.assertIsNone(live.admin_provider())


def a_ship(sponsor):
    """One field of every kind `~` can fill."""
    return menus.Form(
        key="ship", title="A ship", sponsor=lambda ctx: sponsor,
        intro="A trading ship in a world of drowned cities, where the sea "
              "has risen over everything.",
        items=[
            menus.Field("name", "Name", suggestible=True,
                        help="What the ship is called: a short proper name."),
            menus.Field("history", "History", kind=menus.LONG_TEXT,
                        suggestible=True,
                        help="Two or three sentences on where the ship has "
                             "been."),
            menus.Field("crew", "Crew", kind=menus.NUMBER, minimum=2,
                        maximum=12, suggestible=True,
                        help="How many people crew it."),
            menus.Field("armed", "Armed", kind=menus.BOOLEAN, suggestible=True,
                        help="Whether it carries weapons."),
            menus.Field("hull", "Hull", kind=menus.CHOICE, suggestible=True,
                        help="What the hull is made of.",
                        choices=[menus.Choice("wood", "Wood"),
                                 menus.Choice("iron", "Iron"),
                                 menus.Choice("reed", "Woven reed")]),
        ])


@tag("llm")
class FillingInForReal(GameTest):

    def setUp(self):
        super().setUp()
        self.sponsor = live.live_sponsor(self)
        self.form = a_ship(self.sponsor)
        self.ctx = menus.Context(self.char1)

    def fill(self, fields):
        got = []
        with immediately():
            suggesting.fill(self.ctx, self.form, fields,
                            on_done=lambda values: got.append(values),
                            on_error=lambda why: got.append(why))
        self.assertEqual(len(got), 1)
        self.assertIsInstance(got[0], dict, f"no values came back: {got[0]}")
        return got[0]

    def test_one_field_of_every_kind_in_one_conversation(self):
        values = self.fill(suggesting.fillable(self.ctx, self.form))
        self.assertTrue(values["name"].strip())
        self.assertTrue(values["history"].strip())
        self.assertIsInstance(values["crew"], (int, float))
        self.assertTrue(2 <= values["crew"] <= 12)
        self.assertIsInstance(values["armed"], bool)
        self.assertIn(values["hull"], ("wood", "iron", "reed"))

    def test_one_field_built_on_what_is_already_there(self):
        self.ctx.draft.update(name="The Heron", hull="reed")
        history = [field for field in suggesting.fillable(self.ctx, self.form)
                   if field.key == "history"]
        values = self.fill(history)
        self.assertEqual(list(values), ["history"])
        self.assertTrue(values["history"].strip())
