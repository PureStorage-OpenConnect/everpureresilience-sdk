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
system_tests.config — loads system-test-config.json, the input that drives
the whole system test suite: which sites, groups, plans, and VM list to use.

    {
      "schema_version": 1,
      "profile": "default",
      "source_site": "prod-dc",
      "target_site": "dr-dc",
      "failback_site": "prod-dc",
      "group_names": ["G1", "G2"],
      "plan_names": ["P1", "P2"],
      "vms_file": "vm-list.json",
      "with_network": true,
      "with_tags": true,
      "create_missing_tags": false,
      "interval": 10,
      "max_polls": 30
    }

`failback_site` defaults to `source_site` if omitted (the common case:
fail over to the DR site, then fail back to where you started).
"""

import json
import os
import sys

DEFAULT_TEST_CONFIG_PATH = "system-test-config.json"
SUPPORTED_SCHEMA_VERSIONS = (1,)

REQUIRED_FIELDS = ["source_site", "target_site", "group_names", "plan_names", "vms_file"]


def load_test_config(path: str = None) -> dict:
    path = path or DEFAULT_TEST_CONFIG_PATH
    if not os.path.exists(path):
        print(f"Error: system test config not found: {path}")
        print("Copy system-test-config.example.json to system-test-config.json "
              "and fill in your site/group/plan names.")
        sys.exit(1)

    with open(path, "r") as f:
        cfg = json.load(f)

    version = cfg.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        print(f"Error: {path} has unsupported schema_version {version!r} "
              f"(supported: {SUPPORTED_SCHEMA_VERSIONS})")
        sys.exit(1)

    missing = [k for k in REQUIRED_FIELDS if not cfg.get(k)]
    if missing:
        print(f"Error: {path} is missing required fields: {', '.join(missing)}")
        sys.exit(1)

    cfg.setdefault("profile", "default")
    cfg.setdefault("failback_site", cfg["source_site"])
    cfg.setdefault("with_network", True)
    cfg.setdefault("with_tags", True)
    cfg.setdefault("create_missing_tags", False)
    cfg.setdefault("interval", 10)
    cfg.setdefault("max_polls", 30)

    return cfg
