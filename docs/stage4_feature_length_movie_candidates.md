# Stage 4: IMDb Matched Titles -> Feature-Length Movie Candidates

## Goal

After Stage 3 attaches IMDb metadata to single-title rows, Stage 4 identifies which matched titles are valid feature-length movie candidates.

This stage does not need to answer every final curation question, but it should produce a defensible candidate set for titles that look like real feature films.

At the end of Stage 4:

- feature-length movie candidates are explicitly marked
- excluded non-feature rows remain visible
- borderline cases are flagged rather than forced

## Input To Stage 4

Stage 4 starts from rows that already have IMDb metadata attached, including:

- `imdb_id`
- `imdb_title_type`
- `imdb_runtime_minutes`
- `imdb_genres`
- `imdb_start_year`
- Criterion-side provenance and year fields

## Output Of Stage 4

Each row should be assigned one of these working outcomes:

- `feature_length_movie_candidate`
- `excluded_non_feature`
- `needs_manual_review`

This stage is specifically about identifying feature-length movie candidates, not about final inclusion in every downstream chart.

## Core Rules

### Rule 1: Title Type Must Support Movie-Like Content

Primary positive signal:

- `imdb_title_type = movie`

Primary negative signals:

- `tvEpisode`
- `tvSeries`
- `tvMiniSeries`
- `tvMovie`
- `tvSpecial`
- `short`
- `video`
- `tvShort`
- `videoGame`

### Rule 2: Runtime Threshold

Default feature-length threshold:

- `runtime >= 40 minutes`

### Why `40` Minutes

`40` minutes is a standard practical threshold for separating shorts from feature-length works. It is also consistent with how the current repo has been distinguishing short-form material from film-length candidates.

This threshold is strict enough to exclude obvious shorts while still allowing:

- older compact features
- experimental features
- borderline art-house films

## Recommended Decision Logic

Use the following default logic:

```text
IF imdb_title_type is missing:
    needs_manual_review

ELSE IF imdb_title_type in [tvEpisode, tvSeries, tvMiniSeries, tvMovie, tvSpecial]:
    excluded_non_feature

ELSE IF imdb_title_type in [short, video, tvShort, videoGame]:
    excluded_non_feature

ELSE IF runtime is known AND runtime < 40:
    excluded_non_feature

ELSE IF imdb_title_type == movie AND runtime >= 40:
    feature_length_movie_candidate

ELSE IF imdb_title_type == movie AND runtime is missing:
    needs_manual_review

ELSE:
    needs_manual_review
```

## Documentary Rule

This is the main project-policy branch.

Two valid policies exist:

### Policy A: Narrative Features Only

If the project is intended to count narrative feature films only:

- documentaries should not become feature-length movie candidates
- even if `titleType = movie`
- they should be excluded or routed to a separate documentary bucket

### Policy B: All Feature-Length Films

If the project is intended to count all feature-length films:

- feature-length documentaries can remain candidates
- as long as `titleType = movie` and `runtime >= 40`

### Current Repo Direction

The current working logic in this repo has generally treated documentaries as excluded from the main movie bucket unless explicitly allowed.

So the conservative default is:

- documentaries do not count as feature-length movie candidates
- unless the project explicitly switches to the broader “all feature-length films” rule

## Exact Thresholds Used

Recommended default thresholds:

- positive runtime threshold: `>= 40`
- short-form exclusion threshold: `< 40`
- year reconciliation tolerance for later sanity checks: `±1`

These thresholds should be stored in documentation or config so they are not hidden in code.

## Why These Thresholds Were Chosen

### Runtime

`40` minutes is the practical split between short-form and feature-length works.

It avoids:

- counting shorts as features
- counting supplements as features
- overfitting to modern theatrical runtimes

### Title Type

IMDb `titleType` is the strongest structured field for excluding obvious non-feature media:

- episodic TV
- miniseries
- bonus video content
- shorts

### Combined Rule

Using both `titleType` and `runtime` is safer than either alone:

- `titleType` catches obvious structural non-film content
- `runtime` catches short-form rows that still have `movie` set

## Edge Cases

### 1. `movie` With Runtime Missing

Example problem:

- IMDb says `movie`
- runtime is blank or unreliable

Rule:

- do not auto-accept
- mark `needs_manual_review`

### 2. `movie` With Runtime Under `40`

Example problem:

- featurette or short-classified content mislabeled as `movie`

Rule:

- exclude from feature-length candidates

### 3. TV Movies

Some TV movies are feature-length works, but they are not the same as theatrical feature-film candidates if the project excludes television-origin titles.

Rule:

- default to exclusion
- revisit only if project scope later expands

### 4. Miniseries Or Bundled TV Content

Even when long in runtime, these should not become feature-length movie candidates.

Rule:

- exclude by title type

### 5. Documentaries

This is a policy edge case rather than a metadata edge case.

Rule:

- make the documentary policy explicit before final counts are locked

### 6. Experimental Or Borderline Short Features

Some legitimate films are short by mainstream standards but still exceed `40` minutes.

Rule:

- allow them if they meet the runtime threshold and title type is `movie`

### 7. Contaminated Matches

If the row reached Stage 4 through a suspicious Stage 3 match:

- do not allow runtime/type alone to override the contamination risk
- keep the row in review

## Recommended Metadata Fields

Each Stage 4 row should preserve:

- `feature_candidate_status`
- `feature_candidate_reason`
- `runtime_threshold_used`
- `documentary_policy_used`
- `needs_manual_review`

Optional but useful:

- `excluded_by_title_type`
- `excluded_by_runtime`
- `documentary_excluded`

## Completion Criteria

Stage 4 is complete when:

- all IMDb-matched rows have been evaluated against explicit feature-length candidate rules
- title-type exclusions are consistent
- runtime threshold is documented
- documentary handling is explicit
- borderline rows are preserved for review rather than silently forced into or out of the candidate set
