# Stage 1: Current Criterion Titles -> Expand Collections

## Goal

The raw Criterion title set mixes:

- single films
- collections
- box sets
- anthology releases
- television content
- shorts
- documentaries
- titles with missing information
- titles with ambiguous metadata

Stage 1 exists to convert collection/container records into constituent-title records so the downstream dataset works at the film level instead of the package level.

Collections are not dropped. They are unpacked.

## Output Of Stage 1

For every title currently treated as a collection/container:

1. identify that the record is a collection
2. extract constituent titles
3. create one normalized row per constituent title
4. retain the parent collection as provenance, not as a counted movie
5. flag uncertain cases for review instead of forcing a bad expansion

Example:

```text
Three Colors Trilogy
-> Three Colors: Blue
-> Three Colors: White
-> Three Colors: Red
```

## How Collections Are Identified

Collections are identified using a mix of title-pattern detection, existing Criterion metadata, and previously resolved collection maps.

### Signals Used

- explicit collection language in the Criterion title
  - `trilogy`
  - `anthology`
  - `box set`
  - `two films`
  - `three films`
  - `five films`
  - `six films`
  - `complete films`
  - `essential films`
  - `series`
- delimiter-based multi-title structures
  - slash-separated titles such as `Film A / Film B`
  - colon patterns where the left or right side contains multiple embedded titles
- existing resolved collection records
  - [resolved_collections.csv](/Users/friana/CriterionClustering/outputs/resolved_collections.csv)
- known collection maps and hand-built trusted decompositions already used in the repo

### Practical Rule

A record is treated as a collection when it represents a package or container rather than one stable film title.

This includes:

- director sets
- trilogy packages
- anthology packages
- Eclipse sets
- multi-film double features
- spineless Criterion sets with multiple contained works

This does not include:

- a single film with a subtitle that only looks collection-like
- a normal single film with supplements
- a reissue that still represents one primary film

## How Titles Inside Collections Are Found

Constituent titles are identified from the strongest available source in this order:

1. existing trusted decomposition maps
2. previously resolved collection constituent rows
3. title parsing from the collection name
4. Criterion catalog child records already attached to the package
5. manual review for unresolved containers

### Sources Used

- [collection_constituent_films.csv](/Users/friana/CriterionClustering/outputs/collection_constituent_films.csv)
- [resolved_collections.csv](/Users/friana/CriterionClustering/outputs/resolved_collections.csv)
- [unmatchedCollections.csv](/Users/friana/CriterionClustering/unmatchedCollections.csv)
- [collection_unpack_second_pass.csv](/Users/friana/CriterionClustering/outputs/collection_unpack_second_pass.csv)
- hand-maintained trusted collection maps embedded in the unpack logic

### Extraction Methods

The repo already uses multiple extraction styles. Those should remain explicit in the audit trail:

- slash split
  - `Film A / Film B`
- known collection map
  - prevalidated list of expected children
- virtual-only decomposition
  - children inferred from the package title when no clean child record exists
- spineless catalog child expansion
  - children found from attached catalog items in spineless sets
- manual decomposition
  - required when the package title is too broad or noisy

## Handling Bonus Material

Bonus material should not be promoted into the film-level movie dataset by default.

Examples:

- interviews
- trailers
- supplements
- essays
- commentary tracks
- behind-the-scenes material
- video essays

### Rule

If the extracted item is clearly supplemental rather than a primary film:

- keep it out of `Movies`
- classify it later into the non-feature bucket
- or leave it in `Untracked / Problem` if the extraction itself is too noisy

Bonus material should never be used as evidence that a collection contains a feature film.

## Handling Television Content

Collections can contain TV material alongside films.

Examples:

- television films
- miniseries entries
- episodic works
- TV specials

### Rule

Stage 1 should still extract those titles as constituent records, but it should preserve enough metadata so later classification can separate:

- feature films
- TV content
- shorts
- documentaries
- supplements

The presence of TV content is not a reason to discard the collection. It is a reason to unpack the collection more carefully.

## Handling Documentaries, Shorts, And Ambiguous Media

Stage 1 does not need to make every final inclusion decision, but it must preserve the extracted titles cleanly enough for later classification.

That means:

- documentaries stay as extracted titles
- shorts stay as extracted titles
- ambiguous media stays as extracted titles
- uncertain matches are flagged instead of forced

The expansion stage is about getting the package into film-level units. The classification stage decides whether those units count as movies.

## Duplicate Handling

Collections often contain films that already exist elsewhere in the Criterion dataset as standalone entries.

### Duplicate Rule

If a constituent title already exists as a tracked film:

- do not create a net-new movie entity
- keep the constituent row
- mark the collection as an additional source/provenance link

Priority order for duplicate detection:

1. IMDb ID exact match
2. normalized title + year
3. normalized title + year ±1 if the rest of the metadata aligns

### Why This Matters

The expanded collection view and the standalone Criterion view serve different purposes:

- standalone entries tell you what exists as a direct Criterion title
- expanded collection rows tell you what films are represented inside packages

Those should not be collapsed blindly, but they also should not be double-counted as new unique films.

## Ambiguous Cases

A constituent title is ambiguous when the extraction or match is not defensible.

Examples:

- generic extracted strings such as `Volume One`
- collection labels such as `An Anthology`
- child titles that could map to multiple IMDb records
- contaminated partial collections where the inherited child list is clearly noisy
- title/year pairs that imply an obviously wrong match

### Rule

Do not force these into the movie bucket.

Instead:

- preserve the row
- mark it for manual review
- keep the reason in the output

This is preferable to introducing false positives that inflate movie counts.

## Missing Information Cases

Some collections cannot yet be safely decomposed because the available data is incomplete.

Examples:

- no clean child list exists
- extracted title has no reliable IMDb match
- runtime or type is missing
- the package mixes valid films with unidentified supplements

### Rule

When information is missing:

- keep the collection and extracted items in the working dataset
- record the gap explicitly
- route the unresolved items to manual review or a not-yet-resolved bucket

Missing information should create a review obligation, not a silent drop.

## Recommended Audit Trail

Every expanded row should retain:

- parent collection id
- parent collection title
- extracted item title
- normalized item title
- extraction method
- match status
- duplicate status
- confidence
- review flag
- reason/note

This makes the collection expansion reproducible and debuggable.

## Current Repo Direction

The repo already moved toward a safer second pass:

- trusted decompositions are allowed through
- generic labels are blocked
- contaminated partial collections are pushed into review instead of being counted as movies

Relevant artifacts:

- [collection_unpack_agent.py](/Users/friana/CriterionClustering/scripts/collection_unpack_agent.py)
- [collection_unpack_second_pass.csv](/Users/friana/CriterionClustering/outputs/collection_unpack_second_pass.csv)
- [collection_unpack_second_pass_summary.csv](/Users/friana/CriterionClustering/outputs/collection_unpack_second_pass_summary.csv)

## Decision Checklist For Stage 1

Before marking Stage 1 complete, confirm:

- every collection/container record has either a trusted decomposition or an explicit review status
- collection rows are no longer treated as one movie by default
- constituent titles are stored as separate rows
- duplicate constituent films are linked, not double-counted
- bonus material does not leak into the movie set
- ambiguous extractions are preserved for review instead of forced into `Movies`
