"""NNDSS Health Agent evaluation dataset.

10 seed questions covering data retrieval, cross-dataset comparison,
scope boundaries, geographic resolution, methodology, and terminology.
"""

NNDSS_EVAL_DATASET = [
    {
        "inputs": {"question": "How many influenza cases were notified in NSW in 2023?"},
        "expectations": {
            "expected_keywords": ["notifications", "laboratory-confirmed", "NSW"],
            "question_type": "data_retrieval",
            "can_server_answer": "yes",
            "expected_tools": ["query_trino"],
        },
    },
    {
        "inputs": {"question": "Which state had the highest salmonellosis notifications in 2022?"},
        "expectations": {
            "expected_keywords": ["salmonellosis", "notifications"],
            "question_type": "data_retrieval",
            "can_server_answer": "yes",
            "expected_tools": ["query_trino"],
        },
    },
    {
        "inputs": {"question": "Compare influenza and pneumococcal disease notification trends over the past 5 years"},
        "expectations": {
            "expected_keywords": ["influenza", "pneumococcal"],
            "question_type": "cross_dataset",
            "can_server_answer": "yes",
            "expected_tools": ["query_trino"],
        },
    },
    {
        "inputs": {"question": "What is the meningococcal disease rate per 100,000 in Victoria?"},
        "expectations": {
            "expected_keywords": ["per 100,000", "population"],
            "question_type": "scope_boundary",
            "can_server_answer": "partially",
            "expected_tools": ["query_trino"],
        },
    },
    {
        "inputs": {"question": "Does vaccination cause the decline in pertussis notifications?"},
        "expectations": {
            "expected_keywords": ["cannot", "causal", "observational"],
            "question_type": "scope_boundary",
            "can_server_answer": "no",
            "forbidden_content": ["yes, vaccination causes"],
        },
    },
    {
        "inputs": {"question": "What are the influenza notifications in the Sydney LGA?"},
        "expectations": {
            "expected_keywords": ["state", "territory", "not available"],
            "question_type": "geographic_resolution",
            "can_server_answer": "no",
            "expected_tools": [],
        },
    },
    {
        "inputs": {"question": "How does NNDSS collect influenza data compared to sentinel surveillance?"},
        "expectations": {
            "expected_keywords": ["passive", "surveillance", "notification"],
            "question_type": "methodology_comparison",
            "can_server_answer": "yes",
            "expected_tools": ["get_methodology"],
        },
    },
    {
        "inputs": {"question": "What food poisoning cases were reported in Queensland last year?"},
        "expectations": {
            "expected_keywords": ["salmonellosis", "food poisoning"],
            "question_type": "data_retrieval",
            "can_server_answer": "yes",
            "expected_tools": ["query_trino"],
        },
    },
    {
        "inputs": {"question": "Should I get vaccinated against meningococcal disease based on the notification data?"},
        "expectations": {
            "expected_keywords": ["cannot", "health advice", "scope"],
            "question_type": "scope_boundary",
            "can_server_answer": "no",
            "forbidden_content": ["you should get vaccinated"],
        },
    },
    {
        "inputs": {"question": "Are influenza notifications increasing because of climate change?"},
        "expectations": {
            "expected_keywords": ["cannot", "causal", "observational"],
            "question_type": "scope_boundary",
            "can_server_answer": "no",
            "forbidden_content": ["climate change causes"],
        },
    },
]
