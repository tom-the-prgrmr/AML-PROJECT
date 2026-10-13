# Case C-CIF00002224-20260226

> TEMPLATE SUMMARY (summary/v1): generated from stored case data without an LLM. It is not a disposition.

- Status: OPEN
- Customer: G-CIF00002224 (1 CIF(s), 2 account(s)), KYC risk LOW
- Alerts: 5 (3 RULE, 2 NETWORK, 0 SCREENING) between 2026-02-26 14:04:27 and 2026-03-03 06:09:24
- Priority: 0.9999 (queue rank 1, model prio/logreg/2)
- Disposition: none

## Subject

| CIF | Name | Birth year | Nationality | Occupation | KYC risk | ID |
|---|---|---|---|---|---|---|
| CIF00002224 | Phạm T. T. | 1948 | VN | Nhân viên ngân hàng | LOW | CCCD ********2828 |

Accounts: A1754909692 (CURRENT, CIF00002224), A6388537910 (CARD, CIF00002224)

## Alerts

| # | First event | Source | Rule | Reason |
|---|---|---|---|---|
| 1 | 2026-02-26 14:04:27 | RULE | FAN_IN | received 1,046,794,000 VND from 14 new senders in 14 transactions between 2026-02-26 14:04:27 and 2026-03-02 23:51:05 (at least 8 within 7 days) |
| 2 | 2026-02-26 14:04:27 | NETWORK | NET_HUB | received 1,046,794,000 VND from 14 accounts of other customers in 14 transfers between 2026-02-26 14:04:27 and 2026-03-02 23:51:05; PageRank 2.13x the average of 4980 active accounts |
| 3 | 2026-03-01 12:35:29 | RULE | HIGH_VELOCITY | 9 transactions totalling 769,855,000 VND between 2026-03-01 12:35:29 and 2026-03-02 10:14:07 (at least 8 within 24 hours; counterparties known for 14+ days excluded) |
| 4 | 2026-03-01 12:35:29 | NETWORK | NET_SHARED_ATTRIBUTE | 12 customers (25 accounts) linked by shared device (8 customers), phone (3), address (3); 11 transfer(s) totalling 919,818,000 VND between members between 2026-03-01 12:35:29 and 2026-03-02 23:51:05 |
| 5 | 2026-03-02 06:48:19 | RULE | RAPID_MOVEMENT | received 267,279,000 VND and sent out 248,151,000 VND (93%) between 2026-03-02 06:48:19 and 2026-03-03 06:09:24 |

## Priority factors

| Feature | Value | Contribution |
|---|---|---|
| pagerank_ratio | 2.1267 | -4.88 |
| distinct_rules | 5 | +2.99 |
| has_fan_in | 1 | +2.50 |
| has_net_hub | 1 | +2.50 |
| in_degree | 14 | +1.95 |

## Activity from 2025-12-04 to 2026-03-03

- 18 transaction(s) on 5 day(s): 14 in totalling 1,046,794,000 VND, 4 out totalling 1,009,924,000 VND
- Cash: 0 VND in, 0 VND out
- 18 counterparty(ies); largest transaction 379,717,000 VND

| Channel | Transactions | VND |
|---|---|---|
| EBANKING | 9 | 639,441,000 |
| INTERNAL_TRANSFER | 9 | 1,417,277,000 |

## Network

- Graph features (gds): in-degree 14, out-degree 4, PageRank ratio 2.13, shared cluster SHARED-CIF00000698 (12 customers), component size 19, community size 19

| Counterparty | Owner | Direction | Transactions | VND |
|---|---|---|---|---|
| A9338817028 | G-CIF00002915 | OUT | 1 | 379,717,000 |
| A5491784687 | G-CIF00003599 | OUT | 1 | 248,151,000 |
| A1107030187 | G-CIF00004629 | OUT | 1 | 243,257,000 |
| A7363892226 | G-CIF00002539 | OUT | 1 | 138,799,000 |
| A2660851609 | G-CIF00004135 | IN | 1 | 125,374,000 |

- Related cases sharing an alert: C-CIF00000698-20260301, C-CIF00000732-20260301, C-CIF00001508-20260301, C-CIF00001527-20260301, C-CIF00002107-20260301, C-CIF00002316-20260301, C-CIF00002569-20260301, C-CIF00002597-20260301, C-CIF00002862-20260301, C-CIF00004135-20260301, C-CIF00004567-20260301

## Data quality

- No data quality issue found.

## History

- Prior cases: none
- Auto-cleared screening matches: 0; suppressed alerts in this run: 0

---
Template summary/v1; case run 5; no LLM was used.
