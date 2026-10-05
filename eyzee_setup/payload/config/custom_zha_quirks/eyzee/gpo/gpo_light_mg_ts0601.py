"""EyZEE TS0601 double GPO + middle light production quirk for ZHA.

Verified from Zigbee2MQTT testing:
- DP 1   -> left socket
- DP 2   -> middle light
- DP 3   -> right socket
- DP 16  -> button backlight
- DP 21  -> current / 1000
- DP 22  -> energy_wh raw
- DP 23  -> voltage / 10
- DP 101 -> child lock

Notes:
- Indicator mode and restart status are intentionally not included (not confirmed).
"""

import zigpy.types as t
from zigpy.quirks.v2 import EntityType
from zigpy.quirks.v2.homeassistant.sensor import SensorDeviceClass, SensorStateClass
from zhaquirks.tuya.builder import TuyaQuirkBuilder


(
    TuyaQuirkBuilder("_TZE200_4jvmbiph", "TS0601")
    .tuya_switch(
        dp_id=1,
        attribute_name="state_left",
        translation_key="state_left",
        fallback_name="Left socket",
        entity_type=EntityType.STANDARD,
    )
    .tuya_switch(
        dp_id=2,
        attribute_name="state_middle",
        translation_key="state_middle",
        fallback_name="Middle light",
        entity_type=EntityType.STANDARD,
    )
    .tuya_switch(
        dp_id=3,
        attribute_name="state_right",
        translation_key="state_right",
        fallback_name="Right socket",
        entity_type=EntityType.STANDARD,
    )
    .tuya_switch(
        dp_id=16,
        attribute_name="state_backlight",
        translation_key="state_backlight",
        fallback_name="Button backlight",
        entity_type=EntityType.CONFIG,
    )
    .tuya_switch(
        dp_id=101,
        attribute_name="child_lock",
        translation_key="child_lock",
        fallback_name="Child lock",
        entity_type=EntityType.CONFIG,
    )
    .tuya_sensor(
        dp_id=21,
        attribute_name="current",
        type=t.uint32_t,
        divisor=1000,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        unit="A",
        translation_key="current",
        fallback_name="Current",
        entity_type=EntityType.STANDARD,
    )
    .tuya_sensor(
        dp_id=22,
        attribute_name="energy_wh",
        type=t.uint32_t,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        unit="Wh",
        translation_key="energy_wh",
        fallback_name="Energy",
        entity_type=EntityType.STANDARD,
    )
    .tuya_sensor(
        dp_id=23,
        attribute_name="voltage",
        type=t.uint32_t,
        divisor=10,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        unit="V",
        translation_key="voltage",
        fallback_name="Voltage",
        entity_type=EntityType.STANDARD,
    )
    .skip_configuration()
    .add_to_registry()
)