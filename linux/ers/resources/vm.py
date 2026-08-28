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
ers.resources.vm — ErsInstance.vm.* namespace: VM inventory listing and
group enrollment (add/remove).

Two different "VM ID" concepts are involved here, and they are NOT the
same value:
  - The inventory ID (e.g. "e067252a-...::vm-29239") — what list() returns,
    and what add() sends as virtual_machine_id when enrolling a VM.
  - The enrollment ID — a separate ID assigned once a VM is actually
    enrolled into a group, used by remove()'s DELETE call. This is NOT
    confirmed against real API output yet — see remove()'s docstring.
"""

import fnmatch

from .group import GROUPS_PATH
from .site import SITES_PATH

VM_INVENTORY_PATH = "/pure-protect/api/1.latest/inventory/vmware/virtual-machines"
ENROLLED_VMS_PATH = "/pure-protect/api/1.latest/enrolled-virtual-machines"

DEFAULT_PROTECTION_WORKFLOW = "FA_OFFLOAD"


class VmResource:
    def __init__(self, ers):
        self._ers = ers

    # -- internal helpers -------------------------------------------------

    def _resolve_site_id(self, site_name: str):
        ers = self._ers
        data = ers.api.get(SITES_PATH, params={"offset": 0, "limit": 300,
                                                "deployment_id": ers.deployment_id})
        sites = data.get("items") or []
        match = next((s for s in sites if s.get("name", "").lower() == site_name.lower()), None)
        return match["id"] if match else None

    def _resolve_group(self, group_name: str):
        ers = self._ers
        data = ers.api.get(GROUPS_PATH, params={"offset": 0, "limit": 300,
                                                 "deployment_id": ers.deployment_id,
                                                 "names": group_name})
        groups = data.get("items") or []
        group = next((g for g in groups if g.get("name", "").lower() == group_name.lower()), None)
        if not group:
            raise ValueError(f"Group '{group_name}' not found")
        return group

    def _inventory(self, site_id: str, target_site_type: str = "VSPHERE") -> list:
        """Fetches the FULL VM inventory for this site, paginating via
        offset — this endpoint returns continuation_token: null even
        when more results exist (confirmed: 298 items returned out of
        500 total with token=null), so continuation_token can't be
        relied on. Instead, increment offset by the page size and keep
        going until an empty page is returned or we've fetched at least
        total_item_count items."""
        ers = self._ers
        all_items = []
        page_size = 300
        offset = 0
        total = None
        while True:
            params = {"offset": offset, "limit": page_size,
                      "deployment_id": ers.deployment_id,
                      "tag_ids": "", "site_ids": site_id,
                      "target_site_type": target_site_type}
            data = ers.api.get(VM_INVENTORY_PATH, params=params)
            items = data.get("items") or []
            all_items.extend(items)
            if total is None:
                total = data.get("total_item_count")
            if not items:
                break
            offset += len(items)
            if total is not None and offset >= total:
                break
        return all_items

    # -- list -----------------------------------------------------------

    def list(self, with_site: str, details: bool = False, target_site_type: str = "VSPHERE"):
        """Lists VMs in the vSphere inventory known to a given Pure1 site."""
        ers = self._ers
        site_id = self._resolve_site_id(with_site)
        if not site_id:
            raise ValueError(f"Site '{with_site}' not found")

        items = self._inventory(site_id, target_site_type)
        if not items:
            ers.output.out("No VMs found.")
            ers.output.out_json("vms", [])
            return []

        if ers.output.format == "json":
            ers.output.out_json("vms", items)
        elif details:
            for v in items:
                ers.output.out(f"\n  {v.get('name', '-')}")
                for k, val in v.items():
                    if k != "name":
                        ers.output.out(f"    {k}: {val}")
        else:
            ers.output.out(f"\n  {'Name':<40} {'ID'}")
            ers.output.out("  " + "-" * 90)
            for v in items:
                ers.output.out(f"  {v.get('name', '-'):<40} {v.get('id', '-')}")

        ers.output.out(f"\nShowing {len(items)} VM(s) on site '{with_site}'.")
        return items

    # -- add ------------------------------------------------------------

    def add(self, *names, with_group: str, with_type: str = DEFAULT_PROTECTION_WORKFLOW,
            with_wildcard: bool = False):
        """
        Enrolls one or more VMs into an application group.

        VM names are resolved against the vSphere inventory of the
        group's own source site (the site the group was created with) —
        not a separately-specified site, since a group can only enroll
        VMs from where it's actually protecting.

        with_type sets protection_workflow ("FA_OFFLOAD" by default, or
        "VADP").
        """
        ers = self._ers
        group = self._resolve_group(with_group)
        site_id = (group.get("source_site") or {}).get("id")
        if not site_id:
            raise ValueError(f"Group '{with_group}' has no source site — can't resolve VM inventory")

        inventory = self._inventory(site_id)

        if with_wildcard:
            if len(names) != 1:
                raise ValueError(f"with_wildcard expects exactly one pattern, "
                                  f"got {len(names)}: {names!r}")
            matched = [v for v in inventory if fnmatch.fnmatch(v.get("name", ""), names[0])]
            if not matched:
                ers.output.out(f"No VMs matched pattern '{names[0]}' on group '{with_group}''s site.")
                return []
        else:
            lower = [n.strip().lower() for n in names]
            matched = [v for v in inventory if v.get("name", "").lower() in lower]
            found_lower = {v.get("name", "").lower() for v in matched}
            not_found = [n for n in names if n.strip().lower() not in found_lower]
            if not_found:
                ers.output.out(f"Warning: VMs not found in inventory: {', '.join(not_found)}")
            if not matched:
                ers.output.out("No matching VMs found — nothing to add.")
                return []

        body = [{"virtual_machine_id": v["id"], "protection_workflow": with_type} for v in matched]
        ers.api.post(ENROLLED_VMS_PATH,
                     params={"deployment_id": ers.deployment_id, "application_group_id": group["id"]},
                     body=body)

        matched_names = [v.get("name", "-") for v in matched]
        for n in matched_names:
            ers.output.out(f"Added VM '{n}' to group '{with_group}' (protection_workflow={with_type})")
        ers.output.out_json("added_vms", matched_names)
        return matched_names

    # -- remove ---------------------------------------------------------

    def remove(self, *names, with_group: str, with_wildcard: bool = False):
        """
        Unenrolls one or more VMs from an application group.

        Confirmed from real API output:
          - GET /enrolled-virtual-machines takes application_group_ids
            (PLURAL) plus offset/limit/deployment_id — for exact-name
            mode, uses names= (comma-separated); for wildcard mode,
            uses search= (substring match with '*' stripped).
          - DELETE /enrolled-virtual-machines takes application_group_id
            (SINGULAR) plus ids — note this is genuinely a different
            param name than the GET's, not a typo to "fix".
        """
        ers = self._ers
        group = self._resolve_group(with_group)
        group_id = group["id"]

        if with_wildcard:
            if len(names) != 1:
                raise ValueError(f"with_wildcard expects exactly one pattern, "
                                  f"got {len(names)}: {names!r}")
            pattern = names[0]
            filter_params = {"search": pattern.replace("*", "")}
        else:
            pattern = None
            filter_params = {"names": ",".join(n.strip() for n in names)}

        all_results = []
        offset = 0
        total = None
        while True:
            params = {"offset": offset, "limit": 300, "deployment_id": ers.deployment_id,
                      "application_group_ids": group_id}
            params.update(filter_params)
            data = ers.api.get(ENROLLED_VMS_PATH, params=params)
            items = data.get("items") or []
            all_results.extend(items)
            if total is None:
                total = data.get("total_item_count")
            if not items:
                break
            offset += len(items)
            if total is not None and offset >= total:
                break
        results = all_results

        if with_wildcard:
            matched = [v for v in results if fnmatch.fnmatch(self._enrolled_name(v), pattern)]
            if not matched:
                ers.output.out(f"No enrolled VMs matched pattern '{pattern}' in group '{with_group}'.")
                return []
        else:
            lower = [n.strip().lower() for n in names]
            matched = [v for v in results if self._enrolled_name(v).lower() in lower]
            found_lower = {self._enrolled_name(v).lower() for v in matched}
            not_found = [n for n in names if n.strip().lower() not in found_lower]
            if not_found:
                ers.output.out(f"Warning: VMs not found enrolled in group '{with_group}': "
                               f"{', '.join(not_found)}")
            if not matched:
                ers.output.out("No matching enrolled VMs found — nothing to remove.")
                return []

        ids = [v["id"] for v in matched]
        matched_names = [self._enrolled_name(v) for v in matched]

        ers.api.delete(ENROLLED_VMS_PATH,
                       params={"deployment_id": ers.deployment_id, "application_group_id": group_id,
                               "ids": ",".join(ids)})

        for n in matched_names:
            ers.output.out(f"Removed VM '{n}' from group '{with_group}'")
        ers.output.out_json("removed_vms", matched_names)
        return matched_names

    @staticmethod
    def _enrolled_name(item: dict) -> str:
        """
        Confirmed from real API output — an enrolled-virtual-machines
        search result's own top-level "name"/"id" are the ENROLLMENT's
        own identity, not the VM's. The actual VM name is nested under
        primary_virtual_machine.name (or, as a fallback, the first entry
        of virtual_machines[]).
        """
        primary = item.get("primary_virtual_machine") or {}
        if primary.get("name"):
            return primary["name"]
        vms = item.get("virtual_machines") or []
        if vms and vms[0].get("name"):
            return vms[0]["name"]
        return (item.get("name")
                or item.get("virtual_machine_name")
                or (item.get("virtual_machine") or {}).get("name")
                or "")
