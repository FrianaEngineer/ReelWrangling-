# Criterion Matching Algorithm

This document describes the canonicalization and fuzzy-matching logic implemented in [criterion_second_pass.py](/Users/friana/ReelWrangling/scripts/criterion_second_pass.py).

## Goal

Resolve Criterion titles against local IMDb tables using a conservative two-stage process with a `0..100` confidence-style score:

1. exact and canonicalized candidate generation
2. fuzzy scoring with year and director constraints

The matcher is designed to recover slight mismatches without turning into an unconstrained nearest-neighbor search.
It uses add-only scoring: contradictory evidence does not subtract points, but it prevents a candidate from earning points in that category.

## Inputs

- `data/criterion/criterion_films.csv`
- `data/imdb/title.basics.tsv`
- `data/imdb/title.akas.tsv`
- `data/imdb/title.crew.tsv`
- `data/imdb/name.basics.tsv`

## Canonicalization

### Titles

Each title is transformed into multiple canonical forms.

Base normalization:
- Unicode NFKD normalization
- strip accents
- normalize curly quotes and dash variants to ASCII
- lowercase
- convert `&` to `and`
- collapse whitespace

Canonical title cleanup:
- remove parenthetical text like `(English-Dubbed Version)`
- remove bracketed text
- remove known version labels such as:
  - `English-Dubbed Version`
  - `Black and White Version`
  - `Comprehensive Version`
  - `excerpt`
- normalize Roman numerals and ordinal suffixes

Derived title variants:
- article rewrites:
  - `The X`
  - `X, The`
- subtitle splits:
  - `Main Title: Subtitle`
  - `Main Title`
  - `Subtitle`
- loose variants with articles removed
- reduced variants with `part` or `episode` removed

Tokenization:
- split on non-alphanumeric characters
- drop common stopwords
- retain canonical tokens for overlap tests

### Directors

Director names are canonicalized separately from titles.

Base normalization:
- Unicode NFKD normalization
- strip accents
- lowercase
- remove punctuation
- collapse whitespace

Derived director variants:
- split multi-director strings on `and`, `&`, `/`, `,`, `;`
- keep full normalized names
- keep surname-only forms
- keep reordered forms such as `surname given`
- keep concatenated alphanumeric forms for near-equality checks

## Candidate generation

### Exact/canonical candidate generation

The matcher scans:
- `title.basics.tsv` using `primaryTitle` and `originalTitle`
- `title.akas.tsv` using `title`

A candidate `(criterion_row, imdb_tt)` is admitted if any title variant matches on:
- exact strict canonical title
- exact loose canonical title

### Fuzzy review candidate generation

For unresolved rows only, the matcher scans `title.basics.tsv` again and admits a fuzzy candidate if all of the following hold:
- at least 2 shared canonical title tokens
- IMDb year is within 2 years of Criterion year, when both exist
- title similarity is at least `0.72` or token overlap is at least `0.55`

This keeps fuzzy search narrow and year-bounded.

## Similarity functions

### Title similarity

`title_similarity(a, b)` computes the maximum `SequenceMatcher` ratio across canonical title variants of `a` and `b`.

This means title similarity is not based on raw strings. It is based on the best-aligned canonical forms after:
- punctuation cleanup
- article movement
- subtitle stripping
- version-label stripping

### Token overlap

`token_overlap` is Jaccard similarity over canonical title token sets:

`|A ∩ B| / |A ∪ B|`

## Scoring

Each candidate is scored on a `0..100` scale using the following buckets:

- title: `45`
- director: `35`
- year: `15`
- type / episode structure: `5`

AKA / translation support is built into the title bucket rather than treated as a separate additive bonus.

### Title bucket: 45 points

Title score is `45 * max(exact_component, fuzzy_component, aka_component)`.

Exact component:
- strict canonical title match: `1.00`
- loose canonical title match: `0.85`
- otherwise: `0.00`

Fuzzy component:
- average of:
  - title similarity across canonical title variants
  - canonical token Jaccard overlap

AKA component:
- English AKA support: `1.00`
- preferred regional AKA support: `0.90`
- otherwise: `0.00`

This is a balanced title policy: exact matches help a lot, strong fuzzy agreement can still earn most of the title bucket, and alternate-title support strengthens title confidence rather than acting as a separate extra bonus.

### Director bucket: 35 points

Director scoring is intentionally limited to:
- exact/split director match: full `35`
- surname match: `21` (`35 * 0.6`)
- otherwise: `0`

No fuzzy director points are awarded in the score, even though `director_similarity` is still reported for diagnostics.

### Year bucket: 15 points

- exact year: `15`
- within `+/-1`: `12`
- within `+/-2`: `8.25`
- within `+/-3`: `3.75`
- otherwise: `0`

### Type / episode bucket: 5 points

Same scoring is used for all records, but episodic rows can earn points differently:

For episodic Criterion rows:
- IMDb `tvEpisode`: `3`
- matching episode number: `2`
- plausible film-like fallback type (`movie`, `short`, `tvMovie`): `1`

For non-episodic rows:
- plausible film-like type (`movie`, `short`, `tvMovie`): `5`
- `tvEpisode`: `1.5`

Episode-number agreement is a small bonus only.

## Add-only penalties policy

This matcher uses add-only scoring.

That means:
- bad evidence never subtracts points
- but bad or missing evidence prevents a candidate from earning points in that bucket

Examples:
- wrong year does not incur a negative score; it earns `0` year points
- director mismatch does not subtract; it earns `0` director points
- missing IMDb director also earns `0` director points
- wrong episode number earns `0` episode-number points

## Director status labels

`director_match_status` is derived from canonicalized director comparison:

- `exact_or_split_match`
  - at least one normalized Criterion director equals at least one normalized IMDb director
- `surname_match`
  - no full-name match, but at least one surname matches
- `mismatch`
  - IMDb directors exist but none of the above are true
- `no_imdb_director`
  - IMDb record has no director in `title.crew.tsv`

## Acceptance rule

Candidates are ranked per Criterion row.

Top candidate is auto-accepted only if:
- score is at least `85`
- and margin to the next candidate is at least `15`

Otherwise the candidate is emitted to `manual_review_candidates.csv`.

## Why this is conservative

The matcher does not auto-accept based on fuzzy title similarity alone.

It requires fuzzy title evidence to be supported by:
- year proximity
- and preferably director agreement

With this setup, a perfect core match on title, director, year, and type can score `100` without needing separate additive AKA points.

That is intentional. It aims for balanced precision/recall while keeping auto-accept decisions conservative.
