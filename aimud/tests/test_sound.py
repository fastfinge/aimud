"""
Sound: the asset type, the sounds the game ships, steady Ogg files, and
sending a sound to a client, what menus and the parser sound like, and
what happens in a world and the places in it sound like, and making sounds
with genny, for players and for models, the sound ruleset, and the web
client. docs/archived/sound.md, phases 0 to 8.

Every file here is made by `soundfile` in memory, so the type is tested
against what a real encoder writes rather than against bytes that only
start the right way.
"""

import io
import json
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
    """docs/archived/sound.md 4.3."""

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
    """The same sound is the same file. docs/archived/sound.md 4.3."""

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
# Sending. docs/archived/sound.md 3, phase 1
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
# Menus and the parser. docs/archived/sound.md 8, phase 2
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
    """docs/archived/sound.md 8.3."""

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
    """The parser's drum hit. docs/archived/sound.md 8.1."""

    def heard(self, line):
        with mock.patch.object(sound, "cue") as cue:
            self.char1.execute_cmd(line)
        return [call.args[1] for call in cue.call_args_list]

    def test_outside_a_world(self):
        self.assertEqual(self.heard("xyzzyplugh"), [sound.HUH])

    def test_a_command_that_exists_is_not_a_drum_hit(self):
        self.assertEqual(self.heard("look"), [])


# ---------------------------------------------------------------------------
# Event sounds. docs/archived/sound.md 5, phase 3
# ---------------------------------------------------------------------------

