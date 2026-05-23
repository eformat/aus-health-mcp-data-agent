"""NNDSS MCP Server — Australian Disease Surveillance Data Gateway.

All data access goes through Trino (Iceberg lakehouse on MinIO S3).
Metadata tools (describe_datasets, get_methodology) return hardcoded
domain knowledge. The query_trino tool executes agent-generated SQL.

Data sources:
  - NNDSS public datasets loaded into Trino Iceberg tables
  - Table: lakehouse.nndss.notifications (year, state, disease, notifications)
  - Diseases: influenza, meningococcal, pneumococcal, salmonellosis
"""

from __future__ import annotations

import os
import re

from fastmcp import FastMCP

mcp = FastMCP(
    name="nndss-data-server",
    instructions=(
        "Australian NNDSS disease surveillance data server. "
        "All data queries go through Trino SQL. Metadata tools provide "
        "methodology and dataset descriptions."
    ),
)

TRINO_HOST = os.environ.get("TRINO_QUERY_HOST", "trino")
TRINO_PORT = int(os.environ.get("TRINO_QUERY_PORT", "8080"))

_DISEASE_ALIASES = {
    "flu": "influenza",
    "the flu": "influenza",
    "influenza": "influenza",
    "meningococcal": "meningococcal",
    "meningitis": "meningococcal",
    "imd": "meningococcal",
    "invasive meningococcal disease": "meningococcal",
    "pneumococcal": "pneumococcal",
    "ipd": "pneumococcal",
    "invasive pneumococcal disease": "pneumococcal",
    "salmonellosis": "salmonellosis",
    "salmonella": "salmonellosis",
    "food poisoning": "salmonellosis",
}

_DISEASE_FORMAL = {
    "influenza": "Influenza (laboratory confirmed)",
    "meningococcal": "Invasive meningococcal disease",
    "pneumococcal": "Invasive pneumococcal disease",
    "salmonellosis": "Salmonellosis",
}

