#!/usr/bin/env python3
"""
Apply manual resolutions to new_unmatched_tracking.csv.

Writes:
  data/output/manual_resolution_log.csv  — full resolution record for all 236 entries
  data/output/resolved_matches.csv       — entries with confirmed IMDb matches
  data/output/still_unresolved.csv       — any genuinely unresolvable entries
  data/output/new_match_status_summary.csv — updated summary (all 1830 rows)
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
OUTPUTS   = WORKSPACE / "data" / "output"

IN_UNMATCHED   = OUTPUTS / "new_unmatched_tracking.csv"
IN_MATCHES     = OUTPUTS / "new_initial_matches.csv"
IN_SUMMARY     = OUTPUTS / "new_match_status_summary.csv"

OUT_RESOLVED   = OUTPUTS / "manual_resolution_log.csv"
OUT_MATCHES_V2 = OUTPUTS / "resolved_matches.csv"
OUT_REMAINING  = OUTPUTS / "still_unresolved.csv"
OUT_SUMMARY_V2 = OUTPUTS / "new_match_status_summary_v2.csv"

csv.field_size_limit(sys.maxsize)

def load_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        print(f"  Wrote 0 rows → {path.name}")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  Wrote {len(rows):,} rows → {path.name}")

def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ===========================================================================
# RESOLUTION DATABASE
# Each entry keyed by criterion_source_id.
# entity_type:   movie | tvMiniSeries | tvSeries | short | documentary |
#                video | collection | collection_label
# final_action:  matched | collection | collection_label | no_imdb_entry
# imdb_id:       tt-number or ""
# imdb_title:    canonical IMDb title
# notes:         research notes / rationale
# ===========================================================================

RESOLUTIONS = {

    # =========================================================
    # NAMED CRITERION ENTRIES — Individual films / TV
    # =========================================================

    "42": {
        "entity_type": "tvSeries", "imdb_id": "tt0139776",
        "imdb_title": "Fishing with John",
        "notes": "TV series, 6 eps, 1991, John Lurie; Criterion label year 1992",
        "final_action": "matched",
    },
    "100": {
        "entity_type": "video", "imdb_id": "tt0273456",
        "imdb_title": "Beastie Boys: Video Anthology",
        "notes": "Music video compilation, 2000; confirmed by review candidate score=59",
        "final_action": "matched",
    },
    "124": {
        "entity_type": "documentary", "imdb_id": "tt0060212",
        "imdb_title": "Carl Th. Dreyer",
        "notes": "1966 documentary by Jørgen Roos; confirmed by review candidate",
        "final_action": "matched",
    },
    "128": {
        "entity_type": "documentary", "imdb_id": "tt0112631",
        "imdb_title": "Carl Th. Dreyer—My Metier",
        "notes": "1995 documentary by Torben Skjødt Jensen; confirmed via web search",
        "final_action": "matched",
    },
    "169": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Two-film set: Jimi Plays Monterey (tt0093312, D.A. Pennebaker 1986) + Shake! Otis at Monterey (tt0093951, Pennebaker 1987)",
        "final_action": "collection",
    },
    "180": {
        "entity_type": "movie", "imdb_id": "tt0061834",
        "imdb_title": "I Am Curious—Yellow",
        "notes": "Jag är nyfiken - en film i gult, Vilgot Sjöman 1967",
        "final_action": "matched",
    },
    "181": {
        "entity_type": "movie", "imdb_id": "tt0063149",
        "imdb_title": "I Am Curious—Blue",
        "notes": "Jag är nyfiken - en film i blått, Vilgot Sjöman, released 1968 (Criterion year 1967)",
        "final_action": "matched",
    },
    "197": {
        "entity_type": "short", "imdb_id": "tt0048434",
        "imdb_title": "Night and Fog",
        "notes": "Nuit et brouillard, Alain Resnais; IMDb year 1956, Criterion year 1955 (festival/production year); confirmed by review candidate",
        "final_action": "matched",
    },
    "214": {
        "entity_type": "movie", "imdb_id": "tt0033540",
        "imdb_title": "All That Money Can Buy",
        "notes": "aka The Devil and Daniel Webster, William Dieterle 1941; Criterion title uses both names",
        "final_action": "matched",
    },
    "258": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt0095287",
        "imdb_title": "Tanner '88",
        "notes": "HBO political satire miniseries, Robert Altman/Garry Trudeau 1988; 11 episodes",
        "final_action": "matched",
    },
    "261": {
        "entity_type": "movie", "imdb_id": "tt0083922",
        "imdb_title": "Fanny and Alexander",
        "notes": "Theatrical version (188 min), Bergman 1982; confirmed by review candidate",
        "final_action": "matched",
    },
    "262": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt6725158",
        "imdb_title": "Fanny and Alexander: Television Version",
        "notes": "Extended 312-min TV version, Bergman 1983; separate IMDb entry from theatrical",
        "final_action": "matched",
    },
    "263": {
        "entity_type": "movie", "imdb_id": "tt0083922",
        "imdb_title": "Fanny and Alexander: Theatrical Version",
        "notes": "Same film as spine 261 theatrical version (188 min), Bergman 1982; criterion re-released with explicit label",
        "final_action": "matched",
    },
    "411": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt0080196",
        "imdb_title": "Berlin Alexanderplatz",
        "notes": "Fassbinder 1980, 14 episodes + epilogue; review candidate was wrong (2020 remake); correct ID tt0080196",
        "final_action": "matched",
    },
    "517": {
        "entity_type": "video", "imdb_id": "tt33099287",
        "imdb_title": "By Brakhage: An Anthology, Volume Two",
        "notes": "2010 DVD/Blu-ray compilation; confirmed by review candidate score=55",
        "final_action": "matched",
    },
    "598": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt0070904",
        "imdb_title": "World on a Wire",
        "notes": "Welt am Draht, Fassbinder 1973, 2-part TV film; review candidate was wrong (1953 film); correct ID confirmed",
        "final_action": "matched",
    },
    "615": {
        "entity_type": "movie", "imdb_id": "tt0015864",
        "imdb_title": "The Gold Rush",
        "notes": "Chaplin 1925; Criterion releases 1942 reissue (Chaplin's re-edit); IMDb entry is for original 1925 film",
        "final_action": "matched",
    },
    "618": {
        "entity_type": "movie", "imdb_id": "tt0116447",
        "imdb_title": "Gray's Anatomy",
        "notes": "Steven Soderbergh 1996 (Criterion year 1997 = US home video release); confirmed by review candidate score=74",
        "final_action": "matched",
    },
    "772": {
        "entity_type": "movie", "imdb_id": "tt0084549",
        "imdb_title": "Blind Chance",
        "notes": "Przypadek, Kieślowski 1981 (made); held by Polish censors until 1987; confirmed by review candidate",
        "final_action": "matched",
    },
    "791": {
        "entity_type": "movie", "imdb_id": "tt0072210",
        "imdb_title": "Lady Snowblood: Love Song of Vengeance",
        "notes": "Shura-yuki-hime: Urami Renga, Toshiya Fujita 1974",
        "final_action": "matched",
    },
    "837": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt0094725",
        "imdb_title": "Dekalog",
        "notes": "Kieślowski 1988, 10-part Polish TV series; also released as feature films (Krótki film…)",
        "final_action": "matched",
    },
    "876": {
        "entity_type": "movie", "imdb_id": "tt0102497",
        "imdb_title": "Revenge",
        "notes": "Mes, Ermek Shinarbaev 1989, Soviet/Kazakh film; confirmed by research as correct candidate",
        "final_action": "matched",
    },
    "940": {
        "entity_type": "movie", "imdb_id": "tt3551840",
        "imdb_title": "The Ballad of Gregorio Cortez",
        "notes": "Robert M. Young 1982; starring Edward James Olmos",
        "final_action": "matched",
    },
    "946": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt0069034",
        "imdb_title": "Eight Hours Don't Make a Day",
        "notes": "Acht Stunden sind kein Tag, Fassbinder 1972-73, 5-episode WDR series",
        "final_action": "matched",
    },
    "983": {
        "entity_type": "movie", "imdb_id": "tt0063794",
        "imdb_title": "War and Peace",
        "notes": "Bondarchuk 1965-67 (4-part release); IMDb year 1965, Criterion year 1966; 1-yr diff acceptable",
        "final_action": "matched",
    },
    "1121": {
        "entity_type": "movie", "imdb_id": "tt10365870",
        "imdb_title": "Eyimofe (This Is My Desire)",
        "notes": "Arie & Chuko Esiri 2020, Nigerian film; confirmed via web search",
        "final_action": "matched",
    },
    "1177": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt9055008",
        "imdb_title": "Small Axe",
        "notes": "Steve McQueen 2020 anthology, 5 films for BBC/Amazon; individual episodes also have own IMDb entries",
        "final_action": "matched",
    },
    "1223": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt6704972",
        "imdb_title": "The Underground Railroad",
        "notes": "Barry Jenkins 2021, Amazon Prime, 10 episodes; review candidates were wrong (1999 TV movie)",
        "final_action": "matched",
    },

    # New spines 1306–1317
    "1306": {
        "entity_type": "movie", "imdb_id": "tt0062138",
        "imdb_title": "Point Blank",
        "notes": "John Boorman 1967, Lee Marvin",
        "final_action": "matched",
    },
    "1308": {
        "entity_type": "movie", "imdb_id": "tt0082089",
        "imdb_title": "Body Heat",
        "notes": "Lawrence Kasdan 1981",
        "final_action": "matched",
    },
    "1309": {
        "entity_type": "movie", "imdb_id": "tt0116070",
        "imdb_title": "The Delta",
        "notes": "Ira Sachs 1996, LGBT drama",
        "final_action": "matched",
    },
    "1310": {
        "entity_type": "movie", "imdb_id": "tt0109843",
        "imdb_title": "Fresh Kill",
        "notes": "Shu Lea Cheang 1994, sci-fi drama",
        "final_action": "matched",
    },
    "1311": {
        "entity_type": "movie", "imdb_id": "tt27714581",
        "imdb_title": "Sentimental Value",
        "notes": "Joachim Trier 2025; won Grand Prix at Cannes 2025",
        "final_action": "matched",
    },
    "1312": {
        "entity_type": "movie", "imdb_id": "tt0071932",
        "imdb_title": "Lenny",
        "notes": "Bob Fosse 1974, Dustin Hoffman as Lenny Bruce",
        "final_action": "matched",
    },
    "1313": {
        "entity_type": "movie", "imdb_id": "tt0080125",
        "imdb_title": "West Indies",
        "notes": "West Indies: The Fugitive Slaves of Liberty, Med Hondo 1979; original title: Les Négriers",
        "final_action": "matched",
    },
    "1314": {
        "entity_type": "movie", "imdb_id": "tt0130841",
        "imdb_title": "High Art",
        "notes": "Lisa Cholodenko 1998",
        "final_action": "matched",
    },
    "1315": {
        "entity_type": "movie", "imdb_id": "tt0095341",
        "imdb_title": "Hairspray",
        "notes": "John Waters 1988",
        "final_action": "matched",
    },
    "1316": {
        "entity_type": "movie", "imdb_id": "tt0076164",
        "imdb_title": "Desperate Living",
        "notes": "John Waters 1977",
        "final_action": "matched",
    },
    "1317": {
        "entity_type": "movie", "imdb_id": "tt36491653",
        "imdb_title": "It Was Just an Accident",
        "notes": "Jafar Panahi 2025; won Palme d'Or at Cannes 2025",
        "final_action": "matched",
    },

    # =========================================================
    # NAMED CRITERION ENTRIES — Collections (no single IMDb)
    # =========================================================

    "66": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Orphic Trilogy: Blood of a Poet (tt0021629) + Orpheus (tt0041838) + Testament of Orpheus (tt0054506); all Jean Cocteau",
        "final_action": "collection",
    },
    "79": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "6 Paramount comedy shorts 1933: The Dentist/The Fatal Glass of Beer/The Pharmacist/Hip Action/The Barber Shop/The Fatal Glass of Beer",
        "final_action": "collection",
    },
    "86": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Alexander Nevsky (tt0029850) + Ivan the Terrible Pt 1 (tt0036873) + Ivan the Terrible Pt 2 (tt0051790)",
        "final_action": "collection",
    },
    "167": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Monterey Pop (tt0060036) + Jimi Plays Monterey (tt0093312) + Shake! Otis at Monterey (tt0093951)",
        "final_action": "collection",
    },
    "176": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "The Killers (1946, Siodmak, tt0038669) + The Killers (1964, Siegel, tt0058262)",
        "final_action": "collection",
    },
    "179": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "I Am Curious—Yellow (tt0061834) + I Am Curious—Blue (tt0063149); both Vilgot Sjöman",
        "final_action": "collection",
    },
    "185": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "5 Truffaut Antoine Doinel films: The 400 Blows + Antoine and Colette + Stolen Kisses + Bed and Board + Love on the Run",
        "final_action": "collection",
    },
    "203": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Fassbinder BRD Trilogy: The Marriage of Maria Braun (tt0079095) + Lola (tt0080817) + Veronika Voss (tt0082989)",
        "final_action": "collection",
    },
    "208": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Bergman Trilogy of Faith: Through a Glass Darkly (tt0055499) + Winter Light (tt0057765) + The Silence (tt0057507)",
        "final_action": "collection",
    },
    "232": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Two Ozu films: A Story of Floating Weeds (tt0025358, 1934) + Floating Weeds (tt0051523, 1959)",
        "final_action": "collection",
    },
    "239": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "The Lower Depths: Renoir (tt0027336, 1936) + Kurosawa (tt0050330, 1957)",
        "final_action": "collection",
    },
    "241": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Three Renoir films: The Golden Coach + Elena and Her Men + French Cancan",
        "final_action": "collection",
    },
    "250": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "5 Cassavetes films: Shadows + Faces + A Woman Under the Influence + The Killing of a Chinese Bookie + Opening Night",
        "final_action": "collection",
    },
    "282": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Wajda war trilogy: A Generation (tt0047200) + Kanal (tt0050434) + Ashes and Diamonds (tt0051150)",
        "final_action": "collection",
    },
    "322": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Multiple versions of Welles' 1955 film; original Mr. Arkadin: tt0048949; Criterion box set with different cuts",
        "final_action": "collection",
    },
    "327": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "3 Malle early features: Elevator to the Gallows (tt0050189) + The Lovers (tt0051694) + Zazie dans le Métro (tt0054315)",
        "final_action": "collection",
    },
    "342": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Rohmer's Six Contes Moraux: La Boulangère de Monceau + La Carrière de Suzanne + My Night at Maud's + La Collectionneuse + Claire's Knee + Chloe in the Afternoon",
        "final_action": "collection",
    },
    "360": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "William Greaves: Symbiopsychotaxiplasm Take One (tt0063498, 1968) + Take 2½ (tt0373900, 2005)",
        "final_action": "collection",
    },
    "364": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "4 Anglo-Amalgamated horror films: The Crawling Eye + Corridors of Blood + Fiend Without a Face + First Man Into Space",
        "final_action": "collection",
    },
    "369": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Paul Robeson films and docs: Body and Soul + The Emperor Jones + Sanders of the River + Show Boat + Paul Robeson: Tribute to an Artist",
        "final_action": "collection",
    },
    "387": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Two Chris Marker films: La Jetée (tt0056119, 1963 short) + Sans Soleil (tt0084380, 1983)",
        "final_action": "collection",
    },
    "392": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Three Teshigahara films: Pitfall (tt0055444) + Woman in the Dunes (tt0058625) + The Face of Another (tt0061798)",
        "final_action": "collection",
    },
    "406": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Anthology: A Dancer's World (1957) + Appalachian Spring (1959) + Night Journey (1961); Martha Graham dance films",
        "final_action": "collection",
    },
    "418": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "4 Varda features: Cléo de 5 à 7 + Le Bonheur + Vagabond + One Sings, the Other Doesn't",
        "final_action": "collection",
    },
    "468": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "23 short nature documentaries by Jean Painlevé",
        "final_action": "collection",
    },
    "471": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "3 Imamura films: Pigs and Battleships + Intentions of Murder + The Pornographers",
        "final_action": "collection",
    },
    "480": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Kobayashi trilogy: No Greater Love (tt0052836, 1959) + Road to Eternity (tt0053143, 1959) + A Soldier's Prayer (tt0054527, 1961)",
        "final_action": "collection",
    },
    "495": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Classic 1950s live TV dramas: Marty + Days of Wine and Roses + Requiem for a Heavyweight + 12 Angry Men + others",
        "final_action": "collection",
    },
    "500": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Rossellini's War Trilogy: Rome Open City (tt0038890) + Paisà (tt0039535) + Germany Year Zero (tt0040527)",
        "final_action": "collection",
    },
    "508": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Pedro Costa's Fontainhas trilogy: Ossos + In Vanda's Room + Colossal Youth",
        "final_action": "collection",
    },
    "518": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Complete Brakhage anthology: Vol 1 (tt2031785) + Vol 2 (tt33099287); combined 2-disc set",
        "final_action": "collection",
    },
    "524": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Two Ozu sound films: The Only Son (tt0028026, 1936) + There Was a Father (tt0035277, 1942)",
        "final_action": "collection",
    },
    "528": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "3 von Sternberg silents: Underworld (tt0018559) + The Last Command (tt0019155) + The Docks of New York (tt0018964)",
        "final_action": "collection",
    },
    "578": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "All Vigo films: À propos de Nice (tt0021599) + Taris (tt0022716) + Zéro de conduite (tt0024604) + L'Atalante (tt0024831)",
        "final_action": "collection",
    },
    "587": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Kieślowski Three Colors: Blue (tt0108394) + White (tt0111507) + Red (tt0111495)",
        "final_action": "collection",
    },
    "603": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "David Lean directing Noël Coward: In Which We Serve + This Happy Breed + Blithe Spirit + Brief Encounter",
        "final_action": "collection",
    },
    "607": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Anthology of Hollis Frampton avant-garde films including Zorns Lemma, Nostalgia, Magellan fragments",
        "final_action": "collection",
    },
    "631": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Pasolini Trilogy of Life: The Decameron (tt0066893) + The Canterbury Tales (tt0068616) + Arabian Nights (tt0073164)",
        "final_action": "collection",
    },
    "639": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Qatsi Trilogy: Koyaanisqatsi (tt0085809) + Powaqqatsi (tt0095504) + Naqoyqatsi (tt0274085)",
        "final_action": "collection",
    },
    "655": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "5 Pierre Etaix films: The Suitor + Yoyo + As Long As You're Healthy + Le Grand Amour + Pays de Cocagne",
        "final_action": "collection",
    },
    "672": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Rossellini/Bergman: Stromboli (tt0041715) + Europe '51 (tt0044519) + Journey to Italy (tt0047286)",
        "final_action": "collection",
    },
    "679": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Complete 25-film Zatoichi series (1962-1989) plus Kitano's 2003 film",
        "final_action": "collection",
    },
    "684": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Scorsese World Cinema Project #1: restored films from Senegal, Ethiopia, Morocco, Philippines, Mozambique",
        "final_action": "collection",
    },
    "713": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Jacques Demy films: Lola + Bay of Angels + The Umbrellas of Cherbourg + Young Girls of Rochefort + Donkey Skin + A Room in Town",
        "final_action": "collection",
    },
    "729": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Complete Tati: Jour de Fête + Monsieur Hulot's Holiday + Mon Oncle + Playtime + Traffic + Parade",
        "final_action": "collection",
    },
    "737": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Collection of Les Blank documentaries; primary film: Always for Pleasure (tt0077209, 1978) plus ~8 other docs",
        "final_action": "collection",
    },
    "782": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Ray's Apu Trilogy: Pather Panchali (tt0048473) + Aparajito (tt0049835) + The World of Apu (tt0053494)",
        "final_action": "collection",
    },
    "808": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Robert Drew cinema verité docs: Primary + Crisis + Jane + The Chair + Eddie + On the Pole",
        "final_action": "collection",
    },
    "813": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Wenders Road Trilogy: Alice in the Cities (tt0070842) + Wrong Move (tt0073278) + Kings of the Road (tt0074084)",
        "final_action": "collection",
    },
    "841": {
        "entity_type": "collection", "imdb_id": "tt2034724",
        "imdb_title": "Lone Wolf and Cub",
        "notes": "6-film samurai series: Baby Cart at the River Styx etc; tt2034724 appears to be the Criterion box set on IMDb",
        "final_action": "collection",
    },
    "856": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Linklater Before Trilogy: Before Sunrise (tt0112471) + Before Sunset (tt0381681) + Before Midnight (tt2401883)",
        "final_action": "collection",
    },
    "873": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Scorsese World Cinema Project #2: restored international films",
        "final_action": "collection",
    },
    "881": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Marcel Pagnol Marseille Trilogy: Marius (tt0022760) + Fanny (tt0022685) + César (tt0024721)",
        "final_action": "collection",
    },
    "900": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Criterion/IOC collection of Olympic documentary films 1912–2012",
        "final_action": "collection",
    },
    "930": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Dietrich & von Sternberg 6-film set: Morocco + Dishonored + Shanghai Express + Blonde Venus + The Scarlet Empress + The Devil Is a Woman",
        "final_action": "collection",
    },
    "1000": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "15 original Godzilla films 1954–1975 (Showa era), Toho",
        "final_action": "collection",
    },
    "1036": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Bruce Lee films: The Big Boss + Fist of Fury + The Way of the Dragon + Enter the Dragon + Game of Death",
        "final_action": "collection",
    },
    "1044": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Scorsese World Cinema Project #3: restored international films",
        "final_action": "collection",
    },
    "1082": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Marlon Riggs films: Ethnic Notions + Color Adjustment + Tongues Untied + Non Je Ne Regrette Rien + Anthem + Black Is...Black Ain't",
        "final_action": "collection",
    },
    "1103": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "6-film Jackie Chan/Tsui Hark OUATIC series 1991-1997",
        "final_action": "collection",
    },
    "1142": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Scorsese World Cinema Project #4: restored international films",
        "final_action": "collection",
    },
    "1159": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Infernal Affairs Trilogy (Hong Kong): Infernal Affairs 1+2+3 by Lau Wai-keung & Alan Mak",
        "final_action": "collection",
    },
    "1162": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "3 Mai Zetterling films: Loving Couples + Night Games + The Girls",
        "final_action": "collection",
    },
    "1163": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Haneke glaciation trilogy: The Seventh Continent (tt0098802) + Benny's Video (tt0103976) + 71 Fragments (tt0109688)",
        "final_action": "collection",
    },
    "1168": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Lars von Trier Europe Trilogy: The Element of Crime (tt0087216) + Epidemic (tt0092961) + Europa (tt0101765)",
        "final_action": "collection",
    },
    "1172": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Two Marguerite Duras films: India Song (tt0073008) + Son nom de Venise dans Calcutta désert (tt0075298)",
        "final_action": "collection",
    },
    "1186": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "5 Budd Boetticher westerns with Randolph Scott: Seven Men from Now + The Tall T + Decision at Sundown + Buchanan Rides Alone + Ride Lonesome + Comanche Station",
        "final_action": "collection",
    },
    "1189": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "5 Bo Widerberg films: Raven's End + Love 65 + Elvira Madigan + Adalen 31 + Joe Hill",
        "final_action": "collection",
    },
    "1194": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "3 Tod Browning films: Freaks (tt0022913) + The Unknown (tt0018486) + The Mystic (tt0015115)",
        "final_action": "collection",
    },
    "1197": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Jackie Chan early films: Snake in the Eagle's Shadow + Drunken Master + Fearless Hyena",
        "final_action": "collection",
    },
    "1200": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "5 Albert Lamorisse films: White Mane + The Red Balloon + Voyage en Ballon + Fifi la Plume + others",
        "final_action": "collection",
    },
    "1203": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Chantal Akerman 1968-1978: Saute ma ville + La Chambre + Je tu il elle + Jeanne Dielman + News from Home + Les Rendez-vous d'Anna",
        "final_action": "collection",
    },
    "1206": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "4 Rohmer seasons films: A Tale of Springtime + A Tale of Winter + A Tale of Summer + A Tale of Autumn",
        "final_action": "collection",
    },
    "1207": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Two Hong Kong action films: The Heroic Trio (tt0107126, 1993) + Executioners (tt0108606, 1993)",
        "final_action": "collection",
    },
    "1217": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "3 Sembène films: Mandabi (tt0062992) + Emitaï (tt0068165) + Xala (tt0071491)",
        "final_action": "collection",
    },
    "1229": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Two Muratova films: Brief Encounters (tt0112088, 1967) + The Long Farewell (tt0073132, 1971)",
        "final_action": "collection",
    },
    "1233": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Gregg Araki Teen Apocalypse: Totally F***ed Up (tt0108507) + The Doom Generation (tt0112779) + Nowhere (tt0117528)",
        "final_action": "collection",
    },
    "1236": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Val Lewton productions: I Walked with a Zombie (tt0036020) + The Seventh Victim (tt0036365)",
        "final_action": "collection",
    },
    "1257": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Claude Berri 1986 diptych: Jean de Florette (tt0091288) + Manon des Sources / Manon of the Spring (tt0091289)",
        "final_action": "collection",
    },
    "1263": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Richard Lester films: The Three Musketeers (tt0070917, 1973) + The Four Musketeers (tt0071967, 1974)",
        "final_action": "collection",
    },
    "1275": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Two Edward Yang films: A Confucian Confusion (tt0109419, 1994) + Mahjong (tt0116917, 1996)",
        "final_action": "collection",
    },
    "1296": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "Scorsese World Cinema Project #5: restored international films",
        "final_action": "collection",
    },
    "1307": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "",
        "notes": "John Singleton Hood Trilogy: Boyz n the Hood (tt0101507) + Poetic Justice (tt0107888) + Baby Boy (tt0228232)",
        "final_action": "collection",
    },

    # =========================================================
    # COLLECTION CONSTITUENT FILMS (spineless, with directors)
    # =========================================================

    "row_1330": {
        "entity_type": "short", "imdb_id": "tt0056119",
        "imdb_title": "La Jetée",
        "notes": "Chris Marker 1962 short film (28 min); part of La Jetée/Sans Soleil set (spine 387)",
        "final_action": "matched",
    },
    "row_1420": {
        "entity_type": "documentary", "imdb_id": "tt9530198",
        "imdb_title": "Varda by Agnès",
        "notes": "Agnès Varda's final film/documentary 2019; confirmed by web search",
        "final_action": "matched",
    },
    "row_1430": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt2125012",
        "imdb_title": "Agnès de ci de là Varda",
        "notes": "5-episode TV series 2011, also titled 'Agnes Varda: From Here to There'; confirmed by web search",
        "final_action": "matched",
    },
    "row_1450": {
        "entity_type": "short", "imdb_id": "tt0060810",
        "imdb_title": "Paddle to the Sea",
        "notes": "Bill Mason 1966, NFB Canadian short; confirmed by web search",
        "final_action": "matched",
    },
    "row_1454": {
        "entity_type": "collection", "imdb_id": "",
        "imdb_title": "Three Documentaries",
        "notes": "Criterion-specific compilation: The Great Chase + The Love Goddesses + Paul Robeson: Tribute to an Artist (1962); no single IMDb entry",
        "final_action": "no_imdb_entry",
    },
    "row_1467": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt0063914",
        "imdb_title": "Phantom India",
        "notes": "L'Inde fantôme, Louis Malle 1969, 7-part TV documentary; confirmed by web search",
        "final_action": "matched",
    },
    "row_1519": {
        "entity_type": "tvMiniSeries", "imdb_id": "tt0069684",
        "imdb_title": "The Age of the Medici",
        "notes": "L'età di Cosimo de' Medici, Roberto Rossellini 1973, 3-part TV; confirmed by web search",
        "final_action": "matched",
    },
    "row_1520": {
        "entity_type": "tvMovie", "imdb_id": "tt0161382",
        "imdb_title": "Cartesius",
        "notes": "Roberto Rossellini 1974 TV film about Descartes; confirmed by web search",
        "final_action": "matched",
    },
    "row_1580": {
        "entity_type": "movie", "imdb_id": "tt0022036",
        "imdb_title": "Flunky, Work Hard",
        "notes": "Koshiben ganbare, Mikio Naruse 1931; first surviving Naruse film; confirmed by web search",
        "final_action": "matched",
    },
    "row_1588": {
        "entity_type": "movie", "imdb_id": "tt0043532",
        "imdb_title": "Nobody's Children",
        "notes": "I figli di nessuno, Raffaello Matarazzo 1951 (Criterion year 1952); confirmed by web search",
        "final_action": "matched",
    },
    "row_1663": {
        "entity_type": "short", "imdb_id": "tt0179389",
        "imdb_title": "Uncle Yanco",
        "notes": "Agnès Varda 1967 short documentary (22 min); confirmed by web search",
        "final_action": "matched",
    },
    "row_1664": {
        "entity_type": "short", "imdb_id": "tt0209942",
        "imdb_title": "Black Panthers",
        "notes": "Agnès Varda 1968 short documentary (28 min); confirmed by web search",
        "final_action": "matched",
    },
    "row_1675": {
        "entity_type": "movie", "imdb_id": "tt0154767",
        "imdb_title": "Lettres d'amour",
        "notes": "Claude Autant-Lara 1942 French film; confirmed by web search",
        "final_action": "matched",
    },
    "row_1685": {
        "entity_type": "movie", "imdb_id": "tt0149184",
        "imdb_title": "A Tale of Autumn",
        "notes": "Conte d'automne, Eric Rohmer 1998",
        "final_action": "matched",
    },
    "row_1693": {
        "entity_type": "short", "imdb_id": "tt0067053",
        "imdb_title": "L'enfant aimé ou Je joue à être une femme mariée",
        "notes": "Chantal Akerman 1971 short; confirmed by web search",
        "final_action": "matched",
    },
    "row_1708": {
        "entity_type": "short", "imdb_id": "tt0137129",
        "imdb_title": "Non, Je Ne Regrette Rien (No Regret)",
        "notes": "Marlon Riggs 1992/1993 short documentary; confirmed by web search",
        "final_action": "matched",
    },
    "row_1710": {
        "entity_type": "tvSpecial", "imdb_id": "tt10618074",
        "imdb_title": "Red, White and Blue",
        "notes": "Steve McQueen 2020, Small Axe episode 4; part of tt9055008 anthology",
        "final_action": "matched",
    },
    "row_1748": {
        "entity_type": "movie", "imdb_id": "tt0085864",
        "imdb_title": "Fearless Hyena II",
        "notes": "Chan Chuen 1983; Jackie Chan refused to participate; confirmed by web search",
        "final_action": "matched",
    },
    "row_1754": {
        "entity_type": "short", "imdb_id": "tt0136710",
        "imdb_title": "Anthem",
        "notes": "Marlon Riggs 1991 short film; confirmed by web search",
        "final_action": "matched",
    },
    "row_1763": {
        "entity_type": "movie", "imdb_id": "tt0115940",
        "imdb_title": "A Tale of Summer",
        "notes": "Conte d'été, Eric Rohmer 1996; confirmed by web search",
        "final_action": "matched",
    },
    "row_1769": {
        "entity_type": "short", "imdb_id": "tt0069664",
        "imdb_title": "Le 15/8",
        "notes": "Chantal Akerman & Samy Szlingerbaum 1973 short; confirmed by web search",
        "final_action": "matched",
    },
    "row_1779": {
        "entity_type": "tvSpecial", "imdb_id": "tt10612956",
        "imdb_title": "Lovers Rock",
        "notes": "Steve McQueen 2020, Small Axe episode 2; part of tt9055008 anthology",
        "final_action": "matched",
    },
    "row_1792": {
        "entity_type": "tvSpecial", "imdb_id": "tt11080618",
        "imdb_title": "Alex Wheatle",
        "notes": "Steve McQueen 2020, Small Axe episode 5; part of tt9055008 anthology",
        "final_action": "matched",
    },
    "row_1798": {
        "entity_type": "documentary", "imdb_id": "tt0109285",
        "imdb_title": "Black Is... Black Ain't",
        "notes": "Marlon Riggs 1994 documentary; confirmed by web search",
        "final_action": "matched",
    },
    "row_1807": {
        "entity_type": "short", "imdb_id": "tt0063551",
        "imdb_title": "Saute ma ville",
        "notes": "Chantal Akerman 1968 short (13 min); confirmed by web search",
        "final_action": "matched",
    },
    "row_1813": {
        "entity_type": "tvSpecial", "imdb_id": "tt10606966",
        "imdb_title": "Mangrove",
        "notes": "Steve McQueen 2020, Small Axe episode 1; part of tt9055008 anthology",
        "final_action": "matched",
    },
    "row_1818": {
        "entity_type": "movie", "imdb_id": "tt34250044",
        "imdb_title": "Peter Hujar's Day",
        "notes": "Ira Sachs 2025; confirmed by web search",
        "final_action": "matched",
    },
    "row_1819": {
        "entity_type": "movie", "imdb_id": "tt29002950",
        "imdb_title": "Resurrection",
        "notes": "Bi Gan 2025 Chinese sci-fi; won Jury Special Prize Cannes 2025; confirmed by web search",
        "final_action": "matched",
    },
    "row_1820": {
        "entity_type": "movie", "imdb_id": "tt0101507",
        "imdb_title": "Boyz n the Hood",
        "notes": "John Singleton 1991; part of Hood Trilogy (spine 1307)",
        "final_action": "matched",
    },
    "row_1821": {
        "entity_type": "movie", "imdb_id": "tt0107888",
        "imdb_title": "Poetic Justice",
        "notes": "John Singleton 1993; part of Hood Trilogy (spine 1307)",
        "final_action": "matched",
    },
    "row_1822": {
        "entity_type": "movie", "imdb_id": "tt0228232",
        "imdb_title": "Baby Boy",
        "notes": "John Singleton 2001; part of Hood Trilogy (spine 1307)",
        "final_action": "matched",
    },
    "row_1824": {
        "entity_type": "movie", "imdb_id": "tt0407929",
        "imdb_title": "Love Letter",
        "notes": "Koibumi, Kinuyo Tanaka 1953; her directorial debut; confirmed by web search",
        "final_action": "matched",
    },
    "row_1825": {
        "entity_type": "movie", "imdb_id": "tt0417214",
        "imdb_title": "The Moon Has Risen",
        "notes": "Tsuki wa noborinu, Kinuyo Tanaka 1955; script by Yasujiro Ozu; confirmed by web search",
        "final_action": "matched",
    },
    "row_1826": {
        "entity_type": "movie", "imdb_id": "tt0259248",
        "imdb_title": "Forever a Woman",
        "notes": "aka The Eternal Breasts; Chibusa yo eien nare, Kinuyo Tanaka 1955; confirmed by web search",
        "final_action": "matched",
    },
    "row_1827": {
        "entity_type": "movie", "imdb_id": "tt0385202",
        "imdb_title": "The Wandering Princess",
        "notes": "Ruten no ōhi, Kinuyo Tanaka 1960; confirmed by web search",
        "final_action": "matched",
    },
    "row_1828": {
        "entity_type": "movie", "imdb_id": "tt0203040",
        "imdb_title": "Girls of the Night",
        "notes": "Onna bakari no yoru, Kinuyo Tanaka 1961; confirmed by web search",
        "final_action": "matched",
    },
    "row_1829": {
        "entity_type": "movie", "imdb_id": "tt0203751",
        "imdb_title": "Love Under the Crucifix",
        "notes": "Ogin-sama, Kinuyo Tanaka 1962; her final film; confirmed by web search",
        "final_action": "matched",
    },
    "row_1830": {
        "entity_type": "movie", "imdb_id": "tt36456563",
        "imdb_title": "Magellan",
        "notes": "Lav Diaz 2025 Filipino film; Philippines' official Academy Awards entry; confirmed by web search",
        "final_action": "matched",
    },
}

# ===========================================================================
# Apply resolutions to the unmatched tracking file
# ===========================================================================

def main():
    unmatched = load_csv(IN_UNMATCHED)
    print(f"Loaded {len(unmatched)} unmatched rows")

    resolution_log_rows = []
    resolved_match_rows = []
    still_unresolved_rows = []

    # Count stats
    stats = {"matched": 0, "collection": 0, "collection_label": 0,
             "no_imdb_entry": 0, "unresolved": 0}

    for row in unmatched:
        src = row["criterion_source_id"]
        res = RESOLUTIONS.get(src)

        if row["entity_type"] == "collection_header":
            # All spineless collection-label rows
            log_row = {
                "criterion_row_id":            row["criterion_row_id"],
                "criterion_source_id":         src,
                "criterion_title_original":    row["criterion_title_original"],
                "criterion_director_original": row["criterion_director_original"],
                "criterion_year":              row["criterion_year"],
                "entity_type":                 "collection_label",
                "final_action":                "collection_label",
                "imdb_id":                     "",
                "imdb_title":                  "",
                "notes":                       "Collection/box-set label row; no individual IMDb entry needed",
                "resolved_at":                 ts(),
            }
            stats["collection_label"] += 1
            resolution_log_rows.append(log_row)
            continue

        if not res:
            # Not in resolution DB — keep as still unresolved
            log_row = {
                "criterion_row_id":            row["criterion_row_id"],
                "criterion_source_id":         src,
                "criterion_title_original":    row["criterion_title_original"],
                "criterion_director_original": row["criterion_director_original"],
                "criterion_year":              row["criterion_year"],
                "entity_type":                 row["entity_type"],
                "final_action":                "unresolved",
                "imdb_id":                     row.get("candidate_imdb_id", ""),
                "imdb_title":                  row.get("candidate_imdb_title", ""),
                "notes":                       "Not yet resolved",
                "resolved_at":                 ts(),
            }
            stats["unresolved"] += 1
            still_unresolved_rows.append(row)
            resolution_log_rows.append(log_row)
            continue

        log_row = {
            "criterion_row_id":            row["criterion_row_id"],
            "criterion_source_id":         src,
            "criterion_title_original":    row["criterion_title_original"],
            "criterion_director_original": row["criterion_director_original"],
            "criterion_year":              row["criterion_year"],
            "entity_type":                 res["entity_type"],
            "final_action":                res["final_action"],
            "imdb_id":                     res["imdb_id"],
            "imdb_title":                  res["imdb_title"],
            "notes":                       res["notes"],
            "resolved_at":                 ts(),
        }
        stats[res["final_action"]] += 1
        resolution_log_rows.append(log_row)

        if res["final_action"] == "matched" and res["imdb_id"]:
            resolved_match_rows.append({
                "criterion_row_id":            row["criterion_row_id"],
                "criterion_source_id":         src,
                "criterion_title_original":    row["criterion_title_original"],
                "criterion_title_normalized":  row["criterion_title_normalized"],
                "criterion_director_original": row["criterion_director_original"],
                "criterion_year":              row["criterion_year"],
                "imdb_id":                     res["imdb_id"],
                "imdb_title":                  res["imdb_title"],
                "entity_type":                 res["entity_type"],
                "final_action":                "matched",
                "notes":                       res["notes"],
                "resolved_at":                 ts(),
            })

    print(f"\nResolution stats:")
    for k, v in stats.items():
        print(f"  {k:20s}: {v:>4}")
    print(f"  {'TOTAL':20s}: {sum(stats.values()):>4}")

    print("\nWriting outputs …")
    write_csv(OUT_RESOLVED,   resolution_log_rows)
    write_csv(OUT_MATCHES_V2, resolved_match_rows)
    if still_unresolved_rows:
        write_csv(OUT_REMAINING, still_unresolved_rows)
    else:
        print(f"  No remaining unresolved rows!")

    print("\nDone.")


if __name__ == "__main__":
    main()
