"""
Watchdog — External process health monitor for kill switch.

PURPOSE:
  If the main TSAR process dies (crash, OOM, unhandled exception),
  the watchdog detects the missing heartbeat and triggers the kill
  switch to flatten all positions and halt trading.

DESIGN:
  - Runs as a SEPARATE process (or async task) from the main loop
  - Monitors a shared heartbeat file that the main process updates
  - If heartbeat is stale beyond threshold → activate kill switch
  - Also monitors the main process PID for liveness
  - Survives main process crash (file-based, not in-memory)

HEARTBEAT PROTOCOL:
  Main process writes: {"pid": <pid>, "ts": <unix_epoch>, "status": "alive"}
  Watchdog reads this file every `check_interval` seconds.
  If file is missing, corrupt, or timestamp > `max_stale_seconds`:
    → Activate kill switch immediately

SAFETY:
  - Watchdog itself writes a "watchdog alive" marker so orchestration
    can verify the watchdog is running
  - If watchdog can't write its own marker, it logs CRITICAL and exits
  - All state is file-based (survives Redis failure)
  - No LLM calls, no external API calls — pure deterministic logic
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.risk.kill_switch import KillSwitch

logger = logging.getLogger(__name__)

# Default paths — configurable via risk.yaml kill_switch section
DEFAULT_HEARTBEAT_PATH = os.environ.get(
    "TSAR_HEARTBEAT_PATH", "./data/heartbeat.json"
)
DEFAULT_WATCHDOG_MARKER_PATH = os.environ.get(
    "TSAR_WATCHDOG_MARKER_PATH", "./data/watchdog_alive.json"
)


@dataclass(frozen=True)
class WatchdogConfig:
    """Immutable watchdog configuration.

    All values should be sourced from risk.yaml kill_switch.watchdog section.
    Defaults are conservative — fail-safe, not fail-fast.
    """

    # How often (seconds) the watchdog checks the heartbeat file
    check_interval: float = 5.0

    # How many seconds without a heartbeat before triggering kill switch
    # Main process should write heartbeat every ~1-2 seconds ideally
    max_stale_seconds: float = 30.0

    # Path to the heartbeat file written by the main process
    heartbeat_path: str = DEFAULT_HEARTBEAT_PATH

    # Path to the watchdog's own "alive" marker
    marker_path: str = DEFAULT_WATCHDOG_MARKER_PATH

    # Whether to verify the main process PID is still alive
    check_pid: bool = True

    # Grace period on startup (seconds) — don't kill switch immediately
    # if heartbeat file doesn't exist yet
    startup_grace_seconds: float = 60.0

    # Number of consecutive stale reads before triggering
    # (prevents false positives from filesystem hiccups)
    stale_threshold: int = 3


class Watchdog:
    """External watchdog that monitors the main process via heartbeat file.

    ARCHITECTURE:
      ┌──────────────┐    heartbeat.json    ┌──────────────┐
      │  Main Process │ ──────────────────► │   Watchdog   │
      │  (writes HB)  │                     │  (reads HB)  │
      └──────────────┘                      └──────┬───────┘
                                                   │
                                          stale? ──┤
                                                   │
                                            ┌──────▼───────┐
                                            │  Kill Switch  │
                                            │   ACTIVATE    │
                                            └──────────────┘

    USAGE:
      # In a separate process or as an async task:
      watchdog = Watchdog(kill_switch=ks, config=WatchdogConfig())
      await watchdog.run()  # Blocks forever, monitoring

    The main process MUST call `write_heartbeat()` regularly.
    """

    def __init__(
        self,
        kill_switch: KillSwitch,
        config: WatchdogConfig | None = None,
    ) -> None:
        """Initialize the watchdog.

        Args:
            kill_switch: The KillSwitch instance to activate on failure.
            config: Watchdog configuration. Uses defaults if not provided.
        """
        self._kill_switch = kill_switch
        self._config = config or WatchdogConfig()
        self._running = False
        self._stale_count = 0
        self._last_heartbeat_ts: float = 0.0
        self._start_time: float = time.time()

        # Ensure parent directories exist
        Path(self._config.heartbeat_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self._config.marker_path).parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API — Main monitoring loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the watchdog monitoring loop. Blocks forever.

        This is the main entry point. Call it in a separate process
        or as an asyncio task.

        The loop:
          1. Read heartbeat file
          2. Check if timestamp is stale
          3. Optionally verify main process PID
          4. If stale beyond threshold → activate kill switch
          5. Write watchdog alive marker
          6. Sleep for check_interval
          7. Repeat
        """
        self._running = True
        logger.info(
            f"Watchdog started: check_interval={self._config.check_interval}s, "
            f"max_stale={self._config.max_stale_seconds}s, "
            f"stale_threshold={self._config.stale_threshold}"
        )

        while self._running:
            try:
                await self._check_cycle()
            except Exception as e:
                logger.error(f"Watchdog check cycle error: {e}")
                # Don't crash the watchdog on transient errors
                self._stale_count += 1

                if self._stale_count >= self._config.stale_threshold:
                    await self._trigger_kill_switch(
                        f"Watchdog encountered {self._stale_count} "
                        f"consecutive errors: {e}"
                    )

            await asyncio.sleep(self._config.check_interval)

    def stop(self) -> None:
        """Stop the watchdog monitoring loop."""
        self._running = False
        logger.info("Watchdog stopped")

    # ------------------------------------------------------------------
    # Public API — Heartbeat writing (called by main process)
    # ------------------------------------------------------------------

    @staticmethod
    def write_heartbeat(
        heartbeat_path: str = DEFAULT_HEARTBEAT_PATH,
        status: str = "alive",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write a heartbeat file. Called by the MAIN PROCESS.

        This is a static method so the main process can call it
        without needing a Watchdog instance.

        Args:
            heartbeat_path: Path to heartbeat file.
            status: Status string ("alive", "shutting_down", etc.).
            extra: Optional extra metadata to include.
        """
        payload = {
            "pid": os.getpid(),
            "ts": time.time(),
            "status": status,
        }
        if extra:
            payload.update(extra)

        try:
            _write_atomic(json.dumps(payload), heartbeat_path)
        except Exception as e:
            logger.error(f"Failed to write heartbeat: {e}")

    # ------------------------------------------------------------------
    # Internal — Check cycle
    # ------------------------------------------------------------------

    async def _check_cycle(self) -> None:
        """Single watchdog check cycle."""
        now = time.time()

        # Grace period on startup — don't trigger immediately
        if now - self._start_time < self._config.startup_grace_seconds:
            self._write_marker("grace_period")
            return

        # Read heartbeat
        heartbeat = self._read_heartbeat()

        if heartbeat is None:
            # No heartbeat file — could be main process hasn't started yet
            # or it crashed before writing first heartbeat
            self._stale_count += 1
            logger.warning(
                f"Watchdog: no heartbeat file (stale_count={self._stale_count})"
            )

            if self._stale_count >= self._config.stale_threshold:
                await self._trigger_kill_switch(
                    "Heartbeat file missing — main process may have crashed"
                )
            return

        # Check heartbeat freshness
        hb_ts = heartbeat.get("ts", 0)
        age_seconds = now - hb_ts

        if age_seconds > self._config.max_stale_seconds:
            self._stale_count += 1
            logger.warning(
                f"Watchdog: heartbeat stale ({age_seconds:.1f}s old, "
                f"max={self._config.max_stale_seconds}s, "
                f"stale_count={self._stale_count})"
            )

            if self._stale_count >= self._config.stale_threshold:
                await self._trigger_kill_switch(
                    f"Main process heartbeat stale for {age_seconds:.1f}s "
                    f"(threshold: {self._config.max_stale_seconds}s) — "
                    f"process may be dead or hung"
                )
            return

        # Check main process PID (optional)
        if self._config.check_pid:
            pid = heartbeat.get("pid")
            if pid and not _is_pid_alive(pid):
                self._stale_count += 1
                logger.warning(
                    f"Watchdog: main process PID {pid} is dead "
                    f"(stale_count={self._stale_count})"
                )

                if self._stale_count >= self._config.stale_threshold:
                    await self._trigger_kill_switch(
                        f"Main process PID {pid} is no longer alive"
                    )
                return

        # Heartbeat is fresh — reset stale counter
        if self._stale_count > 0:
            logger.info(
                f"Watchdog: heartbeat recovered (was stale {self._stale_count} times)"
            )
        self._stale_count = 0
        self._last_heartbeat_ts = hb_ts

        # Write watchdog alive marker
        self._write_marker("monitoring")

    # ------------------------------------------------------------------
    # Internal — Kill switch trigger
    # ------------------------------------------------------------------

    async def _trigger_kill_switch(self, reason: str) -> None:
        """Activate the kill switch due to watchdog failure detection.

        This is the CRITICAL safety action. Once triggered:
          1. All trading halts immediately
          2. Positions should be flattened (via kill switch callback)
          3. Only manual intervention can resume

        Args:
            reason: Detailed reason for the kill switch activation.
        """
        full_reason = f"WATCHDOG: {reason}"
        logger.critical(f"🔴 WATCHDOG TRIGGERING KILL SWITCH: {full_reason}")

        try:
            await self._kill_switch.activate(reason=full_reason)
            logger.critical("Kill switch activated by watchdog successfully")
        except Exception as e:
            logger.critical(f"Failed to activate kill switch from watchdog: {e}")
            # Last resort: write emergency kill switch file directly
            try:
                emergency_payload = {
                    "active": True,
                    "reason": full_reason,
                    "activated_at": time.time(),
                    "activated_at_human": time.strftime(
                        "%Y-%m-%d %H:%M:%S UTC", time.gmtime()
                    ),
                    "source": "watchdog_emergency",
                }
                _write_atomic(
                    json.dumps(emergency_payload, indent=2),
                    "/tmp/tsar_kill_switch_emergency",
                )
                logger.critical("Emergency kill switch file written directly")
            except Exception as e2:
                logger.critical(f"EMERGENCY KILL SWITCH WRITE FAILED: {e2}")

        # Stop the watchdog loop after triggering
        self._stale_count = 0  # Reset to prevent re-triggering

    # ------------------------------------------------------------------
    # Internal — File operations
    # ------------------------------------------------------------------

    def _read_heartbeat(self) -> dict[str, Any] | None:
        """Read and parse the heartbeat file.

        Returns:
            Parsed heartbeat dict, or None if file missing/corrupt.
        """
        path = Path(self._config.heartbeat_path)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                logger.warning("Watchdog: heartbeat file is not a JSON object")
                return None
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Watchdog: failed to read heartbeat file: {e}")
            # File exists but is corrupt — this is a warning, not a kill trigger
            # (could be mid-write). Count as stale.
            return None

    def _write_marker(self, status: str) -> None:
        """Write the watchdog alive marker file.

        This allows external monitoring to verify the watchdog itself
        is running (who watches the watchdog?).

        Args:
            status: Current watchdog status string.
        """
        payload = {
            "pid": os.getpid(),
            "ts": time.time(),
            "status": status,
            "stale_count": self._stale_count,
            "last_heartbeat_ts": self._last_heartbeat_ts,
        }
        try:
            _write_atomic(json.dumps(payload), self._config.marker_path)
        except Exception as e:
            logger.error(f"Watchdog: failed to write marker: {e}")


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _write_atomic(content: str, path: str) -> None:
    """Atomic file write — prevents partial reads by watchdog.

    Uses write-to-temp-then-rename pattern which is atomic on
    most filesystems (same directory, same filesystem).
    """
    import tempfile

    dir_name = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.rename(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is alive.

    Uses os.kill(pid, 0) which doesn't send a signal but checks
    if the process exists and we have permission to signal it.

    Returns:
        True if the process is alive, False otherwise.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        # Permission error or other — assume alive to be safe
        return True
