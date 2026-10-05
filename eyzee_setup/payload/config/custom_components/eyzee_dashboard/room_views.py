import logging
import yaml

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from .eyzee_settings import get_aura_rgb

_LOGGER = logging.getLogger(__name__)

DOMAIN = "eyzee_dashboard"

DEVICE_REGISTRY_YAML = "/config/eyzee/state/device_registry.yaml"
LIGHTING_GROUPS_YAML = "/config/eyzee/state/lighting_groups.yaml"
ROOMS_YAML = "/config/eyzee/state/rooms.yaml"
ROOM_DASHBOARD_YAML = "/config/eyzee/ui/eyzee-room.yaml"
BINDINGS_YAML = "/config/eyzee/state/bindings.yaml"


CONTROL_ICONS = {
    "light": "mdi:lightbulb",
    "switch": "mdi:light-switch",
    "fan": "mdi:fan",
    "cover": "mdi:blinds",
    "lock": "mdi:lock",
    "sensor": "mdi:motion-sensor",
    "binary_sensor": "mdi:motion-sensor",
}


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    out = ""
    prev = False

    for ch in value:
        if ch.isalnum():
            out += ch
            prev = False
        else:
            if not prev:
                out += "_"
                prev = True

    return out.strip("_") or "unknown"


FLOOR_SECTIONS = {
    "one": (0, "Ground Floor"),
    "1": (0, "Ground Floor"),
    "ground": (0, "Ground Floor"),
    "ground floor": (0, "Ground Floor"),
    "two": (1, "First Floor"),
    "2": (1, "First Floor"),
    "first": (1, "First Floor"),
    "first floor": (1, "First Floor"),
    "three": (2, "Second Floor"),
    "3": (2, "Second Floor"),
    "second": (2, "Second Floor"),
    "second floor": (2, "Second Floor"),
    "four": (3, "Third Floor"),
    "4": (3, "Third Floor"),
    "third": (3, "Third Floor"),
    "third floor": (3, "Third Floor"),
    "five": (4, "Fourth Floor"),
    "5": (4, "Fourth Floor"),
    "fourth": (4, "Fourth Floor"),
    "fourth floor": (4, "Fourth Floor"),
}


def _room_section(room: dict) -> tuple[int, str, str]:
    """Return the ordered display section for one room."""

    group = str(room.get("group") or "").strip().lower()

    if group == "outdoor":
        return (100, "Outdoor Areas", "mdi:tree")

    floor = str(room.get("floor") or "One").strip()
    order, label = FLOOR_SECTIONS.get(
        floor.lower(),
        (90, floor or "Other Areas"),
    )

    return (order, label, "mdi:stairs")


