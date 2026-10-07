import time
import asyncio
import json
import logging
import shutil
import re
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from datetime import datetime
from pathlib import Path
from typing import Optional

from homeassistant.core import HomeAssistant, ServiceCall, Context
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.components import mqtt
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from .remove_device import async_register_remove_device_services
from .refresh_wizard_data import async_register_refresh_wizard_data_service
from .profile_matcher import enrich_discovered_device
from .populate_multiway_dropdowns import async_register_populate_multiway_dropdowns_service
from .lighting_groups import async_register_lighting_groups_services
from .zigbee_coordinator import async_register_zigbee_coordinator_services
from .smart_behaviours import (
    async_register_smart_behaviour_services,
)
from .room_views import async_register_room_view_services
from .room_locations import (
    async_register_room_location_services,
)
from .add_custom_room import async_add_custom_room
from .switch_light_binding import (
    async_setup_switch_light_binding,
    async_register_switch_light_binding_services,
)

_LOGGER = logging.getLogger(__name__)
DOMAIN = "eyzee_dashboard"
ADD_DEVICE_DASHBOARD_PATH = Path(
    "/config/eyzee/ui/setup/add_device.yaml"
)

ADD_DEVICE_SETUP_DASHBOARD_PATH = Path(
    "/config/eyzee/ui/setup/device_setup.yaml"
)

# -----------------------------
# File locations
# -----------------------------
ROOMS_YAML = Path("eyzee/state/rooms.yaml")
LIGHTING_GROUPS_YAML = Path("eyzee/state/lighting_groups.yaml")
BACKUPS_DIR = Path("eyzee/state/backups")
TEMPLATES_DIR = Path("eyzee/ui/templates")
OUT_UI_DIR = Path("eyzee/ui")
OUT_ROOMS_DIR = Path("eyzee/ui/rooms")
DASHBOARDS_YAML = Path("eyzee/dashboards.yaml")
BINDINGS_YAML = Path("eyzee/state/bindings.yaml")
DEVICE_REGISTRY_YAML = Path("eyzee/state/device_registry.yaml")
RULES_YAML = Path("eyzee/state/rules.yaml")
ACTIONS_YAML = Path("eyzee/state/actions.yaml")

# -----------------------------
# UI template filenames
# These should exist in:
# /config/eyzee/ui/templates/
# -----------------------------
TEMPLATE_ROOM = "eyzee-room.jinja"
TEMPLATE_MASTER = "eyzee-master.jinja"
TEMPLATE_SINGLE = "eyzee-single-room.jinja"

# -----------------------------
# Floors
# -----------------------------
FLOOR_NAMES = ["One", "Two", "Three", "Four", "Five"]

# -----------------------------
# Canonical room icons / groups
# -----------------------------
ROOM_META = {
    "kitchen": {"label": "Kitchen", "icon": "mdi:fridge-outline", "group": "Living"},
    "dining": {"label": "Dining", "icon": "mdi:silverware-fork-knife", "group": "Living"},
    "entrance": {"label": "Entrance", "icon": "mdi:door", "group": "Ancillary"},
    "hallway": {"label": "Hallway", "icon": "mdi:floor-plan", "group": "Ancillary"},
    "garage": {"label": "Garage", "icon": "mdi:garage", "group": "Utility"},
    "laundry": {"label": "Laundry", "icon": "mdi:washing-machine", "group": "Utility"},
    "mud_room": {"label": "Mud Room", "icon": "mdi:boot", "group": "Utility"},
    "media": {"label": "Media", "icon": "mdi:television", "group": "Media"},
    "bathroom": {"label": "Bathroom", "icon": "mdi:shower", "group": "Bathrooms"},
    "ensuite": {"label": "Ensuite", "icon": "mdi:shower-head", "group": "Ensuite"},
    "living": {"label": "Living", "icon": "mdi:sofa", "group": "Living"},
    "bedroom": {"label": "Bedroom", "icon": "mdi:bed", "group": "Bedrooms"},
    "study": {"label": "Study", "icon": "mdi:desk", "group": "Study"},
    "office": {"label": "Office", "icon": "mdi:briefcase-outline", "group": "Office"},
}

DEFAULT_OUTDOOR_ICON = "mdi:tree"
DEFAULT_OTHER_ICON = "mdi:door"


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace(" ", "_").replace("-", "_")
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_"
    return "".join(ch for ch in s if ch in allowed).strip("_") or "room"


def _label_from_slug(slug: str) -> str:
    return (slug or "room").replace("_", " ").title()


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up EyZEE Dashboard services."""
    _LOGGER.info("Starting EyZEE Dashboard setup")

    # Prevent double-registration
    hass.data.setdefault(DOMAIN, {})
    if hass.data[DOMAIN].get("_services_registered"):
        _LOGGER.debug("EyZEE Dashboard services already registered; skipping re-registration.")
        return True
    hass.data[DOMAIN]["_services_registered"] = True

    # Ensure status entity exists early
    hass.states.async_set(
        "sensor.eyzee_dashboard_status",
        "starting",
        {"updated": datetime.now().isoformat(), "last_error": None},
    )

    # -----------------------------
    # Helpers
    # -----------------------------
    def _path(rel) -> Path:
        return Path(hass.config.path(str(rel)))

    def _read_yaml_file(path: Path):
        import yaml

        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _read_actions():
        """Read the EyZEE Action Library."""
        data = _read_yaml_file(_path(ACTIONS_YAML))
        if not isinstance(data, dict):
            return {"version": 1, "actions": {}}

        data.setdefault("version", 1)
        data.setdefault("actions", {})

        return data

    def _write_actions(data):
        """Write the EyZEE Action Library."""
        _write_yaml(_path(ACTIONS_YAML), data)

    def _get_action(action_id: str):
        """Return one Action from the EyZEE Action Library."""
        data = _read_actions()
        actions = data.get("actions", {})

        if not isinstance(actions, dict):
            return None

        action = actions.get(action_id)

        if not isinstance(action, dict):
            return None

        return action

    def _get_actions():
        """Return all Actions."""
        data = _read_actions()
        return data.get("actions", {})

    def _validate_action(action: dict) -> bool:
        """Validate the basic Action structure."""

        if not isinstance(action, dict):
            return False

        if not action.get("name"):
            return False

        steps = action.get("steps")

        if not isinstance(steps, list):
            return False

        return True

    async def _run_action_step(step: dict) -> None:
        """Run one Action step."""

        step_type = str(step.get("type") or "").strip()
        entity_id = str(step.get("entity_id") or "").strip()

        if step_type not in {"turn_on", "turn_off"}:
            raise HomeAssistantError(
                f"Unsupported Action step type: {step_type}"
            )

        if not entity_id:
            raise HomeAssistantError(
                "Action step is missing entity_id"
            )

        domain = entity_id.split(".", 1)[0]

        await hass.services.async_call(
            domain,
            step_type,
            {
                "entity_id": entity_id,
            },
            blocking=True,
        )

    async def _run_action(action_id: str) -> None:
        """Run an EyZEE Action."""

        action = _get_action(action_id)

        if action is None:
            raise HomeAssistantError(
                f"Unknown Action: {action_id}"
            )

        if not _validate_action(action):
            raise HomeAssistantError(
                f"Invalid Action: {action_id}"
            )

        steps = action.get("steps", [])

        for step in steps:
            await _run_action_step(step)

    def _write_text(path: Path, content: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_yaml(path: Path, data):
        import yaml

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)

    def _backup_rooms_yaml():
        src = _path(ROOMS_YAML)
        if not src.exists():
            return None

        bdir = _path(BACKUPS_DIR)
        bdir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = bdir / f"rooms.yaml.{stamp}.bak"

        dst.write_text(
            src.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        backups = sorted(
            bdir.glob("rooms.yaml.*.bak"),
            key=lambda p: p.name,
            reverse=True,
        )

        for old_backup in backups[5:]:
            old_backup.unlink()

        return str(dst)

    def _list_backup_files_newest_first():
        bdir = _path(BACKUPS_DIR)
        if not bdir.exists():
            return []
        return sorted(
            bdir.glob("rooms.yaml.*.bak"),
            key=lambda p: p.name,
            reverse=True,
        )

    async def _set_status(ok: bool, last_error: Optional[str], extra: Optional[dict] = None):
        attrs = {
            "updated": datetime.now().isoformat(),
            "last_generated": datetime.now().isoformat() if ok else None,
            "last_error": last_error,
        }
        if extra:
            attrs.update(extra)
        hass.states.async_set("sensor.eyzee_dashboard_status", "ok" if ok else "error", attrs)

    async def _notify(title: str, message: str, notification_id: str):
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": notification_id,
            },
            blocking=False,
        )

    async def _set_multiway_status(
        state: str,
        action: str | None = None,
        master: str | None = None,
        slave: str | None = None,
        message: str | None = None,
    ):
        master_name = _friendly_name(master) if master else None
        slave_name = _friendly_name(slave) if slave and slave != "all" else slave

        hass.states.async_set(
            "sensor.eyzee_multiway_status",
            state,
            {
                "updated": datetime.now().isoformat(),
                "action": action,
                "master": master,
                "slave": slave,
                "master_name": master_name,
                "slave_name": slave_name,
                "message": message,
            },
        )

    # -----------------------------
    # Rooms model helpers
    # -----------------------------

    # ---------------------------------------------------------
    # Room Connect Devices
    # ---------------------------------------------------------

    def _build_room_ui_model(
        room_slug: str,
        rooms_data: dict,
        device_registry: dict,
        lighting_groups_data: dict,
        bindings_data: dict,
    ) -> dict:
        """Build a normalized EyZEE UI model for one room."""

        room_slug = str(room_slug or "").strip()

        # ---------------------------------------------------------
        # Room identity
        # ---------------------------------------------------------
        room_record = {}

        if isinstance(rooms_data, dict):
            rooms_container = rooms_data.get("rooms", rooms_data)

            if isinstance(rooms_container, dict):
                room_record = rooms_container.get(room_slug, {}) or {}

        room_label = (
            room_record.get("label")
            or room_record.get("name")
            or room_slug.replace("_", " ").title()
        )

        room_icon = (
            room_record.get("icon")
            or "mdi:door"
        )

        model = {
            "slug": room_slug,
            "label": room_label,
            "icon": room_icon,

            # Primary room lighting group, if one exists.
            "lighting_group": None,

            # All individual lights assigned to the room.
            "lights": [],

            # Lights assigned to the room but NOT members of
            # the primary lighting group, e.g. wardrobe light.
            "secondary_lights": [],

            # Physical wall switches / multi-gang switches.
            "switches": [],

            # Dedicated fan entities.
            "fans": [],

            # Fan/light controllers such as:
            # Light / Low / Medium / High.
            "fan_controllers": [],

            # Full useful device list for Advanced Controls.
            "advanced_devices": [],

            # Anything we don't yet have a dedicated room UI for.
            "other": [],
        }

        # ---------------------------------------------------------
        # Binding index
        #
        # Keyed by:
        #   (device_registry_key, control_index)
        #
        # This lets the room model attach logical targets to
        # physical switch controls without depending on HA names.
        # ---------------------------------------------------------
        binding_index: dict[tuple[str, int], dict] = {}

        raw_bindings = []

        if isinstance(bindings_data, dict):
            raw_bindings = bindings_data.get("bindings", []) or []

        if isinstance(raw_bindings, list):
            for binding in raw_bindings:
                if not isinstance(binding, dict):
                    continue

                if binding.get("room") != room_slug:
                    continue

                source = binding.get("source") or {}
                target = binding.get("target") or {}

                source_device = str(
                    source.get("device") or ""
                ).strip()

                source_control = source.get("control")

                if not source_device:
                    continue

                try:
                    source_control = int(source_control)
                except (TypeError, ValueError):
                    continue

                binding_index[
                    (source_device, source_control)
                ] = {
                    "type": target.get("type"),
                    "id": target.get("id"),
                    "entity_id": target.get("entity_id"),
                }

        # ---------------------------------------------------------
        # Primary lighting group
        #
        # lighting_groups.yaml structure:
        #
        # version: 1
        # groups:
        #   spare_light_group:
        #     room: spare_room
        #     z2m_entity: light.spare_light_group
        #     members: [...]
        # ---------------------------------------------------------
        groups = {}

        if isinstance(lighting_groups_data, dict):
            groups = lighting_groups_data.get("groups", {}) or {}

        if isinstance(groups, dict):
            for group_slug, group in groups.items():
                if not isinstance(group, dict):
                    continue

                if group.get("room") != room_slug:
                    continue

                entity_id = group.get("z2m_entity")

                if not entity_id:
                    continue

                model["lighting_group"] = {
                    "slug": group_slug,
                    "name": (
                        group.get("name")
                        or group_slug.replace("_", " ").title()
                    ),
                    "entity_id": entity_id,
                    "members": list(group.get("members") or []),
                    "z2m_group_name": group.get("z2m_group_name"),
                    "z2m_group_id": group.get("z2m_group_id"),
                }

                # V1: one primary lighting group per room.
                break

        # ---------------------------------------------------------
        # Physical devices assigned to this room
        # ---------------------------------------------------------
        if not isinstance(device_registry, dict):
            device_registry = {}

        for registry_key, device in device_registry.items():
            if not isinstance(device, dict):
                continue

            if device.get("room") != room_slug:
                continue

            device_type = str(
                device.get("device_type") or ""
            ).strip().lower()

            ha_data = device.get("ha") or {}
            controls = device.get("controls") or []

            primary_entity = ha_data.get("primary_entity")

            base_device = {
                "registry_key": registry_key,
                "device_type": device_type,

                "name": (
                    device.get("display_label")
                    or device.get("name_label")
                    or device.get("device_name")
                    or registry_key
                ),

                "device_name": device.get("device_name"),

                "primary_entity": primary_entity,

                # Full useful HA entity list.
                # Used later by Advanced Controls.
                "entities": list(
                    ha_data.get("entities") or []
                ),

                # Normalized device controls.
                # Used by room dashboards.
                "controls": list(
                    controls
                    if isinstance(controls, list)
                    else []
                ),

                # Integration / protocol information.
                "source": dict(
                    device.get("source") or {}
                ),

                "profile_id": (
                    (device.get("meta") or {}).get(
                        "profile_id"
                    )
                ),

                "product_name": (
                    (device.get("meta") or {}).get(
                        "product_name"
                    )
                ),
            }

            # -----------------------------------------------------
            # Advanced Controls
            #
            # Every room device is retained here before simplified
            # room-screen classification occurs.
            # -----------------------------------------------------
            model["advanced_devices"].append(
                dict(base_device)
            )

            # -----------------------------------------------------
            # Individual lights
            # -----------------------------------------------------
            is_light = (
                primary_entity
                and str(primary_entity).startswith("light.")
            )

            if is_light:
                light_record = dict(base_device)

                light_record["entity_id"] = primary_entity

                # Is this light a member of the room's primary
                # lighting group?
                light_record["in_primary_group"] = False

                if model["lighting_group"]:
                    light_record["in_primary_group"] = (
                        primary_entity
                        in model["lighting_group"]["members"]
                    )

                model["lights"].append(light_record)

                # Lights outside the primary room lighting group
                # remain available as separate everyday controls.
                if not light_record["in_primary_group"]:
                    model["secondary_lights"].append(
                        light_record
                    )

                continue

            # -----------------------------------------------------
            # Fan / light controllers
            #
            # Typical controls:
            # - light
            # - fan_low
            # - fan_medium
            # - fan_high
            #
            # Detect from entity roles rather than integration so
            # the same room model can support Z2M, ZHA and later
            # other integrations.
            # -----------------------------------------------------
            control_entity_ids = []

            if isinstance(controls, list):
                for control in controls:
                    if not isinstance(control, dict):
                        continue

                    entity_id = control.get("entity_id")

                    if entity_id:
                        control_entity_ids.append(
                            str(entity_id).lower()
                        )

            fan_role_hits = {
                "light": any(
                    entity_id.endswith("_light")
                    or entity_id.endswith("_lights")
                    for entity_id in control_entity_ids
                ),
                "low": any(
                    "fan_low" in entity_id
                    for entity_id in control_entity_ids
                ),
                "medium": any(
                    "fan_medium" in entity_id
                    for entity_id in control_entity_ids
                ),
                "high": any(
                    "fan_high" in entity_id
                    for entity_id in control_entity_ids
                ),
            }

            is_fan_controller = (
                device_type == "switch"
                and fan_role_hits["low"]
                and fan_role_hits["medium"]
                and fan_role_hits["high"]
            )

            if is_fan_controller:
                fan_controller = dict(base_device)

                fan_controller["controls"] = []

                for entity_id in control_entity_ids:

                    if (
                        entity_id.endswith("_light")
                        or entity_id.endswith("_lights")
                    ):
                        role = "light"
                        name = "Light"
                        order = 1

                    elif "fan_low" in entity_id:
                        role = "low"
                        name = "Low"
                        order = 2

                    elif "fan_medium" in entity_id:
                        role = "medium"
                        name = "Medium"
                        order = 3

                    elif "fan_high" in entity_id:
                        role = "high"
                        name = "High"
                        order = 4

                    else:
                        continue

                    fan_controller["controls"].append(
                        {
                            "role": role,
                            "name": name,
                            "entity_id": entity_id,
                            "order": order,
                        }
                    )

                fan_controller["controls"].sort(
                    key=lambda item: item.get(
                        "order",
                        999,
                    )
                )

                model["fan_controllers"].append(
                    fan_controller
                )

                continue

            # -----------------------------------------------------
            # Multi-gang / physical switches
            #
            # Use EyZEE controls[], NOT the raw HA entity list.
            # -----------------------------------------------------
            if device_type == "switch":
                switch_record = dict(base_device)
                switch_record["controls"] = []

                if isinstance(controls, list):
                    for control in controls:
                        if not isinstance(control, dict):
                            continue

                        entity_id = control.get("entity_id")

                        if not entity_id:
                            continue

                        control_index = control.get("index")

                        try:
                            control_index_int = int(control_index)
                        except (TypeError, ValueError):
                            control_index_int = None

                        binding = None

                        if control_index_int is not None:
                            binding = binding_index.get(
                                (
                                    registry_key,
                                    control_index_int,
                                )
                            )

                        switch_record["controls"].append(
                            {
                                "index": control_index,
                                "endpoint": control.get("endpoint"),
                                "entity_id": entity_id,

                                "name": (
                                    control.get("name")
                                    or f"Switch {control_index or ''}"
                                ),

                                "name_slug": control.get("name_slug"),

                                "source": (
                                    control.get("source")
                                    or (device.get("source") or {}).get(
                                        "integration"
                                    )
                                    or "generic"
                                ),

                                "binding": binding,
                            }
                        )

                model["switches"].append(switch_record)
                continue

            # -----------------------------------------------------
            # Fans
            #
            # Keep this deliberately simple for now. We can expand
            # fan classification when we have a real fan record.
            # -----------------------------------------------------
            is_fan = (
                device_type == "fan"
                or (
                    primary_entity
                    and str(primary_entity).startswith("fan.")
                )
            )

            if is_fan:
                fan_record = dict(base_device)
                fan_record["entity_id"] = primary_entity
                fan_record["controls"] = controls
                model["fans"].append(fan_record)
                continue

            # -----------------------------------------------------
            # Everything else
            #
            # Keeping unknown room devices is important. The future
            # Home Master dashboard may want them even if the small
            # room controller does not render them yet.
            # -----------------------------------------------------
            other_record = dict(base_device)
            other_record["controls"] = controls

            model["other"].append(other_record)

        # ---------------------------------------------------------
        # Stable ordering
        # ---------------------------------------------------------
        model["lights"].sort(
            key=lambda item: str(item.get("name") or "").lower()
        )

        model["switches"].sort(
            key=lambda item: str(item.get("name") or "").lower()
        )

        model["fans"].sort(
            key=lambda item: str(item.get("name") or "").lower()
        )

        model["other"].sort(
            key=lambda item: str(item.get("name") or "").lower()
        )

        return model

    # ---------------------------------------------------------
    # Helpers to build rooms
    # ---------------------------------------------------------
    def _ensure_min_rooms_model(model):
        if not isinstance(model, dict):
            model = {}

        project = model.get("project")
        if isinstance(project, dict):
            project_name = project.get("name") or "My Home"
        else:
            project_name = project or "My Home"

        rooms = model.get("rooms") or {}
        devices = model.get("devices") or {}

        return {
            "version": int(model.get("version") or 1),
            "project": project_name,
            "devices": devices if isinstance(devices, dict) else {},
            "rooms": rooms if isinstance(rooms, dict) else {},
        }

    def _normalise_room(slug: str, room: dict | None):
        room = room if isinstance(room, dict) else {}
        meta = ROOM_META.get(slug, {})

        label = room.get("label") or meta.get("label") or _label_from_slug(slug)
        icon = room.get("icon") or meta.get("icon") or DEFAULT_OTHER_ICON
        floor = room.get("floor") or "One"
        group = room.get("group") or meta.get("group") or "Other"
        features = room.get("features") or ["lights"]

        if not isinstance(features, list):
            features = ["lights"]

        return {
            "label": label,
            "icon": icon,
            "floor": floor,
            "group": group,
            "features": features,
        }

    def _extract_room_options(model: dict) -> list[str]:
        rooms_map = (model or {}).get("rooms") or {}
        if not isinstance(rooms_map, dict):
            return ["none"]
        slugs = sorted({str(slug).strip() for slug in rooms_map.keys() if slug})
        return ["none"] + [s for s in slugs if s]

    def _make_room(slug: str, label: str | None = None, floor: str = "One", group: str | None = None, icon: str | None = None, features: list[str] | None = None):
        base_slug = _slugify(slug)
        meta = ROOM_META.get(base_slug, {})
        return {
            "label": label or meta.get("label") or _label_from_slug(base_slug),
            "icon": icon or meta.get("icon") or DEFAULT_OTHER_ICON,
            "floor": floor or "One",
            "group": group or meta.get("group") or "Other",
            "features": features if isinstance(features, list) and features else ["lights"],
        }

    # -----------------------------
    # Room Building Function
    # -----------------------------

    def _unique_slug(existing: dict, base: str) -> str:
        base = _slugify(base)
        if base not in existing:
            return base
        idx = 2
        while f"{base}_{idx}" in existing:
            idx += 1
        return f"{base}_{idx}"

    def _build_house_model(payload: dict):
        project_name = payload.get("project_name") or "My Home"
        floors_count = int(payload.get("floors") or 1)
        floors_count = max(1, min(floors_count, len(FLOOR_NAMES)))

        counts = payload.get("counts") or {}
        if not isinstance(counts, dict):
            counts = {}

        features_default = payload.get("features_default") or ["lights"]
        if not isinstance(features_default, list) or not features_default:
            features_default = ["lights"]

        features_overrides = payload.get("features_overrides") or {}
        if not isinstance(features_overrides, dict):
            features_overrides = {}

        rooms: dict[str, dict] = {}

        def add_room(slug: str, label: str | None = None, floor: str = "One", group: str | None = None, icon: str | None = None):
            room_slug = _unique_slug(rooms, slug)
            features = features_overrides.get(room_slug) or features_overrides.get(slug) or features_default
            rooms[room_slug] = _make_room(room_slug, label=label, floor=floor, group=group, icon=icon, features=features)
            return room_slug

    # -----------------------------
    # Rooms Count Handling Options
    # -----------------------------
        kitchen_count = int(counts.get("kitchen") or 0)
        for i in range(max(0, kitchen_count)):
            add_room(
                "kitchen" if i == 0 else f"kitchen_{i + 1}",
                "Kitchen" if i == 0 else f"Kitchen {i + 1}",
                group="Living",
                icon="mdi:countertop",
            )

        dining_count = int(counts.get("dining") or 0)
        for i in range(max(0, dining_count)):
            add_room(
                "dining" if i == 0 else f"dining_{i + 1}",
                "Dining" if i == 0 else f"Dining {i + 1}",
                group="Living",
                icon="mdi:silverware-fork-knife",
            )

        entrance_count = int(counts.get("entrance") or 0)
        for i in range(max(0, entrance_count)):
            add_room(
                "entrance" if i == 0 else f"entrance_{i + 1}",
                "Entrance" if i == 0 else f"Entrance {i + 1}",
                group="Ancillary",
                icon="mdi:door-open",
            )

        hallway_count = int(counts.get("hallway") or 0)
        for i in range(max(0, hallway_count)):
            add_room(
                "hallway" if i == 0 else f"hallway_{i + 1}",
                "Hallway" if i == 0 else f"Hallway {i + 1}",
                group="Ancillary",
                icon="mdi:door",
            )

        living_count = int(counts.get("living") or 0)
        for i in range(max(0, living_count)):
            add_room("living" if i == 0 else f"living_{i + 1}", "Living" if i == 0 else f"Living {i + 1}", group="Living", icon="mdi:sofa")

        bedroom_count = int(counts.get("bedrooms") or 0)
        for i in range(max(0, bedroom_count)):
            floor = "Two" if floors_count >= 2 and i >= max(1, bedroom_count // 2) else "One"
            label = "Bedroom" if bedroom_count == 1 else f"Bedroom {i + 1}"
            add_room("bedroom" if bedroom_count == 1 else f"bedroom_{i + 1}", label, floor=floor, group="Bedrooms", icon="mdi:bed")

        bathroom_count = int(counts.get("bathrooms") or 0)
        for i in range(max(0, bathroom_count)):
            label = "Bathroom" if bathroom_count == 1 else f"Bathroom {i + 1}"
            add_room("bathroom" if bathroom_count == 1 else f"bathroom_{i + 1}", label, group="Bathrooms", icon="mdi:shower")

        ensuite_count = int(counts.get("ensuite") or 0)
        for i in range(max(0, ensuite_count)):
            label = "Ensuite" if ensuite_count == 1 else f"Ensuite {i + 1}"
            add_room("ensuite" if ensuite_count == 1 else f"ensuite_{i + 1}", label, group="Ensuite", icon="mdi:shower-head")

        media_count = int(counts.get("media") or 0)
        for i in range(max(0, media_count)):
            label = "Media" if media_count == 1 else f"Media {i + 1}"
            add_room("media" if media_count == 1 else f"media_{i + 1}", label, group="Media", icon="mdi:television")

        study_count = int(counts.get("study") or 0)
        for i in range(max(0, study_count)):
            label = "Study" if study_count == 1 else f"Study {i + 1}"
            add_room("study" if study_count == 1 else f"study_{i + 1}", label, group="Study", icon="mdi:desk")

        laundry_count = int(counts.get("laundry") or 0)
        for i in range(max(0, laundry_count)):
            label = "Laundry" if laundry_count == 1 else f"Laundry {i + 1}"
            add_room("laundry" if laundry_count == 1 else f"laundry_{i + 1}", label, group="Utility", icon="mdi:washing-machine")

        garage_count = int(counts.get("garage") or 0)
        for i in range(max(0, garage_count)):
            label = "Garage" if garage_count == 1 else f"Garage {i + 1}"
            add_room("garage" if garage_count == 1 else f"garage_{i + 1}", label, group="Utility", icon="mdi:garage")

        mud_room_count = int(counts.get("mud_room") or 0)
        for i in range(max(0, mud_room_count)):
            label = "Mud Room" if mud_room_count == 1 else f"Mud Room {i + 1}"
            add_room("mud_room" if mud_room_count == 1 else f"mud_room_{i + 1}", label, group="Utility", icon="mdi:boot")

        outdoor = payload.get("outdoor") or []
        if isinstance(outdoor, str):
            outdoor = [x.strip() for x in outdoor.split(",") if x.strip()]
        if isinstance(outdoor, list):
            for item in outdoor:
                label = str(item).strip()
                if not label:
                    continue
                add_room(_slugify(label), label, group="Outdoor", icon=DEFAULT_OUTDOOR_ICON)

        custom_rooms = payload.get("custom_rooms") or []
        if isinstance(custom_rooms, list):
            for item in custom_rooms:
                if isinstance(item, dict):
                    label = str(item.get("label") or item.get("name") or "").strip()
                    if not label:
                        continue
                    add_room(
                        item.get("slug") or _slugify(label),
                        label=label,
                        floor=item.get("floor") or "One",
                        group=item.get("group") or "Other",
                        icon=item.get("icon") or DEFAULT_OTHER_ICON,
                    )
                else:
                    label = str(item).strip()
                    if label:
                        add_room(_slugify(label), label=label)

        return {
            "version": 1,
            "project": project_name,
            "devices": {},
            "rooms": rooms,
        }

    # -----------------------------
    # Dashboard rendering helpers
    # -----------------------------
    def _fallback_master_yaml(model: dict) -> str:
        rooms = model.get("rooms") or {}
        lines = [
            "title: EyZEE",
            "views:",
            "  - title: Home",
            "    path: home",
            "    icon: mdi:home-assistant",
            "    cards:",
            "      - type: markdown",
            "        content: |",
            f"          # EyZEE Core",
            f"          Project: **{model.get('project') or 'My Home'}**",
            "",
            "      - type: grid",
            "        columns: 2",
            "        square: false",
            "        cards:",
            "          - type: button",
            "            name: House Builder",
            "            icon: mdi:home-edit",
            "            tap_action:",
            "              action: navigate",
            "              navigation_path: /eyzee-house-builder",
            "          - type: button",
            "            name: Add Device",
            "            icon: mdi:plus-circle",
            "            tap_action:",
            "              action: navigate",
            "              navigation_path: /eyzee-add-device-new",
            "          - type: button",
            "            name: Automate",
            "            icon: mdi:robot",
            "            tap_action:",
            "              action: navigate",
            "              navigation_path: /eyzee-automate",
            "          - type: button",
            "            name: Zigbee Setup",
            "            icon: mdi:zigbee",
            "            tap_action:",
            "              action: navigate",
            "              navigation_path: /zigbee-setup",
            "",
            "      - type: markdown",
            "        content: |",
            "          ## Rooms",
        ]
        if rooms:
            for slug, room in rooms.items():
                label = room.get("label") or _label_from_slug(slug)
                lines.append(f"          - {label}")
        else:
            lines.append("          No rooms have been created yet.")
        return "\n".join(lines) + "\n"

    def _fallback_room_yaml(model: dict) -> str:
        """Build the EyZEE Rooms dashboard with one view per room."""

        rooms = model.get("rooms") or {}

        lines = [
            "title: EyZEE Rooms",
            "views:",

            # -----------------------------------------------------
            # Main room index
            # -----------------------------------------------------
            "  - title: Rooms",
            "    path: rooms",
            "    icon: mdi:floor-plan",
            "    cards:",
            "      - type: markdown",
            "        content: |",
            "          # EyZEE Rooms",
        ]

        if not rooms:
            lines += [
                "          No rooms have been created yet.",
            ]

        else:
            lines += [
                "      - type: grid",
                "        columns: 2",
                "        square: false",
                "        cards:",
            ]

            for slug, room in rooms.items():
                label = (
                    room.get("label")
                    or _label_from_slug(slug)
                )
                icon = (
                    room.get("icon")
                    or DEFAULT_OTHER_ICON
                )

                view_path = slug.replace("_", "-")

                lines += [
                    "          - type: button",
                    f"            name: {label}",
                    f"            icon: {icon}",
                    "            tap_action:",
                    "              action: navigate",
                    (
                        "              navigation_path: "
                        f"/eyzee-rooms/{view_path}"
                    ),
                ]

            # -----------------------------------------------------
            # Individual room views
            # -----------------------------------------------------
            for slug, room in rooms.items():
                room_ui = (
                    (model.get("room_ui") or {}).get(slug)
                    or {}
                )

                label = (
                    room.get("label")
                    or _label_from_slug(slug)
                )
                
                icon = (
                    room.get("icon")
                    or DEFAULT_OTHER_ICON
                )

                view_path = slug.replace("_", "-")
                
                fan_controllers = (
                    room_ui.get("fan_controllers") or []
                )

                lines += [
                    "",
                    f"  - title: {label}",
                    f"    path: {view_path}",
                    f"    icon: {icon}",
                    "    cards:",
                    "      - type: markdown",
                    "        content: |",
                    f"          # {label}",
                ]

                # -------------------------------------------------
                # Fan / Light Controllers
                # -------------------------------------------------
                for fan_controller in fan_controllers:
                    controller_name = (
                        fan_controller.get("name")
                        or "Fan Controller"
                    )

                    controls = (
                        fan_controller.get("controls")
                        or []
                    )

                    lines += [
                        "",
                        "      - type: markdown",
                        "        content: |",
                        f"          ## {controller_name}",
                        "",
                        "      - type: grid",
                        "        columns: 4",
                        "        square: false",
                        "        cards:",
                    ]

                    for control in controls:
                        entity_id = control.get("entity_id")

                        control_name = (
                            control.get("name")
                            or "Control"
                        )

                        if not entity_id:
                            continue

                        lines += [
                            "          - type: button",
                            f"            entity: {entity_id}",
                            f"            name: {control_name}",
                            "            show_state: true",
                            "            tap_action:",
                            "              action: toggle",
                            "            hold_action:",
                            "              action: more-info",
                        ]

                # -------------------------------------------------
                # Navigation
                # -------------------------------------------------
                lines += [
                    "",
                    "      - type: button",
                    "        name: Back to Rooms",
                    "        icon: mdi:arrow-left",
                    "        tap_action:",
                    "          action: navigate",
                    "          navigation_path: /eyzee-rooms/rooms",
                ]

    def _fallback_single_room_yaml(slug: str, room: dict) -> str:
        label = room.get("label") or _label_from_slug(slug)
        icon = room.get("icon") or DEFAULT_OTHER_ICON
        return f"""title: {label}
