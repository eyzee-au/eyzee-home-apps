"""EyZEE TS0601 5-gang touch switch quirk for ZHA.

Converted from Zigbee2MQTT external converter:
- model: TS0601
- manufacturers:
    _TZE204_jgujzjwh
    _TZE284_0kihjsys

Supported in this version:
- 5 switch relays
- indicator mode (DP15)
- global restart status (DP14)
- per-gang restart behavior DP29-DP33

Not included:
- timers
- couple_decouple on DP15
"""

import zigpy.types as t
from zigpy.quirks.v2 import EntityType
from zhaquirks.tuya.builder import TuyaQuirkBuilder


class IndicatorMode(t.enum8):
    off = 0
    on_off_status = 1
    switch_position = 2


class PowerOnBehavior(t.enum8):
    off = 0
    on = 1
    previous = 2


(
    TuyaQuirkBuilder("_TZE204_jgujzjwh", "TS0601")
    .applies_to("_TZE284_0kihjsys", "TS0601")
    .applies_to("_TZE204_ez0byyqa", "TS0601")

    # 5 gang switch states
    .tuya_switch(
        dp_id=1,
        attribute_name="state_l1",
        translation_key="state_l1",
        fallback_name="Switch 1",
        entity_type=EntityType.STANDARD,
    )
    .tuya_switch(
        dp_id=2,
        attribute_name="state_l2",
        translation_key="state_l2",
        fallback_name="Switch 2",
        entity_type=EntityType.STANDARD,
    )
    .tuya_switch(
        dp_id=3,
        attribute_name="state_l3",
        translation_key="state_l3",
        fallback_name="Switch 3",
        entity_type=EntityType.STANDARD,
    )
    .tuya_switch(
        dp_id=4,
        attribute_name="state_l4",
        translation_key="state_l4",
        fallback_name="Switch 4",
        entity_type=EntityType.STANDARD,
    )
    .tuya_switch(
        dp_id=5,
        attribute_name="state_l5",
        translation_key="state_l5",
        fallback_name="Switch 5",
        entity_type=EntityType.STANDARD,
    )

    # Global restart status
    .tuya_switch(
        dp_id=14,
        attribute_name="restart_status",
        translation_key="restart_status",
        fallback_name="Global power restoration",
        entity_type=EntityType.CONFIG,
    )

    # Indicator mode / LED mode
    .tuya_enum(
        dp_id=15,
        attribute_name="indicator_mode",
        enum_class=IndicatorMode,
        translation_key="indicator_mode",
        fallback_name="Indicator mode",
        entity_type=EntityType.CONFIG,
    )

    # Per-gang power-on behavior
    .tuya_enum(
        dp_id=29,
        attribute_name="restart_status_1",
        enum_class=PowerOnBehavior,
        translation_key="restart_status_1",
        fallback_name="Power-on behavior 1",
        entity_type=EntityType.CONFIG,
    )
    .tuya_enum(
        dp_id=30,
        attribute_name="restart_status_2",
        enum_class=PowerOnBehavior,
        translation_key="restart_status_2",
        fallback_name="Power-on behavior 2",
        entity_type=EntityType.CONFIG,
    )
    .tuya_enum(
        dp_id=31,
        attribute_name="restart_status_3",
        enum_class=PowerOnBehavior,
        translation_key="restart_status_3",
        fallback_name="Power-on behavior 3",
        entity_type=EntityType.CONFIG,
    )
    .tuya_enum(
        dp_id=32,
        attribute_name="restart_status_4",
        enum_class=PowerOnBehavior,
        translation_key="restart_status_4",
        fallback_name="Power-on behavior 4",
        entity_type=EntityType.CONFIG,
    )
    .tuya_enum(
        dp_id=33,
        attribute_name="restart_status_5",
        enum_class=PowerOnBehavior,
        translation_key="restart_status_5",
        fallback_name="Power-on behavior 5",
        entity_type=EntityType.CONFIG,
    )

    .skip_configuration()
    .add_to_registry()
)