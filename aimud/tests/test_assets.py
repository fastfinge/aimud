"""
Assets: the register, the store, the types and the one writer.
docs/archived/assets.md, phase 0.

Every test keeps its files in a temporary store, so nothing here touches the
real media folder, and a stray file from one test cannot satisfy another.
"""

import json
import shutil
import tempfile
from unittest import mock

from django.test import SimpleTestCase, override_settings, tag

from tests.base import GameTest
from world import asset_store, asset_types, assets


def world_doc(**extra):
    """The smallest file the `world` type accepts as one."""
    doc = {"aimud": 1, "kind": "world", "setup": {"title": "The School"}}
    doc.update(extra)
    return json.dumps(doc).encode("utf-8")


class _Stored(GameTest):
    """A temporary store, and an account to charge."""

    accounts = True

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp(prefix="aimud-assets-")
        previous = asset_store.use(asset_store.LocalStore(self.folder))
        self.addCleanup(asset_store.use, previous)
        self.addCleanup(shutil.rmtree, self.folder, True)

    def add(self, data=None, **kwargs):
        given = dict(name="The School", description="A haunted school.",
                     added_by=self.account, origin="upload")
        given.update(kwargs)
        return assets.add_bytes(world_doc() if data is None else data, **given)


@tag("world")
class AddingOne(_Stored):

    def test_a_world_document_is_kept(self):
        asset, said = self.add()
        self.assertEqual(asset.type, "world")
        self.assertEqual(asset.version, "1")
        self.assertEqual(asset.charged_to, self.account)
        self.assertEqual(asset.added_by, self.account)
        self.assertIn("is kept", said)
        self.assertTrue(asset_store.store().exists(asset.hash, "json"))

    def test_by_the_hash_of_what_is_in_it(self):
        import hashlib

        asset, _said = self.add()
        self.assertEqual(asset.hash, hashlib.sha256(world_doc()).hexdigest())
        with assets.opened(asset) as handle:
            self.assertEqual(handle.read(), world_doc())

    def test_the_same_file_twice_is_one_asset(self):
        first, _said = self.add()
        again, said = self.add(name="Another name", added_by=self.account2)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(again.name, "The School")
        self.assertIn("costs you nothing", said)
        self.assertEqual(assets.used_by(self.account2), 0)

    def test_a_name_and_a_description_are_required(self):
        with self.assertRaises(assets.Refused) as caught:
            self.add(name="  ", description="")
        said = " ".join(caught.exception.complaints)
        self.assertIn("needs a name", said)
        self.assertIn("needs a description", said)


