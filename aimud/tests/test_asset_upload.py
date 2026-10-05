"""
The website's upload page. docs/archived/assets.md 5.2, 14.

Driven with Django's test client, so the request goes through the real
middleware -- login, CSRF -- and the real upload handling.
"""

import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, tag

from tests.base import GameTest
from tests.test_assets import world_doc
from world import asset_store, assets

PAGE = "/assets/upload/"


@tag("world")
class TheUploadPage(GameTest):

    accounts = True

    def setUp(self):
        super().setUp()
        self.folder = tempfile.mkdtemp(prefix="aimud-upload-")
        previous = asset_store.use(asset_store.LocalStore(self.folder))
        self.addCleanup(asset_store.use, previous)
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.client = Client()
        self.client.force_login(self.account)

    def post(self, data=None, client=None, **fields):
        given = {"name": "The School", "description": "A haunted school.",
                 "file": SimpleUploadedFile("school.json",
                                            world_doc() if data is None else data)}
        given.update(fields)
        return (client or self.client).post(PAGE, given)

    def test_it_needs_somebody_logged_in(self):
        response = Client().get(PAGE)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_the_form_says_what_is_kept_and_how_much_room_there_is(self):
        response = self.client.get(PAGE)
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn("You are using", page)
        self.assertIn("A world document", page)

    def test_a_file_is_kept_for_whoever_uploaded_it(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIn("is kept", response.content.decode())
        asset = assets.search("world").first()
        self.assertEqual(asset.added_by, self.account)
        self.assertEqual(asset.origin, "upload")

    def test_a_file_that_is_not_one_is_refused(self):
        response = self.post(b"MZ\x90\x00 this is an executable")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a kind of file", response.content.decode())
        self.assertFalse(assets.search().exists())

    def test_an_oversized_file_stops_at_the_door(self):
        with mock.patch.object(assets, "largest", return_value=10):
            response = self.post()
        self.assertEqual(response.status_code, 413)
        self.assertFalse(assets.search().exists())

    def test_without_a_csrf_token_nothing_is_kept(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.account)
        response = self.post(client=strict)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(assets.search().exists())

    def test_the_page_never_shows_a_path(self):
        page = self.post().content.decode()
        self.assertNotIn(self.folder, page)
        self.assertNotIn(".media", page)
