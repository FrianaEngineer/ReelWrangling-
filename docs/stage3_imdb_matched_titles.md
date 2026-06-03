# Stage 3: Single Titles Only -> IMDb Matched Titles

## Goal

After Stage 2 produces a strict one-title-per-row dataset, Stage 3 matches those rows to IMDb records.

At the end of Stage 3:

- every successfully resolved title has an IMDb record attached
- the matching method is documented
- the confidence level is explicit
- unresolved rows remain visible rather than silently dropped

## Input To Stage 3

Stage 3 starts from the single-title dataset produced after:

- standalone Criterion rows are normalized to one title per row
- collection-derived rows are normalized to one title per row
- duplicates are either merged canonically or preserved as unresolved review cases

Typical inputs include:

- canonical title
- normalized title
- Criterion year
- Criterion director
- Criterion country
- runtime if known
- provenance from standalone or collection expansion

## Output Of Stage 3

The output should attach IMDb resolution metadata to each single-title row.

Recommended fields:

- `imdb_id`
- `imdb_primary_title`
- `imdb_original_title`
- `imdb_start_year`
- `imdb_runtime_minutes`
- `imdb_title_type`
- `imdb_genres`
- `matched_via`
- `match_confidence`
- `needs_manual_review`
- `match_reason`

Rows that fail to match should still remain in the dataset with blank IMDb fields plus a failure reason.

## Matching Procedure

Match titles in descending order of reliability.

### Step 1: Exact IMDb ID

If an IMDb ID is already known from a prior validated source:

- use it directly
- verify that title/year do not obviously contradict the source row

### Step 2: Exact Normalized Title Match

Try exact normalized title matching against:

- IMDb primary title
- IMDb original title
- IMDb alternate titles

This is the cleanest automatic path when the title is distinctive.

### Step 3: Title + Exact Year

If multiple exact title hits exist, prefer the row where:

- normalized title matches
- year matches exactly

### Step 4: Title + Year Within `±1`

If Criterion and IMDb use adjacent release years:

- allow a `±1` year reconciliation
- downgrade confidence unless another field confirms the match

### Step 5: Fuzzy Title Matching

Use fuzzy matching only after exact title routes fail.

This is useful for:

- punctuation differences
- transliteration differences
- article differences
- abbreviated titles
- small OCR or scrape noise

Fuzzy matching should not override strong contradictory metadata.

### Step 6: Alternate Titles

If the Criterion-facing title is not the same as IMDb primary title:

- search alternate titles
- search foreign-language titles
- search original titles

This is required for non-English films and titles marketed under different names.

### Step 7: Metadata Confirmation

When more than one candidate still looks plausible, use:

- year
- runtime
- director
- country
- title type

to narrow the match.

### Step 8: Manual Resolution

If no automatic path is defensible:

- do not force the match
- mark the row unresolved
- send it to manual review

## Tie-Breaking Rules

When multiple IMDb candidates are plausible, use this priority order:

1. existing validated IMDb ID
2. exact normalized title + exact year
3. exact normalized title + year within `±1`
4. exact normalized title + director match
5. exact normalized title + runtime consistency
6. alternate title match + corroborating metadata
7. fuzzy title match + corroborating metadata

### Hard Stop Rule

Do not choose a candidate when:

- multiple candidates remain plausible
- title is too generic
- year mismatch is large and unexplained
- runtime conflicts sharply
- director conflicts sharply

Those cases stay unresolved until manual review.

## Confidence Criteria

### High Confidence

Use high confidence when:

- IMDb ID is already validated
- title matches exactly
- year matches exactly or is clearly reconciled
- runtime and/or director also align

Typical examples:

- exact title + exact year
- exact alternate title + exact year + same director

### Medium Confidence

Use medium confidence when:

- title is strong but one field is slightly off
- year differs by `1`
- runtime is missing but the rest aligns
- alternate-title matching is required but the candidate is still clear

### Low Confidence

Use low confidence when:

- fuzzy matching is required
- multiple candidates are close
- runtime is missing and year is loose
- title is generic
- the match depends on weak inference

Low-confidence matches should usually be marked for manual review.

## Duplicate Handling

Stage 3 duplicate handling happens at two levels.

### 1. Duplicate Criterion Rows Matching The Same IMDb ID

If multiple single-title Criterion rows resolve to the same IMDb record:

- keep one canonical title entity if the project is building a unique-title table
- preserve multiple Criterion provenance links

### 2. Duplicate IMDb Candidates For One Criterion Row

If one Criterion row could plausibly map to multiple IMDb titles:

- do not merge candidates
- do not assign one arbitrarily
- mark as unresolved/manual review

## Matching Methods To Record

Every successful match should record the method used.

Recommended values:

- `imdb_id_exact`
- `title_exact`
- `title_exact_year_exact`
- `title_exact_year_pm1`
- `aka_exact`
- `aka_exact_year_exact`
- `fuzzy_title_year`
- `manual_resolution`

This allows later auditing of which parts of the dataset are strongest and which are fragile.

## Foreign-Language And Alternate Title Handling

Many Criterion titles are released under:

- English-language titles
- original-language titles
- alternate festival titles
- transliterated titles
- region-specific marketing titles

### Rule

Never assume the displayed Criterion title must equal IMDb primary title.

A strong match can come from:

- IMDb original title
- IMDb alternate title
- normalized transliteration
- known foreign-language alias

## Failure Cases

Stage 3 should explicitly preserve failure reasons.

Common failure cases:

- no IMDb candidate found
- multiple IMDb candidates remain plausible
- title is too generic
- collection-derived row is still contaminated
- runtime and year conflict too strongly
- title may refer to bonus material or a supplement
- metadata is incomplete on both sides

Recommended failure statuses:

- `no_match_found`
- `multiple_candidates`
- `metadata_conflict`
- `insufficient_metadata`
- `contaminated_source_row`

## Manual Resolution

Manual resolution is required when the automated matching procedure cannot produce a defensible single candidate.

Manual review should focus on:

- low-confidence fuzzy matches
- foreign-language ambiguity
- year conflicts greater than `1`
- titles with generic names
- partial collection spillover rows

Manual decisions should be logged so they can be replayed or audited later.

## Completion Criteria

Stage 3 is complete when:

- every single-title row has either a matched IMDb record or an explicit unresolved status
- the matching method is stored
- confidence is stored
- duplicate handling is explicit
- unresolved cases are preserved for review rather than silently excluded
