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

"""ers.resources.group — ErsInstance.group.* namespace."""

import json

from .. import formatting
from ..config import state_path

GROUPS_PATH   = "/pure-protect/api/1.latest/application-groups"
PROTECT_PATH  = "/pure-protect/api/1.latest/application-groups/protection/operations"
LAST_RUN_OPS  = "last_run_ops.json"


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

    # -- enable / disable -------------------------------------------------
    def enable(self, *names):
        return self._toggle(names, enable=True)

    def disable(self, *names):
        return self._toggle(names, enable=False)

    def _toggle(self, names, enable: bool):
        ers = self._ers
        matched, not_found = self._resolve(names)
        if not_found:
            ers.output.out(f"Warning: Groups not found: {', '.join(not_found)}")
        if not matched:
            ers.output.out("No matching groups found — nothing to update.")
            return []

        results = []
        for group in matched:
            body = {"protection_state": "ENABLED" if enable else "DISABLED"}
            ers.api.patch(f"{GROUPS_PATH}/{group['id']}",
                          params={"deployment_id": ers.deployment_id}, body=body)
            ers.output.out(f"  {group['name']}: {'enabled' if enable else 'disabled'}")
            results.append(group["name"])
        return results

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
