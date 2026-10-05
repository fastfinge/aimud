"""
This reroutes from an URL to a python view-function/class.

The main web/urls.py includes these routes for all urls (the root of the url)
so it can reroute to all website pages.

"""

from django.urls import path

from evennia.web.website.urls import urlpatterns as evennia_website_urlpatterns

from web.website.views import assets as asset_views

# add patterns here
urlpatterns = [
    # A file straight from a player's machine; docs/archived/assets.md 5.2.
    path("assets/upload/", asset_views.upload, name="asset-upload"),
]

# read by Django
urlpatterns = urlpatterns + evennia_website_urlpatterns
