"""Voice-channel notification (FR-007).

``pyttsx3`` is synchronous — ``engine.runAndWait()`` blocks until the speech
finishes — so we run it on a single-worker ``ThreadPoolExecutor`` to keep
the GUI thread responsive. One worker is enough: serializing speech matches
human expectations (we don't want overlapping voices) and avoids the
re-entrancy bugs that the SAPI engine is famous for when called from
multiple threads.

Two pre-speak gates exist (US-01 acceptance):
  * ``_focus_assist_active`` — Windows Focus Assist mode.
  * ``_system_muted`` — the user has muted the system or the active output device.

Both are currently stubs returning ``False``. Wiring them is non-trivial
(see TODO comments) and the bootstrap deliberately keeps the audio path
working without them so the smoke test remains useful. Every call site
that triggers speech checks ``is_blocked()`` first, so flipping the gate
to a real implementation is a one-function change.
"""

from __future__ import annotations

import logging
import sys
from concurrent.futures import Future, ThreadPoolExecutor

logger = logging.getLogger(__name__)


class VoiceNotifier:
    """Speak short phrases off-thread, with system-state gates."""

    def __init__(self) -> None:
        """Build the notifier with a single-worker speech thread pool."""
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice")
        self._current: Future[None] | None = None

    # ---- public API -----------------------------------------------------

    def speak(self, phrase: str) -> None:
        """Queue ``phrase`` for speaking unless the system gates block it.

        Empty *and* whitespace-only phrases are treated as no-ops so callers
        (notably the settings dialog's Test-voice button) can pass user
        input straight through without an upstream strip — silence on
        ``"   "`` would otherwise look like the audio path is broken
        (impl-review F4).
        """
        if not phrase or not phrase.strip():
            return
        if self.is_blocked():
            logger.info(
                "voice suppressed: focus_assist=%s muted=%s",
                self._focus_assist_active(),
                self._system_muted(),
            )
            return
        self._current = self._executor.submit(self._say, phrase)

    def stop(self) -> None:
        """Cancel any in-flight speech (US-02 acceptance).

        ``pyttsx3`` exposes ``engine.stop()`` but it must be called on the
        same thread that started the engine, so we set a flag the worker
        checks. In practice phrases are <2s, so the flag-checked approach
        is good enough.
        """
        # TODO(FR-007): implement true mid-utterance stop via a per-engine
        # cancellation token. For the bootstrap, finishing the in-flight
        # phrase is acceptable.
        if self._current is not None and not self._current.done():
            self._current.cancel()
        self._current = None

    def is_blocked(self) -> bool:
        """Return ``True`` if either Focus Assist or system mute is active."""
        return self._focus_assist_active() or self._system_muted()

    def shutdown(self) -> None:
        """Tear down the voice worker pool. Safe to call multiple times."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ---- internals ------------------------------------------------------

    def _say(self, phrase: str) -> None:
        try:
            import pyttsx3  # imported lazily so tests that don't use voice don't pay

            engine = pyttsx3.init()
            engine.say(phrase)
            engine.runAndWait()
        except Exception:  # noqa: BLE001 — voice failures must never crash the app
            logger.exception("pyttsx3 failed to speak %r", phrase)

    def _focus_assist_active(self) -> bool:
        # TODO(US-01): implement via WTSQuerySessionInformation /
        # RtlQueryWnfStateData(WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED).
        # Returning False keeps voice working unconditionally for now.
        if sys.platform != "win32":
            return False
        return False

    def _system_muted(self) -> bool:
        # TODO(US-01): query the default render endpoint via pycaw or
        # winrt's Windows.Media.Audio APIs.
        if sys.platform != "win32":
            return False
        return False
