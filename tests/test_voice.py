"""Unit tests for ``break_reminder.notifications.voice.VoiceNotifier``.

Scope: the input-validation gate in ``speak()``. The pyttsx3 path is NOT
exercised here — ``_say()`` runs on the executor and would actually try
to speak. Instead, we monkeypatch the executor's ``submit`` so we can
observe whether the gate let the call through without spinning up a real
TTS engine.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from break_reminder.notifications.voice import VoiceNotifier


@pytest.fixture
def notifier() -> Iterator[VoiceNotifier]:
    """A ``VoiceNotifier`` whose worker pool is shut down at test teardown."""
    n = VoiceNotifier()
    yield n
    n.shutdown()


@pytest.fixture
def submitted_phrases(monkeypatch: pytest.MonkeyPatch, notifier: VoiceNotifier) -> list[str]:
    """Record every phrase the notifier hands to its executor.

    Replaces ``self._executor.submit`` with a recording stub so we can
    observe what passes the input gate without actually invoking
    ``pyttsx3``. Returns the list the stub appends to.
    """
    captured: list[str] = []

    def _stub(_fn: Any, phrase: str) -> None:
        captured.append(phrase)
        return None

    monkeypatch.setattr(notifier._executor, "submit", _stub)
    return captured


class TestSpeakInputGate:
    """``speak()`` rejects empty / whitespace-only phrases (impl-review F4)."""

    def test_empty_phrase_is_a_no_op(
        self, notifier: VoiceNotifier, submitted_phrases: list[str]
    ) -> None:
        """``speak("")`` does not reach the executor."""
        notifier.speak("")
        assert submitted_phrases == []

    def test_whitespace_only_phrase_is_a_no_op(
        self, notifier: VoiceNotifier, submitted_phrases: list[str]
    ) -> None:
        """F4 contract: ``speak("   ")`` is treated like an empty phrase."""
        notifier.speak("   ")
        assert submitted_phrases == []

    def test_tab_and_newline_only_phrase_is_a_no_op(
        self, notifier: VoiceNotifier, submitted_phrases: list[str]
    ) -> None:
        """F4 contract: any whitespace-only string short-circuits."""
        notifier.speak("\t\n  \r\n")
        assert submitted_phrases == []

    def test_non_empty_phrase_reaches_the_executor(
        self, notifier: VoiceNotifier, submitted_phrases: list[str]
    ) -> None:
        """A real phrase makes it past the gate and into the executor."""
        notifier.speak("Time to take a break")
        assert submitted_phrases == ["Time to take a break"]

    def test_phrase_with_leading_whitespace_reaches_the_executor(
        self, notifier: VoiceNotifier, submitted_phrases: list[str]
    ) -> None:
        """A phrase that has any non-whitespace character passes the gate untouched.

        ``speak`` is permissive on the content side — the gate only rejects
        purely-whitespace input. Trimming would be a behavioral change the
        callers (e.g., custom-reminder names) might not want.
        """
        notifier.speak("  hello  ")
        assert submitted_phrases == ["  hello  "]
