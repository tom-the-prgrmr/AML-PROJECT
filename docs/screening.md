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
