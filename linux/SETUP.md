# ERS SDK — Setup

## License

Apache License, Version 2.0 — see `LICENSE`. Source files carry the standard
Apache header; `NOTICE` carries the project attribution.

## Install

```bash
# From a git repo (tag, branch, or commit):
pip install "git+https://github.com/PureStorage-OpenConnect/everpureresilience-sdk.git@v2.7.0#subdirectory=linux"

# Or, once published to a private index (configured in pip.conf / --index-url):
pip install ers-sdk
```

This installs `PyJWT`, `cryptography`, `requests`, and `pyVmomi`
automatically (declared in `pyproject.toml`), plus two console scripts on
your `PATH`: `ers-cli` and `ers-system-test`.

**Running from a cloned source tree instead, without installing?** Then
nothing installs those dependencies for you, so grab them manually first:
```bash
pip install PyJWT cryptography requests pyVmomi
```
and invoke the scripts directly: `python3 ers_cli.py ...` / `python3 ers_system_test.py ...`.
Everything below assumes the installed `ers-cli`/`ers-system-test` commands;
substitute accordingly if you're running this way.

## 1. `~/.ers/config` — non-secret settings, profiles like `~/.aws/config`

```ini
[default]
base_url      = https://api.pure1.purestorage.com
deployment_id = your-deployment-id
output        = txt
```

> Note: Get your deployment-id from Pure1 > Resilience > Your Deployment (ID).
> It will look something like eg. c951a9875de48435ea37876a5acf9af83

## 2. `~/.ers/credentials` — secrets (chmod 600 recommended; a warning is printed if not)

```ini
[ers]
app_id           = pure1:apikey:YOUR_APP_ID
private_key_path = ~/.ers/ers-private.pem

[site vsphere prod-site]
host = vcenter-source.example.com
user = administrator@vsphere.local
pass = yourpassword
insecure = true

[site vsphere drdc-site]
host = vcenter-target.example.com
user = administrator@vsphere.local
pass = yourpassword
```

```bash
# Generate private key
openssl genrsa -out ~/.ers/ers-private.pem 2048

# Extract public key
openssl rsa -in ~/.ers/ers-private.pem -pubout -out ers-public.pem
```

> Register `ers-public.pem` in Pure1:
> 1. Log in to `https://pure1.purestorage.com`
> 2. Go to **Administration → API Registration**
> 3. Create or update your API key and paste the contents of `ers-public.pem`
> 4. Use the Resource Operator Role for Permissions
> 5. Note your **Application ID** (format: `pure1:apikey:xxxxxxxxxx`)

> Note the naming: register a site with the same name in Pure1 > Resilience >
> Deployment > Sites > your-site-name
> In the example above, prod-site and drdc-site are names used when the sites are
> created. The names can be updated in Pure1, but MUST match what is in the
> credentials file for the automation to work.

## 3. The vm-list file

JSON format - expected to be machine-generated from a CSV export or an RVTools
report rather than hand-authored:

```json
{
  "schema_version": 2,
  "generated_from": "rvtools_export_2026-07-15.xlsx",
  "generated_at": "2026-07-15T14:30:00Z",
  "vms": [
    {
      "name": "vm-1",
      "networks": {
        "prod-site": ["prod-vm-portgroup-01", "prod-dmz-vlan-01"],
        "drdc-site": ["drdc-vm-portgroup-01", "drdc-dmz-vlan-02"]
      }
    },
    {"name": "vm-2", "networks": {"prod-site": ["prod-vm-network"]}},
    {"name": "vm-3"}
  ]
}
```

