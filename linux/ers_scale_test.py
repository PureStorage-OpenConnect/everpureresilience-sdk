#!/usr/bin/env python3
# Copyright 2026 Everpure™
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
----------------------------------------------------------------------------
ers-scale-test — scale/load testing for ERS
----------------------------------------------------------------------------
Creates M VMs distributed evenly across N datastores, distributes those
VMs evenly across X application groups, distributes those X groups evenly
across Y recovery plans, then runs protection on every group and test
failover on every plan.

Configurable defaults live in scale-test-config.json (source_site,
target_site, service_level_policy, name prefixes, VM templates) — M/N/X/Y
are passed on the command line each run, since those are what actually
change from one scale test to the next.

Datastores are NOT created — either datastore_name_prefix + N must already
exist on source_site (e.g. datastore_name_prefix="ers-scale-ds-" and N=10
means ers-scale-ds-001 through ers-scale-ds-010 must already exist), or
the config's datastore_names can list specific existing datastores by
name directly — if set, it takes precedence over datastore_name_prefix
entirely, and --datastores is no longer required on the command line
(its count is taken from datastore_names' length instead).

examples:
  ers-scale-test --vms 100 --datastores 10 --groups 4 --plans 2
  ers-scale-test --vms 100 --datastores 5  --groups 10 --plans 1
  ers-scale-test --vms 100 --datastores 10 --groups 4 --plans 2 --dry-run
  ers-scale-test --vms 100 --groups 4 --plans 2   # datastore_names configured, --datastores omitted
  ers-scale-test --cleanup
"""

import argparse
import json
import sys
import time
from collections import Counter

import ers
from ers.config import state_path

STATE_FILE = ".last_scale_test.json"
DEFAULT_CONFIG_PATH = "scale-test-config.json"


def load_config(path: str) -> dict:
    try:
        with open(path) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"Error: config file not found: {path}")
        sys.exit(1)

    if cfg.get("schema_version") != 1:
        print(f"Error: {path} has unsupported schema_version (expected 1)")
        sys.exit(1)

    required = ["source_site", "target_site", "service_level_policy"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"Error: {path} is missing required fields: {', '.join(missing)}")
        sys.exit(1)

    cfg.setdefault("profile", "default")
    cfg.setdefault("group_name_prefix", "ers-scale-grp-")
    cfg.setdefault("plan_name_prefix", "ers-scale-plan-")
    cfg.setdefault("vm_name_prefix", "ers-scale-vm-")
    cfg.setdefault("datastore_name_prefix", "ers-scale-ds-")
    cfg.setdefault("datastore_names", None)
    cfg.setdefault("vm_lnx_template", None)
    cfg.setdefault("vm_win_template", None)
    cfg.setdefault("sync_wait_seconds", 60)

    if cfg["datastore_names"] is not None:
        if not isinstance(cfg["datastore_names"], list) or not cfg["datastore_names"]:
            print(f"Error: {path}'s datastore_names must be a non-empty list of names")
            sys.exit(1)

    if not cfg["vm_lnx_template"] and not cfg["vm_win_template"]:
        print(f"Error: {path} needs at least one of vm_lnx_template/vm_win_template")
        sys.exit(1)

    return cfg


def round_robin(count: int, buckets: int) -> list:
    """Returns a list of `count` 0-based bucket indices, assigning items to
    buckets round-robin — as even a split as possible, gracefully handling
    counts that don't divide evenly (off by at most 1 per bucket)."""
    return [i % buckets for i in range(count)]


def save_state(state: dict):
    with open(state_path(STATE_FILE), "w") as f:
        json.dump(state, f, indent=2)


def load_state():
    try:
        with open(state_path(STATE_FILE)) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def build_plan(cfg: dict, m: int, n: int, x: int, y: int) -> dict:
    """Computes every name and distribution up front — used by both the
    real run and --dry-run, so the preview is guaranteed to match what a
    real run would actually do."""
    if cfg.get("datastore_names"):
        ds_names = list(cfg["datastore_names"])
    else:
        ds_names = [f"{cfg['datastore_name_prefix']}{i:03d}" for i in range(1, n + 1)]
    vm_names = [f"{cfg['vm_name_prefix']}{i:03d}" for i in range(1, m + 1)]
    group_names = [f"{cfg['group_name_prefix']}{i:03d}" for i in range(1, x + 1)]
    plan_names = [f"{cfg['plan_name_prefix']}{i:03d}" for i in range(1, y + 1)]

    vm_ds_idx = round_robin(m, len(ds_names))
    vm_group_idx = round_robin(m, x)
    group_plan_idx = round_robin(x, y)

    lnx, win = cfg["vm_lnx_template"], cfg["vm_win_template"]
    if lnx and win:
        half = (m + 1) // 2  # first half (rounded up) gets lnx
        vm_template = [lnx] * half + [win] * (m - half)
    else:
        vm_template = [lnx or win] * m

    group_vms = {g: [] for g in group_names}
    for i, name in enumerate(vm_names):
        group_vms[group_names[vm_group_idx[i]]].append(name)

    plan_groups = {p: [] for p in plan_names}
    for j, name in enumerate(group_names):
        plan_groups[plan_names[group_plan_idx[j]]].append(name)

    return {
        "ds_names": ds_names, "vm_names": vm_names,
        "group_names": group_names, "plan_names": plan_names,
        "vm_datastore": {vm_names[i]: ds_names[vm_ds_idx[i]] for i in range(m)},
        "vm_template": {vm_names[i]: vm_template[i] for i in range(m)},
        "group_vms": group_vms, "plan_groups": plan_groups,
    }


def print_dry_run(cfg: dict, plan: dict, m: int, n: int, x: int, y: int):
    print(f"\n  VMs to create: {m}, using templates: "
          f"{Counter(plan['vm_template'].values())}")
    print(f"  VM -> datastore distribution: "
          f"{dict(Counter(plan['vm_datastore'].values()))}")
    print(f"  VM -> group distribution: "
          f"{ {g: len(v) for g, v in plan['group_vms'].items()} }")
    print(f"  Group -> plan distribution: "
          f"{ {p: len(g) for p, g in plan['plan_groups'].items()} }")
    print(f"\n  Datastores expected to already exist on {cfg['source_site']}: "
          f"{', '.join(plan['ds_names'])}")
    print(f"  Groups to create: {', '.join(plan['group_names'])}")
    print(f"  Plans to create: {', '.join(plan['plan_names'])}")


def run_scale_test(cfg: dict, m: int, n: int, x: int, y: int, dry_run: bool):
    print(f"\n{'=' * 70}\n  ERS SCALE TEST\n{'=' * 70}")
    print(f"  VMs: {m}   Datastores: {n}   Groups: {x}   Plans: {y}")
    print(f"  Source site: {cfg['source_site']}   Target site: {cfg['target_site']}")
    if dry_run:
        print("  Mode: DRY RUN — no resources will actually be created")

    plan = build_plan(cfg, m, n, x, y)

    if dry_run:
        print_dry_run(cfg, plan, m, n, x, y)
        return

    e = ers.instance(profile=cfg["profile"])
    site = e.register_site(cfg["source_site"])
    e.register_site(cfg["target_site"])

    # 1. Create VMs — one at a time, since each needs its own datastore/
    #    template assignment (the batch --name-prefix/--count helper
    #    assumes one datastore/template for the whole batch, which doesn't
    #    fit here).
    print(f"\n-> Creating {m} VM(s) across {n} datastore(s)...")
    created_vms = []
    for name in plan["vm_names"]:
        result = site.create_vm(name=name, template=plan["vm_template"][name],
                                 datastore=plan["vm_datastore"][name])
        if result:
            created_vms.append(name)
    print(f"   Created {len(created_vms)}/{m} VM(s).")

    # 2. Create groups — empty of VMs for now, enrolled in step 4.
    print(f"\n-> Creating {x} group(s)...")
    created_groups = []
    for name in plan["group_names"]:
        try:
            e.group.create(name=name, with_policy=cfg["service_level_policy"],
                            source_site=cfg["source_site"], target_site=cfg["target_site"])
            created_groups.append(name)
        except Exception as exc:
            print(f"   {name}: FAILED ({exc})")

    # Save state now, before enrolling/creating plans/running anything —
    # so --cleanup can tear down what was created even if a later step fails.
    save_state({
        "source_site": cfg["source_site"], "target_site": cfg["target_site"],
        "profile": cfg["profile"],
        "vm_names": created_vms, "group_names": created_groups, "plan_names": [],
    })

    # 3. Wait for the newly created VMs to sync into inventory before
    #    trying to enroll them — vm.add() resolves names against the
    #    site's VM inventory, which may not immediately reflect VMs
    #    created moments ago.
    print(f"\n-> Waiting {cfg['sync_wait_seconds']}s for newly created VMs to sync into inventory...")
    time.sleep(cfg["sync_wait_seconds"])

    # 4. Enroll VMs into their assigned group
    print(f"\n-> Enrolling VMs into groups...")
    for group_name in created_groups:
        vms = [v for v in plan["group_vms"].get(group_name, []) if v in created_vms]
        if vms:
            e.vm.add(*vms, with_group=group_name)

    # 5. Create plans, each with its assigned groups already attached —
    #    groups exist and are populated by this point, so there's no
    #    need for the create-empty-then-plan.add() workaround anymore.
    print(f"\n-> Creating {y} plan(s)...")
    created_plans = []
    for plan_name, groups in plan["plan_groups"].items():
        groups = [g for g in groups if g in created_groups]
        if not groups:
            continue
        try:
            e.plan.create(name=plan_name, with_groups=groups, target_site=cfg["target_site"])
            created_plans.append(plan_name)
        except Exception as exc:
            print(f"   {plan_name}: FAILED ({exc})")

    save_state({
        "source_site": cfg["source_site"], "target_site": cfg["target_site"],
        "profile": cfg["profile"],
        "vm_names": created_vms, "group_names": created_groups, "plan_names": created_plans,
    })

    # 6. Run protection on every group — waits for completion, since test
    #    failover needs a completed snapshot to work from.
    print(f"\n-> Running protection for {len(created_groups)} group(s)...")
    if created_groups:
        e.group.run(*created_groups, with_monitor=True)

    # 7. Test failover on every plan
    print(f"\n-> Running test failover for {len(created_plans)} plan(s)...")
    if created_plans:
        e.plan.failover("test", *created_plans, with_monitor=True)

    print(f"\n{'=' * 70}\n  SCALE TEST COMPLETE\n{'=' * 70}")
    print(f"  VMs created:    {len(created_vms)}/{m}")
    print(f"  Groups created: {len(created_groups)}/{x}")
    print(f"  Plans created:  {len(created_plans)}/{y}")
    print(f"\n  Run 'ers-scale-test --cleanup' to tear all of this down.")
    e.flush()


def run_cleanup(cfg: dict):
    state = load_state()
    if not state:
        print(f"No scale-test state found ({state_path(STATE_FILE)}) — nothing to clean up.")
        return

    e = ers.instance(profile=state.get("profile", cfg["profile"]))
    site = e.register_site(state["source_site"])

    plan_names = state.get("plan_names", [])
    group_names = state.get("group_names", [])
    vm_names = state.get("vm_names", [])

    print(f"\nTearing down: {len(plan_names)} plan(s), {len(group_names)} group(s), "
          f"{len(vm_names)} VM(s)")

    if group_names:
        print(f"\n-> Unenrolling VMs from {len(group_names)} group(s)...")
        for group_name in group_names:
            if vm_names:
                try:
                    e.vm.remove(*vm_names, with_group=group_name)
                except Exception:
                    pass  # best-effort — not every VM is necessarily in every group
        print(f"-> Deleting {len(group_names)} group(s)...")
        e.group.delete(*group_names)

    if plan_names:
        print(f"\n-> Deleting {len(plan_names)} plan(s)...")
        e.plan.delete(*plan_names)

    if vm_names:
        print(f"\n-> Deleting {len(vm_names)} VM(s)...")
        for name in vm_names:
            site.delete_vm(name)

    print("\nCleanup complete.")
    e.flush()


def main():
    parser = argparse.ArgumentParser(
        description="ers-scale-test — scale/load testing for ERS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                         help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--vms", type=int, metavar="M", help="Number of VMs to create")
    parser.add_argument("--datastores", type=int, metavar="N",
                         help="Number of datastores to distribute VMs across. Not required if "
                              "the config's datastore_names is set — its length is used instead.")
    parser.add_argument("--groups", type=int, metavar="X",
                         help="Number of groups to distribute VMs across")
    parser.add_argument("--plans", type=int, metavar="Y",
                         help="Number of plans to distribute groups across")
    parser.add_argument("--dry-run", action="store_true",
                         help="Preview the plan (names, distribution) without creating anything")
    parser.add_argument("--sync-wait", type=int, metavar="SECONDS",
                         help="Seconds to wait after VM creation, before enrolling them into "
                              "groups, for vCenter->Pure1 inventory sync (default: 60, or the "
                              "config's sync_wait_seconds)")
    parser.add_argument("--cleanup", action="store_true",
                         help="Tear down everything created by the last scale-test run")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.sync_wait is not None:
        cfg["sync_wait_seconds"] = args.sync_wait

    if args.cleanup:
        run_cleanup(cfg)
        return

    has_datastore_names = bool(cfg.get("datastore_names"))

    required_flags = [("--vms", args.vms), ("--groups", args.groups), ("--plans", args.plans)]
    if not has_datastore_names:
        required_flags.append(("--datastores", args.datastores))
    missing = [flag for flag, val in required_flags if val is None]
    if missing:
        print(f"Error: {', '.join(missing)} are required (unless using --cleanup)")
        sys.exit(1)

    if has_datastore_names:
        n = len(cfg["datastore_names"])
        if args.datastores is not None and args.datastores != n:
            print(f"Note: --datastores {args.datastores} ignored — config's datastore_names "
                  f"({n} entries: {', '.join(cfg['datastore_names'])}) takes precedence.")
    else:
        n = args.datastores

    if any(v < 1 for v in (args.vms, n, args.groups, args.plans)):
        print("Error: --vms/--datastores/--groups/--plans must all be at least 1")
        sys.exit(1)

    run_scale_test(cfg, args.vms, n, args.groups, args.plans, args.dry_run)


if __name__ == "__main__":
    main()
