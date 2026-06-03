# Stage 6: Manual Review -> IMDb Verified Feature-Length Movies

## Goal

Stage 6 is the final verification layer.

After Stage 5 resolves or escalates ambiguous cases, Stage 6 applies the final rules that determine which rows become verified feature-length movie records and which rows fall into non-movie, unresolved, or data-quality buckets.

At the end of Stage 6:

- every row has a final bucket
- the verification logic is documented
- year consistency is explicitly tracked
- unresolved and low-quality rows remain visible

## Final Output Buckets

Every reviewed row should end in exactly one of these final buckets:

- `Years Match`
- `Years Off`
- `Unverified Titles`
- `Other Content`
- `Data Issues / Untracked`

These buckets are final reporting buckets, not intermediate workflow states.

## Final Decision Process

Stage 6 should apply the following order:

1. confirm the row represents one real title
2. confirm the row has a defensible IMDb match if one exists
3. confirm the row is in-scope feature-length content
4. compare Criterion year and IMDb year
5. assign the final bucket
6. record any remaining uncertainty

## Rules Applied

### Rule 1: Verified Match Required For Film Buckets

A row can only land in `Years Match` or `Years Off` if:

- it has a defensible IMDb match
- it passed the feature-length movie rules
- it is not TV, short-form, bonus material, or other non-target media

### Rule 2: Non-Feature Content Goes To `Other Content`

Use `Other Content` for rows that are valid media records but not target feature-length films.

Examples:

- TV content
- shorts
- miniseries
- TV movies if excluded by project scope
- bonus material
- supplements
- video material
- documentaries, if the project policy excludes them

### Rule 3: Uncertain Match Goes To `Unverified Titles`

Use `Unverified Titles` when:

- the title could not be confidently matched
- more than one IMDb candidate remained plausible
- the metadata is too weak to verify the title cleanly
- no defensible final decision can be made yet

### Rule 4: Data Failures Go To `Data Issues / Untracked`

Use `Data Issues / Untracked` when the row could not be processed reliably because of data quality problems.

Examples:

- missing required fields
- parsing failure
- broken inherited collection extraction
- malformed source row
- unresolved record with unusable metadata

### Rule 5: Verified Feature-Length Films Split By Year Agreement

Once a row is confirmed as a verified feature-length movie:

- `Years Match` if Criterion year and IMDb year agree
- `Years Off` if Criterion year and IMDb year disagree

## Bucket Definitions

## `Years Match`

Use `Years Match` when:

- the title is a verified feature-length movie
- the IMDb release year agrees with Criterion metadata

### Default Interpretation

This is the cleanest final movie bucket.

These rows should normally require no additional verification unless another field remains suspicious.

## `Years Off`

Use `Years Off` when:

- the title is still retained as a verified feature-length movie
- Criterion year and IMDb year disagree

### Required Documentation

For each `Years Off` row, record:

- Criterion year
- IMDb year
- absolute year difference
- likely explanation
- whether the title was retained

### Likely Explanations

- different release-year conventions
- production year vs release year
- region-specific release timing
- known catalog inconsistency
- inherited bad match that should still be reviewed

### Retention Rule

A `Years Off` row can still be retained if the overall title match is strong.

If the year conflict is large and the rest of the metadata is weak, the row should not stay in `Years Off`; it should fall back to `Unverified Titles` or `Data Issues / Untracked`.

## `Unverified Titles`

Use `Unverified Titles` when the row might represent a real target title, but final verification is not defensible.

Examples:

- missing metadata
- multiple possible matches
- no IMDb entry found
- unresolved title ambiguity
- foreign-title ambiguity not resolved

### Key Distinction

`Unverified Titles` means the title unit itself may still be valid, but the verification is incomplete.

## `Other Content`

Use `Other Content` for items that are not target feature-length films.

Examples:

- TV content
- shorts
- bonus material
- video essays
- supplements
- non-target documentary rows if the project excludes documentaries
- other non-target media

### Key Distinction

These rows are not bad data. They are real content that falls outside the final target scope.

## `Data Issues / Untracked`

Use `Data Issues / Untracked` when a row fails because the data itself is unreliable or incomplete enough to block verification.

Examples:

- missing fields
- parsing failures
- contaminated collection expansion
- unresolved broken records
- malformed imported rows

### Key Distinction

This bucket is about source quality or processing failure, not just ordinary uncertainty.

## Remaining Uncertainty

Stage 6 should preserve uncertainty explicitly.

Recommended uncertainty fields:

- `verification_confidence`
- `remaining_uncertainty`
- `needs_followup`
- `followup_reason`

Examples of remaining uncertainty:

- year mismatch larger than expected but title retained
- runtime inferred from weak evidence
- foreign-title resolution acceptable but not perfect
- collection-derived provenance still partially noisy

## Quality Checks Performed

Before final export, run explicit quality checks.

### Check 1: One Title Per Row

Verify:

- no row still represents a collection
- no row still represents a multi-film package

### Check 2: Final Bucket Coverage

Verify:

- every row lands in exactly one final bucket
- no row is left without a final status

### Check 3: IMDb Match Consistency

Verify:

- `Years Match` and `Years Off` rows all have nonblank IMDb IDs
- `Unverified Titles` rows do not pretend to be fully resolved

### Check 4: Feature-Length Consistency

Verify:

- `Years Match` and `Years Off` rows satisfy the feature-length movie rules
- `Other Content` rows capture TV, short, and non-target media properly

### Check 5: Year-Mismatch Audit

Verify for every `Years Off` row:

- year difference is recorded
- retention decision is recorded
- explanation is recorded

### Check 6: Duplicate Audit

Verify:

- duplicate IMDb IDs are either intentional provenance duplicates or canonically merged
- duplicate rows are not silently double-counted

### Check 7: Manual Review Closure

Verify:

- every manual-review row has either been resolved or placed into a final non-verified bucket

## Recommended Final Metadata

Each final row should preserve:

- `final_bucket`
- `imdb_verified`
- `verification_confidence`
- `criterion_year`
- `imdb_year`
- `year_difference`
- `retained_in_final_movie_set`
- `likely_explanation`
- `needs_followup`
- `followup_reason`

Useful supporting provenance:

- `original_criterion_id`
- `parent_collection_id`
- `parent_collection_title`
- `match_method`
- `manual_review_status`

## Completion Criteria

Stage 6 is complete when:

- every row has exactly one final bucket
- verified feature-length films are split into `Years Match` and `Years Off`
- unresolved titles remain explicit in `Unverified Titles`
- non-target media is separated into `Other Content`
- source and processing failures are separated into `Data Issues / Untracked`
- quality checks have been run and documented
