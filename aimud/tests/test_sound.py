"""
Sound: the asset type, the sounds the game ships, and steady Ogg files.
docs/sound.md, phase 0.

Every file here is made by `soundfile` in memory, so the type is tested
against what a real encoder writes rather than against bytes that only
start the right way.
"""

import io
import os
import shutil
import tempfile

import numpy as np
import soundfile
from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import asset_store, asset_types, assets, ogg


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
