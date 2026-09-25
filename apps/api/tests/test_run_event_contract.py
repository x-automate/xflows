"""Pin every declaration of the run-event enum to the API's own.

The enum is written out in four places (the API models, the published JSON
Schema, the TypeScript types, and the web SSE subscription list) and they had
drifted to four different lengths: the API emitted ten types, the schema
declared eight, the TS types six, and the browser subscribed to six. A real
``node_skipped`` event failed validation against its own published schema and
never reached the UI at all.

The web side is pinned by apps/web/src/lib/api/workflowApi.test.js.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from app.models import InternalRunEventRequest, RunEvent

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_DIR = REPO_ROOT / "packages" / "workflow-spec"


def _literal_values(annotation) -> list[str]:
    return list(annotation.__args__)


class RunEventContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api_types = _literal_values(RunEvent.model_fields["type"].annotation)

    def test_api_declares_every_emitted_type(self) -> None:
        # Nothing may be emitted internally that the public event cannot carry.
        internal = set(_literal_values(InternalRunEventRequest.model_fields["type"].annotation))
        self.assertEqual(internal, set(self.api_types))

    def test_json_schema_enum_matches_api(self) -> None:
        schema = json.loads((SPEC_DIR / "run-events.schema.json").read_text())
        self.assertEqual(schema["properties"]["type"]["enum"], self.api_types)

    def test_typescript_union_matches_api(self) -> None:
        source = (SPEC_DIR / "src" / "types.ts").read_text()
        block = re.search(r"export interface RunEvent \{.*?type:(.*?);", source, re.S)
        self.assertIsNotNone(block, "RunEvent.type union not found in types.ts")
        declared = re.findall(r'"([a-z_]+)"', block.group(1))
        self.assertEqual(declared, self.api_types)

    def test_every_type_validates_against_the_published_schema(self) -> None:
        import jsonschema

        schema = json.loads((SPEC_DIR / "run-events.schema.json").read_text())
        for event_type in self.api_types:
            with self.subTest(event_type=event_type):
                jsonschema.validate(
                    {
                        "runId": "run_1",
                        "type": event_type,
                        "timestamp": "2026-01-01T00:00:00Z",
                    },
                    schema,
                )


if __name__ == "__main__":
    unittest.main()
