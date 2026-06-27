-- =====================================================================================
-- Criterion <-> IMDb enrichment pipeline (pure DuckDB SQL)
-- =====================================================================================
--
-- Run from the repository root so the relative "data/..." paths resolve, e.g.:
--   duckdb -f scripts/criterion_imdb_duckdb_enrichment.sql
-- or open this file in VS Code with the DuckDB extension and run it top to bottom.
--
-- WHAT THIS SCRIPT PRODUCES (in data/output/):
--   1. criterion_basic_info.csv      - Criterion films + matched IMDb id/type/year/runtime/crew
--   2. actor_filmographies.csv       - (actor_nconst, title_tconst) cast credits for matched films
--   3. actor_names.csv               - (actor_nconst, actor_name) for those same actors
--   4. title_name_translations.csv   - (title_tconst, english_title) for those same matched films
--
-- Outputs 2-4 are scoped to the IMDb titles that this script actually matches to a
-- Criterion film (not the full ~12M-title IMDb dataset), since the point of this script
-- is enriching the Criterion catalog. If you want unscoped, IMDb-wide exports instead,
-- drop the "WHERE tconst IN (SELECT tconst FROM matched_tconst)" filters noted below.
--
-- -------------------------------------------------------------------------------------
-- MATCHING ALGORITHM, IN PLAIN ENGLISH
-- -------------------------------------------------------------------------------------
-- Stage 1 - Exact ID match:
--   If a Criterion row already carries an IMDb id (see the "criterion_tconst" placeholder
--   in Section 2 - it's NULL today because criterion_films.csv has no id column, but the
--   path is wired up for when one exists), that id is used directly with 100% confidence
--   and fuzzy matching is skipped entirely for that row.
--
-- Stage 2 - Canonicalization:
--   Every title and director name (both Criterion's and IMDb's) is canonicalized the same
--   way: Unicode accents are stripped, the string is lowercased, anything that isn't a
--   letter or digit is replaced with a space, and repeated whitespace is collapsed. This
--   means "Agnès Varda" and "agnes   varda!" canonicalize to the identical "agnes varda".
--
-- Stage 3 - Blocking (avoiding a full cross join), via TWO independent paths:
--   Comparing all ~3,200 Criterion rows against all ~6M candidate IMDb titles directly
--   would mean ~19 billion comparisons, so candidates are pre-filtered ("blocked") down
--   to only the rows that could plausibly match. Title text is canonicalized the same way
--   IMDb titles are, but a Criterion title can diverge from IMDb's listed title more than
--   canonicalization alone fixes (e.g. "21 Days" vs. IMDb's "21 Days Together") while its
--   director and year still agree exactly - blocking on title text alone would only find
--   that match by luck (if some alternate title happens to align). So there are two
--   parallel blocking paths, unioned together before scoring:
--     Path A (director+year, cheap and tried first): the Criterion director string is
--       split on commas/"and"/"&"/"/"/";" into individual names (so "Kenji Kamiyama and
--       Toshiyuki Kono" is tried as two separate directors, not one literal string), each
--       canonicalized piece is matched against IMDb's per-title canonicalized director
--       names by exact equality, and the year must be within +/-2 (or unknown on either
--       side). This is a highly selective join - IMDb has ~800K distinct canonical
--       director names averaging ~11 credits each, versus only ~36 first-letter buckets
--       for titles - so it is both fast and precise, and it covers ~94% of Criterion rows
--       that list a director at all.
--     Path B (title-letter+year, fallback only): for the rows Path A found nothing for
--       (no director listed, or the director's IMDb spelling doesn't canonicalize to an
--       identical string), the original approach applies: same first letter of the
--       canonicalized title, plus the same +/-2 year window, plus IMDb titleType
--       restricted to movie/short/tvMovie/tvSpecial/video. Running this only for the
--       rows Path A missed (rather than for all ~3,200 rows) keeps it cheap.
--   The two candidate pools are unioned per (Criterion row, IMDb title) pair, remembering
--   whether Path A found the pair.
--
-- Stage 4 - Title similarity:
--   For every surviving (Criterion row, IMDb title) pair regardless of which path found
--   it, Jaro-Winkler similarity is computed between the canonicalized Criterion title and
--   EVERY canonical English/US form IMDb offers for that title (primaryTitle,
--   originalTitle, and any title.akas.tsv row tagged region='US' or language='en', except
--   akas tagged attributes='segment title' - see the note in Section 2 on title_akas_en
--   for why those are excluded rather than treated as ordinary alternate titles). The
--   pair keeps the single best (highest) similarity across all of those variants.
--
--   Pairs found only via Path B (title-letter blocking) that don't clear a 0.75 title
--   similarity floor are dropped here, before the next (more expensive) step, since a
--   title-blocked candidate that isn't even close on title text is not worth scoring on
--   director agreement. Pairs found via Path A are exempt from this floor - they were
--   selected because of strong director+year evidence in the first place, which is the
--   whole point of having Path A, so a weak title score alone must not disqualify them.
--
-- Stage 5 - Director similarity:
--   title.crew.tsv stores comma-separated director nconst lists per title; those are
--   exploded into one row per (title, director) and joined to name.basics.tsv to get a
--   canonicalized director name (this is the same per-title director pool Path A blocks
--   against in Stage 3). For each surviving candidate, Jaro-Winkler similarity is
--   computed between the Criterion row's canonicalized director string and every IMDb
--   director on that title, keeping the best (highest) match. If IMDb has no director
--   credited for that title at all, director similarity is recorded as NULL (distinct
--   from a real mismatch, which would score near 0).
--
-- Stage 6 - Weighted scoring:
--   weighted_score = 0.50 * title_similarity
--                  + 0.35 * COALESCE(director_similarity, 0)
--                  + 0.15 * year_similarity
--   Title carries the most weight, director next, year least - title and director are
--   still text-similarity scores (0..1), while year_similarity is a step function of how
--   close the two years are: 1.0 if they match exactly, 0.5 if within 1 year, 0.25 if
--   within 2 years, 0 if either year is unknown or further apart than that (an unknown
--   year is an absence of evidence, not evidence of agreement, so it earns no credit -
--   the same "missing evidence scores zero" rule director_similarity already follows).
--   Missing director evidence (NULL) is likewise treated as zero rather than
--   excluded/renormalized - otherwise an obscure, miscredited IMDb title with no director
--   listed could tie a perfect title+director match and the choice between them would be
--   arbitrary.
--
-- Stage 7 - Best match per film:
--   Candidates are ranked per Criterion row by weighted_score, then by raw title
--   similarity, then by tconst (for determinism), and only the top-ranked candidate is
--   kept. confidence_score is weighted_score scaled to 0-100. Rows with no surviving
--   candidate (failed blocking or below the similarity floor) are kept with a NULL
--   IMDb id and match_method = 'unmatched' rather than being dropped from the output.
-- =====================================================================================


-- -------------------------------------------------------------------------------------
-- SECTION 1: Configuration
-- -------------------------------------------------------------------------------------
-- Uncomment and tune if you hit memory pressure on a smaller machine; DuckDB otherwise
-- auto-sizes to a safe fraction of available RAM.
-- SET memory_limit = '8GB';


-- -------------------------------------------------------------------------------------
-- SECTION 2: Load raw source files
-- -------------------------------------------------------------------------------------
-- IMDb .tsv files use tab delimiters, have no quoting (some fields, like
-- title.principals.tsv's "characters" column, contain literal double quotes as data, so
-- quote = '' tells DuckDB not to treat them as CSV quote characters), and use the literal
-- string "\N" for SQL NULL.

CREATE OR REPLACE TABLE criterion_raw AS
SELECT
    row_number() OVER () AS criterion_row_id,
    title,
    director,
    country,
    year,
    -- Placeholder for an existing IMDb id column. criterion_films.csv currently has none,
    -- so every row falls through to fuzzy matching (Section 7). If your CSV gains an id
    -- column (e.g. "tconst" or "imdb_id"), replace the line below with
    -- CAST(<your_column> AS VARCHAR) AS criterion_tconst
    -- to enable the exact-match short-circuit described in Section 10.
    CAST(NULL AS VARCHAR) AS criterion_tconst
FROM read_csv('data/criterion/criterion_films.csv', header = true);

CREATE OR REPLACE TABLE title_basics AS
SELECT
    tconst,
    titleType,
    primaryTitle,
    originalTitle,
    TRY_CAST(startYear AS INTEGER) AS startYear,
    TRY_CAST(runtimeMinutes AS INTEGER) AS runtimeMinutes,
    genres
FROM read_csv(
    'data/imdb/title.basics.tsv',
    delim = '\t', header = true, quote = '', nullstr = '\N', all_varchar = true
);

CREATE OR REPLACE TABLE title_crew AS
SELECT tconst, directors, writers
FROM read_csv(
    'data/imdb/title.crew.tsv',
    delim = '\t', header = true, quote = '', nullstr = '\N', all_varchar = true
);

CREATE OR REPLACE TABLE name_basics AS
SELECT nconst, primaryName
FROM read_csv(
    'data/imdb/name.basics.tsv',
    delim = '\t', header = true, quote = '', nullstr = '\N', all_varchar = true
);

CREATE OR REPLACE TABLE title_principals AS
SELECT tconst, nconst, category
FROM read_csv(
    'data/imdb/title.principals.tsv',
    delim = '\t', header = true, quote = '', nullstr = '\N', all_varchar = true
);

-- Pre-filter title.akas.tsv down to English/US rows up front: at 54M raw rows it's by far
-- the largest file, and only English/US alternate titles are ever used downstream (as
-- title-matching candidates in Section 4, and as translations in Section 14).
--
-- attributes = 'segment title' rows are dropped here too. IMDb tags a part/segment's own
-- name as an aka on its PARENT anthology/omnibus record (e.g. tt0063715 "Spirits of the
-- Dead" carries the aka "Toby Dammit", tagged 'segment title', because Fellini's segment
-- of that anthology is called Toby Dammit). Left in, that aka makes the anthology's own
-- record score a perfect title match against a Criterion row for the segment alone,
-- tying it with the segment's own standalone IMDb record and making the two
-- indistinguishable. A segment's name is not a legitimate alternate title for the whole
-- work, so it's excluded rather than treated as one.
CREATE OR REPLACE TABLE title_akas_en AS
SELECT DISTINCT titleId AS tconst, title, region, language
FROM read_csv(
    'data/imdb/title.akas.tsv',
    delim = '\t', header = true, quote = '', nullstr = '\N', all_varchar = true
)
WHERE (region = 'US' OR language = 'en')
  AND (attributes IS NULL OR attributes != 'segment title');


-- -------------------------------------------------------------------------------------
-- SECTION 3: Canonicalization
-- -------------------------------------------------------------------------------------
-- Lowercase, strip accents, replace any run of non-alphanumeric characters with a single
-- space, then trim. Applied identically to Criterion and IMDb text so both sides land on
-- the same normal form.
CREATE OR REPLACE MACRO canonicalize_text(s) AS (
    trim(
        regexp_replace(
            regexp_replace(lower(strip_accents(coalesce(s, ''))), '[^a-z0-9]+', ' ', 'g'),
            '\s+', ' ', 'g'
        )
    )
);

CREATE OR REPLACE TABLE criterion_canon AS
SELECT
    criterion_row_id,
    title,
    director,
    country,
    year,
    criterion_tconst,
    canonicalize_text(title) AS canon_title,
    canonicalize_text(director) AS canon_director,
    substr(canonicalize_text(title), 1, 1) AS title_block_letter
FROM criterion_raw;

-- Criterion's "director" field sometimes lists multiple people in one string (e.g.
-- "Kenji Kamiyama and Toshiyuki Kono"). canon_director above keeps that as one literal
-- blob, which is fine for director_similarity scoring (Stage 5) but would never exactly
-- equal a single IMDb director's canonical name, which is what Path A blocking (Stage 3)
-- needs. Splitting into individual canonicalized pieces here lets Path A try each name
-- separately.
CREATE OR REPLACE TABLE criterion_directors_split AS
SELECT DISTINCT
    cc.criterion_row_id,
    canonicalize_text(d) AS canon_director_piece
FROM criterion_canon cc
CROSS JOIN UNNEST(
    regexp_split_to_array(cc.director, '\s*,\s*|\s+and\s+|\s*&\s*|\s*/\s*|\s*;\s*', 'i')
) AS t(d)
WHERE cc.director IS NOT NULL AND trim(canonicalize_text(d)) != '';


-- -------------------------------------------------------------------------------------
-- SECTION 4: IMDb title-variant candidate pool (blocking input)
-- -------------------------------------------------------------------------------------
-- Restrict to title types that could plausibly appear in Criterion's catalog.
CREATE OR REPLACE TABLE title_basics_filtered AS
SELECT tconst, titleType, primaryTitle, originalTitle, startYear, runtimeMinutes
FROM title_basics
WHERE titleType IN ('movie', 'short', 'tvMovie', 'tvSpecial', 'video');

-- One row per (tconst, distinct canonical title text), pooling primaryTitle,
-- originalTitle, and English/US akas together. UNION (not UNION ALL) drops exact
-- duplicate variants (e.g. when primaryTitle == originalTitle, or an aka matches
-- primaryTitle verbatim), which otherwise inflates Section 6's similarity computation
-- without changing its result.
CREATE OR REPLACE TABLE imdb_title_variants AS
SELECT DISTINCT
    tb.tconst, tb.titleType, tb.startYear, tb.runtimeMinutes,
    canonicalize_text(v.text_variant) AS canon_variant,
    substr(canonicalize_text(v.text_variant), 1, 1) AS variant_block_letter
FROM title_basics_filtered tb
CROSS JOIN LATERAL (VALUES (tb.primaryTitle), (tb.originalTitle)) AS v(text_variant)
WHERE v.text_variant IS NOT NULL

UNION

SELECT DISTINCT
    tb.tconst, tb.titleType, tb.startYear, tb.runtimeMinutes,
    canonicalize_text(a.title) AS canon_variant,
    substr(canonicalize_text(a.title), 1, 1) AS variant_block_letter
FROM title_basics_filtered tb
JOIN title_akas_en a ON a.tconst = tb.tconst
WHERE a.title IS NOT NULL;


-- -------------------------------------------------------------------------------------
-- SECTION 5: IMDb director-name pool
-- -------------------------------------------------------------------------------------
-- Explode title.crew.tsv's comma-separated directors list into one row per
-- (title, director), with the director's canonicalized primary name attached.
CREATE OR REPLACE TABLE title_directors_unnest AS
SELECT
    tc.tconst,
    nb.nconst AS director_nconst,
    canonicalize_text(nb.primaryName) AS canon_director_name
FROM title_crew tc
CROSS JOIN UNNEST(string_split(tc.directors, ',')) AS d(director_nconst_raw)
JOIN name_basics nb ON nb.nconst = trim(d.director_nconst_raw)
WHERE tc.directors IS NOT NULL;


-- -------------------------------------------------------------------------------------
-- SECTION 6: Two-path blocked candidate generation
-- -------------------------------------------------------------------------------------
-- Only rows without an exact IMDb id need fuzzy candidates (the "WHERE cc.criterion_tconst
-- IS NULL" below).

-- Path A: director+year blocking. Exact canonical-name equality against IMDb's per-title
-- director pool, tried against every individually-split Criterion director name.
--
-- year_confirmed records whether the year match was a *real* agreement (both sides
-- known and within +/-2) as opposed to a pass-through caused by the NULL-year wildcard
-- in the WHERE clause below. That distinction matters in Section 7: an exact director
-- match plus an unknown IMDb year is not enough corroboration to excuse a bad title (it's
-- exactly how generic, undated "Untitled <Year> <Director> Project" placeholder records
-- on IMDb would otherwise win on director-name authority alone), but an exact director
-- match plus a genuinely confirmed year is.
CREATE OR REPLACE TABLE director_year_block AS
SELECT DISTINCT
    cds.criterion_row_id,
    tbf.tconst,
    (cc.year IS NOT NULL AND tbf.startYear IS NOT NULL AND abs(cc.year - tbf.startYear) <= 2) AS year_confirmed
FROM criterion_directors_split cds
JOIN criterion_canon cc ON cc.criterion_row_id = cds.criterion_row_id
JOIN title_directors_unnest tdu ON tdu.canon_director_name = cds.canon_director_piece
JOIN title_basics_filtered tbf ON tbf.tconst = tdu.tconst
WHERE cc.criterion_tconst IS NULL
  AND (cc.year IS NULL OR tbf.startYear IS NULL OR abs(cc.year - tbf.startYear) <= 2);

-- Rows that still need the (more expensive) title-letter fallback: anything Path A found
-- nothing for, PLUS anything Path A only found year-unconfirmed hits for. The latter
-- matters because an unconfirmed-year candidate is not guaranteed to survive Section 7's
-- floor - without this, a row could have its only Path A candidate later discarded there
-- and end up with no candidate at all, having never gotten a chance at Path B.
CREATE OR REPLACE TABLE rows_needing_title_block AS
SELECT cc.* FROM criterion_canon cc
WHERE cc.criterion_tconst IS NULL
  AND cc.criterion_row_id NOT IN (
      SELECT criterion_row_id FROM director_year_block WHERE year_confirmed
  );

-- Path B: title-letter+year blocking, restricted to rows_needing_title_block so the
-- expensive join only runs for the ~6% of rows Path A didn't cover.
CREATE OR REPLACE TABLE title_year_block AS
SELECT DISTINCT cc.criterion_row_id, iv.tconst
FROM rows_needing_title_block cc
JOIN imdb_title_variants iv
  ON iv.variant_block_letter = cc.title_block_letter
 AND (cc.year IS NULL OR iv.startYear IS NULL OR abs(cc.year - iv.startYear) <= 2);

-- Union both paths into one candidate-pair pool. via_director_year_confirmed is true only
-- if Path A found this pair AND that match had a genuinely confirmed (not wildcarded) year.
CREATE OR REPLACE TABLE candidate_pairs AS
SELECT
    criterion_row_id, tconst,
    bool_or(via_director_block) AS via_director_block,
    bool_or(via_director_block AND year_confirmed) AS via_director_year_confirmed
FROM (
    SELECT criterion_row_id, tconst, true AS via_director_block, year_confirmed FROM director_year_block
    UNION ALL
    SELECT criterion_row_id, tconst, false AS via_director_block, false AS year_confirmed FROM title_year_block
)
GROUP BY criterion_row_id, tconst;


-- -------------------------------------------------------------------------------------
-- SECTION 7: Title similarity + similarity floor
-- -------------------------------------------------------------------------------------
-- Title similarity is computed once per (Criterion row, IMDb title) pair regardless of
-- which blocking path found it, taking the best score across all of that title's
-- canonical variants (primaryTitle/originalTitle/English-or-US akas).
CREATE OR REPLACE TABLE match_candidates_best AS
SELECT
    cp.criterion_row_id, cp.tconst, cp.via_director_year_confirmed,
    any_value(iv.titleType) AS titleType,
    any_value(iv.startYear) AS startYear,
    max(jaro_winkler_similarity(cc.canon_title, iv.canon_variant)) AS title_sim
FROM candidate_pairs cp
JOIN criterion_canon cc ON cc.criterion_row_id = cp.criterion_row_id
JOIN imdb_title_variants iv ON iv.tconst = cp.tconst
GROUP BY cp.criterion_row_id, cp.tconst, cp.via_director_year_confirmed;

-- Drop candidates that aren't even close on title text before paying for the director
-- join below - unless director and year both already agree (via_director_year_confirmed),
-- in which case a weak title score is exactly the scenario Path A exists to rescue (e.g.
-- Criterion's "21 Days" vs. IMDb's "21 Days Together"), not a reason to drop the
-- candidate. A director-name match alone (year unknown or unconfirmed) is not treated as
-- enough corroboration to bypass the floor - see the year_confirmed note in Section 6.
CREATE OR REPLACE TABLE match_candidates_titlefiltered AS
SELECT * FROM match_candidates_best WHERE title_sim >= 0.75 OR via_director_year_confirmed;


-- -------------------------------------------------------------------------------------
-- SECTION 8: Director similarity for surviving candidates
-- -------------------------------------------------------------------------------------
-- LEFT JOIN so a title with no IMDb-credited director still survives, with
-- director_sim = NULL (handled explicitly in Section 9, not silently coerced to 0 here,
-- so "no director on file" stays distinguishable from "director text didn't match").
--
-- NOTE: an earlier version of this section discounted director_sim by what fraction of
-- a candidate's credited directors matched (e.g. 1/3 credit for matching only one
-- director on a 3-director title), aimed at anthology/omnibus containers stealing
-- matches from their own segments' standalone records (see Section 2's title_akas_en
-- note for the "Toby Dammit" / "Spirits of the Dead" case that motivated it). Tested
-- against the real data, that discount caused more regressions than fixes: it can't
-- distinguish "this director is 1 of 3 unrelated anthology segment directors" from "this
-- director has an ordinary co-director or effects-director credit on one coherent film"
-- - both look identical (N directors credited, Criterion lists fewer). E.g. it broke
-- Ishirô Honda's co-directed "Atragon" and "All Monsters Attack" (each correct, exact
-- title matches) in favor of his solo-directed, wrong-titled "Matango" and "Latitude
-- Zero" from the same era, since solo credits kept full ratio while the co-directed
-- correct matches did not. The Toby Dammit / Antoine and Colette cases that motivated
-- the discount are already fixed by the segment-title aka exclusion alone, so the
-- discount was reverted rather than kept for a narrower, unproven benefit.
CREATE OR REPLACE TABLE match_candidates_scored AS
SELECT
    mc.criterion_row_id, mc.tconst, mc.titleType, mc.startYear, cc.year AS criterion_year, mc.title_sim,
    max(jaro_winkler_similarity(cc.canon_director, tdu.canon_director_name)) AS director_sim
