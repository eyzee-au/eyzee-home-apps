import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SWITCH_LIGHT_BINDINGS_YAML = "eyzee/state/switch_light_bindings.yaml"


def _normalize_entity_id(e: str) -> str:
    return (e or "").strip()


def _path(hass: HomeAssistant, rel: str) -> Path:
    return Path(hass.config.path(str(rel)))


def _read_yaml_file(path: Path):
    import yaml
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _write_yaml(path: Path, data):
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)


def _desired_from_state(state_str: str) -> Optional[bool]:
    if state_str == "on":
        return True
    if state_str == "off":
        return False
    return None


def _is_valid_switch(eid: str) -> bool:
    return eid.startswith("switch.")


def _is_valid_light(eid: str) -> bool:
    return eid.startswith("light.")


def _ensure_model(data) -> dict:
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("bindings", [])
    if not isinstance(data["bindings"], list):
        data["bindings"] = []
    return data


async def async_setup_switch_light_binding(hass: HomeAssistant) -> None:
    """Initialize runtime state + install listeners from YAML."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("switch_light", {})
    hass.data[DOMAIN]["switch_light"].setdefault("bindings", [])      # list of {switch, light}
    hass.data[DOMAIN]["switch_light"].setdefault("unsubs", [])        # unsubscribe callables
    hass.data[DOMAIN]["switch_light"].setdefault("last_ctx", {})      # entity_id -> ctx.id

    lock = hass.data[DOMAIN]["switch_light"].setdefault("lock", asyncio.Lock())

    def _read_bindings():
        path = _path(hass, SWITCH_LIGHT_BINDINGS_YAML)
        data = _ensure_model(_read_yaml_file(path))
        out = []
        for b in data.get("bindings", []):
            if not isinstance(b, dict):
                continue
            sw = _normalize_entity_id(b.get("switch"))
            lt = _normalize_entity_id(b.get("light"))
            if _is_valid_switch(sw) and _is_valid_light(lt):
                out.append({"switch": sw, "light": lt})
        return out

    async def _install_listeners():
        # clear old listeners
        for unsub in hass.data[DOMAIN]["switch_light"]["unsubs"]:
            try:
                unsub()
            except Exception:
                pass
        hass.data[DOMAIN]["switch_light"]["unsubs"] = []

        bindings = hass.data[DOMAIN]["switch_light"]["bindings"]

        if not bindings:
            return

        watched = sorted({b["switch"] for b in bindings})

        async def _set_light(light_entity: str, on: bool):
            svc = "turn_on" if on else "turn_off"
            ctx = hass.context
            await hass.services.async_call("light", svc, {"entity_id": light_entity}, blocking=False)
            hass.data[DOMAIN]["switch_light"]["last_ctx"][light_entity] = ctx.id

        def _is_our_own_change(event) -> bool:
            # If the light changed due to our own call, ignore to prevent loops
            ent = event.data.get("entity_id")
            ctx = event.context
            last = hass.data[DOMAIN]["switch_light"]["last_ctx"].get(ent)
            return ctx is not None and last is not None and ctx.id == last

        async def _on_state_change(event):
            # only respond to switch changes
            if _is_our_own_change(event):
                return

            ent = event.data.get("entity_id")
            new_state = event.data.get("new_state")
            if not new_state:
                return

            desired = _desired_from_state(new_state.state)
            if desired is None:
                return

            # Find all bindings for this switch
            for b in bindings:
                if b["switch"] != ent:
                    continue
                light_entity = b["light"]
                try:
                    await _set_light(light_entity, desired)
                except Exception as e:
                    _LOGGER.warning("EyZEE switch→light: failed setting %s from %s: %s", light_entity, ent, e)

        unsub = async_track_state_change_event(hass, watched, _on_state_change)
        hass.data[DOMAIN]["switch_light"]["unsubs"].append(unsub)

    async def _load_and_install():
        loaded = await hass.async_add_executor_job(_read_bindings)
        hass.data[DOMAIN]["switch_light"]["bindings"] = loaded
        await _install_listeners()

    # Load on startup
    hass.async_create_task(_load_and_install())

    # Store helpers in hass.data so service handlers can reuse them
    hass.data[DOMAIN]["switch_light"]["_install_listeners"] = _install_listeners
    hass.data[DOMAIN]["switch_light"]["_lock"] = lock


def async_register_switch_light_binding_services(hass: HomeAssistant) -> None:
    """Register bind/unbind services for switch→light binding."""
    lock: asyncio.Lock = hass.data[DOMAIN]["switch_light"]["_lock"]

    def _read_model():
        path = _path(hass, SWITCH_LIGHT_BINDINGS_YAML)
        return _ensure_model(_read_yaml_file(path))

    def _write_model(data):
        path = _path(hass, SWITCH_LIGHT_BINDINGS_YAML)
        _write_yaml(path, data)

    async def handle_bind_switch_to_light(call: ServiceCall):
        confirm = call.data.get("confirm") is True
        if not confirm:
            raise ValueError("Confirmation required: set confirm: true")

        sw = _normalize_entity_id(call.data.get("switch") or "")
        lt = _normalize_entity_id(call.data.get("light") or "")

        if not _is_valid_switch(sw):
            raise ValueError("switch must be a switch.* entity_id")
        if not _is_valid_light(lt):
            raise ValueError("light must be a light.* entity_id")
        if sw == lt:
            raise ValueError("switch and light cannot be the same entity")

        async with lock:
            data = await hass.async_add_executor_job(_read_model)

            # upsert (unique by switch+light)
            exists = False
            for b in data["bindings"]:
                if isinstance(b, dict) and b.get("switch") == sw and b.get("light") == lt:
                    exists = True
                    break
            if not exists:
                data["bindings"].append({"switch": sw, "light": lt, "created": datetime.now().isoformat()})

            await hass.async_add_executor_job(_write_model, data)

            # update runtime + reinstall listeners
            runtime = [{"switch": _normalize_entity_id(b.get("switch")), "light": _normalize_entity_id(b.get("light"))}
                       for b in data["bindings"] if isinstance(b, dict)]
            hass.data[DOMAIN]["switch_light"]["bindings"] = [
                b for b in runtime if _is_valid_switch(b["switch"]) and _is_valid_light(b["light"])
            ]
            await hass.data[DOMAIN]["switch_light"]["_install_listeners"]()

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "EyZEE Switch → Light Linked",
                "message": f"✅ Linked\n\nSWITCH: {sw}\nLIGHT: {lt}\n\nMode: ON/OFF follows switch",
                "notification_id": "eyzee_switch_light_linked",
            },
            blocking=False,
        )
        return True

    async def handle_unbind_switch_to_light(call: ServiceCall):
        confirm = call.data.get("confirm") is True
        if not confirm:
            raise ValueError("Confirmation required: set confirm: true")

        sw = _normalize_entity_id(call.data.get("switch") or "")
        lt = _normalize_entity_id(call.data.get("light") or "")

        if not sw and not lt:
            raise ValueError("Provide switch and/or light to unbind (at least one).")

        async with lock:
            data = await hass.async_add_executor_job(_read_model)

            new_bindings = []
            removed = 0
            for b in data["bindings"]:
                if not isinstance(b, dict):
                    continue
                bsw = _normalize_entity_id(b.get("switch"))
                blt = _normalize_entity_id(b.get("light"))

                match = True
                if sw:
                    match = match and (bsw == sw)
                if lt:
                    match = match and (blt == lt)

                if match:
                    removed += 1
                    continue

                new_bindings.append(b)

            data["bindings"] = new_bindings
            await hass.async_add_executor_job(_write_model, data)

            runtime = [{"switch": _normalize_entity_id(b.get("switch")), "light": _normalize_entity_id(b.get("light"))}
                       for b in data["bindings"] if isinstance(b, dict)]
            hass.data[DOMAIN]["switch_light"]["bindings"] = [
                b for b in runtime if _is_valid_switch(b["switch"]) and _is_valid_light(b["light"])
            ]
            await hass.data[DOMAIN]["switch_light"]["_install_listeners"]()

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "EyZEE Switch → Light Unlinked",
                "message": f"✅ Removed {removed} binding(s).\n\nFilter used:\nSWITCH: {sw or '(any)'}\nLIGHT: {lt or '(any)'}",
                "notification_id": "eyzee_switch_light_unlinked",
            },
            blocking=False,
        )
        return True

    hass.services.async_register(
        DOMAIN,
        "bind_switch_to_light",
        handle_bind_switch_to_light,
        schema=vol.Schema(
            {
                vol.Required("switch"): cv.entity_id,
                vol.Required("light"): cv.entity_id,
                vol.Required("confirm"): cv.boolean,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "unbind_switch_to_light",
        handle_unbind_switch_to_light,
        schema=vol.Schema(
            {
                vol.Optional("switch", default=""): cv.string,
                vol.Optional("light", default=""): cv.string,
                vol.Required("confirm"): cv.boolean,
            }
        ),
    )