"""LangChain tools for NNDSS disease surveillance data.

All data access goes through Trino (Iceberg lakehouse on MinIO S3).
Metadata tools return hardcoded domain knowledge.
SpiceDB provides fine-grained permission checks on datasets.
"""

import json
import os
import re

import grpc

from langchain_core.tools import tool
from authzed.api.v1 import Client as SpiceDBClient

TRINO_HOST = os.environ.get("TRINO_QUERY_HOST", "trino")
TRINO_PORT = int(os.environ.get("TRINO_QUERY_PORT", "8080"))

_BLOCKED_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_DISEASE_ALIASES = {
    "flu": "influenza", "the flu": "influenza", "influenza": "influenza",
    "meningococcal": "meningococcal", "meningitis": "meningococcal",
    "imd": "meningococcal", "invasive meningococcal disease": "meningococcal",
    "pneumococcal": "pneumococcal", "ipd": "pneumococcal",
    "invasive pneumococcal disease": "pneumococcal",
    "salmonellosis": "salmonellosis", "salmonella": "salmonellosis",
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
        "collection_design": "Passive surveillance via NNDSS. Laboratory-confirmed influenza notifications reported by pathology labs and clinicians.",
        "case_definition": "Requires lab evidence: PCR, viral culture, DIF, or seroconversion.",
        "instruments": "PCR (predominant since ~2010), viral culture, DIF, serology",
        "population_coverage": "All Australian residents. Depends on healthcare-seeking and testing. PCR adoption ~2010 increased sensitivity.",
        "known_biases": ["Under-reporting", "PCR adoption varied by state", "COVID-19 2020-2021 near-zero", "Reporting lag"],
        "geographic_resolution": "State/territory",
    },
    "meningococcal": {
        "collection_design": "Passive surveillance via NNDSS. Invasive meningococcal disease from lab-confirmed and clinical cases.",
        "case_definition": "Confirmed: isolation of N. meningitidis from sterile site, or PCR detection.",
        "instruments": "Blood culture, CSF culture, PCR, gram stain",
        "population_coverage": "All residents. High ascertainment due to severity.",
        "known_biases": ["Near-complete capture", "Small numbers unstable", "Vaccination programs affect trends"],
        "geographic_resolution": "State/territory",
    },
    "pneumococcal": {
        "collection_design": "Passive surveillance via NNDSS. Invasive pneumococcal disease from lab-confirmed cases.",
        "case_definition": "Confirmed: isolation of S. pneumoniae from sterile site, or PCR.",
        "instruments": "Blood culture, CSF culture, PCR, urinary antigen",
        "population_coverage": "All residents. Vaccination programs (7vPCV 2005, 13vPCV 2011, 20vPCV 2024) changed serotype distribution.",
        "known_biases": ["Vaccine serotype replacement", "Non-bacteraemic pneumonia not captured"],
        "geographic_resolution": "State/territory",
    },
    "salmonellosis": {
        "collection_design": "Passive surveillance via NNDSS. Salmonellosis from lab-confirmed cases.",
        "case_definition": "Confirmed: isolation of Salmonella spp (excl S. Typhi/Paratyphi).",
        "instruments": "Stool culture, blood culture, MALDI-TOF, WGS",
        "population_coverage": "All residents. Many mild cases never tested — estimated 7-10x under-reporting.",
        "known_biases": ["7-10x under-reporting", "Seasonal peaks in warmer months", "Outbreak clusters inflate counts"],
        "geographic_resolution": "State/territory",
    },
}


@tool
def query_trino(sql: str) -> str:
    """Execute a read-only SQL query against the NNDSS Iceberg lakehouse in Trino.
    USE THIS TOOL for ALL data questions including per-capita, comparisons, and trends.

    Tables:
    1. lakehouse.nndss.notifications (year INT, state VARCHAR, disease VARCHAR, notifications INT)
       Diseases: 'Influenza (laboratory confirmed)', 'Invasive meningococcal disease', 'Invasive pneumococcal disease', 'Salmonellosis'
    2. lakehouse.nndss.population (year INT, state VARCHAR, population INT) — ABS ERP 2008-2025
    3. lakehouse.nndss.fortnightly_notifications (year, period_start, period_end, disease_group, disease, state, notifications) — 73 diseases, 2024-2026

    IMPORTANT: For per-capita or "healthiest state" questions, JOIN with population:
    SELECT n.state, SUM(n.notifications) as total, p.population,
           ROUND(100000.0 * SUM(n.notifications) / p.population, 1) AS rate_per_100k
    FROM lakehouse.nndss.notifications n
    JOIN lakehouse.nndss.population p ON n.state = p.state AND n.year = p.year
    WHERE n.year = 2024
    GROUP BY n.state, p.population
    ORDER BY rate_per_100k ASC

    Only SELECT queries allowed.
    """
    if _BLOCKED_SQL.search(sql):
        return json.dumps({"error": "Only SELECT queries allowed."})

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

        return json.dumps({
            "results": results,
            "row_count": len(results),
            "sql_executed": sql,
            "methodology": "NNDSS passive surveillance — notifications from clinicians/labs. Counts reflect testing practices, not true incidence.",
            "caveats": [
                "Notifications = laboratory-confirmed cases only.",
                "State comparisons should account for population size.",
                "Under-reporting varies by disease.",
            ],
        })
    except Exception as exc:
        return json.dumps({"error": str(exc), "sql_executed": sql})


