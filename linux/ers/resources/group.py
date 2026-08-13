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

"""ers.resources.group — ErsInstance.group.* namespace."""

import fnmatch
import json

from .. import formatting
from ..config import state_path
from .policy import POLICIES_PATH
from .site import SITES_PATH

GROUPS_PATH   = "/pure-protect/api/1.latest/application-groups"
PROTECT_PATH  = "/pure-protect/api/1.latest/application-groups/protection/operations"
LAST_RUN_OPS  = "last_run_ops.json"

# Duplicated from vm.py's ENROLLED_VMS_PATH rather than imported — vm.py
# already imports GROUPS_PATH from this file, so importing the reverse
# direction would create a circular import.
ENROLLED_VMS_PATH = "/pure-protect/api/1.latest/enrolled-virtual-machines"


class GroupResource:
    def __init__(self, ers):
        self._ers = ers

    # -- list -----------------------------------------------------------
    def list(self, *names, details: bool = False, limit: int = 25):
        ers = self._ers
        params = {"offset": 0, "limit": limit, "deployment_id": ers.deployment_id}
        if names:
            params["names"] = ",".join(names)

        data  = ers.api.get(GROUPS_PATH, params=params)
        items = data.get("items") or data.get("data") or (data if isinstance(data, list) else [data])

        if not items:
            ers.output.out("No application groups found.")
            ers.output.out_json("groups", [])
            return []

        if ers.output.format == "json":
            ers.output.out_json("groups", items)
        elif details:
            self._enrich_names(items)
            formatting.print_groups_detailed(items)
        else:
            formatting.print_groups_summary(items)

        total = data.get("total_item_count") or data.get("total", len(items))
        ers.output.out(f"\nShowing {len(items)} of {total} application groups.")
        ers.output.out_json("total_item_count", total)
        return items

    def _resolve(self, names):
        ers = self._ers
        data = ers.api.get(GROUPS_PATH, params={"offset": 0, "limit": 100,
                                                 "deployment_id": ers.deployment_id})
        items = data.get("items") or data.get("data") or []
        lname = [n.lower() for n in names]
        matched   = [g for g in items if g.get("name", "").lower() in lname]
        not_found = [n for n in names if n.lower() not in [g.get("name", "").lower() for g in matched]]
        return matched, not_found

    def _resolve_wildcard(self, pattern):
        ers = self._ers
        data = ers.api.get(GROUPS_PATH, params={"offset": 0, "limit": 300,
                                                 "deployment_id": ers.deployment_id})
        items = data.get("items") or data.get("data") or []
        return [g for g in items if fnmatch.fnmatch(g.get("name", ""), pattern)]

    def _site_name_map(self) -> dict:
        ers = self._ers
        data = ers.api.get(SITES_PATH, params={"offset": 0, "limit": 300,
                                                "deployment_id": ers.deployment_id})
        return {s["id"]: s.get("name") for s in (data.get("items") or []) if s.get("id")}

    def _enrolled_vm_name_map(self, group_id: str) -> dict:
        """
        Confirmed real field for a VM's name here is nested under
        primary_virtual_machine.name (see vm.py's _enrolled_name — same
        shape, duplicated here to avoid a circular import). Passing an
        empty search term to get "all enrolled VMs for this group" is
        NOT confirmed against real API output — every example we've seen
        used an actual search term. Verify with ERS_DEBUG=1 if this
        doesn't return everything.
        """
        ers = self._ers
        data = ers.api.get(ENROLLED_VMS_PATH, params={
            "offset": 0, "limit": 300, "deployment_id": ers.deployment_id,
            "application_group_ids": group_id, "search": "",
        })
        name_map = {}
        for item in (data.get("items") or []):
            item_id = item.get("id")
            primary = item.get("primary_virtual_machine") or {}
            name = primary.get("name")
            if not name:
                vms = item.get("virtual_machines") or []
                if vms:
                    name = vms[0].get("name")
            if item_id and name:
                name_map[item_id] = name
        return name_map

    def _enrich_names(self, groups: list):
        """
        A group's own nested source_site/target_sites/enrolled_virtual_machines
        references come back with a placeholder "N/A" name from the
        application-groups endpoint — SITES_PATH returns the real site
        name (fetched once, not per-group); real VM names need a
        separate per-group lookup, since enrollment is inherently scoped
        to one group (see _enrolled_vm_name_map). Only called for
        --details, since it costs extra API calls the plain summary view
        doesn't need.
        """
        site_names = self._site_name_map()
        for group in groups:
            source = group.get("source_site")
            if source and source.get("id") in site_names:
                source["name"] = site_names[source["id"]]
            for t in (group.get("target_sites") or []):
                if t.get("id") in site_names:
                    t["name"] = site_names[t["id"]]

            vms = group.get("enrolled_virtual_machines") or []
            if vms and group.get("id"):
                vm_names = self._enrolled_vm_name_map(group["id"])
                for vm in vms:
                    if vm.get("id") in vm_names:
                        vm["name"] = vm_names[vm["id"]]

    # -- create -------------------------------------------------------------
    def create(self, name: str, with_policy: str, source_site: str, target_site: str,
               description: str = "", backup_start_time: int = 0,
               is_consistency_group: bool = False, has_cloud_pre_conversion: bool = False,
               has_parallel_boot: bool = True, is_infrastructure_group: bool = False,
               domain_name: str = ""):
        """
        Create an application group. Resolves with_policy (a service level
        policy name) and source_site/target_site (site names) to their
        IDs for you.
        """
        ers = self._ers

        policy_data = ers.api.get(POLICIES_PATH, params={"offset": 0, "limit": 300,
                                                          "deployment_id": ers.deployment_id})
        policies = policy_data.get("items") or []
        policy_match = next((p for p in policies if p.get("name", "").lower() == with_policy.lower()), None)
        if not policy_match:
            raise ValueError(f"Policy '{with_policy}' not found")

        site_data = ers.api.get(SITES_PATH, params={"offset": 0, "limit": 300,
                                                     "deployment_id": ers.deployment_id})
        sites = site_data.get("items") or []

        def _resolve_site(site_name):
            match = next((s for s in sites if s.get("name", "").lower() == site_name.lower()), None)
            if not match:
                raise ValueError(f"Site '{site_name}' not found")
            return match["id"]

        body = {
            "name": name,
            "description": description,
            "backup_start_time": backup_start_time,
            "is_consistency_group": is_consistency_group,
            "has_cloud_pre_conversion": has_cloud_pre_conversion,
            "has_parallel_boot": has_parallel_boot,
            "service_level_policy_id": policy_match["id"],
            "is_infrastructure_group": is_infrastructure_group,
            "domain_name": domain_name,
            "source_site_id": _resolve_site(source_site),
            "target_site_ids": [_resolve_site(target_site)],
        }

        result = ers.api.post(GROUPS_PATH, params={"deployment_id": ers.deployment_id}, body=body)
        items = result.get("items", [result]) if result else [{}]
        item = items[0] if items else {}

        ers.output.out(f"Created group '{name}' (id: {item.get('id', '-')})")
        ers.output.out_json("created_group", item)
        return item

    # -- enable / disable -------------------------------------------------
    def enable(self, *names, with_wildcard: bool = False):
        return self._toggle(names, enable=True, with_wildcard=with_wildcard)

    def disable(self, *names, with_wildcard: bool = False):
        return self._toggle(names, enable=False, with_wildcard=with_wildcard)

    def _toggle(self, names, enable: bool, with_wildcard: bool = False):
        ers = self._ers

        if with_wildcard:
            if len(names) != 1:
                raise ValueError(f"with_wildcard expects exactly one pattern, "
                                  f"got {len(names)}: {names!r}")
            matched = self._resolve_wildcard(names[0])
            if not matched:
                ers.output.out(f"No groups matched pattern '{names[0]}' — nothing to update.")
                return []
        else:
            matched, not_found = self._resolve(names)
            if not_found:
                ers.output.out(f"Warning: Groups not found: {', '.join(not_found)}")
            if not matched:
                ers.output.out("No matching groups found — nothing to update.")
                return []

        ids = [g["id"] for g in matched]
        matched_names = [g["name"] for g in matched]

        body = {"protection_state": "ENABLED" if enable else "DISABLED"}
        ers.api.patch(GROUPS_PATH, params={"deployment_id": ers.deployment_id, "ids": ",".join(ids)},
                      body=body)

        for n in matched_names:
            ers.output.out(f"  {n}: {'enabled' if enable else 'disabled'}")
        return matched_names

    # -- delete ---------------------------------------------------------------
    def delete(self, *names, with_wildcard: bool = False):
        """
        Delete one or more application groups by name.

        Without with_wildcard: each of *names is an exact group name.
        With with_wildcard: expects exactly one '*'-wildcard pattern in
        *names; every group whose name matches gets deleted.
        """
        ers = self._ers

        if with_wildcard:
            if len(names) != 1:
                raise ValueError(f"with_wildcard expects exactly one pattern, "
                                  f"got {len(names)}: {names!r}")
            matched = self._resolve_wildcard(names[0])
            if not matched:
                ers.output.out(f"No groups matched pattern '{names[0]}' — nothing to delete.")
                return []
        else:
            matched, not_found = self._resolve(names)
            if not_found:
                ers.output.out(f"Warning: Groups not found: {', '.join(not_found)}")
            if not matched:
                ers.output.out("No matching groups found — nothing to delete.")
                return []

        ids = [g["id"] for g in matched]
        matched_names = [g["name"] for g in matched]

        ers.api.delete(GROUPS_PATH, params={"deployment_id": ers.deployment_id, "ids": ",".join(ids)})

        for n in matched_names:
            ers.output.out(f"Deleted group '{n}'")
        ers.output.out_json("deleted_groups", matched_names)
        return matched_names

    # -- run --------------------------------------------------------------
    def run(self, *names):
        ers = self._ers
        matched, not_found = self._resolve(names)
        if not_found:
            ers.output.out(f"Warning: Groups not found: {', '.join(not_found)}")
        if not matched:
            ers.output.out("No matching groups found — nothing to update.")
            return {}

        ers.output.out(f"\nTriggering protection run for {len(matched)} group(s):\n")
        ers.output.out(f"  {'Group':<40} {'Op ID':<38} {'Status':<12} {'Type':<12}")
        ers.output.out("  " + "-" * 104)

        op_map = {}
        for group in matched:
            result = ers.api.post(PROTECT_PATH,
                                   params={"deployment_id": ers.deployment_id,
                                           "application_group_id": group["id"]},
                                   body={})
            items = result.get("items", [result] if result else [])
            item  = items[0] if items else {}
            op_id, status, optype = item.get("id", "-"), item.get("status", "-"), item.get("type", "-")

            op_map[group["name"]] = op_id
            ers.output.out(f"  {group['name']:<40} {op_id:<38} {status:<12} {optype:<12}")

            with open(state_path(LAST_RUN_OPS), "w") as f:
                json.dump(op_map, f, indent=2)

        ers.output.out_json("group_run", op_map)
        return op_map

    # -- monitor ------------------------------------------------------------
    def monitor(self, *names, interval: int = 10, max_polls: int = 30):
        import time, datetime
        ers = self._ers

        try:
            with open(state_path(LAST_RUN_OPS), "r") as f:
                op_map = json.load(f)
        except FileNotFoundError:
            print("Error: No recent run found. Run group.run(...) first to generate op IDs.")
            return {}

        if names:
            lname = [n.lower() for n in names]
            op_map = {k: v for k, v in op_map.items() if k.lower() in lname}
            if not op_map:
                print("Error: None of the specified group names found in last run output.")
                return {}

        TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "COMPLETED"}
        states = {name: {"op_id": op_id, "status": "UNKNOWN", "optype": "-", "finished_at": "-"}
                  for name, op_id in op_map.items()}

        print(f"\nMonitoring {len(states)} operation(s). Polling every {interval}s "
              f"(max {max_polls}). Ctrl+C to stop.\n")

        for poll in range(1, max_polls + 1):
            print(f"[Poll {poll}/{max_polls}]  {datetime.datetime.now().strftime('%H:%M:%S')}")
            print(f"  {'Group':<40} {'Op ID':<38} {'Status':<16} {'Type':<12} {'Finished'}")
            print("  " + "-" * 114)

            all_done = True
            for gname, state in states.items():
                if state["status"] in TERMINAL:
                    icon = "✓" if state["status"] in ("SUCCEEDED", "COMPLETED") else "✗"
                    print(f"  {gname:<40} {state['op_id']:<38} {icon} {state['status']:<14} "
                          f"{state['optype']:<12} {state['finished_at']}")
                    continue
                all_done = False

                result = ers.api.get(PROTECT_PATH, params={
                    "offset": 0, "limit": 25, "deployment_id": ers.deployment_id, "ids": state["op_id"]})
                op_items = result.get("items", [])
                op = op_items[0] if op_items else {}
                status, optype = op.get("status", "UNKNOWN"), op.get("type", "-")
                finished_ms = op.get("finished_at")
                finished_str = "-"
                if finished_ms:
                    finished_str = datetime.datetime.fromtimestamp(
                        finished_ms / 1000, datetime.timezone.utc).strftime("%H:%M:%S UTC")
                state.update({"status": status, "optype": optype, "finished_at": finished_str})
                display = f"{'✓' if status in ('SUCCEEDED','COMPLETED') else '…'} {status}" \
                          if status in TERMINAL else f"… {status}"
                print(f"  {gname:<40} {state['op_id']:<38} {display:<16} {optype:<12} {finished_str}")

            print()
            if all_done:
                print("All operations reached a terminal state.")
                break
            if poll < max_polls:
                try:
                    time.sleep(interval)
                except KeyboardInterrupt:
                    print("\nMonitoring stopped.")
                    break
        else:
            print(f"Max polls ({max_polls}) reached — some operations may still be running.")

        ers.output.out_json("group_monitor", [
            {"group": n, "op_id": s["op_id"], "status": s["status"],
             "type": s["optype"], "finished_at": s["finished_at"]}
            for n, s in states.items()
        ])
        return states
