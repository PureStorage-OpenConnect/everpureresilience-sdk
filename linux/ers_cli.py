#!/usr/bin/env python3
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
----------------------------------------------------------------------------
Everpure Resilience service (ERS) CLI
----------------------------------------------------------------------------
Thin argparse wrapper around the `ers` package's ErsInstance class. Every
command below has a direct Python equivalent for use in your own scripts —
see the docstrings in ers/instance.py, ers/resources/*.py, and ers/workflow.py.

Auth and connection settings come from ~/.ers/config (base_url, deployment_id,
output) and ~/.ers/credentials ([ers] section for Pure1 auth, [site ...]
sections for vCenter/other infra). Use --profile to select a non-default
~/.ers/config profile.

examples:
  ers-cli --list policies|groups|plans|sites --names ... --details --limit 50
  ers-cli --group run --names group_name1,group_name2
  ers-cli --monitor group|plan --names group_name1,plan_name1
  ers-cli --profile staging --list groups

  # Test failover — auto picks latest snapshot per group
  ers-cli --plan failover --type test --names plan_name1,plan_name2

  # Prod failover
  ers-cli --plan failover --type prod --names plan_name1

  # Cleanup after test failover
  ers-cli --plan cleanup --names plan_name1

  # Failback — only runs if prod_failover SUCCEEDED, requires --site
  ers-cli --plan failback --names plan_name1 --site DC.DEV

  # Managed failover/failback across two registered sites
  ers-cli --managed-failover --from prod-dc --to dr-dc \\
             --vms-file vm-list.json --group-names G1,G2 --plan-names P1,P2 \\
             --with-tags --create-missing-tags --dry-run
  ers-cli --managed-failback --from dr-dc --to prod-dc \\
             --vms-file vm-list.json --group-names G1,G2 --plan-names P1,P2

  # Direct site actions — power, network, and tags, without a full managed workflow
  ers-cli --site prod-dc --power off --vms-file vm-list.json
  ers-cli --site prod-dc --power off --names vm-1,vm-2
  ers-cli --site prod-dc --power on  --vms-file vm-list.json
  ers-cli --site dr-dc   --connect-networks --vms-file vm-list.json
  ers-cli --site prod-dc --export-tags --vms-file vm-list.json
  ers-cli --site dr-dc   --apply-tags --source prod-dc \\
             --vms-file vm-list.json --create-missing-tags

  # Diagnose "network not found" errors — see exactly what's visible
  ers-cli --site prod-dc --list-networks
"""

import argparse
import sys

import ers
from ers.http import ApiError
from ers.sites.vsphere import VmListError, TaggingError


def csv_list(value):
    return [v.strip() for v in value.split(",")] if value else []


def main():
    parser = argparse.ArgumentParser(
        description="Everpure Resilience Service CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--profile", default="default",
                         help="~/.ers/config profile to use (default: 'default')")
    parser.add_argument("--limit", type=int, default=25, help="Max results (default: 25)")
    parser.add_argument("--details", action="store_true", help="Show detailed output")
    parser.add_argument("--names", metavar="NAME1,NAME2", help="Comma-separated names")

    parser.add_argument("--list", metavar="RESOURCE",
                         help="List a resource: policies, groups, plans, sites, snapshots")
    parser.add_argument("--group", metavar="enable|disable|run", help="Group action")
    parser.add_argument("--plan", metavar="ACTION", help="Plan action: failover, cleanup, failback")
    parser.add_argument("--type", metavar="test|prod", help="Failover type, used with --plan failover")
    parser.add_argument("--snapshot-ids", metavar="ID1,ID2", help="Explicit snapshot set IDs")
    parser.add_argument("--site", metavar="SITE_NAME",
                         help="Target site name — used with --plan failback, or with "
                              "--power/--connect-networks/--export-tags/--apply-tags "
                              "for direct site actions")
    parser.add_argument("--monitor", metavar="RESOURCE", help="Monitor: group, plan")
    parser.add_argument("--interval", type=int, default=10, help="Poll interval (s)")
    parser.add_argument("--max-polls", type=int, default=30, help="Max poll attempts")

    parser.add_argument("--power", metavar="on|off",
                         help="Power VMs on/off on --site (use with --vms-file or --names)")
    parser.add_argument("--connect-networks", action="store_true",
                         help="Reconnect VM NICs on --site (use with --vms-file or --names)")
    parser.add_argument("--list-networks", action="store_true",
                         help="Print every network name visible on --site — use this to "
                              "diagnose 'network not found' errors from --connect-networks")
    parser.add_argument("--export-tags", action="store_true",
                         help="Capture vSphere tags from VMs on --site (use with --vms-file or --names)")
    parser.add_argument("--apply-tags", action="store_true",
                         help="Apply vSphere tags to VMs on --site, captured from --source")
    parser.add_argument("--source", metavar="SITE_NAME",
                         help="Site whose captured tag state to use, with --apply-tags")

    parser.add_argument("--managed-failover", action="store_true")
    parser.add_argument("--managed-failback", action="store_true")
    parser.add_argument("--from", dest="from_site", metavar="SITE",
                         help="Source site name (already registered in credentials)")
    parser.add_argument("--to", dest="to_site", metavar="SITE",
                         help="Destination site name (for failback, also the Pure1 site name)")
    parser.add_argument("--vms-file", metavar="FILE", help="vm-list.json for managed workflows")
    parser.add_argument("--group-names", metavar="G1,G2", help="Groups for managed workflows")
    parser.add_argument("--plan-names", metavar="P1,P2", help="Plans for managed workflows")
    parser.add_argument("--with-network", action="store_true")
    parser.add_argument("--with-tags", action="store_true")
    parser.add_argument("--create-missing-tags", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    site_action = any([args.power, args.connect_networks, args.export_tags, args.apply_tags,
                       args.list_networks])

    if not any([args.list, args.group, args.plan, args.monitor,
                args.managed_failover, args.managed_failback, site_action]):
        parser.print_help()
        sys.exit(0)

    e = ers.instance(profile=args.profile)
    names = csv_list(args.names)

    if args.list:
        resource = args.list.lower()
        if resource == "policies":
            e.policy.list(details=args.details, limit=args.limit)
        elif resource == "groups":
            e.group.list(*names, details=args.details, limit=args.limit)
        elif resource == "plans":
            e.plan.list(*names, details=args.details, limit=args.limit)
        elif resource == "sites":
            e.site.list(details=args.details, limit=args.limit)
        elif resource == "snapshots":
            e.plan.snapshots(*names)
        else:
            print(f"Error: Unknown resource '{resource}'. "
                  f"Supported: policies, groups, plans, sites, snapshots")
            sys.exit(1)

    if args.group:
        action = args.group.lower()
        if not names:
            print("Error: --names is required with --group")
            sys.exit(1)
        if action == "enable":
            e.group.enable(*names)
        elif action == "disable":
            e.group.disable(*names)
        elif action == "run":
            e.group.run(*names)
        else:
            print(f"Error: --group must be enable|disable|run, got '{args.group}'")
            sys.exit(1)

    if args.plan:
        action = args.plan.lower()
        if not names:
            print("Error: --names is required with --plan")
            sys.exit(1)
        snap_ids = csv_list(args.snapshot_ids) if args.snapshot_ids else None
        if action == "failover":
            if not args.type:
                print("Error: --type test|prod is required with --plan failover")
                sys.exit(1)
            e.plan.failover(args.type, *names, snapshot_ids=snap_ids,
                             interval=args.interval, max_polls=args.max_polls)
        elif action == "cleanup":
            e.plan.cleanup(*names, interval=args.interval, max_polls=args.max_polls)
        elif action == "failback":
            if not args.site:
                print("Error: --site is required with --plan failback")
                sys.exit(1)
            e.plan.failback(*names, site=args.site, snapshot_ids=snap_ids,
                             interval=args.interval, max_polls=args.max_polls)
        else:
            print(f"Error: --plan must be failover|cleanup|failback, got '{args.plan}'")
            sys.exit(1)

    if args.monitor:
        resource = args.monitor.lower()
        if resource == "group":
            e.group.monitor(*names, interval=args.interval, max_polls=args.max_polls)
        elif resource == "plan":
            e.plan.monitor(*names, interval=args.interval, max_polls=args.max_polls)
        else:
            print(f"Error: --monitor must be group|plan, got '{args.monitor}'")
            sys.exit(1)

    if site_action:
        if not args.site:
            print("Error: --site is required with --power/--connect-networks/--export-tags/"
                  "--apply-tags/--list-networks")
            sys.exit(1)
        needs_vms = args.power or args.connect_networks or args.export_tags or args.apply_tags
        if needs_vms and not (args.vms_file or names):
            print("Error: --vms-file or --names is required for this site action")
            sys.exit(1)

        target = e.register_site(args.site)

        if args.list_networks:
            net_names = target.list_networks()
            if not net_names:
                print("No networks visible — check the connecting account's view "
                      "privileges on network objects.")
            for net_name in net_names:
                print(f"{net_name}    {net_name.encode('unicode_escape')}")

        if args.power:
            action = args.power.lower()
            if action == "on":
                target.power_on(*names, file=args.vms_file)
            elif action == "off":
                target.power_off(*names, file=args.vms_file)
            else:
                print(f"Error: --power must be 'on' or 'off', got '{args.power}'")
                sys.exit(1)

        if args.connect_networks:
            target.connect_networks(*names, file=args.vms_file)

        if args.export_tags:
            target.export_tags(*names, file=args.vms_file)

        if args.apply_tags:
            if not args.source:
                print("Error: --source SITE_NAME is required with --apply-tags")
                sys.exit(1)
            target.apply_tags(*names, file=args.vms_file, source=args.source,
                               create_missing=args.create_missing_tags)

    if args.managed_failover or args.managed_failback:
        if not (args.from_site and args.to_site and args.vms_file
                and args.group_names and args.plan_names):
            print("Error: --from, --to, --vms-file, --group-names, and --plan-names "
                  "are all required for managed workflows")
            sys.exit(1)
        e.register_site(args.from_site)
        e.register_site(args.to_site)

        kwargs = dict(
            vms_file=args.vms_file, group_names=csv_list(args.group_names),
            plan_names=csv_list(args.plan_names),
            from_site=args.from_site, to_site=args.to_site,
            with_network=args.with_network, with_tags=args.with_tags,
            create_missing_tags=args.create_missing_tags, dry_run=args.dry_run,
            interval=args.interval, max_polls=args.max_polls,
        )
        if args.managed_failover:
            e.workflow.managed_failover(**kwargs)
        else:
            e.workflow.managed_failback(**kwargs)

    e.flush()


if __name__ == "__main__":
    try:
        main()
    except (ApiError, VmListError, TaggingError) as e:
        print(f"Error: {e}")
        sys.exit(1)
