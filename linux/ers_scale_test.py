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

--vms/--datastores/--groups/--plans are DESIRED TOTALS, not deltas — the
tool tracks what already exists in a persistent manifest
(~/.ers/state/scale_test_manifest.json) and only creates the difference.
Existing placements never move: new VMs/groups/plan-memberships always go
to whichever existing bucket currently has the fewest, so scaling up
tops off under-filled buckets and fills new ones first, rather than
reshuffling anything already in place. On a fresh run (nothing in the
manifest yet) this produces the same even distribution as plain
round-robin.

Configurable defaults live in scale-test-config.json (source_site,
target_site, service_level_policy, name prefixes, VM templates).

Datastores are NOT created — either datastore_name_prefix + N must
already exist on source_site, or the config's datastore_names can list
specific existing datastores by name directly (takes precedence over
datastore_name_prefix; --datastores becomes optional, taken from its
length instead). Either way, added datastore names are unioned into the
manifest across runs — none are ever removed automatically.

examples:
  ers-scale-test --vms 4 --datastores 1 --groups 2 --plans 1
  ers-scale-test --vms 20 --datastores 4 --groups 4 --plans 2 --dry-run
  ers-scale-test --vms 20 --datastores 4 --groups 4 --plans 2
  ers-scale-test --cleanup
  ers-scale-test --cleanup --keep-vms      # tear down groups/plans, leave VMs in vCenter
  ers-scale-test --cleanup --keep-groups   # detach groups from plans, delete plans only
"""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import ers
from ers.config import state_path

MANIFEST_FILE = "scale_test_manifest.json"
DEFAULT_CONFIG_PATH = "scale-test-config.json"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Manifest — the persistent record of everything created so far. Single
# source of truth: VM->group and group->plan are recorded on the VM/group
# itself (None = not yet assigned), so "how many does bucket X have" and
# "what's unassigned" are both simple filters over one dict, with no
# separate lists to keep in sync.
# ---------------------------------------------------------------------------

def empty_manifest() -> dict:
    return {
        "source_site": None, "target_site": None, "profile": "default",
        "datastore_names": [],
        "vms": {},      # name -> {"datastore": ..., "template": ..., "group": name or None}
        "groups": {},   # name -> {"plan": name or None}
        "plans": [],    # list of plan names that exist
        "run_history": [],  # one entry per real (non-dry-run) run — see run_scale_test()
    }


def load_manifest() -> dict:
    try:
        with open(state_path(MANIFEST_FILE)) as f:
            manifest = json.load(f)
    except FileNotFoundError:
        return empty_manifest()
    manifest.setdefault("run_history", [])  # forward-compat with older manifests
    return manifest


ENROLLED_VMS_PATH = "/pure-protect/api/1.latest/enrolled-virtual-machines"


def _fetch_all_enrolled_names(e, group_id: str) -> set:
    """Fetches ALL enrolled VM names for a group, with offset-based
    pagination (this endpoint ignores limit= and returns a small
    default page size, same as the inventory endpoint)."""
    all_names = set()
    offset = 0
    total = None
    while True:
        data = e.api.get(ENROLLED_VMS_PATH, params={
            "offset": offset, "limit": 300,
            "deployment_id": e.deployment_id,
            "application_group_ids": group_id,
        })
        items = data.get("items") or []
        if total is None:
            total = data.get("total_item_count")
        for item in items:
            pvm = item.get("primary_virtual_machine") or {}
            name = pvm.get("name")
            if name:
                all_names.add(name)
        if not items:
            break
        offset += len(items)
        if total is not None and offset >= total:
            break
    return all_names


def save_manifest(manifest: dict):
    with open(state_path(MANIFEST_FILE), "w") as f:
        json.dump(manifest, f, indent=2)


def delete_manifest():
    import os
    try:
        os.remove(state_path(MANIFEST_FILE))
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

def least_loaded_assign(new_items: list, buckets: list, current_loads: dict) -> dict:
    """Assigns each of `new_items` to whichever bucket in `buckets`
    currently has the fewest items, incrementing as it goes. Existing
    loads are never disturbed — only where NEW items land is decided
    here. Ties broken by bucket name for determinism. On a fresh set
    (all loads 0) this is equivalent to round-robin."""
    loads = {b: current_loads.get(b, 0) for b in buckets}
    assignment = {}
    for item in new_items:
        chosen = min(buckets, key=lambda b: (loads[b], b))
        assignment[item] = chosen
        loads[chosen] += 1
    return assignment


def resolve_datastore_names(cfg: dict, manifest: dict, target_n) -> list:
    """Full desired datastore list, unioned with whatever's already in
    the manifest (existing entries are never dropped, since they may
    already hold VMs)."""
    existing = manifest.get("datastore_names", [])
    if cfg.get("datastore_names"):
        desired = list(cfg["datastore_names"])
    else:
        desired = [f"{cfg['datastore_name_prefix']}{i:03d}" for i in range(1, (target_n or 0) + 1)]
    result = list(existing)
    for d in desired:
        if d not in result:
            result.append(d)
    return result


def next_index(existing_names, prefix: str) -> int:
    """Highest existing NNN suffix for this prefix, + 1 — so new names
    continue the sequence instead of colliding with what's already there."""
    max_i = 0
    for name in existing_names:
        if name.startswith(prefix):
            suffix = name[len(prefix):]
            if suffix.isdigit():
                max_i = max(max_i, int(suffix))
    return max_i + 1