- `schema_version` is required and validated — `2` is the only supported value today.
- `generated_from`/`generated_at` are optional provenance, not read by ERS, but useful in a DR runbook.
- Each VM needs a `name` matching the vCenter inventory exactly; duplicate names are rejected at load time.
- `networks`, if present, is a **dict keyed by registered site name** — the same names you pass to `register_site(...)` and that appear in `~/.ers/credentials` as `[site vsphere prod-site]`. Each `VSphereSite.connect_networks()` call picks its own entry by its own name (`self.name`), so **one vm-list.json drives failover, failback, and any further site in the same chain** — no separate file or parameter needed per direction. Within a site's list, entries are ordered and mapped to NIC 1, NIC 2, ... by position.
  - If a VM has no `networks` field at all, `connect_networks()` just ensures its NICs are connected on their current backing — no warning, this is the normal case for VMs that don't need network reconfiguration.
  - If a VM *has* a `networks` dict but it's missing the entry for the site you're calling `connect_networks()` on, that's flagged as a warning (likely a config gap) rather than silently skipped.

## 4. Use it as a library

Every namespace below (`e.policy`, `e.group`, `e.vm`, `e.plan`, `e.sites[...]`,
`e.workflow`) has a matching `ers-cli` command in section 5 — the CLI is a
thin wrapper over exactly these calls.

```python
import ers

e = ers.instance()                    # reads ~/.ers/config + credentials, auths automatically
e.register_site("prod-site")          # opens its own SmartConnect using credentials file
e.register_site("drdc-site", si)      # or wrap an si you already connected yourself

# Policies, groups, plans — list/create/delete
e.policy.list()
e.policy.create(name="policy1", rpo_minutes=15, target_type="vmw",
                 local_retention_hours=24, remote_retention_hours=72)
e.policy.delete("policy1", "policy2")             # exact names
e.policy.delete("policy*", with_wildcard=True)    # or a wildcard pattern

e.group.list()
e.group.create(name="group1", with_policy="policy1",
                source_site="prod-site", target_site="drdc-site")
e.group.enable("group1", "group2")
e.group.disable("group1", with_wildcard=True)
e.group.run("group1", "group2")                   # kick off, return op-id(s)
e.group.run("group1", "group2", with_monitor=True) # kick off, poll to a terminal state
e.group.delete("group1", "group2")

e.plan.list()
e.plan.create(name="plan1", with_groups=["group1", "group2"], target_site="drdc-site")
e.plan.add("plan1", ["group1", "group2"])         # add groups to an existing plan
e.plan.remove("plan1", ["group1"])                # remove groups from an existing plan
e.plan.delete("plan1", "plan2")
e.plan.failover("prod", "plan1")                          # kick off, return op-id
e.plan.failover("prod", "plan1", with_monitor=True)       # kick off + poll to terminal
e.plan.cleanup("plan1")
# site doubles as the Pure1 site name for failback — register your sites
# using the same name the site is registered under in Pure1.
e.plan.failback("plan1", site="prod-site")   # only runs if prod_failover SUCCEEDED

# VM enrollment in a group
e.vm.list(with_site="prod-site")
e.vm.add("vm1", "vm2", with_group="group1")                        # default protection_workflow=FA_OFFLOAD
e.vm.add("vm1", "vm2", with_group="group1", with_type="VADP")
e.vm.remove("vm1", "vm2", with_group="group1")

# Direct site actions — power, network, tags
e.sites["prod-site"].power_off(file="vm-list.json")
e.sites["prod-site"].power_on(file="vm-list.json")
e.sites["drdc-site"].connect_networks(file="vm-list.json")
e.sites["prod-site"].export_tags(file="vm-list.json")
e.sites["drdc-site"].apply_tags(file="vm-list.json", source="prod-site", create_missing=True)
e.sites["prod-site"].list_networks()   # diagnose a "network not found" error
e.sites["prod-site"].list_folders()    # diagnose a "folder not found" error

# VM lifecycle — clone from template / delete
e.sites["prod-site"].create_vm(name="vm1", template="golden-template", datastore="datastore1")
e.sites["prod-site"].create_vms(name_prefix="ubuntu-tst-", count=10,
                                 template="golden-template", datastore="datastore1")
e.sites["prod-site"].delete_vm("vm1")
e.sites["prod-site"].delete_vms(name_prefix="ubuntu-tst-", count=10)

# Managed workflows
e.workflow.managed_failover(
    vms_file="vm-list.json", group_names=["G1"], plan_names=["P1"],
    from_site="prod-site", to_site="drdc-site",
    with_network=True, with_tags=True,
)

# to_site doubles as the Pure1 site name for plan.failback() — register
# your sites using the same name the site is registered under in Pure1.
e.workflow.managed_failback(
    vms_file="vm-list.json", group_names=["G1"], plan_names=["P1"],
    from_site="drdc-site", to_site="prod-site",
    with_network=True, with_tags=True, create_missing_tags=True,
)
```

