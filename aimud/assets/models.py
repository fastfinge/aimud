"""
One record per file the game keeps. docs/archived/assets.md 3.1.

A Django model rather than attributes on a script, because the questions
asked of it -- how much one account is using, what was added this week,
which assets of a type match some words -- are queries, and an S3 store or a
second server reading the same register would want them to be.
"""

from django.conf import settings
from django.db import models


class Asset(models.Model):
    #: SHA-256 of the contents: the identity, and the file's name in the
    #: store. One file, one record -- the same file added twice is one asset.
    hash = models.CharField(max_length=64, unique=True)
    #: A key in `world.asset_types`.
    type = models.CharField(max_length=32, db_index=True)
    #: What the type read off the file: a world document's format, say.
    version = models.CharField(max_length=32, blank=True, default="")

    #: What players call it. Not unique: two "rain" sounds may exist.
    name = models.CharField(max_length=120, db_index=True)
    #: Required. To a screen reader user and to a model, this is the asset.
    description = models.TextField()
    size = models.BigIntegerField()

    #: Who brought it in. Kept for review after it is given up.
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assets_added")
    #: Whose quota it counts against: whoever paid for it to exist. None is
    #: the server's pool -- given up, or its account deleted, which
    #: SET_NULL makes the same thing. docs/archived/assets.md 7.
    charged_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assets_charged")
    added = models.DateTimeField(auto_now_add=True, db_index=True)
    #: When anything last used it, for choosing what leaves a full pool.
    last_used = models.DateTimeField(null=True, blank=True)

    UPLOAD, URL, IMPORT, TOOL = "upload", "url", "import", "tool"
    EXPORT, FOLDER = "export", "folder"
    ORIGINS = [(UPLOAD, "uploaded"), (URL, "fetched from a URL"),
               (IMPORT, "came with an imported world"), (TOOL, "made by a tool"),
               (EXPORT, "exported from a world here"),
               (FOLDER, "put in the shared folder by hand")]
    origin = models.CharField(max_length=16, choices=ORIGINS)
    #: Where it was fetched from, if anywhere: for fetching again.
    source = models.TextField(blank=True, default="")
    author = models.CharField(max_length=200, blank=True, default="")
    licence = models.CharField(max_length=200, blank=True, default="")
    #: For a tool: the service and tool, the model and its settings, and the
    #: request -- enough to say how it was made and to match a repeat.
    made_with = models.JSONField(blank=True, default=dict)

    PRESENT, MISSING = "present", "missing"
    status = models.CharField(
        max_length=16, default=PRESENT,
        choices=[(PRESENT, "present"), (MISSING, "missing")])

    class Meta:
        ordering = ["-added"]

    def __str__(self):
        return f"{self.name} ({self.type}, {self.hash[:12]})"