class _Sounding(_Stored):
    """The built-ins kept, and every `heard` written down instead of sent."""

    characters = 2

    def setUp(self):
        super().setUp()
        assets.take_in_builtins()
        self.opened = assets.builtin("menu/open")
        self.played = []
        patcher = mock.patch.object(
            sound, "heard", lambda listener, found, **kwargs:
            self.played.append((listener, found, kwargs)) or 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def effect(self, **extra):
        found = {"type": "play_sound", "sound": self.opened.hash}
        found.update(extra)
        return found

    def who(self):
        return [listener for listener, _found, _kwargs in self.played]


@tag("world")
class PlayingASoundIsAnEffect(_Sounding):

    def test_it_is_in_the_vocabulary_and_says_what_it_plays(self):
        from world import effects

        self.assertIn("play_sound", effects.VOCABULARY)
        self.assertFalse(effects.VOCABULARY["play_sound"]["backwards"])
        said = effects.say(self.effect(to="actor"))
        self.assertEqual(said, f"plays {self.opened.name} to whoever acted")

    def test_with_nothing_waiting_it_is_heard_at_once(self):
        from world import effects

        lines = effects.apply(self.char1, self.room1, [self.effect()])
        self.assertEqual(lines, [])
        self.assertEqual(set(self.who()), {self.char1, self.char2})
        self.assertEqual(self.played[0][2]["category"], sound.EVENT)

    def test_who_hears_it(self):
        from world import effects

        for to, expected in ((sound.ACTOR, [self.char1]),
                             (sound.OTHERS, [self.char2]),
                             ("direct", [self.char2])):
            self.played = []
            effects.apply(self.char1, self.room1, [self.effect(to=to)],
                          bound={"direct": self.char2})
            self.assertEqual(self.who(), expected, to)

    def test_a_sound_this_server_does_not_have_plays_nothing(self):
        from world import effects

        effects.apply(self.char1, self.room1,
                      [self.effect(sound="0" * 64)])
        self.assertEqual(self.played, [])

    def test_a_direction_becomes_a_pan(self):
        from world import effects

        effects.apply(self.char1, self.room1, [self.effect(direction="e")])
        self.assertEqual(self.played[0][2]["pan"], 100)
        self.assertEqual(sound.pan_toward("west"), -100)
        self.assertEqual(sound.pan_toward("northeast"), 50)
        self.assertEqual(sound.pan_toward("up"), 0)
        self.assertEqual(sound.pan_toward("the hatch"), 0)


@tag("world")
class TheEventCarriesIt(_Sounding):

    def test_it_waits_for_the_event_and_is_heard_once(self):
        from world import effects, events

        heard = []
        effects.apply(self.char1, self.room1, [self.effect()], sounds=heard)
        self.assertEqual(self.played, [])
        event = events.Event(actor=self.char1, room=self.room1,
                             room_template="{actor} opens the door.",
                             sounds=heard)
        events.deliver(event)
        self.assertEqual(set(self.who()), {self.char1, self.char2})
        events.deliver(event)
        self.assertEqual(len(self.played), 2)

    def test_after_everybody_has_read_it(self):
        from world import events

        order = []
        self.char2.msg = lambda *args, **kwargs: order.append("read")
        sound.heard = lambda listener, found, **kwargs: order.append("heard")
        event = events.Event(actor=self.char1, room=self.room1,
                             room_template="{actor} opens the door.",
                             sounds=[{"asset": self.opened, "to": "others",
                                      "volume": 100, "pan": 0,
                                      "actor": self.char1,
                                      "room": self.room1, "roles": {}}])
        events.deliver(event)
        self.assertEqual(order, ["read", "heard"])

    def test_a_sound_with_nothing_to_read_is_still_heard(self):
        from world import events

        event = events.Event(actor=self.char1, room=self.room1, sounds=[
            {"asset": self.opened, "to": "everyone", "volume": 100, "pan": 0,
             "actor": self.char1, "room": self.room1, "roles": {}}])
        events.deliver_many([event], actor=self.char1, room=self.room1)
        self.assertEqual(set(self.who()), {self.char1, self.char2})


@override_settings(ASSET_BASE_URL="https://mud.example.com:4001")
@tag("world")
class Captions(_Stored):
    """Every sound is also a line of text. docs/archived/sound.md 7."""

    def setUp(self):
        super().setUp()
        assets.take_in_builtins()
        self.opened = assets.builtin("menu/open")
        self.speakers = FakeSession(CLIENT_MEDIA=True)
        self.agent = FakeSession("mcp")
        self.read = []
        self.listener = Listener(self.account, self.speakers, self.agent)
        self.listener.msg = lambda text, session=None: self.read.append(
            (session, text))

    def test_the_window_with_speakers_hears_it_and_the_other_reads_it(self):
        sent = sound.heard(self.listener, self.opened, category=sound.EVENT)
        self.assertEqual(sent, 1)
        self.assertEqual(len(self.speakers.media()), 1)
        (session, text), = self.read
        self.assertIs(session, self.agent)
        self.assertIn(self.opened.description.rstrip("."), text)

    def test_always_and_never(self):
        self.account.attributes.add("sound_captions_event", "on")
        sound.heard(self.listener, self.opened, category=sound.EVENT)
        self.assertEqual(len(self.read), 2)
        self.read.clear()
        self.account.attributes.add("sound_captions_event", "off")
        sound.heard(self.listener, self.opened, category=sound.EVENT)
        self.assertEqual(self.read, [])

    def test_nobody_without_a_session_is_given_one(self):
        npc = Listener(None)
        npc.msg = mock.Mock()
        sound.heard(npc, self.opened, category=sound.EVENT)
        npc.msg.assert_not_called()


@tag("world")
class WritingOneIntoARule(_Sounding):

    def keep(self, **draft):
        from world.makers import rules

        ctx = menus.Context(self.char1)
        ctx.draft.update(draft)
        return rules.keep_effect(ctx)

    def test_the_form_keeps_the_whole_hash_and_everyone_by_default(self):
        effect, said = self.keep(type="play_sound",
                                 sound=self.opened.hash[:12], volume=60)
        self.assertEqual(effect, {"type": "play_sound",
                                  "sound": self.opened.hash, "volume": 60,
                                  "to": "everyone"})
        self.assertIn(self.opened.name, said)

    def test_and_refuses_one_with_no_sound(self):
        with self.assertRaises(menus.Refuse):
            self.keep(type="play_sound", hearers="actor")

    def test_a_model_must_name_a_sound_the_server_keeps(self):
        from world import rule_gen

        offered = [("world", "everywhere", {"world": True})]
        rule = {"phase": "carry_out", "scope": "world",
                "effects": [{"type": "play_sound", "sound": "feedface0000"}]}
        kept, complaints = rule_gen.validate({"rules": [rule]}, offered,
                                             "ring")
        self.assertEqual(kept, [])
        self.assertIn("play_sound naming no sound", complaints[0])
        rule["effects"][0]["sound"] = self.opened.hash[:12]
        kept, complaints = rule_gen.validate({"rules": [rule]}, offered,
                                             "ring")
        self.assertEqual(complaints, [])
        self.assertEqual(kept[0]["effects"][0]["sound"], self.opened.hash)

    def test_a_world_whose_rule_plays_it_is_using_it(self):
        from world import rulebooks

        self.room1.db.is_world_root = True
        self.room1.db.world_root = self.room1
        rulebooks.add(self.room1, rulebooks.blank(
            action="ring", phase=rulebooks.CARRY_OUT,
            effects=[self.effect()]))
        self.assertEqual(sound.used_in(self.room1), [self.opened])
        use, = sound.uses(self.opened)
        self.assertIs(use["world"], self.room1)
        self.assertIn("a rule", use["said"])


# ---------------------------------------------------------------------------
# Ambience. docs/archived/sound.md 6, phase 4
# ---------------------------------------------------------------------------

class _Ambient(_Stored):
    """A world of one room, its built-in sounds, and listeners to give it."""

    second_room = True
    loose_objects = 1

    def setUp(self):
        super().setUp()
        assets.take_in_builtins()
        self.wind = assets.builtin("menu/open")
        self.fire = assets.builtin("menu/close")
        self.rain = assets.builtin("menu/huh")
        for room in (self.room1, self.room2):
            room.db.world_root = self.room1
            room.tags.add(str(self.room1.id), category="ai_world")
        self.room1.db.is_world_root = True
        self.sessions = {}
        patcher = mock.patch.object(
            sound, "_sessions",
            lambda listener: list(self.sessions.get(getattr(listener, "id",
                                                            None), [])))
        patcher.start()
        self.addCleanup(patcher.stop)

    def listen(self, *sessions):
        for session in sessions:
            session.account = self.account
        self.sessions[self.char1.id] = list(sessions)
        return sessions

    def heard(self, room=None):
        _place, every = sound.ambience_for(self.char1, room)
        return [asset for asset, _volume, _pan in every]


@tag("world")
class WhatAPlaceSoundsLike(_Ambient):

    def test_a_room_s_own_comes_first_and_alone(self):
        from world import zones

        zones.attach(self.room1, self.room1, "The Moor")
        sound.set_zone_ambience(self.room1, "the_moor", [{"sound": self.wind}])
        self.assertEqual(self.heard(), [self.wind])
        sound.set_ambience(self.room1, [{"sound": self.rain.hash}])
        self.assertEqual(self.heard(), [self.rain])

    def test_a_kind_is_heard_in_every_place_of_that_kind(self):
        self.room1.db.kinds = ["forest.n.01"]
        sound.set_kind_ambience(self.room1, "forest.n.01",
                                [{"sound": "menu/open"}])
        self.assertEqual(self.heard(), [self.wind])

    def test_and_in_every_sort_under_it(self):
        self.room1.db.kinds = ["rain_forest.n.01"]
        sound.set_kind_ambience(self.room1, "forest.n.01",
                                [{"sound": "menu/open"}])
        self.assertEqual(self.heard(), [self.wind])

    def test_things_and_their_conditions_are_heard_beside_the_place(self):
        from world import verbs

        sound.set_ambience(self.room1, [{"sound": self.wind, "volume": 40}])
        verbs.register_state(self.room1, "burning")
        sound.set_state_ambience(self.room1, "burning",
                                 [{"sound": self.fire, "volume": 70}])
        self.assertEqual(self.heard(), [self.wind])
        verbs.apply_states(self.obj1, add=["burning"], world_root=self.room1,
                           announce=False)
        self.assertEqual(self.heard(), [self.fire, self.wind])

    def test_nothing_inside_something_else_is_heard(self):
        sound.set_ambience(self.obj1, [{"sound": self.fire}])
        self.assertEqual(self.heard(), [self.fire])
        from evennia.utils.create import create_object

        box = create_object("typeclasses.objects.Object", key="box",
                            location=self.room1)
        self.obj1.move_to(box, quiet=True)
        self.assertEqual(self.heard(), [])

    def test_one_of_each_sound_the_loudest_and_at_most_four(self):
        sound.set_ambience(self.room1, [{"sound": self.wind, "volume": 20},
                                        {"sound": self.wind, "volume": 90}])
        _place, every = sound.ambience_for(self.char1)
        self.assertEqual([(asset, volume) for asset, volume, _pan in every],
                         [(self.wind, 90)])
        loops = [assets.builtin(ref) for ref in sound.MOMENTS.values()]
        sound.set_ambience(self.obj1, [{"sound": asset} for asset in loops])
        _place, every = sound.ambience_for(self.char1)
        self.assertEqual(len(every), sound.MOST_LOOPS)

    def test_a_sound_this_server_does_not_keep_cannot_be_chosen(self):
        self.assertEqual(sound.set_ambience(self.room1,
                                            [{"sound": "0" * 64}]), [])

    def test_look_and_listen_say_it(self):
        sound.set_ambience(self.room1, [{"sound": self.wind}])
        said = self.room1.return_appearance(self.char1)
        self.assertIn("You hear:", said)
        self.assertIn(self.wind.description.rstrip("."), said)
        heard = []
        self.char1.msg = lambda text="", **kwargs: heard.append(str(text))
        self.char1.execute_cmd("listen")
        self.assertIn("You hear:", heard[-1])

    def test_a_world_that_keeps_making_a_sound_is_using_it(self):
        sound.set_ambience(self.room2, [{"sound": self.rain}])
        self.assertIn(self.rain, sound.used_in(self.room1))
        self.assertTrue(sound.uses(self.rain))
        with self.assertRaises(assets.Refused):
            assets.delete(self.rain)


@override_settings(ASSET_BASE_URL="https://mud.example.com:4001")
@tag("world")
class CrossingBetweenPlaces(_Ambient):

    def setUp(self):
        super().setUp()
        sound.set_ambience(self.room1, [{"sound": self.wind}])
        sound.set_ambience(self.room2, [{"sound": self.wind},
                                        {"sound": self.rain, "volume": 50}])

    def test_client_media_starts_what_is_new_and_leaves_what_carries_on(self):
        media, = self.listen(FakeSession(CLIENT_MEDIA=True))
        sound.refresh(self.char1)
        first, = media.media()
        self.assertEqual(first["key"], "ambience-" + self.wind.hash)
        self.assertEqual((first["loops"], first["fadein"]), (-1, 1000))
        self.char1.move_to(self.room2, quiet=True)
        plays = media.media()
        self.assertEqual(len(plays), 2)
        self.assertEqual(plays[1]["key"], "ambience-" + self.rain.hash)
        self.char1.move_to(self.room1, quiet=True)
        self.assertEqual(media.media("client_media_stop")[-1],
                         {"key": "ambience-" + self.rain.hash,
                          "fadeout": 1000})
        self.assertEqual(len(media.media()), 2)

    def test_msp_gets_the_one_loudest_loop_of_the_place(self):
        telnet, = self.listen(FakeSession(MSP=True))
        sound.refresh(self.char1)
        self.char1.move_to(self.room2, quiet=True)
        lines = telnet.msp()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(f"!!MUSIC({self.wind.hash}.ogg"))
        sound.set_ambience(self.room2, [])
        self.assertEqual(telnet.msp()[-1], "!!MUSIC(Off)")

    def test_somebody_reading_is_told_what_changed_once(self):
        agent, = self.listen(FakeSession("mcp"))
        read = []
        self.char1.msg = lambda text="", **kwargs: read.append(str(text))
        sound.refresh(self.char1)
        self.assertIn("You hear:", read[-1])
        sound.refresh(self.char1)
        self.assertEqual(len(read), 1)
        self.char1.move_to(self.room2, quiet=True)
        self.assertIn(self.rain.description[1:20], read[-1])
        self.char1.move_to(self.room1, quiet=True)
        self.assertIn("Fading:", read[-1])

    def test_turning_sound_off_stops_what_is_playing(self):
        media, = self.listen(FakeSession(CLIENT_MEDIA=True))
        sound.refresh(self.char1)
        self.account.attributes.add("sound_on", False)
        self.account.attributes.add("sound_captions_ambience", "off")
        sound.refresh(self.char1)
        self.assertEqual(media.media("client_media_stop")[-1],
                         {"tag": "ambience", "fadeout": 1000})

    def test_a_condition_starting_is_heard_at_once(self):
        from world import verbs

        media, = self.listen(FakeSession(CLIENT_MEDIA=True))
        sound.refresh(self.char1)
        verbs.register_state(self.room1, "burning")
        sound.set_state_ambience(self.room1, "burning",
                                 [{"sound": self.fire}])
        verbs.apply_states(self.obj1, add=["burning"], world_root=self.room1,
                           announce=False)
        self.assertEqual(media.media()[-1]["key"],
                         "ambience-" + self.fire.hash)

    def test_leaving_the_character_stops_it(self):
        media, = self.listen(FakeSession(CLIENT_MEDIA=True))
        sound.refresh(self.char1)
        sound.forget_hearing(media)
        self.assertEqual(media.media("client_media_stop")[-1]["tag"],
                         "ambience")