_METHODOLOGY = {
    "influenza": {
        "collection_design": (
            "Passive surveillance via the National Notifiable Diseases "
            "Surveillance System (NNDSS). Laboratory-confirmed influenza "
            "notifications are reported by pathology laboratories and "
            "clinicians to state/territory health authorities, who forward "
            "de-identified records to the Australian CDC."
        ),
        "case_definition": (
            "Requires laboratory definitive evidence: isolation of influenza "
            "virus, OR detection of influenza virus by nucleic acid testing "
            "(PCR), OR detection of influenza virus antigen by direct "
            "immunofluorescence (DIF) on respiratory specimens, OR "
            "seroconversion or significant rise in antibody level."
        ),
        "instruments": "PCR (predominant since ~2010), viral culture, DIF, serology",
        "population_coverage": (
            "All Australian residents. However, notifications depend on "
            "healthcare-seeking behaviour and testing practices. Mild cases "
            "that don't present to a clinician are not captured. The shift "
            "to PCR testing from ~2010 increased detection sensitivity, "
            "making pre-2010 and post-2010 counts not directly comparable."
        ),
        "known_biases": [
            "Under-reporting: only cases that present to healthcare AND are tested are captured",
            "Testing bias: PCR adoption varied by state/territory and over time",
            "Seasonal variation in testing: more testing during winter peaks",
            "COVID-19 impact: 2020-2021 saw dramatically reduced influenza due to public health measures",
            "Reporting lag: notifications may be delayed days to weeks after diagnosis",
        ],
        "geographic_resolution": "State/territory (not LGA or postcode in public datasets)",
        "temporal_resolution": "Monthly notification date (month of diagnosis)",
        "update_frequency": "Public datasets updated annually in July",
    },
    "meningococcal": {
        "collection_design": (
            "Passive surveillance via NNDSS. Invasive meningococcal disease "
            "notifications from laboratory-confirmed and clinically diagnosed "
            "cases reported by clinicians and laboratories."
        ),
        "case_definition": (
            "Confirmed: isolation of Neisseria meningitidis from a normally "
            "sterile site, OR detection by nucleic acid testing. "
            "Probable: clinically compatible illness with supportive serology "
            "or detection of gram-negative diplococci."
        ),
        "instruments": "Blood culture, CSF culture, PCR, gram stain",
        "population_coverage": (
            "All Australian residents. High case ascertainment due to disease "
            "severity — most cases present to hospital. Serogroup distribution "
            "varies by state/territory and over time."
        ),
        "known_biases": [
            "Relatively complete capture due to disease severity",
            "Serogroup ascertainment may be incomplete for culture-negative cases",
            "Small numbers: jurisdictional breakdowns may be unstable",
        ],
        "geographic_resolution": "State/territory",
        "temporal_resolution": "Monthly notification date",
        "update_frequency": "Public datasets updated annually in July",
    },
    "pneumococcal": {
        "collection_design": (
            "Passive surveillance via NNDSS. Invasive pneumococcal disease "
            "notifications from laboratory-confirmed cases."
        ),
        "case_definition": (
            "Confirmed: isolation of Streptococcus pneumoniae from a normally "
            "sterile site, OR detection by nucleic acid testing from a "
            "normally sterile site."
        ),
        "instruments": "Blood culture, CSF culture, PCR, urinary antigen testing",
        "population_coverage": (
            "All Australian residents. Vaccination programs (7vPCV from 2005, "
            "13vPCV from 2011, 20vPCV from 2024) have significantly changed "
            "serotype distribution and overall incidence."
        ),
        "known_biases": [
            "Vaccination program changes affect trend interpretation",
            "Serotype replacement: non-vaccine serotypes may increase as vaccine serotypes decrease",
            "Under-ascertainment of non-bacteraemic pneumococcal pneumonia",
        ],
        "geographic_resolution": "State/territory",
        "temporal_resolution": "Monthly notification date",
        "update_frequency": "Public datasets updated annually in July",
    },
    "salmonellosis": {
        "collection_design": (
            "Passive surveillance via NNDSS. Salmonellosis notifications from "
            "laboratory-confirmed cases."
        ),
        "case_definition": (
            "Confirmed: isolation of Salmonella species (excluding S. Typhi "
            "and S. Paratyphi) from clinical specimens."
        ),
        "instruments": "Stool culture, blood culture, MALDI-TOF, whole genome sequencing",
        "population_coverage": (
            "All Australian residents. Notifications depend on "
            "healthcare-seeking behaviour — many mild gastroenteritis cases "
            "do not present to a clinician or have a stool sample collected."
        ),
        "known_biases": [
            "Significant under-reporting: estimated 7-10 community cases per notification",
            "Seasonal peaks in warmer months reflect foodborne transmission",
            "Outbreak-associated clusters can inflate counts for specific periods",
            "S. Typhimurium and S. Enteritidis dominate but serovar distribution varies by state",
        ],
        "geographic_resolution": "State/territory",
        "temporal_resolution": "Monthly notification date",
        "update_frequency": "Public datasets updated annually in July",
    },
}

