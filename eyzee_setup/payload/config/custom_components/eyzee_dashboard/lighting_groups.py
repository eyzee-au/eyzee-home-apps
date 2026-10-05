import json
import logging
import yaml

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from .eyzee_settings import save_aura_rgb


_LOGGER = logging.getLogger(__name__)

DOMAIN = "eyzee_dashboard"

DEVICE_REGISTRY_YAML = "/config/eyzee/state/device_registry.yaml"
LIGHTING_GROUPS_YAML = "/config/eyzee/state/lighting_groups.yaml"

DEFAULT_GROUP_DROPDOWN = "input_select.eyzee_lighting_group"
AURA_GROUP_DROPDOWN = "input_select.eyzee_aura_source_group"
DEFAULT_ROOM_DROPDOWN = "input_select.eyzee_lighting_group_room"
DEFAULT_MEMBER_DROPDOWN = "input_select.eyzee_lighting_group_member"


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    out = ""
    prev_underscore = False

    for ch in value:
        if ch.isalnum():
            out += ch
            prev_underscore = False
        else:
            if not prev_underscore:
                out += "_"
                prev_underscore = True

    return out.strip("_") or "unnamed"


def _read_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        data = {}
    except Exception as e:
        _LOGGER.warning("EyZEE lighting groups: failed to read %s: %s", path, e)
        data = {}

    return data if isinstance(data, dict) else {}


