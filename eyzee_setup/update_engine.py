"""Conservative application updates with a durable file rollback journal."""
import copy
import hashlib
import json
import shutil
from pathlib import Path

from subscription import SubscriptionError, atomic_private, managed_path
import edition


# Exact hashes from the last signed release are accepted only for files whose
# source bytes changed in beta.15. This permits a genuine beta.14 installation
# to advance while preserving the local-edit check for every other byte value.
TRUSTED_PREDECESSOR_HASHES = {
    "eyzee/ui/living/eyzee-main-menu.yaml": {
        "c30adc34f471e069bac911b24cecfeeb55527faef6b8612f8360e61d4b10500f",
    },
}


def _local_change_error(relative):
    """Return a support-safe error that identifies the conflicting file."""
    error = SubscriptionError(
        "A local EyZEE file has been changed: " + relative
        + ". Your files were preserved; ask support to review the update."
    )
    error.diagnostic = {"reason": "local_file_changed", "managed_path": relative}
    return error


def _safe_existing_file(relative, current, rendered, signed_source, expected_hash):
    """Accept tracked content or the exact signed source before edition rendering."""
    if current == rendered or current == signed_source:
        return True
    current_hash = hashlib.sha256(current).hexdigest()
    if expected_hash and current_hash == expected_hash:
        return True
    return current_hash in TRUSTED_PREDECESSOR_HASHES.get(relative, set())


def _configuration_edition_migration(installer, plan):
    """Plan the one exact beta14 Home sidebar-title migration for Core."""
    if plan != edition.CORE:
        return None
    target = installer.config / "configuration.yaml"
    if not target.is_file() or target.is_symlink():
        return None
    current = target.read_bytes()
    try:
        text = current.decode("utf-8")
        from installer import load, merge_document
        planned = load(text)
        dashboards = planned["lovelace"]["dashboards"]
        registration = dashboards["eyzee-main-menu"]
    except (UnicodeError, KeyError, TypeError):
        return None
    if not isinstance(registration, dict):
        return None
    if registration.get("title") == "EyZEE® Core":
        return None
    # Preserve custom titles and every non-title setting. Only the exact
    # official beta14 Home registration is an automatic edition migration.
    if registration.get("title") != "EyZEE® Home":
        return None
    registration["title"] = "EyZEE® Core"
    rendered = merge_document(text, planned).encode("utf-8")
    return {
        "current": current,
        "rendered": rendered,
        "verified_hash": hashlib.sha256(current).hexdigest(),
    }


def recover(installer):
    journal = installer.data / "update-journal.json"
    if not journal.exists():
        return
    saved = json.loads(journal.read_text())
    if saved["phase"] == "writing":
        rollback(installer, saved)
        installer.state["update_message"] = "An interrupted update was rolled back. Your previous files were restored."
        installer.save()
    # A validated release is retained if interrupted while requesting restart.
    journal.unlink(missing_ok=True)


def rollback(installer, saved):
    backup = Path(saved["directory"])
    for relative, existed in saved["originals"].items():
        if not managed_path(relative):
            raise SubscriptionError("The update recovery journal needs a support review.")
        target = installer.config / relative
        if existed:
            atomic_private(target, (backup / relative).read_bytes())
        else:
            target.unlink(missing_ok=True)
    if saved.get("configuration_changed"):
        atomic_private(
            installer.config / "configuration.yaml",
            (backup / "configuration.yaml").read_bytes(),
        )
    installer.state["files"] = saved["tracked_files"]
    installer.state["installed_release"] = saved.get("installed_release")
    if saved.get('expected_converters') is not None:
        installer.state['expected_converters']=saved['expected_converters']
    installer.save()