@tag("world")
class AmbienceTravelsWithAWorld(_Ambient):

    def test_a_room_s_ambience_is_in_its_record_and_comes_back(self):
        from world import exchange

        sound.set_ambience(self.room1, [{"sound": self.wind, "pan": 30}])
        record = exchange._room(self.room1, exchange.Names())
        self.assertEqual(record["ambience"],
                         [{"sound": self.wind.hash, "volume": 100,
                           "pan": 30}])
        exchange._write_ambience(self.room2, record)
        self.assertEqual(sound.own_ambience(self.room2), record["ambience"])

    def test_a_document_may_name_a_sound_not_here_yet(self):
        written = sound.written_ambience([{"sound": "AB" * 32},
                                          {"sound": "menu/huh"},
                                          {"sound": ""}])
        self.assertEqual([entry["sound"] for entry in written],
                         ["ab" * 32, self.rain.hash])

    def test_a_ruleset_says_what_a_kind_and_a_condition_sound_like(self):
        from world import rulesets

        rulesets._apply(self.room1, {
            "name": "noises",
            "kinds": [{"kind": "forest.n.01", "affordances": {},
                       "ambience": [{"sound": "menu/open"}]}],
            "conditions": [{"state": "crackling", "means": "on fire",
                            "ambience": [{"sound": "menu/close"}]}]}, {})
        self.assertEqual(sound.kind_ambience(self.room1, "forest.n.01")[0]
                         ["sound"], self.wind.hash)
        self.assertEqual(sound.state_ambience(self.room1, "crackling")[0]
                         ["sound"], self.fire.hash)


