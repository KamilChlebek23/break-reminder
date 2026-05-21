r"""Top-level entry — kept thin so PyInstaller and ``python -m`` agree.

Real wiring lives in ``break_reminder.app:main``. This file exists because
PyInstaller's ``--name`` flag points at a script file rather than a module.

Two pieces of logic live here despite the "thin" doctrine:

1. A bootstrap-panic safety net: if importing ``break_reminder.app`` or
   constructing the ``QApplication`` fails (missing DLL, broken PyInstaller
   bundle, etc.), the user sees a single ``MessageBoxW`` dialog and a
   traceback lands in ``%APPDATA%\BreakReminder\bootstrap-error.log``
   instead of the silent ``--windowed`` exit Windows would otherwise
   produce. Pre-staged mitigation for the "``--windowed`` swallows
   bootstrap panics" risk in ``context/foundation/infrastructure.md``.

2. A ``--self-test`` flag that imports the ``pynput`` listeners and exits
   0 / 1. The release pipeline invokes the bundled ``.exe --self-test``
   after PyInstaller to detect cases where ``--collect-submodules pynput``
   missed a platform-specific submodule.

Both code paths run before any Qt initialization and must therefore use
stdlib only. ``break_reminder.storage.paths`` is intentionally NOT imported
here because it depends on ``QStandardPaths`` — defeats the bootstrap
guarantee in the failure mode where Qt itself is broken.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import traceback
from pathlib import Path

_APP_NAME = "BreakReminder"


def _bootstrap_error_log_path() -> Path:
    r"""Resolve the bootstrap-error log path WITHOUT importing Qt.

    Mirrors the spirit of ``break_reminder.storage.paths.app_data_dir`` but
    uses stdlib only because the bootstrap-panic safety net runs before
    Qt is loaded — and the failure mode it guards against may be Qt
    itself failing to load. Falls back to ``~/.breakreminder/`` when
    ``%APPDATA%`` isn't set (non-Windows / unusual environments).

    Returns:
        Absolute path to ``%APPDATA%\BreakReminder\bootstrap-error.log``
        (or the home-dir fallback). The parent directory is created on
        demand.
    """
    appdata = os.environ.get("APPDATA")
    directory = Path(appdata) / _APP_NAME if appdata else Path.home() / ".breakreminder"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "bootstrap-error.log"


def _show_panic_box(message: str) -> None:
    """Surface a MessageBoxW so a windowed exit isn't silent.

    PyInstaller's ``--windowed`` flag strips the console; without this,
    a bootstrap exception kills the process with no UI feedback. Uses
    ``ctypes.windll.user32.MessageBoxW`` directly so it works even when
    PySide6 itself failed to import.

    Args:
        message: Text shown in the dialog body.
    """
    flags = 0x0 | 0x10 | 0x1000  # MB_OK | MB_ICONERROR | MB_SYSTEMMODAL
    # Non-Windows or otherwise no user32 -> nothing more we can do.
    with contextlib.suppress(Exception):
        ctypes.windll.user32.MessageBoxW(None, message, _APP_NAME, flags)


def _run_self_test() -> int:
    """Import the pynput listeners and exit 0 / 1.

    The release pipeline runs the bundled ``.exe --self-test`` after
    PyInstaller to detect cases where ``--collect-submodules pynput``
    missed a platform-specific submodule. Touching ``Listener`` forces
    ``pynput.keyboard.__init__`` and ``pynput.mouse.__init__`` to dispatch
    to their platform-specific backends (e.g. ``pynput.keyboard._win32``
    on Windows) — exactly what PyInstaller has to pick up.

    Returns:
        0 if pynput imports cleanly, 1 otherwise.
    """
    if sys.platform == "win32":
        # PyInstaller --windowed strips the console; reattach to the
        # parent console so prints reach the CI log on this code path.
        # ATTACH_PARENT_PROCESS = -1 (DWORD). Silent attach is best-effort.
        with contextlib.suppress(Exception):
            ctypes.windll.kernel32.AttachConsole(-1)

    try:
        from pynput import keyboard, mouse

        # Touch the Listener class to trigger the platform-backend import.
        _ = keyboard.Listener
        _ = mouse.Listener
    except ImportError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print("OK")
    return 0


def _run() -> int:
    """Dispatch on argv: ``--self-test`` runs the smoke test, else run the app.

    Kept separate from ``__main__`` so the bootstrap-panic try/except can
    wrap both this function AND the deferred import of
    ``break_reminder.app``. If the import itself fails (missing DLL, bad
    PyInstaller bundle), the traceback still lands in bootstrap-error.log.

    Returns:
        Process exit code; 0 on success.
    """
    if "--self-test" in sys.argv[1:]:
        return _run_self_test()
    # Deferred import: bootstrap-panic catches failures here too.
    from break_reminder.app import main as app_main

    return app_main()


if __name__ == "__main__":
    try:
        sys.exit(_run())
    except Exception:  # noqa: BLE001 -- top-level last-resort handler
        # SystemExit / KeyboardInterrupt derive from BaseException, so
        # they fall through this handler unchanged (intended).
        log_path = _bootstrap_error_log_path()
        try:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
                f.write("\n")
        except Exception:  # noqa: BLE001 -- logging is best-effort
            # If we can't even write the log, at least surface the box.
            pass
        _show_panic_box(f"{_APP_NAME} failed to start.\n\nSee: {log_path}")
        sys.exit(1)
