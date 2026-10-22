#!/bin/sh
# Regenerate src/lib/api/schema.d.ts from the platform API's OpenAPI schema.
# The schema comes from the FastAPI app factory, so no server or database is needed.
set -eu
web=$(cd "$(dirname "$0")/.." && pwd)
root=$(cd "$web/../.." && pwd)
cd "$root"
uv run --package robomcp-platform python -c \
  "import json; from robomcp_platform.api.app import create_app; print(json.dumps(create_app().openapi(), indent=2, sort_keys=True))" \
  > "$web/src/lib/api/openapi.json"
cd "$web"
npx openapi-typescript src/lib/api/openapi.json -o src/lib/api/schema.d.ts
