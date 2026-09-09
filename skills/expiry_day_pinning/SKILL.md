---
name: expiry_day_pinning
description: Rules for BTST options selection when tomorrow is weekly or monthly options expiry.
triggers:
  - dte_near_or_zero
  - fo_expiry
priority: 95
---

# Expiry Day BTST & Pinning Playbook

When holding overnight options into an Expiry Day (DTE <= 1), theta decay is non-linear and Max Pain creates strong directional magnetic pull.

## Execution Directives
1. **Max Pain Gravitational Check**:
   - If NIFTY spot is within ±35 points of the Max Pain strike, assume range pinning at market open.
   - Do NOT take naked directional options (BUY CE / BUY PE) when spot is pinned near Max Pain.
2. **Mandatory Hedging or Half Sizing**:
   - Never recommend `FULL_BTST` on naked calls/puts when DTE <= 1.
   - Force trade structure to `HEDGED_SPREAD` (e.g. Bull Call Spread / Bear Put Spread) or `HALF_QUANTITY`.
3. **Theta Crush Penalty**:
   - Sub-0.30% gap moves will be fully eaten by overnight theta decay on expiry morning.
   - Clamp directional confidence by 15% if proposed gap expectation is mild.
4. **Veto Conditions**:
   - If India VIX > 17.5 on expiry eve, recommend `STRICT_NO_TRADE` due to morning volatility collapse risk.
