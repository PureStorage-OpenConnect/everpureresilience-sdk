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
system_tests.level2_operations — real operations against your Pure1
deployment and registered vCenter sites: group protection runs, plan
failover/cleanup/failback, VM power, network reconnection, and tag
export/apply. These change real state.

`plan_prod_failover` and `plan_failback` are marked dangerous=True — they
run an actual production failover / failback, not a simulation. The CLI
runner requires an extra confirmation for anything dangerous, on top of
the standard --yes gate for level 2/3 as a whole.
"""

from .runner import TestCase


def test_group_protection_run(e, cfg):
    op_map = e.group.run(*cfg["group_names"])
    assert op_map, "group.run() returned no operations"
    states = e.group.monitor(*cfg["group_names"], interval=cfg["interval"], max_polls=cfg["max_polls"])
    failed = [name for name, s in states.items() if s.get("status") != "SUCCEEDED"]
    assert not failed, f"group protection run did not succeed for: {failed}"


def test_plan_test_failover(e, cfg):
    results = e.plan.failover("test", *cfg["plan_names"], interval=cfg["interval"], max_polls=cfg["max_polls"])
    failed = [r["plan"] for r in results if r.get("status") != "SUCCEEDED"]
    assert not failed, f"test failover did not succeed for: {failed}"


def test_plan_cleanup(e, cfg):
    results = e.plan.cleanup(*cfg["plan_names"], interval=cfg["interval"], max_polls=cfg["max_polls"])
    failed = [r["plan"] for r in results if r.get("status") != "SUCCEEDED"]
    assert not failed, f"cleanup did not succeed for: {failed}"


def test_plan_prod_failover(e, cfg):
    """DANGEROUS: this is a real production failover, not a simulation."""
    results = e.plan.failover("prod", *cfg["plan_names"], interval=cfg["interval"], max_polls=cfg["max_polls"])
    failed = [r["plan"] for r in results if r.get("status") != "SUCCEEDED"]
    assert not failed, f"production failover did not succeed for: {failed}"


def test_plan_failback(e, cfg):
    """DANGEROUS: this is a real failback, not a simulation."""
    results = e.plan.failback(*cfg["plan_names"], site=cfg["failback_site"],
                               interval=cfg["interval"], max_polls=cfg["max_polls"])
    failed = [r["plan"] for r in results if r.get("status") != "SUCCEEDED"]
    assert not failed, f"failback did not succeed for: {failed}"


def test_power_off_vms(e, cfg):
    site = e.sites[cfg["source_site"]]
    result = site.power_off(file=cfg["vms_file"])
    assert result, "power_off() reported no VMs succeeded"


def test_power_on_vms(e, cfg):
    site = e.sites[cfg["source_site"]]
    result = site.power_on(file=cfg["vms_file"])
    assert result, "power_on() reported no VMs succeeded"


def test_connect_networks(e, cfg):
    site = e.sites[cfg["target_site"]]
    result = site.connect_networks(file=cfg["vms_file"])
    assert result, "connect_networks() reported no VMs succeeded"


def test_export_import_tags(e, cfg):
    src = e.sites[cfg["source_site"]]
    tgt = e.sites[cfg["target_site"]]
    exported = src.export_tags(file=cfg["vms_file"])
    assert exported is not None, "export_tags() failed"
    result = tgt.apply_tags(file=cfg["vms_file"], source=cfg["source_site"],
                             create_missing=cfg["create_missing_tags"])
    assert result is not None, (
        "apply_tags() failed — check that export_tags() ran against "
        f"'{cfg['source_site']}' immediately before this test"
    )


TESTS = [
    TestCase("group_protection_run", 2, test_group_protection_run),
    TestCase("plan_test_failover", 2, test_plan_test_failover),
    TestCase("plan_cleanup", 2, test_plan_cleanup),
    TestCase("plan_prod_failover", 2, test_plan_prod_failover, dangerous=True),
    TestCase("connect_networks", 2, test_connect_networks),
    TestCase("export_import_tags", 2, test_export_import_tags),
    TestCase("group_protection_run", 2, test_group_protection_run),
    TestCase("plan_failback", 2, test_plan_failback, dangerous=True),
    TestCase("power_off_vms", 2, test_power_off_vms),
    TestCase("power_on_vms", 2, test_power_on_vms),
]
