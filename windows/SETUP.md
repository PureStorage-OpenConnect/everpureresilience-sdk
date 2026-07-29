# ERS.PowerCLI — Setup

PowerShell SDK for the Everpure Resilience Service (ERS), for Windows
users. Same capabilities as the Linux/macOS Python SDK, built the
PowerShell-native way: verb-noun cmdlets instead of method chaining, and
[VCF.PowerCLI](https://developer.broadcom.com/powercli) (the renamed
continuation of VMware.PowerCLI).

## License

Apache License, Version 2.0 — see `LICENSE`. Source files carry the
standard Apache header; `NOTICE` carries the project attribution.

## Prerequisites

- **PowerShell 7+** (not Windows PowerShell 5.1 — some `VCF.PowerCLI`
  distributions require 7.2+; check the compatibility matrix for the
  version you install)
- **VCF.PowerCLI**:
  ```powershell
  Install-Module -Name VCF.PowerCLI -Scope CurrentUser
  ```
- **Pester 5+** (only needed for `Invoke-ErsSystemTest`):
  ```powershell
  Install-Module -Name Pester -MinimumVersion 5.0 -Scope CurrentUser -Force
  ```

## Install

```powershell
# From a git repo (tag, branch, or commit) — clone, then:
Import-Module .\ERS.PowerCLI\ERS.PowerCLI.psd1

# Or, once published to the PowerShell Gallery / a private repository:
Install-Module -Name ERS.PowerCLI -Scope CurrentUser
Import-Module ERS.PowerCLI
```

## 1. `~/.ers/config` — non-secret settings, profiles like `~/.aws/config`

`~` resolves to `$HOME` on Windows.

```ini
[default]
base_url      = https://api.pure1.purestorage.com
deployment_id = your-deployment-id
output        = txt
```

> Note: Get your deployment-id from Pure1 > Resilience > Your Deployment (ID).
> It will look something like eg. c951a9875de48435ea37876a5acf9af83

## 2. `~/.ers/credentials` — secrets

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
insecure = true
```

```powershell
# Generate an RSA key pair for the Pure1 API key (OpenSSL, or use
# New-Object System.Security.Cryptography.RSACng if you'd rather stay
# pure-PowerShell — either produces a compatible PEM)
openssl genrsa -out ers-private.pem 2048
openssl rsa -in ers-private.pem -pubout -out ers-public.pem
```

> Register `ers-public.pem` in Pure1:
> 1. Log in to `https://pure1.purestorage.com`
> 2. Go to **Administration → API Registration**
> 3. Create or update your API key and paste the contents of `ers-public.pem`
> 4. Use the Resource Operator Role for Permissions
> 5. Note your **Application ID** (format: `pure1:apikey:xxxxxxxxxx`)

> Register a site with the same name Pure1 uses for it (Pure1 → Resilience
> → Deployment → Sites). `prod-dc`/`dr-dc` above are examples — whatever
> you name them here MUST match what's registered in Pure1, since the site
> name doubles as the Pure1 > Resilience > Deployment > Site name.

`Import-Module` prints a warning instead if `~/.ers/credentials` is readable by
identities other than your own account, using file ACLs.

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

`networks`, if present, is keyed by registered site name — each
`Connect-ErsVMNetwork` call picks its own entry by its own site's name.
If a VM has fewer existing NICs than networks configured for it, a new
`vmxnet3` adapter is created for each missing position (via
`VCF.PowerCLI`'s `New-NetworkAdapter`).

## 4. Use it as a library

```powershell
Import-Module ERS.PowerCLI

$Ers = New-ErsInstance                       # reads ~/.ers/config + credentials, auths automatically
Register-ErsSite -ErsInstance $Ers -Name prod-dc   # connects via VCF.PowerCLI using credentials file
Register-ErsSite -ErsInstance $Ers -Name dr-dc -VIServer $conn  # or wrap a connection you made yourself

Get-ErsGroup -ErsInstance $Ers
Invoke-ErsPlanFailover -ErsInstance $Ers -Kind Prod -Name P1

# Direct site actions
Stop-ErsVM  -ErsSite $Ers.Sites['prod-dc'] -VmsFile vm-list.json
Start-ErsVM -ErsSite $Ers.Sites['prod-dc'] -VmsFile vm-list.json
Connect-ErsVMNetwork -ErsSite $Ers.Sites['dr-dc'] -VmsFile vm-list.json
Export-ErsTag -ErsSite $Ers.Sites['prod-dc'] -VmsFile vm-list.json
Import-ErsTag -ErsSite $Ers.Sites['dr-dc'] -VmsFile vm-list.json -Source prod-dc -CreateMissing

Invoke-ErsManagedFailover -ErsInstance $Ers -VmsFile vm-list.json `
    -GroupName G1, G2 -PlanName P1, P2 -FromSite prod-dc -ToSite dr-dc `
    -WithNetwork -WithTags -DryRun

# -ToSite doubles as the Pure1 site name for Invoke-ErsPlanFailback —
# register sites using the same name the site is registered under in Pure1.
Invoke-ErsManagedFailback -ErsInstance $Ers -VmsFile vm-list.json `
    -GroupName G1, G2 -PlanName P1, P2 -FromSite dr-dc -ToSite prod-dc `
    -WithNetwork -WithTags -CreateMissingTags
```

## 5. System tests

`Invoke-ErsSystemTest` wraps Pester with three-level, safety-gated
model:

- **Level 1** — read-only. Safe any time, no confirmation.
- **Level 2** — real operations: group runs, test/cleanup/prod
  failover/failback, VM power/network/tags. Prompts for confirmation.
  Prod-failover/failback tests are tagged `Dangerous` and excluded unless
  you pass `-IncludeDangerous`.
- **Level 3** — full managed workflows. Runs `-DryRun` by default (safe,
  no confirmation) regardless of level selection — pass `-NoDryRun` (and
  `-IncludeDangerous`) to actually execute.

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

```powershell
# See what would run, without running anything
Invoke-ErsSystemTest -Level 1, 2, 3 -ListTests

# Level 1 — safe, read-only, no confirmation
Invoke-ErsSystemTest -Level 1

# Level 2 — prompts for confirmation; dangerous tests excluded by default
Invoke-ErsSystemTest -Level 2

# Level 2, including the real prod failover/failback tests
Invoke-ErsSystemTest -Level 2 -IncludeDangerous -Yes

# Level 3 workflows, dry-run only (default) — safe to run any time
Invoke-ErsSystemTest -Level 3

# Level 3, for real
Invoke-ErsSystemTest -Level 3 -NoDryRun -IncludeDangerous -Yes

# Just one test
Invoke-ErsSystemTest -Level 2 -Only 'powers off VMs'
```
