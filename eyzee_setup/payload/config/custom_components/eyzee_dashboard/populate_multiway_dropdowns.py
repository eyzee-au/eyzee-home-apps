import logging
import yaml

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

DOMAIN = "eyzee_dashboard"

DEFAULT_MAIN_DROPDOWN = "input_select.eyzee_multiway_main"
DEFAULT_LINKED_DROPDOWN = "input_select.eyzee_multiway_linked"

DEVICE_REGISTRY_YAML = "/config/eyzee/state/device_registry.yaml"
BINDINGS_YAML = "/config/eyzee/state/bindings.yaml"

EXCLUDE_KEYWORDS = (
    "child_lock",
    "backlight",
    "indicator",
    "countdown",
    "inching",
    "power_on",
    "restart",
    "timer",
    "linkquality",
    "battery",
    "voltage",
    "current",
    "power",
    "energy",
)


def _read_yaml_file(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        _LOGGER.warning("EyZEE multiway: failed to read %s: %s", path, e)
        data = {}

    return data if isinstance(data, dict) else {}


def _read_eyzee_device_registry() -> dict:
    data = _read_yaml_file(DEVICE_REGISTRY_YAML)
    data.setdefault("version", 1)
    data.setdefault("devices", {})
    if not isinstance(data["devices"], dict):
        data["devices"] = {}
    return data


def _read_bindings() -> dict:
    data = _read_yaml_file(BINDINGS_YAML)
    data.setdefault("version", 1)
    data.setdefault("bindings", [])
    if not isinstance(data["bindings"], list):
        data["bindings"] = []
    return data


def _label_for_entity(hass: HomeAssistant, entity_id: str) -> str:
    st = hass.states.get(entity_id)
    if not st:
        return entity_id
    return st.attributes.get("friendly_name") or entity_id


def _is_mqtt_entity(hass: HomeAssistant, entity_id: str) -> bool:
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    entry = ent_reg.async_get(entity_id)
    if not entry or not entry.device_id:
        return False

    device = dev_reg.async_get(entry.device_id)
    if not device:
        return False

    return any(domain == "mqtt" for domain, _ in (device.identifiers or set()))


def _is_allowed_entity(hass: HomeAssistant, entity_id: str) -> bool:
    if not entity_id:
        return False

    if not (entity_id.startswith("switch.") or entity_id.startswith("light.")):
        return False

    lowered = entity_id.lower()

    if any(word in lowered for word in EXCLUDE_KEYWORDS):
        return False

    if not _is_mqtt_entity(hass, entity_id):
        return False

    return hass.states.get(entity_id) is not None


def _extract_entities(hass: HomeAssistant) -> list[str]:
    entities: list[str] = []

    for domain in ("switch", "light"):
        for entity_id in hass.states.async_entity_ids(domain):
            if _is_allowed_entity(hass, entity_id):
                entities.append(entity_id)

    return sorted(set(entities), key=lambda e: _label_for_entity(hass, e).lower())

def _friendly_control_name(
    entity_id: str,
    control: dict,
) -> str:
    """Return a resident-friendly control name."""

    entity_lower = str(entity_id or "").lower()

    # Fan / light controller roles
    if entity_lower.endswith("_light"):
        return "Light"

    if "fan_low" in entity_lower:
        return "Low"

    if "fan_medium" in entity_lower:
        return "Medium"

    if "fan_high" in entity_lower:
        return "High"

    # Normal EyZEE control name
    return (
        control.get("name")
        or control.get("name_slug")
        or entity_id
    )

def _control_label_from_entity(entity_id: str) -> str:
    data = _read_eyzee_device_registry()
    devices = data.get("devices", {}) or {}

    matches = []

    for registry_id, device in devices.items():
        if not isinstance(device, dict):
            continue

        area_label = device.get("area_label") or device.get("room") or ""
        updated = (
            device.get("meta", {}).get("updated")
            if isinstance(device.get("meta"), dict)
            else ""
        )
        device_name = (
            device.get("display_label")
            or device.get("name_label")
            or device.get("device_name")
            or registry_id
        )

        controls = device.get("controls", []) or []

        if not isinstance(controls, list):
            continue

        for control in controls:
            if not isinstance(control, dict):
                continue

            if control.get("entity_id") == entity_id:
                name = _friendly_control_name(
                    entity_id,
                    control,
                )

                label = " • ".join(
                    part
                    for part in (
                        str(area_label).strip(),
                        str(device_name).strip(),
                        str(name).strip(),
                    )
                    if part
                )

                matches.append(
                    {
                        "label": label,
                        "updated": updated or "",
                    }
                )

    if matches:
        matches.sort(key=lambda item: item.get("updated", ""), reverse=True)
        return matches[0]["label"]

    return entity_id

def _extract_registry_controls(hass: HomeAssistant) -> dict[str, str]:
    data = _read_eyzee_device_registry()
    devices = data.get("devices", {})

    dropdown_map: dict[str, str] = {}
    used_labels: dict[str, int] = {}

    if not isinstance(devices, dict):
        return dropdown_map

    for registry_id, device in devices.items():
        if not isinstance(device, dict):
            continue

        area_label = (
            device.get("area_label")
            or device.get("room")
            or ""
        )

        device_name = (
            device.get("display_label")
            or device.get("name_label")
            or device.get("device_name")
            or registry_id
        )

        controls = device.get("controls", []) or []

        if not isinstance(controls, list):
            continue

        for control in controls:
            if not isinstance(control, dict):
                continue

            entity_id = control.get("entity_id")
            name = control.get("name") or control.get("name_slug") or entity_id

            if not entity_id:
                continue

            if not _is_allowed_entity(hass, entity_id):
                continue

            base_label = " • ".join(
                part
                for part in (
                    str(area_label).strip(),
                    str(device_name).strip(),
                    str(name).strip(),
                )
                if part
            )

            count = used_labels.get(base_label, 0) + 1
            used_labels[base_label] = count

            label = base_label if count == 1 else f"{base_label} ({count})"
            dropdown_map[label] = entity_id

    return dict(sorted(dropdown_map.items(), key=lambda item: item[0].lower()))


def _build_bindings_summary() -> str:
    data = _read_bindings()
    bindings = data.get("bindings", []) or []

    if not bindings:
        return "No linked switches yet."

    lines = []

    for idx, binding in enumerate(bindings, start=1):
        if not isinstance(binding, dict):
            continue

        master = binding.get("master")
        slaves = binding.get("slaves", []) or []

        lines.append(f"Link Group {idx}")
        lines.append(f"Main: {_control_label_from_entity(master)}")

        for slave in slaves:
            lines.append(f"Linked: {_control_label_from_entity(slave)}")

        lines.append("")

    return "\n".join(lines).strip() or "No linked switches yet."


def _update_linked_switches_sensor(hass: HomeAssistant):
    hass.states.async_set(
        "sensor.eyzee_linked_switches",
        "Linked Switches",
        {
            "friendly_name": "EyZEE Linked Switches",
            "summary": _build_bindings_summary(),
        },
    )


def async_register_populate_multiway_dropdowns_service(hass: HomeAssistant):
    async def handle_populate_multiway_dropdowns(call: ServiceCall):
        main_dropdown = call.data.get(
            "master_dropdown_entity",
            DEFAULT_MAIN_DROPDOWN,
        )
        linked_dropdown = call.data.get(
            "slave_dropdown_entity",
            DEFAULT_LINKED_DROPDOWN,
        )

        dropdown_map = _extract_registry_controls(hass)

        if not dropdown_map:
            entities = _extract_entities(hass)
            used_labels = {}

            for entity_id in entities:
                base_label = _label_for_entity(hass, entity_id)
                count = used_labels.get(base_label, 0) + 1
                used_labels[base_label] = count
                label = base_label if count == 1 else f"{base_label} ({count})"
                dropdown_map[label] = entity_id

            _LOGGER.warning("EyZEE multiway: using fallback live MQTT entity scan")

        options = ["none"] + list(dropdown_map.keys())

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["multiway_dropdown_map"] = dropdown_map

        _update_linked_switches_sensor(hass)

        for dropdown in (main_dropdown, linked_dropdown):
            await hass.services.async_call(
                "input_select",
                "set_options",
                {
                    "entity_id": dropdown,
                    "options": options,
                },
                blocking=True,
            )

        _LOGGER.info(
            "EyZEE multiway dropdowns populated with %s control(s)",
            len(options) - 1,
        )

    hass.services.async_register(
        DOMAIN,
        "populate_multiway_dropdowns",
        handle_populate_multiway_dropdowns,
        schema=vol.Schema(
            {
                vol.Optional(
                    "master_dropdown_entity",
                    default=DEFAULT_MAIN_DROPDOWN,
                ): cv.entity_id,
                vol.Optional(
                    "slave_dropdown_entity",
                    default=DEFAULT_LINKED_DROPDOWN,
                ): cv.entity_id,
            }
        ),
    )