# ---------------------------------------------------------------------------
# Plan computation — shared by --dry-run and the real run, so the preview
# is guaranteed to match what a real run would actually do.
# ---------------------------------------------------------------------------

def compute_delta(cfg: dict, manifest: dict, m: int, x: int, y: int, n) -> dict:
    ds_names = resolve_datastore_names(cfg, manifest, n)

    current_vms = manifest["vms"]
    current_groups = manifest["groups"]
    current_plans = manifest["plans"]

    current_m, current_x, current_y = len(current_vms), len(current_groups), len(current_plans)

    if m < current_m:
        # Scale DOWN — behavior depends on whether groups exist:
        #   groups > 0: just unenroll the excess VMs (leave in vCenter)
        #   groups = 0: actually delete VMs from vCenter
        # A VM should never be deleted while still enrolled in a group.
        excess_count = current_m - m
        sorted_vms = sorted(current_vms.keys(), key=lambda n: n, reverse=True)
        excess_vms = sorted_vms[:excess_count]
        if current_x > 0:
            vms_to_unenroll = excess_vms
            vms_to_remove = []
        else:
            vms_to_unenroll = []
            vms_to_remove = excess_vms
        new_vm_count = 0
    else:
        vms_to_unenroll = []
        vms_to_remove = []
        new_vm_count = m - current_m
    if x < current_x:
        print(f"Error: --groups {x} is less than the {current_x} group(s) already tracked.")
        sys.exit(1)
    if y < current_y:
        print(f"Error: --plans {y} is less than the {current_y} plan(s) already tracked.")
        sys.exit(1)

    new_group_count = x - current_x
    new_plan_count = y - current_y

    vm_start = next_index(current_vms, cfg["vm_name_prefix"])
    new_vm_names = [f"{cfg['vm_name_prefix']}{i:03d}" for i in range(vm_start, vm_start + new_vm_count)]

    grp_start = next_index(list(current_groups), cfg["group_name_prefix"])
    new_group_names = [f"{cfg['group_name_prefix']}{i:03d}" for i in range(grp_start, grp_start + new_group_count)]

    plan_start = next_index(current_plans, cfg["plan_name_prefix"])
    new_plan_names = [f"{cfg['plan_name_prefix']}{i:03d}" for i in range(plan_start, plan_start + new_plan_count)]

    # Template split across only the NEW VMs (existing ones keep whatever
    # they were already assigned).
    lnx, win = cfg["vm_lnx_template"], cfg["vm_win_template"]
    if lnx and win:
        half = (new_vm_count + 1) // 2
        new_vm_template = {name: (lnx if i < half else win) for i, name in enumerate(new_vm_names)}
    else:
        only = lnx or win
        new_vm_template = {name: only for name in new_vm_names}

    # Datastore assignment: only new VMs get placed; least-loaded across
    # the full (existing + newly added) datastore list.
    ds_loads = Counter(v["datastore"] for v in current_vms.values())
    new_vm_datastore = least_loaded_assign(new_vm_names, ds_names, ds_loads)

    # Group assignment: new VMs, PLUS any existing VMs left unassigned by
    # a prior --keep-vms cleanup, all need a group — least-loaded across
    # the full (existing + new) group list.
    all_group_names = list(current_groups.keys()) + new_group_names
    remove_set = set(vms_to_remove) | set(vms_to_unenroll)
    unassigned_existing_vms = [name for name, v in current_vms.items()
                                if v.get("group") is None and name not in remove_set]
    vms_needing_group = unassigned_existing_vms + new_vm_names
    group_loads = Counter(v["group"] for v in current_vms.values() if v.get("group"))
    vm_group_assignment = (least_loaded_assign(vms_needing_group, all_group_names, group_loads)
                            if all_group_names and vms_needing_group else {})

    # Plan assignment: new groups, PLUS any existing groups left
    # unassigned by a prior --keep-groups cleanup, all need a plan.
    all_plan_names = list(current_plans) + new_plan_names
    unassigned_existing_groups = [name for name, g in current_groups.items() if g.get("plan") is None]
    groups_needing_plan = unassigned_existing_groups + new_group_names
    plan_loads = Counter(g["plan"] for g in current_groups.values() if g.get("plan"))
    group_plan_assignment = (least_loaded_assign(groups_needing_plan, all_plan_names, plan_loads)
                              if all_plan_names and groups_needing_plan else {})

    return {
        "ds_names": ds_names,
        "vms_to_remove": vms_to_remove,
        "vms_to_unenroll": vms_to_unenroll,
        "new_vm_names": new_vm_names, "new_group_names": new_group_names, "new_plan_names": new_plan_names,
        "new_vm_template": new_vm_template, "new_vm_datastore": new_vm_datastore,
        "vm_group_assignment": vm_group_assignment,      # vm name -> group name, for VMs needing (re)assignment
        "group_plan_assignment": group_plan_assignment,  # group name -> plan name, for groups needing (re)assignment
        "all_group_names": all_group_names, "all_plan_names": all_plan_names,
    }