@tag("world")
class WhatAFileIs(_Stored):
    """By its contents, never its name. docs/archived/assets.md 4."""

    def test_something_that_is_not_a_kind_this_server_keeps(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 40
        with self.assertRaises(assets.Refused) as caught:
            self.add(png)
        self.assertIn("not a kind of file this server keeps",
                      str(caught.exception))

    def test_json_that_is_not_a_world(self):
        with self.assertRaises(assets.Refused) as caught:
            self.add(json.dumps({"kind": "ruleset", "aimud": 1}).encode())
        self.assertIn("not a world", str(caught.exception))

    def test_something_that_only_starts_like_json(self):
        with self.assertRaises(assets.Refused) as caught:
            self.add(b"{ this is not json")
        self.assertIn("not JSON", str(caught.exception))

    def test_a_world_from_a_later_aimud_is_refused_by_number(self):
        with self.assertRaises(assets.Refused) as caught:
            self.add(world_doc(aimud=99))
        self.assertIn("written by aimud 99", str(caught.exception))

    def test_a_file_bigger_than_its_type_allows(self):
        with mock.patch("world.exchange.MOST_BYTES", 10):
            with self.assertRaises(assets.Refused) as caught:
                self.add()
        self.assertIn("the most a world file may be", str(caught.exception))

    def test_a_refusal_never_names_a_path(self):
        try:
            self.add(b"{ nope")
        except assets.Refused as refusal:
            said = str(refusal)
        self.assertNotIn(self.folder, said)
        self.assertNotIn("tmp", said.lower())


@tag("world")
class Quotas(_Stored):
    """Charged once, to whoever paid for it to exist. docs/archived/assets.md 7."""

    def test_an_account_uses_what_it_is_charged_for(self):
        asset, _said = self.add()
        self.assertEqual(assets.used_by(self.account), asset.size)

    @override_settings(ASSET_QUOTA=10)
    def test_a_file_that_would_go_over_is_refused_and_says_how_much_is_left(self):
        with self.assertRaises(assets.Refused) as caught:
            self.add()
        self.assertIn("left", str(caught.exception))
        self.assertFalse(assets._model().objects.exists())

    @override_settings(ASSET_QUOTA=10)
    def test_an_admin_can_give_one_account_more(self):
        self.account.db.asset_quota = 10 * 1024
        asset, _said = self.add()
        self.assertEqual(asset.charged_to, self.account)

    @override_settings(ASSET_QUOTA=None)
    def test_no_limit_at_all(self):
        self.assertEqual(assets.room_for(self.account, 10 ** 12), "")

    def test_a_tool_s_file_is_charged_to_whoever_paid_for_the_call(self):
        asset, _said = self.add(origin="tool", charged_to=self.account2)
        self.assertEqual(asset.added_by, self.account)
        self.assertEqual(asset.charged_to, self.account2)
        self.assertEqual(assets.used_by(self.account), 0)

    def test_a_missing_asset_brought_back_is_charged_to_whoever_brought_it(self):
        asset, _said = self.add()
        asset.status, asset.charged_to = "missing", None
        asset.save()
        asset_store.store().delete(asset.hash, "json")

        again, said = self.add(added_by=self.account2)
        self.assertEqual(again.pk, asset.pk)
        self.assertEqual(again.status, "present")
        self.assertEqual(again.charged_to, self.account2)
        self.assertIn("is back", said)


@tag("unit")
class TheTypes(SimpleTestCase):

    def test_no_registered_type_is_code(self):
        for key, found in asset_types.every().items():
            self.assertNotIn(found.extension, asset_types.NEVER, key)

    def test_a_type_that_is_code_cannot_be_registered(self):
        class Script(asset_types.AssetType):
            key, extension = "script", "py"

        with self.assertRaises(ValueError):
            asset_types.register(Script())

    def test_nor_can_a_second_type_take_a_key(self):
        class Impostor(asset_types.AssetType):
            key, extension = "world", "txt"

        with self.assertRaises(ValueError):
            asset_types.register(Impostor())

    def test_a_world_is_recognised_by_its_first_bytes(self):
        self.assertTrue(asset_types.get("world").sniff(b'\n  {"aimud": 1'))
        self.assertFalse(asset_types.get("world").sniff(b"GIF89a"))


@tag("unit")
class TheStore(SimpleTestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="aimud-store-")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.store = asset_store.LocalStore(self.folder)

    def test_a_file_is_named_by_its_hash_and_type(self):
        self.store.put("abc123", "json", b"{}")
        self.assertTrue(self.store.exists("abc123", "json"))
        self.assertEqual(self.store.url("abc123", "json"),
                         "/media/assets/abc123.json")

    def test_keeping_a_file_twice_is_not_an_error(self):
        self.store.put("abc123", "json", b"{}")
        self.store.put("abc123", "json", b"{}")
        with self.store.open("abc123", "json") as handle:
            self.assertEqual(handle.read(), b"{}")

    def test_forgetting_one_that_is_not_there_is_not_an_error(self):
        self.store.delete("nothing", "json")

    def test_nothing_is_left_half_written(self):
        import os

        self.store.put("abc123", "json", b"{}")
        self.assertEqual(os.listdir(self.folder), ["abc123.json"])


@tag("world")
class WhereItCanBeFetched(_Stored):

    def test_nowhere_until_the_server_knows_its_own_address(self):
        asset, _said = self.add()
        self.assertEqual(assets.public_url(asset), "")

    def test_and_then_by_hash(self):
        asset, _said = self.add()
        with override_settings(ASSET_BASE_URL="https://mud.example.com:4001/"):
            self.assertEqual(
                assets.public_url(asset),
                f"https://mud.example.com:4001/media/assets/{asset.hash}.json")


class _Sound(asset_types.AssetType):
    """A stand-in type for these tests: something a world can be using."""

    key, label, extension, most_bytes = "testsound", "A test sound", "snd", 1000
    using = {}

    def sniff(self, head):
        return bytes(head).startswith(b"SOUND")

    def check(self, path):
        return "1", ""

    def uses(self, asset):
        return list(self.using.get(asset.hash, []))


class _WithSounds(_Stored):
    """`room1` is a world `account` made; sounds can be made in use by it."""

    characters = 2

    def setUp(self):
        super().setUp()
        from world import sponsor

        self.sound_type = asset_types.register(_Sound())
        _Sound.using = {}
        self.addCleanup(asset_types._types.pop, "testsound", None)
        self.room1.db.world_root = self.room1
        sponsor.claim(self.room1, self.account)

    def sound(self, body=b"", size=100, by=None, **kwargs):
        data = b"SOUND" + body + b"x" * max(size - 5 - len(body), 0)
        given = dict(name=f"sound {body.decode() or 'one'}",
                     description="A sound.", added_by=by or self.account2,
                     origin="upload")
        given.update(kwargs)
        asset, _said = assets.add_bytes(data, **given)
        return asset

    def used_here(self, asset):
        _Sound.using[asset.hash] = [{"said": "The School", "world": self.room1}]


@tag("world")
class Naming(_WithSounds):

    def test_by_name(self):
        rain = self.sound(b"rain", name="rain")
        self.assertEqual(assets.named("Rain")[0], rain)

    def test_by_part_of_a_name(self):
        rain = self.sound(b"rain", name="heavy rain at night")
        self.assertEqual(assets.named("rain at")[0], rain)

    def test_two_with_one_name_are_told_apart_by_hash(self):
        first = self.sound(b"a", name="rain")
        self.sound(b"b", name="rain")
        found, why = assets.named("rain")
        self.assertIsNone(found)
        self.assertIn(first.hash[:8], why)
        self.assertEqual(assets.named(first.hash[:8])[0], first)


@tag("world")
class Deleting(_WithSounds):

    def test_an_unused_asset_goes_with_its_file(self):
        rain = self.sound(b"rain")
        assets.delete(rain)
        self.assertIsNone(assets.find(rain.hash))
        self.assertFalse(asset_store.store().exists(rain.hash, "snd"))

    def test_one_in_use_is_refused_and_says_by_what(self):
        rain = self.sound(b"rain")
        self.used_here(rain)
        with self.assertRaises(assets.Refused) as caught:
            assets.delete(rain)
        self.assertIn("The School", str(caught.exception))

    def test_forced_it_is_missing_where_it_was_used(self):
        rain = self.sound(b"rain")
        self.used_here(rain)
        assets.delete(rain, force=True)
        rain.refresh_from_db()
        self.assertEqual(rain.status, "missing")
        self.assertFalse(asset_store.store().exists(rain.hash, "snd"))


@tag("world")
class GivingUp(_WithSounds):
    """docs/archived/assets.md 7.1."""

    def test_it_stops_counting_against_whoever_gave_it_up(self):
        rain = self.sound(b"rain")
        assets.give_up(self.account2, rain)
        self.assertIsNone(assets.find(rain.hash).charged_to)
        self.assertEqual(assets.used_by(self.account2), 0)
        self.assertEqual(assets.pool_used(), rain.size)

    def test_only_by_whoever_is_charged(self):
        rain = self.sound(b"rain")
        with self.assertRaises(assets.Refused):
            assets.give_up(self.account, rain)

    @override_settings(ASSET_POOL_QUOTA=50)
    def test_nothing_bigger_than_the_whole_pool(self):
        rain = self.sound(b"rain")
        with self.assertRaises(assets.Refused) as caught:
            assets.give_up(self.account2, rain)
        self.assertIn("more than the server keeps", str(caught.exception))

    @override_settings(ASSET_POOL_QUOTA=250)
    def test_a_full_pool_lets_the_least_used_go_first(self):
        unused = self.sound(b"unused")
        used = self.sound(b"used")
        self.used_here(used)
        assets.give_up(self.account2, unused)
        assets.give_up(self.account2, used)
        newest = self.sound(b"newest")
        assets.give_up(self.account2, newest)

        self.assertEqual(assets.find(unused.hash).status, "missing")
        self.assertEqual(assets.find(used.hash).status, "present")
        self.assertEqual(assets.find(newest.hash).status, "present")
        self.assertFalse(asset_store.store().exists(unused.hash, "snd"))

    @override_settings(ASSET_POOL_QUOTA=150)
    def test_never_the_one_being_given_up(self):
        old = self.sound(b"old")
        self.used_here(old)
        assets.give_up(self.account2, old)
        new = self.sound(b"new")
        assets.give_up(self.account2, new)
        self.assertEqual(assets.find(new.hash).status, "present")
        self.assertEqual(assets.find(old.hash).status, "missing")

    @override_settings(ASSET_POOL_QUOTA=250)
    def test_ties_go_to_whatever_was_used_longest_ago(self):
        from datetime import timedelta

        from django.utils import timezone

        stale = self.sound(b"stale")
        fresh = self.sound(b"fresh")
        now = timezone.now()
        assets.touch(stale, now=now - timedelta(days=30))
        assets.touch(fresh, now=now)
        assets.give_up(self.account2, fresh)
        assets.give_up(self.account2, stale)
        assets.give_up(self.account2, self.sound(b"third"))
        self.assertEqual(assets.find(stale.hash).status, "missing")
        self.assertEqual(assets.find(fresh.hash).status, "present")


@tag("world")
class Adopting(_WithSounds):

    def test_a_given_up_asset_comes_onto_your_quota(self):
        rain = self.sound(b"rain")
        assets.give_up(self.account2, rain)
        assets.adopt(self.account, rain)
        self.assertEqual(assets.find(rain.hash).charged_to, self.account)
        self.assertEqual(assets.pool_used(), 0)

    def test_not_one_that_is_somebody_elses(self):
        rain = self.sound(b"rain")
        with self.assertRaises(assets.Refused):
            assets.adopt(self.account, rain)

    @override_settings(ASSET_QUOTA=10)
    def test_not_past_your_quota(self):
        rain = self.sound(b"rain", charged_to=None)
        with self.assertRaises(assets.Refused) as caught:
            assets.adopt(self.account, rain)
        self.assertIn("left", str(caught.exception))


@tag("world")
class WarningOwners(_WithSounds):
    """The creator of a world using a given-up asset hears about it. 7.1."""

    def setUp(self):
        super().setUp()
        self.heard = []
        self.account.msg = lambda text="", **kw: self.heard.append(str(text))

    def test_when_it_is_given_up_while_they_are_here(self):
        from tests import support

        support.logged_in(self, self.account)
        rain = self.sound(b"rain")
        self.used_here(rain)
        assets.give_up(self.account2, rain)
        said = " ".join(self.heard)
        self.assertIn("given up", said)
        self.assertIn(f"edit asset {rain.hash[:8]} adopt", said)

    def test_or_at_their_next_login(self):
        rain = self.sound(b"rain")
        self.used_here(rain)
        assets.give_up(self.account2, rain)
        self.assertEqual(self.heard, [])
        self.assertEqual(assets.deliver_notices(self.account), 1)
        self.assertIn("While you were away", self.heard[-1])
        self.assertEqual(assets.deliver_notices(self.account), 0)

    @override_settings(ASSET_POOL_QUOTA=150)
    def test_when_it_has_gone(self):
        rain = self.sound(b"rain")
        self.used_here(rain)
        assets.give_up(self.account2, rain)
        assets.give_up(self.account2, self.sound(b"other"))
        notices = " ".join(self.account.db.asset_notices or [])
        self.assertIn("removed to make room", notices)

    def test_a_world_that_does_not_use_it_hears_nothing(self):
        rain = self.sound(b"rain")
        assets.give_up(self.account2, rain)
        self.assertFalse(self.account.db.asset_notices)

    @override_settings(ASSET_POOL_QUOTA=1000)
    def test_next_in_line_is_said_once(self):
        rain = self.sound(b"rain", size=800)
        self.used_here(rain)
        assets.give_up(self.account2, rain)
        self.account.attributes.remove("asset_notices")
        assets.give_up(self.account2, self.sound(b"a", size=150))
        first = list(self.account.db.asset_notices or [])
        assets.give_up(self.account2, self.sound(b"b", size=20))
        again = list(self.account.db.asset_notices or [])
        self.assertTrue(any("next in line" in said for said in first), first)
        self.assertEqual(sum("next in line" in said for said in again), 1)


@tag("unit")
class Sizes(SimpleTestCase):

    def test_sizes_are_read_as_people_write_them(self):
        self.assertEqual(assets.read_size("750MB"), 750 * 1024 ** 2)
        self.assertEqual(assets.read_size("2 gb"), 2 * 1024 ** 3)
        self.assertEqual(assets.read_size("500k"), 500 * 1024)
        self.assertEqual(assets.read_size("300"), 300 * 1024 ** 2)
        self.assertEqual(assets.read_size("default"), "default")

    def test_and_something_that_is_not_one_is_refused(self):
        with self.assertRaises(assets.Refused):
            assets.read_size("lots")

    def test_and_said_as_people_say_them(self):
        self.assertEqual(assets.size_said(2 * 1024 ** 2), "2.0 MB")
        self.assertEqual(assets.size_said(1), "1 byte")


class _Typed(_WithSounds):
    """The commands, as a player types them."""

    def setUp(self):
        super().setUp()
        self.heard = []
        self.char1.msg = lambda text="", **kw: self.heard.append(
            str(text[0] if isinstance(text, tuple) else text))
        # Evennia's fixture accounts are Developers, which outranks Admin.
        # These are players; a test that wants an admin says so.
        for account in (self.account, self.account2):
            account.permissions.remove("Developer")

    def admin(self):
        self.account.permissions.add("Admin")

    def type(self, verb, args):
        from commands import verbs

        command = {"view": verbs.CmdView, "edit": verbs.CmdEdit,
                   "delete": verbs.CmdDelete, "create": verbs.CmdCreate}[verb]()
        command.caller = self.char1
        command.session = None
        command.args = " " + args
        command.cmdstring = verb
        command.raw_string = f"{verb} {args}"
        command.cmdset = None
        command.obj = self.char1
        command.account = self.account
        self.heard.clear()
        command.func()
        return "\n".join(self.heard)


@tag("world")
class TypingIt(_Typed):

    def test_view_assets_opens_with_your_quota(self):
        self.sound(b"rain", name="rain", by=self.account)
        said = self.type("view", "assets")
        self.assertIn("You are using", said)
        self.assertIn("rain", said)

    def test_one_in_full(self):
        rain = self.sound(b"rain", name="rain", author="Somebody",
                          licence="CC-BY 4.0")
        said = self.type("view", "asset rain")
        self.assertIn("CC-BY 4.0", said)
        self.assertIn(rain.hash[:12], said)

    def test_never_a_path(self):
        self.sound(b"rain", name="rain", by=self.account)
        for said in (self.type("view", "assets"), self.type("view", "asset rain")):
            self.assertNotIn(self.folder, said)
            self.assertNotIn(".media", said)
            self.assertNotIn("server/", said)

    def test_changing_a_description_in_a_line(self):
        rain = self.sound(b"rain", name="rain", by=self.account)
        self.type("edit", "asset rain description Steady rain on a tin roof.")
        self.assertEqual(assets.find(rain.hash).description,
                         "Steady rain on a tin roof.")

    def test_not_somebody_elses(self):
        self.sound(b"rain", name="rain", by=self.account2)
        said = self.type("edit", "asset rain description Mine now.")
        self.assertIn("Only whoever it belongs to", said)

    def test_giving_one_up(self):
        rain = self.sound(b"rain", name="rain", by=self.account)
        self.type("edit", "asset rain giveup yes")
        self.assertIsNone(assets.find(rain.hash).charged_to)

    def test_adopting_one(self):
        rain = self.sound(b"rain", name="rain", charged_to=None)
        self.type("edit", "asset rain adopt")
        self.assertEqual(assets.find(rain.hash).charged_to, self.account)

    def test_deleting_one(self):
        rain = self.sound(b"rain", name="rain", by=self.account)
        self.type("delete", "asset rain yes")
        self.assertIsNone(assets.find(rain.hash))

    def test_one_in_use_suggests_giving_it_up(self):
        rain = self.sound(b"rain", name="rain", by=self.account)
        self.used_here(rain)
        said = self.type("delete", "asset rain yes")
        self.assertIn("giveup", said)
        self.assertIsNotNone(assets.find(rain.hash))

    def test_forcing_is_for_admins(self):
        rain = self.sound(b"rain", name="rain", by=self.account)
        self.used_here(rain)
        self.assertIn("Only an admin",
                      self.type("delete", "asset rain force yes"))

    def test_reviewing_is_for_admins(self):
        self.assertIn("for admins", self.type("view", "assets recent"))

    def test_and_an_admin_reviews(self):
        self.sound(b"rain", name="rain")
        self.admin()
        said = self.type("view", "assets recent")
        self.assertIn("rain", said)
        self.assertIn(self.account2.key, said)

    def test_a_quota_is_set_by_an_admin(self):
        self.assertIn("for admins", self.type("edit", f"quota {self.account2.key} 2GB"))
        self.admin()
        self.type("edit", f"quota {self.account2.key} 2GB")
        self.assertEqual(assets.quota_of(self.account2), 2 * 1024 ** 3)
        self.type("edit", f"quota {self.account2.key} default")
        self.assertEqual(assets.quota_of(self.account2),
                         assets.quota_of(self.account))


@tag("world")
class FetchingFromTheCommand(_Typed):
    """`create asset`'s save: fetched in a thread, kept on the main one."""

    def keep(self, fetched):
        from twisted.internet import defer

        from commands import assets_subject

        def now(function, *args):
            return defer.maybeDeferred(function, *args)

        with mock.patch("twisted.internet.threads.deferToThread", now), \
                mock.patch.object(assets, "fetch", fetched):
            assets_subject.fetch_and_add(self.char1, "https://example.com/w",
                                         "The School", "A haunted school.")
        return "\n".join(self.heard)

    def test_a_fetched_file_is_kept_and_its_source_remembered(self):
        def fetched(url, most):
            handle, path = tempfile.mkstemp()
            with open(handle, "wb") as out:
                out.write(world_doc())
            return path

        said = self.keep(fetched)
        self.assertIn("is kept", said)
        asset = assets.search("world").first()
        self.assertEqual(asset.source, "https://example.com/w")
        self.assertEqual(asset.origin, "url")

    def test_a_refused_fetch_says_why(self):
        def fetched(url, most):
            raise assets.Refused(["that address is inside a private network"])

        self.assertIn("private network", self.keep(fetched))
        self.assertFalse(assets.search().exists())


@tag("world")
class SeenInViewWorld(_WithSounds):

    def test_a_given_up_asset_the_world_uses_is_listed_with_how_to_keep_it(self):
        from commands.world_subject import _world_detail

        rain = self.sound(b"rain", name="rain")
        self.used_here(rain)
        self.assertNotIn("given up", _world_detail(self.room1, 1, 1))
        assets.give_up(self.account2, rain)
        said = _world_detail(self.room1, 1, 1)
        self.assertIn("rain", said)
        self.assertIn(f"edit asset {rain.hash[:8]} adopt", said)


class _Carrying(_WithSounds):
    """A document naming sounds, and a fetch that answers from a table."""

    def setUp(self):
        super().setUp()
        self.served = {}
        self.fetched = []
        from twisted.internet import defer

        def now(function, *args):
            return defer.maybeDeferred(function, *args)

        def fetch(url, most):
            self.fetched.append(url)
            if url not in self.served:
                raise assets.Refused(["it could not be reached"])
            handle, path = tempfile.mkstemp()
            with open(handle, "wb") as out:
                out.write(self.served[url])
            return path

        for patcher in (mock.patch("twisted.internet.threads.deferToThread", now),
                        mock.patch.object(assets, "fetch", fetch)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def entry(self, data, name="rain", url="https://elsewhere.example/rain"):
        import hashlib

        return {"name": name, "type": "testsound",
                "hash": hashlib.sha256(data).hexdigest(), "size": len(data),
                "url": url, "description": "Rain on a tin roof.",
                "author": "Somebody", "licence": "CC-BY 4.0"}

    def bring(self, *entries, account=None):
        result = []
        assets.bring_in({"assets": list(entries)}, account or self.account,
                        result.append)
        return result[0]


@tag("world")
class CarriedByAWorld(_Carrying):
    """docs/archived/assets.md 9."""

    def test_an_asset_this_server_has_is_not_fetched(self):
        rain = self.sound(b"rain")
        with assets.opened(rain) as handle:
            data = handle.read()
        self.assertEqual(self.bring(self.entry(data)), [])
        self.assertEqual(self.fetched, [])

    def test_one_it_has_not_is_fetched_and_charged_to_the_importer(self):
        data = b"SOUND rain on a tin roof"
        self.served["https://elsewhere.example/rain"] = data
        self.assertEqual(self.bring(self.entry(data)), [])
        asset = assets.search("testsound").first()
        self.assertEqual(asset.charged_to, self.account)
        self.assertEqual(asset.origin, "import")
        self.assertEqual(asset.licence, "CC-BY 4.0")
        self.assertEqual(asset.source, "https://elsewhere.example/rain")

    def test_a_file_that_is_not_the_one_named_is_missing(self):
        data = b"SOUND rain on a tin roof"
        self.served["https://elsewhere.example/rain"] = b"SOUND something else"
        problems = self.bring(self.entry(data))
        self.assertIn("not the file the world named", problems[0])
        asset = assets.find(self.entry(data)["hash"])
        self.assertEqual(asset.status, "missing")
        self.assertFalse(assets.search("testsound").exists())

    def test_one_that_cannot_be_reached_is_missing_and_says_why(self):
        problems = self.bring(self.entry(b"SOUND gone"))
        self.assertIn("could not be reached", problems[0])
        asset = assets.find(self.entry(b"SOUND gone")["hash"])
        self.assertEqual(asset.status, "missing")
        self.assertEqual(asset.source, "https://elsewhere.example/rain")

    def test_and_can_be_fetched_again_once_its_server_is_back(self):
        data = b"SOUND back again"
        self.bring(self.entry(data))
        missing = assets.find(self.entry(data)["hash"])
        self.served["https://elsewhere.example/rain"] = data
        said = []
        assets.fetch_again(self.account2, missing, said.append)
        self.assertEqual(said, [""])
        missing.refresh_from_db()
        self.assertEqual(missing.status, "present")
        self.assertEqual(missing.charged_to, self.account2)

    @override_settings(ASSET_QUOTA=10)
    def test_an_import_that_would_overrun_the_quota_says_so_first(self):
        doc = {"assets": [self.entry(b"SOUND " + b"x" * 100)]}
        refused = assets.room_to_bring(doc, self.account)
        self.assertIn("of your quota", refused)

    def test_a_broken_entry_is_refused_when_the_document_is_checked(self):
        self.assertTrue(assets.entry_problems([{"name": "x", "type": "nope"}]))
        self.assertEqual(assets.entry_problems([self.entry(b"SOUND")]), [])


@tag("world")
class ListedByItsWorld(_Carrying):

    def test_a_world_lists_the_assets_it_uses(self):
        rain = self.sound(b"rain", name="rain")
        _Sound.used_in = lambda self_, root: [rain] if root == self.room1 else []
        self.addCleanup(delattr, _Sound, "used_in")
        listed = assets.listed(self.room1)
        self.assertEqual([entry["hash"] for entry in listed], [rain.hash])
        self.assertNotIn("path", listed[0])

    def test_a_world_using_none_exports_as_it_always_did(self):
        from world import exchange

        with mock.patch.object(assets, "listed", return_value=[]):
            self.assertNotIn("assets", exchange.document(self.room1))


@tag("world")
class ForAModel(_WithSounds):
    """`list_assets` and `show_asset`. docs/archived/assets.md 10."""

    def ask(self, name, **args):
        from world import toolbox as tb

        tool = {found.name: found for found in assets.lookup_tools()}[name]
        heard = []
        tool.handler(tb.ToolContext(), args, heard.append)
        return heard[0]

    def test_listing_gives_ids_and_descriptions(self):
        rain = self.sound(b"rain", name="rain", description="Rain on tin.")
        said = self.ask("list_assets")
        self.assertIn(rain.hash[:12], said)
        self.assertIn("Rain on tin.", said)

    def test_by_type_and_by_words(self):
        self.sound(b"rain", name="rain", description="Rain on tin.")
        self.add()
        self.assertNotIn("rain", self.ask("list_assets", type="world"))
        self.assertIn("rain", self.ask("list_assets", query="tin"))

    def test_one_in_full(self):
        rain = self.sound(b"rain", name="rain", author="Somebody",
                          licence="CC0")
        said = self.ask("show_asset", id=rain.hash[:12])
        self.assertIn("CC0", said)
        self.assertIn("rain", said)

    def test_never_a_path_or_an_address(self):
        rain = self.sound(b"rain", name="rain")
        with override_settings(ASSET_BASE_URL="https://mud.example.com"):
            for said in (self.ask("list_assets"),
                         self.ask("show_asset", id=rain.hash[:12])):
                self.assertNotIn(self.folder, said)
                self.assertNotIn("/media/", said)


@tag("unit")
class FilesATookSentBack(SimpleTestCase):
    """`services.files_in`: what a tool's content blocks hold besides text."""

    def block(self, **fields):
        from types import SimpleNamespace

        return SimpleNamespace(**fields)

    def test_an_image_and_a_sound_are_files(self):
        import base64

        from world import services

        found = services.files_in([
            self.block(type="image", data=base64.b64encode(b"GIF89a").decode(),
                       mimeType="image/gif"),
            self.block(type="audio", data=base64.b64encode(b"OggS").decode(),
                       mimeType="audio/ogg"),
            self.block(type="text", text="and some words")])
        self.assertEqual(found, [(b"GIF89a", "image/gif"),
                                 (b"OggS", "audio/ogg")])

    def test_an_embedded_resource_with_a_blob_is_a_file(self):
        import base64

        from world import services

        resource = self.block(blob=base64.b64encode(b"{}").decode(),
                              mimeType="application/json")
        self.assertEqual(services.files_in([self.block(type="resource",
                                                       resource=resource)]),
                         [(b"{}", "application/json")])

    def test_data_that_is_not_base64_is_not_kept(self):
        from world import services

        self.assertEqual(services.files_in([self.block(
            type="image", data="not base64 at all!", mimeType="image/gif")]), [])


@tag("world")
class MadeByATool(_WithSounds):
    """docs/archived/assets.md 11."""

    def sponsor(self, payer, actor=None):
        from types import SimpleNamespace

        return SimpleNamespace(payer=payer, actor=actor)

    def make(self, data=b"SOUND thunder", payer=None, actor=None, **args):
        asset, _said = assets.from_tool(
            data, sponsor=self.sponsor(payer or self.account, actor),
            service="noise", tool="make_sound",
            arguments=args or {"what": "thunder"}, name="thunder",
            description="A roll of thunder.", model="noise/v2",
            settings_used={"temperature": 0.7})
        return asset

    def test_it_is_charged_to_whoever_paid_for_the_call(self):
        asset = self.make(payer=self.account, actor=self.char2)
        self.assertEqual(asset.charged_to, self.account)
        self.assertEqual(asset.added_by, self.account2)
        self.assertEqual(asset.origin, "tool")

    def test_it_says_how_it_was_made(self):
        asset = self.make()
        self.assertEqual(asset.made_with["service"], "noise")
        self.assertEqual(asset.made_with["model"], "noise/v2")
        self.assertEqual(asset.made_with["temperature"], 0.7)

    def test_the_same_request_is_found_rather_than_made_again(self):
        asset = self.make()
        self.assertEqual(assets.made_before("noise", "make_sound",
                                            {"what": "thunder"}), asset)
        self.assertIsNone(assets.made_before("noise", "make_sound",
                                             {"what": "rain"}))

    def test_and_is_checked_like_any_other_file(self):
        with self.assertRaises(assets.Refused):
            self.make(data=b"MZ an executable")
