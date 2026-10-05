import logging
import os
import re
import shutil
import yaml

from datetime import datetime, timezone
from .eyzee_settings import get_aura_rgb

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import (
    async_track_state_change_event,
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "eyzee_dashboard"

DEVICE_REGISTRY_YAML = (
    "/config/eyzee/state/device_registry.yaml"
)

LIGHTING_GROUPS_YAML = (
    "/config/eyzee/state/lighting_groups.yaml"
)

RULES_YAML = (
    "/config/eyzee/state/rules.yaml"
)

GENERATED_AUTOMATIONS_YAML = (
    "/config/eyzee/generated_smart_behaviours.yaml"
)

DEFAULT_TRIGGER_DROPDOWN = (
    "input_select.eyzee_rule_trigger_device"
)

DEFAULT_ACTION_DROPDOWN = (
    "input_select.eyzee_rule_action_device"
)

SAVED_BEHAVIOUR_DROPDOWN = (
    "input_select.eyzee_saved_behaviour"
)

def _read_yaml(path: str) -> dict:
    """Read an EyZEE YAML state file safely."""

    try:
        with open(path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}

    except FileNotFoundError:
        data = {}

    except Exception as err:
        _LOGGER.warning(
            "EyZEE Smart Behaviours: "
            "failed to read %s: %s",
            path,
            err,
        )
        data = {}

    return data if isinstance(data, dict) else {}

def _read_rules_yaml() -> dict:
    """Read and normalise the EyZEE Smart Behaviours rules file."""

    data = _read_yaml(RULES_YAML)

    if not isinstance(data, dict):
        data = {}

    if not isinstance(data.get("blocks"), dict):
        data["blocks"] = {}

    if not isinstance(data.get("behaviours"), dict):
        data["behaviours"] = {}

    if not isinstance(data.get("rules"), dict):
        data["rules"] = {}

    if not isinstance(data.get("meta"), dict):
        data["meta"] = {}

    data["version"] = 2

    data["meta"].setdefault(
        "schema",
        "eyzee_rules_v2",
    )

    data["meta"].setdefault(
        "notes",
        (
            "EyZEE Smart Behaviours. Reusable logic blocks and "
            "behaviour templates are stored here and executed or "
            "generated into Home Assistant automations by EyZEE Core."
        ),
    )

    return data

def _backup_rules_yaml() -> None:
    """Create a backup copy of the current rules file."""

    if not os.path.exists(RULES_YAML):
        return

    backup_path = f"{RULES_YAML}.bak"

    shutil.copy2(
        RULES_YAML,
        backup_path,
    )


def _write_rules_yaml(data: dict) -> None:
    """Safely write the EyZEE Smart Behaviours rules file."""

    directory = os.path.dirname(RULES_YAML)

    os.makedirs(
        directory,
        exist_ok=True,
    )

    _backup_rules_yaml()

    temp_path = f"{RULES_YAML}.tmp"

    with open(
        temp_path,
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            data,
            file,
            sort_keys=False,
            allow_unicode=True,
        )

    os.replace(
        temp_path,
        RULES_YAML,
    )

def _slugify_behaviour_name(name: str) -> str:
    """Convert a behaviour name into a safe rules.yaml key."""

    slug = str(name).strip().lower()

    slug = re.sub(
        r"[^a-z0-9]+",
        "_",
        slug,
    )

    slug = slug.strip("_")

    return slug or "behaviour"


def _unique_behaviour_id(
    behaviours: dict,
    name: str,
) -> str:
    """Return a unique behaviour ID for rules.yaml."""

    base_id = _slugify_behaviour_name(name)
    behaviour_id = base_id
    number = 2

    while behaviour_id in behaviours:
        behaviour_id = f"{base_id}_{number}"
        number += 1

    return behaviour_id

def _utc_timestamp() -> str:
    """Return the current UTC time as an ISO timestamp."""

    return datetime.now(
        timezone.utc
    ).isoformat()

def _domain(entity_id: str) -> str:
    """Return the Home Assistant entity domain."""

    if not entity_id or "." not in entity_id:
        return ""

    return entity_id.split(".", 1)[0].lower()

def _build_native_automation(
    behaviour_id: str,
    behaviour: dict,
) -> dict | None:
    """Translate one EyZEE behaviour into a HA automation."""

    if not isinstance(behaviour, dict):
        return None

    trigger = behaviour.get("trigger", {})

    actions = behaviour.get("actions", [])

    if (
        not isinstance(trigger, dict)
        or not isinstance(actions, list)
        or not actions
    ):
        return None

    trigger_kind = str(
        trigger.get("kind") or ""
    ).strip().lower()

    if trigger_kind == "time":
        trigger_time = str(
            trigger.get("at") or ""
        ).strip()

        if not trigger_time:
            return None

        native_trigger = {
            "trigger": "time",
            "at": trigger_time,
        }

    elif trigger_kind == "sun":
        sun_event = str(
            trigger.get("event") or ""
        ).strip().lower()

        if sun_event not in {
            "sunrise",
            "sunset",
        }:
            return None

        try:
            offset_minutes = int(
                trigger.get("offset_minutes", 0)
            )
        except (
            TypeError,
            ValueError,
        ):
            offset_minutes = 0

        native_trigger = {
            "trigger": "sun",
            "event": sun_event,
        }

        if offset_minutes != 0:
            absolute_minutes = abs(
                offset_minutes
            )

            offset_hours = (
                absolute_minutes // 60
            )

            remaining_minutes = (
                absolute_minutes % 60
            )

            offset_sign = (
                "-"
                if offset_minutes < 0
                else "+"
            )

            native_trigger["offset"] = (
                f"{offset_sign}"
                f"{offset_hours:02d}:"
                f"{remaining_minutes:02d}:00"
            )

    else:
        trigger_entity = str(
            trigger.get("entity_id") or ""
        ).strip()

        trigger_event = str(
            trigger.get("event") or ""
        ).strip()

        if (
            not trigger_entity
            or not trigger_event
            or trigger_event in {
                "above",
                "below",
            }
        ):
            return None

        native_trigger = {
            "trigger": "state",
            "entity_id": trigger_entity,
        }

        if trigger_event != "changes":
            native_trigger["to"] = (
                trigger_event
            )

    native_conditions = []

    conditions = behaviour.get(
        "conditions",
        {},
    )

    if isinstance(conditions, dict):
        time_window = conditions.get(
            "time_window",
            {},
        )

        if (
            isinstance(time_window, dict)
            and time_window.get("enabled") is True
        ):
            start_time = str(
                time_window.get("start") or "00:00:00"
            ).strip()

            end_time = str(
                time_window.get("end") or "00:00:00"
            ).strip()

            native_conditions.append(
                {
                    "condition": "time",
                    "after": start_time,
                    "before": end_time,
                }
            )

    native_actions = []

    for action in actions:
        if not isinstance(action, dict):
            continue

        action_entity = str(
            action.get("entity_id") or ""
        ).strip()

        action_name = str(
            action.get("action") or ""
        ).strip()

        action_domain = _domain(
            action_entity
        )

        if (
            not action_entity
            or not action_name
            or not action_domain
        ):
            continue

        action_data = action.get(
            "data",
            {},
        )

        if not isinstance(action_data, dict):
            action_data = {}

        native_actions.append(
            {
                "action": (
                    f"{action_domain}.{action_name}"
                ),
                "target": {
                    "entity_id": action_entity,
                },
                "data": action_data,
            }
        )

    if not native_actions:
        return None

    behaviour_name = str(
        behaviour.get("name") or behaviour_id
    ).strip()

    return {
        "id": f"eyzee_{behaviour_id}",
        "alias": f"EyZEE - {behaviour_name}",
        "description": (
            "Generated and managed by EyZEE Home."
        ),
        "initial_state": bool(
            behaviour.get("enabled", True)
        ),
        "triggers": [
            native_trigger,
        ],
        "conditions": native_conditions,
        "actions": native_actions,
        "mode": "single",
    }

def _build_generated_automation_package(
    rules_data: dict,
) -> dict:
    """Build the HA package containing EyZEE automations."""

    behaviours = rules_data.get(
        "behaviours",
        {},
    )

    if not isinstance(behaviours, dict):
        behaviours = {}

    native_automations = []

    for behaviour_id, behaviour in behaviours.items():
        native_automation = _build_native_automation(
            str(behaviour_id),
            behaviour,
        )

        if native_automation is not None:
            native_automations.append(
                native_automation
            )

    return {
        "automation": native_automations,
    }


def _write_generated_automation_package(
    rules_data: dict,
) -> None:
    """Safely write the generated HA automation package."""

    directory = os.path.dirname(
        GENERATED_AUTOMATIONS_YAML
    )

    os.makedirs(
        directory,
        exist_ok=True,
    )

    if os.path.exists(
        GENERATED_AUTOMATIONS_YAML
    ):
        shutil.copy2(
            GENERATED_AUTOMATIONS_YAML,
            f"{GENERATED_AUTOMATIONS_YAML}.bak",
        )

    package_data = (
        _build_generated_automation_package(
            rules_data
        )
    )

    temp_path = (
        f"{GENERATED_AUTOMATIONS_YAML}.tmp"
    )

    with open(
        temp_path,
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            package_data,
            file,
            sort_keys=False,
            allow_unicode=True,
        )

    os.replace(
        temp_path,
        GENERATED_AUTOMATIONS_YAML,
    )

def _device_label(
    registry_id: str,
    device: dict,
) -> str:
    """Return the homeowner-facing device name."""

    return str(
        device.get("display_label")
        or device.get("name_label")
        or device.get("device_name")
        or registry_id
    ).strip()


def _room_label(device: dict) -> str:
    """Return the homeowner-facing room name."""

    room = str(
        device.get("area_label")
        or device.get("room")
        or "Other"
    ).strip()

    return room.replace("_", " ").title()


def _add_unique_option(
    option_map: dict,
    label: str,
    entity_id: str,
) -> None:
    """Add an option without overwriting a matching label."""

    label = str(label).strip()
    entity_id = str(entity_id).strip()

    if not label or not entity_id:
        return

    candidate = label
    number = 2

    while (
        candidate in option_map
        and option_map[candidate] != entity_id
    ):
        candidate = f"{label} ({number})"
        number += 1

    option_map[candidate] = entity_id

def _sensor_trigger_name(
    entity_id: str,
    state,
) -> str | None:
    """Return a supported homeowner-facing sensor type."""

    device_class = ""

    if state is not None:
        device_class = str(
            state.attributes.get("device_class") or ""
        ).lower()

    sensor_names = {
        "temperature": "Temperature",
        "humidity": "Humidity",
        "motion": "Motion",
        "occupancy": "Occupancy",
        "door": "Door",
        "window": "Window",
        "opening": "Opening",
        "moisture": "Water Leak",
    }

    if device_class in sensor_names:
        return sensor_names[device_class]

    # Some integrations do not provide device_class, so use the
    # entity ID as a conservative fallback.
    entity_lower = str(entity_id).lower()

    fallback_names = (
        ("temperature", "Temperature"),
        ("humidity", "Humidity"),
        ("motion", "Motion"),
        ("occupancy", "Occupancy"),
        ("contact", "Contact"),
        ("door", "Door"),
        ("window", "Window"),
        ("moisture", "Water Leak"),
        ("water_leak", "Water Leak"),
    )

    for keyword, name in fallback_names:
        if keyword in entity_lower:
            return name

    return None


def _build_rule_options(
    hass: HomeAssistant,
) -> tuple[dict, dict]:
    """Build trigger and action choices from EyZEE state."""

    registry = _read_yaml(DEVICE_REGISTRY_YAML)
    devices = registry.get("devices", {}) or {}

    trigger_map = {}
    action_map = {}
    known_trigger_entities = set()

    trigger_domains = {
        "light",
        "switch",
        "fan",
        "cover",
        "lock",
    }

    action_domains = {
        "light",
        "switch",
        "fan",
        "cover",
        "lock",
    }

    if isinstance(devices, dict):
        for registry_id, device in devices.items():
            if not isinstance(device, dict):
                continue

            device_name = _device_label(
                registry_id,
                device,
            )
            room_name = _room_label(device)
            controls = device.get("controls", []) or []

            usable_controls = [
                control
                for control in controls
                if (
                    isinstance(control, dict)
                    and control.get("entity_id")
                )
            ]

            for control in usable_controls:
                entity_id = str(
                    control.get("entity_id")
                ).strip()

                if not entity_id:
                    continue

                control_name = str(
                    control.get("name")
                    or device_name
                ).strip()

                if len(usable_controls) > 1:
                    display_name = (
                        f"{device_name} • {control_name}"
                    )
                else:
                    display_name = device_name

                option_label = (
                    f"{room_name} • {display_name}"
                )

                domain = _domain(entity_id)

                if domain in trigger_domains:
                    _add_unique_option(
                        trigger_map,
                        option_label,
                        entity_id,
                    )
                    known_trigger_entities.add(entity_id)

                if domain in action_domains:
                    _add_unique_option(
                        action_map,
                        option_label,
                        entity_id,
                    )

            # Sensor entities may not be listed as controls.
            ha_data = device.get("ha") or {}
            ha_entities = ha_data.get("entities", []) or []

            if not isinstance(ha_entities, list):
                continue

            for entity_id in ha_entities:
                entity_id = str(entity_id).strip()
                domain = _domain(entity_id)

                if domain not in {
                    "sensor",
                    "binary_sensor",
                }:
                    continue

                if entity_id in known_trigger_entities:
                    continue

                state = hass.states.get(entity_id)
                sensor_name = _sensor_trigger_name(
                    entity_id,
                    state,
                )

                if not sensor_name:
                    continue

                option_label = (
                    f"{room_name} • "
                    f"{device_name} • "
                    f"{sensor_name}"
                )

                _add_unique_option(
                    trigger_map,
                    option_label,
                    entity_id,
                )
                known_trigger_entities.add(entity_id)

    groups_data = _read_yaml(LIGHTING_GROUPS_YAML)
    groups = groups_data.get("groups", {}) or {}

    if isinstance(groups, dict):
        for group_id, group in groups.items():
            if not isinstance(group, dict):
                continue

            entity_id = str(
                group.get("z2m_entity") or ""
            ).strip()

            if not entity_id:
                continue

            group_name = str(
                group.get("name")
                or group_id
            ).strip()

            room_name = str(
                group.get("room_label")
                or group.get("room")
                or "Other"
            ).replace("_", " ").title()

            option_label = (
                f"{room_name} • {group_name} "
                f"(Lighting Group)"
            )

            _add_unique_option(
                action_map,
                option_label,
                entity_id,
            )

    return trigger_map, action_map

def _trigger_events_for_entity(
    hass: HomeAssistant,
    entity_id: str,
) -> dict:
    """Return homeowner-facing trigger events."""

    domain = _domain(entity_id)
    state = hass.states.get(entity_id)

    if domain in {"light", "switch", "fan"}:
        return {
            "Turns on": "on",
            "Turns off": "off",
        }

    if domain == "cover":
        return {
            "Opens": "open",
            "Closes": "closed",
        }

    if domain == "lock":
        return {
            "Locks": "locked",
            "Unlocks": "unlocked",
        }

    if domain == "sensor":
        sensor_name = _sensor_trigger_name(
            entity_id,
            state,
        )

        if sensor_name == "Temperature":
            return {
                "Rises above": "above",
                "Falls below": "below",
            }

        if sensor_name == "Humidity":
            return {
                "Rises above": "above",
                "Falls below": "below",
            }

        return {
            "Value changes": "changes",
        }

    if domain == "binary_sensor":
        device_class = ""

        if state is not None:
            device_class = str(
                state.attributes.get("device_class") or ""
            ).lower()

        if device_class in {
            "motion",
            "occupancy",
        }:
            return {
                "Motion detected": "on",
                "No motion detected": "off",
            }

        if device_class in {
            "door",
            "window",
            "opening",
        }:
            return {
                "Opens": "on",
                "Closes": "off",
            }

        if device_class in {
            "moisture",
        }:
            return {
                "Water detected": "on",
                "Clear": "off",
            }

        return {
            "Becomes active": "on",
            "Becomes clear": "off",
        }

    return {}


def _actions_for_entity(
    entity_id: str,
) -> dict:
    """Return homeowner-facing target actions."""

    domain = _domain(entity_id)

    if domain == "light":
        return {
            "Turn On": "turn_on",
            "Turn Off": "turn_off",
            "Toggle": "toggle",
            "Turn On with Light Options": "turn_on",
        }

    if domain in {
        "switch",
        "fan",
    }:
        return {
            "Turn on": "turn_on",
            "Turn off": "turn_off",
            "Toggle": "toggle",
        }

    if domain == "cover":
        return {
            "Open": "open_cover",
            "Close": "close_cover",
            "Stop": "stop_cover",
        }

    if domain == "lock":
        return {
            "Lock": "lock",
            "Unlock": "unlock",
        }

    return {}

def async_register_smart_behaviour_services(
    hass: HomeAssistant,
) -> None:
    """Register EyZEE Smart Behaviours services."""

    async def _refresh_saved_behaviour_dropdown(
        rules_data: dict | None = None,
    ) -> dict:
        """Populate the saved-behaviour selector."""

        if rules_data is None:
            rules_data = await hass.async_add_executor_job(
                _read_rules_yaml
            )

        behaviours = rules_data.get(
            "behaviours",
            {},
        )

        if not isinstance(behaviours, dict):
            behaviours = {}

        name_totals = {}

        for behaviour_id, behaviour in behaviours.items():
            if not isinstance(behaviour, dict):
                continue

            behaviour_name = str(
                behaviour.get("name") or behaviour_id
            ).strip()

            name_key = behaviour_name.casefold()

            name_totals[name_key] = (
                name_totals.get(name_key, 0) + 1
            )

        name_numbers = {}
        dropdown_map = {}
        options = ["none"]
        behaviour_inventory = []

        for behaviour_id, behaviour in behaviours.items():
            if not isinstance(behaviour, dict):
                continue

            behaviour_name = str(
                behaviour.get("name") or behaviour_id
            ).strip()

            name_key = behaviour_name.casefold()

            name_numbers[name_key] = (
                name_numbers.get(name_key, 0) + 1
            )

            if name_totals.get(name_key, 0) > 1:
                label = (
                    f"{behaviour_name} "
                    f"({name_numbers[name_key]})"
                )
            else:
                label = behaviour_name

            dropdown_map[label] = str(
                behaviour_id
            )

            options.append(label)

            behaviour_inventory.append(
                {
                    "id": str(behaviour_id),
                    "name": label,
                    "enabled": bool(
                        behaviour.get("enabled", True)
                    ),
                }
            )

        domain_data = hass.data.setdefault(
            DOMAIN,
            {},
        )

        domain_data[
            "saved_behaviour_dropdown_map"
        ] = dropdown_map

        hass.states.async_set(
            "sensor.eyzee_smart_behaviour_inventory",
            len(behaviour_inventory),
            {
                "friendly_name": (
                    "EyZEE Smart Behaviour Inventory"
                ),
                "behaviour_count": len(
                    behaviour_inventory
                ),
                "behaviours": behaviour_inventory,
            },
        )

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": (
                    SAVED_BEHAVIOUR_DROPDOWN
                ),
                "options": options,
            },
            blocking=True,
        )

        return dropdown_map

    async def _refresh_rule_option_dropdowns():
        """Refresh choices for the selected devices."""

        domain_data = hass.data.setdefault(
            DOMAIN,
            {},
        )

        trigger_map = domain_data.get(
            "rule_trigger_dropdown_map",
            {},
        )

        action_map = domain_data.get(
            "rule_action_dropdown_map",
            {},
        )

        trigger_state = hass.states.get(
            DEFAULT_TRIGGER_DROPDOWN
        )

        action_state = hass.states.get(
            DEFAULT_ACTION_DROPDOWN
        )

        trigger_label = (
            trigger_state.state
            if trigger_state is not None
            else "none"
        )

        action_label = (
            action_state.state
            if action_state is not None
            else "none"
        )

        trigger_entity = trigger_map.get(
            trigger_label
        )

        action_entity = action_map.get(
            action_label
        )

        if trigger_entity:
            event_map = _trigger_events_for_entity(
                hass,
                trigger_entity,
            )
        else:
            event_map = {}

        if action_entity:
            target_action_map = _actions_for_entity(
                action_entity
            )
        else:
            target_action_map = {}

        domain_data[
            "rule_trigger_event_map"
        ] = event_map

        domain_data[
            "rule_target_action_map"
        ] = target_action_map

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": (
                    "input_select."
                    "eyzee_rule_trigger_event"
                ),
                "options": [
                    "none",
                    *event_map.keys(),
                ],
            },
            blocking=True,
        )

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": (
                    "input_select."
                    "eyzee_rule_action_type"
                ),
                "options": [
                    "none",
                    *target_action_map.keys(),
                ],
            },
            blocking=True,
        )

        trigger_kind = "none"

        if trigger_entity:
            trigger_domain = _domain(
                trigger_entity
            )

            if trigger_domain in {
                "sensor",
                "binary_sensor",
            }:
                trigger_state = hass.states.get(
                    trigger_entity
                )

                sensor_name = _sensor_trigger_name(
                    trigger_entity,
                    trigger_state,
                )

                trigger_kind = (
                    str(sensor_name)
                    .strip()
                    .lower()
                    .replace(" ", "_")
                    if sensor_name
                    else trigger_domain
                )
            else:
                trigger_kind = trigger_domain

        action_domain = (
            _domain(action_entity)
            if action_entity
            else "none"
        )

        hass.states.async_set(
            "sensor.eyzee_rule_trigger_context",
            trigger_kind,
            {
                "friendly_name": (
                    "EyZEE Rule Trigger Context"
                ),
                "entity_id": trigger_entity,
            },
        )

        hass.states.async_set(
            "sensor.eyzee_rule_action_context",
            action_domain,
            {
                "friendly_name": (
                    "EyZEE Rule Action Context"
                ),
                "entity_id": action_entity,
            },
        )

    async def handle_populate_rule_device_dropdown(
        call: ServiceCall,
    ):
        trigger_dropdown = str(
            call.data.get("trigger_dropdown_entity")
            or DEFAULT_TRIGGER_DROPDOWN
        ).strip()

        action_dropdown = str(
            call.data.get("action_dropdown_entity")
            or DEFAULT_ACTION_DROPDOWN
        ).strip()

        trigger_map, action_map = (
            await hass.async_add_executor_job(
                _build_rule_options,
                hass,
            )
        )

        trigger_options = [
            "none",
            *sorted(
                trigger_map.keys(),
                key=str.lower,
            ),
        ]

        action_options = [
            "none",
            *sorted(
                action_map.keys(),
                key=str.lower,
            ),
        ]

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][
            "rule_trigger_dropdown_map"
        ] = trigger_map
        hass.data[DOMAIN][
            "rule_action_dropdown_map"
        ] = action_map

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": trigger_dropdown,
                "options": trigger_options,
            },
            blocking=True,
        )

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": action_dropdown,
                "options": action_options,
            },
            blocking=True,
        )

        await _refresh_rule_option_dropdowns()

        hass.states.async_set(
            "sensor.eyzee_smart_behaviour_status",
            "Device choices refreshed",
            {
                "friendly_name": (
                    "EyZEE Smart Behaviour Status"
                ),
                "trigger_count": len(trigger_map),
                "action_count": len(action_map),
            },
        )

        return True

    async def handle_populate_rule_option_dropdowns(
        call: ServiceCall,
    ):
        """Manually refresh event and action choices."""

        await _refresh_rule_option_dropdowns()
        return True

    async def handle_populate_saved_behaviour_dropdown(
        call: ServiceCall,
    ):
        """Refresh the saved-behaviour selector."""

        await _refresh_saved_behaviour_dropdown()
        return True

    async def _reset_smart_behaviour_form() -> None:
        """Reset the Smart Behaviour form after a successful save."""

        await hass.services.async_call(
            "input_text",
            "set_value",
            {
                "entity_id": (
                    "input_text.eyzee_behaviour_name"
                ),
                "value": "",
            },
            blocking=True,
        )

        select_defaults = {
            "input_select.eyzee_rule_trigger_type": (
                "A device changes"
            ),
            "input_select.eyzee_rule_trigger_device": "none",
            "input_select.eyzee_rule_trigger_event": "none",
            "input_select.eyzee_rule_action_device": "none",
            "input_select.eyzee_rule_action_type": "none",
            "input_select.eyzee_rule_brightness_preset": (
                "Keep current brightness"
            ),
            "input_select.eyzee_rule_colour_preset": (
                "Keep current colour"
            ),
            "input_select.eyzee_rule_sun_offset_direction": "At",
        }

        for entity_id, option in select_defaults.items():
            state = hass.states.get(entity_id)

            if state is None:
                continue

            options = state.attributes.get(
                "options",
                [],
            )

            if option not in options:
                continue

            await hass.services.async_call(
                "input_select",
                "select_option",
                {
                    "entity_id": entity_id,
                    "option": option,
                },
                blocking=True,
            )

        await hass.services.async_call(
            "input_boolean",
            "turn_on",
            {
                "entity_id": (
                    "input_boolean.eyzee_rule_enabled"
                ),
            },
            blocking=True,
        )

        await hass.services.async_call(
            "input_boolean",
            "turn_off",
            {
                "entity_id": (
                    "input_boolean."
                    "eyzee_rule_use_time_window"
                ),
            },
            blocking=True,
        )

        await hass.services.async_call(
            "input_number",
            "set_value",
            {
                "entity_id": (
                    "input_number."
                    "eyzee_rule_sun_offset_minutes"
                ),
                "value": 0,
            },
            blocking=True,
        )

        await hass.services.async_call(
            DOMAIN,
            "populate_rule_device_dropdown",
            {},
            blocking=True,
        )

    async def handle_create_smart_behaviour(
        call: ServiceCall,
    ):
        """Validate selections for a new EyZEE Smart Behaviour."""

        behaviour_name_state = hass.states.get(
            "input_text.eyzee_behaviour_name"
        )

        behaviour_name = (
            str(behaviour_name_state.state).strip()
            if behaviour_name_state is not None
            else ""
        )

        if not behaviour_name:
            raise vol.Invalid(
                "Behaviour Name is required."
            )

        trigger_type_state = hass.states.get(
            "input_select.eyzee_rule_trigger_type"
        )

        trigger_type_label = (
            str(trigger_type_state.state).strip()
            if trigger_type_state is not None
            else "A device changes"
        )

        valid_trigger_types = {
            "A device changes",
            "It is a set time",
            "It is sunrise",
            "It is sunset",
        }

        if trigger_type_label not in valid_trigger_types:
            raise vol.Invalid(
                "Choose when this behaviour should happen."
            )

        trigger_device_state = hass.states.get(
            "input_select.eyzee_rule_trigger_device"
        )

        trigger_event_state = hass.states.get(
            "input_select.eyzee_rule_trigger_event"
        )

        action_device_state = hass.states.get(
            "input_select.eyzee_rule_action_device"
        )

        action_type_state = hass.states.get(
            "input_select.eyzee_rule_action_type"
        )

        trigger_label = (
            str(trigger_device_state.state).strip()
            if trigger_device_state is not None
            else "none"
        )

        trigger_event_label = (
            str(trigger_event_state.state).strip()
            if trigger_event_state is not None
            else "none"
        )

        action_label = (
            str(action_device_state.state).strip()
            if action_device_state is not None
            else "none"
        )

        action_type_label = (
            str(action_type_state.state).strip()
            if action_type_state is not None
            else "none"
        )

        selections = {
            "Device to control": action_label,
            "What EyZEE Home should do": action_type_label,
        }

        if trigger_type_label == "A device changes":
            selections.update(
                {
                    "Device": trigger_label,
                    "What happens": trigger_event_label,
                }
            )

        for selection_name, selection_value in selections.items():
            if not selection_value or selection_value.lower() == "none":
                raise vol.Invalid(
                    f"{selection_name} must be selected."
                )

        domain_data = hass.data.setdefault(
            DOMAIN,
            {},
        )

        trigger_map = domain_data.get(
            "rule_trigger_dropdown_map",
            {},
        )

        action_map = domain_data.get(
            "rule_action_dropdown_map",
            {},
        )

        trigger_event_map = domain_data.get(
            "rule_trigger_event_map",
            {},
        )

        target_action_map = domain_data.get(
            "rule_target_action_map",
            {},
        )

        action_entity = action_map.get(
            action_label
        )

        action_type = target_action_map.get(
            action_type_label
        )

        if not action_entity:
            raise vol.Invalid(
                "The selected device could not be resolved."
            )

        if not action_type:
            raise vol.Invalid(
                "The selected action could not be resolved."
            )

        if trigger_type_label == "A device changes":
            trigger_entity = trigger_map.get(
                trigger_label
            )

            trigger_event = trigger_event_map.get(
                trigger_event_label
            )

            if not trigger_entity:
                raise vol.Invalid(
                    "The selected device could not be resolved."
                )

            if not trigger_event:
                raise vol.Invalid(
                    "What happens could not be resolved."
                )

            trigger_record = {
                "entity_id": trigger_entity,
                "event": trigger_event,
                "kind": _domain(trigger_entity),
                "threshold": None,
                "duration_minutes": 0,
            }

        elif trigger_type_label == "It is a set time":
            trigger_time_state = hass.states.get(
                "input_datetime.eyzee_rule_trigger_time"
            )

            trigger_time = (
                str(trigger_time_state.state).strip()
                if trigger_time_state is not None
                else ""
            )

            if trigger_time in {
                "",
                "unknown",
                "unavailable",
            }:
                raise vol.Invalid(
                    "Choose a time for this behaviour."
                )

            trigger_record = {
                "kind": "time",
                "at": trigger_time,
            }

        else:
            sun_event = (
                "sunrise"
                if trigger_type_label == "It is sunrise"
                else "sunset"
            )

            direction_state = hass.states.get(
                "input_select."
                "eyzee_rule_sun_offset_direction"
            )

            direction = (
                str(direction_state.state).strip()
                if direction_state is not None
                else "At"
            )

            if direction not in {
                "At",
                "Before",
                "After",
            }:
                raise vol.Invalid(
                    "Choose At, Before or After."
                )

            offset_state = hass.states.get(
                "input_number."
                "eyzee_rule_sun_offset_minutes"
            )

            try:
                offset_minutes = int(
                    round(
                        float(offset_state.state)
                    )
                )
            except (
                AttributeError,
                TypeError,
                ValueError,
            ):
                offset_minutes = 0

            offset_minutes = max(
                0,
                min(180, offset_minutes),
            )

            if direction == "Before":
                offset_minutes = -offset_minutes

            elif direction == "At":
                offset_minutes = 0

            trigger_record = {
                "kind": "sun",
                "event": sun_event,
                "offset_minutes": offset_minutes,
            }

        enabled_state = hass.states.get(
            "input_boolean.eyzee_rule_enabled"
        )

        enabled = (
            enabled_state is not None
            and enabled_state.state == "on"
        )

        use_time_window_state = hass.states.get(
            "input_boolean.eyzee_rule_use_time_window"
        )

        use_time_window = (
            use_time_window_state is not None
            and use_time_window_state.state == "on"
        )

        start_state = hass.states.get(
            "input_datetime.eyzee_rule_start"
        )

        end_state = hass.states.get(
            "input_datetime.eyzee_rule_end"
        )

        start_time = (
            str(start_state.state).strip()
            if start_state is not None
            else "00:00:00"
        )

        end_time = (
            str(end_state.state).strip()
            if end_state is not None
            else "00:00:00"
        )

        action_data = {}

        if (
            _domain(action_entity) == "light"
            and action_type == "turn_on"
        ):
        
            brightness_state = hass.states.get(
                "input_select.eyzee_rule_brightness_preset"
            )

            brightness_label = (
                str(brightness_state.state).strip()
                if brightness_state is not None
                else "Keep current brightness"
            )

            brightness_map = {
                "Low – 1%": 1,
                "Soft – 35%": 35,
                "Bright – 70%": 70,
                "Maximum – 100%": 100,
            }

            if brightness_label in brightness_map:
                action_data["brightness_pct"] = (
                    brightness_map[brightness_label]
                )

            elif brightness_label == "Custom":
                custom_brightness_state = hass.states.get(
                    "input_number.eyzee_rule_brightness"
                )

                if custom_brightness_state is not None:
                    action_data["brightness_pct"] = int(
                        round(
                            float(
                                custom_brightness_state.state
                            )
                        )
                    )

            colour_state = hass.states.get(
                "input_select.eyzee_rule_colour_preset"
            )

            colour_label = (
                str(colour_state.state).strip()
                if colour_state is not None
                else "Keep current colour"
            )

            colour_map = {
                "Warm – 2700 K": {
                    "color_temp_kelvin": 2700,
                },
                "Natural – 4000 K": {
                    "color_temp_kelvin": 4000,
                },
                "Cool – 6000 K": {
                    "color_temp_kelvin": 6000,
                },
                "Aura": {
                    "rgb_color": get_aura_rgb(),
                },
            }

            if colour_label in colour_map:
                action_data.update(
                    colour_map[colour_label]
                )

        rules_data = await hass.async_add_executor_job(
            _read_rules_yaml
        )

        behaviours = rules_data.get(
            "behaviours",
            {},
        )

        duplicate_name = any(
            isinstance(existing_behaviour, dict)
            and str(
                existing_behaviour.get("name") or ""
            ).strip().casefold()
            == behaviour_name.casefold()
            for existing_behaviour in behaviours.values()
        )

        if duplicate_name:
            raise vol.Invalid(
                "A behaviour with this name already exists. "
                "Please choose a different name."
            )

        behaviour_id = _unique_behaviour_id(
            behaviours,
            behaviour_name,
        )

        timestamp = _utc_timestamp()

        behaviour_record = {
            "name": behaviour_name,
            "enabled": enabled,
            "trigger": trigger_record,
            "conditions": {
                "time_window": {
                    "enabled": use_time_window,
                    "start": start_time,
                    "end": end_time,
                },
            },
            "actions": [
                {
                    "entity_id": action_entity,
                    "action": action_type,
                    "data": action_data,
                },
            ],
            "meta": {
                "created": timestamp,
                "updated": timestamp,
            },
        }

        behaviours[behaviour_id] = behaviour_record

        rules_data["behaviours"] = behaviours

        await hass.async_add_executor_job(
            _write_rules_yaml,
            rules_data,
        )

        await hass.async_add_executor_job(
            _write_generated_automation_package,
            rules_data,
        )

        await hass.services.async_call(
            "automation",
            "reload",
            {},
            blocking=True,
        )

        await _refresh_saved_behaviour_dropdown(
            rules_data
        )

        try:
            await _reset_smart_behaviour_form()

        except Exception as err:
            _LOGGER.warning(
                "EyZEE Smart Behaviours: "
                "behaviour saved but form reset failed: %s",
                err,
            )

        hass.states.async_set(
            "sensor.eyzee_smart_behaviour_status",
            f"Saved: {behaviour_name}",
            {
                "friendly_name": (
                    "EyZEE Smart Behaviour Status"
                ),
                "behaviour_id": behaviour_id,
                "behaviour_name": behaviour_name,
            },
        )

        return True

    async def handle_toggle_smart_behaviour(
        call: ServiceCall,
    ):
        """Enable or disable the selected Smart Behaviour."""

        selected_state = hass.states.get(
            SAVED_BEHAVIOUR_DROPDOWN
        )

        selected_label = (
            str(selected_state.state).strip()
            if selected_state is not None
            else "none"
        )

        if (
            not selected_label
            or selected_label.lower() == "none"
        ):
            raise vol.Invalid(
                "Select a behaviour to enable or disable."
            )

        domain_data = hass.data.setdefault(
            DOMAIN,
            {},
        )

        dropdown_map = domain_data.get(
            "saved_behaviour_dropdown_map",
            {},
        )

        behaviour_id = dropdown_map.get(
            selected_label
        )

        if not behaviour_id:
            raise vol.Invalid(
                "The selected behaviour could not be resolved."
            )

        rules_data = await hass.async_add_executor_job(
            _read_rules_yaml
        )

        behaviours = rules_data.get(
            "behaviours",
            {},
        )

        behaviour = behaviours.get(
            behaviour_id
        )

        if not isinstance(behaviour, dict):
            raise vol.Invalid(
                "The selected behaviour no longer exists."
            )

        behaviour_name = str(
            behaviour.get("name") or behaviour_id
        ).strip()

        enabled = not bool(
            behaviour.get("enabled", True)
        )

        behaviour["enabled"] = enabled

        meta = behaviour.get("meta")

        if not isinstance(meta, dict):
            meta = {}

        meta["updated"] = _utc_timestamp()
        behaviour["meta"] = meta

        behaviours[behaviour_id] = behaviour
        rules_data["behaviours"] = behaviours

        await hass.async_add_executor_job(
            _write_rules_yaml,
            rules_data,
        )

        await hass.async_add_executor_job(
            _write_generated_automation_package,
            rules_data,
        )

        await hass.services.async_call(
            "automation",
            "reload",
            {},
            blocking=True,
        )

        await _refresh_saved_behaviour_dropdown(
            rules_data
        )

        status_text = (
            "Enabled"
            if enabled
            else "Disabled"
        )

        hass.states.async_set(
            "sensor.eyzee_smart_behaviour_status",
            f"{status_text}: {behaviour_name}",
            {
                "friendly_name": (
                    "EyZEE Smart Behaviour Status"
                ),
                "behaviour_id": behaviour_id,
                "behaviour_name": behaviour_name,
                "enabled": enabled,
            },
        )

        return True

    async def handle_delete_smart_behaviour(
        call: ServiceCall,
    ):
        """Delete the selected EyZEE Smart Behaviour."""

        selected_state = hass.states.get(
            SAVED_BEHAVIOUR_DROPDOWN
        )

        selected_label = (
            str(selected_state.state).strip()
            if selected_state is not None
            else "none"
        )

        if (
            not selected_label
            or selected_label.lower() == "none"
        ):
            raise vol.Invalid(
                "Select a behaviour to delete."
            )

        domain_data = hass.data.setdefault(
            DOMAIN,
            {},
        )

        dropdown_map = domain_data.get(
            "saved_behaviour_dropdown_map",
            {},
        )

        behaviour_id = dropdown_map.get(
            selected_label
        )

        if not behaviour_id:
            raise vol.Invalid(
                "The selected behaviour could not be resolved."
            )

        rules_data = await hass.async_add_executor_job(
            _read_rules_yaml
        )

        behaviours = rules_data.get(
            "behaviours",
            {},
        )

        behaviour = behaviours.get(
            behaviour_id
        )

        if not isinstance(behaviour, dict):
            raise vol.Invalid(
                "The selected behaviour no longer exists."
            )

        behaviour_name = str(
            behaviour.get("name") or behaviour_id
        ).strip()

        del behaviours[behaviour_id]

        rules_data["behaviours"] = behaviours

        await hass.async_add_executor_job(
            _write_rules_yaml,
            rules_data,
        )

        await hass.async_add_executor_job(
            _write_generated_automation_package,
            rules_data,
        )

        await hass.services.async_call(
            "automation",
            "reload",
            {},
            blocking=True,
        )

        await _refresh_saved_behaviour_dropdown(
            rules_data
        )

        hass.states.async_set(
            "sensor.eyzee_smart_behaviour_status",
            f"Deleted: {behaviour_name}",
            {
                "friendly_name": (
                    "EyZEE Smart Behaviour Status"
                ),
                "behaviour_id": behaviour_id,
                "behaviour_name": behaviour_name,
            },
        )

        return True

    async def handle_smart_behaviour_startup(event):
        """Populate Smart Behaviour choices after HA starts."""

        await hass.services.async_call(
            DOMAIN,
            "populate_rule_device_dropdown",
            {},
            blocking=True,
        )

        await _refresh_saved_behaviour_dropdown()

    async def handle_rule_device_changed(event):
        """Refresh dependent choices after a selection."""

        await _refresh_rule_option_dropdowns()

    hass.services.async_register(
        DOMAIN,
        "populate_rule_device_dropdown",
        handle_populate_rule_device_dropdown,
        schema=vol.Schema(
            {
                vol.Optional(
                    "trigger_dropdown_entity",
                    default=DEFAULT_TRIGGER_DROPDOWN,
                ): str,
                vol.Optional(
                    "action_dropdown_entity",
                    default=DEFAULT_ACTION_DROPDOWN,
                ): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "populate_rule_option_dropdowns",
        handle_populate_rule_option_dropdowns,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "populate_saved_behaviour_dropdown",
        handle_populate_saved_behaviour_dropdown,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "create_smart_behaviour",
        handle_create_smart_behaviour,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "toggle_smart_behaviour",
        handle_toggle_smart_behaviour,
        schema=vol.Schema({}),
    )


    hass.services.async_register(
        DOMAIN,
        "delete_smart_behaviour",
        handle_delete_smart_behaviour,
        schema=vol.Schema({}),
    )

    async_track_state_change_event(
        hass,
        [
            DEFAULT_TRIGGER_DROPDOWN,
            DEFAULT_ACTION_DROPDOWN,
        ],
        handle_rule_device_changed,
    )

    hass.bus.async_listen_once(
        "homeassistant_started",
        handle_smart_behaviour_startup,
    )