@tag("world")
class SayingItInAForm(_Ambient):

    def test_adding_and_taking_out_live(self):
        from world.makers import sounding

        where = sounding.of_object(lambda ctx: self.room1)
        ctx = menus.Context(self.char1, ambience_where=where(None))
        ctx.draft.update({"sound": self.wind.hash, "volume": 60, "pan": -20})
        said = sounding._add(ctx)
        self.assertIn(self.wind.name, said)
        self.assertEqual(sound.own_ambience(self.room1),
                         [{"sound": self.wind.hash, "volume": 60,
                           "pan": -20}])
        sounding._dropper(0)(ctx)
        self.assertEqual(sound.own_ambience(self.room1), [])

    def test_the_area_s_only_when_there_is_an_area(self):
        from world import zones
        from world.makers import sounding

        where = sounding.of_zone(lambda ctx: self.room2)
        self.assertIsNone(where(None))
        zones.attach(self.room1, self.room2, "The Cellars")
        self.assertIsNotNone(where(None))


# ---------------------------------------------------------------------------
# genny. docs/archived/sound.md 9, phase 5
# ---------------------------------------------------------------------------

from world import sound_gen  # noqa: E402

BEEP = {"layers": [{"type": "sfx", "kind": "beep",
                    "params": {"dur": 0.05}}]}