FROM match_candidates_titlefiltered mc
JOIN criterion_canon cc ON cc.criterion_row_id = mc.criterion_row_id
LEFT JOIN title_directors_unnest tdu ON tdu.tconst = mc.tconst
GROUP BY mc.criterion_row_id, mc.tconst, mc.titleType, mc.startYear, cc.year, mc.title_sim;


-- -------------------------------------------------------------------------------------
-- SECTION 9: Weighted scoring + best match per Criterion film
-- -------------------------------------------------------------------------------------
-- Title counts for the most, director next, year least. Missing director evidence (NULL)
-- is scored as 0 - see the Stage 6 note above for why. Year similarly scores 0 when
-- either side is unknown: an unknown year is not evidence of agreement, so it should not
-- earn partial credit just for failing to contradict.
CREATE OR REPLACE TABLE match_candidates_weighted AS
SELECT
    *,
    CASE
        WHEN criterion_year IS NULL OR startYear IS NULL THEN 0
        WHEN abs(criterion_year - startYear) = 0 THEN 1.0
        WHEN abs(criterion_year - startYear) = 1 THEN 0.5
        WHEN abs(criterion_year - startYear) = 2 THEN 0.25
        ELSE 0
    END AS year_sim,
    0.50 * title_sim
        + 0.35 * coalesce(director_sim, 0)
        + 0.15 * CASE
            WHEN criterion_year IS NULL OR startYear IS NULL THEN 0
            WHEN abs(criterion_year - startYear) = 0 THEN 1.0
            WHEN abs(criterion_year - startYear) = 1 THEN 0.5
            WHEN abs(criterion_year - startYear) = 2 THEN 0.25
            ELSE 0
        END AS weighted_score
