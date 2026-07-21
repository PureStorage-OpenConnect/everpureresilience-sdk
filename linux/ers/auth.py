# Copyright 2026 [Your Organization]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
ers.auth — RS256 JWT generation and OAuth2 token-exchange for Pure1 bearer tokens.

Replaces the standalone generate_jwt_token.py / get_bearer_token.py scripts —
both steps now happen automatically inside ErsInstance.__init__.
"""

import os
import sys
import time

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None

try:
    import requests
except ImportError:
    print("Missing dependency. Install it with:")
    print("    pip install requests")
    sys.exit(1)

TOKEN_URL_PATH   = "/oauth2/1.0/token"
DEFAULT_JWT_TTL  = 3600  # seconds


def generate_jwt(app_id: str, private_key_path: str, ttl_seconds: int = DEFAULT_JWT_TTL) -> str:
    """Generate a signed RS256 JWT for the given Pure1 API application ID.

    Per Pure1's documented format, the payload is exactly:
        {"iss": app_id, "iat": <ms since epoch>, "exp": <ms since epoch>}
    No "sub" claim, and timestamps are milliseconds, not seconds — Pure1
    will reject the token (often with a confusing "invalid issuer" /
    "On Demand Provisioning is not enabled" error) if either is wrong.
    """
    if pyjwt is None:
        print("Missing dependency. Install it with:")
        print("    pip install PyJWT cryptography")
        sys.exit(1)

    key_path = os.path.expanduser(private_key_path)
    try:
        with open(key_path, "rb") as f:
            private_key = f.read()
    except FileNotFoundError:
        print(f"Error: Private key not found: {key_path}")
        sys.exit(1)

    now_ms = int(time.time() * 1000)
    claims = {
        "iss": app_id,
        "iat": now_ms,
        "exp": now_ms + (ttl_seconds * 1000),
    }

    try:
        return pyjwt.encode(claims, private_key, algorithm="RS256")
    except Exception as e:
        print(f"Error: Could not sign JWT: {e}")
        sys.exit(1)


def load_jwt_file(path: str) -> str:
    path = os.path.expanduser(path)
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"Error: JWT file not found: {path}")
        sys.exit(1)


def exchange_jwt_for_bearer(base_url: str, jwt_token: str) -> str:
    """Exchange a signed JWT for a Pure1 bearer token via the OAuth2 token endpoint."""
    url  = f"{base_url}{TOKEN_URL_PATH}"
    data = {
        "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        "grant_type":         "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token":      jwt_token,
    }
    headers = {
        "accept":       "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
    except requests.HTTPError:
        print(f"Error: Token exchange failed ({response.status_code}): {response.text}")
        sys.exit(1)
    except requests.ConnectionError:
        print(f"Error: Could not connect to {base_url}")
        sys.exit(1)

    payload = response.json()
    token   = payload.get("access_token")
    if not token:
        print(f"Error: No access_token in response: {payload}")
        sys.exit(1)

    return token


def resolve_bearer_token(config: dict, creds: dict) -> str:
    """
    Resolve a Pure1 bearer token using, in priority order:
      1. an explicit bearer_token in credentials
      2. a jwt_file in credentials, exchanged for a bearer token
      3. app_id + private_key_path in credentials — generate the JWT, then exchange it
    """
    if creds.get("bearer_token"):
        return creds["bearer_token"]

    if creds.get("jwt_file"):
        jwt_token = load_jwt_file(creds["jwt_file"])
        return exchange_jwt_for_bearer(config["base_url"], jwt_token)

    if creds.get("app_id") and creds.get("private_key_path"):
        jwt_token = generate_jwt(creds["app_id"], creds["private_key_path"])
        return exchange_jwt_for_bearer(config["base_url"], jwt_token)

    print("Error: No usable auth material in ~/.ers/credentials [ers] section.")
    print("Provide one of: bearer_token, jwt_file, or app_id + private_key_path.")
    sys.exit(1)