def final_counts(manifest: dict, delta: dict) -> dict:
    """What the manifest's distribution will look like AFTER applying
    this delta — used by both the real run's summary and --dry-run."""
    remove_set = set(delta.get("vms_to_remove", []))
    unenroll_set = set(delta.get("vms_to_unenroll", []))
    skip_set = remove_set | unenroll_set

    ds_counts = Counter()
    group_counts = Counter()
    for name, v in manifest["vms"].items():
        if name in remove_set:
            continue  # deleted from vCenter entirely
        ds_counts[v["datastore"]] += 1
        if v.get("group") and name not in unenroll_set:
            group_counts[v["group"]] += 1
    for name, ds in delta["new_vm_datastore"].items():
        ds_counts[ds] += 1
    for vm_name, grp in delta["vm_group_assignment"].items():
        group_counts[grp] += 1

    plan_counts = Counter()
    for g in manifest["groups"].values():
        if g.get("plan"):
            plan_counts[g["plan"]] += 1
    for grp_name, pl in delta["group_plan_assignment"].items():
        plan_counts[pl] += 1

    return {"ds_counts": ds_counts, "group_counts": group_counts, "plan_counts": plan_counts}


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

def print_dry_run(manifest: dict, delta: dict):
    counts = final_counts(manifest, delta)

    print(f"\n  Currently tracked: {len(manifest['vms'])} VM(s), "
          f"{len(manifest['datastore_names'])} datastore(s), "
          f"{len(manifest['groups'])} group(s), {len(manifest['plans'])} plan(s)")

    if delta["vms_to_unenroll"]:
        print(f"  Will UNENROLL (keep in vCenter): {len(delta['vms_to_unenroll'])} VM(s)")
        print(f"    {', '.join(delta['vms_to_unenroll'])}")

    if delta["vms_to_remove"]:
        print(f"  Will DELETE from vCenter: {len(delta['vms_to_remove'])} VM(s)")
        print(f"    {', '.join(delta['vms_to_remove'])}")

    if delta["new_vm_names"] or delta["new_group_names"] or delta["new_plan_names"]:
        print(f"  Will add: {len(delta['new_vm_names'])} VM(s), "
              f"{len(delta['ds_names']) - len(manifest['datastore_names'])} datastore(s), "
              f"{len(delta['new_group_names'])} group(s), {len(delta['new_plan_names'])} plan(s)")

    if delta["new_vm_names"]:
        print(f"\n  New VM names: {', '.join(delta['new_vm_names'])}")
        print(f"  New VM templates: {dict(Counter(delta['new_vm_template'].values()))}")
    if delta["new_group_names"]:
        print(f"  New group names: {', '.join(delta['new_group_names'])}")
    if delta["new_plan_names"]:
        print(f"  New plan names: {', '.join(delta['new_plan_names'])}")

    print(f"\n  Final VMs per datastore:  {dict(counts['ds_counts'])}")
    print(f"  Final VMs per group:      {dict(counts['group_counts'])}")
    print(f"  Final groups per plan:    {dict(counts['plan_counts'])}")


def new_group_plan_order(new_plan_names, by_plan):
    """Process brand-new plans before existing ones get more groups
    added — order doesn't affect correctness, just keeps the printed
    output in a sensible sequence."""
    ordered = [p for p in new_plan_names if p in by_plan]
    ordered += [p for p in by_plan if p not in ordered]
    return ordered


# ---------------------------------------------------------------------------
# Real run
# ---------------------------------------------------------------------------

