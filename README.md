# Reel Wrangling

## Project Goal

`ReelWrangling` contains the Criterion + IMDb data wrangling pipeline that prepares enriched Criterion film records for downstream analysis. The purpose of this repository is to separate data enrichment and preprocessing from clustering, visualization, and website work so that the wrangling steps are easier to inspect, maintain, and reuse.

## Data Sources

The repository currently works with three local data areas:

- `data/criterion/` for Criterion-side source and intermediate files
- `data/imdb/` for local IMDb TSV files
- `data/output/` for merged, reviewed, validated, and final outputs

Current key files include:

- `data/criterion/criterion.csv`
- `data/criterion/new-criterion.csv`
- `data/criterion/criterion_browse_fields.csv`
- `data/criterion/eclipse_series_titles.csv`
- `data/imdb/title.basics.tsv`
- `data/imdb/title.akas.tsv`
- `data/imdb/title.crew.tsv`
- `data/imdb/name.basics.tsv`
- `data/imdb/title.principals.tsv`

## Folder Structure

```text
ReelWrangling/
├── README.md
├── .gitignore
├── data/
│   ├── criterion/
│   ├── imdb/
│   └── output/
├── docs/
├── notebooks/
└── src/
    ├── criterion/
    ├── imdb/
    ├── scraping/
    ├── shared/
    └── wrangling/
```

High-level purpose of the source folders:

- `src/criterion/` loads and prepares Criterion-side inputs
- `src/imdb/` handles IMDb matching, lookup, and candidate evaluation
- `src/scraping/` contains scraper support for Criterion Eclipse pages
- `src/shared/` contains shared normalization and file utilities
- `src/wrangling/` contains the multi-stage merge, review, validation, and export workflow

## Wrangling Pipeline

The current pipeline is script-based rather than a single CLI entrypoint. At a high level it works like this:

1. Load `data/criterion/criterion.csv`.
2. Build normalized Criterion working files such as `data/criterion/new-criterion.csv` and `data/criterion/criterion_browse_fields.csv`.
3. Normalize titles, directors, and year fields for more stable matching.
4. Run initial Criterion-to-IMDb matching against the local IMDb TSV files.
5. Split results into direct matches, review candidates, unmatched rows, and excluded shorts.
6. Build unmatched tracking and manual review worklists.
7. Resolve collection and box-set records into constituent titles where possible.
8. Apply manual resolutions and collection-level decisions.
9. Build the final clean film-level dataset.
10. Validate outputs and produce summary reports.

The pipeline is intentionally audit-heavy. It preserves unresolved and ambiguous cases instead of silently forcing weak matches.

## IMDb Enrichment Process

The IMDb enrichment process currently relies on:

- `title.basics.tsv` for title type, primary title, original title, start year, runtime, and genres
- `title.akas.tsv` for alternate-title matching
- `title.crew.tsv` and `name.basics.tsv` for director confirmation
- `title.principals.tsv` for downstream actor-related work and later network-oriented steps

The matching logic generally does the following:

1. Compare Criterion titles to IMDb primary and original titles.
2. Check alternate titles in `title.akas.tsv`.
3. Use year and director information to reduce false positives.
4. Classify shorts and non-feature cases separately.
5. Keep review files for ambiguous or low-confidence rows.

Important scripts in this part of the workflow:

- `src/imdb/generate_initial_matches.py`
- `src/imdb/resolve_single_collection.py`
- `src/imdb/classify_shorts.py`
- `src/wrangling/find_unmatched.py`
- `src/wrangling/manual_match_review.py`
- `src/wrangling/build_final_dataframe.py`

## Web Scraper

The repository includes scraper-related support for Criterion Eclipse collection handling.

Main files:

- `src/scraping/scrape_eclipse_series.py`
- `src/scraping/build_eclipse_imdb_hints.py`

Current related local files already present in the repo:

- `data/criterion/eclipse_series_titles.csv`
- `data/criterion/eclipse.html`
- `data/output/criterion_eclipse_failures.csv`
- `data/output/criterion_eclipse_url_cache.csv`

## How to Run the Code

Run scripts from the repository root.

Typical early-stage commands:

```bash
python -m src.criterion.build_new_criterion_csv
python -m src.criterion.export_criterion_browse_fields
python -m src.imdb.generate_initial_matches
python -m src.wrangling.find_unmatched
python -m src.wrangling.manual_match_review
python -m src.wrangling.resolve_collections
python -m src.wrangling.build_final_dataframe
python -m src.wrangling.validate_final_dataset
```

Other scripts in `src/wrangling/` support collection expansion, manual resolution application, special-case exports, and review summarization.

## Current Outputs

The repository currently contains a number of local outputs in `data/output/`, including:

- `initial_matches.csv`
- `match_candidates_review.csv`
- `unmatched_initial.csv`
- `unmatched_tracking.csv`
- `manual_resolution_log.csv`
- `resolved_collections.csv`
- `collection_constituent_films.csv`
- `excluded_shorts.csv`
- `criterion_dispositions.csv`
- `final_clean_films.csv`
- `validation_report.csv`

It also still contains some clustering- and network-oriented artifacts such as:

- `data/output/core_clustered.json`
- `data/output/movie_network_leiden_layout.json`
- `data/output/cluster_details.json`
- `data/criterion/actor_network.json`
- `data/criterion/movienetwork_unweighted.json`

Those files are present in the current working tree, but they are downstream artifacts rather than the core wrangling pipeline itself.

## Current Limitations

- The workflow still depends on large local IMDb data files.
- The repository is still script-driven rather than organized as a single reproducible CLI pipeline.
- Manual review is still part of the intended process for ambiguous titles, collections, and edge cases.
- Some supporting local files expected by certain scripts are researcher-maintained working files rather than polished package inputs.
- The repository currently contains both wrangling code and some downstream analysis artifacts that should eventually be separated more cleanly.
- Older notebooks and docs are still present as working references.
