"""EyZEE network Zigbee coordinator discovery."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import shutil
from typing import Any

import aiohttp
import ifaddr

from homeassistant.components import mqtt
from homeassistant.exceptions import HomeAssistantError




ROLE_NAMES = {
    "1": "Coordinator",
    "2": "Router",
    "3": "OpenThread",
    "4": "Multi-PAN",
}


MG24_ROUTER_FIRMWARE_URL = (
    "https://raw.githubusercontent.com/"
    "Inswift-dev/inswift-eth-silabs/"
    "main/zigbee-router/Z3Light_dongle_v8.0.2.0.gbl?b=null"
)

MG24_CMD_ZB_FLASH = 7
MG24_CMD_DNS_CHECK = 15

Z2M_CONFIGURATION_YAML = (
    "/config/zigbee2mqtt/configuration.yaml"
)
Z2M_CONFIGURATION_BACKUP = (
    "/config/zigbee2mqtt/"
    "configuration.yaml.eyzee-before-coordinator.bak"
)

Z2M_APP_SLUG = "45df7312_zigbee2mqtt"
Z2M_VERIFY_ATTEMPTS = 18
Z2M_VERIFY_INTERVAL_SECONDS = 5

async def _get_param(
    session: aiohttp.ClientSession,
    ip_address: str,
    parameter: str,
) -> str | None:
    """Read one parameter from the dongle API."""

    url = f"http://{ip_address}/api?action=1&param={parameter}"

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=2),
        ) as response:
            if response.status != 200:
                return None

            value = (await response.text()).strip()

            if not value or value == "wrong args":
                return None

            return value

    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


async def _get_network_values(
    session: aiohttp.ClientSession,
    ip_address: str,
) -> dict[str, Any]:
    """Read network and hardware values from the dongle API."""

    url = (
        f"http://{ip_address}/api"
        "?action=0&page=2&valuesOnly=1"
    )

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=2),
        ) as response:
            if response.status != 200:
                return {}

            values_header = response.headers.get("respValuesArr")

            if not values_header:
                return {}

            values = json.loads(values_header)

            if isinstance(values, dict):
                return values

    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        json.JSONDecodeError,
    ):
        pass

    return {}

def _get_local_ipv4_network() -> ipaddress.IPv4Network | None:
    """Return the local IPv4 LAN network visible to Home Assistant."""

    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if not isinstance(ip.ip, str):
                continue

            address = ipaddress.ip_address(ip.ip)

            if (
                address.is_loopback
                or address.is_link_local
                or not address.is_private
            ):
                continue

            network = ipaddress.ip_network(
                f"{ip.ip}/{ip.network_prefix}",
                strict=False,
            )

            # Ignore Home Assistant internal Docker networks.
            if network.subnet_of(ipaddress.ip_network("172.30.0.0/16")):
                continue

            return network

    return None

async def _port_is_open(
    ip_address: str,
    port: int = 6638,
) -> bool:
    """Check whether the Zigbee TCP port is open."""

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip_address, port),
            timeout=0.35,
        )

        writer.close()
        await writer.wait_closed()

        return True

    except (
        OSError,
        asyncio.TimeoutError,
    ):
        return False

async def discover_eyzee_mg24_devices() -> list[dict[str, Any]]:
    """Discover EyZEE-compatible MG24 dongles on the local IPv4 network."""

    network = _get_local_ipv4_network()

    if network is None:
        return []

    addresses = [
        str(ip_address)
        for ip_address in network.hosts()
    ]

    candidates: list[str] = []

    for start in range(0, len(addresses), 50):
        batch = addresses[start:start + 50]

        results = await asyncio.gather(
            *(_port_is_open(ip_address) for ip_address in batch)
        )

        candidates.extend(
            ip_address
            for ip_address, is_open in zip(batch, results)
            if is_open
        )

    discovered: list[dict[str, Any]] = []

    for ip_address in candidates:
        result = await identify_eyzee_mg24(ip_address)

        if result:
            discovered.append(result)

    return discovered

async def find_eyzee_mg24_by_mac(
    mac_address: str,
) -> dict[str, Any] | None:
    """Rediscover an EyZEE MG24 using its physical Ethernet MAC address."""

    target_mac = mac_address.strip().upper()

    devices = await discover_eyzee_mg24_devices()

    for device in devices:
        device_mac = str(
            device.get("mac_address") or ""
        ).strip().upper()

        if device_mac == target_mac:
            return device

    return None

def get_discovered_coordinators(
    devices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return discovered MG24 devices operating as Zigbee Coordinators."""

    return [
        device
        for device in devices
        if device.get("role") == "1"
    ]

