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
ers.http — thin Pure1 REST client (get/patch/post) and a generic
poll-until-terminal-state helper shared by group/plan monitoring.

Request failures raise ApiError rather than exiting the process, so a
caller — the CLI, a script, or the system test runner — can decide how to
handle them (print-and-exit for the CLI; report-and-continue for the test
runner, which needs one failing API call to fail just that test, not kill
the whole suite).

Set ERS_DEBUG=1 to print every outgoing request (method, URL, params,
body) and the raw response to stderr — useful when the API rejects a
request with a generic error like "Failed to read HTTP message" and you
need to see exactly what was sent, e.g.:

    ERS_DEBUG=1 ./ers_cli.py --policy create --name x --rpo 15 \\
        --target-type vmw --local-retention 24 --remote-retention 72
"""

import json
import os
import sys
import time
import datetime

try:
    import requests
except ImportError:
    print("Missing dependency. Install it with:")
    print("    pip install requests")
    sys.exit(1)

TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED", "COMPLETED"}


def _debug_enabled() -> bool:
    return os.environ.get("ERS_DEBUG", "").lower() in ("1", "true", "yes")


def _debug_request(method: str, url: str, params: dict, body):
    if not _debug_enabled():
        return
    print(f"\n[ERS_DEBUG] --> {method} {url}", file=sys.stderr)
    if params:
        print(f"[ERS_DEBUG] params: {params}", file=sys.stderr)
    if body is not None:
        print(f"[ERS_DEBUG] body:\n{json.dumps(body, indent=2)}", file=sys.stderr)


def _debug_response(response):
    if not _debug_enabled():
        return
    print(f"[ERS_DEBUG] <-- {response.status_code}", file=sys.stderr)
    if response.text:
        print(f"[ERS_DEBUG] response body: {response.text}", file=sys.stderr)


class ApiError(Exception):
    """Raised on any Pure1 API request failure (HTTP error or connection failure)."""
    pass


class ApiClient:
    def __init__(self, base_url: str, bearer_token: str):
        self.base_url     = base_url
        self.bearer_token = bearer_token

    def _headers(self, extra: dict = None) -> dict:
        headers = {"accept": "application/json", "Authorization": f"Bearer {self.bearer_token}"}
        if extra:
            headers.update(extra)
        return headers

    def get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        _debug_request("GET", url, params, None)
        try:
            response = requests.get(url, headers=self._headers(), params=params)
            _debug_response(response)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError:
            raise ApiError(f"HTTP error {response.status_code}: {response.text}")
        except requests.ConnectionError:
            raise ApiError(f"Could not connect to {self.base_url}")

    def post(self, path: str, params: dict = None, body: dict = None) -> dict:
        return self.post_absolute(f"{self.base_url}{path}", params=params, body=body)

    def post_absolute(self, url: str, params: dict = None, body: dict = None) -> dict:
        """Like post(), but takes a full URL instead of a path relative to
        self.base_url — for endpoints that live on a different host
        entirely (e.g. the draas-api create endpoint vs. the pure-protect
        automation API everything else in this SDK uses)."""
        _debug_request("POST", url, params, body or {})
        try:
            response = requests.post(url, headers=self._headers({"Content-Type": "application/json"}),
                                      params=params, json=body or {})
            _debug_response(response)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.HTTPError:
            raise ApiError(f"HTTP error {response.status_code}: {response.text}")
        except requests.ConnectionError:
            raise ApiError(f"Could not connect to {url}")

    def patch(self, path: str, params: dict = None, body: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        _debug_request("PATCH", url, params, body)
        try:
            response = requests.patch(url, headers=self._headers({"Content-Type": "application/json"}),
                                       params=params, json=body)
            _debug_response(response)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.HTTPError:
            raise ApiError(f"HTTP error {response.status_code}: {response.text}")
        except requests.ConnectionError:
            raise ApiError(f"Could not connect to {self.base_url}")

    def delete(self, path: str, params: dict = None) -> dict:
        """DELETE — takes query params (e.g. deployment_id, ids), no body,
        matching this API's delete convention (?deployment_id=...&ids=...)."""
        url = f"{self.base_url}{path}"
        _debug_request("DELETE", url, params, None)
        try:
            response = requests.delete(url, headers=self._headers(), params=params)
            _debug_response(response)
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.HTTPError:
            raise ApiError(f"HTTP error {response.status_code}: {response.text}")
        except requests.ConnectionError:
            raise ApiError(f"Could not connect to {self.base_url}")


def poll_until_terminal(api: ApiClient, deployment_id: str, path: str, op_id: str,
                         label: str, interval: int, max_polls: int,
                         extra_params: dict = None, out=print) -> str:
    """Poll an operation endpoint until it reaches a terminal state. Returns final status."""
    params = {"offset": 0, "limit": 1, "deployment_id": deployment_id, "ids": op_id}
    if extra_params:
        params.update(extra_params)

    out(f"\n  Polling [{label}] op_id: {op_id}")
    out(f"  {'Poll':<6} {'Status':<16} {'Finished'}")
    out("  " + "-" * 50)

    for poll in range(1, max_polls + 1):
        result   = api.get(path, params=params)
        op_items = result.get("items", [])
        op       = op_items[0] if op_items else {}

        status      = op.get("status", "UNKNOWN")
        finished_ms = op.get("finished_at")
        finished_str = "-"
        if finished_ms:
            finished_str = datetime.datetime.fromtimestamp(
                finished_ms / 1000, datetime.timezone.utc).strftime("%H:%M:%S UTC")

        if status in TERMINAL_STATES:
            icon = "✓" if status in ("SUCCEEDED", "COMPLETED") else "✗"
            out(f"  {poll:<6} {icon} {status:<14} {finished_str}")
            return status

        out(f"  {poll:<6} … {status:<14} {finished_str}")

        if poll < max_polls:
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                out("\n  Monitoring interrupted.")
                return "INTERRUPTED"

    out(f"  Max polls ({max_polls}) reached without terminal state.")
    return "TIMEOUT"
