"""
Freesound: which licences are kept, what a search asks and answers, and
`create sound freesound` hearing and keeping one.

Nothing here reaches freesound.org. Searches answer from a stand-in for
httpx, and fetching a preview writes a tone made in memory.
"""

import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase, override_settings, tag

from tests.test_sound import _Stored, tone
from world import assets, freesound, menus

CC0 = "http://creativecommons.org/publicdomain/zero/1.0/"
BY = "https://creativecommons.org/licenses/by/4.0/"
BY_NC = "https://creativecommons.org/licenses/by-nc/4.0/"
SAMPLING = "http://creativecommons.org/licenses/sampling+/1.0/"


def raw(id_=1, license=CC0, **extra):
    """One result as Freesound sends it."""
    found = {"id": id_, "name": "Door_creak.wav", "username": "someone",
             "license": license, "duration": 2.345, "tags": ["door", "creak"],
             "description": "A <b>wooden</b> door &amp; its hinge.",
             "url": f"https://freesound.org/people/someone/sounds/{id_}/",
             "previews": {"preview-hq-ogg":
                          f"https://cdn.freesound.org/previews/{id_}-hq.ogg"}}
    found.update(extra)
    return found


@tag("unit")
class WhichLicences(SimpleTestCase):

    def test_each_licence_is_named_with_whether_it_may_earn(self):
        self.assertEqual(freesound.licence_of(CC0), ("CC0 1.0", True))
        self.assertEqual(freesound.licence_of(BY), ("CC-BY 4.0", True))
        self.assertEqual(freesound.licence_of(BY_NC), ("CC-BY-NC 4.0", False))
        self.assertIsNone(freesound.licence_of(SAMPLING))
        self.assertIsNone(freesound.licence_of(""))

    def test_non_commercial_is_kept_only_where_the_server_says_so(self):
        self.assertTrue(freesound.allowed(CC0))
        self.assertTrue(freesound.allowed(BY))
        self.assertFalse(freesound.allowed(BY_NC))
        with override_settings(FREESOUND_NONCOMMERCIAL=True):
            self.assertTrue(freesound.allowed(BY_NC))
            self.assertFalse(freesound.allowed(SAMPLING))

    def test_the_search_asks_for_only_what_is_kept(self):
        said = freesound._filter(30)
        self.assertIn('"Creative Commons 0" OR "Attribution"', said)
        self.assertNotIn("NonCommercial", said)
        self.assertIn("duration:[0 TO 30]", said)
        with override_settings(FREESOUND_NONCOMMERCIAL=True):
            self.assertIn('"Attribution NonCommercial"', freesound._filter(0))


@tag("unit")
class AResult(SimpleTestCase):

    def test_it_is_named_described_and_credited(self):
        result = freesound.result_of(raw(license=BY))
        self.assertEqual(result["name"], "Door creak")
        self.assertEqual(result["description"], "A wooden door & its hinge.")
        self.assertEqual(result["seconds"], 2.3)
        self.assertEqual(freesound.credit(result),
                         '"Door_creak.wav" by someone, '
                         "https://freesound.org/people/someone/sounds/1/")
        self.assertEqual(freesound.licence(result), f"CC-BY 4.0, {BY}")

    def test_a_result_with_no_description_is_described_by_its_tags(self):
        result = freesound.result_of(raw(description=""))
        self.assertEqual(result["description"],
                         "Door creak, tagged door, creak.")

    def test_a_long_description_is_cut_at_a_word(self):
        result = freesound.result_of(raw(description="word " * 400))
        self.assertLessEqual(len(result["description"]),
                             freesound.MOST_DESCRIPTION + 3)
        self.assertTrue(result["description"].endswith("word..."))

    def test_one_under_a_licence_not_kept_or_with_no_preview_is_dropped(self):
        self.assertIsNone(freesound.result_of(raw(license=SAMPLING)))
        self.assertIsNone(freesound.result_of(raw(license=BY_NC)))
        self.assertIsNone(freesound.result_of(raw(previews={})))


class _Answer:
    def __init__(self, status, body=None):
        self.status_code = status
        self.body = body

    def json(self):
        if self.body is None:
            raise ValueError("not JSON")
        return self.body