_BLOCKED_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def _resolve_disease(query: str) -> str | None:
    return _DISEASE_ALIASES.get(query.strip().lower())


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(description=(
    "Execute a read-only SQL query against the NNDSS Iceberg lakehouse in Trino. "
    "This is the primary data access tool — use it for ALL data queries.\n\n"
    "Tables:\n"
    "1. lakehouse.nndss.notifications — annual notification counts (4 diseases, 2008-2025)\n"
    "   Columns: year (INTEGER), state (VARCHAR), disease (VARCHAR), notifications (INTEGER)\n"
    "   Disease values: 'Influenza (laboratory confirmed)', "
    "'Invasive meningococcal disease', 'Invasive pneumococcal disease', 'Salmonellosis'\n\n"
    "2. lakehouse.nndss.fortnightly_notifications — fortnightly counts (73 diseases, 2024-2026)\n"
    "   Columns: year (INTEGER), period_start (VARCHAR), period_end (VARCHAR), "
    "disease_group (VARCHAR), disease (VARCHAR), state (VARCHAR), notifications (INTEGER), "
    "source_file (VARCHAR)\n"
    "   Disease groups: Bloodborne, Gastrointestinal, Respiratory, Sexually transmissible, "
    "Vaccine preventable, Vectorborne, Zoonoses, Other\n"
    "   Includes: COVID-19, RSV, Pertussis, Measles, Dengue, Chlamydia, Gonorrhoea, "
    "Hepatitis B/C, Tuberculosis, Campylobacteriosis, Ross River virus, and many more\n\n"
    "3. lakehouse.nndss.population — ABS estimated resident population by state/year\n"
    "   Columns: year (INTEGER), state (VARCHAR), population (INTEGER)\n"
    "   Source: ABS 3101.0 ERP at 30 June. Years: 2008-2025.\n\n"
    "Useful patterns:\n"
    "- Per-capita rate: SELECT n.state, n.notifications, p.population, "
    "ROUND(100000.0 * n.notifications / p.population, 1) AS rate_per_100k "
    "FROM lakehouse.nndss.notifications n JOIN lakehouse.nndss.population p "
    "ON n.state = p.state AND n.year = p.year WHERE ...\n"
    "- State comparison: SELECT state, SUM(notifications) FROM ... GROUP BY state ORDER BY 2 DESC\n"
    "- National trends: SELECT disease, year, SUM(notifications) FROM ... GROUP BY 1,2 ORDER BY 1,2\n"
    "- Cross-disease: SELECT disease, state, notifications FROM ... WHERE year = 2023\n\n"
    "Trino AI functions available (via llm catalog, uses Gemma 4 model):\n"
    "- ai_analyze_sentiment(text) — sentiment classification\n"
    "- ai_classify(text, ARRAY['cat1','cat2']) — classify into categories\n"
    "- ai_gen('prompt') — text generation\n"
    "- ai_extract(text, ARRAY['field1','field2']) — structured extraction\n"
))
async def query_trino(sql: str) -> dict:
    """Execute a read-only SQL query against Trino.

    Args:
        sql: SQL query to execute. Must be SELECT only (no INSERT/UPDATE/DELETE/DROP).
    """
    if _BLOCKED_SQL.search(sql):
        return {
            "results": [],
            "error": "Only SELECT queries are allowed. Write operations are blocked.",
            "data_freshness": {
                "dataset_name": "NNDSS Iceberg Lakehouse",
                "dataset_url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
            },
        }

    try:
        from trino.dbapi import connect as trino_connect

        conn = trino_connect(
            host=TRINO_HOST, port=TRINO_PORT, user="admin",
            catalog="lakehouse", schema="nndss",
        )
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchmany(1000)
        conn.close()

        results = [dict(zip(columns, row)) for row in rows]

        return {
            "results": results,
            "columns": columns,
            "row_count": len(results),
            "sql_executed": sql,
            "truncated": len(results) == 1000,

            "methodology": (
                "All NNDSS data uses passive surveillance — notifications "
                "from clinicians and laboratories to state/territory health "
                "authorities. Notification counts reflect healthcare-seeking "
                "behaviour and testing practices, not true disease incidence."
            ),

            "data_freshness": {
                "dataset_name": "NNDSS Iceberg Lakehouse (via Trino)",
                "dataset_url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
                "dataset_updated": "July 2024",
            },

            "citation": {
                "source": "Australian National Notifiable Diseases Surveillance System (NNDSS)",
                "url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
            },

            "caveats": [
                "Notifications represent laboratory-confirmed cases only.",
                "State comparisons should account for population size differences.",
                "Under-reporting varies by disease (salmonellosis ~7-10x, meningococcal near-complete).",
            ],
        }

    except Exception as exc:
        return {
            "results": [],
            "error": str(exc),
            "sql_executed": sql,
            "data_freshness": {
                "dataset_name": "NNDSS Iceberg Lakehouse (via Trino)",
                "dataset_url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
            },
        }


