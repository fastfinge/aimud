"""
The forms behind every maker, one module per kind of thing.

Kept out of the modules that own the data -- `kinds.py`, `traits.py`,
`rulebooks.py` -- so that a register can be read and written without importing
the menu engine, which is what lets a test, a ruleset and a generator use one
without any of the other two. `world/making.py` is the table that gathers them.
"""
