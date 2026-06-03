# Stage 5: Feature-Length Movie Candidates -> Manual Review

## Goal

After Stage 4 identifies feature-length movie candidates, Stage 5 handles the cases that cannot be accepted or excluded safely with automated rules alone.

This stage exists to resolve ambiguity without lowering the quality of the final dataset.

At the end of Stage 5:

- difficult rows have a documented review reason
- the evidence examined is recorded
- a final resolution path is chosen
- unresolved rows remain explicit rather than silently dropped

## What Enters Manual Review

Manual review is triggered when a row remains ambiguous after matching and candidate filtering.

Common triggers include:

- multiple plausible IMDb matches
- conflicting Criterion and IMDb years
- uncertain or missing runtime
- missing metadata
- inconsistent title types
- foreign release / alternate title ambiguity
- unusual content categories
- suspicious collection-derived rows
- contaminated inherited matches

## Manual Review Does Not Mean Failure

A row entering manual review is not necessarily wrong.

It means:

- the automated pipeline does not have enough confidence
- the decision affects final counts
- a human should confirm the match or classification

## Required Review Metadata

Every manual-review row should preserve:

- `review_reason`
- `review_status`
- `evidence_examined`
- `resolution_strategy`
- `final_decision`
- `review_notes`

Recommended supporting fields:

- `candidate_count`
- `candidate_ids`
- `criterion_year`
- `imdb_year`
- `runtime_minutes`
- `imdb_title_type`
- `source_collection_title`
- `match_confidence`

## Why Titles Entered Manual Review

The reason should be explicit and specific.

Recommended reason labels:

- `multiple_imdb_matches`
- `year_conflict`
- `runtime_missing`
- `runtime_conflict`
- `metadata_missing`
- `title_type_conflict`
- `foreign_title_ambiguity`
- `generic_title`
- `collection_contamination`
- `documentary_policy_ambiguous`
- `bonus_material_unclear`

Avoid generic labels like `manual review needed` without a cause.

## Information Examined

Manual review should be based on concrete evidence, not intuition alone.

Typical evidence sources:

- Criterion title
- Criterion year
- Criterion director
- Criterion country
- collection parent metadata
- extracted constituent title
- IMDb primary title
- IMDb original title
- IMDb alternate titles
- IMDb year
- IMDb runtime
- IMDb title type
- IMDb genres
- previously matched local rows
- existing manual resolution logs

If available, reviewer notes should state which fields actually resolved the ambiguity.

## Resolution Strategy

Manual review should follow a predictable strategy instead of one-off judgment.

### Step 1: Confirm The Title Unit

Before reviewing the match, confirm that the row really represents one title and not:

- a collection label
- a supplement
- a disc marker
- a contaminated inherited child row

If the row is not a real single-title unit, do not continue to IMDb resolution. Route it out of the movie path.

### Step 2: Compare Candidate Matches

If multiple IMDb candidates exist, compare:

- title similarity
- exact or near-exact year
- runtime
- director
- country
- title type

### Step 3: Prefer Strong Structural Evidence

Use this evidence priority:

1. exact validated IMDb ID
2. exact normalized title + exact year
3. exact normalized title + same director
4. exact alternate title + exact year
5. runtime consistency
6. fuzzy title similarity

### Step 4: Reject Bad Fits Explicitly

Do not keep weak candidates “just in case.”

If a candidate is wrong because of:

- major year conflict
- wrong title type
- implausible runtime
- unrelated director
- obvious supplement / TV / short mismatch

remove it from consideration explicitly.

### Step 5: Decide Final Outcome

Each reviewed row should end in one of these states:

- `resolved_match`
- `resolved_non_feature`
- `resolved_duplicate`
- `unresolved_keep_for_review`
- `excluded_bad_source_row`

## Tie-Breaking Rules

When two or more candidates remain plausible, use this order:

1. exact title + exact year
2. exact title + year within `±1`
3. exact title + same director
4. alternate title + corroborating metadata
5. runtime consistency
6. country consistency

If the tie still remains after that:

- do not pick a winner automatically
- keep the row unresolved

## Handling Conflicting Years

Year conflicts are common and should be handled by severity.

### Accept Automatically

- exact year match
- `±1` year difference with otherwise strong agreement

### Send To Review

- year difference greater than `1`
- same title but two plausible release eras
- year mismatch plus missing runtime

### Reject Candidate

- year conflict is large and the rest of the metadata is weak

## Handling Missing Runtime

Missing runtime matters because Stage 4 uses runtime for feature-length filtering.

### If title type is clearly non-feature

- runtime may not matter
- classification can still be resolved

### If title type is `movie`

- missing runtime should usually keep the row in review unless another trusted source confirms feature length

## Handling Inconsistent Title Types

If a row has conflicting signals such as:

- `movie` in one place
- `tvMovie` or `tvMiniSeries` in another

manual review should prefer the structured IMDb title type unless there is strong evidence that the current match is wrong.

If the title type inconsistency is really a bad-match symptom:

- the resolution should be to reject the match, not to override IMDb blindly

## Handling Foreign Releases And Alternate Titles

Foreign-language titles need special care because:

- Criterion may use an English title
- IMDb may prefer the original-language title
- alternate market titles may differ sharply

### Rule

A foreign-title row should not be penalized just because the displayed titles differ.

Instead, compare:

- normalized alternate titles
- original title
- release year
- director
- country

## Handling Unusual Content Categories

Some rows look movie-like but belong to edge categories:

- concert films
- documentary hybrids
- essay films
- experimental features
- TV-origin films

These should not be decided by title alone.

Use:

- title type
- runtime
- genre
- project scope rules

If the project policy is still unclear, the row should remain flagged rather than forced.

## Recommended Review Log Structure

Each review decision should be logged as one row with:

- `title`
- `criterion_id`
- `parent_collection`
- `review_reason`
- `candidate_ids`
- `evidence_examined`
- `resolution_strategy`
- `final_decision`
- `final_imdb_id`
- `reviewer_note`

This makes manual decisions reproducible and auditable.

## Completion Criteria

Stage 5 is complete when:

- every manual-review row has an explicit reason
- the evidence examined is documented
- tie-breaking rules are applied consistently
- final decisions are logged
- unresolved cases remain visible rather than being dropped or guessed