@tag("unit")
class CheckingASpec(SimpleTestCase):
    """Nothing genny would read or write a path for gets through."""

    def wrong(self, spec):
        return " ".join(sound_gen.check(spec)[1])

    def test_a_good_spec_passes_and_loses_its_out(self):
        spec, wrong = sound_gen.check(dict(BEEP, out="C:/anywhere.wav",
                                           out_dir="/etc"))
        self.assertEqual(wrong, [])
        self.assertNotIn("out", spec)
        self.assertNotIn("out_dir", spec)

    def test_a_file_layer_may_not_name_a_path(self):
        with mock.patch("world.sound.resolve", return_value=None):
            said = self.wrong({"layers": [{"type": "file",
                                           "path": "C:/secret.wav"}]})
        self.assertIn("never a path", said)

    def test_names_genny_does_not_have(self):
        self.assertIn("no sound effect called nope", self.wrong(
            {"layers": [{"type": "sfx", "kind": "nope"}]}))
        self.assertIn("no instruments", self.wrong(
            {"layers": [{"type": "seq", "inst": "kazoo9"}]}).replace(
                "no instrument", "no instruments"))
        self.assertIn("no effect called wobble", self.wrong(
            dict(BEEP, fx=[{"type": "wobble"}])))
        self.assertIn("no layer type", self.wrong(
            {"layers": [{"type": "nonsense"}]}))

    def test_the_limits(self):
        self.assertIn("longer than 30", self.wrong(dict(BEEP, duration=40)))
        self.assertEqual(sound_gen.check(dict(BEEP, duration=40,
                                              loop=True))[1], [])
        self.assertIn("more than 64", self.wrong(
            {"layers": [dict(BEEP["layers"][0], repeat=1000)]}))
        many = {"layers": [dict(BEEP["layers"][0]) for _ in range(40)]}
        self.assertIn("40 layers", self.wrong(many))
        deep = {"type": "group", "layers": [dict(BEEP["layers"][0])]}
        for _ in range(5):
            deep = {"type": "group", "layers": [deep]}
        self.assertIn("nest", self.wrong({"layers": [deep]}))
        self.assertIn("sample rate", self.wrong(dict(BEEP, sr=8000)))

    def test_one_sound_at_a_time(self):
        self.assertIn("one sound at a time", self.wrong({"sounds": [BEEP]}))
        self.assertIn("not JSON", self.wrong("{nope"))


