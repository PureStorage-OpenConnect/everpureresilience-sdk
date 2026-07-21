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

"""ers.resources.plan — ErsInstance.plan.* namespace."""

import json
import datetime

from .. import formatting
from ..config import state_path
from ..http import poll_until_terminal

PLANS_PATH     = "/pure-protect/api/1.latest/recovery-plans"
SNAPSHOTS_PATH = "/pure-protect/api/1.latest/recovery-plans/snapshot-sets"
FAILOVER_PATH  = "/pure-protect/api/1.latest/recovery-plans/failover/operations"
CLEANUP_PATH   = "/pure-protect/api/1.latest/recovery-plans/cleanup/operations"
FB_SYNC_PATH   = "/pure-protect/api/1.latest/recovery-plans/failback/synchronization/operations"
FB_CUTOVER_PATH = "/pure-protect/api/1.latest/recovery-plans/failback/cutover/operations"
FB_PROMOTE_PATH = "/pure-protect/api/1.latest/recovery-plans/failback/promotion/operations"
SITES_PATH     = "/pure-protect/api/1.latest/sites"

PLAN_STATE_FILE = "last_plan_ops.json"     # prerequisite state (last action + status)
PLAN_OPS_FILE   = "last_plan_run_ops.json" # op IDs from last run, used by monitor()

#: POST body "plan_type" — the real API's enum for the failover operation body
PLAN_TYPE_MAP = {"test": "TEST", "prod": "PRODUCTION"}
#: GET polling query "failover_type" — a different, abbreviated vocabulary
FAILOVER_QUERY_TYPE_MAP = {"test": "TEST", "prod": "PROD"}
ACTION_NAME_MAP   = {"test": "test_failover", "prod": "prod_failover"}

PREREQUISITES = {
    "test_failover": {"requires": None,            "must_succeed": False},
    "prod_failover": {"requires": None,            "must_succeed": False},
    "cleanup":       {"requires": "test_failover", "must_succeed": False},
    "failback":      {"requires": "prod_failover", "must_succeed": True},
}


