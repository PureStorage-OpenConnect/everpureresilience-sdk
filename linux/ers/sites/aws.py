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
ers.sites.aws — AwsSite: the subset of Site capabilities that translate
cleanly from vSphere to EC2 — power on/off, delete, name-based lookup,
and tag export/apply. NOT implemented, by design, since they don't
translate directly:

  - create_vm/create_vms — AWS launches from an AMI and requires an
    instance_type (compute sizing) with no vSphere-template equivalent.
  - connect_networks — AWS generally doesn't support live-reassigning an
    instance's subnet the way vSphere lets you reconnect a NIC.
  - list_networks/list_folders — no VM-folder concept in EC2, and
    "network" would mean something different (VPC subnet) than what
    connect_networks would need to act on anyway.

Tag export/apply intentionally use the SAME state file and (category,
tag) shape as VSphereSite.export_tags()/apply_tags() — AWS's tag
Key/Value maps directly to vSphere's category/tag — so tags round-trip
across site types: e.g. export from a vSphere source before failover,
apply to the AWS target after; export from AWS before failback, apply
back to vSphere after.
"""

import datetime
import json

from ..config import state_path
from .base import Site

try:
    import boto3
except ImportError:
    boto3 = None

#: shared with VSphereSite — same file, same format, for cross-site-type
#: tag round-tripping.
TAG_EXPORT_FILE = "last_tags_export.json"

#: EC2 instance states considered "exists" for name-based lookup —
#: excludes fully-terminated instances, which AWS keeps describable for
#: a while but which shouldn't count as "still there".
_ACTIVE_STATES = ["pending", "running", "stopping", "stopped", "shutting-down"]


def is_aws_instance(instance) -> bool:
    """Detector for register_site(name, instance) — True if `instance`
    looks like a boto3 EC2 client (has the boto3 client shape) rather
    than a pyVmomi ServiceInstance."""
    service_model = getattr(getattr(instance, "meta", None), "service_model", None)
    return getattr(service_model, "service_name", None) == "ec2"


class AwsSite(Site):
    site_type = "aws"

    def __init__(self, name: str, aws_access_key_id: str = None,
                 aws_secret_access_key: str = None, aws_region: str = None,
                 ec2=None, **_ignored):
        super().__init__(name)
        if ec2 is not None:
            self.ec2 = ec2
            return
        if boto3 is None:
            raise ImportError("AwsSite requires the 'boto3' package: pip install boto3")
        if not (aws_access_key_id and aws_secret_access_key and aws_region):
            raise ValueError(f"Site '{name}': aws_access_key_id, aws_secret_access_key, and "
                              f"aws_region are all required in ~/.ers/credentials")
        session = boto3.Session(aws_access_key_id=aws_access_key_id,
                                 aws_secret_access_key=aws_secret_access_key,
                                 region_name=aws_region)
        self.ec2 = session.client("ec2")

    # -- name-based lookup ------------------------------------------------

    def _get_instances_by_names(self, names: list) -> dict:
        """One batched describe_instances call, filtered on the 'Name'
        tag — EC2 instances have no native name field; 'Name' is only a
        conventional tag. Returns {name: instance_id}."""
        if not names:
            return {}
        response = self.ec2.describe_instances(Filters=[
            {"Name": "tag:Name", "Values": list(names)},
            {"Name": "instance-state-name", "Values": _ACTIVE_STATES},
        ])
        found = {}
        name_set = set(names)
        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}
                name = tags.get("Name")
                if name in name_set:
                    found[name] = instance["InstanceId"]
        return found

    def vms_exist(self, names: list) -> set:
        """Same contract as VSphereSite.vms_exist — the subset of
        `names` that already exist, via one batched lookup."""
        return set(self._get_instances_by_names(names).keys())

    @staticmethod
    def _load_vms_file(path: str) -> list:
        # Same vm-list.json schema/loader as VSphereSite — reused
        # directly rather than duplicated, since it's pure JSON parsing
        # with nothing vSphere-specific in it.
        from .vsphere import VSphereSite
        return VSphereSite._load_vms_file(path)

    # -- power --------------------------------------------------------------

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

        id_map = self._get_instances_by_names(names)
        not_found = [n for n in names if n not in id_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        instance_ids = [id_map[n] for n in names if n in id_map]
        if instance_ids:
            try:
                if turn_on:
                    self.ec2.start_instances(InstanceIds=instance_ids)
                    waiter = self.ec2.get_waiter("instance_running")
                else:
                    self.ec2.stop_instances(InstanceIds=instance_ids)
                    waiter = self.ec2.get_waiter("instance_stopped")
                waiter.wait(InstanceIds=instance_ids)
            except Exception as e:
                print(f"  Error powering {'on' if turn_on else 'off'} instances: {e}")
                instance_ids = []

        success = [n for n in names if id_map.get(n) in instance_ids]
        print(", ".join(success))
        return success

    # -- delete ---------------------------------------------------------------

    def delete_vm(self, name: str):
        deleted = self._delete_vms([name])
        return name if name in deleted else None

    def delete_vms(self, name_prefix: str, count: int, start_index: int = 1):
        """Same 3-digit zero-padded naming as VSphereSite.delete_vms."""
        names = [f"{name_prefix}{i:03d}" for i in range(start_index, start_index + count)]
        return self._delete_vms(names)

    def _delete_vms(self, names: list) -> list:
        id_map = self._get_instances_by_names(names)
        not_found = [n for n in names if n not in id_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        instance_ids = [id_map[n] for n in names if n in id_map]
        deleted = []
        if instance_ids:
            try:
                self.ec2.terminate_instances(InstanceIds=instance_ids)
                waiter = self.ec2.get_waiter("instance_terminated")
                waiter.wait(InstanceIds=instance_ids)
                deleted = [n for n in names if n in id_map]
                for n in deleted:
                    print(f"  {n}: deleted")
            except Exception as e:
                print(f"  Error deleting instances: {e}")

        print(", ".join(deleted))
        return deleted

    # -- tags — shared state file/format with VSphereSite, for cross-
    # platform round-tripping: vSphere's (category, tag) maps directly
    # to AWS's (Key, Value) — category becomes the tag Key, tag becomes
    # the Value. cardinality has no AWS equivalent (a resource can only
    # have one value per key anyway) — recorded as "SINGLE" on export,
    # ignored on apply. create_missing is accepted for interface parity
    # but is a no-op here — AWS has no separate "category" to
    # pre-register the way vSphere tag categories require.
    # ------------------------------------------------------------------

    @staticmethod
    def _tag_state_path() -> str:
        return state_path(TAG_EXPORT_FILE)

    def export_tags(self, *vm_names, file: str = None):
        names = list(vm_names) if vm_names else (
            [v["name"] for v in self._load_vms_file(file)] if file else [])
        if not names:
            print("Error: no VM names given (pass names or file=...)")
            return {}

        id_map = self._get_instances_by_names(names)
        not_found = [n for n in names if n not in id_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        result = {}
        for name, instance_id in id_map.items():
            try:
                response = self.ec2.describe_tags(
                    Filters=[{"Name": "resource-id", "Values": [instance_id]}])
                entries = [{"category": t["Key"], "tag": t["Value"], "cardinality": "SINGLE"}
                           for t in response.get("Tags", []) if t["Key"] != "Name"]
            except Exception as e:
                print(f"  Warning: could not read tags for {name}: {e}")
                continue
            result[name] = entries
            print(f"  {name}: {len(entries)} tag(s) captured")

        payload = {
            "site": self.name,
            "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "vms": result,
        }
        with open(self._tag_state_path(), "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

        total = sum(len(v) for v in result.values())
        print(f"\nCaptured {total} tag assignment(s) across {len(result)} VM(s) "
              f"-> {TAG_EXPORT_FILE} (site: '{self.name}')")
        return result

    def apply_tags(self, *vm_names, file: str = None, source: str = None,
                    create_missing: bool = False):
        """Apply tags captured by another registered site's export_tags()
        — including a VSphereSite, since both share the same state file
        and (category, tag) <-> (Key, Value) shape. `source` is that
        site's name — checked against the site name recorded inside
        last_tags_export.json, no file path needed."""
        if not source:
            print("Error: apply_tags() requires source=<site-name> "
                  "(the site that ran export_tags())")
            return

        try:
            with open(self._tag_state_path(), "r") as f:
                payload = json.load(f)
        except FileNotFoundError:
            print(f"Error: no tag export found ({TAG_EXPORT_FILE}). "
                  f"Run sites['{source}'].export_tags(...) first.")
            return

        recorded_site = payload.get("site")
        if recorded_site != source:
            print(f"Error: {TAG_EXPORT_FILE} was captured from site '{recorded_site}', "
                  f"not '{source}'. Re-run sites['{source}'].export_tags(...) first.")
            return

        state = payload.get("vms", {})
        names = list(vm_names) if vm_names else (
            [v["name"] for v in self._load_vms_file(file)] if file else list(state.keys()))
        id_map = self._get_instances_by_names(names)
        not_found = [n for n in names if n not in id_map]
        if not_found:
            print(f"Warning: VMs not found: {', '.join(not_found)}")

        applied = skipped = 0
        for name, instance_id in id_map.items():
            entries = state.get(name, [])
            if not entries:
                continue
            tags = [{"Key": e["category"], "Value": e["tag"]} for e in entries]
            try:
                self.ec2.create_tags(Resources=[instance_id], Tags=tags)
                applied += len(tags)
            except Exception as e:
                print(f"  Warning: failed to apply tags to {name}: {e}")
                skipped += len(tags)

        print(f"\nTags applied: {applied}, skipped: {skipped}")
        return {"applied": applied, "skipped": skipped}

    # -- explicitly unsupported -------------------------------------------

    def _not_supported(self, capability: str):
        raise NotImplementedError(
            f"AWS sites don't support {capability} — AWS's model (launch-from-AMI, "
            f"subnet/security-group networking, no VM-folder concept) doesn't translate "
            f"directly from vSphere. Only power on/off, delete, name lookup, and tag "
            f"export/apply are implemented for AwsSite.")

    def create_vm(self, *args, **kwargs):
        self._not_supported("--create-vm")

    def create_vms(self, *args, **kwargs):
        self._not_supported("--create-vm (batch)")

    def connect_networks(self, *args, **kwargs):
        self._not_supported("--connect-networks")

    def list_networks(self, *args, **kwargs):
        self._not_supported("--list-networks")

    def list_folders(self, *args, **kwargs):
        self._not_supported("--list-folders")