def run_scale_test(cfg: dict, m: int, n, x: int, y: int, dry_run: bool):
    manifest = load_manifest()
    if manifest["vms"] and (manifest.get("source_site") != cfg["source_site"]
                             or manifest.get("target_site") != cfg["target_site"]):
        print(f"Error: existing manifest was built against source_site="
              f"{manifest.get('source_site')!r}/target_site={manifest.get('target_site')!r}, "
              f"but this config has source_site={cfg['source_site']!r}/"
              f"target_site={cfg['target_site']!r}. Refusing to mix — run --cleanup first, "
              f"or fix the config.")
        sys.exit(1)

    delta = compute_delta(cfg, manifest, m, x, y, n)

    print(f"\n{'=' * 70}\n  ERS SCALE TEST\n{'=' * 70}")
    print(f"  Target totals — VMs: {m}   Datastores: {len(delta['ds_names'])}   "
          f"Groups: {x}   Plans: {y}")
    print(f"  Source site: {cfg['source_site']}   Target site: {cfg['target_site']}")
    if dry_run:
        print("  Mode: DRY RUN — no resources will actually be created")
        print_dry_run(manifest, delta)
        return

    if not (delta["vms_to_remove"] or delta["vms_to_unenroll"]
            or delta["new_vm_names"] or delta["new_group_names"]
            or delta["new_plan_names"] or delta["vm_group_assignment"]
            or delta["group_plan_assignment"]):
        print("\nNothing to do — already at (or beyond) the requested totals.")
        return

    e = ers.instance(profile=cfg["profile"])
    site = e.register_site(cfg["source_site"])
    e.register_site(cfg["target_site"])

    manifest["source_site"] = cfg["source_site"]
    manifest["target_site"] = cfg["target_site"]
    manifest["profile"] = cfg["profile"]
    manifest["datastore_names"] = delta["ds_names"]

    # 1. Sync actual state from Pure1 BEFORE any scale-down/creation
    #    steps — if the manifest is stale (from a prior run or manual
    #    changes), acting on it without syncing first causes wrong
    #    unenrollments, duplicate enrollments (422s), etc.

    # 1a. Sync enrollment state
    if manifest["groups"]:
        print(f"\n-> Syncing actual enrollment state from Pure1...")
        enrollment_changed = False
        for grp_name in list(manifest["groups"].keys()):
            try:
                matched, _ = e.group._resolve([grp_name])
                if not matched:
                    continue
                grp_id = matched[0]["id"]
                enrolled_names = _fetch_all_enrolled_names(e, grp_id)
                for vm_name in enrolled_names:
                    if vm_name in manifest["vms"]:
                        if manifest["vms"][vm_name].get("group") != grp_name:
                            manifest["vms"][vm_name]["group"] = grp_name
                            enrollment_changed = True
                # Also mark VMs that the manifest thinks are in this group
                # but Pure1 says are NOT — set them to None so they don't
                # block unenrollment or get incorrectly counted.
                for vm_name, v in manifest["vms"].items():
                    if v.get("group") == grp_name and vm_name not in enrolled_names:
                        manifest["vms"][vm_name]["group"] = None
                        enrollment_changed = True
            except Exception:
                pass
        if enrollment_changed:
            save_manifest(manifest)
            delta = compute_delta(cfg, manifest, m, x, y, n)
            print(f"   Enrollment state synced — recomputed assignments.")
        else:
            print(f"   Manifest already consistent with Pure1.")

    # 1b. Sync plan memberships
    if manifest["plans"]:
        print(f"-> Syncing actual plan membership state from Pure1...")
        plan_changed = False
        try:
            group_id_to_name = {}
            all_group_matched, _ = e.group._resolve(list(manifest["groups"].keys()))
            for g in all_group_matched:
                group_id_to_name[g["id"]] = g["name"]

            plan_matched, _ = e.plan._resolve(list(manifest["plans"]))
            for plan_obj in plan_matched:
                plan_name = plan_obj.get("name")
                for pg in (plan_obj.get("groups") or []):
                    pg_name = group_id_to_name.get(pg.get("id"))
                    if pg_name and pg_name in manifest["groups"]:
                        if manifest["groups"][pg_name].get("plan") != plan_name:
                            manifest["groups"][pg_name]["plan"] = plan_name
                            plan_changed = True
        except Exception:
            pass
        if plan_changed:
            save_manifest(manifest)
            delta = compute_delta(cfg, manifest, m, x, y, n)
            print(f"   Plan membership synced — recomputed assignments.")
        else:
            print(f"   Manifest already consistent with Pure1.")

    # 2. Scale down VMs if needed — unenroll from groups first,
    #    then delete from vCenter, then remove from the manifest.
    # 2a. Unenroll-only scale-down (groups exist — keep VMs in vCenter,
    #     just remove them from their groups).
    vms_to_unenroll = delta["vms_to_unenroll"]
    if vms_to_unenroll:
        print(f"\n-> Scaling down enrollment: unenrolling {len(vms_to_unenroll)} VM(s) "
              f"(keeping in vCenter)...")
        by_group = {}
        for vm_name in vms_to_unenroll:
            grp = manifest["vms"].get(vm_name, {}).get("group")
            if grp:
                by_group.setdefault(grp, []).append(vm_name)
        for grp, vms in by_group.items():
            try:
                e.vm.remove(*vms, with_group=grp)
            except Exception:
                pass
        for vm_name in vms_to_unenroll:
            if vm_name in manifest["vms"]:
                manifest["vms"][vm_name]["group"] = None
        save_manifest(manifest)
        enrolled_count = sum(1 for v in manifest["vms"].values() if v.get("group"))
        print(f"   {enrolled_count} VM(s) still enrolled, "
              f"{len(manifest['vms'])} total in vCenter.")

    # 2b. Full delete scale-down (no groups — actually remove VMs from
    #     vCenter since nothing references them).
    vms_to_remove = delta["vms_to_remove"]
    if vms_to_remove:
        print(f"\n-> Scaling down: deleting {len(vms_to_remove)} VM(s) from vCenter...")
        for name in vms_to_remove:
            site.delete_vm(name)
            manifest["vms"].pop(name, None)
        save_manifest(manifest)
        print(f"   {len(manifest['vms'])} VM(s) remaining.")

    # 3. Create only the NEW VMs — skip any that already exist in vCenter
    #    (idempotent: safe to re-run after a partial failure).
    new_vm_names = delta["new_vm_names"]
    if new_vm_names:
        print(f"\n-> Creating {len(new_vm_names)} new VM(s)...")
        existing_in_vcenter = site.vms_exist(new_vm_names)
        if existing_in_vcenter:
            print(f"   {len(existing_in_vcenter)} already exist in vCenter — skipping creation for those.")
        for name in new_vm_names:
            if name not in existing_in_vcenter:
                result = site.create_vm(name=name, template=delta["new_vm_template"][name],
                                         datastore=delta["new_vm_datastore"][name])
                if not result:
                    continue
            manifest["vms"][name] = {"datastore": delta["new_vm_datastore"][name],
                                      "template": delta["new_vm_template"][name], "group": None}
        print(f"   {len(manifest['vms'])} VM(s) tracked in total.")

    # 4. Create only the NEW groups.
    new_group_names = delta["new_group_names"]
    if new_group_names:
        print(f"\n-> Creating {len(new_group_names)} new group(s)...")
        # Check which "new" groups already exist in the API (same
        # idempotency pattern as VMs and plans)
        existing_groups_in_api = set()
        try:
            matched, _ = e.group._resolve(new_group_names)
            existing_groups_in_api = {g.get("name") for g in matched}
            if existing_groups_in_api:
                print(f"   {len(existing_groups_in_api)} group(s) already exist in Pure1 — "
                      f"skipping creation for those.")
        except Exception:
            pass

        for name in new_group_names:
            if name in existing_groups_in_api:
                manifest["groups"][name] = {"plan": None}
                continue
            try:
                e.group.create(name=name, with_policy=cfg["service_level_policy"],
                                source_site=cfg["source_site"], target_site=cfg["target_site"])
                manifest["groups"][name] = {"plan": None}
            except Exception as exc:
                print(f"   {name}: FAILED ({exc})")

    save_manifest(manifest)  # save before the sync wait / enrollment, in case those fail

    # 5. Wait for newly created VMs to sync into Pure1's inventory
    #    before enrolling — vm.add() resolves names against the
    #    inventory, which may not immediately reflect VMs just created
    #    in vCenter. Rather than sleeping for a fixed duration and
    #    hoping, poll the inventory until every expected VM actually
    #    appears (or give up after max_sync_polls * sync_poll_interval).
    all_expected_vms = list(manifest["vms"].keys())
    if new_vm_names and all_expected_vms:
        max_sync_polls = cfg.get("max_sync_polls", 30)
        sync_poll_interval = cfg.get("sync_poll_interval", 30)
        print(f"\n-> Waiting for {len(all_expected_vms)} VM(s) to appear in Pure1 inventory "
              f"(polling every {sync_poll_interval}s, up to {max_sync_polls} attempts)...")

        source_site_id = None
        try:
            source_site_id = e.vm._resolve_site_id(cfg["source_site"])
        except Exception:
            pass

        if source_site_id:
            for attempt in range(1, max_sync_polls + 1):
                inventory = e.vm._inventory(source_site_id)
                inventory_names = {v.get("name") for v in inventory}
                missing = [n for n in all_expected_vms if n not in inventory_names]
                if not missing:
                    print(f"   All {len(all_expected_vms)} VM(s) visible in inventory "
                          f"(after {attempt} poll(s)).")
                    break
                print(f"   Poll {attempt}/{max_sync_polls}: "
                      f"{len(all_expected_vms) - len(missing)}/{len(all_expected_vms)} "
                      f"visible, {len(missing)} still syncing...")
                if attempt < max_sync_polls:
                    time.sleep(sync_poll_interval)
            else:
                print(f"   Warning: {len(missing)} VM(s) still not visible after "
                      f"{max_sync_polls} polls — proceeding anyway, but enrollment "
                      f"may report some VMs as 'not found'. Missing: "
                      f"{', '.join(missing[:10])}{'...' if len(missing) > 10 else ''}")
        else:
            print(f"   Could not resolve site ID for '{cfg['source_site']}' — "
                  f"falling back to fixed {cfg['sync_wait_seconds']}s wait.")
            time.sleep(cfg["sync_wait_seconds"])


    # 5. Enroll every VM that needs a group (new ones, plus any orphaned
    #    by a prior --keep-vms cleanup) into its assigned group.
    vm_group_assignment = delta["vm_group_assignment"]
    if vm_group_assignment:
        print(f"\n-> Enrolling {len(vm_group_assignment)} VM(s) into groups...")
        by_group = {}
        for vm_name, grp in vm_group_assignment.items():
            by_group.setdefault(grp, []).append(vm_name)
        for grp, vms in by_group.items():
            if grp not in manifest["groups"]:
                continue
            # Check which VMs are already enrolled in this group — skip
            # those to avoid a 422 on re-enroll.
            try:
                already_enrolled = set()
                matched, _ = e.group._resolve([grp])
                if matched:
                    grp_id = matched[0]["id"]
                    already_enrolled = _fetch_all_enrolled_names(e, grp_id)
                vms_to_enroll = [v for v in vms if v not in already_enrolled]
                skipped = len(vms) - len(vms_to_enroll)
                if skipped:
                    print(f"   {grp}: {skipped} VM(s) already enrolled — skipping those.")
                if vms_to_enroll:
                    e.vm.add(*vms_to_enroll, with_group=grp)
                for vm_name in vms:
                    manifest["vms"][vm_name]["group"] = grp
            except Exception as exc:
                print(f"   {grp}: enrollment FAILED ({exc}) — continuing with next group.")
                # Still mark VMs as assigned in the manifest so a re-run
                # can retry rather than losing the assignment entirely.
                for vm_name in vms:
                    manifest["vms"][vm_name]["group"] = grp

    # 5. Create NEW plans directly with their assigned groups already
    #    attached, and attach any orphaned groups (from a prior
    #    --keep-groups cleanup) or newly-grown groups to existing plans.
    #
    #    Before creating, check which "new" plan names already exist in
    #    the API (e.g. from a prior run whose manifest was wiped, or
    #    manual creation) — for those, fall back to plan.add() instead
    #    of plan.create(), which would fail on the duplicate name and
    #    silently drop their assigned groups on the floor.
    group_plan_assignment = delta["group_plan_assignment"]
    new_plan_names = delta["new_plan_names"]
    if group_plan_assignment:
        print(f"\n-> Assigning {len(group_plan_assignment)} group(s) to plans...")
        by_plan = {}
        for grp_name, pl in group_plan_assignment.items():
            by_plan.setdefault(pl, []).append(grp_name)

        # Check which "new" plan names already exist in Pure1
        already_exist_in_api = set()
        if new_plan_names:
            try:
                matched, _ = e.plan._resolve(new_plan_names)
                already_exist_in_api = {p.get("name") for p in matched}
                if already_exist_in_api:
                    print(f"   Note: {', '.join(already_exist_in_api)} already exist in Pure1 "
                          f"— will add groups to them instead of re-creating.")
            except Exception:
                pass  # if the check itself fails, proceed with create and let it fail naturally

        for plan_name in new_group_plan_order(new_plan_names, by_plan):
            groups_for_plan = by_plan.get(plan_name, [])
            if plan_name in new_plan_names and plan_name not in already_exist_in_api:
                try:
                    e.plan.create(name=plan_name, with_groups=groups_for_plan,
                                   target_site=cfg["target_site"])
                    manifest["plans"].append(plan_name)
                    for g in groups_for_plan:
                        manifest["groups"][g]["plan"] = plan_name
                except Exception as exc:
                    print(f"   {plan_name}: create FAILED ({exc}), trying plan.add() as fallback...")
                    try:
                        e.plan.add(plan_name, groups_for_plan)
                        if plan_name not in manifest["plans"]:
                            manifest["plans"].append(plan_name)
                        for g in groups_for_plan:
                            manifest["groups"][g]["plan"] = plan_name
                    except Exception as exc2:
                        print(f"   {plan_name}: add also FAILED ({exc2}) — "
                              f"groups {', '.join(groups_for_plan)} are unassigned.")
            else:
                # existing plan (either was already in manifest, or just
                # discovered to already exist in the API) gaining groups
                try:
                    e.plan.add(plan_name, groups_for_plan)
                    if plan_name not in manifest["plans"]:
                        manifest["plans"].append(plan_name)
                    for g in groups_for_plan:
                        manifest["groups"][g]["plan"] = plan_name
                except Exception as exc:
                    print(f"   {plan_name}: FAILED to add groups ({exc})")

    save_manifest(manifest)

    run_protection_and_failover(e, manifest)
    e.flush()


