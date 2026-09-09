---
name: rbi_mpc_iv_crush
description: Guidelines for high-impact monetary policy, RBI MPC announcements, and interest rate decisions.
triggers:
  - rbi_news_catalyst
  - event_risk_high
priority: 90
---

# RBI MPC & Monetary Policy Playbook

Monetary policy decisions create massive implied volatility (IV) distortion: premiums inflate before the announcement and instantly deflate (crush) post-decision.

## Execution Directives
1. **Pre-Event Premium Inflation**:
   - Option premiums are systematically overpriced going into 10:00 AM IST policy announcements.
   - Holding naked long options overnight before an MPC decision guarantees severe IV crush (15-25% drop in option value) even if NIFTY moves in the predicted direction.
2. **Trade Structuring Rules**:
   - Strictly prohibit naked `BUY CE` or `BUY PE`.
   - Prefer defined-risk credit spreads or `HEDGED_SPREAD` if a strong directional bias exists.
   - If consensus expects an unexpected rate change or repo rate stance shift, default to `STRICT_NO_TRADE`.
3. **Banking Heavyweight Exposure**:
   - Bank Nifty and private banking heavyweights (HDFC Bank, ICICI Bank, Kotak Bank) drive 80% of index variance on policy days.
   - If banking sentiment diverges from macro cues, abort index trades.
