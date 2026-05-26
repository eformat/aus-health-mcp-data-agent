#!/usr/bin/env python3
"""Standalone test: LangChain SpiceDB permission tool integration.

Run with port-forward active:
  oc port-forward -n nndss-agent svc/dev 50051:50051 &
  python3 agents/nndss-agent/spicedb/test_langchain_integration.py

Tests the SpiceDBAuthorizer and the check_dataset_permission @tool wrapper
without the full agent.
"""

import asyncio
import json
import os
import sys

from langchain_spicedb.core import SpiceDBAuthorizer

SPICEDB_ENDPOINT = os.environ.get("SPICEDB_ENDPOINT", "localhost:50051")
SPICEDB_TOKEN = os.environ.get("SPICEDB_TOKEN", "averysecretpresharedkey")


async def test_authorizer_direct():
    """Test SpiceDBAuthorizer.check_permission directly."""
    print("=== Test 1: SpiceDBAuthorizer direct ===")

    authorizer = SpiceDBAuthorizer(
        spicedb_endpoint=SPICEDB_ENDPOINT,
        spicedb_token=SPICEDB_TOKEN,
        subject_type="user",
        resource_type="dataset",
    )

    test_cases = [
        ("admin", "notifications", "query", True),
        ("admin", "fortnightly_notifications", "query", True),
        ("admin", "population", "query", True),
        ("admin", "notifications", "export", True),
        ("viewer", "notifications", "query", False),
        ("viewer", "notifications", "view_metadata", True),
        ("viewer", "notifications", "export", False),
    ]

    passed = 0
    for subject_id, resource_id, permission, expected in test_cases:
        result = await authorizer.check_permission(
            subject_id=subject_id,
            resource_id=resource_id,
            permission=permission,
        )
        status = "PASS" if result == expected else "FAIL"
        if result == expected:
            passed += 1
        print(f"  {status}  user:{subject_id} {permission} dataset:{resource_id} => {result} (expected {expected})")

    print(f"\n{passed}/{len(test_cases)} passed\n")
    return passed == len(test_cases)


def test_tool_wrapper():
    """Test the @tool wrapper from tools.py."""
    print("=== Test 2: @tool wrapper (check_dataset_permission) ===")

    os.environ["SPICEDB_ENDPOINT"] = SPICEDB_ENDPOINT
    os.environ["SPICEDB_TOKEN"] = SPICEDB_TOKEN

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from tools import check_dataset_permission

    test_cases = [
        ("admin", "notifications", "query", True),
        ("viewer", "notifications", "query", False),
        ("viewer", "notifications", "view_metadata", True),
    ]

    passed = 0
    for subject_id, resource_id, permission, expected in test_cases:
        result_json = check_dataset_permission.invoke({
            "subject_id": subject_id,
            "resource_id": resource_id,
            "permission": permission,
        })
        result = json.loads(result_json)
        status = "PASS" if result["allowed"] == expected else "FAIL"
        if result["allowed"] == expected:
            passed += 1
        print(f"  {status}  {result['subject']} {result['permission']} {result['resource']} => {result['allowed']} (expected {expected})")

    print(f"\n{passed}/{len(test_cases)} passed\n")
    return passed == len(test_cases)


async def main():
    ok1 = await test_authorizer_direct()
    ok2 = test_tool_wrapper()

    if ok1 and ok2:
        print("All tests passed.")
    else:
        print("Some tests FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