views:
  - title: {label}
    path: {slug}
    icon: {icon}
    cards:
      - type: markdown
        content: |
          # {label}

          Devices assigned to this room will appear here.

      - type: button
        name: Back to Rooms
        icon: mdi:arrow-left
        tap_action:
          action: navigate
          navigation_path: /eyzee-rooms
"""

    def _render_template_file(template_path: Path, context: dict) -> str:
        from jinja2 import Environment, FileSystemLoader

        env = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        tmpl = env.get_template(template_path.name)
        return tmpl.render(**context)

    def _generate_dashboards_sync():
        model = _read_yaml_file(_path(ROOMS_YAML)) or {}
        model = _ensure_min_rooms_model(model)

        # Normalise all rooms to a predictable model
        clean_rooms: dict[str, dict] = {}
        for slug, room in (model.get("rooms") or {}).items():
            clean_slug = _slugify(str(slug))
            clean_rooms[clean_slug] = _normalise_room(clean_slug, room)
        model["rooms"] = clean_rooms

        # -----------------------------------------------------
        # Build normalized UI model for every room
        #
        # This becomes the common backend for:
        # - Room dashboards
        # - Advanced Controls
        # - Future Home Master dashboard
        # -----------------------------------------------------

        device_registry_data = _read_device_registry()

        lighting_groups_data = (
            _read_yaml_file(_path(LIGHTING_GROUPS_YAML)) or {}
        )

        bindings_data = (
            _read_yaml_file(_path(BINDINGS_YAML)) or {}
        )

        room_ui_models: dict[str, dict] = {}

        for room_slug in model.get("rooms", {}):
            room_ui_models[room_slug] = _build_room_ui_model(
                room_slug,
                model,
                device_registry_data.get("devices", {}),
                lighting_groups_data,
                bindings_data,
            )

        # Make normalized room data available to renderers.
        model["room_ui"] = room_ui_models

        _path(OUT_UI_DIR).mkdir(parents=True, exist_ok=True)

        rooms_dir = _path(OUT_ROOMS_DIR)
        rooms_dir.mkdir(parents=True, exist_ok=True)

        # Clear old generated room dashboards before regenerating.
        # rooms.yaml is the source of truth; /ui/rooms is generated output only.
        for old_file in rooms_dir.glob("*.yaml"):
            try:
                old_file.unlink()
            except Exception as e:
                _LOGGER.warning("EyZEE: failed to remove old room dashboard %s: %s", old_file, e)

        ctx = {
            "project": model.get("project") or "My Home",
            "rooms": model.get("rooms") or {},
            "devices": model.get("devices") or {},
            "model": model,
            "generated_at": datetime.now().isoformat(),
        }

        master_t = _path(TEMPLATES_DIR / TEMPLATE_MASTER)
        room_t = _path(TEMPLATES_DIR / TEMPLATE_ROOM)

        if master_t.exists():
            master_yaml = _render_template_file(master_t, ctx)
        else:
            master_yaml = _fallback_master_yaml(model)

        if room_t.exists():
            rooms_yaml = _render_template_file(room_t, ctx)
        else:
            rooms_yaml = _fallback_room_yaml(model)

        _write_text(
            _path(OUT_UI_DIR / "eyzee-master.yaml"),
            master_yaml,
        )

        return {
            "project": model.get("project"),
            "rooms_count": len(model.get("rooms", {})),
            "master": str(
                _path(OUT_UI_DIR / "eyzee-master.yaml")
            ),
            "rooms": str(
                _path(OUT_UI_DIR / "eyzee-room.yaml")
            ),
            "rooms_dir": str(
                _path(OUT_ROOMS_DIR)
            ),
        }

    # -----------------------------
    # Service: Generate dashboards
    # -----------------------------
    async def handle_generate(call: ServiceCall):
        try:
            result = await hass.async_add_executor_job(_generate_dashboards_sync)

            current_model = await hass.async_add_executor_job(
                _read_yaml_file,
                _path(ROOMS_YAML),
            )

            current_rooms = []

            for slug, room in (
                (current_model or {}).get("rooms", {})
            ).items():
                current_rooms.append(
                    {
                        "slug": slug,
                        "label": (
                            room.get("label")
                            or _label_from_slug(slug)
                        ),
                        "icon": (
                            room.get("icon")
                            or DEFAULT_OTHER_ICON
                        ),
                        "floor": room.get("floor") or "One",
                        "group": room.get("group") or "Other",
                    }
                )

            hass.states.async_set(
                "sensor.eyzee_current_rooms",
                len(current_rooms),
                {
                    "friendly_name": "EyZEE Current Rooms",
                    "rooms": current_rooms,
                    "room_count": len(current_rooms),
                },
            )

            try:
                await handle_populate_room_dropdown(
                    type(
                        "obj",
                        (),
                        {
                            "data": {
                                "dropdown_entity": (
                                    "input_select.eyzee_room_to_remove"
                                )
                            }
                        },
                    )()
                )
            except Exception as err:
                _LOGGER.warning(
                    "EyZEE: Could not populate room removal dropdown: %s",
                    err,
                )

            # Reload Lovelace if available. Do not fail generation if reload is unavailable.
            try:
                await hass.services.async_call("lovelace", "reload", {}, blocking=False)
            except Exception as reload_err:
                _LOGGER.warning("EyZEE: Lovelace reload failed/non-fatal: %s", reload_err)

            await _set_status(True, None, result)
            await _notify(
                "EyZEE Dashboards Generated",
                f"✅ Dashboards generated.\n\nRooms: {result.get('rooms_count', 0)}",
                "eyzee_dashboards_generated",
            )
            return True
        except Exception as e:
            _LOGGER.exception("EyZEE dashboard generation failed: %s", e)
            await _set_status(False, f"{type(e).__name__}: {e}")
            await _notify(
                "EyZEE Dashboard Error",
                f"❌ Dashboard generation failed:\n\n{type(e).__name__}: {e}",
                "eyzee_dashboard_error",
            )
            raise

    # -----------------------------
    # Service: Build house
    # -----------------------------
    async def handle_build_house(call: ServiceCall):

        hass.states.async_set(
            "sensor.eyzee_room_update_status",
            "updating",
            {
                "friendly_name": "EyZEE Room Update Status",
                "message": "Updating your rooms…",
                "updated": datetime.now().isoformat(),
            },
        )
        try:
            payload = dict(call.data or {})

            def _write_model():
                backup = _backup_rooms_yaml()

                existing_model = (
                    _read_yaml_file(_path(ROOMS_YAML))
                    or {}
                )
                existing_rooms = (
                    existing_model.get("rooms", {})
                    or {}
                )

                # Preserve all existing indoor/custom rooms when
                # only the outdoor-area toggles are being updated.
                counts = payload.get("counts") or {}

                has_room_additions = any(
                    int(value or 0) > 0
                    for value in counts.values()
                )

                if not has_room_additions:
                    requested_model = _build_house_model(payload)
                    requested_rooms = (
                        requested_model.get("rooms", {})
                        or {}
                    )

                    known_outdoor_areas = {
                        "pool",
                        "patio",
                        "yard",
                    }

                    # Remove only Pool, Patio and Yard.
                    for slug in known_outdoor_areas:
                        existing_rooms.pop(slug, None)

                    # Add back the currently selected outdoor areas.
                    for slug, room in requested_rooms.items():
                        if slug in known_outdoor_areas:
                            existing_rooms[slug] = room

                    existing_model.setdefault("version", 1)
                    existing_model["project"] = (
                        payload.get("project_name")
                        or existing_model.get("project")
                        or "My Home"
                    )
                    existing_model.setdefault("devices", {})
                    existing_model["rooms"] = existing_rooms

                    _write_yaml(
                        _path(ROOMS_YAML),
                        existing_model,
                    )

                    return backup, existing_model

                preserved_custom_rooms = {}

                for slug, room in existing_rooms.items():
                    if not isinstance(room, dict):
                        continue

                    group = room.get("group")
                    label = room.get("label") or slug.replace("_", " ").title()

                    is_custom = (
                        group == "Other"
                        or room.get("custom") is True
                        or slug not in ROOM_META
                    )

                    if is_custom:
                        preserved_custom_rooms[slug] = room

                model = _build_house_model(payload)

                model_rooms = model.setdefault("rooms", {})

                for slug, room in preserved_custom_rooms.items():
                    if slug not in model_rooms:
                        model_rooms[slug] = room

                _write_yaml(_path(ROOMS_YAML), model)
                return backup, model

            backup, model = await hass.async_add_executor_job(_write_model)

            # Keep room dropdown current
            try:
                await handle_populate_room_dropdown(
                    type("obj", (), {"data": {"dropdown_entity": "input_select.eyzee_wizard_room"}})
                )
            except Exception:
                pass

            await handle_generate(call)

            success_updated = datetime.now().isoformat()

            hass.states.async_set(
                "sensor.eyzee_room_update_status",
                "success",
                {
                    "friendly_name": "EyZEE Room Update Status",
                    "message": "Your rooms have been saved and updated.",
                    "updated": success_updated,
                },
            )

            # Hide the success message after 10 seconds.
            def _clear_room_update_status():
                current = hass.states.get(
                    "sensor.eyzee_room_update_status"
                )

                if (
                    current is not None
                    and current.state == "success"
                    and current.attributes.get("updated")
                    == success_updated
                ):
                    hass.states.async_set(
                        "sensor.eyzee_room_update_status",
                        "idle",
                        {
                            "friendly_name": (
                                "EyZEE Room Update Status"
                            ),
                            "message": "",
                            "updated": datetime.now().isoformat(),
                        },
                    )

            hass.loop.call_later(
                10,
                _clear_room_update_status,
            )

            await _notify(
                "EyZEE House Built",
                (
                    f"✅ House setup created.\n\n"
                    f"Project: {model.get('project')}\n"
                    f"Rooms: {len(model.get('rooms', {}))}\n"
                    f"Backup: {backup or 'No previous rooms file'}"
                ),
                "eyzee_house_built",
            )
            return True
        except Exception as e:
            hass.states.async_set(
                "sensor.eyzee_room_update_status",
                "error",
                {
                    "friendly_name": "EyZEE Room Update Status",
                    "message": f"{type(e).__name__}: {e}",
                    "updated": datetime.now().isoformat(),
                },
            )
            
            _LOGGER.exception("EyZEE build_house failed: %s", e)
            await _set_status(False, f"{type(e).__name__}: {e}")
            await _notify(
                "EyZEE House Builder Error",
                f"❌ House Builder failed:\n\n{type(e).__name__}: {e}",
                "eyzee_house_builder_error",
            )
            raise

    # -----------------------------
    # Service: Add custom room
    # -----------------------------
    async def handle_add_custom_room(call: ServiceCall):
        await async_add_custom_room(hass, call)

    hass.services.async_register(
        DOMAIN,
        "add_custom_room",
        handle_add_custom_room,
        schema=vol.Schema(
            {
                vol.Optional(
                    "dropdown_entity"
                ): cv.entity_id,
            }
        ),
    )

    # -----------------------------
    # Service: Remove room
    # -----------------------------
    async def handle_remove_room(call: ServiceCall):
        """Remove the selected room from rooms.yaml."""

        selected = hass.states.get(
            "input_select.eyzee_room_to_remove"
        )

        if selected is None:
            raise ValueError(
                "Missing helper: input_select.eyzee_room_to_remove"
            )

        room_slug = selected.state.strip()

        if not room_slug or room_slug.lower() in {
            "none",
            "unknown",
            "unavailable",
        }:
            raise ValueError("No room selected.")

        def _remove():
            model = _read_yaml_file(_path(ROOMS_YAML)) or {}
            rooms = model.get("rooms", {}) or {}

            if room_slug not in rooms:
                raise ValueError(
                    f"Room '{room_slug}' does not exist."
                )

            room_label = (
                rooms[room_slug].get("label")
                or _label_from_slug(room_slug)
            )

            backup = _backup_rooms_yaml()
            del rooms[room_slug]

            model["rooms"] = rooms
            _write_yaml(_path(ROOMS_YAML), model)

            return backup, room_label

        backup, room_label = await hass.async_add_executor_job(
            _remove
        )

        await handle_generate(call)

        await _notify(
            "EyZEE Room Removed",
            (
                f"✅ {room_label} removed from this home.\n\n"
                f"Backup: {backup or 'No previous rooms file'}"
            ),
            "eyzee_room_removed",
        )

        return True

    # -----------------------------
    # Service: Clear rooms / Start over
    # -----------------------------
    async def handle_clear_rooms(call: ServiceCall):
        confirm = str(call.data.get("confirm") or "").strip()

        if confirm != "DELETE":
            raise HomeAssistantError("Confirmation required: type DELETE")

        def _clear():
            backup = _backup_rooms_yaml()
            data = {
                "version": 1,
                "project": "My Home",
                "devices": {},
                "rooms": {},
            }
            _write_yaml(_path(ROOMS_YAML), data)
            return backup

        backup = await hass.async_add_executor_job(_clear)

        try:
            await handle_populate_room_dropdown(
                type("obj", (), {"data": {"dropdown_entity": "input_select.eyzee_wizard_room"}})
            )
        except Exception:
            pass

        await handle_generate(call)

        await _notify(
            "EyZEE Rooms Cleared",
            f"✅ Rooms cleared. You can now rebuild the house setup.\n\nBackup: {backup or 'No previous rooms file'}",
            "eyzee_rooms_cleared",
        )
        return True

    # -----------------------------
    # Service: Restore latest rooms backup
    # -----------------------------
    async def handle_restore_rooms_backup(call: ServiceCall):
        def _restore():
            backups = _list_backup_files_newest_first()
            if not backups:
                raise HomeAssistantError("No room backups found")

            latest = backups[0]
            current_backup = _backup_rooms_yaml()
            shutil.copyfile(str(latest), str(_path(ROOMS_YAML)))
            return str(latest), current_backup

        latest, current_backup = await hass.async_add_executor_job(_restore)

        try:
            await handle_populate_room_dropdown(
                type("obj", (), {"data": {"dropdown_entity": "input_select.eyzee_wizard_room"}})
            )
        except Exception:
            pass

        await handle_generate(call)

        await _notify(
            "EyZEE Rooms Restored",
            (
                f"✅ Rooms restored from latest backup.\n\n"
                f"Restored: {latest}\n"
                f"Current file backed up first: {current_backup or 'No current rooms file'}"
            ),
            "eyzee_rooms_restored",
        )
        return True

    # -----------------------------
    # Switch → Light bindings
    # -----------------------------
    try:
        await async_setup_switch_light_binding(hass)
        async_register_switch_light_binding_services(hass)
    except Exception as e:
        _LOGGER.exception("EyZEE switch→light setup failed: %s", e)

    # -----------------------------
    # Virtual Multi-way Binding
    # -----------------------------
    bindings_lock = asyncio.Lock()

    def _read_bindings():
        data = _read_yaml_file(_path(BINDINGS_YAML)) or {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", 1)
        data.setdefault("bindings", [])
        if not isinstance(data["bindings"], list):
            data["bindings"] = []
        return data

    def _write_bindings(data):
        _write_yaml(_path(BINDINGS_YAML), data)

    def _normalize_entity_id(e: str) -> str:
        value = (e or "").strip()

        # Backward compatibility for old dropdown format:
        # "Office Lights Right | switch.office_lights_right"
        if "|" in value:
            value = value.split("|", 1)[1].strip()

        # New friendly-name-only dropdown support:
        # "Office Lights Right" -> "switch.office_lights_right"
        dropdown_map = hass.data.get(DOMAIN, {}).get("multiway_dropdown_map", {})
        if value in dropdown_map:
            return dropdown_map[value]

        return value

    def _friendly_name(entity_id: str) -> str:
        if not entity_id or entity_id in ("none", "unknown", "unavailable", "all"):
            return entity_id or ""

        st = hass.states.get(entity_id)
        if st:
            return st.attributes.get("friendly_name") or entity_id

        return entity_id

    hass.data[DOMAIN].setdefault("multiway", {})
    hass.data[DOMAIN]["multiway"].setdefault("bindings", [])
    hass.data[DOMAIN]["multiway"].setdefault("unsubs", [])
    hass.data[DOMAIN]["multiway"].setdefault("last_ctx_by_entity", {})

    def _desired_from_state(state_str: str) -> Optional[bool]:
        if state_str == "on":
            return True
        if state_str == "off":
            return False
        return None

    def _is_our_own_change(event) -> bool:
        ent = event.data.get("entity_id")
        ctx = event.context
        last = hass.data[DOMAIN]["multiway"]["last_ctx_by_entity"].get(ent)
        return ctx is not None and last is not None and ctx.id == last

    async def _set_entity_state(entity_id: str, desired_on: bool, parent_ctx: Context | None = None):
        """Turn switch/light on/off and record context id for loop prevention."""
        if entity_id.startswith("switch."):
            svc_domain = "switch"
        elif entity_id.startswith("light."):
            svc_domain = "light"
        else:
            raise ValueError(f"Unsupported entity domain for binding: {entity_id}")

        svc = "turn_on" if desired_on else "turn_off"
        ctx = Context(parent_id=getattr(parent_ctx, "id", None))

        await hass.services.async_call(
            svc_domain,
            svc,
            {"entity_id": entity_id},
            blocking=False,
            context=ctx,
        )

        hass.data[DOMAIN]["multiway"]["last_ctx_by_entity"][entity_id] = ctx.id

    async def _install_binding_listeners():
        """(Re)install listeners for all bindings."""
        last_change: dict[str, float] = {}
        group_busy_until: dict[str, float] = {}
        GROUP_SETTLE_SECONDS = 3.0

        for unsub in hass.data[DOMAIN]["multiway"]["unsubs"]:
            try:
                unsub()
            except Exception:
                pass

        hass.data[DOMAIN]["multiway"]["unsubs"] = []

        bindings = hass.data[DOMAIN]["multiway"]["bindings"]

        master_to_slaves: dict[str, list[str]] = {}

        for b in bindings:
            master = b["master"]
            slaves = b.get("slaves", [])
            master_to_slaves[master] = list(slaves)

        async def _on_state_change(event):
            if _is_our_own_change(event):
                return

            ent = event.data.get("entity_id")
            if not ent:
                return

            now = time.monotonic()

            if ent in last_change and now - last_change[ent] < 0.5:
                _LOGGER.debug("EyZEE debounce ignored %s", ent)
                return

            last_change[ent] = now

            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")

            if not new_state:
                return

            desired = _desired_from_state(new_state.state)
            if desired is None:
                return

            if old_state and old_state.state == new_state.state:
                return

            group_members = None

            for master, slaves in master_to_slaves.items():
                members = [master] + list(slaves)
                if ent in members:
                    group_members = members
                    break

            if not group_members:
                return

            group_key = "|".join(sorted(group_members))
            now = time.monotonic()

            if now < group_busy_until.get(group_key, 0):
                _LOGGER.debug("EyZEE multiway ignored echo event from %s", ent)
                return

            group_busy_until[group_key] = now + GROUP_SETTLE_SECONDS

            for target in group_members:
                if target == ent:
                    continue

                try:
                    await _set_entity_state(target, desired, parent_ctx=event.context)
                except Exception as e:
                    _LOGGER.warning(
                        "EyZEE multiway: failed to sync %s from %s: %s",
                        target,
                        ent,
                        e,
                    )

        entities = set()
        for m, ss in master_to_slaves.items():
            entities.add(m)
            entities.update(ss)

        if entities:
            unsub = async_track_state_change_event(hass, list(entities), _on_state_change)
            hass.data[DOMAIN]["multiway"]["unsubs"].append(unsub)

    async def _load_bindings_on_start():
        data = await hass.async_add_executor_job(_read_bindings)
        bindings: list[dict] = []

        for b in data.get("bindings", []):
            if not isinstance(b, dict):
                continue

            master = _normalize_entity_id(b.get("master"))
            slaves = b.get("slaves") or []

            if not master or not isinstance(slaves, list):
                continue

            slaves = [_normalize_entity_id(s) for s in slaves if _normalize_entity_id(s)]
            bindings.append({"master": master, "slaves": slaves})

        hass.data[DOMAIN]["multiway"]["bindings"] = bindings
        await _install_binding_listeners()

    async def handle_bind_virtual_multiway(call: ServiceCall):
        confirm = call.data.get("confirm")

        master = _normalize_entity_id(call.data.get("master") or "")
        slave = _normalize_entity_id(call.data.get("slave") or "")

        if not master:
            st = hass.states.get("input_select.eyzee_multiway_main")
            master = _normalize_entity_id(st.state if st else "")

        if not slave:
            st = hass.states.get("input_select.eyzee_multiway_linked")
            slave = _normalize_entity_id(st.state if st else "")

        if confirm is not True:
            raise ValueError("Confirmation required: set confirm: true")

        if not master or not slave or master in ("none", "unknown", "unavailable") or slave in ("none", "unknown", "unavailable"):
            raise ValueError("master and slave are required")

        if master == slave:
            raise ValueError("master and slave cannot be the same entity")

        async with bindings_lock:
            data = await hass.async_add_executor_job(_read_bindings)

            new_members = {master, slave}
            remaining_bindings = []
            merged_members = set(new_members)

            # Find any existing group containing either selected switch.
            for b in data["bindings"]:
                if not isinstance(b, dict):
                    continue

                existing_master = _normalize_entity_id(b.get("master") or "")
                existing_slaves = [
                    _normalize_entity_id(s)
                    for s in (b.get("slaves") or [])
                    if _normalize_entity_id(s)
                ]

                existing_members = {existing_master, *existing_slaves}

                if existing_members & new_members:
                    # Merge this existing group into the new combined group.
                    merged_members.update(existing_members)
                else:
                    remaining_bindings.append(
                        {
                            "master": existing_master,
                            "slaves": sorted(
                                s for s in existing_slaves
                                if s and s != existing_master
                            ),
                        }
                    )

            # Keep chosen master as group master.
            merged_slaves = sorted(
                entity for entity in merged_members
                if entity and entity != master
            )

            remaining_bindings.append(
                {
                    "master": master,
                    "slaves": merged_slaves,
                }
            )

            data["bindings"] = remaining_bindings

            await hass.async_add_executor_job(_write_bindings, data)

            hass.data[DOMAIN]["multiway"]["bindings"] = [
                {"master": b.get("master"), "slaves": list(b.get("slaves") or [])}
                for b in data["bindings"]
                if isinstance(b, dict) and b.get("master")
            ]

            await _install_binding_listeners()
        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_multiway_dropdowns",
                {},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.warning(
                "EyZEE: failed to refresh multiway dropdowns after link: %s",
                e,
            )

        await _notify(
            "EyZEE Virtual Multi-way Linked",
            f"✅ Link Group Updated\n\nMain Switch: {_friendly_name(master)}\nLinked Switch: {_friendly_name(slave)}\n\nMode: Group ON/OFF sync",
            "eyzee_multiway_linked",
        )

        await _set_multiway_status(
            "✅ Link Group Updated",
            action="linked",
            master=master,
            slave=slave,
            message="Successfully added the switch to the linked group.",
        )

        return True

    async def handle_unbind_virtual_multiway(call: ServiceCall):
        master = _normalize_entity_id(call.data.get("master") or "")
        slave = _normalize_entity_id(call.data.get("slave") or "")
        confirm = call.data.get("confirm")

        if not master:
            st = hass.states.get("input_select.eyzee_multiway_main")
            master = _normalize_entity_id(st.state if st else "")

        if not slave:
            st = hass.states.get("input_select.eyzee_multiway_linked")
            slave = _normalize_entity_id(st.state if st else "")

        if confirm is not True:
            raise ValueError("Confirmation required: set confirm: true")

        if not master or master in ("none", "unknown", "unavailable"):
            raise ValueError("master is required")

        async with bindings_lock:
            data = await hass.async_add_executor_job(_read_bindings)

            new_bindings = []
            for b in data["bindings"]:
                if not isinstance(b, dict):
                    continue

                if b.get("master") != master:
                    new_bindings.append(b)
                    continue

                if slave and slave not in ("none", "unknown", "unavailable"):
                    slaves = [s for s in (b.get("slaves") or []) if s != slave]
                    if slaves:
                        new_bindings.append({"master": master, "slaves": slaves})

            data["bindings"] = new_bindings
            await hass.async_add_executor_job(_write_bindings, data)

            hass.data[DOMAIN]["multiway"]["bindings"] = [
                {"master": b.get("master"), "slaves": list(b.get("slaves") or [])}
                for b in data["bindings"]
                if isinstance(b, dict) and b.get("master")
            ]

            await _install_binding_listeners()
        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_multiway_dropdowns",
                {},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.warning(
                "EyZEE: failed to refresh multiway dropdowns after link: %s",
                e,
            )

        await _notify(
            "EyZEE Virtual Multi-way Unlinked",
            f"✅ Unlinked binding\n\nMain Switch: {_friendly_name(master)}\nLinked Switch: {_friendly_name(slave) if slave else '(all slaves removed)'}",
            "eyzee_multiway_unlinked",
        )

        await _set_multiway_status(
            "✅ Link Removed",
            action="unlinked",
            master=master,
            slave=slave or "all",
            message="Successfully removed the link.",
        )

        return True

    hass.async_create_task(_load_bindings_on_start())

    # -----------------------------
    # Service: Virtual Multiway End
    # -----------------------------
    # -----------------------------
    # Service: Populate Room dropdown
    # -----------------------------
    async def handle_populate_room_dropdown(call: ServiceCall) -> None:
        dropdown_entity = call.data.get("dropdown_entity", "input_select.eyzee_wizard_room")

        def _load_room_options():
            model = _read_yaml_file(_path(ROOMS_YAML)) or {}
            model = _ensure_min_rooms_model(model)
            return _extract_room_options(model)

        options = await hass.async_add_executor_job(_load_room_options)
        await hass.services.async_call(
            "input_select",
            "set_options",
            {"entity_id": dropdown_entity, "options": options},
            blocking=True,
        )

    # -----------------------------
    # Service: Populate Z2M dropdown PART 2
    # -----------------------------

    async def _get_live_z2m_devices(
        base_topic: str = "zigbee2mqtt",
    ) -> list[dict]:
        """Return the current Zigbee2MQTT bridge device list."""

        base_topic = (
            base_topic or "zigbee2mqtt"
        ).strip().strip("/")

        topic_devices = f"{base_topic}/bridge/devices"
        topic_request = f"{base_topic}/bridge/request/devices"

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
                topic_devices,
                _on_msg,
                qos=0,
            )

            await mqtt.async_publish(
                hass,
                topic_request,
                "{}",
                qos=0,
                retain=False,
            )

            payload = await asyncio.wait_for(
                fut,
                timeout=3.0,
            )

            devices = json.loads(payload) if payload else []

            if isinstance(devices, list):
                return [
                    device
                    for device in devices
                    if isinstance(device, dict)
                ]

            return []

        finally:
            if unsub:
                try:
                    unsub()
                except Exception:
                    pass

    # -----------------------------
    # Service: Populate Z2M dropdown PART 1
    # -----------------------------

    async def handle_populate_z2m_dropdown(call: ServiceCall) -> None:
        dropdown_entity = call.data.get("dropdown_entity", "input_select.eyzee_z2m_device_friendly")
        base_topic = (call.data.get("base_topic", "zigbee2mqtt") or "zigbee2mqtt").strip().strip("/")

        topic_devices = f"{base_topic}/bridge/devices"
        topic_request = f"{base_topic}/bridge/request/devices"

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()

        async def _on_msg(msg) -> None:
            p = getattr(msg, "payload", "")
            payload = p.decode("utf-8", errors="ignore") if isinstance(p, (bytes, bytearray)) else str(p)
            if not fut.done():
                fut.set_result(payload)

        unsub = None
        try:
            unsub = await mqtt.async_subscribe(hass, topic_devices, _on_msg, qos=0)
            await mqtt.async_publish(hass, topic_request, "{}", qos=0, retain=False)

            payload = await asyncio.wait_for(fut, timeout=3.0)
            devices = json.loads(payload) if payload else []

            names: list[str] = []
            if isinstance(devices, list):
                for d in devices:
                    if not isinstance(d, dict):
                        continue
                    fn = (d.get("friendly_name") or "").strip()
                    typ = (d.get("type") or "").strip()
                    disabled = bool(d.get("disabled", False))

                    if not fn or typ == "Coordinator" or disabled:
                        continue
                    names.append(fn)

            options = ["none"] + sorted(set(names))
            await hass.services.async_call(
                "input_select",
                "set_options",
                {"entity_id": dropdown_entity, "options": options},
                blocking=True,
            )
        finally:
            if unsub:
                try:
                    unsub()
                except Exception:
                    pass

    # -----------------------------
    # Device Registry helpers
    # -----------------------------
    def _read_device_registry():
        data = _read_yaml_file(_path(DEVICE_REGISTRY_YAML)) or {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("version", 1)
        data.setdefault("devices", {})
        if not isinstance(data["devices"], dict):
            data["devices"] = {}
        return data

    def _update_device_inventory():
        """Publish the registered EyZEE devices for the homeowner UI."""

        registry = _read_device_registry()
        devices = registry.get("devices", {}) or {}

        rooms_data = _read_yaml_file(_path(ROOMS_YAML)) or {}
        rooms = rooms_data.get("rooms", {}) or {}

        inventory = []

        for device_key, device in devices.items():
            if not isinstance(device, dict):
                continue

            room_key = str(device.get("room") or "").strip()
            room_data = rooms.get(room_key, {}) or {}

            if not isinstance(room_data, dict):
                room_data = {}

            z2m = device.get("z2m", {}) or {}
            if not isinstance(z2m, dict):
                z2m = {}

            controls = device.get("controls", []) or []
            if not isinstance(controls, list):
                controls = []

            inventory.append(
                {
                    "key": device_key,
                    "name": (
                        device.get("display_label")
                        or device.get("name_label")
                        or device_key
                    ),
                    "room": (
                        room_data.get("label")
                        or device.get("area_label")
                        or room_key.replace("_", " ").title()
                    ),
                    "room_key": room_key,
                    "floor": room_data.get("floor") or "",
                    "group": room_data.get("group") or "",
                    "type": (
                        device.get("type_label")
                        or device.get("device_type")
                        or "Device"
                    ),
                    "manufacturer": z2m.get("manufacturer") or "",
                    "model": z2m.get("model") or "",
                    "control_count": len(controls),
                }
            )

        inventory.sort(
            key=lambda item: (
                str(item.get("floor") or "").lower(),
                str(item.get("room") or "").lower(),
                str(item.get("name") or "").lower(),
            )
        )

        hass.states.async_set(
            "sensor.eyzee_device_inventory",
            len(inventory),
            {
                "devices": inventory,
                "device_count": len(inventory),
                "updated": datetime.now().isoformat(),
            },
        )

    _update_device_inventory()

    def _slugify(value: str) -> str:
        value = (value or "").strip().lower()
        value = re.sub(r"[^a-z0-9]+", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        return value or "unnamed"

    def _is_device_registered(device_id: str | None) -> bool:
        """Return True if a Home Assistant device ID is already in the EyZEE registry."""
        if not device_id:
            return False

        data = _read_device_registry()
        devices = data.get("devices", {}) or {}

        if not isinstance(devices, dict):
            return False

        for device in devices.values():
            if not isinstance(device, dict):
                continue

            ha_data = device.get("ha", {}) or {}

            if not isinstance(ha_data, dict):
                continue

            if ha_data.get("device_id") == device_id:
                return True

        return False

    def _find_existing_registry_id_for_entities(entity_ids: list[str]) -> str | None:
        if not entity_ids:
            return None

        wanted = set(entity_ids)

        data = _read_device_registry()
        devices = data.get("devices", {}) or {}

        if not isinstance(devices, dict):
            return None

        for registry_id, device in devices.items():
            if not isinstance(device, dict):
                continue

            ha_entities = device.get("ha", {}).get("entities", []) or []
            controls = device.get("controls", []) or []

            existing_entities = set()

            if isinstance(ha_entities, list):
                existing_entities.update(e for e in ha_entities if e)

            if isinstance(controls, list):
                for control in controls:
                    if isinstance(control, dict) and control.get("entity_id"):
                        existing_entities.add(control.get("entity_id"))

            if wanted & existing_entities:
                return registry_id

        return None

    def _detect_control_index(entity_id: str) -> int | None:
        """
        Detects control number from common HA/Zigbee entity patterns.

        Supports:
        switch.xxx_l1
        switch.xxx_l2
        switch.xxx_state_l1
        switch.xxx_1
        light.xxx_l1
        """

        entity_id = entity_id.lower()

        patterns = [
            r"_l(\d+)$",
            r"_state_l(\d+)$",
            r"_switch_l(\d+)$",
            r"_channel_(\d+)$",
            r"_(\d+)$",
        ]

        for pattern in patterns:
            match = re.search(pattern, entity_id)
            if match:
                return int(match.group(1))

        return None


    def _discover_controls_from_entities(
        entity_ids: list[str],
        source: str = "generic",
    ) -> list[dict]:
        """
        Creates normalized EyZEE control records from HA entities.

        This is intentionally platform-neutral so it can later support:
        - zigbee2mqtt
        - zha
        - tuya_wifi
        - matter
        - thread
        - generic Home Assistant entities
        """

        controls = []

        for entity_id in entity_ids or []:
            if not isinstance(entity_id, str):
                continue

            domain = entity_id.split(".", 1)[0] if "." in entity_id else ""

            if domain not in ["switch", "light", "fan"]:
                continue

            index = _detect_control_index(entity_id)

            if index is None:
                # Single-control device fallback
                index = 1

            endpoint = f"l{index}"

            controls.append(
                {
                    "index": index,
                    "endpoint": endpoint,
                    "source": source,
                    "raw_key": f"state_l{index}",
                    "entity_id": entity_id,
                    "name": f"L{index}",
                    "name_slug": f"l{index}",
                }
            )

        # Remove duplicate entity IDs
        seen = set()
        deduped = []

        for control in controls:
            entity_id = control.get("entity_id")
            if entity_id in seen:
                continue
            seen.add(entity_id)
            deduped.append(control)

        deduped.sort(key=lambda item: item.get("index", 999))

        return deduped

    def _write_device_registry(data):
        _write_yaml(_path(DEVICE_REGISTRY_YAML), data)

    def _upsert_registry_device(
        registry_id: str,
        room_slug: str,
        device_type_slug: str,
        device_name_slug: str,
        z2m_friendly_name: str | None,
        ha_primary_entity: str | None = None,
        ha_entities: list[str] | None = None,
        z2m_ieee: str | None = None,
        z2m_manufacturer: str | None = None,
        z2m_model: str | None = None,
        ha_device_id: str | None = None,
    ):

        now = datetime.now().astimezone().isoformat()

        room_meta = ROOM_META.get(room_slug, {})
        area_label = room_meta.get("label") or room_slug.replace("_", " ").title()

        type_label = device_type_slug.replace("_", " ").title()
        name_label = device_name_slug.replace("_", " ").title() if device_name_slug else "Main"
        display_label = f"{area_label} • {type_label} • {name_label}"

        data = _read_device_registry()
        devices = data.setdefault("devices", {})

        existing = devices.get(registry_id) if isinstance(devices.get(registry_id), dict) else None
        created = (existing.get("meta", {}).get("created") if existing else None) or now

        existing_ha = (existing.get("ha") if existing else {}) or {}

        device_id = (
            ha_device_id
            if ha_device_id is not None
            else existing_ha.get("device_id")
        )

        primary = ha_primary_entity if ha_primary_entity is not None else existing_ha.get("primary_entity")
        entities = ha_entities if ha_entities is not None else existing_ha.get("entities", [])

        if not isinstance(entities, list):
            entities = []
        if entities == [] and primary:
            entities = [primary]

        existing_controls = []
        if existing:
            existing_controls = existing.get("controls", []) or []

        controls = existing_controls

        if not controls and entities:
            controls = _discover_controls_from_entities(
                entities,
                source="generic",
            )

        devices[registry_id] = {
            "room": room_slug,
            "area_label": area_label,
            "device_type": device_type_slug,
            "type_label": type_label,
            "device_name": device_name_slug or "main",
            "name_label": name_label,
            "display_label": display_label,
            "capabilities": (existing.get("capabilities") if existing else []) or [],
            "z2m": {
                "friendly_name": z2m_friendly_name,
                "ieee": z2m_ieee,
                "manufacturer": z2m_manufacturer,
                "model": z2m_model,
            },
            "ha": {
                "device_id": device_id,
                "primary_entity": primary,
                "entities": entities,
                "last_seen": existing_ha.get("last_seen"),
                "managed_by": existing_ha.get("managed_by") or "eyzee",
            },
            "meta": {
                "notes": (existing.get("meta", {}).get("notes") if existing else ""),
                "tags": (existing.get("meta", {}).get("tags") if existing else []) or [],
                "created": created,
                "updated": now,
            },
            "controls": controls,
        }

        _write_device_registry(data)
        return devices[registry_id]

    # -----------------------------
    # Dashboard: Sue-friendly device onboarding
    # -----------------------------
    async def _write_add_device_dashboard(
        discovered_devices: list[dict],
    ) -> None:
        """
        Generate the Sue-friendly EyZEE device onboarding dashboard.

        User journey:

        Pair Device
            ↓
        Find New Devices
            ↓
        Locate Device
            ↓
        Set Up Device
            ↓
        Finished

        Technical identifiers are stored only inside dashboard actions.
        They are never displayed to the user.
        """

        # EyZEE navigation destinations. These currently point to the
        # installed menu-style test dashboard. When that dashboard is
        # promoted to production, only these two paths need to change.
        eyzee_home_path = "/eyzee-main-menu/home"
        manage_devices_path = "/eyzee-main-menu/devices"
        add_devices_help_url = (
            "https://eyzee.au/eyzee-home/support/add-devices/"
        )

        def _standard_navigation(back_path: str) -> list[dict]:
            """Return the standard Back, Home, Help navigation and footer."""

            def _navigation_tile(
                name: str,
                icon: str,
                tap_action: dict,
            ) -> dict:
                return {
                    "type": "tile",
                    "entity": "input_boolean.eyzee_show_welcome",
                    "name": name,
                    "icon": icon,
                    "hide_state": True,
                    "vertical": False,
                    "color": "#D6AD60",
                    "tap_action": tap_action,
                    "icon_tap_action": dict(tap_action),
                }

            back_tap_action = {
                "action": "navigate",
                "navigation_path": back_path,
            }

            return [
                {
                    "type": "grid",
                    "columns": 3,
                    "square": False,
                    "cards": [
                        _navigation_tile(
                            "Back",
                            "mdi:arrow-left",
                            back_tap_action,
                        ),
                        _navigation_tile(
                            "Home",
                            "mdi:home-heart",
                            {
                                "action": "navigate",
                                "navigation_path": eyzee_home_path,
                            },
                        ),
                        _navigation_tile(
                            "Help",
                            "mdi:help-circle-outline",
                            {
                                "action": "url",
                                "url_path": add_devices_help_url,
                            },
                        ),
                    ],
                },
                {
                    "type": "heading",
                    "heading": "EyZEE®  •  Making Smart Easy™",
                    "heading_style": "subtitle",
                },
            ]

        def _is_infrastructure_device(device: dict) -> bool:
            """Exclude the Z2M bridge and virtual groups from physical-device setup."""

            manufacturer = str(
                device.get("manufacturer") or ""
            ).strip().lower()

            model = str(
                device.get("model") or ""
            ).strip().lower()

            return (
                manufacturer == "zigbee2mqtt"
                and model in ("bridge", "group")
            )

        unregistered_devices = [
            device
            for device in discovered_devices
            if device.get("registered") is False
            and not _is_infrastructure_device(device)
        ]

        recognised_devices = [
            device
            for device in unregistered_devices
            if device.get("profile_match") is True
        ]

        # All valid unregistered devices should be available for setup.
        # A profile match improves the EyZEE setup experience, but an
        # unrecognised device must not disappear from Locate & Set Up.
        
        setup_devices = unregistered_devices

        unrecognised_count = (
            len(unregistered_devices)
            - len(recognised_devices)
        )

        main_cards: list[dict] = [
            {
                "type": "heading",
                "heading": "Add a Zigbee Device",
                "heading_style": "title",
                "icon": "mdi:plus-circle",
            },
            {
                "type": "grid",
                "columns": 2,
                "square": False,
                "cards": [
                    {
                        "type": "button",
                        "name": "Start Pairing",
                        "icon": "mdi:zigbee",
                        "show_state": False,
                        "tap_action": {
                            "action": "perform-action",
                            "perform_action": (
                                "eyzee_dashboard.start_z2m_pairing"
                            ),
                        },
                    },
                    {
                        "type": "button",
                        "name": "Stop Pairing",
                        "icon": "mdi:stop-circle-outline",
                        "show_state": False,
                        "tap_action": {
                            "action": "perform-action",
                            "perform_action": (
                                "eyzee_dashboard.stop_z2m_pairing"
                            ),
                        },
                    },
                ],
            },
            {
                "type": "markdown",
                "content": (
                    "{% set sensor = states.sensor.eyzee_add_device_status %}\n"
                    "{% set count = sensor.attributes.get('devices_found', 0) %}\n"
                    "{% set devices = sensor.attributes.get('found_devices', []) %}\n"
                    "\n"
                    "**{{ sensor.state }}**\n"
                    "\n"
                    "{% if count | int > 0 %}\n"
                    "**Devices found — {{ count }}**\n"
                    "\n"
                    "{% for device in devices[:5] %}\n"
                    "✓ {{ device }}  \n"
                    "{% endfor %}\n"
                    "{% endif %}"
                ),
            },
        ]

        setup_views: list[dict] = []
        setup_device_cards: list[dict] = []

        main_cards.append(
            {
                "type": "conditional",
                "conditions": [{
                    "condition": "numeric_state",
                    "entity": "sensor.eyzee_setup_device_count",
                    "above": 0,
                }],
                "card": {
                    "type": "tile",
                    "entity": "input_boolean.eyzee_show_welcome",
                    "name": "Locate & Set Up Devices",
                    "icon": "mdi:map-marker-check-outline",
                    "hide_state": True,
                    "vertical": False,
                    "grid_options": {
                        "columns": 12,
                        "rows": 1,
                    },
                    "tap_action": {
                        "action": "navigate",
                        "navigation_path": (
                            "/eyzee-device-setup/setup-devices"
                        ),
                    },
                },
            }
        )
        main_cards.append(
            {
                "type": "conditional",
                "conditions": [{
                    "condition": "state",
                    "entity": "sensor.eyzee_setup_device_count",
                    "state": "0",
                }],
                "card": {
                    "type": "markdown",
                    "content": (
                        "## No new devices ready yet\n\n"
                        "Put your device into pairing mode. "
                        "Locate & Set Up will appear when it is ready."
                    ),
                },
            }
        )

        if setup_devices:
            device_count = len(setup_devices)

            # Number matching products when several identical devices
            # have been paired at the same time.
            product_totals: dict[str, int] = {}

            for device in setup_devices:
                profile_match = (
                    device.get("profile_match") is True
                )

                product_name = (
                    device.get("product_name")
                    if profile_match
                    else (
                        device.get("model")
                        or device.get("name")
                        or "New Zigbee Device"
                    )
                )

                product_totals[product_name] = (
                    product_totals.get(product_name, 0) + 1
                )

            product_seen: dict[str, int] = {}

            for device in setup_devices:
                device_id = str(
                    device.get("device_id") or ""
                ).strip()

                if not device_id:
                    _LOGGER.warning(
                        "EyZEE dashboard skipped a discovered device "
                        "because it had no Home Assistant device_id: %s",
                        device,
                    )
                    continue

                profile_match = device.get("profile_match") is True

                product_name = (
                    device.get("product_name")
                    if profile_match
                    else (
                        device.get("model")
                        or device.get("name")
                        or "New Zigbee Device"
                    )
                )

                product_seen[product_name] = (
                    product_seen.get(product_name, 0) + 1
                )

                display_name = product_name

                if product_totals.get(product_name, 0) > 1:
                    display_name = (
                        f"{product_name} "
                        f"{product_seen[product_name]}"
                    )

                setup_path = (
                    f"setup-{device_id[:12]}"
                )

                # Build Sue-friendly control naming fields from the
                # actual Home Assistant entities exposed by this device.
                #
                # This mirrors the control filtering used when the
                # device is saved into the EyZEE registry.
                excluded_control_terms = (
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
                    "switch_type",
                    "decouplar_mode",
                )

                usable_control_entities = []

                for entity_id in device.get("entities", []) or []:
                    if not isinstance(entity_id, str):
                        continue

                    lowered = entity_id.lower()

                    if any(
                        term in lowered
                        for term in excluded_control_terms
                    ):
                        continue

                    if entity_id.startswith(
                        (
                            "light.",
                            "switch.",
                            "fan.",
                            "cover.",
                            "lock.",
                        )
                    ):
                        usable_control_entities.append(entity_id)

                # Keep the order deterministic.
                usable_control_entities = sorted(
                    set(usable_control_entities)
                )

                control_name_entities = []

                # Single-control devices use Device Name and therefore
                # do not need a separate Control 1 naming field.
                if len(usable_control_entities) > 1:
                    for index, entity_id in enumerate(
                        usable_control_entities[:6],
                        start=1,
                    ):
                        control_name_entities.append(
                            {
                                "entity": (
                                    f"input_text."
                                    f"eyzee_wizard_control_{index}_name"
                                ),
                                "name": f"Control {index}",
                                "icon": "mdi:light-switch",
                            }
                        )

                device_card_content = "\n".join(
                    [
                        f"## {display_name}",
                        "",
                        "### New Device",
                        "",
                        "First use **Locate Device** to confirm which "
                        "physical device this is.",
                        "",
                        "When you have found it, select "
                        "**Set Up Device**.",
                    ]
                )

                setup_device_cards.append(
                    {
                        "type": "entities",
                        "show_header_toggle": False,
                        "entities": [
                            {
                                "type": "section",
                                "label": f"✓ {display_name}",
                            },
                            {
                                "type": "button",
                                "name": "Locate",
                                "icon": "mdi:map-search",
                                "action_name": "Locate",
                                "tap_action": {
                                    "action": "perform-action",
                                    "perform_action": (
                                        "eyzee_dashboard."
                                        "identify_device"
                                    ),
                                    "data": {
                                        "device_id": device_id,
                                        "duration": 2,
                                    },
                                },
                            },
                            {
                                "type": "button",
                                "name": "Set Up",
                                "icon": "mdi:cog-outline",
                                "action_name": "Set Up",
                                "tap_action": {
                                    "action": "navigate",
                                    "navigation_path": (
                                        "/eyzee-device-setup/"
                                        f"{setup_path}"
                                    ),
                                },
                            },
                        ],
                    }
                )

                setup_views.append(
                    {
                        "title": "Set Up Device",
                        "path": setup_path,
                        "icon": "mdi:cog-outline",
                        "subview": True,
                        "type": "sections",
                        "max_columns": 1,
                        "sections":  [
                            {
                                "type": "grid",
                                "cards": [
                                    {
                                        "type": "heading",
                                        "heading": "Set Up Device",
                                        "heading_style": "title",
                                        "icon": "mdi:cog-outline",
                                    },
                                    {
                                        "type": "markdown",
                                        "content": (
                                            f"## {display_name}\n\n"
                                            "Tell EyZEE where this device "
                                            "is and what you would like to "
                                            "call it."
                                        ),
                                    },
                                    {
                                        "type": "entities",
                                        "entities": [
                                            {
                                                "type": "button",
                                                "name": "Update Room List",
                                                "icon": "mdi:refresh",
                                                "action_name": "Update",
                                                "tap_action": {
                                                    "action": (
                                                        "perform-action"
                                                    ),
                                                    "perform_action": (
                                                        "eyzee_dashboard."
                                                        "populate_room_dropdown"
                                                    ),
                                                    "data": {
                                                        "dropdown_entity": (
                                                            "input_select."
                                                            "eyzee_wizard_room"
                                                        ),
                                                    },
                                                },
                                            },
                                            {
                                                "entity": (
                                                    "input_select."
                                                    "eyzee_wizard_room"
                                                ),
                                                "name": "Room",
                                                "icon": "mdi:door",
                                            },
                                            {
                                                "entity": (
                                                    "input_text."
                                                    "eyzee_wizard_device_"
                                                    "friendly_name"
                                                ),
                                                "name": "Device Name",
                                                "icon": "mdi:form-textbox",
                                            },
                                            *control_name_entities,
                                        ],
                                    },
                                    {
                                        "type": "entities",
                                        "title": "Need to Add a Room?",
                                        "show_header_toggle": False,
                                        "entities": [
                                            {
                                                "entity": (
                                                    "input_text."
                                                    "eyzee_custom_room_name"
                                                ),
                                                "name": "Add a New Room Name",
                                                "icon": (
                                                    "mdi:home-plus-outline"
                                                ),
                                            },
                                            {
                                                "type": "button",
                                                "name": (
                                                    "Add and Select Room"
                                                ),
                                                "icon": (
                                                    "mdi:plus-circle-outline"
                                                ),
                                                "action_name": "Add Room",
                                                "tap_action": {
                                                    "action": (
                                                        "perform-action"
                                                    ),
                                                    "perform_action": (
                                                        "eyzee_dashboard."
                                                        "add_custom_room"
                                                    ),
                                                },
                                            },
                                        ],
                                    },
                                    {
                                        "type": "markdown",
                                        "content": (
                                            "Choose a name that makes sense "
                                            "in everyday use, such as "
                                            "**Office Switch**, "
                                            "**Kitchen Downlight** or "
                                            "**Bedroom Fan**."
                                        ),
                                    },
                                    {
                                        "type": "button",
                                        "name": "Save Device",
                                        "icon": "mdi:check-circle",
                                        "show_state": False,
                                        "grid_options": {
                                            "columns": 12,
                                            "rows": 2,
                                        },
                                        "tap_action": {
                                            "action": "perform-action",
                                            "perform_action": (
                                                "eyzee_dashboard."
                                                "setup_device"
                                            ),
                                            "data": {
                                                "device_id": device_id,
                                            },
                                        },
                                    },
                                    {
                                        "type": "conditional",
                                        "conditions": [
                                            {
                                                "condition": "state",
                                                "entity": (
                                                    "sensor."
                                                    "eyzee_device_"
                                                    "setup_status"
                                                ),
                                                "state": "saving",
                                            }
                                        ],
                                        "card": {
                                            "type": "markdown",
                                            "content": (
                                                "⏳ **Saving your device…**"
                                            ),
                                        },
                                    },
                                    {
                                        "type": "conditional",
                                        "conditions": [
                                            {
                                                "condition": "state",
                                                "entity": (
                                                    "sensor."
                                                    "eyzee_device_"
                                                    "setup_status"
                                                ),
                                                "state": "success",
                                            }
                                        ],
                                        "card": {
                                            "type": "markdown",
                                            "content": (
                                                "✅ **{{ state_attr("
                                                "'sensor."
                                                "eyzee_device_setup_status', "
                                                "'message') }}**"
                                            ),
                                        },
                                    },
                                    {
                                        "type": "conditional",
                                        "conditions": [
                                            {
                                                "condition": "state",
                                                "entity": (
                                                    "sensor."
                                                    "eyzee_device_"
                                                    "setup_status"
                                                ),
                                                "state": "error",
                                            }
                                        ],
                                        "card": {
                                            "type": "markdown",
                                            "content": (
                                                "⚠️ **Your device could not "
                                                "be saved.**\n\n"
                                                "{{ state_attr("
                                                "'sensor."
                                                "eyzee_device_setup_status', "
                                                "'message') }}"
                                            ),
                                        },
                                    },
                                    *_standard_navigation(
                                        "/eyzee-add-device-new/"
                                        "setup-devices"
                                    ),
                                 ],
                            }
                        ],
                    }
                )

        if unrecognised_count > 0:
            device_word = (
                "devices" if unrecognised_count != 1 else "device"
            )

            main_cards.append(
                {
                    "type": "markdown",
                    "content": (
                        f"⚠ **{unrecognised_count} other {device_word} detected**\n\n"
                        "These devices are not yet recognised by EyZEE."
                    ),
                }
            )

        main_cards.extend(
            _standard_navigation(manage_devices_path)
        )

        setup_devices_view = {
            "title": "Locate & Set Up",
            "path": "setup-devices",
            "icon": "mdi:map-marker-check-outline",
            "subview": True,
            "type": "sections",
            "max_columns": 1,
            "sections": [
                {
                    "type": "grid",
                    "cards": [
                        {
                            "type": "heading",
                            "heading": "Locate & Set Up Devices",
                            "heading_style": "title",
                            "icon": "mdi:map-marker-check-outline",
                        },
                        {
                            "type": "entities",
                            "show_header_toggle": False,
                            "entities": [
                            {
                                "type": "button",
                                "name": "Refresh Device List",
                                "icon": "mdi:refresh",
                                "action_name": "Refresh",
                                "tap_action": {
                                    "action": "perform-action",
                                    "perform_action": "eyzee_dashboard.discover_eyzee_devices",
                                },
                            },
                            ],
                        },
                        {
                            "type": "markdown",
                            "content": (
                                f"## {len(setup_devices)} device"
                                f"{'s' if len(setup_devices) != 1 else ''} "
                                "ready to set up"
                            ),
                        },
                        *setup_device_cards,
                        *_standard_navigation(
                            "/eyzee-add-device-new/add-device"
                        ),
                    ],
                }
            ],
        }

        main_view = {
            "title": "Add a Zigbee Device",
            "path": "add-device",
            "icon": "mdi:plus-circle",
            "type": "sections",
            "max_columns": 1,
            "sections": [
                {
                    "type": "grid",
                    "cards": main_cards,
                }
            ],
        }

        # Apply the shared theme to both pairing and per-device setup screens.
        for view in [main_view, setup_devices_view, *setup_views]:
            view["theme"] = "EyZEE Home"

        add_device_config = {
            "title": "Add a Zigbee Device",
            "views": [
                main_view,
                setup_devices_view,
            ],
        }

        device_setup_config = {
            "title": "Device Setup",
            "views": [
                setup_devices_view,
                *setup_views,
            ],
        }

        def _write_dashboard_file() -> None:
            ADD_DEVICE_DASHBOARD_PATH.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            ADD_DEVICE_SETUP_DASHBOARD_PATH.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            add_device_temporary_path = (
                ADD_DEVICE_DASHBOARD_PATH.with_suffix(
                    ".yaml.tmp"
                )
            )

            add_device_temporary_path.write_text(
                json.dumps(
                    add_device_config,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            add_device_temporary_path.replace(
                ADD_DEVICE_DASHBOARD_PATH
            )

            device_setup_temporary_path = (
                ADD_DEVICE_SETUP_DASHBOARD_PATH.with_suffix(
                    ".yaml.tmp"
                )
            )

            device_setup_temporary_path.write_text(
                json.dumps(
                    device_setup_config,
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            device_setup_temporary_path.replace(
                ADD_DEVICE_SETUP_DASHBOARD_PATH
            )

        try:
            await hass.async_add_executor_job(
                _write_dashboard_file
            )

            hass.states.async_set(
                "sensor.eyzee_setup_device_count",
                len(setup_devices),
                {"friendly_name": "EyZEE Devices Ready for Setup"},
            )

            _LOGGER.info(
                "EyZEE generated Sue-friendly Add Devices "
                "dashboard with %s recognised new devices",
                len(recognised_devices),
            )

        except Exception as err:
            _LOGGER.exception(
                "EyZEE could not generate Add Devices "
                "dashboard: %s",
                err,
            )

            raise HomeAssistantError(
                "Could not generate Add Devices dashboard: "
                f"{err}"
            ) from err

    async def handle_discover_existing_devices(call: ServiceCall):
        """Find Home Assistant devices not yet registered in EyZEE."""

        # -----------------------------------------------------
        # Populate room dropdown for Existing Device screen
        # -----------------------------------------------------
        try:
            await handle_populate_room_dropdown(
                type(
                    "obj",
                    (),
                    {
                        "data": {
                            "dropdown_entity": (
                                "input_select.eyzee_wizard_room"
                            )
                        }
                    },
                )()
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE: Could not populate Existing Device "
                "room dropdown: %s",
                err,
            )

        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        registry_data = await hass.async_add_executor_job(
            _read_device_registry
        )

        registered_ha_device_ids: set[str] = set()

        for device in (
            registry_data.get("devices", {}) or {}
        ).values():
            if not isinstance(device, dict):
                continue

            ha_data = device.get("ha") or {}
            device_id = ha_data.get("device_id")

            if device_id:
                registered_ha_device_ids.add(
                    str(device_id)
                )

        ALLOWED_DOMAINS = {
            "light",
            "switch",
            "fan",
            "cover",
            "lock",
            "climate",
            "sensor",
            "binary_sensor",
        }

        existing_devices: list[dict] = []

        EXCLUDED_INTEGRATIONS = {
            "backup",
            "mobile_app",
            "rpi_power",
            "sun",
        }

        EXCLUDED_NAMES = {
            "zigbee2mqtt bridge",
            "slzb-06m",
        }

        for device_id, device in dev_reg.devices.items():

            # Skip devices already registered in EyZEE.
            if device_id in registered_ha_device_ids:
                continue

            entities: list[str] = []

            for entry in ent_reg.entities.values():

                if entry.device_id != device_id:
                    continue

                if entry.disabled:
                    continue

                if entry.domain not in ALLOWED_DOMAINS:
                    continue

                entities.append(entry.entity_id)

            # Ignore HA devices with no useful entities.
            if not entities:
                continue

            entities = sorted(set(entities))

            # -------------------------------------------------
            # Determine likely primary entity / device type
            # -------------------------------------------------
            priority = [
                "light",
                "switch",
                "fan",
                "cover",
                "lock",
                "climate",
            ]

            primary_entity = None
            device_type = "other"

            for domain in priority:
                match = next(
                    (
                        entity_id
                        for entity_id in entities
                        if entity_id.startswith(
                            f"{domain}."
                        )
                    ),
                    None,
                )

                if match:
                    primary_entity = match
                    device_type = domain
                    break

            if primary_entity is None:
                primary_entity = entities[0]

            # -------------------------------------------------
            # Determine source integration
            # -------------------------------------------------
            integrations: set[str] = set()

            for identifier in (
                device.identifiers or set()
            ):
                try:
                    domain = str(identifier[0])
                except Exception:
                    continue

                integrations.add(domain)

            integration = (
                sorted(integrations)[0]
                if integrations
                else "unknown"
            )

            # Friendly display name
            display_name = (
                device.name_by_user
                or device.name
                or device.model
                or "Unnamed Device"
            )

            # -------------------------------------------------
            # Skip HA infrastructure / system devices
            # -------------------------------------------------

            if integration.lower() in EXCLUDED_INTEGRATIONS:
                continue

            if str(display_name).strip().lower() in EXCLUDED_NAMES:
                continue

            existing_devices.append(
                {
                    "device_id": device_id,
                    "name": display_name,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    "integration": integration,
                    "device_type": device_type,
                    "primary_entity": primary_entity,
                    "entities": entities,
                }
            )

        existing_devices.sort(
            key=lambda item: (
                str(item.get("name") or "").lower()
            )
        )

        # -----------------------------------------------------
        # Populate Existing Device dropdown
        # -----------------------------------------------------
        existing_device_options = ["none"]

        for device in existing_devices:
            name = str(
                device.get("name")
                or "Unnamed Device"
            ).strip()

            integration = str(
                device.get("integration")
                or "unknown"
            ).upper()

            device_id = str(
                device.get("device_id")
                or ""
            ).strip()

            if not device_id:
                continue

            existing_device_options.append(
                f"{name} [{integration}] | {device_id}"
            )

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": "input_select.eyzee_existing_device",
                "options": existing_device_options,
            },
            blocking=True,
        )

        hass.states.async_set(
            "sensor.eyzee_existing_devices",
            len(existing_devices),
            {
                "friendly_name": (
                    "EyZEE Existing Devices"
                ),
                "device_count": len(
                    existing_devices
                ),
                "devices": existing_devices,
                "updated": datetime.now().isoformat(),
            },
        )

        _LOGGER.info(
            "EyZEE: Found %d existing HA devices "
            "not registered in EyZEE",
            len(existing_devices),
        )

        return True

    # ---------------------------------------------------------
    # Register Existing HA Device
    # ---------------------------------------------------------

    async def handle_register_existing_device(call: ServiceCall):
        """Register a selected existing HA device into EyZEE."""

        selected_state = hass.states.get(
            "input_select.eyzee_existing_device"
        )
        room_state = hass.states.get(
            "input_select.eyzee_wizard_room"
        )
        name_state = hass.states.get(
            "input_text.eyzee_existing_device_name"
        )

        selected_value = (
            selected_state.state.strip()
            if selected_state
            else ""
        )

        room_value = (
            room_state.state.strip()
            if room_state
            else ""
        )

        friendly_name = (
            name_state.state.strip()
            if name_state
            else ""
        )

        if not selected_value or selected_value == "none":
            raise HomeAssistantError(
                "Please select an existing device."
            )

        if not room_value or room_value == "none":
            raise HomeAssistantError(
                "Please select a room."
            )

        if not friendly_name:
            raise HomeAssistantError(
                "Please enter a device name."
            )

        # Selected option format:
        # Device Name [ZHA] | <ha_device_id>
        if "|" not in selected_value:
            raise HomeAssistantError(
                "Selected device format is invalid."
            )

        ha_device_id = selected_value.split("|", 1)[1].strip()

        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        device = dev_reg.devices.get(ha_device_id)

        if not device:
            raise HomeAssistantError(
                f"Home Assistant device not found: {ha_device_id}"
            )

        # -----------------------------------------------------
        # Collect useful enabled entities
        # -----------------------------------------------------
        allowed_domains = {
            "light",
            "switch",
            "fan",
            "cover",
            "lock",
            "climate",
            "sensor",
            "binary_sensor",
        }

        entities: list[str] = []

        for entry in ent_reg.entities.values():
            if entry.device_id != ha_device_id:
                continue

            if entry.disabled:
                continue

            if entry.domain not in allowed_domains:
                continue

            entities.append(entry.entity_id)

        entities = sorted(set(entities))

        if not entities:
            raise HomeAssistantError(
                "Selected device has no usable entities."
            )

        # -----------------------------------------------------
        # Determine primary entity and type
        # -----------------------------------------------------
        priority = [
            "light",
            "switch",
            "fan",
            "cover",
            "lock",
            "climate",
        ]

        primary_entity = None
        device_type = "other"

        for domain in priority:
            match = next(
                (
                    entity_id
                    for entity_id in entities
                    if entity_id.startswith(f"{domain}.")
                ),
                None,
            )

            if match:
                primary_entity = match
                device_type = domain
                break

        if primary_entity is None:
            primary_entity = entities[0]

        # -----------------------------------------------------
        # Detect source integration
        # -----------------------------------------------------
        integrations: set[str] = set()

        for identifier in (device.identifiers or set()):
            try:
                integrations.add(
                    str(identifier[0]).lower()
                )
            except Exception:
                continue

        integration = (
            sorted(integrations)[0]
            if integrations
            else "unknown"
        )

        protocol = "unknown"

        if integration == "zha":
            protocol = "zigbee"
        elif integration == "mqtt":
            protocol = "zigbee"
        elif integration == "matter":
            protocol = "matter"

        # -----------------------------------------------------
        # Resolve room slug / label
        # -----------------------------------------------------
        room_label = room_value
        room_slug = _slugify(room_value)

        rooms_model = await hass.async_add_executor_job(
            _read_yaml_file,
            _path(ROOMS_YAML),
        )

        for slug, room in (
            (rooms_model or {}).get("rooms", {})
        ).items():
            label = (
                room.get("label")
                or _label_from_slug(slug)
            )

            if (
                room_value == slug
                or room_value.lower() == str(label).lower()
            ):
                room_slug = slug
                room_label = label
                break

        # -----------------------------------------------------
        # Build controls
        # -----------------------------------------------------
        controls = []

        control_index = 1

        for entity_id in entities:
            if not (
                entity_id.startswith("light.")
                or entity_id.startswith("switch.")
            ):
                continue

            controls.append(
                {
                    "index": control_index,
                    "endpoint": f"l{control_index}",
                    "source": integration,
                    "raw_key": None,
                    "entity_id": entity_id,
                    "name": friendly_name,
                    "name_slug": _slugify(friendly_name),
                }
            )

            control_index += 1

        # -----------------------------------------------------
        # Build registry key
        # -----------------------------------------------------
        registry_id = (
            f"{room_slug}_"
            f"{device_type}_"
            f"{_slugify(friendly_name)}"
        )

        now = datetime.now().isoformat()

        registry_data = await hass.async_add_executor_job(
            _read_device_registry
        )

        devices = registry_data.setdefault(
            "devices",
            {},
        )

        record = {
            "room": room_slug,
            "area_label": room_label,
            "device_type": device_type,
            "type_label": device_type.replace(
                "_",
                " ",
            ).title(),
            "device_name": _slugify(friendly_name),
            "name_label": friendly_name,
            "display_label": friendly_name,
            "capabilities": [],
            "source": {
                "integration": integration,
                "protocol": protocol,
            },
            "ha": {
                "device_id": ha_device_id,
                "primary_entity": primary_entity,
                "entities": entities,
                "last_seen": None,
                "managed_by": "eyzee",
            },
            "meta": {
                "notes": "",
                "tags": [],
                "created": now,
                "updated": now,
                "profile_id": None,
                "product_name": (
                    str(device.model)
                    if device.model
                    else friendly_name
                ),
            },
            "controls": controls,
        }

        # Z2M-specific metadata only belongs on MQTT/Z2M devices.
        if integration == "mqtt":
            record["z2m"] = {
                "friendly_name": None,
                "ieee": None,
                "manufacturer": (
                    str(device.manufacturer)
                    if device.manufacturer
                    else None
                ),
                "model": (
                    str(device.model)
                    if device.model
                    else None
                ),
            }
        
        devices[registry_id] = record
        
        await hass.async_add_executor_job(
            _write_device_registry,
            registry_data,
        )

        # -----------------------------------------------------
        # Rename HA device
        # -----------------------------------------------------
        try:
            dev_reg.async_update_device(
                ha_device_id,
                name_by_user=friendly_name,
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE: Could not rename HA device %s: %s",
                ha_device_id,
                err,
            )

        # -----------------------------------------------------
        # Clear helper and refresh discovery list
        # -----------------------------------------------------
        await hass.services.async_call(
            "input_text",
            "set_value",
            {
                "entity_id": (
                    "input_text.eyzee_existing_device_name"
                ),
                "value": "",
            },
            blocking=True,
        )

        await handle_discover_existing_devices(
            type(
                "obj",
                (),
                {"data": {}},
            )()
        )

        hass.states.async_set(
            "sensor.eyzee_existing_device_status",
            "Registered",
            {
                "friendly_name": (
                    "EyZEE Existing Device Status"
                ),
                "device": friendly_name,
                "room": room_label,
                "source": integration,
            },
        )

        return True

    # -----------------------------
    # Wizard: discovery
    # -----------------------------
    async def handle_discover_devices(call: ServiceCall):
        _LOGGER.info("EyZEE: Starting device discovery")

        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        # Get the current live Zigbee2MQTT device list.
        # This lets discovery ignore stale MQTT devices that still
        # exist in the Home Assistant device/entity registries.
        try:
            z2m_devices = await _get_live_z2m_devices()

            live_z2m_ieees = {
                str(device.get("ieee_address") or "").lower()
                for device in z2m_devices
                if device.get("ieee_address")
                and device.get("type") != "Coordinator"
                and not device.get("disabled", False)
            }

            _LOGGER.debug(
                "EyZEE: Z2M reports %d live devices",
                len(live_z2m_ieees),
            )

        except Exception as err:
            _LOGGER.warning(
                "EyZEE: Could not read live Z2M devices: %s",
                err,
            )
            live_z2m_ieees = set()

        # Keep the Sue-friendly setup room dropdown up to date.
        try:
            await handle_populate_room_dropdown(
                type(
                    "obj",
                    (),
                    {
                        "data": {
                            "dropdown_entity": (
                                "input_select.eyzee_wizard_room"
                            )
                        }
                    },
                )()
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE: Could not populate room dropdown: %s",
                err,
            )

        filter_state = hass.states.get("input_select.eyzee_discovery_filter")
        valid_filter_modes = {"Z2M only", "All devices"}

        if not filter_state or filter_state.state not in valid_filter_modes:
            filter_mode = "Z2M only"
        else:
            filter_mode = filter_state.state

        ALLOWED_DOMAINS = {
            "switch",
            "light",
            "fan",
            "sensor",
            "binary_sensor",
            "lock",
            "cover",
            "climate",
        }

        def _is_mqtt_device(device) -> bool:
            try:
                return any(
                    domain == "mqtt"
                    for domain, _ in (device.identifiers or set())
                )
            except Exception:
                return False

        device_entities: dict[str, list[str]] = {}
        orphan_entities: list[str] = []

        for entry in ent_reg.entities.values():
            if entry.domain not in ALLOWED_DOMAINS:
                continue
            if entry.disabled:
                continue
            if entry.device_id:
                device_entities.setdefault(
                    entry.device_id,
                    [],
                ).append(entry.entity_id)
            else:
                orphan_entities.append(entry.entity_id)

        # Read the EyZEE device registry once for this discovery run.
        try:
            registry_data = await hass.async_add_executor_job(
                _read_device_registry
            )
        except OSError as err:
            _LOGGER.warning(
                "EyZEE: Unable to read device registry during discovery: %s",
                err,
            )
            registry_data = {
                "version": 1,
                "devices": {},
            }
        except Exception:
            _LOGGER.exception(
                "EyZEE: Unexpected error reading device registry during discovery"
            )
            registry_data = {
                "version": 1,
                "devices": {},
            }

        registered_ha_device_ids: set[str] = set()
        registered_entity_ids: set[str] = set()

        registry_devices = registry_data.get("devices", {})

        if isinstance(registry_devices, dict):
            for registry_device in registry_devices.values():
                if not isinstance(registry_device, dict):
                    continue

                # New registry entries store the HA device ID here.
                ha_data = registry_device.get("ha", {})

                if isinstance(ha_data, dict):
                    registered_device_id = ha_data.get("device_id")

                    if (
                        isinstance(registered_device_id, str)
                        and registered_device_id
                    ):
                        registered_ha_device_ids.add(
                            registered_device_id
                        )

                # Existing registry entries store HA entities under ha.entities.
                registered_entities = []

                if isinstance(ha_data, dict):
                    registered_entities = ha_data.get("entities", [])

                # Temporary fallback in case any record uses top-level entities.
                if not registered_entities:
                    registered_entities = registry_device.get("entities", [])

                if isinstance(registered_entities, list):
                    registered_entity_ids.update(
                        entity_id
                        for entity_id in registered_entities
                        if isinstance(entity_id, str) and entity_id
                    )

                elif isinstance(registered_entities, dict):
                    registered_entity_ids.update(
                        entity_id
                        for entity_id in registered_entities.values()
                        if isinstance(entity_id, str) and entity_id
                    )

        _LOGGER.debug(
            "EyZEE: Loaded registry lookup containing %d HA device IDs "
            "and %d entity IDs",
            len(registered_ha_device_ids),
            len(registered_entity_ids),
        )

        devices_out: list[dict] = []

        for device_id, entity_ids in device_entities.items():
            device = dev_reg.devices.get(device_id)
            if not device:
                continue

            if filter_mode == "Z2M only" and not _is_mqtt_device(device):
                continue

            # Ignore stale Home Assistant MQTT device records that
            # no longer exist in the current Zigbee2MQTT network.
            if filter_mode == "Z2M only":
                device_ieees = set()

                for domain, identifier in (
                    device.identifiers or set()
                ):
                    if domain != "mqtt":
                        continue

                    match = re.search(
                        r"0x[0-9a-fA-F]{16}",
                        str(identifier),
                    )

                    if match:
                        device_ieees.add(
                            match.group(0).lower()
                        )

                # Only apply the live-Z2M filter when we actually
                # received a live device list from Zigbee2MQTT.
                if (
                    live_z2m_ieees
                    and device_ieees
                    and not device_ieees.intersection(
                        live_z2m_ieees
                    )
                ):
                    _LOGGER.debug(
                        "EyZEE: Ignoring stale Z2M device %s (%s)",
                        device.name or device_id,
                        ", ".join(sorted(device_ieees)),
                    )
                    continue

            entity_ids = sorted(set(entity_ids))

            available_entities: list[str] = []
            unavailable_entities: list[str] = []

            for eid in entity_ids:
                st = hass.states.get(eid)
                if not st or st.state in ("unavailable", "unknown", "", None):
                    unavailable_entities.append(eid)
                else:
                    available_entities.append(eid)

            name = device.name_by_user or device.name or "Unnamed device"

            ieee = None
            try:
                ieee = next(iter(device.identifiers))[1]
            except Exception:
                pass

            normalized = {
                "integration": "z2m" if _is_mqtt_device(device) else "zha",
                "manufacturer_name": device.manufacturer,
                "model_id": device.model,
                "friendly_name": name,
                "device_id": device_id,
                "ieee": ieee,
                "entities": entity_ids,
            }

            enriched = enrich_discovered_device(normalized)

            is_registered = (
                device_id in registered_ha_device_ids
                or bool(set(entity_ids) & registered_entity_ids)
            )

            devices_out.append(
                {
                    "device_id": device_id,
                    "registered": is_registered,
                    "name": enriched.get("eyzee", {}).get("product_name") or name,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    "entity_count": len(entity_ids),
                    "available_count": len(available_entities),
                    "unavailable_count": len(unavailable_entities),
                    "entities": entity_ids,
                    "profile_id": enriched.get("profile_id"),
                    "profile_match": enriched.get("profile_match"),
                    "product_name": enriched.get("eyzee", {}).get("product_name"),
                    "device_type": enriched.get("eyzee", {}).get("device_type"),
                    "features": enriched.get("eyzee", {}).get("features", {}),
                    "capabilities": enriched.get("eyzee", {}).get("capabilities", {}),
                }
            )

        devices_out.sort(
            key=lambda d: (
                -d.get("entity_count", 0),
                d.get("name", ""),
            )
        )

        discovered_entities: list[dict] = []

        for domain in ("switch", "light"):
            for entity_id in hass.states.async_entity_ids(domain):
                st = hass.states.get(entity_id)
                if not st:
                    continue

                discovered_entities.append(
                    {
                        "entity_id": entity_id,
                        "friendly_name": (
                            st.attributes.get("friendly_name") or ""
                        ).strip(),
                        "state": st.state,
                        "type": domain,
                    }
                )

        switch_count = sum(
            1
            for device in discovered_entities
            if device.get("type") == "switch"
        )

        light_count = sum(
            1
            for device in discovered_entities
            if device.get("type") == "light"
        )

        fan_count = sum(
            1
            for device in discovered_entities
            if device.get("type") == "fan"
        )

        hass.states.async_set(
            "sensor.eyzee_hardware_devices",
            f"Found {len(devices_out)} devices",
            {
                "devices": devices_out,
                "device_count": len(devices_out),
                "entities": discovered_entities,
                "entity_count": len(discovered_entities),
                "switch_count": switch_count,
                "light_count": light_count,
                "fan_count": fan_count,
                "orphan_entities": sorted(set(orphan_entities)),
                "discovered_at": datetime.now().isoformat(),
                "filter": filter_mode,
                "mode": "grouped_by_device_registry",
            },
        )

        await _write_add_device_dashboard(devices_out)

        await _notify(
            "EyZEE Device Discovery",
            (
                f"✅ Found {len(devices_out)} devices\n\n"
                f"Entities: {len(discovered_entities)} "
                f"(switch={switch_count}, light={light_count}, fan={fan_count})\n"
                f"Filter: {filter_mode}"
            ),
            "eyzee_discovery_results",
        )

        return True

    # -----------------------------
    # Live Zigbee pairing session state.
    # This is reset whenever a new pairing session starts.
    # -----------------------------
    pairing_devices_found: list[dict] = []
    pairing_event_unsub = None
    pairing_expiry_task = None
    
    async def _expire_pairing_after(delay_seconds: int) -> None:
        """Update EyZEE when the normal Zigbee pairing window expires."""

        nonlocal pairing_event_unsub, pairing_expiry_task

        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            return

        # Pairing window has naturally expired.
        # Stop listening for pairing events.
        if pairing_event_unsub is not None:
            pairing_event_unsub()
            pairing_event_unsub = None

        pairing_expiry_task = None

        hass.states.async_set(
            "sensor.eyzee_add_device_status",
            "⚪ Pairing finished",
            {
                "friendly_name": "EyZEE Add Device Status",
                "method": "Zigbee2MQTT",
                "pairing_time": 0,
                "devices_found": len(pairing_devices_found),
                "latest_device": (
                    pairing_devices_found[0].get("name")
                    if pairing_devices_found
                    else None
                ),
                "found_devices": [
                    item.get("name")
                    for item in pairing_devices_found
                ],
            },
        )

    async def _refresh_devices_after_pairing() -> None:
        """Refresh discovery after Home Assistant creates the device."""

        try:
            # First refresh after the MQTT device has had time to load.
            await asyncio.sleep(5.0)

            await handle_discover_devices(
                type("obj", (), {"data": {}})()
            )

            # Run once more because entity creation can finish after
            # the Home Assistant device itself becomes available.
            await asyncio.sleep(5.0)

            await handle_discover_devices(
                type("obj", (), {"data": {}})()
            )

        except asyncio.CancelledError:
            return

        except Exception as err:
            _LOGGER.warning(
                "EyZEE could not auto-refresh devices after pairing: %s",
                err,
            )

    async def _handle_pairing_event(msg) -> None:
        """Track devices successfully found during the current pairing session."""

        try:
            payload = json.loads(msg.payload)
        except Exception:
            return

        if not isinstance(payload, dict):
            return

        # We only care about completed device interviews.
        if payload.get("type") != "device_interview":
            return

        data = payload.get("data") or {}

        if data.get("status") != "successful":
            return

        friendly_name = str(
            data.get("friendly_name") or ""
        ).strip()

        ieee = str(
            data.get("ieee_address") or ""
        ).strip()

        definition = data.get("definition") or {}

        manufacturer = str(
            definition.get("vendor") or ""
        ).strip()

        model = str(
            definition.get("description")
            or definition.get("model")
            or ""
        ).strip()

        # Feed the discovered device through the same EyZEE
        # profile matcher used by normal device discovery.
        normalized = {
            "integration": "z2m",
            "manufacturer_name": manufacturer,
            "manufacturer": manufacturer,
            "model_id": model,
            "model": model,
        }

        enriched = enrich_discovered_device(normalized)

        product_name = (
            enriched.get("eyzee", {}).get("product_name")
            or model
            or friendly_name
            or "New Zigbee Device"
        )

        # Don't add the same physical device twice if Z2M
        # publishes more than one event for it.
        existing_ieees = {
            str(item.get("ieee") or "")
            for item in pairing_devices_found
        }

        if ieee and ieee in existing_ieees:
            return

        pairing_devices_found.insert(
            0,
            {
                "ieee": ieee,
                "name": product_name,
                "friendly_name": friendly_name,
            },
        )

        # Keep the live sensor compact while retaining the complete
        # pairing-session list in its attributes.
        hass.states.async_set(
            "sensor.eyzee_add_device_status",
            "🟢 Zigbee pairing is active",
            {
                "friendly_name": "EyZEE Add Device Status",
                "method": "Zigbee2MQTT",
                "devices_found": len(pairing_devices_found),
                "latest_device": product_name,
                "found_devices": [
                    item.get("name")
                    for item in pairing_devices_found
                ],
            },
        )

        _LOGGER.info(
            "EyZEE pairing: found %s (%s)",
            product_name,
            ieee,
        )

        hass.async_create_task(
            _refresh_devices_after_pairing()
        )

    # -----------------------------
    # Service: Zigbee2MQTT Pairing
    # -----------------------------
    async def handle_start_z2m_pairing(call: ServiceCall):
        nonlocal pairing_event_unsub, pairing_expiry_task

        # Start a fresh live discovery list for this pairing session.
        pairing_devices_found.clear()

        # Refresh discovery before pairing starts so removed or
        # previously configured devices do not remain on the
        # Locate & Set Up Devices page.
        try:
            await handle_discover_devices(
                type("obj", (), {"data": {}})()
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE could not refresh devices before pairing: %s",
                err,
            )

        # Remove any previous pairing event listener before
        # creating a new one.

        if pairing_event_unsub is not None:
            pairing_event_unsub()
            pairing_event_unsub = None

        pairing_event_unsub = await mqtt.async_subscribe(
            hass,
            "zigbee2mqtt/bridge/event",
            _handle_pairing_event,
            qos=0,
        )
        pairing_time = call.data.get("time")

        if pairing_time is None:
            st = hass.states.get("input_select.eyzee_zigbee_pairing_time")
            pairing_time = st.state if st else "240"

        try:
            pairing_time = int(pairing_time)
        except Exception:
            pairing_time = 240

        # Cancel any previous pairing expiry timer.
        if pairing_expiry_task is not None:
            pairing_expiry_task.cancel()

        # Keep EyZEE's pairing status aligned with the Z2M permit-join timer.
        pairing_expiry_task = hass.async_create_task(
            _expire_pairing_after(pairing_time)
        )

        await mqtt.async_publish(
            hass,
            "zigbee2mqtt/bridge/request/permit_join",
            json.dumps({"time": pairing_time}),
            qos=0,
            retain=False,
        )

        hass.states.async_set(
            "sensor.eyzee_add_device_status",
            f"🟢 Zigbee pairing is active for {pairing_time // 60} minutes",
            {
                "friendly_name": "EyZEE Add Device Status",
                "method": "Zigbee2MQTT",
                "pairing_time": pairing_time,
            },
        )

        await _set_status(
            f"Zigbee pairing is active for {pairing_time // 60} minutes.",
            None,
        )

        return True


    async def handle_stop_z2m_pairing(call: ServiceCall):
        nonlocal pairing_event_unsub, pairing_expiry_task

        # Cancel the automatic pairing expiry timer because
        # pairing has been stopped manually.
        if pairing_expiry_task is not None:
            pairing_expiry_task.cancel()
            pairing_expiry_task = None

        # Stop listening for live pairing events.
        if pairing_event_unsub is not None:
            pairing_event_unsub()
            pairing_event_unsub = None

        await mqtt.async_publish(
            hass,
            "zigbee2mqtt/bridge/request/permit_join",
            json.dumps({"time": 0}),
            qos=0,
            retain=False,
        )

        hass.states.async_set(
            "sensor.eyzee_add_device_status",
            "🔴 Zigbee pairing stopped",
            {
                "friendly_name": "EyZEE Add Device Status",
                "method": "Zigbee2MQTT",
                "pairing_time": 0,
                "devices_found": len(pairing_devices_found),
                "latest_device": (
                    pairing_devices_found[0].get("name")
                    if pairing_devices_found
                    else None
                ),
                "found_devices": [
                    item.get("name")
                    for item in pairing_devices_found
                ],
            },
        )

        await _set_status("Zigbee pairing stopped.", None)

        return True

    # -----------------------------
    # Wizard: add_device 10062026
    # -----------------------------
    async def handle_add_device(call: ServiceCall):
        room = call.data.get("room") or ""
        device_type = call.data.get("device_type") or ""
        installed_device = (call.data.get("z2m_from") or "").strip()
        device_friendly_name = (call.data.get("custom_friendly_name") or "").strip()
        confirm_rename = call.data.get("confirm_rename") is True

        if not room:
            st = hass.states.get("input_select.eyzee_wizard_room")
            room = st.state if st else ""

        if not device_type:
            st = hass.states.get("input_select.eyzee_wizard_device_type")
            device_type = st.state if st else ""

        if not installed_device:
            st = hass.states.get("input_select.z2m_device_friendly_name")
            installed_device = (st.state if st else "").strip()

        if not device_friendly_name:
            st = hass.states.get("input_text.eyzee_wizard_device_friendly_name")
            device_friendly_name = (st.state if st else "").strip()

        max_controls_by_type = {
            "light": 1,
            "dimmer": 1,
            "fan": 1,
            "fan_light": 2,
            "switch": 6,
            "power_point": 2,
            "sensor": 1,
            "contact_sensor": 1,
            "motion_sensor": 1,
            "presence_sensor": 1,
            "temperature_sensor": 1,
            "water_sensor": 1,
            "lock": 1,
            "blind": 1,
            "cover": 1,
            "other": 1,
        }

        temp_device_type_slug = _slugify(device_type)
        max_controls = max_controls_by_type.get(temp_device_type_slug, 1)

        control_names = []
        for idx in range(1, max_controls + 1):
            st = hass.states.get(f"input_text.eyzee_wizard_control_{idx}_name")
            value = (st.state if st else "").strip()

            if not value:
                if max_controls == 1:
                    value = device_friendly_name or installed_device or "Control"
                else:
                    value = f"Control {idx}"

            control_names.append(value)

        room_slug = _slugify(room)
        device_type_slug = _slugify(device_type)
        device_name_slug = _slugify(device_friendly_name) or _slugify(installed_device) or "device"

        if not room_slug or room_slug in ("none", "unknown", "unavailable"):
            raise HomeAssistantError("Room is required")

        if not device_type_slug or device_type_slug in ("none", "unknown", "unavailable"):
            raise HomeAssistantError("Device type is required")

        if not installed_device or installed_device in ("none", "unknown", "unavailable"):
            raise HomeAssistantError("Installed device is required")

        if not device_friendly_name:
            raise HomeAssistantError("Friendly name is required")

        z2m_to_name = _slugify(device_friendly_name)

        provisional_registry_id = _slugify(
            "_".join([room_slug, device_type_slug, device_name_slug]).strip("_")
        )

        did_rename = False
        rename_error = None

        if confirm_rename and installed_device and installed_device not in ("none", "unknown", "unavailable"):
            try:
                await mqtt.async_publish(
                    hass,
                    "zigbee2mqtt/bridge/request/device/rename",
                    json.dumps({"from": installed_device, "to": z2m_to_name}),
                    qos=0,
                    retain=False,
                )
                did_rename = True
            except Exception as e:
                _LOGGER.exception("EyZEE: Z2M rename failed: %s", e)
                rename_error = f"{type(e).__name__}: {e}"

        def _find_matching_entities():
            matches = []

            search_terms = {
                installed_device,
                z2m_to_name,
                _slugify(installed_device),
                _slugify(device_friendly_name),
                device_friendly_name,
            }

            search_terms = {
                str(s).lower()
                for s in search_terms
                if s and str(s).lower() not in ("none", "unknown", "unavailable")
            }

            entity_registry = er.async_get(hass)
            device_registry = dr.async_get(hass)

            for entity_id in hass.states.async_entity_ids():
                st = hass.states.get(entity_id)
                haystack = [entity_id.lower()]

                if st:
                    for value in st.attributes.values():
                        if isinstance(value, str):
                            haystack.append(value.lower())

                entry = entity_registry.async_get(entity_id)

                if entry:
                    if entry.name:
                        haystack.append(str(entry.name).lower())

                    if entry.original_name:
                        haystack.append(str(entry.original_name).lower())

                    if entry.unique_id:
                        haystack.append(str(entry.unique_id).lower())

                    if entry.platform:
                        haystack.append(str(entry.platform).lower())

                    if entry.device_id:
                        dev = device_registry.async_get(entry.device_id)

                        if dev:
                            if dev.name:
                                haystack.append(str(dev.name).lower())

                            if dev.name_by_user:
                                haystack.append(str(dev.name_by_user).lower())

                            if dev.manufacturer:
                                haystack.append(str(dev.manufacturer).lower())

                            if dev.model:
                                haystack.append(str(dev.model).lower())

                            for identifier in dev.identifiers:
                                for part in identifier:
                                    haystack.append(str(part).lower())

                combined = " ".join(haystack)

                if any(term in combined for term in search_terms):
                    matches.append(entity_id)

            return sorted(set(matches))

        ha_entities = _find_matching_entities()
        ha_primary_entity = ha_entities[0] if ha_entities else None
        existing_registry_id = _find_existing_registry_id_for_entities(ha_entities)
        registry_id = existing_registry_id or provisional_registry_id
        
        ha_device_id = None

        entity_registry = er.async_get(hass)

        for entity_id in ha_entities:
            entry = entity_registry.async_get(entity_id)

            if entry and entry.device_id:
                ha_device_id = entry.device_id
                break

        def _is_valid_control_entity(entity_id: str, device_type_slug: str) -> bool:
            if not entity_id:
                return False

            lowered = entity_id.lower()

            exclude_words = (
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
                return False

            if lowered.startswith("select."):
                return False

            if lowered.startswith("sensor."):
                return False

            if lowered.startswith("binary_sensor."):
                return False

            if device_type_slug == "light":
                return entity_id.startswith("light.")

            if device_type_slug == "dimmer":
                return entity_id.startswith("light.")

            if device_type_slug == "switch":
                return entity_id.startswith("switch.")

            if device_type_slug == "fan":
                return entity_id.startswith("fan.")

            if device_type_slug == "fan_light":
                return entity_id.startswith("fan.") or entity_id.startswith("light.") or entity_id.startswith("switch.")

            if device_type_slug in ("blind", "cover"):
                return entity_id.startswith("cover.")

            if device_type_slug == "lock":
                return entity_id.startswith("lock.")

            return (
                entity_id.startswith("switch.")
                or entity_id.startswith("light.")
                or entity_id.startswith("fan.")
                or entity_id.startswith("cover.")
                or entity_id.startswith("lock.")
            )

        usable_entities = [
            e for e in ha_entities
            if _is_valid_control_entity(e, device_type_slug)
        ]

        try:
            await hass.async_add_executor_job(
                _upsert_registry_device,
                registry_id,
                room_slug,
                device_type_slug,
                device_name_slug,
                z2m_to_name,
                ha_primary_entity,
                ha_entities,
                None,
                None,
                None,
                ha_device_id,
            )

            def _add_controls_to_registry():
                data = _read_device_registry()
                devices = data.setdefault("devices", {})
                device = devices.get(registry_id)

                if isinstance(device, dict):
                    device["display_label"] = device_friendly_name

                    existing_controls = device.get("controls", []) or []
                    merged_controls = []

                    max_count = max(len(existing_controls), len(control_names), len(usable_entities))
                    for idx in range(1, max_count + 1):
                        existing_control = next(
                            (
                                c for c in existing_controls
                                if isinstance(c, dict) and c.get("index") == idx
                            ),
                            {},
                        )

                        control_name = (
                            control_names[idx - 1]
                            if idx - 1 < len(control_names)
                            else existing_control.get("name")
                            or f"L{idx}"
                        )

                        entity_id = (
                            existing_control.get("entity_id")
                            or (
                                usable_entities[idx - 1]
                                if idx - 1 < len(usable_entities)
                                else None
                            )
                        )

                        merged_controls.append(
                            {
                                "index": idx,
                                "endpoint": existing_control.get("endpoint") or f"l{idx}",
                                "source": existing_control.get("source") or "generic",
                                "raw_key": existing_control.get("raw_key") or f"state_l{idx}",
                                "entity_id": entity_id,
                                "name": control_name,
                                "name_slug": _slugify(control_name),
                            }
                        )

                    device["controls"] = merged_controls
                    devices[registry_id] = device
                    _write_device_registry(data)

            await hass.async_add_executor_job(_add_controls_to_registry)

        except Exception as e:
            _LOGGER.exception("EyZEE: failed to write device_registry.yaml: %s", e)
            raise

        msg_lines = [
            "✅ Device assignment received.",
            f"• Room: {room_slug}",
            f"• Device Type: {device_type_slug}",
            f"• Device: {installed_device}",
            f"• Friendly Name: {device_friendly_name}",
            f"• Matched HA Entities: {len(ha_entities)}",
            f"• Controls: {len(control_names)}",
        ]

        if did_rename:
            msg_lines += [
                "",
                "✅ Zigbee2MQTT rename requested:",
                f"• From: {installed_device}",
                f"• To: {z2m_to_name}",
            ]
        elif confirm_rename and installed_device not in ("none", "unknown", "unavailable"):
            msg_lines += ["", "⚠️ Rename requested but failed:", f"{rename_error or 'Unknown error'}"]
        else:
            msg_lines += ["", "ℹ️ Rename not performed."]

        await _notify("EyZEE Device Assigned", "\n".join(msg_lines), "eyzee_device_assigned")

        try:
            await handle_populate_z2m_dropdown(
                type(
                    "obj",
                    (),
                    {
                        "data": {
                            "dropdown_entity": "input_select.z2m_device_friendly_name",
                            "base_topic": "zigbee2mqtt",
                        }
                    },
                )
            )
        except Exception:
            pass

        return True
        
    # -----------------------------
    # Service: Identify device
    # -----------------------------
    async def handle_identify_device(call: ServiceCall):
        """
        Identify a physical device by briefly toggling one usable entity.

        Behaviour:
        - Prefer a light entity.
        - Fall back to a switch entity.
        - Restore the entity to its original state.
        """

        device_id = str(call.data.get("device_id") or "").strip()
        duration = call.data.get("duration", 2)

        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = 2.0

        duration = max(0.5, min(duration, 10.0))

        if not device_id:
            raise HomeAssistantError("A Home Assistant device_id is required.")

        entity_registry = er.async_get(hass)

        matching_entities: list[str] = []

        for entry in entity_registry.entities.values():
            if entry.device_id != device_id:
                continue

            if entry.disabled:
                continue

            if entry.domain not in ("light", "switch"):
                continue

            matching_entities.append(entry.entity_id)

        # Prefer actual lights over switch entities.
        matching_entities.sort(
            key=lambda entity_id: (
                0 if entity_id.startswith("light.") else 1,
                entity_id,
            )
        )

        target_entity = None
        original_state = None
        needs_initialisation = False

        # First preference: an entity that already has a known ON/OFF state.
        for entity_id in matching_entities:
            state = hass.states.get(entity_id)

            if not state:
                continue

            if state.state in ("on", "off"):
                target_entity = entity_id
                original_state = state.state
                break

        # Freshly paired devices can initially report unknown/unavailable.
        # If no known-state entity exists, use the first available control
        # and initialise it before performing Locate.
        if target_entity is None and matching_entities:
            target_entity = matching_entities[0]
            needs_initialisation = True

        if not target_entity:
            hass.states.async_set(
                "sensor.eyzee_identify_status",
                "unavailable",
                {
                    "updated": datetime.now().isoformat(),
                    "device_id": device_id,
                    "entity_id": None,
                    "message": (
                        "No available light or switch entity could be used "
                        "to identify this device."
                    ),
                },
            )

            raise HomeAssistantError(
                "No available light or switch entity could be used "
                "to identify this device."
            )

        domain = target_entity.split(".", 1)[0]

        hass.states.async_set(
            "sensor.eyzee_identify_status",
            "identifying",
            {
                "updated": datetime.now().isoformat(),
                "device_id": device_id,
                "entity_id": target_entity,
                "original_state": original_state,
                "duration": duration,
                "message": "Identifying device.",
            },
        )

        try:
            # A freshly paired device may not yet have reported a definite
            # ON/OFF state. Initialise it to OFF so Locate can operate
            # predictably without requiring the installer to use Z2M first.
            if needs_initialisation:
                await hass.services.async_call(
                    domain,
                    "turn_off",
                    {"entity_id": target_entity},
                    blocking=True,
                )

                await asyncio.sleep(1.0)

                state = hass.states.get(target_entity)

                if not state or state.state not in ("on", "off"):
                    raise HomeAssistantError(
                        "The device was found but has not finished initialising. "
                        "Please try Locate again."
                    )

                original_state = state.state

            if original_state == "off":
                # Off device: briefly turn it on, then restore off.
                await hass.services.async_call(
                    domain,
                    "turn_on",
                    {"entity_id": target_entity},
                    blocking=True,
                )

                await asyncio.sleep(duration)

                await hass.services.async_call(
                    domain,
                    "turn_off",
                    {"entity_id": target_entity},
                    blocking=True,
                )

            else:
                # On device: briefly turn it off, then restore on.
                await hass.services.async_call(
                    domain,
                    "turn_off",
                    {"entity_id": target_entity},
                    blocking=True,
                )

                await asyncio.sleep(duration)

                await hass.services.async_call(
                    domain,
                    "turn_on",
                    {"entity_id": target_entity},
                    blocking=True,
                )

            hass.states.async_set(
                "sensor.eyzee_identify_status",
                "complete",
                {
                    "updated": datetime.now().isoformat(),
                    "device_id": device_id,
                    "entity_id": target_entity,
                    "original_state": original_state,
                    "restored_state": original_state,
                    "duration": duration,
                    "message": "Device identification completed.",
                },
            )

            return True

        except Exception as err:
            _LOGGER.exception(
                "EyZEE identify failed for device %s using %s: %s",
                device_id,
                target_entity,
                err,
            )

            # Best-effort state restoration if identification failed midway.
            try:
                restore_service = (
                    "turn_on" if original_state == "on" else "turn_off"
                )

                await hass.services.async_call(
                    domain,
                    restore_service,
                    {"entity_id": target_entity},
                    blocking=True,
                )
            except Exception as restore_err:
                _LOGGER.warning(
                    "EyZEE could not restore %s after identify failure: %s",
                    target_entity,
                    restore_err,
                )

            hass.states.async_set(
                "sensor.eyzee_identify_status",
                "error",
                {
                    "updated": datetime.now().isoformat(),
                    "device_id": device_id,
                    "entity_id": target_entity,
                    "original_state": original_state,
                    "message": f"{type(err).__name__}: {err}",
                },
            )

            raise HomeAssistantError(
                f"Could not identify device: {err}"
            ) from err

    # -----------------------------
    # Service: Setup device
    # -----------------------------
    async def _perform_setup_device(call: ServiceCall):
        """
        Set up a discovered Home Assistant device in EyZEE.

        Required inputs:
        - device_id
        - room
        - friendly_name

        This first version:
        - finds the exact HA device
        - collects its entities
        - identifies its EyZEE profile and device type
        - creates or updates the EyZEE registry entry
        - stores the HA device ID
        - creates basic control records
        - refreshes device discovery

        It does not rename Zigbee2MQTT or HA entity IDs.
        """

        device_id = str(
            call.data.get("device_id") or ""
        ).strip()

        room = str(
            call.data.get("room") or ""
        ).strip()

        friendly_name = str(
            call.data.get("friendly_name") or ""
        ).strip()

        # The Sue-friendly dashboard supplies Room, Friendly Name
        # and individual control names through the existing
        # Home Assistant helpers.
        if not room:
            room_state = hass.states.get(
                "input_select.eyzee_wizard_room"
            )
            room = str(
                room_state.state if room_state else ""
            ).strip()

        if not friendly_name:
            name_state = hass.states.get(
                "input_text.eyzee_wizard_device_friendly_name"
            )
            friendly_name = str(
                name_state.state if name_state else ""
            ).strip()

        # Read the optional names Sue entered for the individual
        # buttons / controls on the device.
        control_names: list[str] = []

        for index in range(1, 7):
            control_state = hass.states.get(
                f"input_text.eyzee_wizard_control_{index}_name"
            )

            control_name = str(
                control_state.state if control_state else ""
            ).strip()

            control_names.append(control_name)

        # Validate the required setup information.
        if not device_id:
            raise HomeAssistantError("Device ID is required")

        if not room or room.lower() in (
            "none",
            "unknown",
            "unavailable",
        ):
            raise HomeAssistantError("Room is required")

        if not friendly_name:
            raise HomeAssistantError("Friendly name is required")

        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)

        device = device_registry.async_get(device_id)

        if not device:
            raise HomeAssistantError(
                f"Home Assistant device not found: {device_id}"
            )

        # Collect every enabled HA entity belonging to this exact device.
        ha_entities: list[str] = []

        for entry in entity_registry.entities.values():
            if entry.device_id != device_id:
                continue

            if entry.disabled:
                continue

            ha_entities.append(entry.entity_id)

        ha_entities = sorted(set(ha_entities))

        if not ha_entities:
            raise HomeAssistantError(
                "No enabled Home Assistant entities were found "
                "for this device"
            )

        # Determine whether this is an MQTT/Zigbee2MQTT device.
        is_mqtt_device = False

        try:
            is_mqtt_device = any(
                domain == "mqtt"
                for domain, _ in (device.identifiers or set())
            )
        except Exception:
            is_mqtt_device = False

        ieee = None

        try:
            for identifier_domain, identifier_value in (
                device.identifiers or set()
            ):
                if identifier_domain == "mqtt":
                    ieee = str(identifier_value)
                    break

            if ieee is None and device.identifiers:
                ieee = str(next(iter(device.identifiers))[1])

        except Exception:
            ieee = None

        current_device_name = (
            device.name_by_user
            or device.name
            or friendly_name
        )

        normalized = {
            "integration": "z2m" if is_mqtt_device else "zha",
            "manufacturer_name": device.manufacturer,
            "model_id": device.model,
            "friendly_name": current_device_name,
            "device_id": device_id,
            "ieee": ieee,
            "entities": ha_entities,
        }

        enriched = enrich_discovered_device(normalized)

        profile_id = enriched.get("profile_id")
        profile_data = enriched.get("eyzee", {}) or {}

        detected_device_type = str(
            profile_data.get("device_type") or ""
        ).strip()

        # Convert profile terminology into the existing registry types.
        device_type_map = {
            "light_switch": "switch",
            "touch_switch": "switch",
            "smart_switch": "switch",
            "rgbw_light": "light",
            "rgb_light": "light",
            "downlight": "light",
            "smart_light": "light",
            "dimmer_switch": "dimmer",
            "fan_controller": "fan",
            "fan_light_switch": "fan_light",
            "power_point": "power_point",
            "smart_plug": "power_point",
            "presence_sensor": "presence_sensor",
            "motion_sensor": "motion_sensor",
            "contact_sensor": "contact_sensor",
            "temperature_sensor": "temperature_sensor",
            "water_sensor": "water_sensor",
            "door_lock": "lock",
            "blind_controller": "blind",
        }

        device_type_slug = device_type_map.get(
            _slugify(detected_device_type),
            _slugify(detected_device_type),
        )

        # Fall back to the available control domains when no profile matches.
        if (
            not device_type_slug
            or device_type_slug
            in ("none", "unknown", "unavailable", "unnamed")
        ):
            if any(
                entity_id.startswith("light.")
                for entity_id in ha_entities
            ):
                device_type_slug = "light"

            elif any(
                entity_id.startswith("switch.")
                for entity_id in ha_entities
            ):
                device_type_slug = "switch"

            elif any(
                entity_id.startswith("fan.")
                for entity_id in ha_entities
            ):
                device_type_slug = "fan"

            elif any(
                entity_id.startswith("cover.")
                for entity_id in ha_entities
            ):
                device_type_slug = "cover"

            elif any(
                entity_id.startswith("lock.")
                for entity_id in ha_entities
            ):
                device_type_slug = "lock"

            else:
                device_type_slug = "other"

        room_slug = _slugify(room)
        device_name_slug = _slugify(friendly_name)

        provisional_registry_id = _slugify(
            "_".join(
                [
                    room_slug,
                    device_type_slug,
                    device_name_slug,
                ]
            )
        )

        existing_registry_id = (
            _find_existing_registry_id_for_entities(ha_entities)
        )

        registry_id = (
            existing_registry_id
            or provisional_registry_id
        )

        # Configuration entities must not be selected as the primary control.
        excluded_primary_terms = (
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
            "switch_type",
            "decouplar_mode",
        )

        primary_candidates = [
            entity_id
            for entity_id in ha_entities
            if not any(
                term in entity_id.lower()
                for term in excluded_primary_terms
            )
        ]

        primary_entity = next(
            (
                entity_id
                for entity_id in primary_candidates
                if entity_id.startswith("light.")
            ),
            None,
        )

        if primary_entity is None:
            primary_entity = next(
                (
                    entity_id
                    for entity_id in primary_candidates
                    if entity_id.startswith("switch.")
                ),
                None,
            )

        if primary_entity is None:
            primary_entity = next(
                (
                    entity_id
                    for entity_id in primary_candidates
                    if entity_id.startswith(
                        (
                            "fan.",
                            "cover.",
                            "lock.",
                            "binary_sensor.",
                            "sensor.",
                        )
                    )
                ),
                None,
            )

        if primary_entity is None:
            primary_entity = ha_entities[0]
            
        # Rename Zigbee2MQTT device to the Sue-friendly device name.
        z2m_friendly_name = _slugify(friendly_name)

        if is_mqtt_device:
            try:
                await mqtt.async_publish(
                    hass,
                    "zigbee2mqtt/bridge/request/device/rename",
                    json.dumps(
                        {
                            "from": current_device_name,
                            "to": z2m_friendly_name,
                        }
                    ),
                    qos=0,
                    retain=False,
                )

                _LOGGER.info(
                    "EyZEE: Zigbee2MQTT rename requested: %s -> %s",
                    current_device_name,
                    z2m_friendly_name,
                )

            except Exception as err:
                _LOGGER.warning(
                    "EyZEE: Zigbee2MQTT rename failed: %s",
                    err,
                )

        await hass.async_add_executor_job(
            _upsert_registry_device,
            registry_id,
            room_slug,
            device_type_slug,
            device_name_slug,
            z2m_friendly_name,
            primary_entity,
            ha_entities,
            ieee,
            device.manufacturer,
            device.model,
            device_id,
        )

        # Configuration entities must not become user controls.
        excluded_control_terms = (
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
            "switch_type",
            "decouplar_mode",
        )

        usable_entities: list[str] = []

        for entity_id in ha_entities:
            lowered = entity_id.lower()

            if any(
                term in lowered
                for term in excluded_control_terms
            ):
                continue

            if entity_id.startswith(
                (
                    "light.",
                    "switch.",
                    "fan.",
                    "cover.",
                    "lock.",
                )
            ):
                usable_entities.append(entity_id)
                continue

            # Fan-light switches expose fan speed as a select entity.
            if (
                device_type_slug == "fan_light"
                and entity_id.startswith("select.")
                and "fan_speed" in lowered
            ):
                usable_entities.append(entity_id)

        def _finish_setup_registry():
            registry_data = _read_device_registry()
            registry_devices = registry_data.setdefault(
                "devices",
                {},
            )

            registry_device = registry_devices.get(registry_id)

            if not isinstance(registry_device, dict):
                raise HomeAssistantError(
                    "EyZEE registry record was not created"
                )

            registry_device["display_label"] = friendly_name
            registry_device["device_name"] = device_name_slug
            registry_device["name_label"] = friendly_name

            ha_data = registry_device.setdefault("ha", {})
            ha_data["device_id"] = device_id
            ha_data["primary_entity"] = primary_entity
            ha_data["entities"] = ha_entities
            ha_data["managed_by"] = "eyzee"

            meta_data = registry_device.setdefault("meta", {})

            if profile_id:
                meta_data["profile_id"] = profile_id

            product_name = profile_data.get("product_name")

            if product_name:
                meta_data["product_name"] = product_name

            existing_controls = (
                registry_device.get("controls", []) or []
            )

            existing_by_entity = {
                control.get("entity_id"): control
                for control in existing_controls
                if isinstance(control, dict)
                and control.get("entity_id")
            }

            controls: list[dict] = []

            for index, entity_id in enumerate(
                usable_entities,
                start=1,
            ):
                existing_control = existing_by_entity.get(
                    entity_id,
                    {},
                )

                state = hass.states.get(entity_id)

                default_control_name = None

                if state:
                    default_control_name = (
                        state.attributes.get("friendly_name")
                    )

                if (
                    device_type_slug == "fan_light"
                    and entity_id.startswith("select.")
                    and "fan_speed" in entity_id.lower()
                ):
                    control_name = "Fan Speed"

                    try:
                        entity_registry.async_update_entity(
                            entity_id,
                            name="Fan Speed",
                        )
                    except Exception as err:
                        _LOGGER.warning(
                            "EyZEE: Could not rename fan speed entity %s: %s",
                            entity_id,
                            err,
                        )

                elif (
                    device_type_slug == "fan_light"
                    and entity_id.startswith("switch.")
                    and "light" in entity_id.lower()
                ):
                    control_name = "Light"

                else:
                    # Prefer the Sue-friendly control name entered
                    # during device setup.
                    entered_control_name = (
                        control_names[index - 1]
                        if index - 1 < len(control_names)
                        else ""
                    )

                if len(usable_entities) == 1:
                    # A single-control device such as a downlight,
                    # plug or 1-gang switch should use the device
                    # name rather than a meaningless L1 label.
                    control_name = (
                        entered_control_name
                        or friendly_name
                        or existing_control.get("name")
                        or default_control_name
                        or "Control 1"
                    )
                else:
                    control_name = (
                        entered_control_name
                        or existing_control.get("name")
                        or default_control_name
                        or f"Control {index}"
                    )

                if (
                    device_type_slug == "fan_light"
                    and entity_id.startswith("select.")
                    and "fan_speed" in entity_id.lower()
                ):
                    control_endpoint = "fan_speed"
                    control_raw_key = "fan_speed"
                else:
                    control_endpoint = (
                        existing_control.get("endpoint")
                        or f"l{index}"
                    )
                    control_raw_key = (
                        existing_control.get("raw_key")
                        or f"state_l{index}"
                    )

                controls.append(
                    {
                        "index": index,
                        "endpoint": control_endpoint,
                        "source": (
                            existing_control.get("source")
                            or "home_assistant"
                        ),
                        "raw_key": control_raw_key,
                        "entity_id": entity_id,
                        "name": control_name,
                        "name_slug": _slugify(control_name),
                    }
                )

            registry_device["controls"] = controls
            registry_devices[registry_id] = registry_device

            _write_device_registry(registry_data)

        await hass.async_add_executor_job(
            _finish_setup_registry
        )

        _update_device_inventory()

        _LOGGER.info(
            "EyZEE: Device setup complete: device_id=%s, "
            "registry_id=%s, room=%s, profile=%s",
            device_id,
            registry_id,
            room_slug,
            profile_id,
        )

        await _notify(
            "EyZEE Device Set Up",
            (
                f"✅ {friendly_name} has been set up.\n\n"
                f"Room: {room}\n"
                f"Device type: {device_type_slug}\n"
                f"Profile: {profile_id or 'Generic device'}\n"
                f"Controls: {len(usable_entities)}"
            ),
            "eyzee_device_setup_complete",
        )

        # Refresh discovery so the device becomes registered immediately.
        await handle_discover_devices(call)

        return True

    async def handle_setup_device(call: ServiceCall):
        """Set up a device with homeowner-friendly status feedback."""

        device_id = str(
            call.data.get("device_id") or ""
        ).strip()

        room_state = hass.states.get(
            "input_select.eyzee_wizard_room"
        )

        name_state = hass.states.get(
            "input_text.eyzee_wizard_device_friendly_name"
        )

        selected_room = str(
            room_state.state if room_state else ""
        ).strip()

        friendly_name = str(
            name_state.state if name_state else ""
        ).strip()

        hass.states.async_set(
            "sensor.eyzee_device_setup_status",
            "saving",
            {
                "friendly_name": (
                    "EyZEE Device Setup Status"
                ),
                "message": "Saving your device…",
                "device_id": device_id,
            },
        )

        try:
            result = await _perform_setup_device(call)

        except Exception as err:
            hass.states.async_set(
                "sensor.eyzee_device_setup_status",
                "error",
                {
                    "friendly_name": (
                        "EyZEE Device Setup Status"
                    ),
                    "message": (
                        f"{type(err).__name__}: {err}"
                    ),
                    "device_id": device_id,
                },
            )
            raise

        # Rebuild room dashboards after successful device setup.
        try:
            await hass.services.async_call(
                DOMAIN,
                "build_room_views",
                {},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE: failed to rebuild room views "
                "after device setup: %s",
                err,
            )

        room_label = (
            selected_room.replace("_", " ").title()
            or "the selected room"
        )

        hass.states.async_set(
            "sensor.eyzee_device_setup_status",
            "success",
            {
                "friendly_name": (
                    "EyZEE Device Setup Status"
                ),
                "message": (
                    f"{friendly_name} has been added "
                    f"to {room_label}."
                ),
                "device_id": device_id,
            },
        )

        # Hide the success message after 10 seconds.
        async def _clear_setup_status():
            await asyncio.sleep(10)

            current = hass.states.get(
                "sensor.eyzee_device_setup_status"
            )

            if (
                current is not None
                and current.state == "success"
                and current.attributes.get("device_id")
                == device_id
            ):
                hass.states.async_set(
                    "sensor.eyzee_device_setup_status",
                    "idle",
                    {
                        "friendly_name": (
                            "EyZEE Device Setup Status"
                        ),
                        "message": "",
                    },
                )

        hass.async_create_task(_clear_setup_status())

        return result

    # -----------------------------
    # Service: Run Action
    # -----------------------------
    async def handle_run_action(call: ServiceCall):
        action_id = call.data.get("action_id")

        if not action_id:
            raise HomeAssistantError(
                "action_id is required"
            )

        await _run_action(action_id)

    # -----------------------------
    # Service: Refresh Device Inventory
    # -----------------------------
    async def handle_refresh_device_inventory(call: ServiceCall):
        _update_device_inventory()

    # -----------------------------
    # Register services
    # -----------------------------
    hass.services.async_register(
        DOMAIN,
        "generate",
        handle_generate,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "refresh_device_inventory",
        handle_refresh_device_inventory,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "run_action",
        handle_run_action,
        schema=vol.Schema(
            {
                vol.Required("action_id"): str,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "build_house",
        handle_build_house,
        schema=vol.Schema(
            {
                vol.Optional("project_name", default="My Home"): cv.string,
                vol.Optional("floors", default=1): vol.Coerce(int),
                vol.Optional("counts", default={}): dict,
                vol.Optional("outdoor", default=[]): vol.Any(list, cv.string),
                vol.Optional("custom_rooms", default=[]): list,
                vol.Optional("features_default", default=["lights"]): list,
                vol.Optional("features_overrides", default={}): dict,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "clear_rooms",
        handle_clear_rooms,
        schema=vol.Schema({vol.Required("confirm"): cv.string}),
    )

    hass.services.async_register(
        DOMAIN,
        "remove_room",
        handle_remove_room,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "restore_rooms_backup",
        handle_restore_rooms_backup,
        schema=vol.Schema({}),
    )

    async_register_lighting_groups_services(hass)

    async_register_zigbee_coordinator_services(hass)

    async_register_smart_behaviour_services(hass)

    async_register_remove_device_services(hass)

    async_register_room_view_services(hass)

    async_register_room_location_services(hass)

    hass.services.async_register(
        DOMAIN,
        "start_z2m_pairing",
        handle_start_z2m_pairing,
        schema=vol.Schema(
            {
                vol.Optional("time", default=240): cv.positive_int,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "stop_z2m_pairing",
        handle_stop_z2m_pairing,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "identify_device",
        handle_identify_device,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
                vol.Optional("duration", default=2): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0.5, max=10),
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "setup_device",
        handle_setup_device,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
                vol.Optional("room"): cv.string,
                vol.Optional("friendly_name"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "discover_existing_devices",
        handle_discover_existing_devices,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "register_existing_device",
        handle_register_existing_device,
        schema=vol.Schema({}),
    )

    # -----------------------------
    # Registered Device Name Editor
    # -----------------------------
    def _registered_device_label(registry_id: str, device: dict) -> str:
        area = device.get("area_label") or device.get("room") or ""
        display = device.get("display_label") or device.get("device_name") or registry_id
        return f"{area} • {display}" if area else display


    def _find_registry_id_from_registered_dropdown(value: str) -> str:
        value = (value or "").strip()

        if not value or value in ("none", "unknown", "unavailable"):
            return ""

        dropdown_map = hass.data.get(DOMAIN, {}).get("registered_device_dropdown_map", {})

        if value in dropdown_map:
            return dropdown_map[value]

        return value


    async def handle_populate_registered_devices(call: ServiceCall):
        data = await hass.async_add_executor_job(_read_device_registry)
        devices = data.get("devices", {}) or {}

        options = ["none"]
        dropdown_map = {}
        used_labels = {}

        if isinstance(devices, dict):
            for registry_id, device in devices.items():
                if not isinstance(device, dict):
                    continue

                label_base = _registered_device_label(registry_id, device)

                count = used_labels.get(label_base, 0) + 1
                used_labels[label_base] = count

                label = label_base if count == 1 else f"{label_base} ({count})"

                options.append(label)
                dropdown_map[label] = registry_id

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["registered_device_dropdown_map"] = dropdown_map

        await hass.services.async_call(
            "input_select",
            "set_options",
            {
                "entity_id": "input_select.eyzee_registered_device",
                "options": options,
            },
            blocking=True,
        )

        await _set_status(f"Loaded {len(options) - 1} registered device(s).", None)

        return True


    async def handle_load_registered_device(call: ServiceCall):
        registry_id = call.data.get("registry_id") or ""

        if not registry_id:
            st = hass.states.get("input_select.eyzee_registered_device")
            registry_id = _find_registry_id_from_registered_dropdown(st.state if st else "")

        if not registry_id:
            raise HomeAssistantError("Registered device is required")

        data = await hass.async_add_executor_job(_read_device_registry)
        device = data.get("devices", {}).get(registry_id)

        if not isinstance(device, dict):
            raise HomeAssistantError(f"Registered device not found: {registry_id}")

        room_name = device.get("area_label") or device.get("room") or ""
        device_name = device.get("display_label") or device.get("name_label") or device.get("device_name") or ""

        await hass.services.async_call(
            "input_text",
            "set_value",
            {
                "entity_id": "input_text.eyzee_registered_room_name",
                "value": room_name,
            },
            blocking=True,
        )

        await hass.services.async_call(
            "input_text",
            "set_value",
            {
                "entity_id": "input_text.eyzee_registered_device_name",
                "value": device_name,
            },
            blocking=True,
        )

        controls = device.get("controls", []) or []

        for idx in range(1, 7):
            value = ""

            for control in controls:
                if isinstance(control, dict) and control.get("index") == idx:
                    value = control.get("name") or ""
                    break

            await hass.services.async_call(
                "input_text",
                "set_value",
                {
                    "entity_id": f"input_text.eyzee_registered_control_{idx}_name",
                    "value": value,
                },
                blocking=True,
            )

        available_controls = [
            control
            for control in controls
            if isinstance(control, dict)
        ]

        control_count = len(available_controls)

        # Single-control devices use Device Name, so they do not
        # need a separate Control 1 naming field.
        control_field_count = (
            control_count if control_count > 1 else 0
        )

        hass.states.async_set(
            "sensor.eyzee_rename_device_status",
            "Loaded selected device",
            {
                "friendly_name": (
                    "EyZEE Rename Device Status"
                ),
                "device": device_name,
                "room": room_name,
                "control_count": control_count,
                "control_field_count": control_field_count,
            },
        )

        await _set_status(f"Loaded registered device: {device_name}", None)

        return True


    async def handle_update_registered_device_names(call: ServiceCall):
        registry_id = call.data.get("registry_id") or ""

        if not registry_id:
            st = hass.states.get("input_select.eyzee_registered_device")
            registry_id = _find_registry_id_from_registered_dropdown(st.state if st else "")

        if not registry_id:
            raise HomeAssistantError("Registered device is required")

        room_name = (call.data.get("room_name") or "").strip()

        if not room_name:
            st = hass.states.get("input_select.eyzee_registered_room")
            room_name = (st.state if st else "").strip()

        device_name = (call.data.get("device_name") or "").strip()

        if not device_name:
            st = hass.states.get("input_text.eyzee_registered_device_name")
            device_name = (st.state if st else "").strip()

        if not device_name:
            raise HomeAssistantError("Device name is required")

        control_names = {}

        for idx in range(1, 7):
            value = (call.data.get(f"control_{idx}_name") or "").strip()

            if not value:
                st = hass.states.get(f"input_text.eyzee_registered_control_{idx}_name")
                value = (st.state if st else "").strip()

            if value:
                control_names[idx] = value

        new_z2m_name = _slugify(device_name)

        def _get_current_z2m_name():
            data = _read_device_registry()
            device = data.get("devices", {}).get(registry_id)

            if not isinstance(device, dict):
                raise HomeAssistantError(
                    f"Registered device not found: {registry_id}"
                )

            z2m = device.get("z2m", {}) or {}

            if not isinstance(z2m, dict):
                return ""

            return str(
                z2m.get("friendly_name") or ""
            ).strip()

        old_z2m_name = await hass.async_add_executor_job(
            _get_current_z2m_name
        )

        if (
            old_z2m_name
            and new_z2m_name
            and old_z2m_name != new_z2m_name
        ):
            try:
                await mqtt.async_publish(
                    hass,
                    "zigbee2mqtt/bridge/request/device/rename",
                    json.dumps(
                        {
                            "from": old_z2m_name,
                            "to": new_z2m_name,
                        }
                    ),
                    qos=0,
                    retain=False,
                )

                _LOGGER.info(
                    "EyZEE: Zigbee2MQTT rename requested: %s -> %s",
                    old_z2m_name,
                    new_z2m_name,
                )

            except Exception as err:
                raise HomeAssistantError(
                    f"Zigbee2MQTT rename failed: {err}"
                ) from err

        def _update_registry():
            data = _read_device_registry()
            devices = data.setdefault("devices", {})
            device = devices.get(registry_id)

            if not isinstance(device, dict):
                raise HomeAssistantError(f"Registered device not found: {registry_id}")

            z2m = device.get("z2m")

            if (
                isinstance(z2m, dict)
                and old_z2m_name
                and new_z2m_name
            ):
                z2m["friendly_name"] = new_z2m_name

            now = datetime.now().astimezone().isoformat()

            if room_name:
                device["room"] = _slugify(room_name)
                device["area_label"] = room_name

            device["display_label"] = device_name
            device["name_label"] = device_name
            device["device_name"] = _slugify(device_name)

            meta = device.setdefault("meta", {})
            if isinstance(meta, dict):
                meta["updated"] = now

            controls = device.get("controls", []) or []

            if isinstance(controls, list):
                valid_controls = [
                    control
                    for control in controls
                    if isinstance(control, dict)
                ]

                for control in valid_controls:
                    idx = control.get("index")

                    if len(valid_controls) == 1:
                        # A single-control device uses Device Name
                        # for both the device and its sole control.
                        name = device_name
                    elif idx in control_names:
                        name = control_names[idx]
                    else:
                        continue

                    control["name"] = name
                    control["name_slug"] = _slugify(name)

            devices[registry_id] = device
            _write_device_registry(data)

        await hass.async_add_executor_job(_update_registry)

        # Rebuild room dashboards using the updated room and names.
        try:
            await hass.services.async_call(
                DOMAIN,
                "build_room_views",
                {},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE: failed to rebuild room views "
                "after device rename: %s",
                err,
            )

        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_registered_devices",
                {},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.warning("EyZEE: failed to refresh registered devices after name update: %s", e)

        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_multiway_dropdowns",
                {},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.warning("EyZEE: failed to refresh multiway dropdowns after name update: %s", e)

        hass.states.async_set(
            "sensor.eyzee_rename_device_status",
            "✅ Names updated successfully",
            {
                "friendly_name": "EyZEE Rename Device Status",
                "device": device_name,
                "room": room_name,
            },
        )

        await _set_status(f"Updated registered device names: {device_name}", None)
        await _notify(
            "EyZEE Device Updated",
            (
                f"✅ Device updated successfully\n\n"
                f"Room: {room_name}\n"
                f"Device: {device_name}"
            ),
            "eyzee_device_updated",
        )
        return True

    # -----------------------------
    # Service: Rename room label
    # -----------------------------
    async def handle_rename_room(call: ServiceCall):
        room_slug = _slugify(call.data.get("room") or "")
        new_label = str(call.data.get("new_label") or "").strip()
        confirm = call.data.get("confirm")

        if confirm is not True:
            raise HomeAssistantError("Confirmation required: set confirm: true")

        if not room_slug or room_slug in ("none", "unknown", "unavailable"):
            raise HomeAssistantError("room is required")

        if not new_label:
            raise HomeAssistantError("new_label is required")

        def _rename():
            model = _read_yaml_file(_path(ROOMS_YAML)) or {}
            model = _ensure_min_rooms_model(model)

            rooms = model.get("rooms") or {}

            if room_slug not in rooms:
                raise HomeAssistantError(f"Room not found: {room_slug}")

            backup = _backup_rooms_yaml()

            room = rooms.get(room_slug)
            if not isinstance(room, dict):
                room = {}

            old_label = room.get("label") or _label_from_slug(room_slug)
            room["label"] = new_label
            rooms[room_slug] = room
            model["rooms"] = rooms

            _write_yaml(_path(ROOMS_YAML), model)

            return backup, old_label, new_label

        backup, old_label, renamed_label = await hass.async_add_executor_job(_rename)

        try:
            await handle_populate_room_dropdown(
                type("obj", (), {"data": {"dropdown_entity": "input_select.eyzee_wizard_room"}})
            )
        except Exception:
            pass

        await handle_generate(call)

        await _notify(
            "EyZEE Room Renamed",
            (
                f"✅ Room renamed.\n\n"
                f"Room ID: {room_slug}\n"
                f"Old name: {old_label}\n"
                f"New name: {renamed_label}\n"
                f"Backup: {backup or 'No previous rooms file'}"
            ),
            "eyzee_room_renamed",
        )

        return True

    hass.services.async_register(
        DOMAIN,
        "bind_virtual_multiway",
        handle_bind_virtual_multiway,
        schema=vol.Schema(
            {
                vol.Optional("master", default=""): cv.string,
                vol.Optional("slave", default=""): cv.string,
                vol.Required("confirm"): cv.boolean,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "unbind_virtual_multiway",
        handle_unbind_virtual_multiway,
        schema=vol.Schema(
            {
                vol.Optional("master", default=""): cv.string,
                vol.Optional("slave", default=""): cv.string,
                vol.Required("confirm"): cv.boolean,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "populate_z2m_dropdown",
        handle_populate_z2m_dropdown,
        schema=vol.Schema(
            {
                vol.Optional("dropdown_entity", default="input_select.z2m_device_friendly_name"): cv.entity_id,
                vol.Optional("base_topic", default="zigbee2mqtt"): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "populate_room_dropdown",
        handle_populate_room_dropdown,
        schema=vol.Schema({vol.Optional("dropdown_entity", default="input_select.eyzee_wizard_room"): cv.entity_id}),
    )

    hass.services.async_register(
        DOMAIN,
        "discover_eyzee_devices",
        handle_discover_devices,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "populate_registered_devices",
        handle_populate_registered_devices,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "load_registered_device",
        handle_load_registered_device,
        schema=vol.Schema(
            {
                vol.Optional("registry_id", default=""): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "update_registered_device_names",
        handle_update_registered_device_names,
        schema=vol.Schema(
            {
                vol.Optional("registry_id", default=""): cv.string,
                vol.Optional("device_name", default=""): cv.string,
                vol.Optional("room_name", default=""): cv.string,
                vol.Optional("control_1_name", default=""): cv.string,
                vol.Optional("control_2_name", default=""): cv.string,
                vol.Optional("control_3_name", default=""): cv.string,
                vol.Optional("control_4_name", default=""): cv.string,
                vol.Optional("control_5_name", default=""): cv.string,
                vol.Optional("control_6_name", default=""): cv.string,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "discover_devices",
        handle_discover_devices,
        schema=vol.Schema({}),
    )

    hass.services.async_register(
        DOMAIN,
        "identify_device",
        handle_identify_device,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
                vol.Optional("duration", default=2): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=0.5, max=10),
                ),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "add_device",
        handle_add_device,
        schema=vol.Schema(
            {
                vol.Optional("room", default=""): cv.string,
                vol.Optional("device_type", default=""): cv.string,
                vol.Optional("device_name", default=""): cv.string,
                vol.Optional("z2m_from", default=""): cv.string,
                vol.Optional("custom_friendly_name", default=""): cv.string,
                vol.Optional("confirm_rename", default=False): cv.boolean,
            }
        ),
    )

    # Register external module services
    async_register_refresh_wizard_data_service(hass)
    async_register_populate_multiway_dropdowns_service(hass)

    await _set_status(
        True,
        None,
        {
            "services": "registered",
            "registered_services": [
                "generate",
                "build_house",
                "clear_rooms",
                "restore_rooms_backup",
                "populate_room_dropdown",
                "populate_z2m_dropdown",
                "discover_devices",
                "identify_device",
                "add_device",
                "bind_virtual_multiway",
                "unbind_virtual_multiway",
            ],
        },
    )

    # -----------------------------
    # Refresh House Builder data after Home Assistant starts
    # -----------------------------
    async def _refresh_house_builder_on_start(event):
        """Populate House Builder room data after HA has fully started."""

        try:
            await handle_generate(
                type("obj", (), {"data": {}})()
            )

            _LOGGER.info(
                "EyZEE: House Builder data refreshed at startup"
            )

        except Exception as err:
            _LOGGER.warning(
                "EyZEE: Could not refresh House Builder data at startup: %s",
                err,
            )

    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STARTED,
        _refresh_house_builder_on_start,
    )

    _LOGGER.info("EyZEE Dashboard services registered successfully")
    return True


async def async_setup_entry(hass: HomeAssistant, entry) -> bool:
    """Set up EyZEE Dashboard from a config entry."""
    return await async_setup(hass, {})
