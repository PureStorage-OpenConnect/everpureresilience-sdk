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
system_tests.level1_list — read-only: confirms the ERS SDK can reach Pure1
and that the group/plan/site names in your test config actually exist.
Nothing here changes any state. Safe to run at any time, no confirmation
required.
"""

from .runner import TestCase


def test_list_policies(e, cfg):
    items = e.policy.list()
    assert isinstance(items, list), "policy.list() did not return a list"


def test_list_sites(e, cfg):
    items = e.site.list()
    assert isinstance(items, list), "site.list() did not return a list"


def test_list_groups(e, cfg):
    items = e.group.list(*cfg["group_names"], details=True)
    found = {g.get("name") for g in items}
    missing = set(cfg["group_names"]) - found
    assert not missing, f"groups not found in Pure1: {sorted(missing)}"


def test_list_plans(e, cfg):
    items = e.plan.list(*cfg["plan_names"], details=True)
    found = {p.get("name") for p in items}
    missing = set(cfg["plan_names"]) - found
    assert not missing, f"plans not found in Pure1: {sorted(missing)}"


def test_list_snapshots(e, cfg):
    # informational only — doesn't assert snapshots exist, since a brand new
    # plan may not have run yet; just confirms the call succeeds.
    e.plan.snapshots(*cfg["plan_names"])


TESTS = [
    TestCase("list_policies", 1, test_list_policies),
    TestCase("list_sites", 1, test_list_sites),
    TestCase("list_groups", 1, test_list_groups),
    TestCase("list_plans", 1, test_list_plans),
    TestCase("list_snapshots", 1, test_list_snapshots),
]
