r"""Local-only persistence layer.

All state lives under ``%APPDATA%\BreakReminder`` per FR-002 / FR-015.
No module in this package may make outbound network calls.
"""