@tag("world")
class Rendering(_Stored):

    def render(self, spec, **kwargs):
        found = {}
        given = dict(name="a beep", description="A short high beep.",
                     added_by=self.account, charged_to=self.account,
                     on_done=lambda asset, said: found.update(asset=asset,
                                                              said=said),
                     on_fail=lambda why: found.update(why=why), wait=True)
        given.update(kwargs)
        sound_gen.render(spec, **given)
        return found

    def test_a_spec_becomes_a_steady_ogg_asset(self):
        found = self.render(BEEP)
        asset = found["asset"]
        self.assertEqual((asset.type, asset.version, asset.origin),
                         ("sound", "vorbis", "tool"))
        self.assertEqual(asset.charged_to, self.account)
        self.assertEqual(asset.made_with["tool"], "render")
        self.assertEqual(asset.made_with["spec"], BEEP)
        self.assertIn("genny", asset.author)

    def test_asked_once(self):
        first = self.render(BEEP)["asset"]
        with mock.patch.object(sound_gen, "_render_file") as again:
            second = self.render(BEEP)
        again.assert_not_called()
        self.assertEqual(second["asset"].pk, first.pk)

    def test_a_render_that_runs_too_long_is_stopped(self):
        import subprocess

        with mock.patch.object(subprocess, "run",
                               side_effect=subprocess.TimeoutExpired("x", 1)):
            found = self.render(BEEP)
        self.assertIn("was stopped", found["why"])

    def test_what_genny_refuses_is_said_without_a_path(self):
        spec = {"layers": [{"type": "sfx", "kind": "beep",
                            "params": {"nonsense": 1}}]}
        found = self.render(spec)
        self.assertIn("genny could not make it", found["why"])
        self.assertNotIn("aimud-genny-", found["why"])

    def test_a_file_layer_builds_on_a_sound_here(self):
        base = self.render(BEEP)["asset"]
        found = self.render({"layers": [{"type": "file",
                                         "path": base.hash[:12]}],
                             "fx": [{"type": "reverb", "mix": 0.3}]},
                            name="a beep in a hall")
        self.assertNotEqual(found["asset"].hash, base.hash)

    def test_a_panned_copy_belongs_to_its_source(self):
        base = self.render(BEEP)["asset"]
        self.assertIs(sound_gen.panned(base, 0), base)
        copy_made = sound_gen.panned(base, 80, wait=True)
        self.assertEqual(copy_made.origin, "derived")
        self.assertEqual(copy_made.made_with["pan"], 67)
        self.assertIsNone(copy_made.charged_to)
        self.assertEqual(sound_gen.panned(base, 70).pk, copy_made.pk)
        self.assertEqual(assets.pool_used(), 0)
        assets.delete(base)
        self.assertIsNone(assets.find(copy_made.hash))

    def test_where_a_pan_lands(self):
        self.assertEqual([sound_gen.position(pan) for pan in
                          (-100, -60, -10, 0, 20, 55, 99)],
                         [-100, -67, 0, 0, 33, 67, 100])


@tag("world")
class TheGennyForm(_Stored):

    def test_a_sound_effect_with_its_parameters_and_effects(self):
        from commands import sound_subject

        spec = sound_subject.spec_of({
            "how": "sfx", "which": "beep", "p_freq": "880", "p_dur": "0.1",
            "fx": "reverb:mix=0.3 lowpass:cutoff=2000", "loop": True,
            "seconds": 4})
        self.assertEqual(spec["layers"], [{"type": "sfx", "kind": "beep",
                                           "params": {"freq": 880,
                                                      "dur": 0.1}}])
        self.assertEqual(spec["fx"], [{"type": "reverb", "mix": 0.3},
                                      {"type": "lowpass", "cutoff": 2000}])
        self.assertEqual((spec["loop"], spec["duration"]), (True, 4))

    def test_the_fields_are_genny_s_own(self):
        from commands import sound_subject

        ctx = menus.Context(self.char1)
        ctx.draft.update({"how": "sfx", "which": "beep"})
        keys = {field.key for field in sound_subject._param_fields(ctx)}
        self.assertEqual(keys, {"p_" + name for name in
                                sound_gen.catalog()["sfx"]["beep"]["params"]})
        names = [value for value, _label in
                 sound_subject._which_options(ctx)]
        self.assertIn("beep", names)

    def test_editing_one_opens_on_how_it_was_made(self):
        from commands import sound_subject

        found = {}
        sound_gen.render(BEEP, name="a beep", description="A beep.",
                         added_by=self.account, charged_to=self.account,
                         on_done=lambda asset, said: found.update(a=asset),
                         on_fail=found.update, wait=True)
        draft = sound_subject.draft_of(found["a"])
        self.assertEqual(draft["how"], "spec")
        self.assertEqual(sound_subject.spec_of(draft), BEEP)

    def test_create_sound_offers_its_sources(self):
        from commands import sound_subject

        self.assertEqual([key for key, *_rest in sound_subject.SOURCES],
                         ["genny"])