@tool
def describe_datasets(topic: str = "") -> str:
    """List available NNDSS datasets and their characteristics.

    Args:
        topic: Filter by 'respiratory', 'foodborne', 'vaccine-preventable', or 'all'.
    """
    datasets = {
        "influenza": {"name": "Influenza (laboratory confirmed)", "category": "respiratory", "years": "2008-2025", "notes": "Largest dataset. PCR adoption ~2010. COVID near-zero 2020-2021."},
        "meningococcal": {"name": "Invasive meningococcal disease", "category": "vaccine-preventable", "years": "2009-2024", "notes": "Small numbers, near-complete ascertainment."},
        "pneumococcal": {"name": "Invasive pneumococcal disease", "category": "vaccine-preventable", "years": "2009-2024", "notes": "Vaccine serotype replacement complicates trends."},
        "salmonellosis": {"name": "Salmonellosis", "category": "foodborne", "years": "2009-2025", "notes": "7-10x under-reporting. Seasonal peaks."},
    }
    topic_lower = topic.strip().lower() if topic else "all"
    if topic_lower not in ("all", ""):
        datasets = {k: v for k, v in datasets.items() if topic_lower in v["category"] or topic_lower in k}

    return json.dumps({
        "datasets": list(datasets.values()),
        "also_available": "lakehouse.nndss.fortnightly_notifications covers 73 diseases (2024-2026) and lakehouse.nndss.population has ABS ERP data (2008-2025).",
    })


@tool
def get_methodology(dataset_name: str) -> str:
    """Get detailed methodology for a specific NNDSS dataset.

    Args:
        dataset_name: Disease name (e.g., 'influenza', 'meningococcal', 'pneumococcal', 'salmonellosis').
    """
    resolved = _DISEASE_ALIASES.get(dataset_name.strip().lower())
    if not resolved or resolved not in _METHODOLOGY:
        return json.dumps({"error": f"Unknown dataset '{dataset_name}'. Available: influenza, meningococcal, pneumococcal, salmonellosis."})

    meth = _METHODOLOGY[resolved]
    return json.dumps({
        "dataset": _DISEASE_FORMAL[resolved],
        "surveillance_type": "Passive (notification-based)",
        **meth,
    })


class _BearerInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, token):
        self._metadata = [("authorization", f"Bearer {token}")]

    def intercept_unary_unary(self, continuation, client_call_details, request):
        metadata = list(client_call_details.metadata or []) + self._metadata
        new_details = client_call_details._replace(metadata=metadata)
        return continuation(new_details, request)


SPICEDB_ENDPOINT = os.environ.get("SPICEDB_ENDPOINT", "dev:50051")
SPICEDB_TOKEN = os.environ.get("SPICEDB_TOKEN", "averysecretpresharedkey")

_spicedb_channel = grpc.intercept_channel(
    grpc.insecure_channel(SPICEDB_ENDPOINT),
    _BearerInterceptor(SPICEDB_TOKEN),
)
_spicedb_client = SpiceDBClient.__new__(SpiceDBClient)
_spicedb_client.init_stubs(_spicedb_channel)


@tool
def check_dataset_permission(subject_id: str, resource_id: str, permission: str) -> str:
    """Check if a user has a specific permission on a dataset using SpiceDB.

    Args:
        subject_id: The user ID to check (e.g., 'admin', 'viewer').
        resource_id: The dataset name (e.g., 'notifications', 'fortnightly_notifications', 'population').
        permission: The permission to check (e.g., 'query', 'view_metadata', 'export').

    Returns:
        JSON with 'allowed' (true/false) and details.
    """
    from authzed.api.v1 import (
        CheckPermissionRequest, CheckPermissionResponse,
        ObjectReference, SubjectReference,
    )

    resp = _spicedb_client.CheckPermission(
        CheckPermissionRequest(
            resource=ObjectReference(object_type="dataset", object_id=resource_id),
            permission=permission,
            subject=SubjectReference(
                object=ObjectReference(object_type="user", object_id=subject_id)
            ),
        )
    )
    allowed = resp.permissionship == CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION

    return json.dumps({
        "allowed": allowed,
        "subject": f"user:{subject_id}",
        "resource": f"dataset:{resource_id}",
        "permission": permission,
    })