@tag("unit")
@override_settings(FREESOUND_CLIENT_SECRET="the-secret")
class Searching(SimpleTestCase):

    def search(self, answer):
        calls = []

        def get(url, **kwargs):
            calls.append(kwargs)
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch("httpx.get", get):
            return freesound.search("door creak", 30), calls

    def test_the_key_is_a_header_and_never_in_the_address(self):
        (found, count), calls = self.search(_Answer(200, {
            "count": 3, "results": [raw(1), raw(2, license=SAMPLING),
                                    raw(3, license=BY)]}))
        self.assertEqual(calls[0]["headers"]["Authorization"],
                         "Token the-secret")
        self.assertNotIn("the-secret", repr(calls[0]["params"]))
        self.assertEqual([result["id"] for result in found], [1, 3])
        self.assertEqual(count, 3)

    def test_the_little_words_are_left_out_of_a_search(self):
        _found, calls = self.search(_Answer(200, {"count": 0,
                                                  "results": []}))
        self.assertEqual(calls[0]["params"]["query"], "door creak")
        self.assertEqual(freesound.keywords("rain on a tent"), "rain tent")
        self.assertEqual(freesound.keywords("the"), "the")

    def test_what_goes_wrong_is_said(self):
        import httpx

        for answer, said in ((_Answer(401), "refused this server's key"),
                             (_Answer(429), "too often"),
                             (_Answer(500), "answered 500"),
                             (_Answer(200), "could not be read"),
                             (httpx.ConnectError("no"), "could not be reached")):
            with self.assertRaises(freesound.Unavailable) as caught:
                self.search(answer)
            self.assertIn(said, str(caught.exception))

    @override_settings(FREESOUND_CLIENT_SECRET="")
    def test_there_is_no_search_without_a_key(self):
        self.assertFalse(freesound.available())
        with self.assertRaises(freesound.Unavailable):
            freesound.search("door")


@tag("world")
class TheFreesoundForm(_Stored):
    """Hearing a result and keeping it, with the thread and the fetch made
    to answer at once."""

    def setUp(self):
        super().setUp()
        from twisted.internet import defer

        self.heard = []
        self.char1.msg = lambda text="", **kw: self.heard.append(
            str(text[0] if isinstance(text, tuple) else text))
        self.fetched = []

        def fetch(url, most):
            self.fetched.append(url)
            handle, path = tempfile.mkstemp()
            with os.fdopen(handle, "wb") as out:
                out.write(tone(pitch=7))
            return path

        for patcher in (
                mock.patch("twisted.internet.threads.deferToThread",
                           lambda work, *args: defer.maybeDeferred(work,
                                                                   *args)),
                mock.patch.object(assets, "fetch", fetch)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.result = freesound.result_of(raw(license=BY))
        self.root = menus.Context(self.char1)
        self.ctx = self.root.child(result=self.result,
                                   root_draft=self.root.draft)
        self.ctx.draft = {"name": "a creaking door",
                          "description": "A wooden door, slowly opening."}

    def test_keeping_one_credits_it_and_remembers_where_it_came_from(self):
        from commands import sound_subject

        sound_subject._keep_result(self.ctx)
        asset = assets.search("sound").get()
        self.assertEqual(asset.name, "a creaking door")
        self.assertEqual(asset.origin, "url")
        self.assertEqual(asset.source, self.result["preview"])
        self.assertIn("by someone", asset.author)
        self.assertEqual(asset.licence, f"CC-BY 4.0, {BY}")
        self.assertIn("credit goes wherever it does: \"Door_creak.wav\" by "
                      "someone", "\n".join(self.heard))

    def test_one_heard_then_kept_is_fetched_once_and_renamed(self):
        from commands import sound_subject

        sound_subject._hear_result(self.ctx)
        sound_subject._keep_result(self.ctx)
        self.assertEqual(len(self.fetched), 1)
        asset = assets.search("sound").get()
        self.assertEqual(asset.name, "a creaking door")
        sound_subject._forget_all_tried(self.root, "quit")
        self.assertTrue(assets.search("sound").exists())

    def test_one_heard_and_not_kept_is_thrown_away_on_closing(self):
        from commands import sound_subject

        sound_subject._hear_result(self.ctx)
        self.assertEqual(assets.search("sound").get().description,
                         sound_subject.TRYING)
        sound_subject._forget_all_tried(self.root, "quit")
        self.assertFalse(assets.search("sound").exists())

    def test_it_needs_a_name_and_a_description(self):
        from commands import sound_subject

        self.ctx.draft["description"] = ""
        with self.assertRaises(menus.Refuse):
            sound_subject._keep_result(self.ctx)

    def test_the_licences_are_said_as_a_list(self):
        self.assertEqual(freesound.allowed_said(), "CC0 and CC-BY")
        with override_settings(FREESOUND_NONCOMMERCIAL=True):
            self.assertEqual(freesound.allowed_said(),
                             "CC0, CC-BY and CC-BY-NC")

    def test_each_result_opens_holding_freesound_s_own_words(self):
        from commands import sound_subject

        self.root.draft["found"] = [self.result]
        item = sound_subject._results_items(self.root)[0]
        child = item.context(self.root)
        self.assertEqual(child.draft, {"name": "Door creak",
                                       "description": self.result[
                                           "description"]})
        self.assertIs(child.root_draft, self.root.draft)


@tag("unit")
class OfferedOnlyWithAKey(SimpleTestCase):

    def sources(self):
        from commands import sound_subject

        return [key for key, *_rest in sound_subject._sources()]

    @override_settings(FREESOUND_CLIENT_SECRET="")
    def test_without_one_there_is_only_genny(self):
        self.assertEqual(self.sources(), ["genny"])

    @override_settings(FREESOUND_CLIENT_SECRET="the-secret")
    def test_with_one_there_is_freesound(self):
        self.assertEqual(self.sources(), ["genny", "freesound"])