@tag("world")
class ForAModel(_Stored):

    def test_the_catalog_is_a_lookup(self):
        from world import lookups, toolbox

        tool = lookups.named("sound_catalog")[0]
        said = []
        tool.handler(toolbox.ToolContext(), {"section": "sfx",
                                             "name": "beep"}, said.append)
        self.assertIn("freq", said[0])
        said = []
        tool.handler(toolbox.ToolContext(), {}, said.append)
        self.assertIn("instruments", said[0])

    def test_the_manual_has_a_page(self):
        from world import manual

        self.assertIn("sound", manual.PAGES)
        self.assertIn("play_sound", manual.page("sound"))

    def test_a_sound_is_measured_for_whoever_cannot_hear_it(self):
        assets.take_in_builtins()
        said = sound.measure(assets.builtin("menu/huh"))
        self.assertIn("seconds", said)
        self.assertIn("sharpness", said)


# ---------------------------------------------------------------------------
# Models. docs/archived/sound.md 9.5, phase 6
# ---------------------------------------------------------------------------

@tag("world")
class AModelMakingASound(_Stored):

    def setUp(self):
        super().setUp()
        from tests.support import FakeSponsor

        self.room1.db.world_root = self.room1
        self.sponsor = FakeSponsor(world_root=self.room1, actor=self.char1)
        self.sponsor.account = self.account

    def call(self, args):
        from world import toolbox

        said = []
        tool = sound_gen.make_sound_tool()
        ctx = toolbox.ToolContext(world_root=self.room1, sponsor=self.sponsor)
        real = sound_gen.render
        with mock.patch.object(sound_gen, "render",
                               lambda *a, **k: real(*a, **dict(k, wait=True))):
            tool.handler(ctx, args, said.append)
        return said[0], tool.offered(ctx)

    def test_sounds_are_a_permit_and_the_type_names_it(self):
        from world import permits

        self.assertIn("sounds", permits.MADE)
        self.assertEqual(asset_types.get("sound").permit, "sounds")

    def test_it_makes_one_and_answers_its_id(self):
        said, offered = self.call({"spec": json.dumps(BEEP), "name": "a beep",
                                   "description": "A short beep."})
        self.assertTrue(offered)
        made = assets.search("sound").get(name="a beep")
        self.assertIn(made.hash[:12], said)
        self.assertEqual(made.charged_to, self.account)
        self.assertEqual(made.made_with["asked_by"], "model")

    def test_a_world_that_says_never_is_not_offered_it(self):
        from world import permits

        permits.choose(self.room1, "sounds", permits.NEVER)
        said, offered = self.call({"spec": json.dumps(BEEP), "name": "a beep",
                                   "description": "A short beep."})
        self.assertFalse(offered)
        self.assertIn("does not have new sounds made", said)
        self.assertFalse(assets.search("sound").filter(name="a beep").exists())

    def test_the_rule_loop_is_told_only_what_it_may_do(self):
        from world import permits, rule_gen

        self.assertEqual(rule_gen._sounds_said(self.sponsor), "")
        assets.take_in_builtins()
        said = rule_gen._sounds_said(self.sponsor)
        self.assertIn("play_sound", said)
        self.assertIn("make_sound", said)
        permits.choose(self.room1, "sounds", permits.NEVER)
        said = rule_gen._sounds_said(self.sponsor)
        self.assertIn("play_sound", said)
        self.assertNotIn("make_sound", said)


