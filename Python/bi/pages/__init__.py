"""Dash pages. Each module calls dash.register_page at import time; the app
points pages_folder at this directory and Dash imports them automatically.

Every layout is a function rather than a module-level object, so navigating
after a data refresh re-renders against the reloaded DataFrames.
"""