def validate_mg24_coordinator_candidate(
    device: dict[str, Any],
    active_z2m_ip: str | None = None,
) -> tuple[bool, str]:
    """Check whether an MG24 can become the first Zigbee Coordinator."""

    if active_z2m_ip:
        return False, (
            "A Zigbee2MQTT coordinator is already configured"
        )

    if device.get("hardware") != "MG24":
        return False, "Device is not an MG24"

    if not device.get("mac_address"):
        return False, "MG24 MAC address is unavailable"

    if device.get("role") != "1":
        return False, (
            "MG24 is not operating as a Coordinator "
            f"(role: {device.get('role_name', 'Unknown')})"
        )

    if not device.get("ip_address"):
        return False, "MG24 IP address is unavailable"

    return True, "MG24 is ready for Zigbee Coordinator setup"

def validate_mg24_extender_candidate(
    device: dict[str, Any],
    active_z2m_ip: str | None = None,
) -> tuple[bool, str]:
    """Check whether an MG24 is a suitable Zigbee Extender conversion candidate."""

    if device.get("hardware") != "MG24":
        return False, "Device is not an MG24"

    if not device.get("mac_address"):
        return False, "MG24 MAC address is unavailable"

    if device.get("role") != "1":
        return False, (
            f"MG24 is not currently a Coordinator "
            f"(role: {device.get('role_name', 'Unknown')})"
        )

    if not device.get("ip_address"):
        return False, "MG24 IP address is unavailable"

    if active_z2m_ip and device.get("ip_address") == active_z2m_ip:
        return False, (
            "MG24 is currently being used as the "
            "Zigbee2MQTT coordinator"
        )

    return True, "MG24 is ready for Zigbee Extender conversion"

async def preflight_mg24_coordinator_setup(
    mac_address: str,
    active_z2m_ip: str | None,
) -> dict[str, Any]:
    """Perform final read-only checks before Coordinator setup."""

    if active_z2m_ip:
        return {
            "ready": False,
            "status": (
                "A Zigbee2MQTT coordinator is already configured"
            ),
            "active_z2m_ip": active_z2m_ip,
        }

    device = await find_eyzee_mg24_by_mac(
        mac_address
    )

    if not device:
        return {
            "ready": False,
            "status": (
                "The selected MG24 could not be rediscovered"
            ),
            "mac_address": mac_address,
            "active_z2m_ip": active_z2m_ip,
        }

    safe, reason = validate_mg24_coordinator_candidate(
        device,
        active_z2m_ip,
    )

    result = dict(device)

    result["ready"] = safe
    result["status"] = reason
    result["active_z2m_ip"] = active_z2m_ip
    result["serial_port"] = (
        f"tcp://{device.get('ip_address')}:6638"
        if device.get("ip_address")
        else None
    )
    result["adapter"] = "ember"

    return result

async def preflight_mg24_extender_conversion(
    mac_address: str,
    active_z2m_ip: str | None,
) -> dict[str, Any]:
    """Perform final read-only checks before MG24 Extender conversion."""

    if not active_z2m_ip:
        return {
            "ready": False,
            "status": (
                "Active Zigbee2MQTT coordinator could not be determined"
            ),
            "mac_address": mac_address,
            "active_z2m_ip": None,
        }

    if not await _port_is_open(active_z2m_ip):
        return {
            "ready": False,
            "status": (
                "Active Zigbee2MQTT coordinator is not reachable"
            ),
            "mac_address": mac_address,
            "active_z2m_ip": active_z2m_ip,
        }

    device = await find_eyzee_mg24_by_mac(mac_address)

    if not device:
        return {
            "ready": False,
            "status": "MG24 could not be rediscovered by MAC address",
            "mac_address": mac_address,
        }

    safe, reason = validate_mg24_extender_candidate(
        device,
        active_z2m_ip,
    )

    return {
        "ready": safe,
        "status": reason,
        "mac_address": device.get("mac_address"),
        "ip_address": device.get("ip_address"),
        "role": device.get("role"),
        "role_name": device.get("role_name"),
        "firmware": device.get("firmware"),
        "active_z2m_ip": active_z2m_ip,
    }

