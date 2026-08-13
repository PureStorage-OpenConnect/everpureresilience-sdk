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

"""ers.resources.policy — ErsInstance.policy.* namespace."""

import fnmatch

from .. import formatting

POLICIES_PATH = "/pure-protect/api/1.latest/service-level-policies"


class PolicyResource:
    #: Pure1's site_type enum for the create body. Both values confirmed.
    SITE_TYPE_MAP = {"vmw": "VSPHERE", "aws": "AWS"}

    def __init__(self, ers):
        self._ers = ers

    def create(self, name: str, rpo_minutes: int, target_type: str,
               local_retention_hours: int, remote_retention_hours: int,
               estimated_rto_hours: int = 0, description: str = ""):
        """
        Create a service level policy.

        rpo_minutes may be 0. local/remote/estimated_rto are in hours.
        target_type is 'vmw' or 'aws'.

        rpo, retention, and estimated_rto are all plain integer
        milliseconds on the wire — engineer-confirmed against a real
        request. This method converts minutes/hours to ms for you.

        replication_strategy.ordinal is 0 (the local/source side);
        the replication target's ordinal is 1 — engineer-confirmed,
        not what the API docs' own example showed (which used 1 for
        both).
        """
        ers = self._ers
        site_type = self.SITE_TYPE_MAP.get(target_type.lower())
        if not site_type:
            raise ValueError(f"target_type must be one of {sorted(self.SITE_TYPE_MAP)}, "
                              f"got {target_type!r}")

        body = {
            "name": name,
            "description": description,
            "rpo": rpo_minutes * 60_000,  # minutes -> ms
            "replication_strategy": {
                "ordinal": 0,
                "site_type": site_type,
                "retention": local_retention_hours * 3_600_000,  # hours -> ms
                "replication_targets": [
                    {
                        "ordinal": 1,
                        "site_type": site_type,
                        "retention": remote_retention_hours * 3_600_000,  # hours -> ms
                        "estimated_rto": estimated_rto_hours * 3_600_000,  # hours -> ms
                        "replication_targets": [],
                    }
                ],
            },
        }

        result = ers.api.post(POLICIES_PATH, params={"deployment_id": ers.deployment_id}, body=body)
        items = result.get("items", [result]) if result else [{}]
        item = items[0] if items else {}

        ers.output.out(f"Created policy '{name}' (id: {item.get('id', '-')})")
        ers.output.out_json("created_policy", item)
        return item

    def delete(self, *names: str, with_wildcard: bool = False):
        """
        Delete one or more service level policies by name.

        Without with_wildcard: each of *names is an exact policy name to
        delete (case-insensitive match).

        With with_wildcard: expects exactly one pattern in *names, using
        '*' as a multi-character wildcard (fnmatch-style) — every policy
        whose name matches gets deleted. e.g.
        delete("policy-name-prefix*", with_wildcard=True)

        The API's delete endpoint takes policy IDs, not names, so this
        resolves names/pattern -> IDs via list() first.
        """
        ers = self._ers
        data = ers.api.get(POLICIES_PATH, params={"offset": 0, "limit": 300,
                                                    "deployment_id": ers.deployment_id})
        all_items = data.get("items") or []

        if with_wildcard:
            if len(names) != 1:
                raise ValueError("with_wildcard expects exactly one pattern, "
                                  f"got {len(names)}: {names!r}")
            pattern = names[0]
            matched = [p for p in all_items if fnmatch.fnmatch(p.get("name", ""), pattern)]
            if not matched:
                ers.output.out(f"No policies matched pattern '{pattern}' — nothing to delete.")
                return []
        else:
            lower_names = [n.strip().lower() for n in names]
            matched = [p for p in all_items if p.get("name", "").lower() in lower_names]
            found_lower = {p.get("name", "").lower() for p in matched}
            not_found = [n for n in names if n.strip().lower() not in found_lower]
            if not_found:
                ers.output.out(f"Warning: policies not found: {', '.join(not_found)}")
            if not matched:
                ers.output.out("No matching policies found — nothing to delete.")
                return []

        ids = [p["id"] for p in matched]
        matched_names = [p.get("name", "-") for p in matched]

        ers.api.delete(POLICIES_PATH, params={"deployment_id": ers.deployment_id,
                                               "ids": ",".join(ids)})

        for n in matched_names:
            ers.output.out(f"Deleted policy '{n}'")
        ers.output.out_json("deleted_policies", matched_names)
        return matched_names

    def list(self, details: bool = False, limit: int = 25):
        ers = self._ers
        data  = ers.api.get(POLICIES_PATH, params={"offset": 0, "limit": limit,
                                                    "deployment_id": ers.deployment_id})
        items = data.get("items") or data.get("data") or (data if isinstance(data, list) else [data])

        if not items:
            ers.output.out("No policies found.")
            ers.output.out_json("policies", [])
            return []

        if ers.output.format == "json":
            ers.output.out_json("policies", items)
        elif details:
            formatting.print_policies_detailed(items)
        else:
            formatting.print_policies_summary(items)

        total = data.get("total_item_count") or data.get("total", len(items))
        ers.output.out(f"\nShowing {len(items)} of {total} policies.")
        ers.output.out_json("total_item_count", total)
        return items