## 5. Or use the CLI

Every command below has a direct Python equivalent — `ers-cli --help` shows
the full, current list. `--name` (singular) is used only for `create`
actions, which always create exactly one resource; `--names` (comma-
separated, or a single `*`-wildcard pattern — no separate flag needed, a
literal `*` anywhere in `--names` is auto-detected) is used everywhere else.

### List

```bash
ers-cli --list policies|groups|plans|sites|snapshots --names ... --details --limit 50
ers-cli --list vms --with-site prod-site
```

### Service level policies

```bash
ers-cli --policy create --name policy1 --rpo 15 --target-type vmw \
           --local-retention 24 --remote-retention 72
ers-cli --policy delete --names policy1,policy2
ers-cli --policy delete --names "policy*"
```

### Application groups

```bash
ers-cli --group create --name group1 --with-policy policy1 \
           --source-site prod-site --target-site drdc-site
ers-cli --group enable --names group1,group2
ers-cli --group disable --names "group1*"
ers-cli --group run --names group1,group2                # kick off, return op-id(s)
ers-cli --group run --names group1,group2 --with-monitor  # kick off, poll to a terminal state
ers-cli --group delete --names group1,group2
ers-cli --group delete --names "group1*"
```

### VM enrollment in a group

```bash
ers-cli --vm add --names vm1,vm2 --with-group group1
ers-cli --vm add --names vm1,vm2 --with-group group1 --with-type VADP   # default: FA_OFFLOAD
ers-cli --vm add --names "vm*" --with-group group1
ers-cli --vm remove --names vm1,vm2 --with-group group1
ers-cli --vm remove --names "vm*" --with-group group1
```

### Recovery plans

```bash
ers-cli --plan create --name plan1 --with-groups group1,group2 --target-site drdc-site
ers-cli --plan add --names plan1 --with-groups group1,group2
ers-cli --plan remove --names plan1 --with-groups group1,group2
ers-cli --plan delete --names plan1,plan2
ers-cli --plan delete --names "plan*"

ers-cli --plan failover --type test --names plan1,plan2   # auto picks latest snapshot per group
ers-cli --plan failover --type prod --names plan1
ers-cli --plan cleanup --names plan1
ers-cli --plan failback --names plan1 --site prod-site    # only runs if prod_failover SUCCEEDED
```

By default, `--group run` and `--plan failover/cleanup/failback` just kick
off the operation and return its op ID — add `--with-monitor` to also poll
to a terminal state in the same call, instead of a separate `--monitor`
step:
```bash
ers-cli --plan failover --type prod --names plan1 --with-monitor
```
`failback` is the one exception worth knowing about: its synchronization
and cutover steps always poll to completion internally regardless of
`--with-monitor`, since each is a hard prerequisite for triggering the
next — the flag only controls whether the final promotion step is also
polled, or just kicked off like everything else.

### Managed workflows — orchestrated failover/failback across two sites

```bash
ers-cli --managed failover --from prod-site --to drdc-site \
           --vms-file vm-list.json --group-names G1,G2 --plan-names P1,P2 \
           --with-tags --create-missing-tags --dry-run

# --to is also the Pure1 site name used for the failback API call — register
# sites using the same name the site is registered under in Pure1.
ers-cli --managed failback --from drdc-site --to prod-site \
           --vms-file vm-list.json --group-names G1,G2 --plan-names P1,P2 \
           --with-network --with-tags --create-missing-tags
```

### Direct site actions — power, network, tags, VM lifecycle, without a full managed workflow

