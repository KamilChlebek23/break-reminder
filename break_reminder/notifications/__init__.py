"""Break-time and custom-reminder UI surfaces.

Two distinct severity levels live here on purpose (FR-013):

* ``break_dialog`` — the load-bearing FR-009 non-dismissable popup.
* ``reminder_dialog`` — a deliberately *dismissable* popup for custom
  reminders (a dentist reminder shouldn't lock the screen).

Don't bring the FR-009 hardening across to the reminder dialog. The split
is the whole point.
"""