FROM match_candidates_scored;

CREATE OR REPLACE TABLE match_best AS
SELECT * EXCLUDE (rnk)
FROM (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY criterion_row_id
            ORDER BY weighted_score DESC, title_sim DESC, tconst
        ) AS rnk
    FROM match_candidates_weighted
)
WHERE rnk = 1;


-- -------------------------------------------------------------------------------------
-- SECTION 10: Resolve final tconst per Criterion film (exact id, else fuzzy, else none)
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE criterion_resolved AS
SELECT
    cc.criterion_row_id,
    cc.title,
    cc.director,
    cc.country,
    cc.year,
    COALESCE(cc.criterion_tconst, mb.tconst) AS tconst,
    CASE
        WHEN cc.criterion_tconst IS NOT NULL THEN 'exact_tconst'
        WHEN mb.tconst IS NOT NULL THEN 'fuzzy_canonical'
        ELSE 'unmatched'
    END AS match_method,
    CASE
        WHEN cc.criterion_tconst IS NOT NULL THEN 100.0
        WHEN mb.tconst IS NOT NULL THEN round(mb.weighted_score * 100, 1)
        ELSE NULL
    END AS confidence_score,
    round(mb.title_sim, 4) AS title_similarity,
    round(mb.director_sim, 4) AS director_similarity,
    round(mb.year_sim, 4) AS year_similarity
