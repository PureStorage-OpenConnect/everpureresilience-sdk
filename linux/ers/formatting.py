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
ers.formatting — per-instance output handling (replaces the global OUTPUT_FORMAT /
_json_output state from the old ers-cli.py) plus the txt pretty-printers for
each resource type.
"""

import json


class Output:
    """Accumulates output for one ErsInstance. format is 'txt' or 'json'."""

    def __init__(self, fmt: str = "txt"):
        self.format = fmt
        self._json  = {}

    def out(self, msg: str = ""):
        if self.format == "txt":
            print(msg, flush=True)

    def out_json(self, key: str, value):
        self._json[key] = value

    def flush_json(self):
        if self.format == "json":
            print(json.dumps(self._json, indent=2, default=str))
        self._json = {}


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

def print_policies_summary(items: list):
    print(f"\n  {'ID':<38} {'Name':<25} {'Groups':<8} {'RPO':<12}")
    print("  " + "-" * 85)
    for p in items:
        rpo_hrs = p.get("rpo", 0) / 3600000
        print(f"  {p.get('id', '-'):<38} {p.get('name', '-'):<25} "
              f"{p.get('group_count', 0):<8} {rpo_hrs:.0f}h")


def print_policies_detailed(items: list):
    def ms_to_human(ms):
        if ms is None:
            return "-"
        hours = ms // 3600000
        return f"{hours // 24}d" if hours >= 24 else f"{hours}h"

    for i, policy in enumerate(items, 1):
        print(f"\n{'='*60}\n  Policy {i}: {policy.get('name', '-')}\n{'='*60}")
        print(f"  {'ID':<22}: {policy.get('id', '-')}")
        print(f"  {'Description':<22}: {policy.get('description', '-')}")
        print(f"  {'Groups Using Policy':<22}: {policy.get('group_count', 0)}")
        print(f"  {'RPO':<22}: {ms_to_human(policy.get('rpo'))}")
        strategy = policy.get("replication_strategy", {})
        if strategy:
            print(f"\n  Replication Strategy:")
            print(f"    {'Source Site Type':<22}: {strategy.get('site_type', '-')}")
            print(f"    {'Retention':<22}: {ms_to_human(strategy.get('retention'))}")
            for t in strategy.get("replication_targets", []):
                print(f"      - Site Type     : {t.get('site_type', '-')}")
                print(f"        Retention     : {ms_to_human(t.get('retention'))}")
                print(f"        Estimated RTO : {ms_to_human(t.get('estimated_rto'))}")


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

def print_groups_summary(items: list):
    print(f"\n{'ID':<40} {'Name':<30} {'Protection State':<18}")
    print("-" * 90)
    for g in items:
        print(f"{g.get('id', '-'):<40} {g.get('name', '-'):<30} {g.get('protection_state', '-'):<18}")


def print_groups_detailed(items: list):
    for i, group in enumerate(items, 1):
        state = group.get("protection_state", "-")
        icon  = "✓" if state == "ENABLED" else "✗"
        print(f"\n{'='*60}\n  Group {i}: {group.get('name', '-')}  [{icon} {state}]\n{'='*60}")
        print(f"  {'ID':<26}: {group.get('id', '-')}")
        print(f"  {'Description':<26}: {group.get('description', '-')}")
        print(f"  {'Protection State':<26}: {state}")
        backup_ms = group.get("backup_start_time")
        if backup_ms is not None:
            total_seconds = backup_ms // 1000
            hours, remainder = divmod(total_seconds, 3600)
            minutes = remainder // 60
            print(f"  {'Backup Start Time':<26}: {hours:02d}:{minutes:02d} UTC")
        print(f"  {'Parallel Boot':<26}: {group.get('has_parallel_boot', False)}")
        print(f"  {'Cloud Pre-Conversion':<26}: {group.get('has_cloud_pre_conversion', False)}")
        print(f"  {'Infrastructure Group':<26}: {group.get('is_infrastructure_group', False)}")
        print(f"  {'Consistency Group':<26}: {group.get('is_consistency_group', False)}")
        print(f"  {'In Failover':<26}: {group.get('is_in_failover', False)}")
        print(f"  {'Protection Triggerable':<26}: {group.get('is_protection_triggerable', False)}")
        policy = group.get("service_level_policy", {})
        if policy:
            print(f"  {'Service Level Policy':<26}: {policy.get('name', '-')}  (id: {policy.get('id', '-')})")
        source = group.get("source_site", {})
        if source:
            print(f"  {'Source Site':<26}: id: {source.get('id', '-')}")
        targets = group.get("target_sites", [])
        if targets:
            print(f"  {'Target Sites':<26}:")
            for t in targets:
                print(f"    - id: {t.get('id', '-')}")
        vms = group.get("enrolled_virtual_machines", [])
        if vms:
            print(f"  {'Enrolled VMs':<26}: {len(vms)} enrolled")
            for vm in vms:
                print(f"    - id: {vm.get('id', '-')}")


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def print_plans_summary(items: list):
    print(f"\n  {'ID':<38} {'Name':<28} {'Plan State':<24} {'Recovery State':<16} {'Failback'}")
    print("  " + "-" * 115)
    for p in items:
        failback = "✓" if p.get("is_failback_triggerable") else "✗"
        print(f"  {p.get('id', '-'):<38} {p.get('name', '-'):<28} "
              f"{p.get('plan_state', '-'):<24} {p.get('recovery_state', '-'):<16} {failback}")


def print_plans_detailed(items: list):
    for i, plan in enumerate(items, 1):
        recovery_state = plan.get("recovery_state", "-")
        icon = "✓" if recovery_state == "HEALTHY" else "✗"
        print(f"\n{'='*60}\n  Plan {i}: {plan.get('name', '-')}  [{icon} {recovery_state}]\n{'='*60}")
        print(f"  {'ID':<26}: {plan.get('id', '-')}")
        print(f"  {'Description':<26}: {plan.get('description', '-')}")
        print(f"  {'Plan State':<26}: {plan.get('plan_state', '-')}")
        print(f"  {'Recovery State':<26}: {recovery_state}")
        print(f"  {'Failback Triggerable':<26}: {'Yes' if plan.get('is_failback_triggerable') else 'No'}")
        target = plan.get("target_site", {})
        if target:
            print(f"  {'Target Site':<26}: id: {target.get('id', '-')}")
        groups = plan.get("groups", [])
        if groups:
            print(f"  {'Groups':<26}: {len(groups)} assigned")
            for g in groups:
                print(f"    - id: {g.get('id', '-')}")
        else:
            print(f"  {'Groups':<26}: none assigned")


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

def print_sites_summary(items: list):
    print(f"\n{'ID':<40} {'Name':<20} {'Type':<10} {'Status':<12}")
    print("-" * 84)
    for site in items:
        print(f"{site.get('id', '-'):<40} {site.get('name', '-'):<20} "
              f"{site.get('type', '-'):<10} {site.get('status', '-'):<12}")


def print_sites_detailed(items: list):
    import datetime
    for i, site in enumerate(items, 1):
        status = site.get("status", "-")
        icon = "✓" if status == "HEALTHY" else "✗"
        print(f"\n{'='*60}\n  Site {i}: {site.get('name', '-')}  [{icon} {status}]\n{'='*60}")
        print(f"  {'ID':<18}: {site.get('id', '-')}")
        print(f"  {'Type':<18}: {site.get('type', '-')}")
        print(f"  {'Status':<18}: {status}")
        updated_ms = site.get("updated_at")
        if updated_ms:
            updated_str = datetime.datetime.fromtimestamp(
                updated_ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"  {'Last Updated':<18}: {updated_str}")
        if site.get("instance_type"):
            print(f"  {'Instance Type':<18}: {site.get('instance_type')}")
        if site.get("region"):
            print(f"  {'Region':<18}: {site.get('region')}")
        if site.get("storage_quota"):
            quota_gib = site["storage_quota"] / (1024 ** 3)
            print(f"  {'Storage Quota':<18}: {quota_gib:.0f} GiB")
        flash_arrays = site.get("flash_arrays", [])
        if flash_arrays:
            print(f"  {'Flash Arrays':<18}:")
            for fa in flash_arrays:
                print(f"    - {fa.get('name', '-')}  (id: {fa.get('id', '-')})")


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def print_snapshots(plan_name: str, plan_id: str, items: list, total: int, out):
    import datetime
    out(f"\n{'='*70}")
    out(f"  Plan : {plan_name}  (id: {plan_id})")
    out(f"  Total snapshots: {total}")
    out(f"{'='*70}")
    if not items:
        out("  No snapshots found.")
        return
    out(f"\n  {'Snapshot ID':<38} {'Group':<28} {'Created':<22} {'VMs (protected/total)'}")
    out("  " + "-" * 100)
    for snap in items:
        group = snap.get("application_group", {})
        created_ms = snap.get("created_at")
        created_str = "-"
        if created_ms:
            created_str = datetime.datetime.fromtimestamp(
                created_ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        out(f"  {snap.get('id', '-'):<38} {group.get('name', '-'):<28} {created_str:<22} "
            f"{snap.get('protected_vm_count', '-')}/{snap.get('total_vm_count', '-')}")