def _read_yaml(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        _LOGGER.warning("EyZEE room views: failed to read %s: %s", path, e)
        data = {}

    return data if isinstance(data, dict) else {}


def _write_yaml(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if entity_id and "." in entity_id else ""


def _control_card(control: dict, fallback_name: str = "Control") -> dict | None:
    entity_id = control.get("entity_id")

    if not entity_id:
        return None

    card_name = fallback_name or control.get("name") or "Control"
    domain = _domain(entity_id)
    icon = CONTROL_ICONS.get(domain, "mdi:gesture-tap-button")

    return {
        "type": "tile",
        "entity": entity_id,
        "name": card_name,
        "icon": icon,
        "vertical": True,
    }

def _compact_control_card(
    control: dict,
    fallback_name: str = "Control",
) -> dict | None:
    """Compact tile used on the More Controls page."""

    entity_id = control.get("entity_id")

    if not entity_id:
        return None

    card_name = (
        fallback_name
        or control.get("name")
        or "Control"
    )

    domain = _domain(entity_id)
    icon = CONTROL_ICONS.get(
        domain,
        "mdi:gesture-tap-button",
    )

    return {
        "type": "tile",
        "entity": entity_id,
        "name": card_name,
        "icon": icon,
        "vertical": False,
        "tap_action": {
            "action": "toggle",
        },
        "hold_action": {
            "action": "more-info",
        },
        "icon_tap_action": {
            "action": "toggle",
        },
    }



def _group_card(group_id: str, group: dict) -> dict:
    name = group.get("name") or group_id
    entity = group.get("z2m_entity")

    if entity:
        return {
            "type": "tile",
            "entity": entity,
            "name": name,
            "icon": "mdi:lightbulb-group",
            "vertical": False,

            # Full-width card on a Sections dashboard.
            "grid_options": {
                "columns": 12,
            },

            # Tap anywhere on the tile to toggle the group.
            "tap_action": {
                "action": "toggle",
            },

            # Hold still gives access to HA's full light controls.
            "hold_action": {
                "action": "more-info",
            },

            "icon_tap_action": {
                "action": "toggle",
            },
        }

def _scene_button(name: str, icon: str) -> dict:
    return {
        "type": "button",
        "name": name,
        "icon": icon,
        "tap_action": {
            "action": "none",
        },
    }

def _brightness_button(
    entity_id: str,
    name: str,
    brightness_pct: int,
) -> dict:
    return {
        "type": "button",
        "name": name,
        "icon": "mdi:brightness-6",
        "tap_action": {
            "action": "perform-action",
            "perform_action": "light.turn_on",
            "data": {
                "entity_id": entity_id,
                "brightness_pct": brightness_pct,
            },
        },
    }

def _colour_preset_button(
    entity_id: str,
    name: str,
    *,
    color_temp_kelvin: int | None = None,
    rgb_color: list[int] | None = None,
) -> dict:
    data = {
        "entity_id": entity_id,
    }

    if color_temp_kelvin is not None:
        data["color_temp_kelvin"] = color_temp_kelvin

    if rgb_color is not None:
        data["rgb_color"] = rgb_color

    return {
        "type": "button",
        "name": name,
        "icon": "mdi:palette",
        "tap_action": {
            "action": "perform-action",
            "perform_action": "light.turn_on",
            "data": data,
        },
    }

def _future_nav_button(name: str, icon: str, path: str) -> dict:
    return {
        "type": "button",
        "name": name,
        "icon": icon,
        "tap_action": {
            "action": "navigate",
            "navigation_path": path,
        },
    }


def _build_room_dashboard() -> dict:
    registry = _read_yaml(DEVICE_REGISTRY_YAML)
    lighting = _read_yaml(LIGHTING_GROUPS_YAML)
    bindings_data = _read_yaml(BINDINGS_YAML)
    rooms_data = _read_yaml(ROOMS_YAML)

    devices = registry.get("devices", {}) or {}
    groups = lighting.get("groups", {}) or {}
    bindings = bindings_data.get("bindings", []) or []
    configured_rooms = rooms_data.get("rooms", {}) or {}

    binding_index = {}

    rooms = {}

    # Whole-home lookup used to resolve lighting-group members,
    # including lights physically registered in another room.
    control_items_by_entity = {}

    # ---------------------------------------------------------
    # rooms.yaml is the source of truth for room existence.
    # Devices, groups and bindings are layered onto each room.
    # ---------------------------------------------------------
    for room_slug, room in configured_rooms.items():
        if not isinstance(room, dict):
            continue

        room_label = (
            room.get("label")
            or room_slug.replace("_", " ").title()
        )

        rooms[room_slug] = {
            "label": room_label,
            "icon": room.get("icon") or "mdi:door-open",
            "floor": room.get("floor") or "One",
            "group": room.get("group") or "Other",
            "controls": [],
            "lights": [],
            "group_member_lights": [],
            "switches": [],
            "other": [],
            "groups": [],
        }

    if isinstance(bindings, list):
        for binding in bindings:
            if not isinstance(binding, dict):
                continue

            source = binding.get("source") or {}

            source_device = source.get("device")
            source_control = source.get("control")

            if not source_device:
                continue

            try:
                source_control = int(source_control)
            except (TypeError, ValueError):
                continue

            binding_index[
                (str(source_device), source_control)
            ] = binding

    for registry_id, device in devices.items():
        if not isinstance(device, dict):
            continue

        room_slug = device.get("room") or "unknown"

        # rooms.yaml is authoritative.
        # A device must not recreate a room that has been removed.
        if room_slug not in rooms:
            continue

        device_name = device.get("display_label") or device.get("device_name") or registry_id
        device_type = device.get("device_type") or "other"
        controls = device.get("controls", []) or []

        if not isinstance(controls, list):
            continue

        for control in controls:
            if not isinstance(control, dict):
                continue

            entity_id = control.get("entity_id")
            if not entity_id:
                continue

            domain = _domain(entity_id)

            item = {
                "registry_id": registry_id,
                "device_name": device_name,
                "device_type": device_type,
                "control": control,
            }
            
            control_index = control.get("index")

            try:
                control_index_int = int(control_index)
            except (TypeError, ValueError):
                control_index_int = None

            binding = None

            if control_index_int is not None:
                binding = binding_index.get(
                    (
                        registry_id,
                        control_index_int,
                    )
                )

            item["binding"] = binding

            # -------------------------------------------------
            # Friendly role names for fan/light controllers
            # -------------------------------------------------
            entity_lower = str(entity_id).lower()

            if entity_lower.endswith("_light"):
                display_name = "Light"

            elif "fan_low" in entity_lower:
                display_name = "Low"

            elif "fan_medium" in entity_lower:
                display_name = "Medium"

            elif "fan_high" in entity_lower:
                display_name = "High"

            else:
                display_name = (
                    control.get("name")
                    or device_name
                )

            item["display_name"] = display_name

            # Keep every registered control available by entity ID.
            # Lighting groups can contain lights from multiple rooms.
            control_items_by_entity[str(entity_id)] = item

            if domain == "light":
                rooms[room_slug]["lights"].append(item)
            elif domain == "switch":
                rooms[room_slug]["switches"].append(item)
            else:
                rooms[room_slug]["other"].append(item)

    for group_id, group in groups.items():
        if not isinstance(group, dict):
            continue

        room_slug = group.get("room") or "unknown"

        # rooms.yaml is authoritative.
        # A lighting group must not recreate a removed room.
        if room_slug not in rooms:
            continue

        rooms[room_slug]["groups"].append((group_id, group))

        # Resolve this group's members from the whole-home
        # control lookup. A member may belong to another room.
        members = group.get("members", []) or []

        if isinstance(members, list):
            existing_entities = {
                str(
                    item.get("control", {}).get("entity_id")
                )
                for item in rooms[room_slug][
                    "group_member_lights"
                ]
                if isinstance(item, dict)
            }

            for member_entity in members:
                member_entity = str(member_entity)
                member_item = control_items_by_entity.get(
                    member_entity
                )

                if not isinstance(member_item, dict):
                    continue

                if _domain(member_entity) != "light":
                    continue

                if member_entity in existing_entities:
                    continue

                rooms[room_slug][
                    "group_member_lights"
                ].append(member_item)

                existing_entities.add(member_entity)

    views = []

    if not rooms:
        views.append(
            {
                "title": "Rooms",
                "path": "rooms",
                "icon": "mdi:home",
                "type": "sections",
                "sections": [
                    {
                        "type": "grid",
                        "cards": [
                            {
                                "type": "heading",
                                "heading": "EyZEE Rooms",
                                "heading_style": "title",
                                "icon": "mdi:home",
                            },
                            {
                                "type": "markdown",
                                "content": "No devices or groups have been added yet.",
                            },
                        ],
                    }
                ],
            }
        )

        return {
            "title": "EyZEE Rooms",
            "views": views,
        }

    # ---------------------------------------------------------
    # Main room index
    # ---------------------------------------------------------
    room_buttons_by_section = {}

    for room_slug, room in sorted(
        rooms.items(),
        key=lambda item: item[1]["label"].lower(),
    ):
        section_order, section_label, section_icon = (
            _room_section(room)
        )
        section_key = (
            section_order,
            section_label,
            section_icon,
        )

        room_buttons_by_section.setdefault(
            section_key,
            [],
        ).append(
            {
                "type": "button",
                "name": room["label"],
                "icon": room["icon"],
                "show_state": False,
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": (
                        f"/eyzee-rooms/{_slugify(room_slug)}"
                    ),
                },
                "card_mod": {
                    "style": (
                        "ha-card { min-height:110px; "
                        "border-radius:16px; }\n"
                        "ha-state-icon { color:#D6AD60 "
                        "!important; }"
                    ),
                },
            }
        )

    room_index_cards = [
        {
            "type": "heading",
            "heading": "View All Rooms",
            "heading_style": "title",
            "icon": "mdi:floor-plan",
        },
        {
            "type": "heading",
            "heading": "Choose a room to control",
            "heading_style": "subtitle",
        },
    ]

    for section_key in sorted(
        room_buttons_by_section,
        key=lambda item: (item[0], item[1].lower()),
    ):
        _, section_label, section_icon = section_key

        room_index_cards.extend(
            [
                {
                    "type": "heading",
                    "heading": section_label,
                    "heading_style": "subtitle",
                    "icon": section_icon,
                },
                {
                    "type": "grid",
                    "columns": 2,
                    "square": False,
                    "cards": room_buttons_by_section[
                        section_key
                    ],
                },
            ]
        )

    room_index_cards.extend(
        [
            {
                "type": "grid",
                "columns": 3,
                "square": False,
                "cards": [
                    {
                        "type": "button",
                        "name": "Back",
                        "icon": "mdi:arrow-left",
                        "show_state": False,
                        "tap_action": {
                            "action": "navigate",
                            "navigation_path": (
                                "/eyzee-main-menu/rooms"
                            ),
                        },
                    },
                    {
                        "type": "button",
                        "name": "Home",
                        "icon": "mdi:home-heart",
                        "show_state": False,
                        "tap_action": {
                            "action": "navigate",
                            "navigation_path": (
                                "/eyzee-main-menu/home"
                            ),
                        },
                    },
                    {
                        "type": "button",
                        "name": "Help",
                        "icon": "mdi:help-circle-outline",
                        "show_state": False,
                        "tap_action": {
                            "action": "url",
                            "url_path": (
                                "https://eyzee.au/"
                                "eyzee-home/support/"
                            ),
                        },
                    },
                ],
            },
            {
                "type": "markdown",
                "content": (
                    "<div style=\"color:var(--secondary-"
                    "text-color); font-size:14px; "
                    "font-weight:600; padding:2px 8px;\">"
                    "EyZEE® • Making Smart Easy™</div>"
                ),
                "card_mod": {
                    "style": (
                        "ha-card { background:transparent; "
                        "border:none; box-shadow:none; }"
                    ),
                },
            },
        ]
    )

    views.append(
        {
            "title": "Rooms",
            "path": "rooms",
            "icon": "mdi:floor-plan",
            "type": "sections",
            "max_columns": 1,
            "sections": [
                {
                    "type": "grid",
                    "cards": room_index_cards,
                }
            ],
        }
    )

    for room_slug, room in sorted(rooms.items(), key=lambda item: item[1]["label"].lower()):
        room_path = _slugify(room_slug)

        cards = [
            {
                "type": "heading",
                "heading": room["label"],
                "heading_style": "title",
                "icon": "mdi:home",
            },
        ]

        # -----------------------------------------------------
        # Primary room lighting
        #
        # Lighting groups are the everyday room-level control.
        # Keep track of their members so grouped lights can be
        # moved off the main screen into More Controls.
        # -----------------------------------------------------
        grouped_light_entities = set()
        group_entity = None

        if room["groups"]:
            cards.append(
                {
                    "type": "heading",
                    "heading": "Lighting",
                    "heading_style": "subtitle",
                    "icon": "mdi:lightbulb-group",
                }
            )

            for group_id, group in room["groups"]:
                members = group.get("members", []) or []

                if isinstance(members, list):
                    grouped_light_entities.update(
                        str(entity_id)
                        for entity_id in members
                        if entity_id
                    )

                cards.append(
                    _group_card(
                        group_id,
                        group,
                    )
                )

                group_entity = group.get("z2m_entity")

                if group_entity:
                    cards.append(
                        {
                            "type": "grid",
                            "columns": 4,
                            "square": False,
                            "cards": [
                                _brightness_button(
                                    group_entity,
                                    "Low",
                                    10,
                                ),
                                _brightness_button(
                                    group_entity,
                                    "Soft",
                                    35,
                                ),
                                _brightness_button(
                                    group_entity,
                                    "Bright",
                                    70,
                                ),
                                _brightness_button(
                                    group_entity,
                                    "Max",
                                    100,
                                ),
                            ],
                        }
                    )

                if group_entity:
                    cards.append(
                        {
                            "type": "grid",
                            "columns": 4,
                            "square": False,
                            "cards": [
                                _colour_preset_button(
                                    group_entity,
                                    "Warm",
                                    color_temp_kelvin=2700,
                                ),
                                _colour_preset_button(
                                    group_entity,
                                    "Natural",
                                    color_temp_kelvin=4000,
                                ),
                                _colour_preset_button(
                                    group_entity,
                                    "Cool",
                                    color_temp_kelvin=6000,
                                ),
                                _colour_preset_button(
                                    group_entity,
                                    "Aura",
                                    rgb_color=get_aura_rgb(),
                                ),
                            ],
                        }
                    )


        # Switch buttons
        if room["switches"]:
            cards.append(
                {
                    "type": "heading",
                    "heading": "Switch Buttons",
                    "heading_style": "subtitle",
                    "icon": "mdi:light-switch",
                }
            )

            def _switch_sort_key(item):
                name = str(
                    item.get("display_name") or ""
                ).strip().lower()

                priority = {
                    "light": 1,
                    "low": 2,
                    "medium": 3,
                    "high": 4,
                }

                return (
                    priority.get(name, 100),
                    name,
                )

            for item in sorted(
                room["switches"],
                key=_switch_sort_key,
            ):
                card = _control_card(
                    item["control"],
                    item["display_name"],
                )

                if card:
                    cards.append(card)

        # -----------------------------------------------------
        # Secondary / individual lights
        #
        # Group members are hidden from the main room screen.
        # Lights outside the primary lighting group remain
        # visible as separate everyday controls.
        # -----------------------------------------------------
        visible_individual_lights = []

        for item in room["lights"]:
            control = item.get("control") or {}
            entity_id = control.get("entity_id")

            if not entity_id:
                continue

            if entity_id in grouped_light_entities:
                continue

            visible_individual_lights.append(item)

        if visible_individual_lights:
            cards.append(
                {
                    "type": "heading",
                    "heading": "Other Lights",
                    "heading_style": "subtitle",
                    "icon": "mdi:lightbulb",
                }
            )

            for item in sorted(
                visible_individual_lights,
                key=lambda x: (
                    x["control"].get("name") or ""
                ).lower(),
            ):
                card = _control_card(
                    item["control"],
                    item["display_name"],
                )

                if card:
                    cards.append(card)

        # Other controls
        if room["other"]:
            cards.append(
                {
                    "type": "heading",
                    "heading": "Other Devices",
                    "heading_style": "subtitle",
                    "icon": "mdi:devices",
                }
            )

            for item in sorted(room["other"], key=lambda x: (x["control"].get("name") or "").lower()):
                card = _control_card(item["control"], item["display_name"])
                if card:
                    cards.append(card)

        # Future navigation placeholders
        cards.append(
            {
                "type": "heading",
                "heading": "More",
                "heading_style": "subtitle",
                "icon": "mdi:dots-horizontal-circle",
            }
        )

        more_cards = []

        if group_entity:
            more_cards.append(
                {
                    "type": "button",
                    "name": "All Off",
                    "icon": "mdi:power",
                    "tap_action": {
                        "action": "perform-action",
                        "perform_action": "light.turn_off",
                        "target": {
                            "entity_id": group_entity,
                        },
                    },
                }
            )

        more_cards.append(
            _future_nav_button(
                "More Controls",
                "mdi:tune",
                f"/eyzee-rooms/{room_path}-more-controls",
            )
        )

        cards.extend(more_cards)

        views.append(
            {
                "title": room["label"],
                "path": room_path,
                "icon": "mdi:home",
                "subview": True,
                "type": "sections",
                "sections": [
                    {
                        "type": "grid",
                        "cards": cards,
                    }
                ],
            }
        )

        # -----------------------------------------------------
        # More Controls pages
        # -----------------------------------------------------

        # Complete room-specific advanced controls.
        more_control_cards = [
            {
                "type": "heading",
                "heading": f"{room['label']} More Controls",
                "heading_style": "title",
                "icon": "mdi:tune",
            },
        ]

        # Lighting groups
        if room["groups"]:
            more_control_cards.append(
                {
                    "type": "heading",
                    "heading": "Lighting Groups",
                    "heading_style": "subtitle",
                    "icon": "mdi:lightbulb-group",
                }
            )

            for group_id, group in room["groups"]:
                more_control_cards.append(
                    _group_card(group_id, group)
                )

        # Include lights physically assigned to this room and lights
        # brought into the room through its lighting groups.
        advanced_light_items = []
        advanced_light_entities = set()

        for item in (
            room["lights"]
            + room["group_member_lights"]
        ):
            if not isinstance(item, dict):
                continue

            control = item.get("control") or {}
            entity_id = control.get("entity_id")

            if not entity_id:
                continue

            entity_id = str(entity_id)

            if entity_id in advanced_light_entities:
                continue

            advanced_light_entities.add(entity_id)
            advanced_light_items.append(item)

        if advanced_light_items:
            more_control_cards.append(
                {
                    "type": "heading",
                    "heading": "Individual Lights",
                    "heading_style": "subtitle",
                    "icon": "mdi:lightbulb-multiple",
                }
            )

            compact_light_cards = []

            for item in sorted(
                advanced_light_items,
                key=lambda x: (
                    x["control"].get("name") or ""
                ).lower(),
            ):
                card = _compact_control_card(
                    item["control"],
                    item["display_name"],
                )

                if card:
                    compact_light_cards.append(card)

            if compact_light_cards:
                more_control_cards.append(
                    {
                        "type": "grid",
                        "columns": 2,
                        "square": False,
                        "cards": compact_light_cards,
                    }
                )

        # Every named switch control.
        if room["switches"]:
            more_control_cards.append(
                {
                    "type": "heading",
                    "heading": "Switch Buttons",
                    "heading_style": "subtitle",
                    "icon": "mdi:light-switch",
                }
            )

            compact_switch_cards = []

            for item in sorted(
                room["switches"],
                key=lambda x: (
                    x.get("display_name") or ""
                ).lower(),
            ):
                card = _compact_control_card(
                    item["control"],
                    item["display_name"],
                )

                if card:
                    compact_switch_cards.append(card)

            if compact_switch_cards:
                more_control_cards.append(
                    {
                        "type": "grid",
                        "columns": 2,
                        "square": False,
                        "cards": compact_switch_cards,
                    }
                )

        # Other supported room devices.
        if room["other"]:
            more_control_cards.append(
                {
                    "type": "heading",
                    "heading": "Other Devices",
                    "heading_style": "subtitle",
                    "icon": "mdi:devices",
                }
            )

            for item in sorted(
                room["other"],
                key=lambda x: (
                    x["control"].get("name") or ""
                ).lower(),
            ):
                card = _control_card(
                    item["control"],
                    item["display_name"],
                )

                if card:
                    more_control_cards.append(card)

        more_control_cards.append(
            {
                "type": "button",
                "name": f"Back to {room['label']}",
                "icon": "mdi:arrow-left",
                "grid_options": {
                    "columns": 12,
                    "rows": 1,
                },
                "tap_action": {
                    "action": "navigate",
                    "navigation_path": (
                        f"/eyzee-rooms/{room_path}"
                    ),
                },
            }
        )

        views.append(
            {
                "title": f"{room['label']} More Controls",
                "path": f"{room_path}-more-controls",
                "icon": "mdi:tune",
                "subview": True,
                "type": "sections",
                "max_columns": 1,
                "sections": [
                    {
                        "type": "grid",
                        "cards": more_control_cards,
                    }
                ],
            }
        )

        # Other Devices
        for suffix, title, icon in (
            ("devices", "Other Devices", "mdi:devices"),
            ("settings", "Room Settings", "mdi:cog"),
        ):
            views.append(
                {
                    "title": f"{room['label']} {title}",
                    "path": f"{room_path}-{suffix}",
                    "icon": icon,
                    "subview": True,
                    "type": "sections",
                    "sections": [
                        {
                            "type": "grid",
                            "cards": [
                                {
                                    "type": "heading",
                                    "heading": f"{room['label']} {title}",
                                    "heading_style": "title",
                                    "icon": icon,
                                },
                                {
                                    "type": "markdown",
                                    "content": "Coming soon.",
                                },
                                {
                                    "type": "button",
                                    "name": f"Back to {room['label']}",
                                    "icon": "mdi:arrow-left",
                                    "tap_action": {
                                        "action": "navigate",
                                        "navigation_path": f"/eyzee-rooms/{room_path}",
                                    },
                                },
                            ],
                        }
                    ],
                }
            )

    return {
        "title": "EyZEE Rooms",
        "views": views,
    }


def async_register_room_view_services(hass: HomeAssistant):
    async def handle_build_room_views(call: ServiceCall):
        dashboard = await hass.async_add_executor_job(
            _build_room_dashboard
        )

        await hass.async_add_executor_job(
            _write_yaml,
            ROOM_DASHBOARD_YAML,
            dashboard,
        )

        hass.states.async_set(
            "sensor.eyzee_room_view_status",
            "✅ Room views rebuilt",
            {
                "friendly_name": "EyZEE Room View Status",
                "dashboard": ROOM_DASHBOARD_YAML,
            },
        )

        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_room_dropdown",
                {
                    "dropdown_entity": (
                        "input_select.eyzee_room_to_remove"
                    )
                },
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning(
                "EyZEE room views: could not refresh "
                "Room to Remove dropdown: %s",
                err,
            )

        return True

    hass.services.async_register(
        DOMAIN,
        "build_room_views",
        handle_build_room_views,
        schema=vol.Schema({}),
    )
