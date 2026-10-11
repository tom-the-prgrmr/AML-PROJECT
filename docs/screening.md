# Name screening design notes

Phases 3b and 3c append further sections to this file.

## Why not Soundex / Metaphone

Vietnamese names are strings of short syllables (2 to 4 tokens per customer name). Two different
names usually differ in the vowel or the tone mark, which are exactly the parts that Soundex and
Metaphone throw away. The compound consonants common in Vietnamese (`NG`, `NH`, `TR`, `PH`, `KH`,
`TH`) are encoded with English pronunciation rules, so the codes carry little information.

Measured on the 228 distinct tokens of the `small` profile (seed 42), using a self-written
American Soundex:

- The 228 tokens collapse into only 115 codes.
- `H520` holds `HOANG`, `HONG`, `HUNG` and `HUONG`, four different given names with the same code.
- `H000` holds `HA`, `HAI`, `HAO`, `HIEU`, `HO`, `HOA`, `HUU` and more.
- `T000` holds `TAI`, `THAO`, `THI`, `THU` and more.

A phonetic code would therefore flood analysts with false positives. Diacritic stripping alone
already merges 280 accented tokens into 228, so the screening score uses normalised tokens,
rapidfuzz `token_set_ratio`, Jaro-Winkler and IDF weighting instead (see
`specs/screening-normalize-score.md`). Double Metaphone is rejected for the same reasons.

## Oracle UTL_MATCH vs Python

`aml screen-compare` runs a screen written in SQL next to the two-tier Python screen and counts how
the two differ. The SQL version joins `screening_customer_name` with `screening_list_name` (both
filled by Python, so there is one normaliser), blocks on the first letter of the order-free name
key and a length gap of at most `screening.sql_length_band` (3), scores each pair with Jaro-Winkler
and keeps scores of at least `screening.alert_threshold` (90). It has no IDF weighting, no
`token_set_ratio` and no Tier 2 (date of birth, nationality, gender), so it can only say "the names
look alike".

`UTL_MATCH.JARO_WINKLER_SIMILARITY` returns an integer from 0 to 100, the integer part of 100 times
the Jaro-Winkler value (`HUU LONG TRA` / `HUU LONG TRAN` gives 98, `TRA` / `TRAN` gives 94,
`AN` / `ANH` gives 91). It is not the same function as `rapidfuzz.distance.JaroWinkler`. On 611 test
pairs of name keys (Oracle 23.26.3, TINY seed 42), 311 pairs differ, by up to 0.15, mostly in the
low and middle score range (`HA` / `HOA`: Oracle 64, rapidfuzz 61). At the 85 mark the two agreed
on that sample, but over all 4367 distinct blocked pairs of TINY, 13 of the 114 pairs that reach
85 on at least one side are split (`DO HUYEN THI` / `DO HA THI`: Oracle 88, rapidfuzz 91). DuckDB's
`jaro_winkler_similarity` matches rapidfuzz exactly on the same 611 pairs. The DuckDB score is
`FLOOR(100 * similarity + 1e-9)`: the `1e-9` stops a score of exactly 90 from being computed as
89.999... and dropped.

On TINY the SQL screen compares 5797 pairs out of 133,500 and returns 32 pairs on DuckDB and 30 on
Oracle (a subset of the 32), all 5 ground-truth pairs included. On `small` (DuckDB) it returns 4737
pairs with all 25 true hits and precision 0.005, against 72 `ALERT` + `REVIEW` pairs from the
two-tier screen. Pure Jaro-Winkler therefore keeps recall but is as noisy as the fuzzy baseline.

Trade-off. SQL inside the database keeps personal data in place, runs next to the data and needs no
extra service. Python carries the parts that make screening usable: IDF weighting, token-level
matching, Tier 2 and a stored reason for each decision. The SQL version is a comparison, not a
replacement; the numbers from a real run go here after the demo step.

## Incremental screening

A full screen costs roughly (customers x names on the lists), because each customer is compared
with every candidate name. A daily change is a tiny part of that: a few customers are onboarded or
edited and a few list entries are added or removed. On TINY, three changes (one customer edit, one
new entry, one removed entry) need 7 candidate pairs, against 262 for the full run, and the
resulting current set equals a full run on the changed data (55 rows: 5 `ALERT`, 1 `REVIEW`,
49 `AUTO_CLEARED`). At production size the same ratio decides whether screening finishes in minutes
or hours, and a newly listed entry must raise an alert quickly instead of waiting for the next
full run.

No Phase 1 table has an update timestamp and `aml load` always replaces the data, so changes are
found by content: a SHA-256 fingerprint of the fields that feed Tier 1 and Tier 2 is compared with
`screening_state`. Changing a phone number or a `program` does not change a decision, so it does
not count. In production the same step would read an `updated_at` column or change data capture
(CDC) instead of fingerprinting whole tables.

The IDF is frozen at the last full run and kept in `screening_token_stats`. Recomputing it would
change the score of every pair a little and force a rescreen of everything. Freezing gives a clean
guarantee: an incremental run equals a full run that uses the same IDF. The cost is that a token
that first appears in a new customer is treated as unseen (highest IDF) until the next full run.
Run a full screen periodically (for example weekly) to refresh the IDF, and always after the
screening configuration changes: `run_incremental` refuses to run when the configuration hash
differs from the last full run.
