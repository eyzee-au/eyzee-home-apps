"""Add a custom room to EyZEE Home."""

from __future__ import annotations

import re
import yaml
from pathlib import Path
from homeassistant.core import HomeAssistant, ServiceCall

ROOMS_FILE = Path("/config/eyzee/state/rooms.yaml")
CUSTOM_ROOM_HELPER = "input_text.eyzee_custom_room_name"


def _slugify_room_name(name: str) -> str:
    """Convert room name to safe internal key."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def _read_rooms() -> dict:
    """Read rooms.yaml."""
    if not ROOMS_FILE.exists():
        return {"rooms": {}}

    with ROOMS_FILE.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if "rooms" not in data or data["rooms"] is None:
        data["rooms"] = {}

    return data


def _write_rooms(data: dict) -> None:
    """Write rooms.yaml."""
    ROOMS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with ROOMS_FILE.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            data,
            file,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

async def async_add_custom_room(
    hass: HomeAssistant,
    call: ServiceCall,
) -> None:
    """Add a custom room and select it for device setup."""

    dropdown_entity = str(
        call.data.get("dropdown_entity")
        or "input_select.eyzee_wizard_room"
    ).strip()

    allowed_dropdowns = {
        "input_select.eyzee_wizard_room",
        "input_select.eyzee_registered_room",
    }

    if dropdown_entity not in allowed_dropdowns:
        raise ValueError(
            f"Unsupported room dropdown: {dropdown_entity}"
        )

    raw_name = hass.states.get(CUSTOM_ROOM_HELPER)

    if raw_name is None:
        raise ValueError(
            f"Missing helper: {CUSTOM_ROOM_HELPER}"
        )

    display_name = raw_name.state.strip()

    if not display_name:
        raise ValueError("Custom room name is empty.")

    room_key = _slugify_room_name(display_name)

    if not room_key:
        raise ValueError("Custom room name is not valid.")

    def _add_room() -> None:
        data = _read_rooms()
        rooms = data.setdefault("rooms", {})

        if room_key not in rooms:
            rooms[room_key] = {
                "label": display_name,
                "icon": "mdi:door",
                "floor": "One",
                "group": "Other",
                "features": ["lights"],
                "custom": True,
            }

            _write_rooms(data)

    await hass.async_add_executor_job(_add_room)

    # Clear the custom-room name only after it has been saved.
    await hass.services.async_call(
        "input_text",
        "set_value",
        {
            "entity_id": CUSTOM_ROOM_HELPER,
            "value": "",
        },
        blocking=True,
    )

    # Refresh the room dropdown before selecting the new room.
    await hass.services.async_call(
        "eyzee_dashboard",
        "populate_room_dropdown",
        {
            "dropdown_entity": dropdown_entity,
        },
        blocking=True,
    )

    # Automatically select the new room for the current device.
    await hass.services.async_call(
        "input_select",
        "select_option",
        {
            "entity_id": dropdown_entity,
            "option": room_key,
        },
        blocking=True,
    )

    # Refresh EyZEE room information.
    await hass.services.async_call(
        "eyzee_dashboard",
        "generate",
        {},
        blocking=True,
    )
