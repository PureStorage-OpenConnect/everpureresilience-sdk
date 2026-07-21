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
ers.workflow — ErsInstance.workflow.* namespace. Replaces ers-orchestrator.py.

`from_site` / `to_site` are site names already registered via
ErsInstance.register_site(...). For managed_failback, `to_site`
doubles as the Pure1 site name passed to plan.failback() — i.e. the
site name you register for a site must match that site's name in
Pure1 (e.g. "DC.DEV").
"""


class Workflow:
    def __init__(self, ers):
        self._ers = ers

    def managed_failover(self, *, vms_file: str, group_names: list, plan_names: list,
                          from_site: str, to_site: str,
                          with_network: bool = False, with_tags: bool = False,
                          create_missing_tags: bool = False, dry_run: bool = False,
                          interval: int = 10, max_polls: int = 30):
        ers = self._ers
        src = ers.sites.get(from_site)
        tgt = ers.sites.get(to_site)
        if not src or not tgt:
            print(f"Error: register both sites first — "
                  f"'{from_site}' and '{to_site}'")
            return False

        self._banner("MANAGED FAILOVER")
        print(f"  Plans     : {', '.join(plan_names)}")
        print(f"  Groups    : {', '.join(group_names)}")
        print(f"  VMs file  : {vms_file}")
        print(f"  From      : {from_site}   To: {to_site}")
        if dry_run:
            print(f"  Mode      : DRY RUN")

        if with_tags:
            if not dry_run:
                self._step("Capture tags from source VMs")
                src.export_tags(file=vms_file)
            else:
                self._dry(f"{from_site}.export_tags(file={vms_file!r})")

        if not dry_run:
            self._step("Power off source VMs")
            src.power_off(file=vms_file)
        else:
            self._dry(f"{from_site}.power_off(file={vms_file!r})")

        if not dry_run:
            self._step(f"Protect groups: {', '.join(group_names)}")
            ers.group.run(*group_names)
        else:
            self._dry(f"group.run({', '.join(group_names)!r})")

        if not dry_run:
            self._step(f"Production failover: {', '.join(plan_names)}")
            results = ers.plan.failover("prod", *plan_names, interval=interval, max_polls=max_polls)
            if not all(r.get("status") == "SUCCEEDED" for r in results):
                print("Error: production failover did not succeed for all plans.")
                return False
        else:
            self._dry(f"plan.failover('prod', {', '.join(plan_names)!r})")

        if with_tags:
            if not dry_run:
                self._step("Apply tags to target VMs (non-fatal on error)")
                tgt.apply_tags(file=vms_file, source=from_site, create_missing=create_missing_tags)
            else:
                self._dry(f"{to_site}.apply_tags(file={vms_file!r}, source={from_site!r}, "
                          f"create_missing={create_missing_tags})")

        if with_network and not dry_run:
            self._step("Connect VM NICs on target")
            tgt.connect_networks(file=vms_file)
        elif with_network:
            self._dry(f"{to_site}.connect_networks(file={vms_file!r})")

        self._banner("MANAGED FAILOVER COMPLETE")
        return True

    def managed_failback(self, *, vms_file: str, group_names: list, plan_names: list,
                          from_site: str, to_site: str,
                          with_network: bool = False, with_tags: bool = False,
                          create_missing_tags: bool = False, dry_run: bool = False,
                          interval: int = 10, max_polls: int = 30):
        """`to_site` is also used as the Pure1 site name for plan.failback()."""
        ers = self._ers
        src = ers.sites.get(from_site)
        tgt = ers.sites.get(to_site)
        if not src or not tgt:
            print(f"Error: register both sites first — "
                  f"'{from_site}' and '{to_site}'")
            return False

        self._banner("MANAGED FAILBACK")
        print(f"  Plans     : {', '.join(plan_names)}")
        print(f"  Groups    : {', '.join(group_names)}")
        print(f"  VMs file  : {vms_file}")
        print(f"  From      : {from_site}   To (site): {to_site}")
        if dry_run:
            print(f"  Mode      : DRY RUN")

        if with_tags:
            if not dry_run:
                self._step("Capture tags from target-side VMs")
                src.export_tags(file=vms_file)
            else:
                self._dry(f"{from_site}.export_tags(file={vms_file!r})")

        if not dry_run:
            self._step("Power off target-side VMs")
            src.power_off(file=vms_file)
        else:
            self._dry(f"{from_site}.power_off(file={vms_file!r})")

        if not dry_run:
            self._step(f"Protect groups: {', '.join(group_names)}")
            ers.group.run(*group_names)
        else:
            self._dry(f"group.run({', '.join(group_names)!r})")

        if not dry_run:
            self._step(f"Failback: {', '.join(plan_names)} -> {to_site}")
            results = ers.plan.failback(*plan_names, site=to_site,
                                         interval=interval, max_polls=max_polls)
            if not all(r.get("status") == "SUCCEEDED" for r in results):
                print("Error: failback did not succeed for all plans.")
                return False
        else:
            self._dry(f"plan.failback({', '.join(plan_names)!r}, site={to_site!r})")

        if with_tags:
            if not dry_run:
                self._step("Apply tags to source-side VMs (non-fatal on error)")
                tgt.apply_tags(file=vms_file, source=from_site, create_missing=create_missing_tags)
            else:
                self._dry(f"{to_site}.apply_tags(file={vms_file!r}, source={from_site!r}, "
                          f"create_missing={create_missing_tags})")

        if with_network and not dry_run:
            self._step("Connect VM NICs on source")
            tgt.connect_networks(file=vms_file)
        elif with_network:
            self._dry(f"{to_site}.connect_networks(file={vms_file!r})")

        self._banner("MANAGED FAILBACK COMPLETE")
        return True

    @staticmethod
    def _banner(title):
        print(f"\n{'='*60}\n  {title}\n{'='*60}")

    @staticmethod
    def _step(label):
        print(f"\n-> {label}")
        print("-" * 60)

    @staticmethod
    def _dry(cmd):
        print(f"  [DRY RUN] Would call: {cmd}")