FROM criterion_canon cc
LEFT JOIN match_best mb ON mb.criterion_row_id = cc.criterion_row_id;


-- -------------------------------------------------------------------------------------
-- SECTION 11: Output 1 - criterion_basic_info.csv
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE criterion_basic_info AS
SELECT
    cr.title,
    cr.director AS criterion_director,
    cr.country AS criterion_country,
    cr.year AS criterion_year,
    cr.tconst AS imdb_tconst,
    tb.titleType AS imdb_title_type,
    tb.startYear AS imdb_year,
    tb.runtimeMinutes AS imdb_runtime_minutes,
    tc.directors AS imdb_director_nconst,
    tc.writers AS imdb_writer_nconst,
    cr.match_method,
    cr.confidence_score,
    cr.title_similarity,
    cr.director_similarity,
    cr.year_similarity
FROM criterion_resolved cr
LEFT JOIN title_basics tb ON tb.tconst = cr.tconst
LEFT JOIN title_crew tc ON tc.tconst = cr.tconst
ORDER BY cr.criterion_row_id;

COPY criterion_basic_info TO 'data/output/criterion_basic_info.csv' (HEADER, DELIMITER ',');


-- -------------------------------------------------------------------------------------
-- SECTION 12: Scope set for outputs 2-4 - the IMDb titles actually matched above
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE matched_tconst AS
SELECT DISTINCT tconst FROM criterion_resolved WHERE tconst IS NOT NULL;


