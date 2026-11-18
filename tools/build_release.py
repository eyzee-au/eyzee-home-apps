"""Create an immutable payload package for the official service (no customer data)."""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eyzee_setup"))
from subscription import managed_path


def build(payload, output, version):
    hashes, updates = {}, {}
    files = sorted(p for p in payload.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")
    for path in files:
        relative = path.relative_to(payload).as_posix()
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        if relative.startswith("config/"):
            destination = relative[len("config/"):]
        elif relative.startswith("device-support/zigbee2mqtt/external_converters/"):
            destination = relative[len("device-support/"):]
        else:
            continue
        if managed_path(destination):
            updates[destination] = relative
    metadata = {"format": 1, "version": version, "update_files": updates,
                "requires_setup": "0.1.0-beta.15", "migration": "none"}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, "payload/" + path.relative_to(payload).as_posix())
        archive.writestr("payload-hashes.json", json.dumps(hashes, sort_keys=True))
        archive.writestr("release.json", json.dumps(metadata, sort_keys=True))
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--payload", type=Path, default=ROOT / "eyzee_setup/payload")
    args = parser.parse_args()
    metadata = build(args.payload, args.output, args.version)
    print(json.dumps({"version": args.version, "update_files": len(metadata["update_files"]), "output": str(args.output)}))
