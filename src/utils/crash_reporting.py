"""
utils.crash_reporting  -  Opt-in Sentry initialization.

Crash reporting is opt-in for two reasons: privacy, and not wanting the
casual / open-source install to phone home to our infra by default. The
flow:

1. The user (or our premium installer) installs sentry-sdk via
   ``uv sync --extra crash-reporting``. Without the SDK, this module
   is a no-op - every public function returns immediately.

2. The runtime checks two environment variables, both of which must
   be set for any traces to leave the machine:

       SVCS_ENABLE_SENTRY=1
       SENTRY_DSN=https://<key>@o<org>.ingest.sentry.io/<project>

3. PII scrubbing is enabled hard-coded - we don't ship request headers,
   cookies, or user IPs. Only the exception type, message, traceback
   frames, and (optional) build info travel.

To test locally without sending to real Sentry, you can use any DSN with
a fake key - the SDK still produces a structured event you can see in
logs, and it'll drop the network call cleanly when the DSN doesn't
resolve.

This module exposes only ``init_crash_reporting()`` and
``capture_exception()``; callers should NOT import sentry_sdk directly,
so that the rest of the codebase stays clean when the SDK is absent.

Author: Bloodawn (KheivenD), 2026-05-14 (audit item: crash reporting).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

_log = logging.getLogger(__name__)

# Set on a successful init so capture_exception() knows whether to
# bother. We don't import sentry_sdk at module top: that would crash
# the casual install where the SDK is intentionally absent.
_SENTRY_ENABLED: bool = False


def _is_truthy_env(name: str) -> bool:
    """Return True if env var ``name`` is set to a truthy value."""
    value = os.environ.get(name, "").strip().lower()
    return value in ("1", "true", "yes", "on")


def init_crash_reporting(
    release: Optional[str] = None,
    environment: Optional[str] = None,
) -> bool:
    """Initialize Sentry if the SDK is installed and opt-in is on.

    Args:
        release: Build/version identifier shown in Sentry events. We
            pass the SVCS package version when called from run_gui.
        environment: 'dev' | 'beta' | 'production'. Helps split traffic
            in the Sentry UI. Defaults to 'dev' for source runs and
            'production' for frozen exe runs.

    Returns:
        True if Sentry was wired up; False if it was skipped (SDK not
        installed, env vars not set, or DSN missing).
    """
    global _SENTRY_ENABLED

    if _SENTRY_ENABLED:
        return True  # already wired, idempotent

    if not _is_truthy_env("SVCS_ENABLE_SENTRY"):
        # Opt-in flag isn't set; never phone home.
        return False

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        _log.info(
            "crash_reporting: SVCS_ENABLE_SENTRY=1 but SENTRY_DSN is empty; "
            "skipping init."
        )
        return False

    try:
        import sentry_sdk  # local import: only loaded when opt-in is on
    except ImportError:
        _log.info(
            "crash_reporting: sentry-sdk not installed. Install with "
            "`uv sync --extra crash-reporting` to enable."
        )
        return False

    # Auto-detect environment if caller didn't pass one. Frozen exe ==
    # production by default; source runs are dev unless overridden.
    if environment is None:
        environment = "production" if _is_truthy_env("SVCS_FROZEN") else "dev"

    try:
        sentry_sdk.init(
            dsn=dsn,
            release=release,
            environment=environment,
            # PII off by default. The SDK still strips most of it, but
            # being explicit here means a future SDK update can't quietly
            # flip the default and start exfiltrating headers/cookies.
            send_default_pii=False,
            # Performance traces sample rate. 0 = errors only, no
            # performance data. We can crank this up later if we want
            # to track encoder hot paths.
            traces_sample_rate=0.0,
            # Don't auto-attach local variables to frames - they may
            # contain file paths or video filenames the user considers
            # sensitive.
            include_local_variables=False,
        )
    except Exception as exc:  # noqa: BLE001  - never let init crash startup
        _log.warning("crash_reporting: sentry init failed: %s", exc)
        return False

    _SENTRY_ENABLED = True
    _log.info(
        "crash_reporting: Sentry enabled (release=%s, env=%s).",
        release, environment,
    )
    return True


def capture_exception(exc: BaseException) -> None:
    """Forward an exception to Sentry if init succeeded; otherwise no-op.

    Use this from explicit try/except blocks where you want to record
    the error but not crash the surrounding flow (e.g. inside a Flask
    route handler that returns 500 to the user). Unhandled exceptions
    are picked up automatically by Sentry's signal handlers - you do
    NOT need to call this for those.
    """
    if not _SENTRY_ENABLED:
        return
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001 - reporting must not raise
        pass


def is_enabled() -> bool:
    """Return True if Sentry was successfully initialized this process."""
    return _SENTRY_ENABLED
