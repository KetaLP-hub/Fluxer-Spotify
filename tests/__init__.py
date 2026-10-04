"""Test package.

Tests must never touch the real desktop: no browser tabs, no Explorer windows. This guard runs before any test module imports
the program (so even default arguments such as `open_browser=webbrowser.open` pick it up). A test that needs to see a "browser
open" passes its own fake (`open_browser=opened.append`).
"""
import os
import webbrowser


def _blocked(*args, **kwargs):
    raise RuntimeError("a test tried to open a real browser/window - pass a fake open_browser instead")


webbrowser.open = webbrowser.open_new = webbrowser.open_new_tab = _blocked
if hasattr(os, "startfile"):
    os.startfile = _blocked