-- -------------------------------------------------------------------------------------
-- SECTION 13: Output 2 - actor_filmographies.csv
-- -------------------------------------------------------------------------------------
-- "actor/actress/cast-related" is read here as category IN ('actor', 'actress', 'self')
-- - 'self' covers people (often documentary subjects) credited as appearing as
-- themselves, which is common in Criterion's catalog. It excludes archive_footage /
-- archive_sound, since those credit footage reused from another production rather than
-- an on-screen appearance in this title. Adjust the category list if you want a
-- narrower (or broader) definition.
CREATE OR REPLACE TABLE actor_filmographies AS
SELECT DISTINCT nconst AS actor_nconst, tconst AS title_tconst
FROM title_principals
WHERE category IN ('actor', 'actress', 'self')
  AND tconst IN (SELECT tconst FROM matched_tconst);

COPY actor_filmographies TO 'data/output/actor_filmographies.csv' (HEADER, DELIMITER ',');


-- -------------------------------------------------------------------------------------
-- SECTION 14: Output 3 - actor_names.csv
-- -------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE actor_names AS
SELECT DISTINCT nb.nconst AS actor_nconst, nb.primaryName AS actor_name
FROM name_basics nb
WHERE nb.nconst IN (SELECT DISTINCT actor_nconst FROM actor_filmographies);