def _write_yaml(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _read_device_registry() -> dict:
    data = _read_yaml(DEVICE_REGISTRY_YAML)
    data.setdefault("version", 1)
    data.setdefault("devices", {})

    if not isinstance(data["devices"], dict):
        data["devices"] = {}

    return data


def _read_lighting_groups() -> dict:
    data = _read_yaml(LIGHTING_GROUPS_YAML)
    data.setdefault("version", 1)
    data.setdefault("groups", {})

    if not isinstance(data["groups"], dict):
        data["groups"] = {}

    return data


def _write_lighting_groups(data: dict):
    data.setdefault("version", 1)
    data.setdefault("groups", {})
    _write_yaml(LIGHTING_GROUPS_YAML, data)


def _entity_to_z2m_friendly_name(entity_id: str) -> str:
    """
    Convert HA entity_id to likely Zigbee2MQTT friendly name.

    Examples:
        light.downlight1 -> downlight1
        light.0xa4c138754f35ccea -> 0xa4c138754f35ccea
    """

    if not entity_id or "." not in entity_id:
        return entity_id

    return entity_id.split(".", 1)[1]


def _control_label_from_entity(hass: HomeAssistant, entity_id: str) -> str:
    registry = _read_device_registry()
    devices = registry.get("devices", {}) or {}

    matches = []

    for device in devices.values():
        if not isinstance(device, dict):
            continue

        area = device.get("area_label") or device.get("room") or ""

        updated = (
            device.get("meta", {}).get("updated")
            if isinstance(device.get("meta"), dict)
            else ""
        )

        controls = device.get("controls", []) or []

        if not isinstance(controls, list):
            continue

        for control in controls:
            if not isinstance(control, dict):
                continue

            if control.get("entity_id") == entity_id:
                name = control.get("name") or control.get("name_slug") or entity_id
                label = f"{area} • {name}" if area else str(name)
                matches.append(
                    {
                        "label": label,
                        "updated": updated or "",
                    }
                )

    if matches:
        matches.sort(key=lambda item: item.get("updated", ""), reverse=True)
        return matches[0]["label"]

    st = hass.states.get(entity_id)
    if st:
        return st.attributes.get("friendly_name") or entity_id

    return entity_id


def _is_noisy_entity(entity_id: str) -> bool:
    lowered = (entity_id or "").lower()

    noisy_words = (
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

    return any(word in lowered for word in noisy_words)


def _extract_registry_controls(hass: HomeAssistant) -> dict[str, str]:
    registry = _read_device_registry()
    devices = registry.get("devices", {}) or {}

    dropdown_map: dict[str, str] = {}
    used_labels: dict[str, int] = {}
    used_entities = set()

    # Registry-only controls.
    # Lighting Groups should only show devices that have been properly added to EyZEE.
    for device in devices.values():
        if not isinstance(device, dict):
            continue

        area = device.get("area_label") or device.get("room") or ""
        device_type = device.get("device_type") or ""
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

            lowered = entity_id.lower()

            exclude_words = (
                "permit_join",
                "bridge",
                "coordinator",
                "do_not_disturb",
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
                "color_power_on_behavior",
            )

            if any(word in lowered for word in exclude_words):
                continue

            # Lighting Groups should only use light entities.
            # Switch buttons belong in Link Switches / Automations.
            if not entity_id.startswith("light."):
                continue

            if not hass.states.get(entity_id):
                continue

            used_entities.add(entity_id)

            base_label = f"{area} • {name}" if area else str(name)

            count = used_labels.get(base_label, 0) + 1
            used_labels[base_label] = count

            label = base_label if count == 1 else f"{base_label} ({count})"
            dropdown_map[label] = entity_id
            
    return dict(sorted(dropdown_map.items(), key=lambda item: item[0].lower()))

def _extract_rooms() -> list[str]:
    registry = _read_device_registry()
    devices = registry.get("devices", {}) or {}

    rooms = set()

    for device in devices.values():
        if not isinstance(device, dict):
            continue

        area = device.get("area_label") or device.get("room")

        if area:
            rooms.add(str(area))

    return sorted(rooms)


def _group_label(group_id: str, group: dict) -> str:
    name = group.get("name") or group_id
    room = group.get("room_label") or group.get("room") or ""

    return f"{room} • {name}" if room else name


def _find_group_id_from_dropdown(hass: HomeAssistant, value: str) -> str:
    value = (value or "").strip()

    if not value or value in ("none", "unknown", "unavailable"):
        return ""

    group_map = hass.data.get(DOMAIN, {}).get("lighting_group_dropdown_map", {})

    if value in group_map:
        return group_map[value]

    return value


def _find_entity_from_member_dropdown(hass: HomeAssistant, value: str) -> str:
    value = (value or "").strip()

    if not value or value in ("none", "unknown", "unavailable"):
        return ""

    member_map = hass.data.get(DOMAIN, {}).get("lighting_group_member_map", {})

    if value in member_map:
        return member_map[value]

    return value


def _build_group_summary(hass: HomeAssistant) -> str:
    data = _read_lighting_groups()
    groups = data.get("groups", {}) or {}

    if not groups:
        return "No lighting groups yet."

    lines = []

    for idx, (group_id, group) in enumerate(groups.items(), start=1):
        if not isinstance(group, dict):
            continue

        lines.append(f"Lighting Group {idx}")
        lines.append(f"Name: {group.get('name') or group_id}")

        room = group.get("room_label") or group.get("room")
        if room:
            lines.append(f"Room: {room}")

        z2m_group_name = group.get("z2m_group_name")
        z2m_entity = group.get("z2m_entity")

        if z2m_group_name:
            lines.append(f"Zigbee Group: {z2m_group_name}")

        if z2m_entity:
            lines.append(f"Group Entity: {z2m_entity}")

        members = group.get("members", []) or []

        if members:
            lines.append("Members:")
            for entity_id in members:
                lines.append(f"- {_control_label_from_entity(hass, entity_id)}")
        else:
            lines.append("Members: none")

        lines.append("")

    return "\n".join(lines).strip() or "No lighting groups yet."


def _update_lighting_groups_sensor(hass: HomeAssistant):
    hass.states.async_set(
        "sensor.eyzee_lighting_groups",
        "Lighting Groups",
        {
            "friendly_name": "EyZEE Lighting Groups",
            "summary": _build_group_summary(hass),
        },
    )

def _entity_to_z2m_friendly_name_from_registry(entity_id: str) -> str:
    registry = _read_device_registry()
    devices = registry.get("devices", {}) or {}

    for device in devices.values():
        if not isinstance(device, dict):
            continue

        z2m_name = ((device.get("z2m") or {}).get("friendly_name") or "").strip()
        controls = device.get("controls", []) or []

        if not z2m_name or not isinstance(controls, list):
            continue

        for control in controls:
            if isinstance(control, dict) and control.get("entity_id") == entity_id:
                return z2m_name

    return _entity_to_z2m_friendly_name(entity_id)

def async_register_lighting_groups_services(hass: HomeAssistant):
    async def handle_populate_lighting_group_dropdowns(call: ServiceCall):
        group_dropdown = call.data.get(
            "group_dropdown_entity",
            DEFAULT_GROUP_DROPDOWN,
        )
        room_dropdown = call.data.get(
            "room_dropdown_entity",
            DEFAULT_ROOM_DROPDOWN,
        )
        member_dropdown = call.data.get(
            "member_dropdown_entity",
            DEFAULT_MEMBER_DROPDOWN,
        )

        data = await hass.async_add_executor_job(_read_lighting_groups)
        groups = data.get("groups", {}) or {}

        group_options = ["none"]
        group_map = {}
        used_group_labels = {}

        if isinstance(groups, dict):
            for group_id, group in groups.items():
                if not isinstance(group, dict):
                    continue

                base_label = _group_label(group_id, group)
                count = used_group_labels.get(base_label, 0) + 1
                used_group_labels[base_label] = count

                label = base_label if count == 1 else f"{base_label} ({count})"
                group_options.append(label)
                group_map[label] = group_id

        rooms = await hass.async_add_executor_job(_extract_rooms)
        rooms = [room for room in rooms if str(room).lower() != "none"]
        room_options = ["none"] + rooms

        member_map = await hass.async_add_executor_job(
            _extract_registry_controls,
            hass,
        )
        member_options = ["none"] + list(member_map.keys())

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["lighting_group_dropdown_map"] = group_map
        hass.data[DOMAIN]["lighting_group_member_map"] = member_map

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": group_dropdown,
                "options": group_options,
            },
            blocking=True,
        )

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": AURA_GROUP_DROPDOWN,
                "options": group_options,
            },
            blocking=True,
        )

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": room_dropdown,
                "options": room_options,
            },
            blocking=True,
        )

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": member_dropdown,
                "options": member_options,
            },
            blocking=True,
        )

        # When only one lighting group exists, select it
        # automatically instead of leaving the homeowner at "none".
        if len(group_options) == 2:
            await hass.services.async_call(
                "input_select",
                "select_option",
                {
                    "entity_id": group_dropdown,
                    "option": group_options[1],
                },
                blocking=True,
            )

            await hass.services.async_call(
                "input_select",
                "select_option",
                {
                    "entity_id": AURA_GROUP_DROPDOWN,
                    "option": group_options[1],
                },
                blocking=True,
            )

        _update_lighting_groups_sensor(hass)

        return True

    async def handle_create_lighting_group(call: ServiceCall):
        group_name = (call.data.get("group_name") or "").strip()

        if not group_name:
            st = hass.states.get("input_text.eyzee_lighting_group_name")
            group_name = (st.state if st else "").strip()

        if not group_name:
            raise HomeAssistantError("Lighting group name is required")

        room = (call.data.get("room") or "").strip()

        if not room:
            st = hass.states.get("input_select.eyzee_lighting_group_room")
            room = (st.state if st else "").strip()

        if room in ("none", "unknown", "unavailable"):
            room = ""

        group_id = _slugify(group_name)

        def _create():
            data = _read_lighting_groups()
            groups = data.setdefault("groups", {})

            existing = groups.get(group_id, {})
            members = (
                existing.get("members", [])
                if isinstance(existing, dict)
                else []
            )

            groups[group_id] = {
                "name": group_name,
                "name_slug": _slugify(group_name),
                "room": _slugify(room) if room else "",
                "room_label": room,
                "members": members,
            }

            _write_lighting_groups(data)

        await hass.async_add_executor_job(_create)

        await handle_populate_lighting_group_dropdowns(
            type("obj", (), {"data": {}})
        )

        hass.states.async_set(
            "sensor.eyzee_lighting_group_status",
            "✅ Lighting group saved",
            {
                "friendly_name": "EyZEE Lighting Group Status",
                "group": group_name,
                "room": room,
            },
        )

        return True

    async def handle_add_lighting_group_member(call: ServiceCall):
        group_id = call.data.get("group_id") or ""

        if not group_id:
            st = hass.states.get("input_select.eyzee_lighting_group")
            group_id = _find_group_id_from_dropdown(hass, st.state if st else "")

        entity_id = call.data.get("entity_id") or ""

        if not entity_id:
            st = hass.states.get("input_select.eyzee_lighting_group_member")
            entity_id = _find_entity_from_member_dropdown(
                hass,
                st.state if st else "",
            )

        if not group_id:
            raise HomeAssistantError("Lighting group is required")

        if not entity_id:
            raise HomeAssistantError("Group member is required")

        def _add():
            data = _read_lighting_groups()
            groups = data.setdefault("groups", {})
            group = groups.get(group_id)

            if not isinstance(group, dict):
                raise HomeAssistantError(f"Lighting group not found: {group_id}")

            members = group.setdefault("members", [])

            if entity_id not in members:
                members.append(entity_id)

            group["members"] = sorted(set(members))
            groups[group_id] = group
            _write_lighting_groups(data)

        await hass.async_add_executor_job(_add)

        await handle_populate_lighting_group_dropdowns(
            type("obj", (), {"data": {}})
        )

        # Rebuild room views so the applied lighting group
        # appears in its assigned room automatically.
        try:
            await hass.services.async_call(
                DOMAIN,
                "build_room_views",
                {},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE lighting groups: could not rebuild "
                "room views after group sync: %s",
                err,
            )

        hass.states.async_set(
            "sensor.eyzee_lighting_group_status",
            "✅ Member added",
            {
                "friendly_name": "EyZEE Lighting Group Status",
                "group": group_id,
                "member": entity_id,
            },
        )

        return True

    async def handle_remove_lighting_group_member(call: ServiceCall):
        group_id = call.data.get("group_id") or ""

        if not group_id:
            st = hass.states.get("input_select.eyzee_lighting_group")
            group_id = _find_group_id_from_dropdown(hass, st.state if st else "")

        entity_id = call.data.get("entity_id") or ""

        if not entity_id:
            st = hass.states.get("input_select.eyzee_lighting_group_member")
            entity_id = _find_entity_from_member_dropdown(
                hass,
                st.state if st else "",
            )

        if not group_id:
            raise HomeAssistantError("Lighting group is required")

        if not entity_id:
            raise HomeAssistantError("Group member is required")

        def _remove():
            data = _read_lighting_groups()
            groups = data.setdefault("groups", {})
            group = groups.get(group_id)

            if not isinstance(group, dict):
                raise HomeAssistantError(f"Lighting group not found: {group_id}")

            members = group.get("members", []) or []
            group["members"] = [m for m in members if m != entity_id]

            groups[group_id] = group
            _write_lighting_groups(data)

        await hass.async_add_executor_job(_remove)

        await handle_populate_lighting_group_dropdowns(
            type("obj", (), {"data": {}})
        )

        hass.states.async_set(
            "sensor.eyzee_lighting_group_status",
            "✅ Member removed",
            {
                "friendly_name": "EyZEE Lighting Group Status",
                "group": group_id,
                "member": entity_id,
            },
        )

        return True

    async def handle_delete_lighting_group(call: ServiceCall):
        group_id = call.data.get("group_id") or ""

        if not group_id:
            st = hass.states.get("input_select.eyzee_lighting_group")
            group_id = _find_group_id_from_dropdown(hass, st.state if st else "")

        if not group_id:
            raise HomeAssistantError("Lighting group is required")

        def _delete():
            data = _read_lighting_groups()
            groups = data.setdefault("groups", {})

            if group_id in groups:
                del groups[group_id]

            _write_lighting_groups(data)

        await hass.async_add_executor_job(_delete)

        await handle_populate_lighting_group_dropdowns(
            type("obj", (), {"data": {}})
        )

        await hass.async_add_executor_job(_delete)

        await handle_populate_lighting_group_dropdowns(
            type("obj", (), {"data": {}})
        )

        # Rebuild room views so the deleted lighting group
        # is removed from its room automatically.
        try:
            await hass.services.async_call(
                DOMAIN,
                "build_room_views",
                {},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE lighting groups: could not rebuild "
                "room views after group deletion: %s",
                err,
            )

        hass.states.async_set(
            "sensor.eyzee_lighting_group_status",
            "✅ Lighting group deleted",
            {
                "friendly_name": "EyZEE Lighting Group Status",
                "group": group_id,
            },
        )

        return True

    async def handle_save_current_colour_as_aura(
        call: ServiceCall,
    ):
        """Save the selected lighting group's current colour as Aura."""

        group_id = call.data.get("group_id") or ""

        if not group_id:
            selected_state = hass.states.get(
                AURA_GROUP_DROPDOWN
            )

            selected_label = (
                selected_state.state
                if selected_state is not None
                else ""
            )

            group_id = _find_group_id_from_dropdown(
                hass,
                selected_label,
            )

        if not group_id:
            raise HomeAssistantError(
                "Select a lighting group first."
            )

        data = await hass.async_add_executor_job(
            _read_lighting_groups
        )

        groups = data.get("groups", {}) or {}
        group = groups.get(group_id)

        if not isinstance(group, dict):
            raise HomeAssistantError(
                f"Lighting group not found: {group_id}"
            )

        group_name = str(
            group.get("name") or group_id
        ).strip()

        group_entity = str(
            group.get("z2m_entity") or ""
        ).strip()

        if not group_entity:
            raise HomeAssistantError(
                "Sync the selected lighting group with "
                "Zigbee2MQTT first."
            )

        group_state = hass.states.get(group_entity)

        if group_state is None:
            raise HomeAssistantError(
                "The selected lighting group is unavailable."
            )

        rgb_color = group_state.attributes.get(
            "rgb_color"
        )

        if (
            not isinstance(rgb_color, (list, tuple))
            or len(rgb_color) != 3
        ):
            raise HomeAssistantError(
                "Set the selected lighting group to the "
                "desired colour first."
            )

        saved_rgb = await hass.async_add_executor_job(
            save_aura_rgb,
            rgb_color,
        )

        await hass.services.async_call(
            DOMAIN,
            "build_room_views",
            {},
            blocking=True,
        )

        hass.states.async_set(
            "sensor.eyzee_lighting_group_status",
            "✅ Aura colour saved",
            {
                "friendly_name": (
                    "EyZEE Lighting Group Status"
                ),
                "group": group_name,
                "group_entity": group_entity,
                "aura_rgb": saved_rgb,
            },
        )

        return True

    async def handle_sync_z2m_lighting_group(call: ServiceCall):
        group_id = call.data.get("group_id") or ""

        if not group_id:
            st = hass.states.get("input_select.eyzee_lighting_group")
            group_id = _find_group_id_from_dropdown(hass, st.state if st else "")

        if not group_id:
            raise HomeAssistantError("Lighting group is required")

        data = await hass.async_add_executor_job(_read_lighting_groups)
        groups = data.get("groups", {}) or {}
        group = groups.get(group_id)

        if not isinstance(group, dict):
            raise HomeAssistantError(f"Lighting group not found: {group_id}")

        group_name = group.get("name") or group_id
        z2m_group_name = group.get("z2m_group_name") or _slugify(group_name)
        z2m_group_id = group.get("z2m_group_id") or 100 + abs(hash(group_id)) % 30000
        members = group.get("members", []) or []

        if not members:
            raise HomeAssistantError("Lighting group has no members")

        await mqtt.async_publish(
            hass,
            "zigbee2mqtt/bridge/request/group/add",
            json.dumps(
                {
                    "friendly_name": z2m_group_name,
                    "id": z2m_group_id,
                }
            ),
            qos=0,
            retain=False,
        )

        z2m_members = []

        for entity_id in members:
            z2m_member = await hass.async_add_executor_job(
                _entity_to_z2m_friendly_name_from_registry,
                entity_id,
            )

            if not z2m_member:
                continue

            z2m_members.append(z2m_member)

            await mqtt.async_publish(
                hass,
                "zigbee2mqtt/bridge/request/group/members/add",
                json.dumps(
                    {
                        "group": z2m_group_name,
                        "device": z2m_member,
                    }
                ),
                qos=0,
                retain=False,
            )

        def _update_yaml():
            data2 = _read_lighting_groups()
            groups2 = data2.setdefault("groups", {})
            group2 = groups2.get(group_id)

            if isinstance(group2, dict):
                group2["z2m_group_name"] = z2m_group_name
                group2["z2m_group_id"] = z2m_group_id
                group2["z2m_synced"] = True
                group2["z2m_entity"] = f"light.{z2m_group_name}"
                group2["z2m_members"] = z2m_members
                groups2[group_id] = group2
                _write_lighting_groups(data2)

        await hass.async_add_executor_job(_update_yaml)

        await handle_populate_lighting_group_dropdowns(
            type("obj", (), {"data": {}})
        )

        try:
            await hass.services.async_call(
                DOMAIN,
                "build_room_views",
                {},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE lighting groups: could not rebuild "
                "room views after group sync: %s",
                err,
            )

        hass.states.async_set(
            "sensor.eyzee_lighting_group_status",
            "✅ Zigbee2MQTT group sync requested",
            {
                "friendly_name": "EyZEE Lighting Group Status",
                "group": group_name,
                "z2m_group_name": z2m_group_name,
                "z2m_group_id": z2m_group_id,
                "members": z2m_members,
            },
        )

        return True

    async def handle_lighting_groups_startup(event):
        """Populate lighting-group choices after Home Assistant starts."""

        try:
            await handle_populate_lighting_group_dropdowns(
                type(
                    "obj",
                    (),
                    {
                        "data": {},
                    },
                )
            )

        except Exception as err:
            _LOGGER.warning(
                "EyZEE lighting groups: could not populate "
                "dropdowns after startup: %s",
                err,
            )

    hass.services.async_register(
        DOMAIN,
        "populate_lighting_group_dropdowns",
        handle_populate_lighting_group_dropdowns,
        schema=vol.Schema(
            {
                vol.Optional("group_dropdown_entity", default=DEFAULT_GROUP_DROPDOWN): cv.entity_id,
                vol.Optional("room_dropdown_entity", default=DEFAULT_ROOM_DROPDOWN): cv.entity_id,
                vol.Optional("member_dropdown_entity", default=DEFAULT_MEMBER_DROPDOWN): cv.entity_id,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "create_lighting_group",
        handle_create_lighting_group,
        schema=vol.Schema(
            {
                vol.Optional("group_name", default=""): cv.string,
                vol.Optional("room", default=""): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "add_lighting_group_member",
        handle_add_lighting_group_member,
        schema=vol.Schema(
            {
                vol.Optional("group_id", default=""): cv.string,
                vol.Optional("entity_id", default=""): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "remove_lighting_group_member",
        handle_remove_lighting_group_member,
        schema=vol.Schema(
            {
                vol.Optional("group_id", default=""): cv.string,
                vol.Optional("entity_id", default=""): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "delete_lighting_group",
        handle_delete_lighting_group,
        schema=vol.Schema(
            {
                vol.Optional("group_id", default=""): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "save_current_colour_as_aura",
        handle_save_current_colour_as_aura,
        schema=vol.Schema(
            {
                vol.Optional(
                    "group_id",
                    default="",
                ): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "sync_z2m_lighting_group",
        handle_sync_z2m_lighting_group,
        schema=vol.Schema(
            {
                vol.Optional("group_id", default=""): cv.string,
            }
        ),
    )

    hass.bus.async_listen_once(
        "homeassistant_started",
        handle_lighting_groups_startup,
    )