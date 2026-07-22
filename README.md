# Everpure Resilience SDK

Core automation SDK for the Everpure Resilience service (ERS) in Pure1.
ERS offers Cyber Resilience and Disaster Recovery functionality as a
Service for Enterprise customers.

This SDK lets you drive ERS programmatically — as a Python library or via
the bundled CLI — to manage recovery plans, application groups, and
orchestrated failover/failback workflows against your registered vCenter
site(s).

## Features

- **Pure1 automation** — list and manage policies, application groups, and
  recovery plans; run test/production failover, cleanup, and failback
- **vCenter site integration** — power VMs on/off, reconnect NICs to the
  right network post-failover, and carry vSphere tags across sites
- **Managed workflows** — one call to orchestrate a full failover or
  failback: protect groups, run the plan, and handle VM power/network/tags
  in the right order
- **CLI** — every SDK capability is also available as a command-line tool,
  for scripting or ad hoc use
- **System test suite** — a three-level test suite (read-only checks,
  real operations, full workflows) to validate your setup against your
  actual environment

## Install

```bash
pip install "git+https://github.com/PureStorage-OpenConnect/everpureresilience-sdk.git@v2.7.0#subdirectory=linux"
```

This installs the SDK along with its dependencies and two console
commands: `ers-cli` and `ers-system-test`.

## Getting started

Full setup instructions — configuring `~/.ers/config` and
`~/.ers/credentials`, registering vCenter sites, the vm-list file format,
library and CLI usage, and running the system test suite — are here:

**[SETUP.md](https://github.com/PureStorage-OpenConnect/everpureresilience-sdk/blob/main/linux/SETUP.md)**

## Requirements

- Python 3.9+
- A Pure1 account with an ERS deployment and an API application ID
- Access to the vCenter server(s) you want to protect/recover

## License

Apache License, Version 2.0 — see [LICENSE](LICENSE) for details.
   