COPY actor_names TO 'data/output/actor_names.csv' (HEADER, DELIMITER ',');


-- -------------------------------------------------------------------------------------
-- SECTION 15: Output 4 - title_name_translations.csv
-- -------------------------------------------------------------------------------------
-- Prefer a title.akas.tsv row tagged region='US', then one tagged language='en', falling
-- back to title.basics.tsv's primaryTitle when no English/US aka exists at all.
CREATE OR REPLACE TABLE best_english_aka AS
SELECT tconst, title AS english_title
FROM (
    SELECT
        tconst, title,
        row_number() OVER (
            PARTITION BY tconst
            ORDER BY (region = 'US') DESC, (language = 'en') DESC
        ) AS rnk
    FROM title_akas_en
    WHERE tconst IN (SELECT tconst FROM matched_tconst)
)
WHERE rnk = 1;

CREATE OR REPLACE TABLE title_name_translations AS
SELECT
    mt.tconst AS title_tconst,
    COALESCE(bea.english_title, tb.primaryTitle) AS english_title
FROM matched_tconst mt
LEFT JOIN best_english_aka bea ON bea.tconst = mt.tconst
LEFT JOIN title_basics tb ON tb.tconst = mt.tconst;

COPY title_name_translations TO 'data/output/title_name_translations.csv' (HEADER, DELIMITER ',');
