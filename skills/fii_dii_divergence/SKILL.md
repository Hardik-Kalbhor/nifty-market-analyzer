---
name: fii_dii_divergence
description: Institutional flow dynamics when foreign institutions (FII) and domestic institutions (DII) are in sharp opposition.
triggers:
  - institutional_absorption
  - fii_sell_dii_buy_extreme
priority: 80
---

# Institutional Absorption & FII/DII Divergence Playbook

When foreign institutions (FII) are heavy net sellers while domestic mutual funds and insurance (DII) aggressively absorb liquidity, traditional momentum models generate false break signals.

## Execution Directives
1. **Absorption Dynamics (FII < -2,000 Cr & DII > +2,500 Cr)**:
   - Domestic liquidity acts as a hard cushion. Do NOT chase aggressive `BUY PE` breakdowns on foreign selling when DII net buying exceeds FII net selling.
   - Gaps down on heavy DII absorption often turn into morning short-covering rallies between 09:30 and 10:15 IST.
2. **Distribution Top Traps (FII > +2,000 Cr & DII < -1,500 Cr)**:
   - FII buying into DII profit booking indicates institutional hand-off.
   - Require confluence from GIFT Nifty (> +0.30%) and US market momentum before entering `BUY CE`.
3. **Execution Sizing**:
   - Institutional opposition compresses next-day gap magnitude.
   - Default structure should be `HALF_QUANTITY` or `HEDGED_SPREAD` to protect against choppy, range-bound open.
