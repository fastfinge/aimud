"""
Sound: the asset type, the sounds the game ships, steady Ogg files, and
sending a sound to a client, and what menus and the parser sound like.
docs/sound.md, phases 0 to 2.

Every file here is made by `soundfile` in memory, so the type is tested
against what a real encoder writes rather than against bytes that only
start the right way.
"""

import io
import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest import mock

import numpy as np
import soundfile
from django.test import SimpleTestCase, override_settings, tag

from tests.base import GameTest
from world import asset_store, asset_types, assets, ogg, sound


def tone(format_="OGG", subtype="VORBIS", seconds=0.1, rate=44100, pitch=10):
    """A short sine, written as `format_`/`subtype`."""
    samples = (np.sin(np.arange(int(rate * seconds)) / pitch) * 0.3
               ).astype("float32")
    out = io.BytesIO()
    soundfile.write(out, samples, rate, format=format_, subtype=subtype)
    return out.getvalue()


def written(data):
    """`data` in a temporary file, for `check`, which reads a path."""
    handle, path = tempfile.mkstemp(suffix=".sound")
    with os.fdopen(handle, "wb") as out:
        out.write(data)
    return path


@tag("unit")
class TheSoundType(SimpleTestCase):

    def setUp(self):
        self.sound = asset_types.get("sound")
        self.paths = []

    def tearDown(self):
        for path in self.paths:
            os.remove(path)

    def check(self, data):
        path = written(data)
        self.paths.append(path)
        return self.sound.check(path)

    def test_it_is_registered(self):
        self.assertIsNotNone(self.sound)

    def test_none_of_its_extensions_is_code(self):
        for extension in self.sound.every_extension():
            self.assertNotIn(extension, asset_types.NEVER)

    def test_wav_ogg_and_mp3_are_recognised_by_their_first_bytes(self):
        for format_, subtype in (("WAV", "PCM_16"), ("OGG", "VORBIS"),
                                 ("MP3", "MPEG_LAYER_III")):
            self.assertTrue(self.sound.sniff(tone(format_, subtype)[:64]),
                            format_)
        self.assertTrue(self.sound.sniff(b"ID3\x04\0\0" + b"\0" * 20))

    def test_text_is_not(self):
        self.assertFalse(self.sound.sniff(b'{"aimud": 1}'))
        self.assertFalse(self.sound.sniff(b"GIF89a"))

    def test_each_codec_is_its_version(self):
        self.assertEqual(self.check(tone("WAV", "PCM_16")), ("pcm", ""))
        self.assertEqual(self.check(tone("OGG", "VORBIS")), ("vorbis", ""))
        self.assertEqual(self.check(tone("MP3", "MPEG_LAYER_III")),
                         ("mp3", ""))

    def test_and_says_what_it_is_served_as(self):
        self.assertEqual(self.sound.extension_for("pcm"), "wav")
        self.assertEqual(self.sound.extension_for("vorbis"), "ogg")
        self.assertEqual(self.sound.extension_for("mp3"), "mp3")

    def test_opus_and_float_wav_are_refused_by_name(self):
        version, why = self.check(tone("OGG", "OPUS", rate=48000))
        self.assertEqual(why, "")
        self.assertIn("Opus", self.sound.refuses(version))
        version, _why = self.check(tone("WAV", "FLOAT"))
        self.assertIn("floating-point", self.sound.refuses(version))

    def test_something_that_only_starts_like_a_sound(self):
        version, why = self.check(b"RIFF\x24\0\0\0WAVEjunk" + b"x" * 200)
        self.assertEqual(version, "")
        self.assertIn("not a sound", why)

    def test_a_cut_off_ogg_is_not_a_sound(self):
        whole = tone("OGG", "VORBIS", seconds=1.0)
        _version, why = self.check(whole[:len(whole) // 3])
        self.assertTrue(why)


class _Stored(GameTest):
    """A temporary store, and an account to charge."""

    accounts = True

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp(prefix="aimud-sound-")
        previous = asset_store.use(asset_store.LocalStore(self.folder))
        self.addCleanup(asset_store.use, previous)
        self.addCleanup(shutil.rmtree, self.folder, True)

    def add(self, data, **kwargs):
        given = dict(name="a tone", description="A short, plain tone.",
                     added_by=self.account, origin="upload")
        given.update(kwargs)
        return assets.add_bytes(data, **given)[0]


@tag("world")
class KeepingASound(_Stored):

    def test_an_ogg_is_kept_and_served_as_one(self):
        asset = self.add(tone("OGG", "VORBIS"))
        self.assertEqual((asset.type, asset.version), ("sound", "vorbis"))
        self.assertTrue(asset_store.store().exists(asset.hash, "ogg"))
        self.assertTrue(asset_store.store().url(
            asset.hash, assets.extension_of(asset)).endswith(".ogg"))

    def test_a_wav_and_an_mp3_keep_their_own_extensions(self):
        wav = self.add(tone("WAV", "PCM_16"), name="wav")
        mp3 = self.add(tone("MP3", "MPEG_LAYER_III"), name="mp3")
        self.assertEqual(assets.extension_of(wav), "wav")
        self.assertEqual(assets.extension_of(mp3), "mp3")
        self.assertTrue(asset_store.store().exists(wav.hash, "wav"))
        self.assertTrue(asset_store.store().exists(mp3.hash, "mp3"))

    def test_an_opus_file_is_refused(self):
        with self.assertRaises(assets.Refused) as caught:
            self.add(tone("OGG", "OPUS", rate=48000))
        self.assertIn("Opus", str(caught.exception))

    def test_deleting_one_removes_the_right_file(self):
        asset = self.add(tone("WAV", "PCM_16"))
        assets.delete(asset)
        self.assertFalse(asset_store.store().exists(asset.hash, "wav"))


@tag("world")
class TheGamesOwnSounds(_Stored):
    """docs/sound.md 4.3."""

    MENU = ("menu/open", "menu/close", "menu/select", "menu/error",
            "menu/huh")

    def test_every_one_ships_with_a_name_a_description_and_its_spec(self):
        files = assets.builtin_files()
        for ref in self.MENU:
            path, doc = files[ref]
            self.assertTrue(doc["name"], ref)
            self.assertTrue(doc["description"], ref)
            self.assertEqual(doc["made_with"]["tool"], "genny", ref)
            self.assertIn("layers", doc["made_with"]["spec"], ref)
            self.assertEqual(asset_types.get("sound").check(path)[0],
                             "vorbis", ref)

    def test_they_are_kept_once_and_charged_to_nobody(self):
        self.assertEqual(assets.take_in_builtins(), len(assets.builtin_files()))
        self.assertEqual(assets.take_in_builtins(), 0)
        for ref in self.MENU:
            asset = assets.builtin(ref)
            self.assertIsNotNone(asset, ref)
            self.assertEqual(asset.origin, "builtin")
            self.assertIsNone(asset.charged_to)
            self.assertEqual(assets.builtin_ref(asset), ref)

    def test_nobody_can_delete_give_up_or_adopt_one(self):
        assets.take_in_builtins()
        opened = assets.builtin("menu/open")
        with self.assertRaises(assets.Refused):
            assets.delete(opened, force=True)
        with self.assertRaises(assets.Refused):
            assets.give_up(self.account, opened)
        with self.assertRaises(assets.Refused):
            assets.adopt(self.account, opened)
        self.assertEqual(assets.find(opened.hash).origin, "builtin")

    def test_they_are_not_the_pools_to_count_or_evict(self):
        assets.take_in_builtins()
        self.assertEqual(assets.pool_used(), 0)
        self.assertFalse(assets.pooled().exists())

    def test_one_somebody_had_already_added_becomes_the_games(self):
        path, _doc = assets.builtin_files()["menu/select"]
        with open(path, "rb") as handle:
            mine = self.add(handle.read(), name="my chirp")
        self.assertEqual(mine.charged_to, self.account)
        assets.take_in_builtins()
        mine.refresh_from_db()
        self.assertEqual(mine.origin, "builtin")
        self.assertIsNone(mine.charged_to)
        self.assertEqual(assets.used_by(self.account), 0)

    def test_a_file_gone_from_the_store_is_put_back(self):
        assets.take_in_builtins()
        opened = assets.builtin("menu/open")
        asset_store.store().delete(opened.hash, "ogg")
        assets.take_in_builtins()
        self.assertTrue(asset_store.store().exists(opened.hash, "ogg"))


@tag("unit")
class SteadyOgg(SimpleTestCase):
    """The same sound is the same file. docs/sound.md 4.3."""

    def test_encoding_twice_gives_one_file(self):
        first, second = tone(), tone()
        self.assertNotEqual(first, second)
        self.assertEqual(ogg.steady(first), ogg.steady(second))

    def test_and_it_still_plays(self):
        data, rate = soundfile.read(io.BytesIO(ogg.steady(tone())))
        self.assertEqual(rate, 44100)
        self.assertEqual(len(data), 4410)

    def test_anything_else_is_refused_rather_than_half_changed(self):
        with self.assertRaises(ValueError):
            ogg.steady(b"RIFF" + b"\0" * 60)
        with self.assertRaises(ValueError):
            ogg.steady(tone()[:100])


# ---------------------------------------------------------------------------
# Sending. docs/sound.md 3, phase 1
# ---------------------------------------------------------------------------

class FakeSession:
    """What `world.sound` reads of a session, and what it was sent."""

    def __init__(self, key="telnet", **flags):
        self.protocol_key = key
        self.protocol_flags = dict(flags)
        self.ndb = SimpleNamespace()
        self.account = None
        self.sent = []

    def msg(self, *args, **kwargs):
        if args:
            kwargs["text"] = args[0]
        self.sent.append(kwargs)

    def media(self, name="client_media_play"):
        return [kwargs[name][1] for kwargs in self.sent if name in kwargs]

    def msp(self):
        return [kwargs["msp"][0][0] for kwargs in self.sent if "msp" in kwargs]


class Listener:
    """A character with these sessions, played by `account`."""

    def __init__(self, account, *sessions):
        self.account = account
        self.sessions = SimpleNamespace(all=lambda: list(sessions))


@tag("unit")
class WhatASessionSpeaks(SimpleTestCase):

    def speaks(self, session, **settings):
        account = mock.Mock()
        account.attributes.get = lambda attr: settings.get(attr)
        return sound.speaks(session, account)

    def test_a_client_that_asked_for_client_media(self):
        self.assertEqual(self.speaks(FakeSession(CLIENT_MEDIA=True)),
                         sound.MEDIA)

    def test_a_telnet_client_that_agreed_to_msp(self):
        self.assertEqual(self.speaks(FakeSession(MSP=True)), sound.MSP)
        self.assertEqual(self.speaks(FakeSession("telnet/ssl", MSP=True)),
                         sound.MSP)

    def test_one_that_has_both_is_sent_client_media_only(self):
        self.assertEqual(self.speaks(FakeSession(MSP=True, CLIENT_MEDIA=True)),
                         sound.MEDIA)

    def test_nothing_else_is_sent_anything(self):
        self.assertEqual(self.speaks(FakeSession()), "")
        self.assertEqual(self.speaks(FakeSession("mcp")), "")
        self.assertEqual(self.speaks(FakeSession("webclient/websocket",
                                                 MSP=True)), "")

    def test_sounds_off_or_protocol_off_sends_nothing(self):
        session = FakeSession(CLIENT_MEDIA=True, MSP=True)
        self.assertEqual(self.speaks(session, sound_on=False), "")
        self.assertEqual(self.speaks(session, sound_protocol="off"), "")

    def test_a_player_can_insist(self):
        self.assertEqual(self.speaks(FakeSession(), sound_protocol="msp"),
                         sound.MSP)
        self.assertEqual(self.speaks(FakeSession("mcp"),
                                     sound_protocol="msp"), "")
        self.assertEqual(self.speaks(FakeSession(MSP=True),
                                     sound_protocol="media"), sound.MEDIA)


@override_settings(ASSET_BASE_URL="https://mud.example.com:4001")
@tag("world")
class PlayingOne(_Stored):

    characters = 2

    def setUp(self):
        super().setUp()
        assets.take_in_builtins()
        self.media = FakeSession(CLIENT_MEDIA=True)
        self.telnet = FakeSession(MSP=True)
        self.listener = Listener(self.account, self.media, self.telnet)
        self.opened = assets.builtin("menu/open")
        self.name = f"{self.opened.hash}.ogg"
        self.url = "https://mud.example.com:4001/media/assets/"

    def test_client_media_is_told_where_and_what_it_is(self):
        self.assertEqual(sound.play(self.listener, "menu/open",
                                    category=sound.UI, volume=80), 2)
        payload, = self.media.media()
        self.assertEqual(payload["name"], self.name)
        self.assertEqual(payload["url"], self.url)
        self.assertEqual((payload["type"], payload["tag"]), ("sound", "ui"))
        self.assertEqual((payload["volume"], payload["loops"]), (80, 1))
        self.assertEqual(payload["caption"], self.opened.description)
        self.assertNotIn("key", payload)

    def test_msp_gets_a_line_of_its_own(self):
        sound.play(self.listener, self.opened, category=sound.UI, volume=80)
        line, = self.telnet.msp()
        self.assertEqual(line, f"!!SOUND({self.name} V=80 L=1 P=50 T=ui "
                               f"U={self.url})")

    def test_a_loop_is_keyed_and_carries_on(self):
        sound.play(self.listener, self.opened, category=sound.AMBIENCE,
                   loop=True, key="wind", fade=1000)
        payload, = self.media.media()
        self.assertEqual(payload["loops"], -1)
        self.assertEqual((payload["key"], payload["continue"]), ("wind", True))
        self.assertEqual(payload["fadein"], 1000)
        line, = self.telnet.msp()
        self.assertTrue(line.startswith(f"!!MUSIC({self.name} "))
        self.assertIn(" L=-1 C=1 T=ambience ", line)

    def test_stopping_a_loop(self):
        sound.play(self.listener, self.opened, category=sound.AMBIENCE,
                   loop=True, key="wind")
        # MSP cannot stop a sound by name, so only its one loop is stopped.
        self.assertEqual(sound.stop(self.listener, "rain"), 1)
        self.assertEqual(len(self.telnet.msp()), 1)
        sound.stop(self.listener, "wind", fade=500)
        self.assertEqual(self.media.media("client_media_stop")[-1],
                         {"key": "wind", "fadeout": 500})
        self.assertEqual(self.telnet.msp()[-1], "!!MUSIC(Off)")

    def test_the_players_own_volume_scales_it(self):
        self.account.attributes.add("sound_volume_ui", 50)
        sound.play(self.listener, self.opened, category=sound.UI, volume=80)
        self.assertEqual(self.media.media()[0]["volume"], 40)
        self.assertIn(" V=40 ", self.telnet.msp()[0])

    def test_turned_all_the_way_down_nothing_is_sent(self):
        self.account.attributes.add("sound_volume_ui", 0)
        self.assertEqual(sound.play(self.listener, self.opened,
                                    category=sound.UI), 0)
        self.assertEqual(self.media.sent + self.telnet.sent, [])

    def test_playing_one_says_it_was_used(self):
        sound.play(self.listener, self.opened, category=sound.UI)
        self.assertIsNotNone(assets.find(self.opened.hash).last_used)

    def test_a_missing_sound_or_nobody_listening_plays_nothing(self):
        self.opened.status = "missing"
        self.opened.save()
        self.assertEqual(sound.play(self.listener, self.opened,
                                    category=sound.UI), 0)
        self.assertEqual(sound.play(self.char2, "menu/close",
                                    category=sound.UI), 0)

    def test_the_menu_sounds_are_fetched_ahead(self):
        self.assertEqual(sound.preload(self.media, sound.ui_sounds(None)), 5)
        self.assertEqual(sound.preload(self.telnet, sound.ui_sounds(None)), 0)
        first = self.media.media("client_media_load")[0]
        self.assertEqual(first, {"name": self.name, "url": self.url})

    @override_settings(ASSET_BASE_URL="")
    def test_without_an_address_nothing_is_sent(self):
        self.assertEqual(sound.play(self.listener, self.opened,
                                    category=sound.UI), 0)
        self.assertEqual(self.media.sent + self.telnet.sent, [])

    @override_settings(ASSET_BASE_URL="")
    def test_and_an_admin_is_told_why_when_they_log_in(self):
        self.account.permissions.add("Admin")
        sound.at_login(self.account, self.media)
        said, = [kwargs["text"] for kwargs in self.media.sent]
        self.assertIn("ASSET_BASE_URL", str(said))
        player = FakeSession(CLIENT_MEDIA=True)
        self.account2.permissions.remove("Developer")
        sound.at_login(self.account2, player)
        self.assertEqual(player.sent, [])


@tag("unit")
class TheWire(SimpleTestCase):
    """What the Portal makes of what `world.sound` sends."""

    def test_client_media_is_named_as_gmcp_names_it(self):
        from evennia.server.portal.gmcp_utils import encode_gmcp

        for evennia, gmcp in (("client_media_play", "Client.Media.Play"),
                              ("client_media_stop", "Client.Media.Stop"),
                              ("client_media_load", "Client.Media.Load")):
            self.assertTrue(encode_gmcp(evennia, key="x").startswith(
                gmcp + " "))

    def test_core_supports_set_reaches_ours(self):
        from evennia.server.portal.gmcp_utils import decode_gmcp

        self.assertEqual(decode_gmcp('Core.Supports.Set ["Client.Media 1"]'),
                         {"supports_set": [["Client.Media 1"], {}]})

    def test_client_media_in_the_list_sets_the_flag(self):
        from server.conf import inputfuncs

        session = FakeSession()
        session.sessid, session.logged_in = 1, False
        session.sessionhandler = mock.Mock()
        inputfuncs.supports_set(session, "Char 1", "Client.Media 1")
        self.assertTrue(session.protocol_flags["CLIENT_MEDIA"])
        inputfuncs.supports_remove(session, "Client.Media")
        self.assertFalse(session.protocol_flags["CLIENT_MEDIA"])
        inputfuncs.supports_add(session, ["client.media 1"])
        self.assertTrue(session.protocol_flags["CLIENT_MEDIA"])
        inputfuncs.supports_set(session, "Char 1")
        self.assertFalse(session.protocol_flags["CLIENT_MEDIA"])


@tag("unit")
class TheMspHandshake(SimpleTestCase):

    def protocol(self):
        from server.conf import telnet_msp

        found = telnet_msp.MspTelnetProtocol.__new__(
            telnet_msp.MspTelnetProtocol)
        found.protocol_flags = {}
        found.sendLine = mock.Mock()
        found.handshake_done = mock.Mock()
        return found

    def test_agreeing_turns_it_on_and_counts_the_handshake(self):
        found = self.protocol()
        found._msp_yes(None)
        self.assertTrue(found.protocol_flags["MSP"])
        found.handshake_done.assert_called_once()

    def test_declining_leaves_it_off_and_counts_too(self):
        found = self.protocol()
        found._msp_no(None)
        self.assertFalse(found.protocol_flags["MSP"])
        found.handshake_done.assert_called_once()

    def test_a_line_is_written_only_to_a_client_that_agreed(self):
        found = self.protocol()
        found.send_msp("!!SOUND(a.ogg)")
        found.sendLine.assert_not_called()
        found.protocol_flags["MSP"] = True
        found.send_msp("!!SOUND(a.ogg)")
        found.sendLine.assert_called_once_with("!!SOUND(a.ogg)")

    def test_a_client_asking_first_is_agreeing(self):
        from server.conf import telnet_msp

        found = self.protocol()
        self.assertTrue(found.enableLocal(telnet_msp.MSP))
        self.assertTrue(found.protocol_flags["MSP"])


# ---------------------------------------------------------------------------
# Menus and the parser. docs/sound.md 8, phase 2
# ---------------------------------------------------------------------------

from tests.test_menus import Driving, Recorder, a_form  # noqa: E402
from world import menus  # noqa: E402


class _Cued(Driving):
    """The real sound presenter, with what it would play written down."""

    def setUp(self):
        super().setUp()
        self.presenter = sound._presenter_class()()
        patcher = mock.patch.object(menus, "PRESENTER", self.presenter)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cues = []
        player = mock.patch.object(
            sound, "play", lambda listener, found, **kwargs:
            self.cues.append(found) or 1)
        player.start()
        self.addCleanup(player.stop)


@tag("world")
class WhatAMenuSoundsLike(_Cued):

    def test_each_moment_has_its_sound(self):
        self.open(a_form())
        self.assertEqual(self.cues, ["menu/open"])
        # A field is chosen when it is answered, not when its prompt opens.
        self.type("1")
        self.assertEqual(self.cues, ["menu/open"])
        self.type("Harbour")
        self.assertEqual(self.cues[-1], "menu/select")
        self.type("fly")
        self.assertEqual(self.cues[-1], "menu/error")
        self.type("4")
        self.type("no")
        self.assertEqual(self.cues[-1], "menu/close")
        self.assertTrue(self.is_open)
        self.type("4")
        self.type("yes")
        self.assertEqual(self.cues[-2:], ["menu/select", "menu/select"])
        # The title is unsaved, so quitting asks first.
        self.type("q")
        self.type("yes")
        self.assertEqual(self.cues[-2:], ["menu/select", "menu/close"])
        self.assertFalse(self.is_open)

    def test_a_sound_that_fails_never_takes_the_menu_with_it(self):
        with mock.patch.object(sound, "play", side_effect=RuntimeError):
            self.open(a_form())
            self.type("1")
        self.assertTrue(self.is_open)


@tag("world")
class ARefusalIsHeard(Driving):
    """An action that says no is "not one of the choices" too."""

    def test_an_action_refusing_reaches_the_presenter(self):
        def refuse(ctx):
            raise menus.Refuse("That cannot be done here.")

        form = menus.Form(key="t", title="T", items=[
            menus.Action("go", "Go", run=refuse)])
        self.open(form)
        said = self.type("1")
        self.assertIn("That cannot be done here.", said)
        self.assertEqual(len(self.presenter.named("refused")), 1)


@tag("world")
class ChoosingYourOwn(_Stored):
    """docs/sound.md 8.3."""

    def setUp(self):
        super().setUp()
        assets.take_in_builtins()
        from world import preferences

        self.fields = {field.key: field for field in preferences.MOMENT_FIELDS}
        self.ctx = menus.Context(self.account)
        self.ctx.account = self.account

    def test_the_game_s_own_until_somebody_chooses(self):
        self.assertEqual(sound.ui_sound(self.account, sound.OPEN), "menu/open")
        self.assertEqual(sound.ui_sound(None, sound.HUH), "menu/huh")

    def test_any_sound_can_be_chosen_and_is_kept_by_hash(self):
        mine = self.add(tone("WAV", "PCM_16"), name="my bell")
        offered = [choice.value for choice in
                   self.fields["menuopen"].choices_for(self.ctx)]
        self.assertIn(mine.hash, offered)
        self.assertIn(sound.SILENT, offered)
        self.fields["menuopen"].store(self.ctx, mine.hash)
        self.assertEqual(self.account.attributes.get("sound_moment_open"),
                         mine.hash)
        self.assertEqual(sound.ui_sound(self.account, sound.OPEN), mine)

    def test_a_built_in_is_kept_by_its_name(self):
        error = assets.builtin("menu/error")
        self.fields["menuopen"].store(self.ctx, error.hash)
        self.assertEqual(self.account.attributes.get("sound_moment_open"),
                         "menu/error")
        self.fields["menuopen"].store(self.ctx, assets.builtin("menu/open")
                                      .hash)
        self.assertIsNone(self.account.attributes.get("sound_moment_open"))

    def test_silence_and_clearing(self):
        self.fields["huhsound"].store(self.ctx, sound.SILENT)
        self.assertIsNone(sound.ui_sound(self.account, sound.HUH))
        self.assertEqual(sound.cue(self.account, sound.HUH), 0)
        self.fields["huhsound"].store(self.ctx, None)
        self.assertEqual(sound.ui_sound(self.account, sound.HUH), "menu/huh")

    def test_a_chosen_sound_that_has_gone_falls_back(self):
        mine = self.add(tone("WAV", "PCM_16"), name="my bell")
        self.fields["menuclose"].store(self.ctx, mine.hash)
        assets.delete(mine)
        self.assertEqual(sound.ui_sound(self.account, sound.CLOSE),
                         "menu/close")


@tag("world")
class NotUnderstood(GameTest):
    """The parser's drum hit. docs/sound.md 8.1."""

    def heard(self, line):
        with mock.patch.object(sound, "cue") as cue:
            self.char1.execute_cmd(line)
        return [call.args[1] for call in cue.call_args_list]

    def test_outside_a_world(self):
        self.assertEqual(self.heard("xyzzyplugh"), [sound.HUH])

    def test_a_command_that_exists_is_not_a_drum_hit(self):
        self.assertEqual(self.heard("look"), [])
