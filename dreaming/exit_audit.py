"""
dreaming/exit_audit.py — Exit trade effectiveness audit and exit-specific axiom synthesis.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Any
from .constants import TIMEZONE, _clean_float, _now_ist_str

logger = logging.getLogger("DreamingEngine")


class ExitAuditMixin:
    def audit_exit_effectiveness(
        self, exit_episodes: list[dict[str, Any]], settlement_spot: float | None = None
    ) -> dict[str, Any]:
        """
        Audit exit recommendation outcomes against actual market trajectory:
        - TIMELY_PROFIT_LOCK: PARTIAL_BOOK/TRAIL_SL advised before intraday reversal/fade or on contrarian signal.
        - PREMATURE_PANIC_EXIT: FULL_EXIT advised right before continuation rally.
        - LETHAL_HOLD_ERROR: HOLD_AND_RIDE advised when position subsequently broke down or in opposing trap.
        - PROTECTIVE_EXIT: FULL_EXIT advised on failing trade preventing deeper drawdown.
        """
        audit_res: dict[str, Any] = {
            "total_exits_audited": len(exit_episodes),
            "timely_profit_locks": [],
            "premature_panic_exits": [],
            "lethal_hold_errors": [],
            "protective_exits": [],
            "effectiveness_score_pct": 100.0,
            "failure_traps_identified": [],
        }

        if not exit_episodes:
            return audit_res

        for ep in exit_episodes:
            if not isinstance(ep, dict):
                continue
            pos = ep.get("position") or {}
            if not isinstance(pos, dict):
                pos = {}
            side = str(pos.get("position_side") or pos.get("position_type") or pos.get("option_type") or "BUY_CE").upper()
            is_bullish = any(k in side for k in ["CE", "LONG", "BULL"])
            is_bearish = any(k in side for k in ["PE", "SHORT", "BEAR"])

            entry_spot = _clean_float(pos.get("entry_spot") or pos.get("entry_price"), default=24200.0)
            eval_spot = _clean_float(ep.get("live_spot") or pos.get("current_spot") or entry_spot, default=entry_spot)
            entry_prem = _clean_float(pos.get("entry_premium") or pos.get("entry_price"), default=0.0)
            curr_prem = _clean_float(pos.get("current_premium") or pos.get("current_price"), default=0.0)
            verdict = str(ep.get("verdict") or "").upper()
            c_warn = str(ep.get("contrarian_warning") or "").upper()

            raw_settle = settlement_spot if settlement_spot is not None else ep.get("settlement_spot")
            settle = _clean_float(raw_settle) if raw_settle is not None else None

            # Check profitability at evaluation time
            was_in_profit = (curr_prem > entry_prem > 0) or (is_bullish and eval_spot > entry_spot + 15) or (is_bearish and eval_spot < entry_spot - 15)
            was_in_loss = (0 < curr_prem < entry_prem) or (is_bullish and eval_spot < entry_spot - 15) or (is_bearish and eval_spot > entry_spot + 15)

            # Trajectory direction after evaluation (if settlement spot is available)
            subsequent_favorable = False
            subsequent_adverse = False
            if settle and eval_spot > 0:
                spot_delta = settle - eval_spot
                if is_bullish:
                    subsequent_favorable = spot_delta >= 30.0
                    subsequent_adverse = spot_delta <= -20.0
                elif is_bearish:
                    subsequent_favorable = spot_delta <= -30.0
                    subsequent_adverse = spot_delta >= 20.0

            # 1. LETHAL_HOLD_ERROR Check
            is_lethal_hold = False
            if "HOLD" in verdict:
                if (is_bullish and "BULL TRAP" in c_warn) or (is_bearish and "BEAR TRAP" in c_warn):
                    is_lethal_hold = True
                elif subsequent_adverse:
                    is_lethal_hold = True
                elif was_in_loss and curr_prem > 0 and curr_prem < (entry_prem * 0.70):
                    is_lethal_hold = True

            if is_lethal_hold:
                audit_res["lethal_hold_errors"].append({
                    "timestamp": ep.get("timestamp"),
                    "side": side,
                    "verdict": verdict,
                    "eval_spot": eval_spot,
                    "settlement_spot": settle,
                    "reason": "Advised HOLD_AND_RIDE into opposing contrarian trap or intraday breakdown",
                })
                trap_desc = f"Lethal Hold in {side} at {eval_spot:.0f}: gave up profits during adverse reversal."
                if trap_desc not in audit_res["failure_traps_identified"]:
                    audit_res["failure_traps_identified"].append(trap_desc)
                continue

            # 2. PREMATURE_PANIC_EXIT Check
            if verdict in ["FULL_EXIT", "EMERGENCY_EXIT"] and subsequent_favorable and settle:
                audit_res["premature_panic_exits"].append({
                    "timestamp": ep.get("timestamp"),
                    "side": side,
                    "verdict": verdict,
                    "eval_spot": eval_spot,
                    "settlement_spot": settle,
                    "reason": f"Advised FULL_EXIT before continuation move to {settle:.0f}",
                })
                continue

            # 3. TIMELY_PROFIT_LOCK Check
            if any(k in verdict for k in ["PARTIAL_BOOK", "TRAIL_SL_TIGHT", "TRAIL_SL_TO_COST"]):
                if was_in_profit or subsequent_adverse or c_warn:
                    audit_res["timely_profit_locks"].append({
                        "timestamp": ep.get("timestamp"),
                        "side": side,
                        "verdict": verdict,
                        "eval_spot": eval_spot,
                        "settlement_spot": settle,
                        "reason": "Locked profit / tightened SL before trend stall or during contrarian trap",
                    })
                    continue

            # 4. PROTECTIVE_EXIT Check
            if verdict in ["FULL_EXIT", "TRAIL_SL_TIGHT"] and (was_in_loss or subsequent_adverse):
                audit_res["protective_exits"].append({
                    "timestamp": ep.get("timestamp"),
                    "side": side,
                    "verdict": verdict,
                    "eval_spot": eval_spot,
                    "settlement_spot": settle,
                    "reason": "Defensive exit preserved capital against deepening drawdown",
                })

        total_critical = (
            len(audit_res["timely_profit_locks"])
            + len(audit_res["protective_exits"])
            + len(audit_res["lethal_hold_errors"])
            + len(audit_res["premature_panic_exits"])
        )
        if total_critical > 0:
            success = len(audit_res["timely_profit_locks"]) + len(audit_res["protective_exits"])
            audit_res["effectiveness_score_pct"] = round((success / total_critical) * 100.0, 1)
        else:
            audit_res["effectiveness_score_pct"] = 100.0

        return audit_res

    def synthesize_exit_macro_axioms(
        self, audit_res: dict[str, Any], exit_episodes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Synthesize durable Macro Axioms from exit evaluation audit results.
        Translates real-world exit successes and mistakes into permanent committee rules.
        """
        axioms: list[dict[str, Any]] = []
        today_date = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

        # 1. Lethal Hold Error Axiom
        if audit_res.get("lethal_hold_errors"):
            count = len(audit_res["lethal_hold_errors"])
            axioms.append({
                "axiom_id": "AXIOM_AVOID_HOLDING_ON_RETAIL_EUPHORIA",
                "statement": "Advising HOLD_AND_RIDE during opposing contrarian crowd traps or afternoon theta decay leads to rapid intraday profit evaporation. Require mandatory tiered scale-out.",
                "subject": "Retail_Euphoria_Trap",
                "relation": "caused_failure_of",
                "target": "HOLD_AND_RIDE",
                "polarity": "NEGATIVE",
                "regime": "VIX_MOD|DTE_NEAR|FII_BEAR|GAP_MILD_UP",
                "confidence": round(min(0.96, 0.75 + 0.05 * count), 2),
                "observation_count": count,
                "evidence_dates": [ep.get("trade_date") for ep in audit_res["lethal_hold_errors"] if ep.get("trade_date")] or [today_date],
                "last_validated": today_date,
            })

        # 2. Timely Profit Lock Axiom
        if audit_res.get("timely_profit_locks"):
            count = len(audit_res["timely_profit_locks"])
            axioms.append({
                "axiom_id": "AXIOM_CONTRARIAN_PARTIAL_PROFIT_DEFUSAL",
                "statement": "Locking 50% profit on contrarian sentiment divergence eliminates drawdown risk and secures intraday win rate before afternoon reversals.",
                "subject": "Contrarian_Partial_Book",
                "relation": "protects_against",
                "target": "Afternoon_Trend_Fade",
                "polarity": "POSITIVE",
                "regime": "VIX_MOD|DTE_NEAR|FII_NEUT|GAP_STRONG_UP",
                "confidence": round(min(0.95, 0.70 + 0.04 * count), 2),
                "observation_count": count,
                "evidence_dates": [ep.get("trade_date") for ep in audit_res["timely_profit_locks"] if ep.get("trade_date")] or [today_date],
                "last_validated": today_date,
            })

        # 3. Premature Panic Exit Axiom
        if audit_res.get("premature_panic_exits"):
            count = len(audit_res["premature_panic_exits"])
            axioms.append({
                "axiom_id": "AXIOM_AVOID_PREMATURE_PANIC_IN_TREND",
                "statement": "Full panic exits on minor pullbacks prematurely forfeit strong afternoon trend continuation. Use tiered scale-out and cost trailing instead.",
                "subject": "Premature_Panic_Exit",
                "relation": "erodes",
                "target": "Trend_Continuation_Runners",
                "polarity": "NEGATIVE",
                "regime": "VIX_LOW|DTE_MID|FII_BULL|GAP_STRONG_UP",
                "confidence": round(min(0.90, 0.65 + 0.05 * count), 2),
                "observation_count": count,
                "evidence_dates": [ep.get("trade_date") for ep in audit_res["premature_panic_exits"] if ep.get("trade_date")] or [today_date],
                "last_validated": today_date,
            })

        return axioms

    def record_exit_traps_in_cognigraph(self, audit_res: dict[str, Any]) -> int:
        """
        Record empirically validated exit failure traps as negative causal edges in CogniGraph.
        """
        trap_count = 0
        try:
            from cognigraph import get_cognigraph
            cg = get_cognigraph(str(self._history_dir))
            for err in audit_res.get("lethal_hold_errors", []):
                side = err.get("side", "BUY_CE")
                sub = "Retail_Euphoria_Trap" if "CE" in side or "LONG" in side else "Retail_Panic_Trap"
                cg.add_or_update_triple(
                    subject=sub,
                    relation="caused_failure_of",
                    target="HOLD_AND_RIDE",
                    polarity="NEGATIVE",
                    regime="VIX_MOD|DTE_NEAR|FII_BEAR|GAP_MILD_UP",
                    detail=f"Post-market dream audit: advising HOLD_AND_RIDE in {side} resulted in lethal drawdown ({err.get('reason')}).",
                    evidence_date=datetime.now(TIMEZONE).strftime("%Y-%m-%d"),
                    weight_increment=1.5,
                )
                trap_count += 1
            if trap_count > 0:
                cg.save()
        except Exception as e:
            logger.warning(f"DreamingEngine: Failed to record exit traps in CogniGraph: {e}")
        return trap_count

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2: Synthesize Macro Axioms (Dual Engine: Heuristic + LLM)
    # ─────────────────────────────────────────────────────────────────────────

