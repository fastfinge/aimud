"""
The models menu, as far as it decides what may be chosen.

Every job in this game uses tools, so a model whose published parameters leave
them out is not offered for any job. See docs/generator-tool-loops.md §3.2.
"""

from django.test import tag

from tests.base import GameTest
from commands import model_menu


@tag("world")
class ChoosingAModel(GameTest):
    accounts = True

    def setUp(self):
        super().setUp()
        self.account.ndb.openrouter_models_cache = [
            {"id": "a/tools", "supported_parameters": ["tools", "seed"]},
            {"id": "b/none", "supported_parameters": ["temperature"]},
            {"id": "c/unlisted"},
        ]

    def offered(self, **kwargs):
        text, options = model_menu.node_select_model(
            self.account, "", function="dialogue", **kwargs)
        ids = [option["desc"] for option in options
               if isinstance(option["key"], str) and option["key"].isdigit()]
        return text, ids

    def test_a_model_that_cannot_use_tools_is_not_offered(self):
        text, ids = self.offered()
        self.assertEqual(ids, ["a/tools", "c/unlisted"])
        self.assertIn("1 model that cannot use tools is not listed", text)

    def test_nor_is_it_found_by_searching_for_it(self):
        _text, ids = self.offered(search="b/none")
        self.assertEqual(ids, [])
