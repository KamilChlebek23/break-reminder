"""Test suite for ``break_reminder``.

Mirrors the package layout: each ``tests/test_<module>.py`` file targets
exactly one module under ``break_reminder/``. Shared fixtures and the
canonical ``Clock`` test helper live in ``conftest.py``; per-file
``clock`` fixtures (and helper stubs like ``FakeVoice``) stay file-local
where their epoch / wiring encodes per-suite intent — the scheduler
suites pin a different epoch than the form-dialog suite, so a single
shared fixture would lose that intent.
"""
