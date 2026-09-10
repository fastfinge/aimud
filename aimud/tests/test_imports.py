"""
Names used in one function and imported in another.

This project imports inside functions almost everywhere, deliberately: it keeps
module import order from mattering in a codebase where nearly everything refers
to nearly everything else. The cost is a trap that Python does not catch and a
linter is not usually run to find -- `from world import llm` inside one function
does nothing for the function below it, and the mistake is invisible until
somebody walks that exact line.

It has happened. `models` raised `NameError: name 'llm' is not defined` on the
first world built with this engine, because phase 0's refactor put the import in
the helper that fetches and the call in the function that schedules it. Nothing
failed until a player typed the command, weeks later.

So: read every function's own scope, and say which names it uses that neither it
nor the module ever bound. Free, exhaustive, and it runs in the same second as
the rest of tier A.
"""

import ast
import builtins
import pathlib

from django.test import SimpleTestCase, tag

GAME = pathlib.Path(__file__).resolve().parent.parent

#: Files that are not the game's own code.
SKIP = ("__pycache__", "migrations", "tests")

#: Names that are there without anybody importing them.
GIVEN = frozenset(dir(builtins)) | {"self", "cls", "__file__", "__name__",
                                    "__doc__", "__package__"}


def _bound_here(node):
    """Every name this node binds directly, not counting nested scopes."""
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                found.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(child, ast.ImportFrom):
            for alias in child.names:
                found.add(alias.asname or alias.name)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            found.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef)):
            found.add(child.name)
        elif isinstance(child, ast.arg):
            found.add(child.arg)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            found.add(child.name)
        elif isinstance(child, ast.Global):
            found.update(child.names)
        elif isinstance(child, ast.alias):
            found.add(alias_name(child))
    return {name for name in found if name}


def alias_name(alias):
    return (alias.asname or alias.name).split(".")[0]


def _module_level(tree):
    """
    What the module itself binds: imports, constants, defs and classes.

    Deliberately shallow -- a name bound inside a function is not module level,
    which is the whole point of this file.
    """
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias_name(alias))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                found.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx,
                                                              ast.Store):
                    found.add(child.id)
        elif isinstance(node, (ast.If, ast.Try, ast.With)):
            # A conditional import at module level still binds at module level.
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        found.add(alias_name(alias))
                elif isinstance(child, ast.ImportFrom):
                    for alias in child.names:
                        found.add(alias.asname or alias.name)
                elif isinstance(child, ast.Name) and isinstance(child.ctx,
                                                                ast.Store):
                    found.add(child.id)
    return found


def _functions(tree):
    """Every function in the file, with the scopes that enclose it."""
    found = []

    def walk(node, enclosing):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mine = _bound_here(child)
                found.append((child, enclosing | mine))
                walk(child, enclosing | mine)
            elif isinstance(child, ast.ClassDef):
                walk(child, enclosing | _bound_here(child))
            else:
                walk(child, enclosing)

    walk(tree, set())
    return found


def unresolved(path):
    """
    Names this file uses as `x.something` that nothing in scope ever bound.

    Attributes only, which is the narrow, high-signal case: `llm.fetch` where
    `llm` was never imported here. A bare name has too many honest ways to be
    defined elsewhere to be worth flagging.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    at_module = _module_level(tree) | GIVEN
    found = []
    for function, in_scope in _functions(tree):
        known = at_module | in_scope
        for node in ast.walk(function):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            if node.value.id in known:
                continue
            found.append((node.lineno, function.name, node.value.id))
    return found


def source_files():
    for path in sorted(GAME.rglob("*.py")):
        if any(part in SKIP for part in path.parts):
            continue
        yield path


@tag("unit")
class EveryNameIsInScopeWhereItIsUsed(SimpleTestCase):
    """
    The check itself. One line per offence, naming the function, because the
    fix is always "move the import" and the only hard part is finding it.
    """

    def test_nothing_uses_a_module_it_did_not_import(self):
        offences = []
        for path in source_files():
            for line, function, name in unresolved(path):
                offences.append(
                    f"{path.relative_to(GAME)}:{line} {function}() uses "
                    f"{name!r}, which nothing in scope imported")
        self.assertEqual(offences, [], "\n" + "\n".join(offences))


@tag("unit")
class TheCheckItself(SimpleTestCase):
    """
    Tested against known-good and known-bad shapes, because a scope check that
    quietly stopped finding anything would be worse than not having one.
    """

    def offences(self, source):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         encoding="utf-8") as handle:
            handle.write(source)
            path = pathlib.Path(handle.name)
        try:
            return [name for _line, _func, name in unresolved(path)]
        finally:
            path.unlink()

    def test_it_catches_the_bug_this_was_written_for(self):
        """The real one, reduced: imported in the helper, used in the caller."""
        self.assertEqual(self.offences(
            "def helper():\n"
            "    from world import llm\n"
            "    return llm.models()\n"
            "\n"
            "def caller():\n"
            "    llm.fetch(helper)\n"), ["llm"])

    def test_a_module_level_import_is_in_scope_everywhere(self):
        self.assertEqual(self.offences(
            "from world import llm\n"
            "\n"
            "def caller():\n"
            "    llm.fetch()\n"), [])

    def test_a_local_import_is_in_scope_in_its_own_function(self):
        self.assertEqual(self.offences(
            "def caller():\n"
            "    from world import llm\n"
            "    llm.fetch()\n"), [])

    def test_and_in_a_function_nested_inside_it(self):
        """A closure sees what encloses it, which is how half this code works."""
        self.assertEqual(self.offences(
            "def caller():\n"
            "    from world import llm\n"
            "    def inner():\n"
            "        llm.fetch()\n"
            "    inner()\n"), [])

    def test_an_argument_is_in_scope(self):
        self.assertEqual(self.offences(
            "def caller(llm):\n"
            "    llm.fetch()\n"), [])

    def test_a_caught_exception_is_in_scope(self):
        self.assertEqual(self.offences(
            "def caller():\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError as err:\n"
            "        return err.args\n"), [])

    def test_a_builtin_is_in_scope(self):
        self.assertEqual(self.offences(
            "def caller(text):\n"
            "    return str.upper(text)\n"), [])

    def test_a_conditional_module_import_is_in_scope(self):
        self.assertEqual(self.offences(
            "try:\n"
            "    import ujson as json\n"
            "except ImportError:\n"
            "    import json\n"
            "\n"
            "def caller():\n"
            "    return json.dumps({})\n"), [])

    def test_a_name_assigned_before_use_is_in_scope(self):
        self.assertEqual(self.offences(
            "def caller():\n"
            "    thing = object()\n"
            "    return thing.name\n"), [])

    def test_a_class_attribute_use_is_in_scope(self):
        self.assertEqual(self.offences(
            "import os\n"
            "\n"
            "class Thing:\n"
            "    def method(self):\n"
            "        return os.sep\n"), [])
