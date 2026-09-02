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

  --list -- list a resource
  ers-cli --list policies|groups|plans|sites|snapshots --names ... --details --limit 50
  ers-cli --list vms --with-site site1

  --site -- direct actions against a registered vCenter site
  ers-cli --site site1 --power off --vms-file vm-list.json
  ers-cli --site site1 --power off --names vm1,vm2
  ers-cli --site site1 --power on  --vms-file vm-list.json
  ers-cli --site site2 --connect-networks --vms-file vm-list.json
  ers-cli --site site1 --export-tags --vms-file vm-list.json
  ers-cli --site site2 --apply-tags --source site1 \\
             --vms-file vm-list.json --create-missing-tags
  ers-cli --site site1 --list-networks    # diagnose "network not found" errors

  # Clone a single VM from a template
  ers-cli --site site1 --create-vm --name vm1 --template golden-template \\
             --resource-pool Resources --datastore datastore1 --network "VM Network"

  # Clone N VMs from a template (auto-numbered, e.g. ubuntu-tst-001, ubuntu-tst-002, ...)
  ers-cli --site site1 --create-vm --name-prefix ubuntu-tst- --count 10 \\
             --template golden-template --resource-pool Resources --datastore datastore1

  # Delete a single VM (powers off first if running)
  ers-cli --site site1 --delete-vm --name vm1

  # Delete N VMs by name-prefix/count (same naming as --create-vm)
  ers-cli --site site1 --delete-vm --name-prefix ubuntu-tst- --count 10

  --policy -- service level policies (rpo in minutes; retention and rto in hours)
  ers-cli --policy create --name policy1 --rpo 15 --target-type vmw \\
             --local-retention 24 --remote-retention 72 --estimated-rto 1
  ers-cli --policy create --name policy1 --rpo 60 --source-type vmw --target-type aws \\
             --local-retention 24 --remote-retention 24 --estimated-rto 1
  ers-cli --policy delete --names policy1,policy2
  ers-cli --policy delete --names "policy*"

  --group -- application groups
  ers-cli --group create --name group1 --with-policy policy1 \\
             --source-site site1 --target-site site2
  ers-cli --group enable --names group1,group2
  ers-cli --group disable --names "group1*"
  ers-cli --group run --names group1,group2                     # kick off, return op-ids
  ers-cli --group run --names group1,group2 --with-monitor       # kick off, poll to terminal state
  ers-cli --group delete --names group1,group2
  ers-cli --group delete --names "group1*"

  --vm -- enroll/unenroll VMs in an application group
  ers-cli --vm add --names vm1,vm2 --with-group group1
  ers-cli --vm add --names vm1,vm2 --with-group group1 --with-type VADP
  ers-cli --vm add --names "vm*" --with-group group1
  ers-cli --vm remove --names vm1,vm2 --with-group group1
  ers-cli --vm remove --names "vm*" --with-group group1

  --plan -- recovery plans
  ers-cli --plan create --name plan1 --with-groups group1,group2 --target-site site1
  ers-cli --plan add --names plan1 --with-groups group1,group2
  ers-cli --plan remove --names plan1 --with-groups group1,group2
  ers-cli --plan delete --names plan1,plan2
  ers-cli --plan delete --names "plan*"
  ers-cli --plan failover --type test --names plan1,plan2   # kick off, return op-id (auto picks latest snapshot per group)
  ers-cli --plan failover --type test --names plan1,plan2 --with-monitor   # kick off + poll to terminal
  ers-cli --plan failover --type prod --names plan1
  ers-cli --plan cleanup --names plan1
  ers-cli --plan failback --names plan1 --site site1   # only runs if prod_failover SUCCEEDED
             # (sync/cutover always poll internally -- required to sequence the steps --
             # --with-monitor only affects whether the final promotion step is polled too)

  --managed -- orchestrated failover/failback across two registered sites
  ers-cli --managed failover --from site1 --to site2 \\
             --vms-file vm-list.json --group-names group1,group2 --plan-names plan1,plan2 \\
             --with-tags --create-missing-tags --dry-run

  ers-cli --managed failback --from site2 --to site1 \\
             --vms-file vm-list.json --group-names group1,group2 --plan-names plan1,plan2

  other
  ers-cli --monitor group|plan --names group1,plan1
  ers-cli --profile staging --list groups
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

    parser.add_argument("--version", action="version", version=f"ers-cli {ers.__version__}")
    parser.add_argument("--profile", default="default",
                         help="~/.ers/config profile to use (default: 'default')")
    parser.add_argument("--limit", type=int, default=25, help="Max results (default: 25)")
    parser.add_argument("--details", action="store_true", help="Show detailed output")
    parser.add_argument("--names", metavar="NAME1,NAME2", help="Comma-separated names")
    parser.add_argument("--name", metavar="NAME",
                         help="A single name — used with --policy/--group/--plan create and "
                              "--create-vm (single-VM mode), which each always create exactly "
                              "one resource")

    parser.add_argument("--list", metavar="RESOURCE",
                         help="List a resource: policies, groups, plans, sites, snapshots, vms")
    parser.add_argument("--with-site", metavar="SITE_NAME", help="Site name, used with --list vms")
    parser.add_argument("--vm", metavar="ACTION", help="VM action: add, remove")
    parser.add_argument("--with-group", metavar="GROUP_NAME",
                         help="Application group name, used with --vm add/remove")
    parser.add_argument("--with-type", metavar="FA_OFFLOAD|VADP", default="FA_OFFLOAD",
                         help="Protection workflow (default: FA_OFFLOAD), used with --vm add")
    parser.add_argument("--group", metavar="ACTION", help="Group action: create, enable, disable, run, delete")
    parser.add_argument("--policy", metavar="ACTION", help="Policy action: create, delete")
    parser.add_argument("--with-policy", metavar="POLICY_NAME",
                         help="Service level policy name, used with --group create")
    parser.add_argument("--source-site", metavar="SITE_NAME",
                         help="Source site name, used with --group create")
    parser.add_argument("--target-site", metavar="SITE_NAME",
                         help="Target site name, used with --group create")
    parser.add_argument("--rpo", type=int, metavar="MINUTES",
                         help="RPO in minutes (0 allowed)")
    parser.add_argument("--target-type", metavar="vmw|aws",
                         help="Replication target platform")
    parser.add_argument("--source-type", metavar="vmw|aws", default="vmw",
                         help="Source provider platform (default: vmw)")
    parser.add_argument("--local-retention", type=int, metavar="HOURS",
                         help="Local snapshot retention in hours")
    parser.add_argument("--remote-retention", type=int, metavar="HOURS",
                         help="Remote snapshot retention in hours")
    parser.add_argument("--estimated-rto", type=int, metavar="HOURS",
                         help="Estimated recovery time objective in hours")
    parser.add_argument("--description", metavar="TEXT", default="",
                         help="Optional description")
    parser.add_argument("--plan", metavar="ACTION",
                         help="Plan action: create, add, remove, delete, failover, cleanup, failback")
    parser.add_argument("--with-groups", metavar="G1,G2",
                         help="Comma-separated group names, used with --plan create/add/remove")
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
    parser.add_argument("--list-folders", action="store_true",
                         help="Print every VM folder's full path visible on --site — use this "
                              "to diagnose 'folder not found' errors from --create-vm")
    parser.add_argument("--export-tags", action="store_true",
                         help="Capture vSphere tags from VMs on --site (use with --vms-file or --names)")
    parser.add_argument("--apply-tags", action="store_true",
                         help="Apply vSphere tags to VMs on --site, captured from --source")
    parser.add_argument("--source", metavar="SITE_NAME",
                         help="Site whose captured tag state to use, with --apply-tags")

    parser.add_argument("--create-vm", action="store_true",
                         help="Clone VM(s) from a template on --site — a single VM via --name, "
                              "or --count VMs via --name-prefix (zero-padded 3-digit numbering)")
    parser.add_argument("--delete-vm", action="store_true",
                         help="Delete VM(s) on --site — a single VM via --name, or --count VMs "
                              "via --name-prefix (same naming as --create-vm). Powers off first "
                              "if running, then destroys.")
    parser.add_argument("--template", metavar="TEMPLATE_NAME", help="Template to clone from")
    parser.add_argument("--resource-pool", metavar="POOL_NAME", default="Resources",
                         help="Target resource pool (default: 'Resources', vCenter's standard "
                              "name for a cluster/host's default root resource pool)")
    parser.add_argument("--datastore", metavar="DATASTORE_NAME", help="Target datastore")
    parser.add_argument("--network", metavar="NETWORK_NAME",
                         help="Reconnect the clone's first NIC to this network (optional — "
                              "otherwise it inherits the template's network)")
    parser.add_argument("--folder", metavar="FOLDER_NAME",
                         help="VM folder for the clone (optional — otherwise same folder as the template)")
    parser.add_argument("--power-on", action="store_true",
                         help="Power on the clone(s) immediately after creation (default: stay off)")
    parser.add_argument("--name-prefix", metavar="PREFIX",
                         help="Name prefix for --count VMs, e.g. 'ubuntu-tst-' -> ubuntu-tst-001, ...")
    parser.add_argument("--count", type=int, metavar="N", help="Number of VMs to create from --name-prefix")
    parser.add_argument("--start-index", type=int, default=1,
                         help="First number used with --name-prefix (default: 1)")

    parser.add_argument("--managed", metavar="ACTION", help="Managed workflow: failover, failback")
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
    parser.add_argument("--with-monitor", action="store_true",
                         help="Poll to a terminal state after kicking off — used with --group "
                              "run and --plan failover/cleanup/failback. Without it, the "
                              "command just kicks off and returns the op ID(s); monitor "
                              "separately with --monitor group|plan.")

    args = parser.parse_args()

    site_action = any([args.power, args.connect_networks, args.export_tags, args.apply_tags,
                       args.list_networks, args.list_folders, args.create_vm, args.delete_vm])

    if not any([args.list, args.group, args.policy, args.vm, args.plan, args.monitor,
                args.managed, site_action]):
        parser.print_help()
        sys.exit(0)

    e = ers.instance(profile=args.profile)
    names = csv_list(args.names)
    # Wildcard mode is inferred automatically from a literal '*' anywhere in --names.
    wildcard = any("*" in n for n in names)

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
        elif resource == "vms":
            if not args.with_site:
                print("Error: --with-site is required with --list vms")
                sys.exit(1)
            e.vm.list(with_site=args.with_site, details=args.details)
        else:
            print(f"Error: Unknown resource '{resource}'. "
                  f"Supported: policies, groups, plans, sites, snapshots, vms")
            sys.exit(1)

    if args.group:
        action = args.group.lower()
        if action == "create":
            missing = [flag for flag, val in [
                ("--name", args.name), ("--with-policy", args.with_policy),
                ("--source-site", args.source_site), ("--target-site", args.target_site),
            ] if val is None]
            if missing:
                print(f"Error: --group create requires {', '.join(missing)}")
                sys.exit(1)
            e.group.create(name=args.name, with_policy=args.with_policy,
                            source_site=args.source_site, target_site=args.target_site)
        elif action in ("enable", "disable", "delete"):
            if not names:
                print(f"Error: --names is required with --group {action}")
                sys.exit(1)
            if wildcard and len(names) != 1:
                print("Error: a wildcard pattern in --names must be the only value given")
                sys.exit(1)
            if action == "enable":
                e.group.enable(*names, with_wildcard=wildcard)
            elif action == "disable":
                e.group.disable(*names, with_wildcard=wildcard)
            else:
                e.group.delete(*names, with_wildcard=wildcard)
        elif action == "run":
            if not names:
                print("Error: --names is required with --group run")
                sys.exit(1)
            e.group.run(*names, with_monitor=args.with_monitor)
        else:
            print(f"Error: --group must be create|enable|disable|run|delete, got '{args.group}'")
            sys.exit(1)

    if args.policy:
        action = args.policy.lower()
        if action == "create":
            missing = [flag for flag, val in [
                ("--name", args.name), ("--rpo", args.rpo), ("--target-type", args.target_type),
                ("--local-retention", args.local_retention), ("--remote-retention", args.remote_retention),
                ("--estimated-rto", args.estimated_rto),
            ] if val is None]
            if missing:
                print(f"Error: --policy create requires {', '.join(missing)}")
                sys.exit(1)
            e.policy.create(name=args.name, rpo_minutes=args.rpo, target_type=args.target_type,
                             local_retention_hours=args.local_retention,
                             remote_retention_hours=args.remote_retention,
                             estimated_rto_hours=args.estimated_rto,
                             description=args.description,
                             source_type=args.source_type)
        elif action == "delete":
            if not names:
                print("Error: --names is required with --policy delete")
                sys.exit(1)
            if wildcard and len(names) != 1:
                print("Error: a wildcard pattern in --names must be the only value given")
                sys.exit(1)
            e.policy.delete(*names, with_wildcard=wildcard)
        else:
            print(f"Error: --policy must be create|delete, got '{args.policy}'")
            sys.exit(1)

    if args.vm:
        action = args.vm.lower()
        if action not in ("add", "remove"):
            print(f"Error: --vm must be add|remove, got '{args.vm}'")
            sys.exit(1)
        if not args.with_group:
            print(f"Error: --with-group is required with --vm {action}")
            sys.exit(1)
        if wildcard:
            if not names or len(names) != 1:
                print("Error: a wildcard pattern in --names must be the only value given")
                sys.exit(1)
            vm_names = tuple(names)
        else:
            if not names:
                print(f"Error: --names is required with --vm {action}")
                sys.exit(1)
            vm_names = tuple(names)
        if action == "add":
            e.vm.add(*vm_names, with_group=args.with_group, with_type=args.with_type,
                     with_wildcard=wildcard)
        else:
            e.vm.remove(*vm_names, with_group=args.with_group, with_wildcard=wildcard)

    if args.plan:
        action = args.plan.lower()

        if action == "create":
            if not args.name:
                print("Error: --plan create requires --name")
                sys.exit(1)
            if not args.with_groups or not args.target_site:
                print("Error: --plan create requires --with-groups and --target-site")
                sys.exit(1)
            group_names = csv_list(args.with_groups)
            e.plan.create(name=args.name, with_groups=group_names, target_site=args.target_site,
                           description=args.description)
        elif action in ("add", "remove", "delete", "failover", "cleanup", "failback"):
            if not names:
                print("Error: --names is required with --plan")
                sys.exit(1)
            if action in ("add", "remove"):
                if len(names) != 1:
                    print(f"Error: --plan {action} requires exactly one name via --names")
                    sys.exit(1)
                if not args.with_groups:
                    print(f"Error: --plan {action} requires --with-groups")
                    sys.exit(1)
                group_names = csv_list(args.with_groups)
                if action == "add":
                    e.plan.add(names[0], group_names)
                else:
                    e.plan.remove(names[0], group_names)
            elif action == "delete":
                if wildcard and len(names) != 1:
                    print("Error: a wildcard pattern in --names must be the only value given")
                    sys.exit(1)
                e.plan.delete(*names, with_wildcard=wildcard)
            elif action == "failover":
                if not args.type:
                    print("Error: --type test|prod is required with --plan failover")
                    sys.exit(1)
                snap_ids = csv_list(args.snapshot_ids) if args.snapshot_ids else None
                e.plan.failover(args.type, *names, snapshot_ids=snap_ids, with_monitor=args.with_monitor,
                                 interval=args.interval, max_polls=args.max_polls)
            elif action == "cleanup":
                e.plan.cleanup(*names, with_monitor=args.with_monitor,
                                interval=args.interval, max_polls=args.max_polls)
            elif action == "failback":
                if not args.site:
                    print("Error: --site is required with --plan failback")
                    sys.exit(1)
                snap_ids = csv_list(args.snapshot_ids) if args.snapshot_ids else None
                e.plan.failback(*names, site=args.site, snapshot_ids=snap_ids, with_monitor=args.with_monitor,
                                 interval=args.interval, max_polls=args.max_polls)
        else:
            print(f"Error: --plan must be create|add|remove|delete|failover|cleanup|failback, "
                  f"got '{args.plan}'")
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
                  "--apply-tags/--list-networks/--create-vm/--delete-vm")
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

        if args.list_folders:
            folder_paths = target.list_folders()
            if not folder_paths:
                print("No folders visible — check the connecting account's view "
                      "privileges on folder objects.")
            for path in folder_paths:
                print(path)

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

        if args.create_vm:
            if not (args.template and args.datastore):
                print("Error: --create-vm requires --template and --datastore")
                sys.exit(1)
            batch_mode = bool(args.name_prefix or args.count)
            if batch_mode:
                if not (args.name_prefix and args.count):
                    print("Error: batch VM creation requires both --name-prefix and --count")
                    sys.exit(1)
                target.create_vms(name_prefix=args.name_prefix, count=args.count,
                                   template=args.template, resource_pool=args.resource_pool,
                                   datastore=args.datastore, network=args.network,
                                   folder=args.folder, power_on=args.power_on,
                                   start_index=args.start_index)
            else:
                if not args.name:
                    print("Error: --create-vm without --name-prefix/--count requires --name")
                    sys.exit(1)
                target.create_vm(name=args.name, template=args.template,
                                  resource_pool=args.resource_pool, datastore=args.datastore,
                                  network=args.network, folder=args.folder, power_on=args.power_on)

        if args.delete_vm:
            batch_mode = bool(args.name_prefix or args.count)
            if batch_mode:
                if not (args.name_prefix and args.count):
                    print("Error: batch VM deletion requires both --name-prefix and --count")
                    sys.exit(1)
                target.delete_vms(name_prefix=args.name_prefix, count=args.count,
                                   start_index=args.start_index)
            else:
                if not args.name:
                    print("Error: --delete-vm without --name-prefix/--count requires --name")
                    sys.exit(1)
                target.delete_vm(name=args.name)

    if args.managed:
        action = args.managed.lower()
        if action not in ("failover", "failback"):
            print(f"Error: --managed must be failover|failback, got '{args.managed}'")
            sys.exit(1)
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
        if action == "failover":
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
