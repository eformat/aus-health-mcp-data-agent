#!/usr/bin/env python3
"""Write SpiceDB schema and seed initial relationships for NNDSS health agent."""

import os
import sys
from pathlib import Path

from authzed.api.v1 import (
    Client,
    ObjectReference,
    Relationship,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
    WriteSchemaRequest,
)
from grpcutil import insecure_bearer_token_credentials

SPICEDB_ENDPOINT = os.environ.get("SPICEDB_ENDPOINT", "localhost:50051")
SPICEDB_TOKEN = os.environ.get("SPICEDB_TOKEN", "averysecretpresharedkey")

SCHEMA_PATH = Path(__file__).parent / "schema.zed"

DATASETS = ["notifications", "fortnightly_notifications", "population"]

SEED_RELATIONSHIPS = [
    # Organization
    ("organization", "nndss", "member", "user", "admin"),
    ("organization", "nndss", "admin", "user", "admin"),
    ("organization", "nndss", "member", "user", "viewer"),
    # admin user: analyst on all datasets
    ("dataset", "notifications", "analyst", "user", "admin"),
    ("dataset", "fortnightly_notifications", "analyst", "user", "admin"),
    ("dataset", "population", "analyst", "user", "admin"),
    # viewer user: viewer on all datasets (can see metadata, cannot query)
    ("dataset", "notifications", "viewer", "user", "viewer"),
    ("dataset", "fortnightly_notifications", "viewer", "user", "viewer"),
    ("dataset", "population", "viewer", "user", "viewer"),
    # All datasets owned by nndss org
    ("dataset", "notifications", "owner", "organization", "nndss"),
    ("dataset", "fortnightly_notifications", "owner", "organization", "nndss"),
    ("dataset", "population", "owner", "organization", "nndss"),
    # Org admins are dataset admins (grants export permission)
    ("dataset", "notifications", "admin", "organization", "nndss#admin"),
    ("dataset", "fortnightly_notifications", "admin", "organization", "nndss#admin"),
    ("dataset", "population", "admin", "organization", "nndss#admin"),
]


def main():
    client = Client(
        SPICEDB_ENDPOINT,
        insecure_bearer_token_credentials(SPICEDB_TOKEN),
    )

    schema = SCHEMA_PATH.read_text()
    print(f"Writing schema from {SCHEMA_PATH}...")
    client.WriteSchema(WriteSchemaRequest(schema=schema))
    print("Schema written.")

    updates = []
    for res_type, res_id, relation, sub_type, sub_id in SEED_RELATIONSHIPS:
        # Handle subject relations like "nndss#admin"
        sub_relation = ""
        if "#" in sub_id:
            sub_id, sub_relation = sub_id.split("#", 1)

        subject = SubjectReference(
            object=ObjectReference(object_type=sub_type, object_id=sub_id)
        )
        if sub_relation:
            subject.optional_relation = sub_relation

        updates.append(
            RelationshipUpdate(
                operation=RelationshipUpdate.Operation.OPERATION_TOUCH,
                relationship=Relationship(
                    resource=ObjectReference(object_type=res_type, object_id=res_id),
                    relation=relation,
                    subject=subject,
                ),
            )
        )

    print(f"Writing {len(updates)} relationships...")
    resp = client.WriteRelationships(WriteRelationshipsRequest(updates=updates))
    print(f"Relationships written. ZedToken: {resp.written_at.token}")


if __name__ == "__main__":
    main()