```bash
ers-cli --site prod-site --power off --vms-file vm-list.json
ers-cli --site prod-site --power off --names vm-1,vm-2
ers-cli --site prod-site --power on  --vms-file vm-list.json
ers-cli --site drdc-site --connect-networks --vms-file vm-list.json
ers-cli --site prod-site --export-tags --vms-file vm-list.json
ers-cli --site drdc-site --apply-tags --source prod-site \
           --vms-file vm-list.json --create-missing-tags

# Diagnose "network not found"/"folder not found" errors — see exactly
# what your connecting account can actually see in vCenter
ers-cli --site prod-site --list-networks
ers-cli --site prod-site --list-folders

# Clone a single VM from a template
ers-cli --site prod-site --create-vm --name vm1 --template golden-template \
           --resource-pool Resources --datastore datastore1 --network "VM Network"

# Clone N VMs from a template (auto-numbered, e.g. ubuntu-tst-001, ubuntu-tst-002, ...)
ers-cli --site prod-site --create-vm --name-prefix ubuntu-tst- --count 10 \
           --template golden-template --datastore datastore1
# --resource-pool defaults to 'Resources' (vCenter's standard default root
# resource pool) if omitted; --network/--folder are optional too, inheriting
# the template's own network/folder if not given; --power-on to start it
# immediately (default: stays off).

# Delete a VM — powers off first if running, then destroys it
ers-cli --site prod-site --delete-vm --name vm1
# Delete N VMs by the same --name-prefix/--count naming as --create-vm
ers-cli --site prod-site --delete-vm --name-prefix ubuntu-tst- --count 10
```

### Everything else

```bash
ers-cli --monitor group|plan --names group1,plan1
ers-cli --profile staging --list groups
```

## 6. System tests

`ers-system-test` runs against your real Pure1 deployment and registered
vCenter site(s) — no mocking. Three levels, increasing in what they touch:

- **Level 1** — read-only: list policies/groups/plans/sites, confirm your
  group/plan names actually exist. Safe to run any time, no confirmation needed.
- **Level 2** — real operations: group protection runs, plan test failover,
  cleanup, **production failover**, **failback**, VM power on/off, network
  reconnection, tag export/apply. `plan_prod_failover` and `plan_failback`
  are real, not simulated.
- **Level 3** — the full `managed_failover`/`managed_failback` workflows.
  Runs with `dry_run=True` by default (safe, no confirmation needed) even if
  you select level 3 — pass `--no-dry-run` to actually execute them.

### Setup

Edit `system-test-config.json`:

```json
{
  "schema_version": 1,
  "profile": "default",
  "source_site": "prod-site",
  "target_site": "drdc-site",
  "failback_site": "prod-site",
  "group_names": ["YOUR-GROUP-1"],
  "plan_names": ["YOUR-PLAN-1"],
  "vms_file": "vm-list.json",
  "with_network": true,
  "with_tags": true,
  "create_missing_tags": false,
  "interval": 10,
  "max_polls": 30
}
```

`source_site`/`target_site` must already be registered as `[site vsphere ...]`
sections in `~/.ers/credentials` (see §2).

### Running

```bash
# See what would run, without running anything
ers-system-test --level 1 2 3 --list

# Level 1 — safe, read-only, no confirmation
ers-system-test --level 1

# Level 2 — prompts for confirmation (real operations against your environment)
ers-system-test --level 2

# Level 2, skipping the real prod failover/failback
ers-system-test --level 2 --skip plan_prod_failover,plan_failback

# Level 2, non-interactive (e.g. CI) — still prints what it's about to do
ers-system-test --level 2 --yes

# Level 3 workflows, dry-run only (default) — safe to run any time
ers-system-test --level 3

# Level 3, for real — requires --yes AND typing the site name to confirm
ers-system-test --level 3 --no-dry-run --yes

# Just one test
ers-system-test --level 2 --only power_off_vms
```

