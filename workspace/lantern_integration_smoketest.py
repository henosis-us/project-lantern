"""Lantern integration smoke test (Identity + Media claim token).

This script is meant to be a fast validation tool for local dev setup.

It runs both FastAPI apps in-process using TestClient and validates that:

1) Identity service can start against Postgres
2) Media server can start against SQLite
3) Media server can request a claim token from Identity

Because Identity and Media share module names (e.g. both have a top-level
`database.py`), this script carefully isolates imports to avoid collisions.

Usage (from `project-lantern/`):

    python workspace\\lantern_integration_smoketest.py

Environment:

- DATABASE_URL: Postgres URL for identity service (defaults to local 5432)
"""

import os
import sys
import importlib.util
import argparse
from urllib.parse import urlparse
from unittest.mock import patch

from fastapi.testclient import TestClient


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IDENTITY_DIR = os.path.join(PROJECT_ROOT, "identity-service")
MEDIA_DIR = PROJECT_ROOT


def load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


# --- Identity Service (real Postgres) ---
DEFAULT_DATABASE_URL = "postgresql://lantern:lantern@localhost:5432/lantern_identity"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Lantern integration smoke test (Identity + Media claim token)."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        help=(
            "Postgres connection string for the Identity service. "
            f"Default: {DEFAULT_DATABASE_URL}"
        ),
    )
    return parser.parse_args()


args = _parse_args()
os.environ["DATABASE_URL"] = args.database_url
os.environ.setdefault("IDENTITY_PUBLIC_URL", "http://localhost:8001")

# make identity-service importable for its relative imports (auth/models/database)
sys.path.insert(0, IDENTITY_DIR)
identity_mod = load_module('lantern_identity_main', os.path.join(IDENTITY_DIR, 'main.py'))

with TestClient(identity_mod.app) as identity_client:
    r = identity_client.get('/openapi.json')
    print('[identity] openapi', r.status_code, 'paths', len(r.json().get('paths', {})))

    # --- Media Server (SQLite) ---
    dev_data_dir = os.path.join(PROJECT_ROOT, "workspace", "dev_data")
    os.makedirs(dev_data_dir, exist_ok=True)

    os.environ.setdefault("DATABASE_PATH", os.path.join(dev_data_dir, "lantern_media_test.db"))
    os.environ.setdefault("LMS_PUBLIC_URL", "http://localhost:8000")
    os.environ.setdefault("IDENTITY_SERVICE_URL", "http://localhost:8001")

    # IMPORTANT: avoid module-name collisions between identity-service/ and media-server/.
    # Both have top-level modules named e.g. "database.py".
    # When running as real services, they're in separate processes so it's fine.
    # For this in-process smoke test, ensure the media-server folder wins module resolution.
    sys.path = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(IDENTITY_DIR)]
    sys.path.insert(0, MEDIA_DIR)

    # Also drop any already-imported modules that would otherwise be reused by name.
    for mod_name in ("database", "auth", "models"):
        sys.modules.pop(mod_name, None)
    media_mod = load_module('lantern_media_main', os.path.join(MEDIA_DIR, 'main.py'))

    class FakeResponse:
        def __init__(self, status_code: int, json_data=None, text: str = ''):
            self.status_code = status_code
            self._json = json_data
            self.text = text
            self.response = None

        def json(self):
            if self._json is None:
                raise ValueError('No json')
            return self._json

        def raise_for_status(self):
            if 400 <= self.status_code:
                raise media_mod.requests.RequestException(self.text, response=self)

    def fake_post(url, json=None, timeout=None, **kwargs):
        parsed = urlparse(url)
        path = parsed.path

        if path == '/servers/generate-claim-token':
            resp = identity_client.post('/servers/generate-claim-token', json=json)
            return FakeResponse(resp.status_code, json_data=resp.json(), text=resp.text)

        if path == '/servers/heartbeat':
            resp = identity_client.post('/servers/heartbeat', json=json)
            return FakeResponse(resp.status_code, json_data=None, text=resp.text)

        return FakeResponse(500, json_data=None, text=f'Unhandled POST {url}')

    with patch.object(media_mod.requests, 'post', side_effect=fake_post):
        with TestClient(media_mod.app) as media_client:
            r = media_client.get('/')
            print('[media] root', r.status_code, r.json())

            r = media_client.get('/server/claim-info')
            print('[media] claim-info', r.status_code, r.text)

            if r.status_code != 200:
                raise SystemExit(1)

    print('OK: identity + media server booted and claim token flow succeeded (via mocked HTTP to identity).')