def run_protection_and_failover(e, manifest: dict):
    """Runs protection on every currently-tracked group and test failover
    on every currently-tracked plan, timing each and appending a fresh
    entry to the manifest's run_history — shared by the tail of a normal
    run and by --rerun, so both record identical, non-divergent history
    entries."""
    all_groups = list(manifest["groups"].keys())
    all_plans = list(manifest["plans"])

    # Run protection on every group — waits for completion, since test
    # failover needs a completed snapshot to work from.
    print(f"\n-> Running protection for {len(all_groups)} group(s)...")
    protection_time_minutes = None
    if all_groups:
        protection_start = time.time()
        e.group.run(*all_groups, with_monitor=True)
        protection_time_minutes = round((time.time() - protection_start) / 60, 2)
        print(f"   Protection completed in {protection_time_minutes}min.")

    # Test failover on every plan
    print(f"\n-> Running test failover for {len(all_plans)} plan(s)...")
    recovery_time_minutes = None
    if all_plans:
        recovery_start = time.time()
        e.plan.failover("test", *all_plans, with_monitor=True)
        recovery_time_minutes = round((time.time() - recovery_start) / 60, 2)
        print(f"   Test failover completed in {recovery_time_minutes}min.")

    manifest["run_history"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_vms": len(manifest["vms"]), "total_groups": len(manifest["groups"]),
        "total_plans": len(manifest["plans"]),
        "protection_time_minutes": protection_time_minutes,
        "recovery_time_minutes": recovery_time_minutes,
    })
    save_manifest(manifest)

    counts = final_counts(manifest, {"new_vm_datastore": {}, "vm_group_assignment": {},
                                      "group_plan_assignment": {}})
    print(f"\n{'=' * 70}\n  SCALE TEST COMPLETE\n{'=' * 70}")
    print(f"  Total VMs:    {len(manifest['vms'])}")
    print(f"  Total groups: {len(manifest['groups'])}")
    print(f"  Total plans:  {len(manifest['plans'])}")
    print(f"  VMs per datastore: {dict(counts['ds_counts'])}")
    print(f"  VMs per group:     {dict(counts['group_counts'])}")
    print(f"  Groups per plan:   {dict(counts['plan_counts'])}")
    print(f"  Protection time:   {f'{protection_time_minutes}min' if protection_time_minutes is not None else '-'}")
    print(f"  Recovery time:     {f'{recovery_time_minutes}min' if recovery_time_minutes is not None else '-'}")
    print(f"\n  Run 'ers-scale-test --cleanup' to tear all of this down.")


