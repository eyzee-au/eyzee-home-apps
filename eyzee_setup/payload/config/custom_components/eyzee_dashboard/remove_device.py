import json
import logging
import yaml

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

DOMAIN = "eyzee_dashboard"

DEVICE_REGISTRY_YAML = "/config/eyzee/state/device_registry.yaml"
BINDINGS_YAML = "/config/eyzee/state/bindings.yaml"
LIGHTING_GROUPS_YAML = "/config/eyzee/state/lighting_groups.yaml"
RULES_YAML = "/config/eyzee/state/rules.yaml"

DEFAULT_REMOVE_DROPDOWN = "input_select.eyzee_remove_device"


def _read_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}
    except Exception as e:
        _LOGGER.warning("EyZEE remove device: failed to read %s: %s", path, e)
        data = {}

    return data if isinstance(data, dict) else {}


def _write_yaml(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _device_label(registry_id: str, device: dict) -> str:
    area = device.get("area_label") or device.get("room") or ""
    display = device.get("display_label") or device.get("device_name") or registry_id
    return f"{area} • {display}" if area else display


def _find_registry_id_from_dropdown(hass: HomeAssistant, value: str) -> str:
    value = (value or "").strip()

    if not value or value in ("none", "unknown", "unavailable"):
        return ""

    dropdown_map = hass.data.get(DOMAIN, {}).get("remove_device_dropdown_map", {})

    if value in dropdown_map:
        return dropdown_map[value]

    return value


def _device_entities(device: dict) -> set[str]:
    entities = set()

    ha_entities = device.get("ha", {}).get("entities", []) or []
    if isinstance(ha_entities, list):
        entities.update(e for e in ha_entities if e)

    controls = device.get("controls", []) or []
    if isinstance(controls, list):
        for control in controls:
            if isinstance(control, dict) and control.get("entity_id"):
                entities.add(control["entity_id"])

    return entities


def _clean_bindings(removed_entities: set[str]):
    data = _read_yaml(BINDINGS_YAML)
    data.setdefault("version", 1)
    data.setdefault("bindings", [])

    new_bindings = []

    for binding in data.get("bindings", []) or []:
        if not isinstance(binding, dict):
            continue

        members = [binding.get("master")] + list(binding.get("slaves", []) or [])
        members = [m for m in members if m and m not in removed_entities]

        if len(members) >= 2:
            new_bindings.append(
                {
                    "master": members[0],
                    "slaves": members[1:],
                }
            )

    data["bindings"] = new_bindings
    _write_yaml(BINDINGS_YAML, data)


def _clean_lighting_groups(removed_entities: set[str]):
    data = _read_yaml(LIGHTING_GROUPS_YAML)
    data.setdefault("version", 1)
    data.setdefault("groups", {})

    groups = data.get("groups", {}) or {}

    if isinstance(groups, dict):
        for group in groups.values():
            if not isinstance(group, dict):
                continue

            members = group.get("members", []) or []
            group["members"] = [m for m in members if m not in removed_entities]

    _write_yaml(LIGHTING_GROUPS_YAML, data)


def _clean_rules(removed_entities: set[str]):
    data = _read_yaml(RULES_YAML)

    if not data:
        return

    # Safe placeholder cleanup for future rules.yaml.
    # Full rules cleanup can be expanded once rules.yaml schema is final.
    _write_yaml(RULES_YAML, data)


def async_register_remove_device_services(hass: HomeAssistant):
    async def handle_populate_remove_device_dropdown(call: ServiceCall):
        dropdown = call.data.get("dropdown_entity", DEFAULT_REMOVE_DROPDOWN)

        data = await hass.async_add_executor_job(_read_yaml, DEVICE_REGISTRY_YAML)
        devices = data.get("devices", {}) or {}

        options = ["none"]
        dropdown_map = {}
        used_labels = {}

        if isinstance(devices, dict):
            for registry_id, device in devices.items():
                if not isinstance(device, dict):
                    continue

                base_label = _device_label(registry_id, device)

                count = used_labels.get(base_label, 0) + 1
                used_labels[base_label] = count

                label = base_label if count == 1 else f"{base_label} ({count})"

                options.append(label)
                dropdown_map[label] = registry_id

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["remove_device_dropdown_map"] = dropdown_map

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": dropdown,
                "options": options,
            },
            blocking=True,
        )

        hass.states.async_set(
            "sensor.eyzee_remove_device_status",
            f"Loaded {len(options) - 1} device(s)",
            {
                "friendly_name": "EyZEE Remove Device Status",
            },
        )

        return True

    async def handle_remove_device(call: ServiceCall):
        registry_id = call.data.get("registry_id") or ""
        remove_from_network = call.data.get("remove_from_network") is True
        confirm = call.data.get("confirm") is True

        if not registry_id:
            st = hass.states.get(DEFAULT_REMOVE_DROPDOWN)
            registry_id = _find_registry_id_from_dropdown(hass, st.state if st else "")

        if not registry_id:
            raise HomeAssistantError("Device is required")

        if not confirm:
            raise HomeAssistantError("Confirmation required: set confirm: true")

        data = await hass.async_add_executor_job(_read_yaml, DEVICE_REGISTRY_YAML)
        data.setdefault("version", 1)
        data.setdefault("devices", {})

        devices = data.get("devices", {}) or {}
        device = devices.get(registry_id)

        if not isinstance(device, dict):
            raise HomeAssistantError(f"Device not found: {registry_id}")

        label = _device_label(registry_id, device)
        removed_entities = _device_entities(device)
        z2m_name = ((device.get("z2m") or {}).get("friendly_name") or "").strip()

        def _remove_from_eyzee():
            data2 = _read_yaml(DEVICE_REGISTRY_YAML)
            data2.setdefault("version", 1)
            data2.setdefault("devices", {})

            devices2 = data2.get("devices", {}) or {}
            if registry_id in devices2:
                del devices2[registry_id]

            data2["devices"] = devices2
            _write_yaml(DEVICE_REGISTRY_YAML, data2)

            _clean_bindings(removed_entities)
            _clean_lighting_groups(removed_entities)
            _clean_rules(removed_entities)

        await hass.async_add_executor_job(_remove_from_eyzee)

        network_message = "Network removal not requested."

        if remove_from_network:
            if z2m_name:
                await mqtt.async_publish(
                    hass,
                    "zigbee2mqtt/bridge/request/device/remove",
                    json.dumps(
                        {
                            "id": z2m_name,
                            "force": False,
                        }
                    ),
                    qos=0,
                    retain=False,
                )
                network_message = f"Zigbee2MQTT safe remove requested for {z2m_name}."
            else:
                network_message = "No Zigbee2MQTT friendly name found. EyZEE records removed only."

        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_remove_device_dropdown",
                {},
                blocking=True,
            )
        except Exception:
            pass

        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_multiway_dropdowns",
                {},
                blocking=True,
            )
        except Exception:
            pass

        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_lighting_group_dropdowns",
                {},
                blocking=True,
            )
        except Exception:
            pass

        hass.states.async_set(
            "sensor.eyzee_remove_device_status",
            "✅ Device removed",
            {
                "friendly_name": "EyZEE Remove Device Status",
                "device": label,
                "entities_removed": sorted(removed_entities),
                "network_message": network_message,
            },
        )

        return True

    hass.services.async_register(
        DOMAIN,
        "populate_remove_device_dropdown",
        handle_populate_remove_device_dropdown,
        schema=vol.Schema(
            {
                vol.Optional(
                    "dropdown_entity",
                    default=DEFAULT_REMOVE_DROPDOWN,
                ): cv.entity_id,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "remove_device",
        handle_remove_device,
        schema=vol.Schema(
            {
                vol.Optional("registry_id", default=""): cv.string,
                vol.Optional("remove_from_network", default=False): cv.boolean,
                vol.Optional("confirm", default=False): cv.boolean,
            }
        ),
    )