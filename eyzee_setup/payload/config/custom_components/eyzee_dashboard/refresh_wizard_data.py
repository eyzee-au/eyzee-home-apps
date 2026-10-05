import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def handle_refresh_wizard_data(call):
    hass: HomeAssistant = call.hass

    base_topic = call.data.get("base_topic", "zigbee2mqtt")
    room_dropdown = call.data.get("room_dropdown_entity", "input_select.eyzee_wizard_room")
    z2m_dropdown = call.data.get("z2m_dropdown_entity", "input_select.z2m_device_friendly_name")
    master_dropdown = call.data.get("master_dropdown_entity", "input_select.eyzee_wizard_switch")
    slave_dropdown = call.data.get("slave_dropdown_entity", "input_select.eyzee_wizard_light")

    _LOGGER.info(
        "[%s] Refresh wizard data (rooms=%s, z2m=%s, master=%s, slave=%s, base_topic=%s)",
        DOMAIN, room_dropdown, z2m_dropdown, master_dropdown, slave_dropdown, base_topic
    )

    # 1) Rooms dropdown
    await hass.services.async_call(
        DOMAIN,
        "populate_room_dropdown",
        {"dropdown_entity": room_dropdown},
        blocking=True,
    )

    # 2) Z2M dropdown
    await hass.services.async_call(
        DOMAIN,
        "populate_z2m_dropdown",
        {"dropdown_entity": z2m_dropdown, "base_topic": base_topic},
        blocking=True,
    )

    # 3) Rule dropdowns (optional)
    if hass.services.has_service(DOMAIN, "populate_rule_device_dropdown"):
        try:
            await hass.services.async_call(DOMAIN, "populate_rule_device_dropdown", {}, blocking=False)
        except Exception:
            pass

    # 4) MASTER/SLAVE dropdowns (optional)
    if hass.services.has_service(DOMAIN, "populate_multiway_dropdowns"):
        try:
            await hass.services.async_call(
                DOMAIN,
                "populate_multiway_dropdowns",
                {"master_dropdown_entity": master_dropdown, "slave_dropdown_entity": slave_dropdown},
                blocking=False,
            )
        except Exception:
            pass

    # 5) Discovery / Find My Devices (optional)
    if hass.services.has_service(DOMAIN, "discover_eyzee_devices"):
        try:
            await hass.services.async_call(DOMAIN, "discover_eyzee_devices", {}, blocking=False)
        except Exception:
            pass

    # Visible confirmation
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "EyZEE Wizard Refreshed",
            "message": "Rooms + Z2M lists refreshed.",
            "notification_id": "eyzee_wizard_refresh",
        },
        blocking=False,
    )


def async_register_refresh_wizard_data_service(hass: HomeAssistant):
    hass.services.async_register(
        DOMAIN,
        "refresh_wizard_data",
        handle_refresh_wizard_data,
        schema=vol.Schema(
            {
                vol.Optional("base_topic", default="zigbee2mqtt"): cv.string,
                vol.Optional("room_dropdown_entity", default="input_select.eyzee_wizard_room"): cv.entity_id,
                vol.Optional("z2m_dropdown_entity", default="input_select.eyzee_z2m_device_friendly"): cv.entity_id,
                vol.Optional("master_dropdown_entity", default="input_select.eyzee_wizard_switch"): cv.entity_id,
                vol.Optional("slave_dropdown_entity", default="input_select.eyzee_wizard_light"): cv.entity_id,
            }
        ),
    )