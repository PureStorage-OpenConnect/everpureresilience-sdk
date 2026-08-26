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

"""ers.resources.plan — ErsInstance.plan.* namespace."""

import json
import datetime
import fnmatch

from .. import formatting
from ..config import state_path
from ..http import poll_until_terminal
from .group import GROUPS_PATH

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
            self._enrich_names(items)
            formatting.print_plans_detailed(items)
        else:
            formatting.print_plans_summary(items)

        total = data.get("total_item_count") or data.get("total", len(items))
        ers.output.out(f"\nShowing {len(items)} of {total} recovery plans.")
        ers.output.out_json("total_item_count", total)
        return items

    def _resolve(self, names):
        ers = self._ers
        data = ers.api.get(PLANS_PATH, params={"offset": 0, "limit": 300,
                                                "deployment_id": ers.deployment_id,
                                                "names": ",".join(names)})
        plans = data.get("items") or data.get("data") or []
        lname = [n.lower() for n in names]
        matched   = [p for p in plans if p.get("name", "").lower() in lname]
        not_found = [n for n in names if n.lower() not in [p.get("name", "").lower() for p in matched]]
        return matched, not_found

    def _resolve_site_id(self, site_name: str):
        ers = self._ers
        data = ers.api.get(SITES_PATH, params={"offset": 0, "limit": 300,
                                                "deployment_id": ers.deployment_id})
        sites = data.get("items") or data.get("data") or []
        for site in sites:
            if site.get("name", "").lower() == site_name.lower():
                return site["id"]
        return None

    def _resolve_group_ids(self, group_names) -> list:
        """Resolves a list of exact group names to their IDs, via the
        already-established names= filter on GET /application-groups."""
        ers = self._ers
        data = ers.api.get(GROUPS_PATH, params={"offset": 0, "limit": 300,
                                                 "deployment_id": ers.deployment_id,
                                                 "names": ",".join(group_names)})
        groups = data.get("items") or []
        lname = [n.lower() for n in group_names]
        matched = [g for g in groups if g.get("name", "").lower() in lname]
        found_lower = {g.get("name", "").lower() for g in matched}
        not_found = [n for n in group_names if n.lower() not in found_lower]
        if not_found:
            raise ValueError(f"Groups not found: {', '.join(not_found)}")
        return [g["id"] for g in matched]

    def _site_name_map(self) -> dict:
        ers = self._ers
        data = ers.api.get(SITES_PATH, params={"offset": 0, "limit": 300,
                                                "deployment_id": ers.deployment_id})
        return {s["id"]: s.get("name") for s in (data.get("items") or []) if s.get("id")}

    def _group_name_map(self) -> dict:
        ers = self._ers
        data = ers.api.get(GROUPS_PATH, params={"offset": 0, "limit": 300,
                                                 "deployment_id": ers.deployment_id})
        return {g["id"]: g.get("name") for g in (data.get("items") or []) if g.get("id")}

    def _enrich_names(self, plans: list):
        """
        Plan objects' own nested target_site/groups references come back
        with a placeholder "N/A" name from the recovery-plans endpoint —
        SITES_PATH and GROUPS_PATH return the real names, so cross-
        reference those (fetched once, not per-plan) and patch them in
        before display. Only called for --details, since it costs two
        extra API calls the plain summary view doesn't need.
        """
        site_names = self._site_name_map()
        group_names = self._group_name_map()
        for plan in plans:
            target = plan.get("target_site")
            if target and target.get("id") in site_names:
                target["name"] = site_names[target["id"]]
            for g in (plan.get("groups") or []):
                if g.get("id") in group_names:
                    g["name"] = group_names[g["id"]]

    # -- create -----------------------------------------------------------
    def create(self, name: str, with_groups, target_site: str, description: str = ""):
        """Creates a recovery plan. with_groups resolves group names to
        IDs; target_site resolves a site name to an ID."""
        ers = self._ers
        group_names = list(with_groups)
        group_ids = self._resolve_group_ids(group_names)
        target_site_id = self._resolve_site_id(target_site)
        if not target_site_id:
            raise ValueError(f"Site '{target_site}' not found")

        body = {"name": name, "description": description,
                 "group_ids": group_ids, "target_site_id": target_site_id}
        result = ers.api.post(PLANS_PATH, params={"deployment_id": ers.deployment_id}, body=body)
        items = result.get("items", [result]) if result else [{}]
        item = items[0] if items else {}

        ers.output.out(f"Created plan '{name}' (id: {item.get('id', '-')})")
        ers.output.out_json("created_plan", item)
        return item

    # -- add / remove groups ------------------------------------------------
    def add(self, name: str, with_groups):
        """Adds group(s) to an existing plan's group_ids (union with what's
        already there). The PATCH endpoint takes the full desired
        group_ids/target_site_id every time — there's no partial-add
        operation on the wire, so this reads the plan's current state
        first and PATCHes the computed union."""
        return self._patch_groups(name, list(with_groups), removing=False)

    def remove(self, name: str, with_groups):
        """Removes group(s) from an existing plan's group_ids. Same
        read-current-state-then-PATCH-the-full-list approach as add()."""
        return self._patch_groups(name, list(with_groups), removing=True)

    def _patch_groups(self, name: str, group_names: list, removing: bool):
        ers = self._ers
        matched, not_found = self._resolve([name])
        if not_found or not matched:
            raise ValueError(f"Plan '{name}' not found")
        plan = matched[0]

        existing_group_ids = [g["id"] for g in (plan.get("groups") or [])]
        changed_ids = self._resolve_group_ids(group_names)

        if removing:
            changed_set = set(changed_ids)
            new_group_ids = [gid for gid in existing_group_ids if gid not in changed_set]
        else:
            new_group_ids = list(dict.fromkeys(existing_group_ids + changed_ids))  # union, de-duped, order kept

        # Unlike create's POST body (which needs target_site_id), the PATCH
        # body here must NOT include it — confirmed: including it gets a
        # 400 "Failed to read HTTP message" even though the field is
        # otherwise valid on this same endpoint for create. The plan being
        # patched is identified via the &ids= query param (same pattern
        # as DELETE and the group enable/disable PATCH), not by matching
        # "name" in the body — confirmed: omitting it gets a 400
        # "Missing 'ids' query parameter."
        body = {"name": plan.get("name", name), "description": plan.get("description", ""),
                 "group_ids": new_group_ids}
        ers.api.patch(PLANS_PATH, params={"deployment_id": ers.deployment_id, "ids": plan["id"]},
                      body=body)

        verb = "Removed" if removing else "Added"
        prep = "from" if removing else "to"
        ers.output.out(f"{verb} group(s) {', '.join(group_names)} {prep} plan '{name}'")
        ers.output.out_json("plan_group_ids", new_group_ids)
        return new_group_ids

    # -- delete ---------------------------------------------------------------
    def delete(self, *names: str, with_wildcard: bool = False):
        """
        Deletes one or more recovery plans by name.

        Without with_wildcard: each of *names is an exact plan name.
        With with_wildcard: expects exactly one '*'-wildcard pattern in
        *names; every plan whose name matches gets deleted.
        """
        ers = self._ers

        if with_wildcard:
            if len(names) != 1:
                raise ValueError(f"with_wildcard expects exactly one pattern, "
                                  f"got {len(names)}: {names!r}")
            pattern = names[0]
            data = ers.api.get(PLANS_PATH, params={"offset": 0, "limit": 300,
                                                    "deployment_id": ers.deployment_id})
            all_items = data.get("items") or []
            matched = [p for p in all_items if fnmatch.fnmatch(p.get("name", ""), pattern)]
            if not matched:
                ers.output.out(f"No plans matched pattern '{pattern}' — nothing to delete.")
                return []
        else:
            matched, not_found = self._resolve(list(names))
            if not_found:
                ers.output.out(f"Warning: Plans not found: {', '.join(not_found)}")
            if not matched:
                ers.output.out("No matching plans found — nothing to delete.")
                return []

        ids = [p["id"] for p in matched]
        matched_names = [p.get("name", "-") for p in matched]

        ers.api.delete(PLANS_PATH, params={"deployment_id": ers.deployment_id, "ids": ",".join(ids)})

        for n in matched_names:
            ers.output.out(f"Deleted plan '{n}'")
        ers.output.out_json("deleted_plans", matched_names)
        return matched_names

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
    def failover(self, kind: str, *names, snapshot_ids=None, with_monitor: bool = False,
                 interval: int = 10, max_polls: int = 30):
        """kind: 'test' or 'prod'."""
        kind = kind.lower()
        if kind not in PLAN_TYPE_MAP:
            print(f"Error: failover kind must be 'test' or 'prod', got '{kind}'")
            return []
        return self._run_action(ACTION_NAME_MAP[kind], names, snapshot_ids, interval, max_polls,
                                 with_monitor=with_monitor)

    def cleanup(self, *names, with_monitor: bool = False, interval: int = 10, max_polls: int = 30):
        return self._run_action("cleanup", names, None, interval, max_polls, with_monitor=with_monitor)

    def failback(self, *names, site: str, snapshot_ids=None, with_monitor: bool = False,
                 interval: int = 10, max_polls: int = 30):
        return self._run_action("failback", names, snapshot_ids, interval, max_polls, site=site,
                                 with_monitor=with_monitor)

    def _run_action(self, action, names, snapshot_ids, interval, max_polls, site=None,
                     with_monitor: bool = False):
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
                # Don't poll here — collect the op and poll after all
                # cleanups are kicked off (see the batch-poll block
                # below the loop), so multiple plans run in parallel
                # rather than serially.

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

                # sync and cutover MUST be polled to completion regardless
                # of with_monitor — each one is a structural prerequisite
                # for triggering the next step, not just a status display.
                # Only the final promotion step (below) can honor
                # with_monitor, since nothing depends on knowing it
                # finished before this call returns.
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
                op_id, status, optype = self._extract(promote_result)
                optype = "FAILBACK"
                if with_monitor:
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

                # Don't poll here — collected and batch-polled after all
                # plans are kicked off (see the batch-poll block below).

            plan_state[state_key] = {"last_action": action, "last_status": status, "op_id": op_id}
            results.append({"plan": plan_name, "op_id": op_id, "status": status, "type": optype})

        # Batch-poll: for actions that kicked off multiple operations
        # above without polling inline (cleanup, failover), poll them
        # all now — they've been running in parallel on the server since
        # being kicked off, so this just waits for all to finish rather
        # than serializing them.
        if with_monitor and action in ("cleanup", "test_failover", "prod_failover"):
            for r in results:
                if r.get("op_id") and r["status"] not in ("SUCCEEDED", "FAILED", "SKIPPED"):
                    extra_params = {}
                    if action in ("test_failover", "prod_failover"):
                        extra_params = {"failover_type": FAILOVER_QUERY_TYPE_MAP[action.split("_")[0]]}
                    path = CLEANUP_PATH if action == "cleanup" else FAILOVER_PATH
                    r["status"] = poll_until_terminal(
                        ers.api, ers.deployment_id, path, r["op_id"],
                        f"{action}: {r['plan']}", interval, max_polls,
                        extra_params=extra_params if extra_params else None,
                        out=ers.output.out)
                    plan_state[r["plan"].lower()] = {"last_action": action,
                                                      "last_status": r["status"],
                                                      "op_id": r["op_id"]}

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