Anything at level 2, or level 3 with `--no-dry-run`, prompts you to type the
site name to confirm before running, unless `--yes` is passed. Tests marked
`dangerous` (`plan_prod_failover`, `plan_failback`, and level 3 with
`--no-dry-run`) require a second, separate confirmation. Exit code is `0`
only if every selected test PASSed; `SKIP`ped tests don't count against it.

## 7. Scale testing

`ers-scale-test` creates M VMs distributed across N datastores,
distributes those VMs across X application groups, distributes those X
groups across Y recovery plans, then runs protection on every group and
test failover on every plan.

**`--vms`/`--datastores`/`--groups`/`--plans` are desired TOTALS, not
deltas.** A persistent manifest (`~/.ers/state/scale_test_manifest.json`)
tracks everything created so far, so re-running with higher numbers is
additive — it only creates the difference, and never moves or recreates
anything that already exists. New items always go to whichever existing
bucket (datastore/group/plan) currently has the fewest, so scaling up
tops off under-filled buckets and fills new ones first; on a first/fresh
run (nothing in the manifest yet) this is equivalent to plain round-robin.

Edit `scale-test-config.json`:
```json
{
  "schema_version": 1,
  "profile": "default",
  "source_site": "prod-site",
  "target_site": "drdc-site",
  "service_level_policy": "YOUR-POLICY-NAME",
  "group_name_prefix": "ers-scale-grp-",
  "plan_name_prefix": "ers-scale-plan-",
  "vm_name_prefix": "ers-scale-vm-",
  "datastore_name_prefix": "ers-scale-ds-",
  "vm_lnx_template": "YOUR-LINUX-TEMPLATE-NAME",
  "vm_win_template": "YOUR-WINDOWS-TEMPLATE-NAME"
}
```

**Datastores are not created** — `datastore_name_prefix` + N must already
exist on `source_site`. If you want to target specific existing
datastores by name instead, set `datastore_names` in the config to a
list of them — when set, it takes precedence over `datastore_name_prefix`
entirely, and `--datastores` is no longer required on the command line
(its count comes from `datastore_names`' length instead). Either way,
datastore names are unioned into the manifest across runs — none are
ever removed automatically, even if you later shrink the config's list.
If only one of `vm_lnx_template`/`vm_win_template` is given, every new VM
uses it; if both are given, new VMs split evenly between them.

VM/group/plan names are `{prefix}{NNN}` (3-digit, zero-padded) and
continue the existing numbering sequence across runs — a second run
never collides with names the first run already created.

```bash
# First run
ers-scale-test --vms 4 --datastores 1 --groups 2 --plans 1
# -> 4 VMs on 1 datastore, 2 per group, 1 plan with both groups

# Scale up -- additive: adds 16 VMs (to reach 20), 3 datastores (to reach
# 4), 2 groups (to reach 4), 1 plan (to reach 2). Existing VMs/groups
# never move to a different datastore/group.
ers-scale-test --vms 20 --datastores 4 --groups 4 --plans 2 --dry-run   # preview first
ers-scale-test --vms 20 --datastores 4 --groups 4 --plans 2
# -> 20 VMs, 5 per datastore, 5 per group, 2 groups per plan

# Tear everything down
ers-scale-test --cleanup

# Partial teardown, resumable later:
ers-scale-test --cleanup --keep-vms      # delete groups/plans; VMs stay in vCenter, unenrolled
ers-scale-test --cleanup --keep-groups   # detach groups from plans, delete plans;
                                          # groups and their VM membership are untouched
```

`--keep-vms`/`--keep-groups` can't be combined (`--keep-groups` already
implies keeping the VMs, since they're still enrolled in the groups you
kept). Whatever's left behind stays in the manifest as "unassigned," so
the next scale-up run picks it back up automatically — orphaned VMs get
re-enrolled into a group (no re-creation), orphaned groups get attached
to a plan (no re-creating the group) — rather than creating duplicates
alongside what's already there.

Either way, `--cleanup` always runs plan cleanup first (reverting test
failover) and waits for it to finish before touching anything else, since
groups/plans can't safely be torn down while still mid-failover.

