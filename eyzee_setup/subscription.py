"""Official update client. Never imported by the running EyZEE integration."""
import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


OFFICIAL_SERVICE_URL = "https://subscriptions.eyzee.au"
OFFICIAL_RELEASE_PUBLIC_KEY = "vAoZ9VFR/qYR+LFXJEXJknAnAVBxU8BBuTwylZKeVkA="


class SubscriptionError(Exception):
    """Public error without credentials or raw server output."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None  # Never forward an installation credential to another host.


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def atomic_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


MUTABLE_UI_PATHS = frozenset({
    "eyzee/ui/eyzee-room.yaml",
    "eyzee/ui/eyzee-master.yaml",
    "eyzee/ui/setup/add_device.yaml",
    "eyzee/ui/setup/device_setup.yaml",
})


def managed_path(path):
    """Only application code and static product UI; never home state/settings."""
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(p in {"..", "."} for p in pure.parts) or "\\" in path:
        return False
    if path in MUTABLE_UI_PATHS:
        return False
    prefixes = ("custom_components/eyzee_dashboard/", "custom_zha_quirks/eyzee/",
                "eyzee/helpers/", "eyzee/scripts/", "eyzee/themes/",
                "eyzee/ui/", "zigbee2mqtt/external_converters/")
    if path == "eyzee/dashboards.yaml":
        return True
    return path.startswith(prefixes) and not path.endswith((".pyc", "/")) and "__pycache__" not in pure.parts


class SubscriptionClient:
    def __init__(self, data, service_url="", public_key="", transport=None):
        self.data = Path(data)
        self.url, self.public_key = service_url.rstrip("/"), public_key
        self.transport = transport or self.http
        self.path = self.data / "subscription.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}

    @classmethod
    def configured(cls, data):
        options_path = Path(data) / "options.json"
        options = json.loads(options_path.read_text()) if options_path.exists() else {}
        return cls(data, os.environ.get("EYZEE_SERVICE_URL") or options.get("service_url") or OFFICIAL_SERVICE_URL,
                   os.environ.get("EYZEE_RELEASE_PUBLIC_KEY") or options.get("release_public_key") or OFFICIAL_RELEASE_PUBLIC_KEY)

    def configured_ok(self):
        parts = urlsplit(self.url)
        try:
            public_key = base64.b64decode(self.public_key, validate=True)
        except (ValueError, TypeError):
            public_key = b""
        return bool(parts.scheme == "https" and parts.hostname and not parts.username and
                    not parts.password and not parts.query and not parts.fragment and not parts.path and
                    len(public_key) == 32)

    def save(self):
        atomic_private(self.path, json.dumps(self.state).encode())

    def summary(self):
        return {"configured": self.configured_ok(), "activated": bool(self.state.get("entitlement")),
                **self.state.get("entitlement", {}), "message": self.state.get("message", "Activate to receive official updates and support.")}

    def http(self, path, body=None, binary=False):
        if not self.configured_ok():
            raise SubscriptionError("Official downloads are not configured yet. Contact EyZEE.")
        # LiteSpeed blocks urllib's default Python-urllib user agent before the
        # request reaches the EyZEE service. Identify this client explicitly.
        headers = {"Accept": "application/zip" if binary else "application/json",
                   "User-Agent": "EyZEE-Setup/0.1"}
        if self.state.get("credential"):
            headers["Authorization"] = "Bearer " + self.state["installation_id"] + ":" + self.state["credential"]
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.url + path, data=None if body is None else canonical(body), headers=headers)
        try:
            with build_opener(NoRedirects()).open(request, timeout=60) as response:
                limit = 50_000_000 if binary else 100_000
                value = response.read(limit + 1)
                if len(value) > limit:
                    raise SubscriptionError("The update response is too large. Contact EyZEE.")
                return value if binary else json.loads(value)
        except HTTPError as error:
            message = {401: "Activation could not be verified. Contact EyZEE support.",
                       403: ("EyZEE activation was blocked before it reached the service. Please try again or contact EyZEE support."
                             if path == "/v1/activate" else
                             "This release is not included in your updates access."),
                       404: "No authorised release is available yet. Contact EyZEE.",
                       409: "The code is invalid or already activated elsewhere. Check it or contact EyZEE.",
                       429: "Please wait a minute before trying activation again."}.get(error.code,
                        "EyZEE downloads are temporarily unavailable. Please try again later.")
            raise SubscriptionError(message) from None
        except (OSError, URLError, ValueError):
            raise SubscriptionError("Unable to contact EyZEE. Check your internet connection and try again. Your home keeps working.") from None

    def activate(self, code):
        if not isinstance(code, str) or not 10 <= len(code.strip()) <= 100:
            raise SubscriptionError("Enter the activation code from your EyZEE email.")
        # Save before sending: retries after a lost response reuse the same identity.
        if "credential" not in self.state:
            self.state.update(installation_id=str(uuid4()), credential=secrets.token_urlsafe(40))
            self.save()
        result = self.transport("/v1/activate", {"code": code.strip(), "installation_id": self.state["installation_id"], "credential": self.state["credential"]})
        self.state["entitlement"] = result
        self.state["message"] = "Your EyZEE installation is activated."
        self.save()
        return self.summary()

    def check(self):
        if not self.state.get("entitlement"):
            raise SubscriptionError("Activate this installation using your EyZEE code first.")
        self.state["entitlement"] = self.transport("/v1/entitlement")
        self.state["message"] = "Updates access checked. Your installed home keeps working if access expires."
        self.save()
        return self.summary()

    def release(self):
        if not self.state.get("entitlement"):
            raise SubscriptionError("Activate this installation using your EyZEE code first.")
        envelope = self.transport("/v1/releases/latest")
        manifest = envelope["manifest"]
        try:
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(self.public_key, validate=True))
            key.verify(base64.b64decode(envelope["signature"], validate=True), canonical(manifest))
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", manifest["version"]):
                raise ValueError()
            if manifest["download_path"] != "/v1/download/" + manifest["version"]:
                raise ValueError()
            if type(manifest["size"]) is not int or not 0 < manifest["size"] <= 50_000_000:
                raise ValueError()
        except Exception:
            raise SubscriptionError("The release signature could not be verified. No files have been installed.") from None
        self.state["entitlement"] = envelope["entitlement"]
        self.state["available_release"] = manifest["version"]
        self.save()
        return manifest

    def download(self, manifest):
        archive_bytes = self.transport(manifest["download_path"], binary=True)
        if len(archive_bytes) != manifest["size"] or hashlib.sha256(archive_bytes).hexdigest() != manifest["sha256"]:
            raise SubscriptionError("The release download could not be verified. No files have been installed.")
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        stage = Path(tempfile.mkdtemp(prefix="release-", dir=self.data))
        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                members = archive.infolist()
                names = [m.filename for m in members]
                if len(names) != len(set(names)) or len(names) > 3000 or sum(m.file_size for m in members) > 100_000_000:
                    raise ValueError("Invalid archive size or duplicate entries")
                for member in members:
                    name = PurePosixPath(member.filename)
                    if (name.is_absolute() or ".." in name.parts or name.as_posix()!=member.filename or "\\" in member.filename or
                        stat.S_ISLNK(member.external_attr >> 16) or member.is_dir() or
                        not (member.filename in {"release.json", "payload-hashes.json"} or member.filename.startswith("payload/"))):
                        raise ValueError("Invalid archive path")
                release = json.loads(archive.read("release.json"))
                hashes = json.loads(archive.read("payload-hashes.json"))
                if release["version"] != manifest["version"] or not isinstance(hashes, dict) or not hashes:
                    raise ValueError("Invalid release metadata")
                if set(names) != {"release.json", "payload-hashes.json"} | {"payload/" + name for name in hashes}:
                    raise ValueError("Archive contents do not match its manifest")
                for relative, expected in hashes.items():
                    pure = PurePosixPath(relative)
                    if pure.is_absolute() or ".." in pure.parts or pure.as_posix()!=relative or "\\" in relative:
                        raise ValueError("Invalid manifest path")
                    body = archive.read("payload/" + relative)
                    if hashlib.sha256(body).hexdigest() != expected:
                        raise ValueError("Invalid file digest")
                    target = stage / "payload" / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(body)
                (stage / "payload-hashes.json").write_text(json.dumps(hashes))
                (stage / "release.json").write_text(json.dumps(release))
            return stage, release
        except Exception:
            shutil.rmtree(stage)
            raise SubscriptionError("The update package could not be verified. No files have been installed.") from None
