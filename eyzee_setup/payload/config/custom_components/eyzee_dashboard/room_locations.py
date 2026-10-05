"""Room-location services for EyZEE Home."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

import voluptuous as vol
import yaml

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError


DOMAIN = "eyzee_dashboard"

ROOMS_YAML = Path("/config/eyzee/state/rooms.yaml")
ROOM_HELPER = "input_select.eyzee_room_for_location"
LOCATION_HELPER = "input_select.eyzee_room_location"
FLOORS_HELPER = "input_select.eyzee_floors"
STATUS_ENTITY = "sensor.eyzee_room_location_status"

FLOOR_LOCATIONS = [
    ("One", "Ground Floor"),
    ("Two", "First Floor"),
    ("Three", "Second Floor"),
    ("Four", "Third Floor"),
    ("Five", "Fourth Floor"),
]

DEFAULT_GROUPS = {
    "kitchen": "Living",
    "dining": "Living",
    "entrance": "Ancillary",
    "hallway": "Ancillary",
    "living": "Living",
    "bedroom": "Bedrooms",
    "bathroom": "Bathrooms",
    "ensuite": "Ensuite",
    "media": "Media",
    "garage": "Utility",
    "laundry": "Utility",
    "mud_room": "Utility",
    "study": "Study",
    "office": "Office",
}


def _read_rooms() -> dict:
    if not ROOMS_YAML.exists():
        return {"version": 1, "rooms": {}}

    with ROOMS_YAML.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("version", 1)
    data.setdefault("rooms", {})
    return data


def _write_rooms(data: dict) -> None:
    ROOMS_YAML.parent.mkdir(parents=True, exist_ok=True)

    if ROOMS_YAML.exists():
        backup = ROOMS_YAML.with_name(
            "rooms.before-location-change.yaml"
        )
        shutil.copy2(ROOMS_YAML, backup)

    temporary = ROOMS_YAML.with_suffix(".yaml.tmp")

    with temporary.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            data,
            file,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    temporary.replace(ROOMS_YAML)


def _helper_state(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    return state.state.strip() if state is not None else ""


def _find_room(rooms: dict, selected: str) -> tuple[str, dict]:
    for slug, room in rooms.items():
        if not isinstance(room, dict):
            continue

        label = room.get("label") or slug.replace("_", " ").title()

        if selected in {slug, label}:
            return slug, room

    raise HomeAssistantError(
        f"Room '{selected}' could not be found. Refresh the room list."
    )


def _current_location(room: dict) -> str:
    if str(room.get("group") or "").lower() == "outdoor":
        return "Outdoor Areas"

    internal_floor = str(room.get("floor") or "One")

    for stored, displayed in FLOOR_LOCATIONS:
        if internal_floor.lower() in {
            stored.lower(),
            displayed.lower(),
        }:
            return displayed

    return "Ground Floor"


def _default_group(slug: str, room: dict) -> str:
    if room.get("custom") is True:
        return "Other"

    for prefix, group in DEFAULT_GROUPS.items():
        if slug == prefix or slug.startswith(f"{prefix}_"):
            return group

    return "Other"


def _set_status(
    hass: HomeAssistant,
    state: str,
    message: str,
    *,
    room: str = "",
    location: str = "",
) -> str:
    updated = datetime.now().isoformat()

    hass.states.async_set(
        STATUS_ENTITY,
        state,
        {
            "friendly_name": "EyZEE Room Location Status",
            "message": message,
            "room": room,
            "location": location,
            "updated": updated,
        },
    )

    return updated


def _clear_success_later(hass: HomeAssistant, updated: str) -> None:
    def _clear() -> None:
        current = hass.states.get(STATUS_ENTITY)

        if (
            current is not None
            and current.state == "success"
            and current.attributes.get("updated") == updated
        ):
            _set_status(hass, "idle", "")

    hass.loop.call_later(10, _clear)


async def _set_options(
    hass: HomeAssistant,
    entity_id: str,
    options: list[str],
) -> None:
    await hass.services.async_call(
        "input_select",
        "set_options",
        {
            "entity_id": entity_id,
            "options": options,
        },
        blocking=True,
    )


async def _select_option(
    hass: HomeAssistant,
    entity_id: str,
    option: str,
) -> None:
    await hass.services.async_call(
        "input_select",
        "select_option",
        {
            "entity_id": entity_id,
            "option": option,
        },
        blocking=True,
    )


def async_register_room_location_services(
    hass: HomeAssistant,
) -> None:
    """Register services used by the Set Room Locations screen."""

    async def handle_populate(
        call: ServiceCall,
    ) -> None:
        data = await hass.async_add_executor_job(_read_rooms)
        rooms = data.get("rooms", {}) or {}

        room_labels = sorted(
            [
                room.get("label")
                or slug.replace("_", " ").title()
                for slug, room in rooms.items()
                if isinstance(room, dict)
            ],
            key=str.lower,
        )

        floor_count_text = _helper_state(hass, FLOORS_HELPER)

        try:
            floor_count = int(float(floor_count_text or "1"))
        except ValueError:
            floor_count = 1

        floor_count = max(1, min(floor_count, len(FLOOR_LOCATIONS)))

        # Do not hide a floor already used by an existing room.
        used_floor_count = 1
        stored_floors = [item[0] for item in FLOOR_LOCATIONS]

        for room in rooms.values():
            if not isinstance(room, dict):
                continue

            floor = str(room.get("floor") or "One")

            if floor in stored_floors:
                used_floor_count = max(
                    used_floor_count,
                    stored_floors.index(floor) + 1,
                )

        floor_count = max(floor_count, used_floor_count)
        locations = [
            displayed
            for _, displayed in FLOOR_LOCATIONS[:floor_count]
        ]
        locations.append("Outdoor Areas")

        await _set_options(
            hass,
            ROOM_HELPER,
            ["none", *room_labels],
        )
        await _set_options(
            hass,
            LOCATION_HELPER,
            locations,
        )

        _set_status(
            hass,
            "ready",
            "Select a room and load its current location.",
        )

    async def handle_load(
        call: ServiceCall,
    ) -> None:
        selected = _helper_state(hass, ROOM_HELPER)

        if selected.lower() in {"", "none", "unknown", "unavailable"}:
            raise HomeAssistantError("Select a room first.")

        data = await hass.async_add_executor_job(_read_rooms)
        _, room = _find_room(data.get("rooms", {}) or {}, selected)
        location = _current_location(room)

        await _select_option(
            hass,
            LOCATION_HELPER,
            location,
        )

        _set_status(
            hass,
            "ready",
            f"{selected} is currently in {location}.",
            room=selected,
            location=location,
        )

    async def handle_save(
        call: ServiceCall,
    ) -> None:
        selected = _helper_state(hass, ROOM_HELPER)
        location = _helper_state(hass, LOCATION_HELPER)

        try:
            if selected.lower() in {
                "",
                "none",
                "unknown",
                "unavailable",
            }:
                raise HomeAssistantError("Select a room first.")

            location_map = dict(
                (displayed, stored)
                for stored, displayed in FLOOR_LOCATIONS
            )

            if location not in {
                *location_map,
                "Outdoor Areas",
            }:
                raise HomeAssistantError("Select a valid location.")

            def _save() -> tuple[str, str]:
                data = _read_rooms()
                rooms = data.get("rooms", {}) or {}
                slug, room = _find_room(rooms, selected)

                if location == "Outdoor Areas":
                    room["group"] = "Outdoor"
                else:
                    room["floor"] = location_map[location]

                    if str(room.get("group") or "").lower() == "outdoor":
                        room["group"] = _default_group(slug, room)

                rooms[slug] = room
                data["rooms"] = rooms
                _write_rooms(data)
                return slug, room.get("label") or selected

            _, label = await hass.async_add_executor_job(_save)

            # Refresh the Current Rooms sensor.
            await hass.services.async_call(
                DOMAIN,
                "generate",
                {},
                blocking=True,
            )

            # Rebuild the level-grouped Rooms dashboard last.
            await hass.services.async_call(
                DOMAIN,
                "build_room_views",
                {},
                blocking=True,
            )

            updated = _set_status(
                hass,
                "success",
                f"{label} has been moved to {location}.",
                room=label,
                location=location,
            )
            _clear_success_later(hass, updated)

        except Exception as error:
            _set_status(
                hass,
                "error",
                f"{type(error).__name__}: {error}",
                room=selected,
                location=location,
            )
            raise

    hass.services.async_register(
        DOMAIN,
        "populate_room_location_dropdowns",
        handle_populate,
        schema=vol.Schema({}),
    )
    hass.services.async_register(
        DOMAIN,
        "load_room_location",
        handle_load,
        schema=vol.Schema({}),
    )
    hass.services.async_register(
        DOMAIN,
        "save_room_location",
        handle_save,
        schema=vol.Schema({}),
    )
