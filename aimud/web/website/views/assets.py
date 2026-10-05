"""
The upload page: a file straight from a player's machine. docs/archived/assets.md 5.2.

The in-game way in is `create asset` with a web address. This is for a
player who has a file and nowhere to put it. It goes through the same
`assets.add`, so it is checked exactly as a fetched file is: by its contents,
its type's version, its size and the uploader's quota.

**An oversized upload stops at the door.** Django keeps reading a file however
big it is unless something stops it, so `CappedUpload` does: it counts the
bytes as they arrive and gives up once they pass the most any type allows,
before the whole file has landed on disk.
"""

import os

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.files.uploadhandler import (StopUpload,
                                             TemporaryFileUploadHandler)
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, csrf_protect

from world import asset_types, assets


class CappedUpload(TemporaryFileUploadHandler):
    """Writes to a temporary file, and stops once it is bigger than allowed."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.received = 0
        self.too_big = False

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > assets.largest():
            self.too_big = True
            raise StopUpload(connection_reset=True)
        return super().receive_data_chunk(raw_data, start)


class UploadForm(forms.Form):
    file = forms.FileField(
        label="The file",
        help_text="What kind of file it is is read from what is in it, never "
                  "from its name.")
    name = forms.CharField(
        label="Its name", max_length=120,
        help_text="What players and models will call it.")
    description = forms.CharField(
        label="What it is", widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Say what it is as if to somebody who cannot see or hear "
                  "it: a screen reader user and a model will only ever know "
                  "it by this.")
    author = forms.CharField(label="Who made it", max_length=200,
                             required=False)
    licence = forms.CharField(label="Its licence", max_length=200,
                              required=False,
                              help_text="CC-BY 4.0, public domain, your own.")


def _quota(account):
    allowed = assets.quota_of(account)
    used = assets.size_said(assets.used_by(account))
    if allowed is None:
        return f"You are using {used}, with no limit."
    return f"You are using {used} of {assets.size_said(allowed)}."


def _page(request, form, said="", status=200):
    return render(request, "website/asset_upload.html", {
        "form": form, "said": said, "quota": _quota(request.user),
        "kinds": [(label, assets.size_said(most))
                  for _key, label, most in asset_types.described()],
        "page_title": "Add an asset",
    }, status=status)


@csrf_exempt
@login_required
def upload(request):
    """
    GET: the form. POST: keep the file, or say why not.

    Exempt here and protected in `_upload`, which is Django's own pattern
    for a view that changes its upload handlers: the CSRF check reads the
    body, and once the body is read the handlers can no longer be changed.
    The check still happens, on every POST, before anything is kept.
    """
    if request.method != "POST":
        return _page(request, UploadForm())
    # Swapped in before anything reads the body, which is when Django would
    # otherwise choose its own handlers.
    capped = CappedUpload(request)
    request.upload_handlers = [capped]
    return _upload(request, capped)


@csrf_protect
def _upload(request, capped):
    form = UploadForm(request.POST, request.FILES)
    if capped.too_big:
        return _page(request, UploadForm(),
                     f"That file is bigger than "
                     f"{assets.size_said(assets.largest())}, the most this "
                     f"server keeps.", status=413)
    if not form.is_valid():
        return _page(request, form, status=400)
    given = form.cleaned_data["file"]
    path = given.temporary_file_path() if hasattr(
        given, "temporary_file_path") else None
    try:
        if path is None:
            _asset, said = assets.add_bytes(
                given.read(), **_fields(form, request.user))
        else:
            _asset, said = assets.add(path, **_fields(form, request.user))
    except assets.Refused as refusal:
        return _page(request, form, f"Not kept: {refusal}.", status=400)
    finally:
        given.close()
        if path and os.path.exists(path):
            os.remove(path)
    return _page(request, UploadForm(), _plain(said))


def _fields(form, account):
    data = form.cleaned_data
    return dict(name=data["name"], description=data["description"],
                author=data.get("author") or "",
                licence=data.get("licence") or "",
                added_by=account, origin="upload")


def _plain(said):
    """A game sentence without its colour codes, for a web page."""
    from evennia.utils.ansi import strip_ansi

    return strip_ansi(str(said or ""))
