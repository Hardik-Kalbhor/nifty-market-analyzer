"""
exit/session_manager.py — Trade Session Manager for Continuous MFE/MAE and Position Tracking.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Optional
import pytz

logger = logging.getLogger(__name__)
TIMEZONE = pytz.timezone("Asia/Kolkata")


def _get_history_dir() -> str:
    from pathlib import Path
    base_dir = Path(__file__).resolve().parent.parent
    hdir = base_dir / "history"
    hdir.mkdir(parents=True, exist_ok=True)
    return str(hdir)


class TradeSessionManager:
    """
    Manages stateful trade sessions to track:
    - Peak spot & Trough spot (MFE and MAE)
    - Consecutive poll count and duration
    - Realized P&L upon close ("Exit" button)
    Backed by history/exit_sessions.jsonl for persistence across restarts.
    """

    def __init__(self, history_dir: str | None = None):
        self._history_dir = history_dir or _get_history_dir()
        self._log_file = os.path.join(self._history_dir, "exit_sessions.jsonl")
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Load recent active sessions from disk into memory."""
        if not os.path.exists(self._log_file):
            return
        try:
            with open(self._log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        sid = record.get("session_id")
                        if sid:
                            self._sessions[sid] = record
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"Failed to load exit sessions from disk: {e}")

    def _persist_session(self, session: dict[str, Any]) -> None:
        """Append latest session update to jsonl file."""
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(session, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.debug(f"Failed to persist exit session: {e}")

    def create_or_get_session(
        self,
        position: dict[str, Any],
        live_spot: float = 0.0,
    ) -> dict[str, Any]:
        """
        Retrieves existing session if session_id is provided, or creates a new active session.
        """
        with self._lock:
            sid = position.get("session_id")
            if sid and sid in self._sessions:
                sess = self._sessions[sid]
                # Update spot if provided
                if live_spot > 0:
                    self._update_excursion(sess, live_spot)
                return sess

            # Generate new session
            side = str(position.get("position_side", "BUY_CE")).upper()
            now_dt = datetime.now(TIMEZONE)
            new_sid = f"sess_{now_dt.strftime('%Y%m%d_%H%M%S')}_{side}"
            entry_spot = float(position.get("entry_spot") or live_spot or 24200.0)
            initial_spot = live_spot if live_spot > 0 else entry_spot

            session_record = {
                "session_id": new_sid,
                "created_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "ACTIVE",
                "position": dict(position),
                "side": side,
                "entry_spot": entry_spot,
                "peak_spot": initial_spot,
                "trough_spot": initial_spot,
                "mfe_pct": 0.0,
                "mae_pct": 0.0,
                "mfe_r": 0.0,
                "current_r": 0.0,
                "poll_count": 1,
                "last_poll_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "last_verdict": None,
                "last_eci_score": None,
                "exit_spot": None,
                "final_pnl_pct": None,
            }
            self._update_excursion(session_record, initial_spot)
            self._sessions[new_sid] = session_record
            self._persist_session(session_record)
            return session_record

    def _update_excursion(self, session: dict[str, Any], current_spot: float) -> None:
        """Internal helper to calculate MFE and MAE according to directional trade side."""
        if current_spot <= 0:
            return

        side = str(session.get("side", "BUY_CE")).upper()
        entry_spot = float(session.get("entry_spot", current_spot))
        is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]

        if is_bullish:
            session["peak_spot"] = max(float(session.get("peak_spot", current_spot)), current_spot)
            session["trough_spot"] = min(float(session.get("trough_spot", current_spot)), current_spot)
            mfe_pts = session["peak_spot"] - entry_spot
            mae_pts = session["trough_spot"] - entry_spot
            curr_pts = current_spot - entry_spot
        else:
            # Bearish trade: lower spot is favorable (peak), higher spot is adverse (trough)
            session["peak_spot"] = min(float(session.get("peak_spot", current_spot)), current_spot)
            session["trough_spot"] = max(float(session.get("trough_spot", current_spot)), current_spot)
            mfe_pts = entry_spot - session["peak_spot"]
            mae_pts = entry_spot - session["trough_spot"]
            curr_pts = entry_spot - current_spot

        mfe_pct = (mfe_pts / entry_spot) * 100.0 if entry_spot > 0 else 0.0
        mae_pct = (mae_pts / entry_spot) * 100.0 if entry_spot > 0 else 0.0
        curr_pct = (curr_pts / entry_spot) * 100.0 if entry_spot > 0 else 0.0

        session["mfe_pct"] = round(mfe_pct, 2)
        session["mae_pct"] = round(mae_pct, 2)
        # 1R = 0.60% spot move (hard stop threshold)
        session["mfe_r"] = round(mfe_pct / 0.60, 2)
        session["current_r"] = round(curr_pct / 0.60, 2)

    def record_poll(
        self,
        session_id: str,
        current_spot: float,
        verdict: str,
        eci_score: int | None = None,
    ) -> dict[str, Any] | None:
        """Update session with poll results."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return None
            sess["poll_count"] = int(sess.get("poll_count", 0)) + 1
            sess["last_poll_at"] = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            sess["last_verdict"] = verdict
            if eci_score is not None:
                sess["last_eci_score"] = int(eci_score)
            self._update_excursion(sess, current_spot)
            self._persist_session(sess)
            return sess

    def close_session(
        self,
        session_id: str,
        exit_spot: float | None = None,
        exit_premium: float | None = None,
        reason: str = "MANUAL_EXIT",
    ) -> dict[str, Any] | None:
        """Mark trade session as CLOSED upon exit."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return None

            sess["status"] = "CLOSED"
            sess["closed_at"] = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            sess["exit_reason"] = reason

            pos = sess.get("position", {})
            entry_spot = float(sess.get("entry_spot", 0.0))
            side = str(sess.get("side", "BUY_CE")).upper()
            is_bullish = side in ["BUY_CE", "LONG_FUTURES", "SHORT_PE"]

            final_spot = exit_spot if (exit_spot and exit_spot > 0) else entry_spot
            sess["exit_spot"] = final_spot

            # Calculate realized spot P&L %
            if entry_spot > 0:
                spot_diff = (final_spot - entry_spot) if is_bullish else (entry_spot - final_spot)
                sess["realized_spot_pnl_pct"] = round((spot_diff / entry_spot) * 100.0, 2)

            # Calculate premium P&L % if premium data available
            entry_prem = float(pos.get("entry_premium") or pos.get("entry_price") or 0.0)
            if entry_prem > 0 and exit_premium and exit_premium > 0:
                is_short = side in ["SHORT_CE", "SHORT_PE"]
                prem_diff = (entry_prem - exit_premium) if is_short else (exit_premium - entry_prem)
                sess["realized_premium_pnl_pct"] = round((prem_diff / entry_prem) * 100.0, 1)

            self._persist_session(sess)
            return sess

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Fetch single session."""
        with self._lock:
            return self._sessions.get(session_id)

    def get_active_sessions(self) -> list[dict[str, Any]]:
        """Return all currently open / active sessions."""
        with self._lock:
            return [s for s in self._sessions.values() if s.get("status") == "ACTIVE"]


_GLOBAL_SESSION_MANAGER: Optional[TradeSessionManager] = None
_INIT_LOCK = threading.Lock()


def get_trade_session_manager() -> TradeSessionManager:
    global _GLOBAL_SESSION_MANAGER
    if _GLOBAL_SESSION_MANAGER is None:
        with _INIT_LOCK:
            if _GLOBAL_SESSION_MANAGER is None:
                _GLOBAL_SESSION_MANAGER = TradeSessionManager()
    return _GLOBAL_SESSION_MANAGER
