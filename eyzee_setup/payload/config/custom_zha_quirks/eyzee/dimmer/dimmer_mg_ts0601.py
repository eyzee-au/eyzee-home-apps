"""EyZEE TS0601 Tuya dimmer quirk for _TZE200_6fjev1mn.

Confirmed datapoints:
DP16  = backlight switch
DP20  = energy
DP21  = current
DP22  = power
DP23  = voltage
DP101 = child lock
DP141 = relay state
DP142 = brightness, native 10..1000
DP143 = brightness min, native 10..1000
DP144 = brightness max, native 10..1000
DP145 = countdown seconds
DP146 = power-on behavior
DP107 = raw backlight colour config, not implemented here yet
"""

import zigpy.types as t
from zigpy.quirks.v2 import EntityType
from zhaquirks.tuya.builder import TuyaQuirkBuilder


class PowerOnBehavior(t.enum8):
    """Power-on restore mode."""

    Off = 0x00
    On = 0x01
    Memory = 0x02


(
    TuyaQuirkBuilder("_TZE200_6fjev1mn", "TS0601")

    # Main relay
    .tuya_switch(
        dp_id=141,
        attribute_name="state",
        entity_type=EntityType.STANDARD,
        translation_key="state",
        fallback_name="Dimmer",
    )

    # Brightness is exposed as a number entity on the native Tuya scale.
    # Native range is 10..1000.
    .tuya_number(
        dp_id=142,
        attribute_name="brightness",
        type=t.uint16_t,
        min_value=10,
        max_value=1000,
        step=1,
        entity_type=EntityType.STANDARD,
        translation_key="dimmer_brightness",
        fallback_name="Dimmer brightness",
    )

    # Backlight master switch / arrows depending on DP107 mode
    .tuya_switch(
        dp_id=16,
        attribute_name="backlight_switch",
        entity_type=EntityType.CONFIG,
        translation_key="button_backlight",
        fallback_name="Button backlight",
    )

    # Child lock
    .tuya_switch(
        dp_id=101,
        attribute_name="child_lock",
        entity_type=EntityType.CONFIG,
        translation_key="child_lock",
        fallback_name="Child lock",
    )

    # Brightness min/max on native Tuya scale 10..1000
    .tuya_number(
        dp_id=143,
        attribute_name="brightness_min",
        type=t.uint16_t,
        min_value=10,
        max_value=1000,
        step=1,
        entity_type=EntityType.CONFIG,
        translation_key="minimum_dim_level",
        fallback_name="Minimum dim level",
    )

    .tuya_number(
        dp_id=144,
        attribute_name="brightness_max",
        type=t.uint16_t,
        min_value=10,
        max_value=1000,
        step=1,
        entity_type=EntityType.CONFIG,
        translation_key="maximum_dim_level",
        fallback_name="Maximum dim level",
    )

    # Countdown seconds
    .tuya_number(
        dp_id=145,
        attribute_name="countdown",
        type=t.uint32_t,
        min_value=0,
        max_value=86400,
        step=1,
        entity_type=EntityType.CONFIG,
        translation_key="countdown",
        fallback_name="Countdown",
    )

    # Power-on behavior
    .tuya_enum(
        dp_id=146,
        attribute_name="power_on_behavior",
        enum_class=PowerOnBehavior,
        entity_type=EntityType.CONFIG,
        translation_key="power_on_behavior",
        fallback_name="Power-on behavior",
    )

    # Metering / diagnostics
    .tuya_sensor(
        dp_id=20,
        attribute_name="energy",
        type=t.uint32_t,
        converter=lambda x: x / 100,
        unit="kWh",
        entity_type=EntityType.STANDARD,
        translation_key="energy",
        fallback_name="Energy",
    )

    .tuya_sensor(
        dp_id=21,
        attribute_name="current",
        type=t.uint32_t,
        unit="mA",
        entity_type=EntityType.STANDARD,
        translation_key="current",
        fallback_name="Current",
    )

    .tuya_sensor(
        dp_id=22,
        attribute_name="power",
        type=t.uint32_t,
        converter=lambda x: x / 10,
        unit="W",
        entity_type=EntityType.STANDARD,
        translation_key="power",
        fallback_name="Power",
    )

    .tuya_sensor(
        dp_id=23,
        attribute_name="voltage",
        type=t.uint32_t,
        converter=lambda x: x / 10,
        unit="V",
        entity_type=EntityType.STANDARD,
        translation_key="voltage",
        fallback_name="Voltage",
    )

    .skip_configuration()
    .add_to_registry()
)