async def check_mg24_firmware_network(
    ip_address: str,
) -> tuple[bool, str]:
    """Run the MG24 manufacturer's non-flashing firmware network check."""

    url = (
        f"http://{ip_address}/api?"
        f"action=8&cmd={MG24_CMD_DNS_CHECK}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                payload = (await response.text()).strip()

                if response.status != 200:
                    return False, (
                        f"MG24 firmware network check returned "
                        f"HTTP {response.status}"
                    )

                return payload.lower() == "ok", payload

    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        return False, str(err)

async def flash_mg24_router_firmware(
    ip_address: str,
) -> tuple[bool, str]:
    """Request the MG24 to flash the approved EyZEE Router firmware."""

    firmware_url = MG24_ROUTER_FIRMWARE_URL

    url = (
        f"http://{ip_address}/api?"
        f"action=8&cmd={MG24_CMD_ZB_FLASH}"
        f"&url={firmware_url}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                payload = (await response.text()).strip()

                if response.status != 200:
                    return False, (
                        f"MG24 firmware flash request returned "
                        f"HTTP {response.status}"
                    )

                return True, payload

    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        return False, str(err)

async def prepare_mg24_extender_conversion(
    mac_address: str,
    active_z2m_ip: str | None,
) -> dict[str, Any]:
    """Perform final MG24 Extender conversion checks without flashing."""

    result = await preflight_mg24_extender_conversion(
        mac_address,
        active_z2m_ip,
    )

    if not result.get("ready"):
        return result

    check_ok, check_response = await check_mg24_firmware_network(
        result["ip_address"]
    )

    result["firmware_network_check_passed"] = check_ok
    result["firmware_network_check_response"] = check_response

    if not check_ok:
        result["ready"] = False
        result["status"] = (
            "MG24 firmware network check did not pass"
        )
        return result

    result["status"] = (
        "MG24 passed final checks and is ready for Router firmware"
    )

    return result

async def wait_for_mg24_router(
    mac_address: str,
    attempts: int = 12,
    delay: float = 5.0,
) -> dict[str, Any] | None:
    """Wait for the flashed MG24 to return as a Zigbee Router."""

    for _ in range(attempts):
        await asyncio.sleep(delay)

        device = await find_eyzee_mg24_by_mac(mac_address)

        if (
            device
            and device.get("role") == "2"
            and device.get("firmware") == "v8.0.2.0"
        ):
            return device

    return None

async def convert_mg24_to_extender(
    mac_address: str,
    active_z2m_ip: str | None,
) -> dict[str, Any]:
    """Convert an approved MG24 Coordinator to Zigbee Router firmware."""

    result = await prepare_mg24_extender_conversion(
        mac_address,
        active_z2m_ip,
    )

    result["diagnostic_path"] = "convert_mg24_to_extender"

    if not result.get("ready"):
        return result

    # Rediscover the physical target immediately before flashing.
    target = await find_eyzee_mg24_by_mac(mac_address)

    if not target:
        result["ready"] = False
        result["status"] = (
            "MG24 could not be rediscovered immediately before flashing"
        )
        return result

    if target.get("role") != "1":
        result["ready"] = False
        result["status"] = (
            "MG24 is no longer in Coordinator mode"
        )
        return result

    if target.get("ip_address") == active_z2m_ip:
        result["ready"] = False
        result["status"] = (
            "MG24 is now being used as the Zigbee2MQTT coordinator"
        )
        return result

    result["ip_address"] = target["ip_address"]

    flash_ok, flash_response = await flash_mg24_router_firmware(
        target["ip_address"]
    )

    result["flash_request_accepted"] = flash_ok
    result["flash_response"] = flash_response

    if not flash_ok:
        result["ready"] = False
        result["status"] = (
            "MG24 Router firmware flash request failed"
        )
        return result

    router = await wait_for_mg24_router(mac_address)

    if not router:
        result["ready"] = False
        result["status"] = (
            "MG24 flash request was accepted but Router verification failed"
        )
        return result

    result["ready"] = True
    result["status"] = (
        "MG24 successfully converted to Zigbee Router"
    )
    result["ip_address"] = router.get("ip_address")
    result["role"] = router.get("role")
    result["role_name"] = router.get("role_name")
    result["firmware"] = router.get("firmware")

    return result

def get_network_serial_ip(
    serial_port: str | None,
) -> str | None:
    """Return the IP address from a tcp:// network serial port."""

    if not serial_port:
        return None

    prefix = "tcp://"

    if not serial_port.startswith(prefix):
        return None

    address = serial_port[len(prefix):]

    if ":" not in address:
        return None

    host, _port = address.rsplit(":", 1)

    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None

async def identify_eyzee_mg24(
    ip_address: str,
) -> dict[str, Any] | None:
    """Identify an EyZEE-compatible MG24 network dongle."""

    async with aiohttp.ClientSession() as session:
        hardware = await _get_param(
            session,
            ip_address,
            "zbHwVer",
        )

        if hardware != "MG24":
            return None

        role = await _get_param(
            session,
            ip_address,
            "zbRole",
        )

        firmware = await _get_param(
            session,
            ip_address,
            "zbFwVerStr",
        )

        network = await _get_network_values(
            session,
            ip_address,
        )

        return {
            "ip_address": ip_address,
            "hardware": hardware,
            "zigbee_hardware": network.get("zigbeeHwRev"),
            "hardware_revision": network.get("hwRev"),
            "mac_address": network.get("ethMac"),
            "ethernet_connected": network.get("ethConnected"),
            "wifi_connected": network.get("wifiConn"),
            "work_mode": network.get("workMode"),
            "role": role,
            "role_name": ROLE_NAMES.get(role, "Unknown"),
            "firmware": firmware,
        }

def build_zigbee_gateway_inventory(
    devices: list[dict[str, Any]],
    active_z2m_ip: str | None,
) -> list[dict[str, Any]]:
    """Build homeowner-facing EyZEE Zigbee Gateway inventory."""

    gateways: list[dict[str, Any]] = []
    seen_ips: set[str] = set()

    for device in devices:
        gateway = dict(device)

        ip_address = str(gateway.get("ip_address") or "")
        role = str(gateway.get("role") or "")

        if ip_address:
            seen_ips.add(ip_address)

        if active_z2m_ip and ip_address == active_z2m_ip:
            gateway["display_name"] = "My Zigbee Coordinator"
            gateway["display_status"] = "Protected"
            gateway["ui_state"] = "protected"
            gateway["can_convert"] = False

        elif role == "2":
            gateway["display_name"] = "Zigbee Extender"
            gateway["display_status"] = "Already an Extender"
            gateway["ui_state"] = "extender"
            gateway["can_convert"] = False

        elif role == "1" and not active_z2m_ip:
            gateway["display_name"] = "Zigbee Coordinator"
            gateway["display_status"] = "Ready to Set Up"
            gateway["ui_state"] = "setup_ready"
            gateway["can_setup"] = True
            gateway["can_convert"] = False

        elif role == "1":
            safe, reason = validate_mg24_extender_candidate(
                gateway,
                active_z2m_ip,
            )

            gateway["display_name"] = "Zigbee Gateway"
            gateway["display_status"] = (
                "Available to Convert"
                if safe
                else reason
            )
            gateway["ui_state"] = (
                "available"
                if safe
                else "unavailable"
            )
            gateway["can_convert"] = safe

        else:
            gateway["display_name"] = "Zigbee Gateway"
            gateway["display_status"] = (
                f"{gateway.get('role_name', 'Unknown')} mode"
            )
            gateway["ui_state"] = "unavailable"
            gateway["can_convert"] = False

        gateways.append(gateway)

    # Include the active Z2M coordinator even if the normal
    # network discovery scan did not return it.
    if active_z2m_ip and active_z2m_ip not in seen_ips:
        gateways.append(
            {
                "ip_address": active_z2m_ip,
                "hardware": "MG24",
                "mac_address": None,
                "role": "1",
                "role_name": "Coordinator",
                "firmware": None,
                "display_name": "My Zigbee Coordinator",
                "display_status": "Protected",
                "ui_state": "protected",
                "can_convert": False,
            }
        )

    def sort_key(gateway: dict[str, Any]) -> tuple[int, str]:
        protected = (
            0
            if gateway.get("ui_state") == "protected"
            else 1
        )

        return (
            protected,
            str(gateway.get("ip_address") or ""),
        )

    gateways.sort(key=sort_key)

    return gateways


def publish_zigbee_gateway_inventory(
    hass,
    gateways: list[dict[str, Any]],
) -> None:
    """Publish Zigbee Gateways into fixed homeowner UI slots."""

    max_slots = 4

    for index in range(max_slots):
        entity_id = f"sensor.eyzee_zigbee_gateway_{index + 1}"

        if index < len(gateways):
            gateway = gateways[index]

            hass.states.async_set(
                entity_id,
                gateway.get("ui_state", "unknown"),
                gateway,
            )
        else:
            hass.states.async_set(
                entity_id,
                "empty",
                {
                    "display_name": "",
                    "display_status": "",
                    "can_convert": False,
                },
            )

def _read_z2m_configured_serial_port() -> str | None:
    """Read the configured Zigbee2MQTT serial port."""

    if not os.path.isfile(Z2M_CONFIGURATION_YAML):
        return None

    with open(
        Z2M_CONFIGURATION_YAML,
        "r",
        encoding="utf-8",
    ) as file:
        lines = file.readlines()

    serial_start = None

    for index, line in enumerate(lines):
        if re.match(
            r"^serial:\s*(?:\{\s*\}\s*)?(?:#.*)?(?:\r?\n)?$",
            line,
        ):
            serial_start = index
            break

    if serial_start is None:
        return None

    for line in lines[serial_start + 1:]:
        if (
            line.strip()
            and not line.startswith((" ", "\t", "#"))
        ):
            break

        match = re.match(
            r"^[ \t]+port\s*:\s*(.+?)\s*$",
            line,
        )

        if match:
            return (
                match.group(1)
                .split("#", 1)[0]
                .strip()
                .strip("\"'")
            )

    return None

def _write_z2m_coordinator_configuration(
    serial_port: str,
    adapter: str = "ember",
) -> dict[str, str]:
    """Safely update only the Zigbee2MQTT serial settings."""

    if not serial_port.startswith("tcp://"):
        raise HomeAssistantError(
            "Zigbee Coordinator serial port is invalid"
        )

    if adapter != "ember":
        raise HomeAssistantError(
            "Zigbee Coordinator adapter must be ember"
        )

    if not os.path.isfile(Z2M_CONFIGURATION_YAML):
        raise HomeAssistantError(
            "Zigbee2MQTT configuration.yaml was not found"
        )

    with open(
        Z2M_CONFIGURATION_YAML,
        "r",
        encoding="utf-8",
    ) as file:
        lines = file.readlines()

    serial_start = None

    for index, line in enumerate(lines):
        if re.match(
            r"^serial:\s*(?:\{\s*\}\s*)?(?:#.*)?(?:\r?\n)?$",
            line,
        ):
            serial_start = index
            break

    newline = "\r\n" if any(
        line.endswith("\r\n") for line in lines
    ) else "\n"

    if (
        serial_start is not None
        and re.match(
            (
                r"^serial:\s*\{\s*\}\s*"
                r"(?:#.*)?(?:\r?\n)?$"
            ),
            lines[serial_start],
        )
    ):
        lines[serial_start] = f"serial:{newline}"

    for index, line in enumerate(lines):
        if re.match(
            (
                r"^onboarding:\s*true\s*"
                r"(?:#.*)?(?:\r?\n)?$"
            ),
            line,
            flags=re.IGNORECASE,
        ):
            lines[index] = (
                f"onboarding: false{newline}"
            )
            break

    if serial_start is None:
        if lines and not lines[-1].endswith(
            ("\n", "\r")
        ):
            lines[-1] += newline

        lines.extend(
            [
                f"serial:{newline}",
                f"  port: {serial_port}{newline}",
                f"  adapter: {adapter}{newline}",
            ]
        )

    else:
        serial_end = len(lines)

        for index in range(
            serial_start + 1,
            len(lines),
        ):
            line = lines[index]

            if (
                line.strip()
                and not line.startswith((" ", "\t", "#"))
            ):
                serial_end = index
                break

        port_indexes = []
        adapter_indexes = []

        for index in range(
            serial_start + 1,
            serial_end,
        ):
            if re.match(
                r"^[ \t]+port\s*:",
                lines[index],
            ):
                port_indexes.append(index)

            if re.match(
                r"^[ \t]+adapter\s*:",
                lines[index],
            ):
                adapter_indexes.append(index)

        if len(port_indexes) > 1:
            raise HomeAssistantError(
                "Zigbee2MQTT serial configuration "
                "contains duplicate port settings"
            )

        if len(adapter_indexes) > 1:
            raise HomeAssistantError(
                "Zigbee2MQTT serial configuration "
                "contains duplicate adapter settings"
            )

        if port_indexes:
            index = port_indexes[0]
            indent = re.match(
                r"^([ \t]+)",
                lines[index],
            ).group(1)
            lines[index] = (
                f"{indent}port: {serial_port}{newline}"
            )
        else:
            lines.insert(
                serial_end,
                f"  port: {serial_port}{newline}",
            )
            serial_end += 1

        if adapter_indexes:
            index = adapter_indexes[0]
            indent = re.match(
                r"^([ \t]+)",
                lines[index],
            ).group(1)
            lines[index] = (
                f"{indent}adapter: {adapter}{newline}"
            )
        else:
            lines.insert(
                serial_end,
                f"  adapter: {adapter}{newline}",
            )

    if not os.path.exists(
        Z2M_CONFIGURATION_BACKUP
    ):
        shutil.copy2(
            Z2M_CONFIGURATION_YAML,
            Z2M_CONFIGURATION_BACKUP,
        )

    temporary_path = (
        f"{Z2M_CONFIGURATION_YAML}.eyzee.tmp"
    )

    with open(
        temporary_path,
        "w",
        encoding="utf-8",
    ) as file:
        file.writelines(lines)

    original_mode = os.stat(
        Z2M_CONFIGURATION_YAML
    ).st_mode

    os.chmod(
        temporary_path,
        original_mode & 0o777,
    )

    os.replace(
        temporary_path,
        Z2M_CONFIGURATION_YAML,
    )

    return {
        "configuration": Z2M_CONFIGURATION_YAML,
        "backup": Z2M_CONFIGURATION_BACKUP,
        "serial_port": serial_port,
        "adapter": adapter,
    }

def _restore_z2m_configuration_backup() -> None:
    """Restore the Zigbee2MQTT configuration backup."""

    if not os.path.isfile(
        Z2M_CONFIGURATION_BACKUP
    ):
        raise HomeAssistantError(
            "Zigbee2MQTT configuration backup "
            "was not found"
        )

    temporary_path = (
        f"{Z2M_CONFIGURATION_YAML}.eyzee.restore.tmp"
    )

    shutil.copy2(
        Z2M_CONFIGURATION_BACKUP,
        temporary_path,
    )

    os.replace(
        temporary_path,
        Z2M_CONFIGURATION_YAML,
    )

def async_register_zigbee_coordinator_services(hass) -> None:
    """Register EyZEE Zigbee coordinator services."""

    async def get_z2m_serial_port(
        base_topic: str = "zigbee2mqtt",
    ) -> str | None:
        """Return the active Zigbee2MQTT serial port."""

        base_topic = (
            base_topic or "zigbee2mqtt"
        ).strip().strip("/")

        topic_info = f"{base_topic}/bridge/info"

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()

        async def _on_msg(msg) -> None:
            payload = getattr(msg, "payload", "")

            if isinstance(payload, (bytes, bytearray)):
                payload = payload.decode(
                    "utf-8",
                    errors="ignore",
                )
            else:
                payload = str(payload)

            if not fut.done():
                fut.set_result(payload)

        unsub = None

        try:
            unsub = await mqtt.async_subscribe(
                hass,
                topic_info,
                _on_msg,
                qos=0,
            )

            payload = await asyncio.wait_for(
                fut,
                timeout=3.0,
            )

            info = json.loads(payload) if payload else {}

            if not isinstance(info, dict):
                return None

            config = info.get("config", {})

            if not isinstance(config, dict):
                return None

            serial = config.get("serial", {})

            if not isinstance(serial, dict):
                return None

            port = serial.get("port")

            return str(port) if port else None

        except (
            asyncio.TimeoutError,
            json.JSONDecodeError,
        ):
            return None

        finally:
            if unsub:
                try:
                    unsub()
                except Exception:
                    pass

    async def _restart_and_verify_zigbee_coordinator(
        setup_result: dict[str, Any],
    ) -> None:
        """Restart Zigbee2MQTT and verify the new Coordinator."""

        expected_serial_port = setup_result.get(
            "serial_port"
        )
        last_reported_port = None

        setup_result["status"] = (
            "Restarting the Zigbee service"
        )

        hass.states.async_set(
            "sensor.eyzee_zigbee_coordinator_setup",
            "restarting",
            setup_result,
        )

        try:
            await hass.services.async_call(
                "hassio",
                "app_restart",
                {
                    "app": Z2M_APP_SLUG,
                },
                blocking=True,
            )

            for attempt in range(
                1,
                Z2M_VERIFY_ATTEMPTS + 1,
            ):
                await asyncio.sleep(
                    Z2M_VERIFY_INTERVAL_SECONDS
                )

                last_reported_port = (
                    await get_z2m_serial_port()
                )

                setup_result[
                    "verification_attempt"
                ] = attempt

                setup_result[
                    "reported_serial_port"
                ] = last_reported_port

                hass.states.async_set(
                    (
                        "sensor."
                        "eyzee_zigbee_coordinator_setup"
                    ),
                    "verifying",
                    setup_result,
                )

                if (
                    last_reported_port
                    == expected_serial_port
                ):
                    setup_result["ready"] = True
                    setup_result["status"] = (
                        "Zigbee Coordinator ready"
                    )
                    setup_result[
                        "restart_required"
                    ] = False
                    setup_result[
                        "rollback_performed"
                    ] = False

                    hass.states.async_set(
                        (
                            "sensor."
                            "eyzee_zigbee_coordinator_setup"
                        ),
                        "ready",
                        setup_result,
                    )
                    return

            raise HomeAssistantError(
                "Zigbee2MQTT did not reconnect "
                "to the selected Coordinator"
            )

        except Exception as err:
            rollback_error = None

            try:
                await hass.async_add_executor_job(
                    _restore_z2m_configuration_backup
                )

                await hass.services.async_call(
                    "hassio",
                    "app_restart",
                    {
                        "app": Z2M_APP_SLUG,
                    },
                    blocking=True,
                )

                setup_result[
                    "rollback_performed"
                ] = True

            except Exception as restore_err:
                rollback_error = str(restore_err)

                setup_result[
                    "rollback_performed"
                ] = False

            setup_result["ready"] = False
            setup_result["status"] = (
                "Zigbee Coordinator setup failed"
            )
            setup_result["error"] = str(err)
            setup_result[
                "last_reported_serial_port"
            ] = last_reported_port

            if rollback_error:
                setup_result[
                    "rollback_error"
                ] = rollback_error

            hass.states.async_set(
                "sensor.eyzee_zigbee_coordinator_setup",
                "failed",
                setup_result,
            )

    async def handle_identify_mg24(call):
        """Identify one MG24 or automatically discover all MG24 devices."""

        z2m_serial_port = await get_z2m_serial_port()
        z2m_coordinator_ip = get_network_serial_ip(z2m_serial_port)

        hass.states.async_set(
            "sensor.eyzee_z2m_coordinator_diagnostic",
            z2m_coordinator_ip or "unknown",
            {
                "serial_port": z2m_serial_port,
                "coordinator_ip": z2m_coordinator_ip,
            },
        )

        ip_address = call.data.get("ip_address")

        if ip_address:
            result = await identify_eyzee_mg24(ip_address)

            if result:
                safe, reason = validate_mg24_extender_candidate(
                    result,
                    z2m_coordinator_ip,
                )

                result["extender_conversion_safe"] = safe
                result["extender_conversion_status"] = reason
                rediscovered = await find_eyzee_mg24_by_mac(
                    result["mac_address"]
                )

                result["rediscovered_by_mac"] = bool(rediscovered)
                result["rediscovered_ip"] = (
                    rediscovered.get("ip_address")
                    if rediscovered
                    else None
                )

            if result:
                hass.states.async_set(
                    "sensor.eyzee_zigbee_coordinator_discovery",
                    "found",
                    result,
                )
            else:
                hass.states.async_set(
                    "sensor.eyzee_zigbee_coordinator_discovery",
                    "not_found",
                    {
                        "ip_address": ip_address,
                    },
                )

            return

        discovered = await discover_eyzee_mg24_devices()

        gateways = build_zigbee_gateway_inventory(
            discovered,
            z2m_coordinator_ip,
        )

        publish_zigbee_gateway_inventory(
            hass,
            gateways,
        )

        hass.states.async_set(
            "sensor.eyzee_zigbee_coordinator_discovery",
            len(gateways),
            {
                "devices": gateways,
                "device_count": len(gateways),
                "active_z2m_ip": z2m_coordinator_ip,
            },
        )

    async def handle_find_mg24_by_mac(call):
        """Find an MG24 by its physical Ethernet MAC address."""

        mac_address = call.data.get("mac_address")

        if not mac_address:
            return

        z2m_serial_port = await get_z2m_serial_port()
        z2m_coordinator_ip = get_network_serial_ip(z2m_serial_port)

        result = await convert_mg24_to_extender(
            mac_address,
            z2m_coordinator_ip,
        )

        hass.states.async_set(
            "sensor.eyzee_mg24_mac_diagnostic",
            "found" if result else "not_found",
            result or {
                "mac_address": mac_address,
            },
        )

    async def handle_prepare_zigbee_coordinator(call):
        """Check whether a discovered MG24 can become the Coordinator."""

        try:
            slot = int(call.data.get("slot", 0))

        except (TypeError, ValueError):
            slot = 0

        if slot < 1 or slot > 4:
            hass.states.async_set(
                "sensor.eyzee_zigbee_coordinator_setup",
                "blocked",
                {
                    "ready": False,
                    "status": "Select a valid Zigbee Gateway",
                },
            )
            return

        entity_id = (
            f"sensor.eyzee_zigbee_gateway_{slot}"
        )

        state = hass.states.get(entity_id)

        if state is None:
            hass.states.async_set(
                "sensor.eyzee_zigbee_coordinator_setup",
                "blocked",
                {
                    "ready": False,
                    "status": "Selected Zigbee Gateway was not found",
                    "slot": slot,
                },
            )
            return

        mac_address = state.attributes.get(
            "mac_address"
        )

        if not mac_address:
            hass.states.async_set(
                "sensor.eyzee_zigbee_coordinator_setup",
                "blocked",
                {
                    "ready": False,
                    "status": "Selected Zigbee Gateway has no MAC address",
                    "slot": slot,
                },
            )
            return

        mqtt_serial_port = await get_z2m_serial_port()

        configured_serial_port = (
            await hass.async_add_executor_job(
                _read_z2m_configured_serial_port
            )
        )

        mqtt_coordinator_ip = get_network_serial_ip(
            mqtt_serial_port
        )
        configured_coordinator_ip = (
            get_network_serial_ip(
                configured_serial_port
            )
        )

        active_z2m_ip = (
            mqtt_coordinator_ip
            or configured_coordinator_ip
            or mqtt_serial_port
            or configured_serial_port
        )

        result = await preflight_mg24_coordinator_setup(
            mac_address,
            active_z2m_ip,
        )

        result["slot"] = slot

        hass.states.async_set(
            "sensor.eyzee_zigbee_coordinator_setup",
            (
                "ready"
                if result.get("ready")
                else "blocked"
            ),
            result,
        )

    async def handle_setup_zigbee_coordinator(call):
        """Configure Zigbee2MQTT to use the selected MG24."""

        try:
            slot = int(call.data.get("slot", 0))
        except (TypeError, ValueError):
            slot = 0

        if slot < 1 or slot > 4:
            raise HomeAssistantError(
                "Select a valid Zigbee Gateway"
            )

        entity_id = (
            f"sensor.eyzee_zigbee_gateway_{slot}"
        )
        state = hass.states.get(entity_id)

        if state is None:
            raise HomeAssistantError(
                "Selected Zigbee Gateway was not found"
            )

        mac_address = state.attributes.get(
            "mac_address"
        )

        if not mac_address:
            raise HomeAssistantError(
                "Selected Zigbee Gateway has no MAC address"
            )

        mqtt_serial_port = await get_z2m_serial_port()

        configured_serial_port = (
            await hass.async_add_executor_job(
                _read_z2m_configured_serial_port
            )
        )

        mqtt_coordinator_ip = get_network_serial_ip(
            mqtt_serial_port
        )
        configured_coordinator_ip = (
            get_network_serial_ip(
                configured_serial_port
            )
        )

        active_z2m_ip = (
            mqtt_coordinator_ip
            or configured_coordinator_ip
            or mqtt_serial_port
            or configured_serial_port
        )

        result = await preflight_mg24_coordinator_setup(
            mac_address,
            active_z2m_ip,
        )
        result["slot"] = slot

        if not result.get("ready"):
            hass.states.async_set(
                "sensor.eyzee_zigbee_coordinator_setup",
                "blocked",
                result,
            )

            raise HomeAssistantError(
                result.get(
                    "status",
                    "Zigbee Coordinator setup was blocked",
                )
            )

        configuration_result = (
            await hass.async_add_executor_job(
                _write_z2m_coordinator_configuration,
                result["serial_port"],
                result["adapter"],
            )
        )

        result.update(configuration_result)
        result["restart_required"] = True
        result["status"] = (
            "Zigbee2MQTT configuration saved"
        )

        hass.states.async_set(
            "sensor.eyzee_zigbee_coordinator_setup",
            "configured",
            result,
        )

        hass.async_create_task(
            _restart_and_verify_zigbee_coordinator(
                dict(result)
            )
        )

    async def handle_convert_zigbee_gateway(call):
        """Convert a discovered Zigbee Gateway into an Extender."""

        try:
            slot = int(call.data.get("slot", 0))
        except (TypeError, ValueError):
            return

        if slot < 1 or slot > 4:
            return

        entity_id = f"sensor.eyzee_zigbee_gateway_{slot}"
        state = hass.states.get(entity_id)

        if state is None:
            return

        # Only a Gateway explicitly classified as available
        # by the discovery process may be converted.
        if state.state != "available":
            return

        mac_address = state.attributes.get("mac_address")

        if not mac_address:
            return

        # Re-read the active Zigbee2MQTT coordinator immediately
        # before conversion. Do not rely on discovery-time information.
        mqtt_serial_port = await get_z2m_serial_port()

        configured_serial_port = (
            await hass.async_add_executor_job(
                _read_z2m_configured_serial_port
            )
        )

        mqtt_coordinator_ip = get_network_serial_ip(
            mqtt_serial_port
        )
        configured_coordinator_ip = (
            get_network_serial_ip(
                configured_serial_port
            )
        )

        active_z2m_ip = (
            mqtt_coordinator_ip
            or configured_coordinator_ip
            or mqtt_serial_port
            or configured_serial_port
        )

        result = await convert_mg24_to_extender(
            mac_address,
            z2m_coordinator_ip,
        )

        hass.states.async_set(
            "sensor.eyzee_zigbee_extender_conversion",
            "success" if result.get("ready") else "failed",
            result,
        )

        # Rediscover everything after the conversion attempt so
        # the homeowner-facing Gateway list reflects the real state.
        discovered = await discover_eyzee_mg24_devices()

        gateways = build_zigbee_gateway_inventory(
            discovered,
            z2m_coordinator_ip,
        )

        publish_zigbee_gateway_inventory(
            hass,
            gateways,
        )

        hass.states.async_set(
            "sensor.eyzee_zigbee_coordinator_discovery",
            len(gateways),
            {
                "devices": gateways,
                "device_count": len(gateways),
                "active_z2m_ip": z2m_coordinator_ip,
            },
        )

    hass.services.async_register(
        "eyzee_dashboard",
        "identify_mg24",
        handle_identify_mg24,
    )
    
    hass.services.async_register(
        "eyzee_dashboard",
        "prepare_zigbee_coordinator",
        handle_prepare_zigbee_coordinator,
    )

    hass.services.async_register(
        "eyzee_dashboard",
        "setup_zigbee_coordinator",
        handle_setup_zigbee_coordinator,
    )

    hass.services.async_register(
        "eyzee_dashboard",
        "convert_zigbee_gateway",
        handle_convert_zigbee_gateway,
    )

    hass.services.async_register(
        "eyzee_dashboard",
        "find_mg24_by_mac",
        handle_find_mg24_by_mac,
    )