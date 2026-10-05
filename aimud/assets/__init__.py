"""
The register of assets: one record per file the game keeps.

Only the record lives here, because Django wants a model in an app. What an
asset is, how one is added and who it is charged to is `world/assets.py`;
what kinds of file there are is `world/asset_types.py`; where the bytes live
is `world/asset_store.py`. docs/archived/assets.md.
"""
