"""User-initiated configuration surfaces.

Houses dialogs that the user opens explicitly (Settings, future custom-
reminder editors) — distinct from ``notifications/``, which holds popups
that fire on events (break dialog, custom-reminder popup). Keeping the
two split prevents ``notifications/`` from becoming a misnomer as
v0.2.x adds editor surfaces.
"""
