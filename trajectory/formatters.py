"""
trajectory/formatters.py — Trajectory dataset formatting for ShareGPT, DPO, and Alpaca.
"""

from __future__ import annotations

from typing import Any

from .constants import _SYSTEM_PROMPT


class TrajectoryFormattersMixin:
    """Mixin providing SFT/DPO dataset transformation formats."""

    def export_sharegpt(self, episodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """
        Convert trade trajectories into ShareGPT multi-turn conversational format.
        Schema:
          {
            "id": "trade_YYYY-MM-DD",
            "conversations": [
              {"from": "system", "value": "..."},
              {"from": "human", "value": "..."},
              {"from": "gpt", "value": "..."},
              {"from": "human", "value": "..."},
              {"from": "gpt", "value": "..."}
            ]
          }
        """
        if episodes is None:
            episodes = self.collect_trajectories()

        sharegpt_dataset: list[dict[str, Any]] = []

        for ep in episodes:
            trade_date = ep.get("trade_date", "unknown_date")
            signals = ep.get("market_signals", {})
            bull_factors = ep.get("bullish_factors", [])
            bear_factors = ep.get("bearish_factors", [])
            debate = ep.get("debate", {})
            specialists = ep.get("dynamic_subagents", [])

            # Human turn 1: Context & observation
            signals_desc = (
                f"Market Signals for {trade_date}:\n"
                f"- GIFT Nifty Change: {signals.get('gift_nifty_change_pct', 'N/A')}%\n"
                f"- India VIX: {signals.get('india_vix', 'N/A')}\n"
                f"- Institutional FII Net Flow: ₹{signals.get('fii_net', 'N/A')} Cr\n"
                f"- Put-Call Ratio (PCR): {signals.get('pcr', 'N/A')}\n"
                f"- Bullish Factors: {', '.join(bull_factors[:4]) if bull_factors else 'None recorded'}\n"
                f"- Bearish Factors: {', '.join(bear_factors[:4]) if bear_factors else 'None recorded'}\n\n"
                "Evaluate these market conditions through the multi-agent Risk Committee and dynamic catalyst specialists. "
                "Synthesize the calibrated BTST structure, consensus verdict, and actionable trade instruction."
            )

            # Assistant turn 1: Reasoning, Committee Debate, and Final Calibrated Verdict
            gpt_reasoning_parts = ["<thought>"]
            if debate:
                agg = debate.get("aggressive", {})
                cons = debate.get("conservative", {})
                neut = debate.get("neutral", {})
                gpt_reasoning_parts.append(
                    f"Committee Perspectives:\n"
                    f"• Aggressive: {agg.get('verdict', 'N/A')} ({agg.get('confidence', 0)}%) — {agg.get('rationale', '')}\n"
                    f"• Conservative: {cons.get('verdict', 'N/A')} ({cons.get('confidence', 0)}%) — {cons.get('rationale', '')}\n"
                    f"• Neutral: {neut.get('verdict', 'N/A')} ({neut.get('confidence', 0)}%) — {neut.get('rationale', '')}"
                )
            if specialists:
                gpt_reasoning_parts.append("Catalyst Specialists:")
                for sp in specialists:
                    gpt_reasoning_parts.append(
                        f"• [{sp.get('subagent')}]: {sp.get('verdict')} ({sp.get('confidence')}%) — {sp.get('specialist_rationale')}"
                    )
            gpt_reasoning_parts.append(f"Base Reasoning: {ep.get('reasoning', '')}")
            gpt_reasoning_parts.append("</thought>")

            gpt_turn_1 = (
                f"{chr(10).join(gpt_reasoning_parts)}\n\n"
                f"**Directional Prediction**: {ep.get('prediction')} | **BTST Bias**: {ep.get('btst_bias')}\n"
                f"**Calibrated Trade Structure**: {ep.get('btst_structure')}\n"
                f"**Committee Consensus**: {ep.get('debate_consensus')} (Confidence: {ep.get('confidence')}%)\n"
                f"**Actionable Instruction**: {ep.get('trade_instruction') or 'Execute with tight stop loss and disciplined sizing.'}"
            )

            conversations = [
                {"from": "system", "value": _SYSTEM_PROMPT},
                {"from": "human", "value": signals_desc},
                {"from": "gpt", "value": gpt_turn_1},
            ]

            # If outcome is known, add settlement evaluation and reflection turns
            outcome = ep.get("outcome")
            reflection = ep.get("reflection")
            if outcome or reflection:
                human_turn_2 = (
                    f"Market Settlement Report for {trade_date}:\n"
                    f"- Actual Open Gap: {ep.get('actual_gap_pct'):+.2f}%\n"
                    f"- Trade Outcome: {outcome or 'SETTLED'}\n\n"
                    "Conduct a disciplined post-mortem reflection. Review what held, what failed, and the durable lesson learned."
                )
                gpt_turn_2 = (
                    f"Post-Mortem Reflection:\n"
                    f"{reflection or f'The trade outcome was {outcome}. The directional bias performed in accordance with risk limits.'}"
                )
                conversations.append({"from": "human", "value": human_turn_2})
                conversations.append({"from": "gpt", "value": gpt_turn_2})

            sharegpt_dataset.append({
                "id": f"nifty_btst_{trade_date}",
                "conversations": conversations,
            })

        return sharegpt_dataset

    def export_dpo(self, episodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """
        Convert trade trajectories into DPO (Direct Preference Optimization) pair format.
        """
        if episodes is None:
            episodes = self.collect_trajectories()

        dpo_dataset: list[dict[str, Any]] = []

        for ep in episodes:
            trade_date = ep.get("trade_date", "unknown_date")
            outcome = ep.get("outcome", "").upper()
            signals = ep.get("market_signals", {})
            structure = ep.get("btst_structure", "HALF_QUANTITY")
            instruction = ep.get("trade_instruction", "")
            reasoning = ep.get("reasoning", "")
            reflection = ep.get("reflection", "")

            prompt = (
                f"Analyze NIFTY 50 overnight trade risk for {trade_date}:\n"
                f"GIFT Nifty: {signals.get('gift_nifty_change_pct', 'N/A')}%, "
                f"India VIX: {signals.get('india_vix', 'N/A')}, "
                f"FII Net: ₹{signals.get('fii_net', 'N/A')} Cr, "
                f"PCR: {signals.get('pcr', 'N/A')}.\n"
                "Recommend calibrated position sizing, risk controls, and BTST options structure."
            )

            is_correct = "CORRECT" in outcome

            if is_correct:
                # Chosen is the winning calibrated strategy with risk bounds
                chosen = (
                    f"Calibrated Verdict: {structure}\n"
                    f"Consensus: {ep.get('debate_consensus', 'MAJORITY')} (Confidence: {ep.get('confidence', 70)}%)\n"
                    f"Strategy: {instruction or 'Deploy controlled size adhering to conservative bounds.'}\n"
                    f"Rationale: {reasoning}\n"
                    "Risk Controls: VIX and theta decay strictly factored in; stops enforced."
                )
                # Rejected is an aggressive uncalibrated bet ignoring risk bounds
                rejected = (
                    f"Calibrated Verdict: FULL_BTST\n"
                    f"Consensus: UNANIMOUS (Confidence: 95%)\n"
                    f"Strategy: Take maximum naked contracts without stop loss.\n"
                    f"Rationale: Pure momentum bet. Disregard VIX levels, theta decay, or overnight headline risk."
                )
            elif "WRONG" in outcome:
                # When wrong, the chosen response is the corrective defensive strategy learned in reflection
                chosen = (
                    f"Calibrated Verdict: STRICT_NO_TRADE (Defensive Fallback)\n"
                    f"Post-Mortem Lesson: {reflection or 'Macro signals diverged; defensive capital preservation mandated.'}\n"
                    f"Corrective Action: Never take naked directional risk when heavyweight or institutional signals conflict with momentum."
                )
                # Rejected was the failed thesis that caused the wrong call
                rejected = (
                    f"Calibrated Verdict: FULL_BTST\n"
                    f"Rationale: {reasoning or 'Overconfidently held directional position despite conflicting macro signals.'}\n"
                    "Action: Ignored dissenting committee signals and maintained unhedged overnight exposure."
                )
            else:
                # Partial / Neutral
                chosen = (
                    f"Calibrated Verdict: HEDGED_SPREAD\n"
                    f"Rationale: Mixed signals warrant defined-risk spread structures rather than naked calls or puts.\n"
                    f"Instruction: {instruction or 'Cap downside with vertical spreads.'}"
                )
                rejected = (
                    f"Calibrated Verdict: FULL_BTST\n"
                    "Rationale: High conviction despite mixed signals; full capital allocation without hedging."
                )

            dpo_dataset.append({
                "id": f"nifty_dpo_{trade_date}",
                "prompt": prompt,
                "chosen": chosen,
                "rejected": rejected,
                "metadata": {
                    "trade_date": trade_date,
                    "prediction": ep.get("prediction"),
                    "btst_bias": ep.get("btst_bias"),
                    "outcome": outcome or "SETTLED",
                    "actual_gap_pct": ep.get("actual_gap_pct", 0.0),
                    "confidence": ep.get("confidence", 50),
                },
            })

        return dpo_dataset

    def export_alpaca(self, episodes: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """
        Convert trade trajectories into Alpaca instruction-tuning format.
        """
        if episodes is None:
            episodes = self.collect_trajectories()

        alpaca_dataset: list[dict[str, Any]] = []

        for ep in episodes:
            trade_date = ep.get("trade_date", "unknown_date")
            signals = ep.get("market_signals", {})

            instruction = (
                "You are an institutional NIFTY 50 trading quant. "
                "Synthesize prevailing market signals into a calibrated BTST trade structure and risk allocation."
            )
            input_text = (
                f"Date: {trade_date}\n"
                f"GIFT Nifty: {signals.get('gift_nifty_change_pct', 'N/A')}%\n"
                f"India VIX: {signals.get('india_vix', 'N/A')}\n"
                f"FII Net Flow: ₹{signals.get('fii_net', 'N/A')} Cr\n"
                f"PCR: {signals.get('pcr', 'N/A')}"
            )
            output_text = (
                f"Prediction: {ep.get('prediction')} | Bias: {ep.get('btst_bias')}\n"
                f"Structure: {ep.get('btst_structure')} ({ep.get('debate_consensus')})\n"
                f"Confidence: {ep.get('confidence')}%\n"
                f"Instruction: {ep.get('trade_instruction')}\n"
                f"Analysis: {ep.get('reasoning')}"
            )

            alpaca_dataset.append({
                "instruction": instruction,
                "input": input_text,
                "output": output_text,
                "metadata": {
                    "trade_date": trade_date,
                    "outcome": ep.get("outcome", ""),
                },
            })

        return alpaca_dataset
