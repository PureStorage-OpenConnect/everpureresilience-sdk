# ERS SDK — Setup

## License

Apache License, Version 2.0 — see `LICENSE`. Source files carry the standard
Apache header; `NOTICE` carries the project attribution. Replace
`[Your Organization]` in `LICENSE`, `NOTICE`, and each file's header with
your actual copyright holder before distributing.

## Install

```bash
# From a git repo (tag, branch, or commit):
pip install git+https://github.com/YourOrg/ers-sdk.git@v2.7.0

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

[site vsphere prod-dc]
host = vcenter-source.example.com
user = administrator@vsphere.local
pass = yourpassword
insecure = true

[site vsphere dr-dc]
host = vcenter-target.example.com
user = administrator@vsphere.local
pass = yourpassword
```

```bash
# Generate private key
openssl genrsa -out ers-private.pem 2048

# Extract public key
openssl rsa -in ers-private.pem -pubout -out ers-public.pem
```

> Register `ers-public.pem` in Pure1:
> 1. Log in to `https://pure1.purestorage.com`
> 2. Go to **Administration → API Registration**
> 3. Create or update your API key and paste the contents of `ers-public.pem`
> 4. Use the Resource Operator Role for Permissions
> 5. Note your **Application ID** (format: `pure1:apikey:xxxxxxxxxx`)

> Note the naming: register a site with the same name in Pure1 > Resilience >
> Deployment > Sites > your-site-name
> In the example above, prod-dc and dr-dc are names used when the sites are
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
        "prod-dc": ["prod-vm-network", "prod-dmz"],
        "dr-dc":   ["dr-vm-network", "dr-dmz"]
      }
    },
    {"name": "vm-2", "networks": {"prod-dc": ["prod-vm-network"]}},
    {"name": "vm-3"}
  ]
}
```

- `schema_version` is required and validated — `2` is the only supported value today.
- `generated_from`/`generated_at` are optional provenance, not read by ERS, but useful in a DR runbook.
- Each VM needs a `name` matching the vCenter inventory exactly; duplicate names are rejected at load time.
- `networks`, if present, is a **dict keyed by registered site name** — the same names you pass to `register_site(...)` and that appear in `~/.ers/credentials` as `[site vsphere prod-dc]`. Each `VSphereSite.connect_networks()` call picks its own entry by its own name (`self.name`), so **one vm-list.json drives failover, failback, and any further site in the same chain** — no separate file or parameter needed per direction. Within a site's list, entries are ordered and mapped to NIC 1, NIC 2, ... by position.
  - If a VM has no `networks` field at all, `connect_networks()` just ensures its NICs are connected on their current backing — no warning, this is the normal case for VMs that don't need network reconfiguration.
  - If a VM *has* a `networks` dict but it's missing the entry for the site you're calling `connect_networks()` on, that's flagged as a warning (likely a config gap) rather than silently skipped.

## 4. Use it as a library

```python
import ers

e = ers.instance()                  # reads ~/.ers/config + credentials, auths automatically
e.register_site("prod-dc")          # opens its own SmartConnect using credentials file
e.register_site("dr-dc", si)        # or wrap an si you already connected yourself

e.group.list()
e.plan.failover("prod", "PLAN-1")

# Direct site actions
e.sites["prod-dc"].power_off(file="vm-list.json")
e.sites["prod-dc"].power_on(file="vm-list.json")
e.sites["dr-dc"].connect_networks(file="vm-list.json")
e.sites["prod-dc"].export_tags(file="vm-list.json")
e.sites["dr-dc"].apply_tags(file="vm-list.json", source="prod-dc", create_missing=True)

e.workflow.managed_failover(
    vms_file="vm-list.json", group_names=["G1"], plan_names=["P1"],
    from_site="prod-dc", to_site="dr-dc",
    with_network=True, with_tags=True,
)

# to_site doubles as the Pure1 site name for plan.failback() — register
# your sites using the same name the site is registered under in Pure1.
e.workflow.managed_failback(
    vms_file="vm-list.json", group_names=["G1"], plan_names=["P1"],
    from_site="dr-dc", to_site="prod-dc",
    with_network=True, with_tags=True, create_missing_tags=True,
)
```

## 5. Or use the CLI

```bash
ers-cli --list groups
ers-cli --group run --names G1,G2
ers-cli --plan failover --type prod --names P1,P2
ers-cli --plan failback --names P1 --site DC.DEV
ers-cli --managed-failover --from prod-dc --to dr-dc \
           --vms-file vm-list.json --group-names G1,G2 --plan-names P1,P2 \
           --with-tags --create-missing-tags --dry-run

# --to is also the Pure1 site name used for the failback API call — register
# sites using the same name the site is registered under in Pure1.
ers-cli --managed-failback --from dr-dc --to prod-dc \
           --vms-file vm-list.json --group-names G1,G2 --plan-names P1,P2 \
           --with-network --with-tags --create-missing-tags

# Direct site actions — power, network, and tags, without a full managed workflow
ers-cli --site prod-dc --power off --vms-file vm-list.json
ers-cli --site prod-dc --power off --names vm-1,vm-2
ers-cli --site prod-dc --power on  --vms-file vm-list.json
ers-cli --site dr-dc   --connect-networks --vms-file vm-list.json
ers-cli --site prod-dc --export-tags --vms-file vm-list.json
ers-cli --site dr-dc   --apply-tags --source prod-dc \
           --vms-file vm-list.json --create-missing-tags
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
  "source_site": "prod-dc",
  "target_site": "dr-dc",
  "failback_site": "prod-dc",
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

