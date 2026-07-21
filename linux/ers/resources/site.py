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

"""ers.resources.site / policy — ErsInstance.site.* and ErsInstance.policy.* namespaces."""

from .. import formatting

SITES_PATH    = "/pure-protect/api/1.latest/sites"
POLICIES_PATH = "/pure-protect/api/1.latest/service-level-policies"


class SiteResource:
    def __init__(self, ers):
        self._ers = ers

    def list(self, details: bool = False, limit: int = 25):
        ers = self._ers
        data  = ers.api.get(SITES_PATH, params={"offset": 0, "limit": limit,
                                                 "deployment_id": ers.deployment_id})
        items = data.get("items") or data.get("data") or (data if isinstance(data, list) else [data])

        if not items:
            ers.output.out("No sites found.")
            ers.output.out_json("sites", [])
            return []

        if ers.output.format == "json":
            ers.output.out_json("sites", items)
        elif details:
            formatting.print_sites_detailed(items)
        else:
            formatting.print_sites_summary(items)

        total = data.get("total_item_count") or data.get("total", len(items))
        ers.output.out(f"\nShowing {len(items)} of {total} sites.")
        ers.output.out_json("total_item_count", total)
        return items


class PolicyResource:
    def __init__(self, ers):
        self._ers = ers

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