def apply(installer):
    client = installer.subscription
    if client is None:
        raise SubscriptionError("Official updates are not configured.")
    if not installer.existing_installation():
        raise SubscriptionError("Prepare your home before applying updates.")
    installer.stage("checking_update", "Checking your official EyZEE update access.")
    manifest = client.release()
    plan = edition.plan_for(client)
    configuration_migration = _configuration_edition_migration(installer, plan)
    if installer.state.get("installed_release") == manifest["version"] and configuration_migration is None:
        installer.stage("installed", "Your authorised EyZEE release is already installed.")
        return
    stage, release = client.download(manifest)
    try:
        # The activated entitlement plan is read from the verified release
        # response. It only selects customer-visible product wording.
        updates = release.get("update_files")
        if not isinstance(updates, dict) or not updates or release.get("migration") != "none" or release.get("requires_setup") != "0.1.0-beta.15":
            raise SubscriptionError("This release needs a newer installer or a migration review.")
        payload_hashes = json.loads((stage / "payload-hashes.json").read_text())
        rendered = {}
        signed_sources = {}
        verified_existing_hashes = {}
        changed_converters=set()
        for relative, source in updates.items():
            if not managed_path(relative) or not isinstance(source, str) or source not in payload_hashes:
                raise SubscriptionError("The release contains an unsupported update path.")
            expected_source = "device-support/" + relative if relative.startswith("zigbee2mqtt/") else "config/" + relative
            if source != expected_source:
                raise SubscriptionError("The release file mapping could not be verified.")
            signed_sources[relative] = (stage / "payload" / source).read_bytes()
            rendered[relative] = edition.render(signed_sources[relative], plan)
            target = installer.config / relative
            if relative.startswith('zigbee2mqtt/external_converters/') and (not target.exists() or target.read_bytes() != rendered[relative]):
                changed_converters.add(Path(relative).name)
            # Reject symlinks anywhere in the destination chain.
            if any(parent.is_symlink() for parent in [target, *target.parents] if parent != installer.config.parent):
                raise SubscriptionError("A managed file uses a symbolic link. Support must review the update.")
            if target.exists():
                current = target.read_bytes()
                expected = installer.state.get("files", {}).get(relative)
                if not _safe_existing_file(relative, current, rendered[relative], signed_sources[relative], expected):
                    raise _local_change_error(relative)
                verified_existing_hashes[relative] = hashlib.sha256(current).hexdigest()
        installer.stage("update_backup", "Saving a recovery copy before updating EyZEE.")
        recovery = installer.api.call("/backups/new/full", "POST", {"name": "Before EyZEE update " + manifest["version"]}, timeout=1200)
        if not recovery.get("slug"):
            raise SubscriptionError("A recovery backup could not be confirmed. The update has stopped.")
        backup = installer.data / "update-backups" / manifest["version"]
        backup.mkdir(parents=True, exist_ok=True)
        saved = {"phase": "writing", "directory": str(backup), "originals": {},
                 "tracked_files": copy.deepcopy(installer.state.get("files", {})),
                 "expected_converters":installer.state.get('expected_converters'),
                 "installed_release": installer.state.get("installed_release"), "ha_backup": recovery["slug"],
                 "configuration_changed": configuration_migration is not None}
        for relative in updates:
            target = installer.config / relative
            saved["originals"][relative] = target.exists()
            if target.exists():
                original = backup / relative
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, original)
        if configuration_migration is not None:
            atomic_private(backup / "configuration.yaml", configuration_migration["current"])
        journal = installer.data / "update-journal.json"
        atomic_private(journal, json.dumps(saved).encode())
        installer.stage("updating", "Installing the verified EyZEE release. Your home settings are preserved.")
        try:
            if configuration_migration is not None:
                installer.write_owned(
                    "configuration.yaml",
                    configuration_migration["rendered"],
                    replace=True,
                    verified_hash=configuration_migration["verified_hash"],
                )
            for relative in updates:
                installer.write_owned(
                    relative,
                    rendered[relative],
                    replace=True,
                    verified_hash=verified_existing_hashes.get(relative),
                )
            installer.api.call("/core/check", "POST", timeout=180)
            if changed_converters:
                from installer import Z2M_SLUG, mqtt_snapshot
                installer.api.call('/addons/'+Z2M_SLUG+'/restart','POST',{},timeout=180)
                service=installer.api.call('/services/mqtt')
                def converters_loaded():
                    snapshot=mqtt_snapshot(service,5)
                    bridge=snapshot.get('zigbee2mqtt/bridge/state',{})
                    online=bridge.get('state')=='online' if isinstance(bridge,dict) else bridge=='online'
                    loaded={entry.get('name') for entry in snapshot.get('zigbee2mqtt/bridge/converters',[]) if isinstance(entry,dict)}
                    return online and changed_converters<=loaded
                installer.wait(converters_loaded,90)
        except BaseException:
            rollback(installer, saved)
            if changed_converters:
                try:
                    from installer import Z2M_SLUG
                    installer.api.call('/addons/'+Z2M_SLUG+'/restart','POST',{},timeout=180)
                except Exception:
                    installer.state['update_message']='Previous files restored. Check Zigbee2MQTT is running before retrying.'
                    installer.save()
            journal.unlink(missing_ok=True)
            raise SubscriptionError("The update could not be validated. Your previous EyZEE files were restored.") from None
        installer.state["installed_release"] = manifest["version"]
        installer.state['expected_converters']=sorted(set(installer.state.get('expected_converters',[])) | {Path(p).name for p in updates if p.startswith('zigbee2mqtt/external_converters/')})
        installer.state["update_backup"] = recovery["slug"]
        installer.save()
        saved["phase"] = "validated"
        atomic_private(journal, json.dumps(saved).encode())
        installer.stage("installed", "EyZEE has been updated. Home Assistant is restarting; reopen EyZEE when it returns.")
        try:
            installer.api.call("/core/restart", "POST", timeout=180)
        except Exception:
            installer.stage("installed", "The update is installed and checked. Restart Home Assistant to load it.")
        journal.unlink(missing_ok=True)
    finally:
        shutil.rmtree(stage)
