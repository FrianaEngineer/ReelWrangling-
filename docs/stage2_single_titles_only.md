# Stage 2: Expanded Records -> Single Titles Only

## Goal

After Stage 1 expands collections into constituent titles, Stage 2 converts the working dataset into a strict single-title table.

At the end of Stage 2:

- every row corresponds to exactly one title
- standalone Criterion titles remain as single-title rows
- collection-derived constituent titles remain as single-title rows

The dataset should no longer contain:

- collection-level entries
- bundled package rows
- multi-film rows
- container titles used as counted film rows

## Input To Stage 2

Stage 2 starts from two sources:

- original standalone Criterion title rows
- collection-derived constituent rows produced during Stage 1

Relevant repo artifacts:

- [final_clean_films.csv](/Users/friana/CriterionClustering/outputs/final_clean_films.csv)
- [collection_unpack_second_pass.csv](/Users/friana/CriterionClustering/outputs/collection_unpack_second_pass.csv)
- [resolved_collections.csv](/Users/friana/CriterionClustering/outputs/resolved_collections.csv)

## Output Of Stage 2

The output should be one normalized dataset where each row represents one title only.

That means:

- one film = one row
- one TV title = one row
- one short = one row
- one documentary = one row
- one unresolved ambiguous title = one row

The parent collection may still be referenced in metadata, but it must not survive as a counted content row.

## Core Rule

If a row still represents more than one title, Stage 2 is not complete.

## How Standalone And Collection-Derived Rows Combine

Stage 2 merges:

1. standalone Criterion rows already representing one title
2. expanded constituent rows from collections

The merge must preserve provenance, because collection-derived titles are not the same thing as standalone catalog rows even when they map to the same underlying film.

## Duplicate Resolution

Duplicates are expected because the same film may appear:

- as a standalone Criterion release
- inside one or more box sets or trilogies
- in multiple collection contexts

### Duplicate Resolution Order

1. exact IMDb ID match
2. normalized title + year match
3. normalized title + year within `±1` when other metadata supports the merge

### Resolution Rule

If a collection-derived row matches an existing standalone row:

- keep one canonical single-title record
- do not count the collection-derived row as a new unique title
- retain the collection as provenance metadata on the canonical record

If two rows look like the same title but the match is not fully defensible:

- do not force the merge
- keep them separate
- mark for review

### Practical Canonical Preference

When both exist, prefer the standalone Criterion row as canonical because it is usually cleaner and already normalized in the base pipeline.

The collection-derived row then contributes:

- parent collection
- expansion source
- expansion confidence
- any alternate year/runtime evidence

## Collection Metadata Retention

Collection metadata should not be discarded. It should move from row identity into provenance fields.

### Keep

- parent collection title
- parent collection id
- collection type
- expansion method
- expansion confidence
- collection notes

### Do Not Keep As Primary Row Identity

- collection title as the main title field
- package/container status as the content identity

The title row should represent the constituent title, not the package.

## Parent Collection Storage

Parent collection information should be stored as metadata attached to the constituent title row.

Recommended fields:

- `original_criterion_id`
- `parent_collection_id`
- `parent_collection_title`
- `expansion_source`
- `expansion_confidence`
- `expansion_reason`
- `is_collection_constituent`

If a title appears in more than one collection, parent collection storage should allow multiple sources.

Two valid approaches:

- store one canonical row plus a separate provenance table
- store one canonical row with a multi-source field or linked source table

The cleaner design is a canonical titles table plus a linked provenance table.

## Suggested Metadata

Minimum recommended metadata for every Stage 2 row:

- `canonical_title`
- `normalized_title`
- `imdb_id`
- `criterion_year`
- `imdb_year`
- `runtime_minutes`
- `title_type`
- `original_criterion_id`
- `is_collection_constituent`
- `parent_collection_id`
- `parent_collection_title`
- `expansion_source`
- `expansion_confidence`
- `needs_manual_review`
- `reason`

Recommended additional provenance fields:

- `source_row_type`
  - standalone
  - collection_constituent
- `canonicalization_method`
  - imdb_id_exact
  - title_year_exact
  - title_year_fuzzy
  - unresolved

## Handling Multi-Source Titles

A single title can have multiple Criterion-source contexts.

Example:

- standalone release
- trilogy package
- director box set

Stage 2 should not duplicate the title row for each context if the goal is a unique-title dataset.

Instead:

- one canonical row represents the title
- one or more linked provenance records represent where it appeared

## Ambiguous Cases

If a collection-derived row is still ambiguous after Stage 1:

- keep it as a single-title candidate row
- do not collapse it into another record unless the match is justified
- retain `needs_manual_review = true`

Stage 2 still requires single-title rows, but not every row must be fully trusted yet.

That means unresolved rows may still exist, but they must each represent only one candidate title.

## Missing Information Cases

If runtime, year, or type is missing:

- preserve the row as one title
- preserve the uncertainty in metadata
- do not convert it back into a collection-level record

Missing metadata is a classification problem, not a reason to violate the one-title-per-row rule.

## Recommended Output Structure

Stage 2 works best as two linked outputs:

### 1. Canonical titles table

One row per unique title.

### 2. Title provenance table

One row per source relationship.

This avoids double-counting while preserving collection membership and expansion evidence.

## Completion Criteria

Stage 2 is complete when:

- no row represents multiple titles
- no collection/container row remains in the counted dataset
- duplicate titles are merged only when the merge is defensible
- collection metadata is preserved as provenance
- every collection-derived title still points back to its parent collection
- unresolved titles remain one-title rows with review flags rather than package rows