class PlanResource:
    def __init__(self, ers):
        self._ers = ers

    # -- list -----------------------------------------------------------
    def list(self, *names, details: bool = False, limit: int = 25):
        ers = self._ers
        params = {"offset": 0, "limit": limit, "deployment_id": ers.deployment_id}
        if names:
            params["names"] = ",".join(names)

        data  = ers.api.get(PLANS_PATH, params=params)
        items = data.get("items") or data.get("data") or (data if isinstance(data, list) else [data])

        if not items:
            ers.output.out("No recovery plans found.")
            ers.output.out_json("plans", [])
            return []

        if ers.output.format == "json":
            ers.output.out_json("plans", items)
        elif details:
            formatting.print_plans_detailed(items)
        else:
            formatting.print_plans_summary(items)

        total = data.get("total_item_count") or data.get("total", len(items))
        ers.output.out(f"\nShowing {len(items)} of {total} recovery plans.")
        ers.output.out_json("total_item_count", total)
        return items

    def _resolve(self, names):
        ers = self._ers
        data = ers.api.get(PLANS_PATH, params={"offset": 0, "limit": 100,
                                                "deployment_id": ers.deployment_id})
        plans = data.get("items") or data.get("data") or []
        lname = [n.lower() for n in names]
        matched   = [p for p in plans if p.get("name", "").lower() in lname]
        not_found = [n for n in names if n.lower() not in [p.get("name", "").lower() for p in matched]]
        return matched, not_found

    def _resolve_site_id(self, site_name: str):
        ers = self._ers
        data = ers.api.get(SITES_PATH, params={"offset": 0, "limit": 100,
                                                "deployment_id": ers.deployment_id})
        sites = data.get("items") or data.get("data") or []
        for site in sites:
            if site.get("name", "").lower() == site_name.lower():
                return site["id"]
        return None

    def _latest_snapshot_ids(self, plan_id: str):
        ers = self._ers
        result = ers.api.get(SNAPSHOTS_PATH, params={"deployment_id": ers.deployment_id,
                                                       "recovery_plan_id": plan_id})
        items = result.get("items") or []
        latest = {}
        for snap in items:
            group_id   = snap.get("application_group", {}).get("id")
            created_at = snap.get("created_at", 0)
            if group_id not in latest or created_at > latest[group_id]["created_at"]:
                latest[group_id] = {"snap_id": snap["id"], "created_at": created_at,
                                     "group_name": snap.get("application_group", {}).get("name", "-")}
        return latest

    @staticmethod
    def _load_state():
        try:
            with open(state_path(PLAN_STATE_FILE), "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    @staticmethod
    def _save_state(state):
        with open(state_path(PLAN_STATE_FILE), "w") as f:
            json.dump(state, f, indent=2)

    @staticmethod
    def _load_ops():
        try:
            with open(state_path(PLAN_OPS_FILE), "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    @staticmethod
    def _save_ops(ops):
        with open(state_path(PLAN_OPS_FILE), "w") as f:
            json.dump(ops, f, indent=2)

    # -- failover ---------------------------------------------------------
    def failover(self, kind: str, *names, snapshot_ids=None, interval: int = 10, max_polls: int = 30):
        """kind: 'test' or 'prod'."""
        kind = kind.lower()
        if kind not in PLAN_TYPE_MAP:
            print(f"Error: failover kind must be 'test' or 'prod', got '{kind}'")
            return []
        return self._run_action(ACTION_NAME_MAP[kind], names, snapshot_ids, interval, max_polls)

    def cleanup(self, *names, interval: int = 10, max_polls: int = 30):
        return self._run_action("cleanup", names, None, interval, max_polls)

    def failback(self, *names, site: str, snapshot_ids=None, interval: int = 10, max_polls: int = 30):
        return self._run_action("failback", names, snapshot_ids, interval, max_polls, site=site)

    def _run_action(self, action, names, snapshot_ids, interval, max_polls, site=None):
        ers = self._ers
        matched, not_found = self._resolve(list(names))
        if not_found:
            ers.output.out(f"Warning: Plans not found: {', '.join(not_found)}")
        if not matched:
            ers.output.out("No matching plans found.")
            return []

        plan_state = self._load_state()
        prereq = PREREQUISITES[action]
        results = []

        ers.output.out(f"\nRunning '{action}' for {len(matched)} plan(s):\n")

        for plan in matched:
            plan_id, plan_name = plan["id"], plan["name"]
            state_key = plan_name.lower()

            if prereq["requires"]:
                prior = plan_state.get(state_key, {})
                if prior.get("last_action") != prereq["requires"]:
                    ers.output.out(f"  {plan_name}: SKIPPED — '{action}' requires "
                                   f"'{prereq['requires']}' to have run first.")
                    continue
                if prereq["must_succeed"] and prior.get("last_status") != "SUCCEEDED":
                    ers.output.out(f"  {plan_name}: SKIPPED — '{action}' requires "
                                   f"'{prereq['requires']}' to have SUCCEEDED.")
                    continue

            # resolve snapshots
            snaps = list(snapshot_ids) if snapshot_ids else None
            if action in ("test_failover", "prod_failover", "failback") and snaps is None:
                latest = self._latest_snapshot_ids(plan_id)
                if not latest:
                    ers.output.out(f"  {plan_name}: SKIPPED — no snapshots found.")
                    continue
                snaps = [v["snap_id"] for v in latest.values()]

            if action == "cleanup":
                result = ers.api.post(CLEANUP_PATH,
                                       params={"deployment_id": ers.deployment_id, "recovery_plan_id": plan_id},
                                       body={})
                op_id, status, optype = self._extract(result)
                status = poll_until_terminal(ers.api, ers.deployment_id, CLEANUP_PATH, op_id,
                                              action, interval, max_polls, out=ers.output.out)

            elif action == "failback":
                if not site:
                    ers.output.out(f"  {plan_name}: SKIPPED — site/to_site is required for failback.")
                    continue
                target_site_id = self._resolve_site_id(site)
                if not target_site_id:
                    ers.output.out(f"  {plan_name}: SKIPPED — site '{site}' not found.")
                    continue
                group_ids = [g["id"] for g in plan.get("groups", [])]
                if not group_ids:
                    ers.output.out(f"  {plan_name}: SKIPPED — no groups found in plan.")
                    continue

                sync_result = ers.api.post(FB_SYNC_PATH,
                    params={"deployment_id": ers.deployment_id, "recovery_plan_id": plan_id},
                    body={"target_site_id": target_site_id, "snapshot_set_ids": snaps,
                          "active_sync_application_group_ids": group_ids})
                sync_op_id, _, _ = self._extract(sync_result)
                sync_status = poll_until_terminal(ers.api, ers.deployment_id, FB_SYNC_PATH, sync_op_id,
                                                   "synchronization", interval, max_polls, out=ers.output.out)
                if sync_status != "SUCCEEDED":
                    results.append({"plan": plan_name, "step": "synchronization",
                                     "op_id": sync_op_id, "status": sync_status})
                    continue

                cutover_result = ers.api.post(FB_CUTOVER_PATH,
                    params={"deployment_id": ers.deployment_id, "recovery_plan_id": plan_id}, body={})
                cutover_op_id, _, _ = self._extract(cutover_result)
                cutover_status = poll_until_terminal(ers.api, ers.deployment_id, FB_CUTOVER_PATH, cutover_op_id,
                                                      "cutover", interval, max_polls, out=ers.output.out)
                if cutover_status != "SUCCEEDED":
                    results.append({"plan": plan_name, "step": "cutover",
                                     "op_id": cutover_op_id, "status": cutover_status})
                    continue

                promote_result = ers.api.post(FB_PROMOTE_PATH,
                    params={"deployment_id": ers.deployment_id, "recovery_plan_id": plan_id}, body={})
                op_id, _, optype = self._extract(promote_result)
                optype = "FAILBACK"
                status = poll_until_terminal(ers.api, ers.deployment_id, FB_PROMOTE_PATH, op_id,
                                              "promotion", interval, max_polls, out=ers.output.out)
                results.append({"plan": plan_name, "status": status, "steps": {
                    "synchronization": {"op_id": sync_op_id, "status": sync_status},
                    "cutover":         {"op_id": cutover_op_id, "status": cutover_status},
                    "promotion":       {"op_id": op_id, "status": status},
                }})

                ops = self._load_ops()
                ops[state_key] = {"op_id": op_id, "last_action": action,
                                   "plan_id": plan_id, "plan_name": plan_name}
                self._save_ops(ops)
                plan_state[state_key] = {"last_action": action, "last_status": status, "op_id": op_id}
                self._save_state(plan_state)
                continue

            else:  # test_failover / prod_failover
                body = {"plan_type": PLAN_TYPE_MAP[action.split("_")[0]],
                         "scale": 0, "snapshot_set_ids": snaps}
                result = ers.api.post(FAILOVER_PATH,
                                       params={"deployment_id": ers.deployment_id, "recovery_plan_id": plan_id},
                                       body=body)
                op_id, status, optype = self._extract(result)

                ops = self._load_ops()
                ops[state_key] = {"op_id": op_id, "last_action": action,
                                   "plan_id": plan_id, "plan_name": plan_name}
                self._save_ops(ops)

                extra = {"failover_type": FAILOVER_QUERY_TYPE_MAP[action.split("_")[0]]}
                status = poll_until_terminal(ers.api, ers.deployment_id, FAILOVER_PATH, op_id,
                                              action, interval, max_polls, extra_params=extra,
                                              out=ers.output.out)

            plan_state[state_key] = {"last_action": action, "last_status": status, "op_id": op_id}
            results.append({"plan": plan_name, "op_id": op_id, "status": status, "type": optype})

        self._save_state(plan_state)
        ers.output.out_json("plan_run", results)
        return results

    @staticmethod
    def _extract(result):
        items = result.get("items", [result] if result else [])
        item  = items[0] if items else {}
        return item.get("id", "-"), item.get("status", "-"), item.get("type", "-")

    # -- monitor ------------------------------------------------------------
    def monitor(self, *names, interval: int = 10, max_polls: int = 30):
        import time
        ers = self._ers
        try:
            op_map = self._load_ops()
        except FileNotFoundError:
            print("Error: No recent plan run found. Run plan.failover/cleanup/failback first.")
            return {}

        if names:
            lname = [n.lower() for n in names]
            op_map = {k: v for k, v in op_map.items() if k.lower() in lname}

        if not op_map:
            print("Error: No op IDs found to monitor.")
            return {}

        TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "COMPLETED"}
        states = {name: {**entry, "status": "UNKNOWN", "optype": "-", "finished_at": "-"}
                  for name, entry in op_map.items()}

        print(f"\nMonitoring {len(states)} plan operation(s). Polling every {interval}s "
              f"(max {max_polls}). Ctrl+C to stop.\n")

        path_map = {
            "test_failover": FAILOVER_PATH, "prod_failover": FAILOVER_PATH,
            "failback": FB_PROMOTE_PATH, "cleanup": CLEANUP_PATH,
        }

        for poll in range(1, max_polls + 1):
            print(f"[Poll {poll}/{max_polls}]")
            all_done = True
            for name, state in states.items():
                if state["status"] in TERMINAL:
                    continue
                all_done = False
                action = state["last_action"]
                params = {"offset": 0, "limit": 25, "deployment_id": ers.deployment_id, "ids": state["op_id"]}
                action_kind = action.split("_")[0]
                if action_kind in FAILOVER_QUERY_TYPE_MAP:
                    params["failover_type"] = FAILOVER_QUERY_TYPE_MAP[action_kind]
                result = ers.api.get(path_map.get(action, FAILOVER_PATH), params=params)
                op_items = result.get("items", [])
                op = op_items[0] if op_items else {}
                status, optype = op.get("status", "UNKNOWN"), op.get("type", "-")
                state.update({"status": status, "optype": optype})
                print(f"  {state['plan_name']:<40} {state['op_id']:<38} {status:<16} {optype:<12}")

                if status in TERMINAL:
                    plan_state = self._load_state()
                    plan_state[name] = {"last_action": action, "last_status": status, "op_id": state["op_id"]}
                    self._save_state(plan_state)
            print()
            if all_done:
                print("All plan operations reached a terminal state.")
                break
            if poll < max_polls:
                try:
                    time.sleep(interval)
                except KeyboardInterrupt:
                    print("\nMonitoring stopped.")
                    break
        else:
            print(f"Max polls ({max_polls}) reached — some operations may still be running.")

        ers.output.out_json("plan_monitor", [
            {"plan": s["plan_name"], "op_id": s["op_id"], "status": s["status"], "type": s["optype"]}
            for s in states.values()
        ])
        return states

    # -- snapshots ------------------------------------------------------------
    def snapshots(self, *names):
        ers = self._ers
        if not names:
            print("Error: at least one plan name is required")
            return
        matched, not_found = self._resolve(list(names))
        if not_found:
            print(f"Warning: Plans not found: {', '.join(not_found)}")
        if not matched:
            print("No matching plans found.")
            return

        for plan in matched:
            result = ers.api.get(SNAPSHOTS_PATH, params={
                "deployment_id": ers.deployment_id, "recovery_plan_id": plan["id"]})
            items = result.get("items") or []
            total = result.get("total_item_count", len(items))

            if ers.output.format == "json":
                key = plan["name"].lower().replace(" ", "_") + "_snapshots"
                ers.output.out_json(key, {"plan_id": plan["id"], "plan_name": plan["name"],
                                           "total_item_count": total, "items": items})
                continue

            formatting.print_snapshots(plan["name"], plan["id"], items, total, ers.output.out)