def run_rerun(cfg: dict):
    """Re-executes protection + test failover against everything
    currently tracked in the manifest, with no --vms/--datastores/
    --groups/--plans needed — for repeating the exact same scale test
    (e.g. a second timing measurement) without creating or changing
    anything."""
    manifest = load_manifest()
    if not manifest["vms"]:
        print(f"No scale-test manifest found ({state_path(MANIFEST_FILE)}) — nothing to re-run. "
              f"Run a normal scale test first.")
        return

    print(f"\n{'=' * 70}\n  ERS SCALE TEST — RERUN\n{'=' * 70}")
    print(f"  Re-running against everything already tracked: "
          f"{len(manifest['vms'])} VM(s), {len(manifest['groups'])} group(s), "
          f"{len(manifest['plans'])} plan(s). No resources will be created or moved.")

    e = ers.instance(profile=manifest.get("profile", cfg["profile"]))
    e.register_site(manifest["source_site"])
    e.register_site(manifest["target_site"])

    run_protection_and_failover(e, manifest)
    e.flush()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def run_cleanup(cfg: dict, keep_vms: bool, keep_groups: bool, keep_plans: bool):
    manifest = load_manifest()
    if not manifest["vms"] and not manifest["groups"] and not manifest["plans"]:
        print(f"No scale-test manifest found ({state_path(MANIFEST_FILE)}) — nothing to clean up.")
        return

    e = ers.instance(profile=manifest.get("profile", cfg["profile"]))
    site = e.register_site(manifest["source_site"])

    plan_names = list(manifest["plans"])
    group_names = list(manifest["groups"].keys())
    vm_names = list(manifest["vms"].keys())

    if keep_plans:
        mode = "keep everything (plan cleanup only — reverts test failover, nothing deleted)"
    elif keep_groups:
        mode = "keep groups (detach from plans, delete plans only)"
    elif keep_vms:
        mode = "keep VMs (delete groups/plans, leave VMs in vCenter)"
    else:
        mode = "full teardown"
    print(f"\nCleanup mode: {mode}")
    print(f"Tracked: {len(plan_names)} plan(s), {len(group_names)} group(s), {len(vm_names)} VM(s)")

    if plan_names:
        print(f"\n-> Running plan cleanup for {len(plan_names)} plan(s) "
              f"(reverting test failover)...")
        results = e.plan.cleanup(*plan_names, with_monitor=True)
        failed = [r["plan"] for r in results if r.get("status") != "SUCCEEDED"]
        if failed:
            print(f"   Warning: plan cleanup did not succeed for: {', '.join(failed)}. "
                  f"Continuing with the rest of teardown anyway, but these may leave "
                  f"orphaned test-failover resources behind in vCenter.")
        else:
            print(f"   Plan cleanup succeeded for all {len(plan_names)} plan(s).")

    if keep_plans:
        # Nothing else to do — plans/groups/VMs are all left exactly as
        # they are, ready for --rerun or a further scale-up.
        print("\nCleanup complete — nothing deleted; plan cleanup reverted test failover state "
              "so a --rerun or further scale-up can proceed cleanly.")
        e.flush()
        return

    if keep_groups:
        # Detach every group from its plan before deleting the plan --
        # the API rejects deleting a plan that still references groups.
        if plan_names:
            print(f"\n-> Detaching groups from {len(plan_names)} plan(s)...")
            groups_by_plan = {}
            for name, g in manifest["groups"].items():
                if g.get("plan"):
                    groups_by_plan.setdefault(g["plan"], []).append(name)
            for plan_name in plan_names:
                groups = groups_by_plan.get(plan_name, [])
                if groups:
                    e.plan.remove(plan_name, groups)
            print(f"-> Deleting {len(plan_names)} plan(s)...")
            e.plan.delete(*plan_names)
        # Groups and VMs are left entirely alone.
        for name in manifest["groups"]:
            manifest["groups"][name]["plan"] = None
        manifest["plans"] = []
        save_manifest(manifest)
        print("\nCleanup complete — groups and VMs left in place, plans removed.")
        e.flush()
        return

    if group_names:
        print(f"\n-> Unenrolling VMs from {len(group_names)} group(s)...")
        vms_by_group = {}
        for vm_name, v in manifest["vms"].items():
            grp = v.get("group")
            if grp:
                vms_by_group.setdefault(grp, []).append(vm_name)
        for group_name in group_names:
            group_vms = vms_by_group.get(group_name, [])
            if group_vms:
                try:
                    e.vm.remove(*group_vms, with_group=group_name)
                except Exception:
                    pass  # best-effort
        print(f"-> Deleting {len(group_names)} group(s)...")
        e.group.delete(*group_names)

    if plan_names:
        print(f"\n-> Deleting {len(plan_names)} plan(s)...")
        e.plan.delete(*plan_names)

    if keep_vms:
        for name in manifest["vms"]:
            manifest["vms"][name]["group"] = None
        manifest["groups"] = {}
        manifest["plans"] = []
        save_manifest(manifest)
        print("\nCleanup complete — VMs left in vCenter, unenrolled; groups/plans removed.")
        e.flush()
        return

    if vm_names:
        print(f"\n-> Deleting {len(vm_names)} VM(s)...")
        for name in vm_names:
            site.delete_vm(name)

    delete_manifest()
    print("\nCleanup complete.")
    e.flush()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ers-scale-test — scale/load testing for ERS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                         help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--vms", type=int, metavar="M", help="Desired total number of VMs")
    parser.add_argument("--datastores", type=int, metavar="N",
                         help="Desired total number of datastores. Not required if the "
                              "config's datastore_names is set — its length is used instead.")
    parser.add_argument("--groups", type=int, metavar="X", help="Desired total number of groups")
    parser.add_argument("--plans", type=int, metavar="Y", help="Desired total number of plans")
    parser.add_argument("--dry-run", action="store_true",
                         help="Preview the delta (names, final distribution) without creating anything")
    parser.add_argument("--cleanup", action="store_true",
                         help="Tear down everything tracked in the scale-test manifest")
    parser.add_argument("--rerun", action="store_true",
                         help="Re-run protection + test failover against everything already "
                              "tracked, with no --vms/--datastores/--groups/--plans needed — "
                              "creates or moves nothing, just repeats the exercise (e.g. for "
                              "another timing measurement)")
    parser.add_argument("--keep-vms", action="store_true",
                         help="With --cleanup: delete groups/plans, leave VMs in vCenter (unenrolled)")
    parser.add_argument("--keep-groups", action="store_true",
                         help="With --cleanup: detach groups from plans and delete plans only; "
                              "groups and their VMs are left exactly as they are")
    parser.add_argument("--keep-plans", action="store_true",
                         help="With --cleanup: deletes nothing — just runs plan cleanup "
                              "(reverts test failover) so a --rerun or further scale-up can "
                              "proceed. Plans, groups, and VMs are all left exactly as they are.")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.rerun:
        if args.cleanup or args.keep_vms or args.keep_groups or args.keep_plans:
            print("Error: --rerun can't be combined with --cleanup/--keep-vms/"
                  "--keep-groups/--keep-plans")
            sys.exit(1)
        if args.vms or args.datastores or args.groups or args.plans:
            print("Note: --vms/--datastores/--groups/--plans are ignored with --rerun — "
                  "it always targets everything already tracked.")
        run_rerun(cfg)
        return

    if args.cleanup:
        keep_flags_given = sum([args.keep_vms, args.keep_groups, args.keep_plans])
        if keep_flags_given > 1:
            print("Error: --keep-vms/--keep-groups/--keep-plans are mutually exclusive — "
                  "--keep-plans already implies keeping groups and VMs too, and --keep-groups "
                  "already implies keeping VMs too.")
            sys.exit(1)
        run_cleanup(cfg, keep_vms=args.keep_vms, keep_groups=args.keep_groups,
                    keep_plans=args.keep_plans)
        return

    if args.keep_vms or args.keep_groups or args.keep_plans:
        print("Error: --keep-vms/--keep-groups/--keep-plans only apply with --cleanup")
        sys.exit(1)

    has_datastore_names = bool(cfg.get("datastore_names"))
    manifest = load_manifest()
    current_ds_count = len(manifest.get("datastore_names", []))

    if args.vms is None:
        print("Error: --vms is required (unless using --cleanup)")
        sys.exit(1)

    # Resolve datastores: config's datastore_names > explicit --datastores > manifest
    n = None
    if has_datastore_names:
        n = len(cfg["datastore_names"])
        if args.datastores is not None and args.datastores != n:
            print(f"Note: --datastores {args.datastores} ignored — config's datastore_names "
                  f"({n} entries: {', '.join(cfg['datastore_names'])}) takes precedence.")
    elif args.datastores is not None:
        n = args.datastores
    elif current_ds_count > 0:
        n = current_ds_count
    else:
        print("Error: --datastores is required on the first run (no prior state in manifest)")
        sys.exit(1)

    current_groups = len(manifest.get("groups", {}))
    current_plans = len(manifest.get("plans", []))
    x = args.groups if args.groups is not None else current_groups
    y = args.plans if args.plans is not None else current_plans

    if args.vms < 1 or n < 1:
        print("Error: --vms and --datastores must be at least 1")
        sys.exit(1)
    if y > 0 and x < 1:
        print("Error: --plans requires at least --groups 1 (plans need groups)")
        sys.exit(1)

    run_scale_test(cfg, args.vms, n, x, y, args.dry_run)


if __name__ == "__main__":
    main()
