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
ers.sites.vsphere — VSphereSite.

A site is usable two ways:
  1. register_site("prod-dc")           -- host/user/pass come from
     ~/.ers/credentials [site vsphere prod-dc]; VSphereSite opens
     its own SmartConnect session.
  2. register_site("prod-dc", si)        -- an already-connected
     SmartConnect() session is wrapped directly. In this case there's no
     plaintext password available for the vSphere Automation REST tagging
     API, so tagging authenticates via a SOAP clone ticket
     (SessionManager.AcquireCloneTicket()) instead of basic auth.

Tag state is transparent to the caller: export_tags()/apply_tags() read
and write ~/.ers/state/last_tags_export.json automatically — no file
path is ever passed in or out. Like the other .last_*.json state files,
only one export is "in flight" at a time; the site it was captured from
is recorded inside the file (not in the filename), and apply_tags()
checks that recorded site against its `source=` argument before applying
anything.

power_on()/power_off()/connect_networks()/export_tags()/apply_tags() all
accept a `file=` pointing at a vm-list JSON file (see _load_vms_file for
the schema) instead of/in addition to explicit *vm_names. This file is
expected to be machine-generated (e.g. from a CSV export or an RVTools
report), so the schema favors a flat array of records over anything that
needs hand-authoring conventions.
"""

import json
import ssl
import sys

from ..config import state_path
from .base import Site

try:
    from pyVim.connect import SmartConnect, Disconnect
    from pyVmomi import vim
except ImportError:
    SmartConnect = Disconnect = None
    vim = None

try:
    import requests
    import urllib3
except ImportError:
    requests = None


def is_vsphere_instance(instance) -> bool:
    """True if `instance` looks like a pyVmomi SmartConnect() return value."""
    if vim is None:
        return False
    return isinstance(instance, vim.ServiceInstance)


class TaggingError(Exception):
    pass


class VmListError(Exception):
    """Raised on a malformed/unreadable vm-list JSON file."""
    pass


class _TaggingSession:
    """vSphere Automation REST tagging API session — basic auth or clone ticket."""

    def __init__(self, base: str, verify: bool, session_id: str):
        self.base   = base
        self.verify = verify
        self.headers = {"vmware-api-session-id": session_id, "Content-Type": "application/json"}

    @classmethod
    def from_basic_auth(cls, host: str, user: str, password: str, insecure: bool = True):
        base = f"https://{host}"
        verify = not insecure
        if insecure and urllib3:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        resp = requests.post(f"{base}/api/session", auth=(user, password), verify=verify, timeout=30)
        if resp.status_code not in (200, 201):
            raise TaggingError(f"REST login failed ({resp.status_code}): {resp.text}")
        return cls(base, verify, resp.json())

    @classmethod
    def from_clone_ticket(cls, si, insecure: bool = True):
        """Bootstrap a REST tagging session from an existing SOAP session, so
        tagging works even when only a live `si` was handed to the site
        (no plaintext password available)."""
        host = si._stub.host
        base = f"https://{host}"
        verify = not insecure
        if insecure and urllib3:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        ticket = si.content.sessionManager.AcquireCloneTicket()
        resp = requests.post(f"{base}/api/session",
                              headers={"vmware-cis-clone-ticket": ticket}, verify=verify, timeout=30)
        if resp.status_code not in (200, 201):
            raise TaggingError(f"REST login via clone ticket failed ({resp.status_code}): {resp.text}")
        return cls(base, verify, resp.json())

    def _request(self, method, path, **kwargs):
        try:
            resp = requests.request(method, f"{self.base}{path}", headers=self.headers,
                                     verify=self.verify, timeout=30, **kwargs)
        except requests.exceptions.RequestException as e:
            raise TaggingError(str(e))
        if resp.status_code >= 400:
            raise TaggingError(f"{resp.status_code}: {resp.text}")
        if resp.text:
            try:
                return resp.json()
            except ValueError:
                return None
        return None

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, body=None):
        return self._request("POST", path, json=body)

    def logout(self):
        try:
            self._request("DELETE", "/api/session")
        except TaggingError:
            pass


class VSphereSite(Site):
    site_type = "vsphere"

    def __init__(self, name: str, si=None, host: str = None, user: str = None,
                 password: str = None, insecure: bool = True, port: int = 443):
        super().__init__(name)
        if SmartConnect is None:
            print("Missing dependency. Install it with:\n    pip install pyVmomi")
            sys.exit(1)

        self._creds = None
        if si is not None:
            self.si = si
        else:
            if not (host and user and password):
                print(f"Error: site '{name}' needs either a live SmartConnect() instance "
                      f"or host/user/pass credentials.")
                sys.exit(1)
            self._creds = {"host": host, "user": user, "password": password, "insecure": insecure}
            self.si = self._connect(host, user, password, port, insecure)

        self._rest = None  # lazy vSphere Automation REST session for tagging

    @staticmethod
    def _connect(host, user, password, port, insecure):
        context = None
        if insecure:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode    = ssl.CERT_NONE
        try:
            return SmartConnect(host=host, user=user, pwd=password, port=port, sslContext=context)
        except Exception as e:
            print(f"Error: Could not connect to vCenter {host}: {e}")
            sys.exit(1)

    def disconnect(self):
        if self.si:
            Disconnect(self.si)

    def _rest_session(self) -> _TaggingSession:
        if self._rest is None:
            if self._creds:
                self._rest = _TaggingSession.from_basic_auth(
                    self._creds["host"], self._creds["user"], self._creds["password"],
                    self._creds.get("insecure", True))
            else:
                self._rest = _TaggingSession.from_clone_ticket(self.si)
        return self._rest

    # ------------------------------------------------------------------
    # VM lookup (shared by power / network / tags)
    # ------------------------------------------------------------------

    def _get_vms_by_names(self, names: list) -> dict:
        content  = self.si.RetrieveContent()
        name_set = set(names)

        folder_traversal = vim.TraversalSpec(
            name="folderTraversal", type=vim.Folder, path="childEntity", skip=False,
            selectSet=[vim.SelectionSpec(name="folderTraversal"), vim.SelectionSpec(name="dcTraversal"),
                       vim.SelectionSpec(name="clusterTraversal"), vim.SelectionSpec(name="hostTraversal")])
        dc_traversal = vim.TraversalSpec(
            name="dcTraversal", type=vim.Datacenter, path="vmFolder", skip=False,
            selectSet=[vim.SelectionSpec(name="folderTraversal")])
        cluster_traversal = vim.TraversalSpec(name="clusterTraversal", type=vim.ClusterComputeResource,
                                               path="host", skip=False)
        host_traversal = vim.TraversalSpec(name="hostTraversal", type=vim.HostSystem, path="vm", skip=False)

        obj_spec = vim.ObjectSpec(obj=content.rootFolder, skip=True,
                                   selectSet=[folder_traversal, dc_traversal, cluster_traversal, host_traversal])
        prop_spec = vim.PropertySpec(type=vim.VirtualMachine, pathSet=["name"], all=False)
        filter_spec = vim.PropertyFilterSpec(objectSet=[obj_spec], propSet=[prop_spec])

        results = content.propertyCollector.RetrieveContents([filter_spec])
        found = {}
        for obj in results:
            for prop in obj.propSet:
                if prop.name == "name" and prop.val in name_set:
                    found[prop.val] = obj.obj
        return found

    def vms_exist(self, names: list) -> set:
        """Returns the subset of `names` that already exist as VMs in
        this site's inventory — one batched PropertyCollector lookup
        (same as _get_vms_by_names), not one round trip per name. Useful
        for idempotent VM creation: skip cloning a VM that's already
        there instead of erroring on a duplicate name."""
        return set(self._get_vms_by_names(names).keys())

    #: bump if the vm-list JSON schema ever changes shape
    SUPPORTED_SCHEMA_VERSIONS = (2,)

    @classmethod
    def _load_vms_file(cls, path: str) -> list:
        """
        Load a vm-list JSON file:

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

        Returns the list of VM record dicts. `networks`, if present, is a
        dict keyed by *registered site name* (matching register_site(...)
        and the [site ...] sections in ~/.ers/credentials) — each value is
        an ordered list mapped to NIC 1, NIC 2, ... by position for that
        site. This lets one vm-list.json drive connect_networks() through
        failover, failback, and any further site in the same chain: each
        VSphereSite picks its own entry by its own name.

        Raises VmListError on any problem with the file — never exits the
        process, so a caller (e.g. the system test runner) can report it
        as a failed test rather than the whole run dying.
        """
        with open(path, "r") as f:
            data = json.load(f)

        version = data.get("schema_version")
        if version not in cls.SUPPORTED_SCHEMA_VERSIONS:
            if version == 1:
                raise VmListError(
                    f"{path} is schema_version 1 (networks as a flat list) — this is no "
                    f"longer supported. Regenerate it as schema_version 2, with 'networks' "
                    f"as a dict keyed by registered site name, e.g. "
                    f'{{"prod-dc": [...], "dr-dc": [...]}}.'
                )
            raise VmListError(f"{path} has unsupported schema_version {version!r} "
                               f"(supported: {cls.SUPPORTED_SCHEMA_VERSIONS})")

        vms = data.get("vms")
        if not isinstance(vms, list) or not vms:
            raise VmListError(f"{path} has no VMs listed under 'vms'")

        names_seen = set()
        for record in vms:
            name = record.get("name")
            if not name:
                raise VmListError(f"{path} has a VM entry with no 'name'")
            if name in names_seen:
                raise VmListError(f"{path} lists VM '{name}' more than once")
            names_seen.add(name)

            networks = record.get("networks")
            if networks is not None and not isinstance(networks, dict):
                raise VmListError(
                    f"{path}: VM '{name}' has 'networks' as a {type(networks).__name__}, "
                    f"expected a dict keyed by site name — e.g. "
                    f'{{"prod-dc": ["net1", "net2"]}}. (schema_version 1 used a flat list; '
                    f"this file needs to be regenerated as schema_version 2.)"
                )

        return vms

    @staticmethod
    def _wait_for_task(task, timeout: int = 120):
        import time
        start = time.time()
        while task.info.state in (vim.TaskInfo.State.running, vim.TaskInfo.State.queued):
            if time.time() - start > timeout:
                return "timeout"
            time.sleep(2)
        return task.info.state

    # ------------------------------------------------------------------
    # Power (was vm-power-mgr.py)
    # ------------------------------------------------------------------

    def power_on(self, *vm_names, file: str = None):
        return self._power(vm_names, file, turn_on=True)

    def power_off(self, *vm_names, file: str = None):
        return self._power(vm_names, file, turn_on=False)

    def _power(self, vm_names, file, turn_on: bool):
        names = list(vm_names) if vm_names else (
            [v["name"] for v in self._load_vms_file(file)] if file else [])
        if not names:
            print("Error: no VM names given (pass names or file=...)")
            return []

        vm_map = self._get_vms_by_names(names)
        not_found = [n for n in names if n not in vm_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        success = []
        for name in names:
            vm = vm_map.get(name)
            if not vm:
                continue
            target_state = vim.VirtualMachine.PowerState.poweredOn if turn_on else vim.VirtualMachine.PowerState.poweredOff
            if vm.runtime.powerState == target_state:
                success.append(name)
                continue
            try:
                task = vm.PowerOnVM_Task() if turn_on else vm.PowerOffVM_Task()
                state = self._wait_for_task(task)
                if state == vim.TaskInfo.State.success:
                    success.append(name)
                else:
                    print(f"  Error powering {'on' if turn_on else 'off'} {name}: task state {state}")
            except Exception as e:
                print(f"  Error powering {'on' if turn_on else 'off'} {name}: {e}")

        print(", ".join(success))
        return success

    # ------------------------------------------------------------------
    # Network (was vm-network-mgr.py)
    # ------------------------------------------------------------------

    def list_networks(self) -> list:
        """Return every network name visible to this site's connection —
        standard portgroups and distributed virtual portgroups alike.
        Use this to compare, character-for-character, against the names
        in your vm-list.json when connect_networks() reports a network
        as 'not found' despite it looking identical in the vSphere UI.
        Common causes, roughly in order of likelihood: a lookalike
        Unicode character (an en-dash '–' or non-breaking hyphen where
        you'd expect a plain ASCII hyphen '-' — invisible to the eye,
        including in screenshots), case, trailing whitespace, or the
        connecting account lacking view privileges on network objects
        even though an admin account sees them fine. The CLI's
        --list-networks prints repr() of each name specifically so
        lookalike characters become visible."""
        content = self.si.RetrieveContent()
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.Network], True)
        try:
            names = sorted(net.name for net in container.view)
        finally:
            container.Destroy()
        return names

    def _suggest_network_names(self, network_name: str) -> list:
        """Fuzzy-match close network names in inventory, for a helpful
        'did you mean' when an exact/case-insensitive match both fail —
        catches things like a missing/extra hyphen that case-folding
        won't."""
        import difflib
        try:
            all_names = self.list_networks()
        except Exception:
            return []
        return difflib.get_close_matches(network_name, all_names, n=3, cutoff=0.6)

    def _find_network_in_inventory(self, network_name: str):
        """Search the full vCenter inventory — standard networks AND
        distributed virtual portgroups — for a network by name. Returns
        the matching vim.Network (or vim.dvs.DistributedVirtualPortgroup,
        which is a subtype of vim.Network) object, or None.

        This is deliberately NOT vm.network — that's only the networks a
        VM is already attached to, which is empty for exactly the case
        this method exists for: reconnecting a just-failed-over VM to a
        network it has never been on before.

        Tries an exact match first; falls back to a case-insensitive,
        whitespace-trimmed match (common when names are copy-pasted from
        a spreadsheet or RVTools export) and warns when that's what
        resolved it, since it usually means the vm-list.json entry should
        be corrected to match vCenter exactly.
        """
        content = self.si.RetrieveContent()
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.Network], True)
        try:
            all_networks = list(container.view)
        finally:
            container.Destroy()

        if not all_networks:
            print(f"  Warning: this connection sees ZERO networks in vCenter inventory at all — "
                  f"the account used to connect likely lacks view privileges on network objects, "
                  f"even if an admin account sees them in the UI. Check the account's role/privileges.")
            return None

        for net in all_networks:
            if net.name == network_name:
                return net

        target_normalized = network_name.strip().lower()
        for net in all_networks:
            if net.name.strip().lower() == target_normalized:
                print(f"  Warning: matched '{network_name}' to '{net.name}' only after "
                      f"ignoring case/whitespace — fix the name in your vm-list.json to "
                      f"match vCenter exactly: '{net.name}'")
                return net

        # Catch lookalike-but-different characters (e.g. an en-dash '–' or
        # non-breaking hyphen where a plain ASCII '-' is expected) — these
        # are invisible to the eye but make an exact string comparison
        # fail even when case/whitespace normalization doesn't help.
        target_folded = self._fold_lookalike_chars(network_name)
        for net in all_networks:
            if self._fold_lookalike_chars(net.name) == target_folded:
                print(f"  Warning: '{network_name}' (bytes: {network_name.encode('unicode_escape')}) "
                      f"looks identical to but is NOT the same string as vCenter's "
                      f"'{net.name}' (bytes: {net.name.encode('unicode_escape')}) — likely a "
                      f"lookalike Unicode character (e.g. an en-dash vs a hyphen). Fix the "
                      f"name in vm-list.json to match vCenter's exact bytes.")
                return net

        return None

    @staticmethod
    def _fold_lookalike_chars(s: str) -> str:
        """Normalize visually-identical-but-different characters (dash
        variants, non-breaking space) to their plain ASCII equivalent,
        purely for comparison/detection — never used for the actual
        network match, only to explain why one failed."""
        lookalikes = {
            "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
            "\u2014": "-", "\u2212": "-",  # various dash/minus variants
            "\u00a0": " ", "\u2009": " ", "\u200b": "",  # nbsp, thin space, zero-width space
        }
        for lookalike, plain in lookalikes.items():
            s = s.replace(lookalike, plain)
        return s.strip().lower()

    @staticmethod
    def _build_nic_backing(network):
        """Build the correct NIC backing for a resolved network object —
        standard portgroup vs. distributed virtual portgroup need
        different VirtualDeviceSpec backings."""
        if isinstance(network, vim.dvs.DistributedVirtualPortgroup):
            switch_uuid = network.config.distributedVirtualSwitch.uuid
            port = vim.dvs.PortConnection(portgroupKey=network.key, switchUuid=switch_uuid)
            return vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(port=port)
        return vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
            deviceName=network.name, network=network)

    def connect_networks(self, *vm_names, file: str = None):
        """Reconnect VM NICs to the networks listed for each VM, for THIS
        site, using the `networks` dict (keyed by registered site name)
        from the vm-list JSON file — each site picks its own entry by its
        own name, so one vm-list.json drives connect_networks() through
        failover, failback, and any further site in the same chain.

        Each network name is looked up in the vCenter network inventory
        (standard portgroups and distributed virtual portgroups) — not the
        VM's currently-attached networks, since the whole point is
        reconnecting to a network the VM may never have been on before
        (e.g. the DR site's portgroup after a failover). Without `file`,
        `vm_names` are simply ensured 'connected' on their current backing."""
        if file:
            records = self._load_vms_file(file)
            entries = []
            for r in records:
                networks_by_site = r.get("networks")
                if networks_by_site is None:
                    entries.append((r["name"], []))
                elif self.name not in networks_by_site:
                    print(f"  Warning: '{r['name']}' has a 'networks' entry but none for "
                          f"site '{self.name}' — NICs will be left on their current backing")
                    entries.append((r["name"], []))
                else:
                    entries.append((r["name"], networks_by_site[self.name]))
        else:
            entries = [(n, []) for n in vm_names]

        if not entries:
            print("Error: no VM names given (pass names or file=...)")
            return []

        names = [e[0] for e in entries]
        vm_map = self._get_vms_by_names(names)
        not_found = [n for n in names if n not in vm_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        network_cache = {}  # network name -> resolved object (or None), shared across VMs

        success = []
        for name, nics in entries:
            vm = vm_map.get(name)
            if not vm:
                continue
            try:
                nic_devices = [d for d in vm.config.hardware.device
                               if isinstance(d, vim.vm.device.VirtualEthernetCard)]
                changes = []
                skip_vm = False
                for i, nic in enumerate(nic_devices):
                    if i < len(nics) and nics[i]:
                        network_name = nics[i]
                        if network_name not in network_cache:
                            network_cache[network_name] = self._find_network_in_inventory(network_name)
                        network = network_cache[network_name]
                        if network is None:
                            suggestions = self._suggest_network_names(network_name)
                            hint = f" — did you mean: {', '.join(suggestions)}?" if suggestions else \
                                   " — run sites['<name>'].list_networks() to see exactly what's visible"
                            print(f"  Warning: network '{network_name}' not found in vCenter "
                                  f"inventory for {name}{hint}")
                            skip_vm = True
                            continue
                        nic.backing = self._build_nic_backing(network)
                    nic.connectable.connected = True
                    nic.connectable.startConnected = True
                    changes.append(vim.vm.device.VirtualDeviceSpec(
                        operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=nic))
                if skip_vm:
                    print(f"  Skipping {name} entirely — one or more target networks "
                          f"couldn't be resolved (partial reconfiguration would leave "
                          f"it in an inconsistent state)")
                    continue
                if changes:
                    spec = vim.vm.ConfigSpec(deviceChange=changes)
                    task = vm.ReconfigVM_Task(spec=spec)
                    state = self._wait_for_task(task)
                    if state == vim.TaskInfo.State.success:
                        success.append(name)
                    else:
                        print(f"  Error reconfiguring NICs on {name}: task state {state}")
                else:
                    success.append(name)
            except Exception as e:
                import traceback
                print(f"  Error connecting network for {name}: {type(e).__module__}.{type(e).__name__}: {e}")
                print(f"  {traceback.format_exc()}")

        print(", ".join(success))
        return success

    # ------------------------------------------------------------------
    # VM creation (clone from template)
    # ------------------------------------------------------------------

    def _find_in_inventory(self, vim_type, name: str):
        """Generic by-name lookup for a single vCenter object type
        (resource pool, datastore, template VM, ...) — same
        container-view approach as _find_network_in_inventory, minus its
        network-specific fuzzy-matching (templates/pools/datastores don't
        have the same DVS-vs-standard or lookalike-Unicode footguns that
        motivated that extra logic for networks).

        Flat, whole-inventory search — matches the first object with this
        exact name anywhere in the tree. Fine for resource pools/
        datastores/templates, which are rarely duplicated by name across
        an inventory, but NOT hierarchy-aware — if the same name exists
        in more than one place, this can silently return the wrong one.
        Folders specifically use _find_folder_by_path instead, since
        folders are exactly the case where same-named-but-different
        objects at different nesting levels is common (e.g. a per-user
        subfolder name reused under multiple parents)."""
        content = self.si.RetrieveContent()
        container = content.viewManager.CreateContainerView(content.rootFolder, [vim_type], True)
        try:
            for obj in container.view:
                if obj.name == name:
                    return obj
        finally:
            container.Destroy()
        return None

    def _find_folder_by_path(self, path: str):
        """
        Resolve a folder by path, e.g. '/Dev/smadhu1' or 'Dev/smadhu1'
        (leading/trailing slashes optional) — walks the inventory tree
        one path segment at a time, matching each segment's name exactly
        at that level, so a folder named 'smadhu1' under 'Dev' can't be
        confused with a different, same-named folder somewhere else in
        the inventory.

        A single segment with no '/' (e.g. just 'smadhu1') falls back to
        the old flat, whole-inventory search for backward compatibility —
        fine as long as that name is unique across your inventory; use
        the full path if it isn't.

        Datacenters are transparent in the path: vCenter's inventory tree
        interleaves a Datacenter object between the root Folder and your
        own folders (root -> Datacenter -> vmFolder -> Dev -> smadhu1),
        but a path like '/Dev/smadhu1' doesn't name the datacenter at
        all — matching how vCenter's own UI commonly shows folders
        without the datacenter prefix. So at each level, this tries the
        current segment against named children directly, AND tries
        descending through any datacenter-like child (one with a
        vmFolder) without consuming a path segment, in case the
        datacenter's own name was omitted.
        """
        segments = [s for s in path.split("/") if s]
        if not segments:
            return None

        all_folders = self._all_folders()
        normalized = "/" + "/".join(segments)

        if normalized in all_folders:
            return all_folders[normalized]

        if len(segments) == 1:
            # Leaf-name-only: search anywhere in the tree for a folder
            # with this name, regardless of nesting — convenient, but
            # only safe if that name is unique across the whole
            # inventory; use the full path if it isn't.
            leaf = segments[0]
            matches = [(p, f) for p, f in all_folders.items() if f.name == leaf]
            if len(matches) == 1:
                return matches[0][1]
            if len(matches) > 1:
                print(f"  Warning: '{leaf}' matches multiple folders: "
                      f"{', '.join(p for p, _ in matches)} — use the full path to disambiguate.")
                return None

        # Case-insensitive / whitespace-trimmed fallback, segment by segment.
        target_segments = [s.strip().lower() for s in segments]
        for candidate_path, folder_obj in all_folders.items():
            candidate_segments = [s.strip().lower() for s in candidate_path.split("/") if s]
            if candidate_segments == target_segments:
                print(f"  Warning: matched '{path}' to '{candidate_path}' only after ignoring "
                      f"case/whitespace — fix the path to match vCenter exactly.")
                return folder_obj

        return None

    def _all_folders(self) -> dict:
        """
        Single canonical traversal of the VM folder tree, used by BOTH
        list_folders() and _find_folder_by_path() — having two separate
        tree-walking implementations previously let them silently
        disagree (list_folders() found a path _find_folder_by_path()
        couldn't). Returns {full_path: folder_object}, e.g.
        {'/Dev': <Folder>, '/Dev/smadhu1': <Folder>}.

        Uses isinstance(node, vim.Datacenter) rather than
        hasattr(node, 'vmFolder') to detect datacenters — a more
        reliable check against pyVmomi's dynamically-typed SOAP proxy
        objects, where hasattr's behavior on optional/type-dependent
        properties is less predictable than an explicit type check.
        """
        content = self.si.RetrieveContent()
        paths = {}

        def walk(node, prefix):
            if isinstance(node, vim.Datacenter):
                walk(node.vmFolder, prefix)
                return
            for child in getattr(node, "childEntity", None) or []:
                if isinstance(child, vim.Datacenter):
                    walk(child, prefix)
                    continue
                if isinstance(child, vim.Folder):
                    child_path = f"{prefix}/{child.name}"
                    paths[child_path] = child
                    walk(child, child_path)

        walk(content.rootFolder, "")
        return paths

    def list_folders(self) -> list:
        """Return every VM folder's full path visible to this site's
        connection, e.g. ['/Dev', '/Dev/smadhu1', '/Prod'] — datacenter
        names omitted. Use this to diagnose a '--folder ... not found'
        error the same way --list-networks diagnoses a network mismatch:
        confirms the exact spelling/case/nesting vCenter actually has,
        and whether the connecting account can see folders at all (an
        empty result here usually means a view-privilege problem, not a
        naming problem). Derived from the exact same traversal
        _find_folder_by_path() uses, so the two can never disagree."""
        return sorted(self._all_folders().keys())

    def create_vm(self, name: str, template: str, datastore: str,
                   resource_pool: str = "Resources", network: str = None,
                   folder: str = None, power_on: bool = False):
        """Clones a single VM named `name` from an existing template.
        resource_pool defaults to 'Resources', vCenter's standard name
        for a cluster/host's default root resource pool."""
        created = self._clone_from_template(names=[name], template=template,
                                             resource_pool=resource_pool, datastore=datastore,
                                             network=network, folder=folder, power_on=power_on)
        return created[0] if created else None

    def create_vms(self, name_prefix: str, count: int, template: str, datastore: str,
                    resource_pool: str = "Resources", network: str = None, folder: str = None,
                    power_on: bool = False, start_index: int = 1):
        """Clones `count` VMs from an existing template, named
        `<name_prefix><NNN>` — 3-digit, zero-padded, starting at
        start_index (e.g. name_prefix='ubuntu-tst-' -> ubuntu-tst-001,
        ubuntu-tst-002, ...). resource_pool defaults to 'Resources',
        vCenter's standard name for a cluster/host's default root
        resource pool."""
        names = [f"{name_prefix}{i:03d}" for i in range(start_index, start_index + count)]
        return self._clone_from_template(names=names, template=template,
                                          resource_pool=resource_pool, datastore=datastore,
                                          network=network, folder=folder, power_on=power_on)

    def delete_vm(self, name: str):
        """Deletes a single VM by name — powers it off first if it's
        running, then destroys it (files and all)."""
        deleted = self._delete_vms([name])
        return name if name in deleted else None

    def delete_vms(self, name_prefix: str, count: int, start_index: int = 1):
        """Deletes VMs named `<name_prefix><NNN>` — same 3-digit,
        zero-padded naming convention as create_vms, so the exact names
        this generates match what create_vms would have created with the
        same name_prefix/count/start_index."""
        names = [f"{name_prefix}{i:03d}" for i in range(start_index, start_index + count)]
        return self._delete_vms(names)

    def _delete_vms(self, names: list) -> list:
        vm_map = self._get_vms_by_names(names)
        not_found = [n for n in names if n not in vm_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        deleted = []
        for name in names:
            vm = vm_map.get(name)
            if not vm:
                continue
            try:
                if vm.runtime.powerState == vim.VirtualMachine.PowerState.poweredOn:
                    power_task = vm.PowerOffVM_Task()
                    power_state = self._wait_for_task(power_task)
                    if power_state != vim.TaskInfo.State.success:
                        print(f"  {name}: FAILED to power off before delete (state {power_state})")
                        continue
                task = vm.Destroy_Task()
                state = self._wait_for_task(task, timeout=300)
                if state == vim.TaskInfo.State.success:
                    print(f"  {name}: deleted")
                    deleted.append(name)
                else:
                    error = getattr(task.info, "error", None)
                    msg = error.msg if error else state
                    print(f"  {name}: FAILED ({msg})")
            except Exception as e:
                print(f"  {name}: FAILED ({e})")

        print(", ".join(deleted))
        return deleted

    def _clone_from_template(self, names: list, template: str, resource_pool: str,
                              datastore: str, network: str, folder: str, power_on: bool):
        # Templates are just VirtualMachine objects (config.template=True) —
        # reuse the same PropertyCollector-based lookup power_on/off/delete
        # already use, rather than the less-efficient CreateContainerView
        # scan _find_in_inventory does. One targeted server round trip
        # instead of enumerating every VM in the inventory.
        template_map = self._get_vms_by_names([template])
        template_vm = template_map.get(template)
        if not template_vm:
            print(f"Error: template '{template}' not found")
            return []

        pool = self._find_in_inventory(vim.ResourcePool, resource_pool)
        if not pool:
            print(f"Error: resource pool '{resource_pool}' not found")
            return []

        ds = self._find_in_inventory(vim.Datastore, datastore)
        if not ds:
            print(f"Error: datastore '{datastore}' not found")
            return []

        dest_folder = template_vm.parent
        if folder:
            found_folder = self._find_folder_by_path(folder)
            if not found_folder:
                print(f"Error: folder '{folder}' not found")
                return []
            dest_folder = found_folder

        # Reuse the existing network resolution/backing logic from
        # connect_networks() rather than duplicating it — same fuzzy
        # matching, same lookalike-Unicode detection.
        device_changes = []
        if network:
            net = self._find_network_in_inventory(network)
            if not net:
                print(f"Error: network '{network}' not found")
                return []
            for device in template_vm.config.hardware.device:
                if isinstance(device, vim.vm.device.VirtualEthernetCard):
                    nic_spec = vim.vm.device.VirtualDeviceSpec()
                    nic_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.edit
                    nic_spec.device = device
                    nic_spec.device.backing = self._build_nic_backing(net)
                    device_changes.append(nic_spec)
                    break

        reloc_spec = vim.vm.RelocateSpec(pool=pool, datastore=ds)
        clone_spec = vim.vm.CloneSpec(location=reloc_spec, powerOn=power_on, template=False)
        if device_changes:
            clone_spec.config = vim.vm.ConfigSpec(deviceChange=device_changes)

        created = []
        for vm_name in names:
            try:
                task = template_vm.Clone(folder=dest_folder, name=vm_name, spec=clone_spec)
                state = self._wait_for_task(task, timeout=600)  # clones take longer than power ops
                if state == vim.TaskInfo.State.success:
                    print(f"  {vm_name}: created")
                    created.append(vm_name)
                else:
                    error = getattr(task.info, "error", None)
                    msg = error.msg if error else state
                    print(f"  {vm_name}: FAILED ({msg})")
            except Exception as e:
                print(f"  {vm_name}: FAILED ({e})")

        print(", ".join(created))
        return created

    # ------------------------------------------------------------------
    # Tags (was vm-tag-mgr.py) — state file is transparent
    # ------------------------------------------------------------------

    #: single shared file, like the other last_*.json state files — only
    #: one export is "in flight" at a time; the site it came from is
    #: recorded inside the file itself rather than in the filename.
    TAG_EXPORT_FILE = "last_tags_export.json"

    @staticmethod
    def _tag_state_path() -> str:
        return state_path(VSphereSite.TAG_EXPORT_FILE)

    def export_tags(self, *vm_names, file: str = None):
        names = list(vm_names) if vm_names else (
            [v["name"] for v in self._load_vms_file(file)] if file else [])
        if not names:
            print("Error: no VM names given (pass names or file=...)")
            return {}

        vm_map = self._get_vms_by_names(names)
        not_found = [n for n in names if n not in vm_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        session = self._rest_session()
        tag_cache, category_cache, result = {}, {}, {}

        for name, vm in vm_map.items():
            moid = vm._moId
            try:
                tag_ids = session.post("/api/cis/tagging/tag-association?action=list-attached-tags",
                                        {"object_id": {"id": moid, "type": "VirtualMachine"}}) or []
            except TaggingError as e:
                print(f"  Warning: could not read tags for {name}: {e}")
                continue

            entries = []
            for tag_id in tag_ids:
                if tag_id not in tag_cache:
                    tag_cache[tag_id] = session.get(f"/api/cis/tagging/tag/{tag_id}")
                tag_detail = tag_cache[tag_id]
                if not tag_detail:
                    continue
                cat_id = tag_detail["category_id"]
                if cat_id not in category_cache:
                    category_cache[cat_id] = session.get(f"/api/cis/tagging/category/{cat_id}")
                cat_detail = category_cache[cat_id]
                if not cat_detail:
                    continue
                entries.append({"category": cat_detail["name"], "tag": tag_detail["name"],
                                 "cardinality": cat_detail.get("cardinality", "MULTIPLE")})
            result[name] = entries
            print(f"  {name}: {len(entries)} tag(s) captured")

        import datetime
        payload = {
            "site": self.name,
            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "vms": result,
        }
        with open(self._tag_state_path(), "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

        total = sum(len(v) for v in result.values())
        print(f"\nCaptured {total} tag assignment(s) across {len(result)} VM(s) "
              f"-> {self.TAG_EXPORT_FILE} (site: '{self.name}')")
        return result

    def apply_tags(self, *vm_names, file: str = None, source: str = None, create_missing: bool = False):
        """Apply tags captured by another registered site's export_tags().
        `source` is that site's name — checked against the site name
        recorded inside last_tags_export.json, no file path needed."""
        if not source:
            print("Error: apply_tags() requires source=<site-name> "
                  "(the site that ran export_tags())")
            return

        try:
            with open(self._tag_state_path(), "r") as f:
                payload = json.load(f)
        except FileNotFoundError:
            print(f"Error: no tag export found ({self.TAG_EXPORT_FILE}). "
                  f"Run sites['{source}'].export_tags(...) first.")
            return

        recorded_site = payload.get("site")
        if recorded_site != source:
            print(f"Error: {self.TAG_EXPORT_FILE} was captured from site '{recorded_site}', "
                  f"not '{source}'. Re-run sites['{source}'].export_tags(...) first.")
            return

        state = payload.get("vms", {})

        names = list(vm_names) if vm_names else (
            [v["name"] for v in self._load_vms_file(file)] if file else list(state.keys()))
        vm_map = self._get_vms_by_names(names)
        not_found = [n for n in names if n not in vm_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        session = self._rest_session()
        category_index = self._build_category_index(session)
        tag_index_cache = {}
        applied = skipped = cats_created = tags_created = 0

        for name, vm in vm_map.items():
            entries = state.get(name, [])
            if not entries:
                continue
            moid = vm._moId
            for entry in entries:
                cat_name, tag_name = entry["category"], entry["tag"]
                cardinality = entry.get("cardinality", "MULTIPLE")

                if cat_name in category_index:
                    cat_id, _ = category_index[cat_name]
                elif create_missing:
                    try:
                        cat_id = session.post("/api/cis/tagging/category", {
                            "name": cat_name, "description": "Auto-created by ers VSphereSite",
                            "cardinality": cardinality if cardinality in ("SINGLE", "MULTIPLE") else "MULTIPLE",
                            "associable_types": ["VirtualMachine"]})
                        category_index[cat_name] = (cat_id, cardinality)
                        tag_index_cache[cat_id] = {}
                        cats_created += 1
                        print(f"  Created missing category: {cat_name}")
                    except TaggingError as e:
                        print(f"  Warning: could not create category '{cat_name}': {e}")
                        skipped += 1
                        continue
                else:
                    print(f"  Warning: category '{cat_name}' not found on '{self.name}' — "
                          f"skipping tag '{tag_name}' for {name} (create_missing=True to auto-create)")
                    skipped += 1
                    continue

                if cat_id not in tag_index_cache:
                    tag_index_cache[cat_id] = self._build_tag_index(session, cat_id)

                if tag_name in tag_index_cache[cat_id]:
                    tag_id = tag_index_cache[cat_id][tag_name]
                elif create_missing:
                    try:
                        tag_id = session.post("/api/cis/tagging/tag", {
                            "name": tag_name, "description": "Auto-created by ers VSphereSite",
                            "category_id": cat_id})
                        tag_index_cache[cat_id][tag_name] = tag_id
                        tags_created += 1
                        print(f"  Created missing tag: {cat_name}/{tag_name}")
                    except TaggingError as e:
                        print(f"  Warning: could not create tag '{cat_name}/{tag_name}': {e}")
                        skipped += 1
                        continue
                else:
                    print(f"  Warning: tag '{cat_name}/{tag_name}' not found on '{self.name}' — "
                          f"skipping for {name} (create_missing=True to auto-create)")
                    skipped += 1
                    continue

                try:
                    try:
                        session.post(f"/api/cis/tagging/tag-association/{tag_id}?action=attach",
                                     {"object_id": {"id": moid, "type": "VirtualMachine"}})
                    except TaggingError as e:
                        if "already_exists" not in str(e).lower() and "already associated" not in str(e).lower():
                            raise
                    applied += 1
                except TaggingError as e:
                    print(f"  Warning: failed to attach '{cat_name}/{tag_name}' to {name}: {e}")
                    skipped += 1

        print(f"\nTags applied: {applied}, skipped: {skipped}, "
              f"categories created: {cats_created}, tags created: {tags_created}")
        return {"applied": applied, "skipped": skipped,
                "categories_created": cats_created, "tags_created": tags_created}

    @staticmethod
    def _build_category_index(session) -> dict:
        index = {}
        for cat_id in (session.get("/api/cis/tagging/category") or []):
            detail = session.get(f"/api/cis/tagging/category/{cat_id}")
            if detail:
                index[detail["name"]] = (cat_id, detail.get("cardinality", "MULTIPLE"))
        return index

    @staticmethod
    def _build_tag_index(session, category_id: str) -> dict:
        index = {}
        tag_ids = session.post("/api/cis/tagging/tag?action=list-tags-for-category",
                                {"category_id": category_id}) or []
        for tag_id in tag_ids:
            detail = session.get(f"/api/cis/tagging/tag/{tag_id}")
            if detail:
                index[detail["name"]] = tag_id
        return index