@tag("world")
class AServiceSendingASound(_Stored):
    """A tool's sound file is kept and heard. docs/archived/sound.md 9.5."""

    def setUp(self):
        super().setUp()
        self.room1.db.world_root = self.room1

    def test_the_destination_reads_and_is_said(self):
        from world import tool_calls

        self.assertEqual(tool_calls.read_target("sound:everyone"),
                         {"to": "sound", "role": "everyone"})
        self.assertEqual(tool_calls.read_target("sound"),
                         {"to": "sound", "role": "everyone"})
        self.assertIn("a sound played to",
                      tool_calls.said_target("sound:actor"))

    def test_the_file_is_kept_once_and_played(self):
        from world import services, tool_calls

        answer = services.Answer(text="A bell rings once.",
                                 files=[(tone(), "audio/ogg")])
        effect = {"type": "call_tool", "tool": "bells.ring",
                  "results": {"file": "sound:everyone"},
                  tool_calls.ANSWER: answer, tool_calls.CALLED: {"n": "1"}}
        played = []
        with mock.patch("world.sponsor.of", return_value=mock.Mock(
                payer=self.account, actor=self.char1)), \
                mock.patch.object(sound, "heard", lambda listener, found,
                                  **kwargs: played.append(found) or 1), \
                mock.patch("world.services.find", return_value=(None, {})):
            tool_calls.apply(self.char1, self.room1, effect, {}, self.room1)
            tool_calls.apply(self.char1, self.room1, effect, {}, self.room1)
        kept = assets.search("sound").filter(origin="tool")
        self.assertEqual(kept.count(), 1)
        self.assertEqual(kept[0].description, "A bell rings once.")
        self.assertEqual(played, [kept[0], kept[0]])


# ---------------------------------------------------------------------------
# The sound ruleset. docs/archived/sound.md 10, phase 7
# ---------------------------------------------------------------------------

@tag("world")
class TheSoundRuleset(_Ambient):

    def setUp(self):
        super().setUp()
        from world import rulesets

        self.doc = rulesets.get("sound")

    def test_it_is_a_ruleset_this_game_reads_and_not_a_default(self):
        from world import rulesets

        self.assertIsNotNone(self.doc)
        self.assertEqual(rulesets.problems(self.doc), [])
        self.assertFalse(self.doc.get("default"))

    def test_every_sound_it_names_ships_with_the_game(self):
        named = set()
        for entry in self.doc.get("kinds", []) + self.doc.get("conditions",
                                                              []):
            named |= {one["sound"] for one in entry.get("ambience", [])}
        for rule in self.doc["rules"]:
            named |= {effect["sound"] for effect in rule["effects"]}
        for ref in sorted(named):
            found = assets.builtin(ref)
            self.assertIsNotNone(found, ref)
            self.assertEqual(found.type, "sound", ref)
            self.assertTrue(found.description, ref)

    def test_a_world_using_it_hears_its_places_and_its_fires(self):
        from world import rulesets, verbs

        rulesets._apply(self.room1, self.doc, {})
        self.room1.db.kinds = ["rain_forest.n.01"]
        self.assertEqual([asset.name for asset in self.heard()],
                         ["a forest"])
        verbs.apply_states(self.obj1, add=["burning"], world_root=self.room1,
                           announce=False)
        self.assertIn("a fire burning",
                      [asset.name for asset in self.heard()])

    def test_naming_a_kind_for_its_sound_does_not_settle_it(self):
        from world import kinds, rulesets

        rulesets._apply(self.room1, self.doc, {})
        self.assertNotIn("affordances",
                         kinds.spec(self.room1, "forest.n.01") or {})

    def test_its_rules_play_through_the_effect(self):
        from world import effects, rulebooks, rulesets

        rulesets._apply(self.room1, self.doc, {})
        opened = [rule for rule in rulebooks.all_rules(self.room1)
                  if rule.get("name") == "a door creaks open"]
        self.assertEqual(len(opened), 1)
        played = []
        with mock.patch.object(sound, "heard", lambda listener, found,
                               **kwargs: played.append(found) or 1):
            effects.apply(self.char1, self.room1, opened[0]["effects"])
        self.assertEqual([found.name for found in played],
                         ["a door opening"])
        self.assertIn(assets.builtin("ruleset/door_open"),
                      sound.used_in(self.room1))


# ---------------------------------------------------------------------------
# The web client. docs/archived/sound.md 3.1, phase 8
# ---------------------------------------------------------------------------

@tag("unit")
class TheWebClient(SimpleTestCase):

    def test_its_page_loads_the_sound_plugin_beside_evennia_s_own(self):
        from django.contrib.auth.models import AnonymousUser
        from django.template.loader import get_template
        from django.test import RequestFactory

        request = RequestFactory().get("/webclient/")
        request.user = AnonymousUser()
        html = get_template("webclient/webclient.html").render({}, request)
        self.assertIn("webclient/js/plugins/aimud_sound.js", html)
        self.assertIn("webclient/js/plugins/default_in.js", html)

    def test_it_is_told_the_pan_and_no_other_client_is(self):
        web = FakeSession("webclient/websocket", CLIENT_MEDIA=True)
        self.assertTrue(sound._web(web))
        self.assertFalse(sound._web(FakeSession(CLIENT_MEDIA=True)))