@mcp.tool(description=(
    "Describe and compare NNDSS datasets available for a topic. Use when "
    "the user asks what data is available, or when you need to understand "
    "dataset characteristics before writing SQL."
))
async def describe_datasets(topic: str = "") -> dict:
    """List available NNDSS datasets and their characteristics.

    Args:
        topic: Optional topic filter (e.g., 'respiratory', 'foodborne',
               'vaccine-preventable', 'all'). Default returns all datasets.
    """
    topic_lower = topic.strip().lower() if topic else "all"

    datasets = {
        "influenza": {
            "formal_name": "Influenza (laboratory confirmed)",
            "category": "respiratory",
            "also_tagged": ["vaccine-preventable"],
            "years_available": "2008-2025",
            "geographic_resolution": "State/territory",
            "key_features": [
                "Laboratory-confirmed cases only (PCR, culture, DIF, serology)",
                "Largest NNDSS dataset (~100K+ notifications/year pre-COVID)",
            ],
            "limitations": [
                "PCR adoption (~2010) makes pre/post-2010 trends non-comparable",
                "COVID-19 measures caused near-zero notifications in 2020-2021",
            ],
        },
        "meningococcal": {
            "formal_name": "Invasive meningococcal disease (IMD)",
            "category": "vaccine-preventable",
            "also_tagged": ["bacterial"],
            "years_available": "2009-2024",
            "geographic_resolution": "State/territory",
            "key_features": [
                "High case ascertainment (severe disease, most hospitalised)",
                "Small numbers — state breakdowns may be unstable",
            ],
            "limitations": [
                "Vaccination programs (MenC 2003, MenACWY 2018) affect trends",
            ],
        },
        "pneumococcal": {
            "formal_name": "Invasive pneumococcal disease (IPD)",
            "category": "vaccine-preventable",
            "also_tagged": ["bacterial", "respiratory"],
            "years_available": "2009-2024",
            "geographic_resolution": "State/territory",
            "key_features": [
                "Vaccination program changes create natural experiments",
            ],
            "limitations": [
                "Serotype replacement complicates trend interpretation",
                "Invasive disease only, not all pneumonia",
            ],
        },
        "salmonellosis": {
            "formal_name": "Salmonellosis",
            "category": "foodborne",
            "also_tagged": ["gastrointestinal", "zoonotic"],
            "years_available": "2009-2025",
            "geographic_resolution": "State/territory",
            "key_features": [
                "Most common notifiable foodborne disease in Australia",
                "Strong seasonal pattern (peaks in warmer months)",
            ],
            "limitations": [
                "Significant under-reporting (~7-10 community cases per notification)",
            ],
        },
    }

    if topic_lower not in ("all", ""):
        filtered = {
            k: v for k, v in datasets.items()
            if v["category"] == topic_lower
            or topic_lower in v.get("also_tagged", [])
            or topic_lower in k
        }
    else:
        filtered = datasets

    return {
        "availability": [
            {"dataset": v["formal_name"], "key": k, **v}
            for k, v in filtered.items()
        ],
        "methodology": (
            "All NNDSS datasets use passive surveillance. Notification counts "
            "reflect healthcare-seeking and testing practices, not true incidence."
        ),
        "cross_dataset_context": {
            "comparison_notes": (
                "Comparing across diseases requires caution: different "
                "under-reporting ratios, testing practices, and case definitions."
            ),
        },
        "data_freshness": {
            "dataset_name": "NNDSS Public Datasets",
            "dataset_url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
            "dataset_updated": "July 2024",
        },
        "citation": {
            "source": "Australian NNDSS",
            "url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
        },
    }


@mcp.tool(description=(
    "Retrieve detailed methodology for a specific NNDSS dataset. Use when "
    "assessing data quality, comparing collection methods, or explaining "
    "trend changes."
))
async def get_methodology(dataset_name: str) -> dict:
    """Get deep methodology for a specific NNDSS dataset.

    Args:
        dataset_name: Disease name (e.g., 'influenza', 'meningococcal',
                      'pneumococcal', 'salmonellosis').
    """
    resolved = _resolve_disease(dataset_name)
    if not resolved or resolved not in _METHODOLOGY:
        return {
            "methodology_structured": None,
            "terminology_note": (
                f"'{dataset_name}' could not be mapped to a known NNDSS dataset. "
                f"Available: influenza, meningococcal, pneumococcal, salmonellosis."
            ),
            "data_freshness": {
                "dataset_name": "NNDSS Public Datasets",
                "dataset_url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
            },
        }

    meth = _METHODOLOGY[resolved]

    return {
        "methodology_structured": {
            "dataset": _DISEASE_FORMAL[resolved],
            "surveillance_type": "Passive (notification-based)",
            "collection_design": meth["collection_design"],
            "case_definition": meth["case_definition"],
            "diagnostic_instruments": meth["instruments"],
            "population_coverage": meth["population_coverage"],
            "known_biases": meth["known_biases"],
            "geographic_resolution": meth["geographic_resolution"],
            "temporal_resolution": meth["temporal_resolution"],
            "update_frequency": meth["update_frequency"],
        },
        "methodology": meth["collection_design"],
        "data_freshness": {
            "dataset_name": f"NNDSS {_DISEASE_FORMAL[resolved]}",
            "dataset_url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
            "dataset_updated": "July 2024",
        },
        "citation": {
            "source": "Australian NNDSS",
            "url": "https://www.cdc.gov.au/resources/collections/nndss-public-datasets",
        },
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=9090)
