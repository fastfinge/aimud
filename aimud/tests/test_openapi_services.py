"""
OpenAPI services: an MCP server the game starts for itself from a spec.

docs/mcp-client.md §3.3 and §12. FastMCP builds a server from the spec and it
is served in process, so everything above it -- listing, classifying,
calling, fingerprints -- is the same code an MCP server goes through. What is
OpenAPI's own is held here: the spec read from a file, every operation off
until the owner switches it on, a level guessed from the HTTP method, and a
key sent where the spec says.

Nothing touches the network: the API behind the spec is an httpx mock.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, tag

from tests.base import GameTest
from world import services

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Pubs", "version": "1"},
    "servers": [{"url": "https://pubs.example"}],
    "components": {"securitySchemes": {
        "key": {"type": "apiKey", "in": "header", "name": "X-Pubs-Key"}}},
    "paths": {"/pubs": {
        "get": {
            "operationId": "find_pubs", "summary": "Find pubs near a place",
            "parameters": [{"name": "near", "in": "query", "required": True,
                            "schema": {"type": "string"}}],
            "responses": {"200": {"description": "ok", "content": {
                "application/json": {"schema": {
                    "type": "object",
                    "properties": {"names": {"type": "array",
                                             "items": {"type": "string"}}}}}}}}},
        "post": {
            "operationId": "add_pub", "summary": "Add a pub",
            "requestBody": {"content": {"application/json": {"schema": {
                "type": "object", "properties": {"name": {"type": "string"}}}}}},
            "responses": {"200": {"description": "ok"}}}}},
}


@tag("unit")
class WhereTheKeyGoes(SimpleTestCase):

    def test_an_api_key_header(self):
        self.assertEqual(services.spec_key(SPEC), (services.HEADER, "X-Pubs-Key"))

    def test_a_query_parameter(self):
        spec = {"components": {"securitySchemes": {
            "k": {"type": "apiKey", "in": "query", "name": "apikey"}}}}
        self.assertEqual(services.spec_key(spec), (services.QUERY, "apikey"))

    def test_a_bearer_token(self):
        spec = {"components": {"securitySchemes": {
            "b": {"type": "http", "scheme": "bearer"}}}}
        self.assertEqual(services.spec_key(spec), (services.BEARER, ""))

    def test_nothing_said(self):
        self.assertEqual(services.spec_key({}), (None, None))

    def test_methods_by_operation(self):
        self.assertEqual(services.spec_methods(SPEC),
                         {"find_pubs": "GET", "add_pub": "POST"})


@tag("world")
class AnOpenAPIService(GameTest):

    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.spec_path = Path(self.folder.name) / "pubs.json"
        self.spec_path.write_text(json.dumps(SPEC), encoding="utf-8")
        self.requests = []
        self.old = services._MANAGER
        services._MANAGER = services._Manager()
        self.addCleanup(self.restore)
        real = services._http_client

        def mocked(record, base_url=None):
            import httpx2

            client = real(record, base_url=base_url)
            client._transport = httpx2.MockTransport(self.answer)
            return client

        patcher = mock.patch.object(services, "_http_client", mocked)
        patcher.start()
        self.addCleanup(patcher.stop)

    def restore(self):
        manager = services._MANAGER
        for name in list(manager.connections):
            manager.drop(name)
        services._MANAGER = self.old

    def answer(self, request):
        import httpx2

        self.requests.append(request)
        return httpx2.Response(200, json={"names": ["The Lamb", "The Eagle"]})

    def record(self, **extra):
        record = services.blank("pubs", services.OPENAPI)
        record["spec"] = str(self.spec_path)
        record.update(extra)
        return record

    def test_every_operation_is_listed_and_guessed_from_its_method(self):
        tools, status = services.connect_and_list(self.record())
        self.assertEqual(status, "")
        self.assertEqual(tools["find_pubs"]["level"], services.LOOKS)
        self.assertEqual(tools["add_pub"]["level"], services.ACTS)
        self.assertEqual(tools["find_pubs"]["method"], "GET")

    def test_every_operation_starts_switched_off(self):
        """§12: the spec lists everything the API has; the owner chooses."""
        tools, _status = services.connect_and_list(self.record())
        merged = services.merge_tools({}, tools, openapi=True)
        self.assertFalse(any(info["on"] for info in merged.values()))

    def test_a_call_reaches_the_api_with_the_key_where_the_spec_says(self):
        record = self.record(auth=services.KEY_AUTH, key="pubs-secret")
        answer = services.call(record, "find_pubs", {"near": "London"})
        self.assertTrue(answer.ok, answer)
        self.assertEqual(answer.field("names"), ["The Lamb", "The Eagle"])
        sent = self.requests[-1]
        self.assertEqual(sent.url.params.get("near"), "London")
        self.assertEqual(sent.headers.get("X-Pubs-Key"), "pubs-secret")
        self.assertIn("aimud", sent.headers.get("User-Agent"))

    def test_a_spec_that_is_not_there_is_said_and_not_raised(self):
        tools, status = services.connect_and_list(
            self.record(spec=str(Path(self.folder.name) / "missing.json")))
        self.assertIsNone(tools)
        self.assertTrue(status)

    def test_a_yaml_spec_is_read_too(self):
        import yaml

        path = Path(self.folder.name) / "pubs.yaml"
        path.write_text(yaml.safe_dump(SPEC), encoding="utf-8")
        tools, status = services.connect_and_list(self.record(spec=str(path)))
        self.assertEqual(status, "")
        self.assertIn("find_pubs", tools)
