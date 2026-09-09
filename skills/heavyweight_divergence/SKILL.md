---
name: heavyweight_divergence
description: Rules for when NIFTY heavyweights (HDFC Bank, Reliance) decouple from broad market gap cues.
triggers:
  - heavyweight_conflict
  - reliance_hdfc_counter_trend
priority: 85
---

# Heavyweight Divergence Playbook

HDFC Bank (~13%) and Reliance Industries (~9%) command ~22% combined weight in NIFTY 50. Broad market signals cannot overcome a synchronized heavyweight drag.

## Execution Directives
1. **The Twin Heavyweight Veto**:
   - If GIFT Nifty or macro news suggests `GAP UP`, but both HDFC Bank and Reliance closed down > 0.40% on weak technical volume, the gap up is high-risk and prone to immediate morning fade.
   - If both heavyweights are up > 0.40%, do NOT recommend `BUY PE` regardless of global market negativity.
2. **Opening Fade Traps**:
   - An opening gap driven solely by IT or midcaps without banking/energy participation creates an opening pop followed by a steep retracement within the first 15 minutes.
   - In such cases, clamp BTST sizing to `HALF_QUANTITY` or advise waiting for the 09:45 IST intraday opening range breakout.
3. **Earnings & Results Distortion**:
   - On days when Reliance, TCS, or HDFC Bank report quarterly earnings post-market, overnight BTST should either be avoided (`STRICT_NO_TRADE`) or limited to hedged spreads.
