"""EyZEE TS0004 fan/light named-entity quirk for ZHA.

Supported fingerprints: ver 20082026
- _TZ3000_fqyuqfbf / TS0004
- _TZ3000_ncb6mkx8 / TS0004


This is the v2 follow-up to the proven v1 endpoint-control quirk. It retains:
- Endpoint 1: light
- Endpoint 2: fan high
- Endpoint 3: fan low
- Endpoint 4: fan medium
- Tuya OnOff attributes, backlight and external switch type clusters
- The unchunked six-attribute Basic-cluster initialization request

It additionally changes the metadata of ZHA's four native Switch entities so
their fallback names are Light, Fan high, Fan low and Fan medium.

IMPORTANT: Do not load this file alongside eyzee_fan_light_ts0004.py because
both files match the same manufacturer/model pair. Keep the proven v1 file as
a backup outside the active custom quirks directory while testing this file.
"""

from zigpy.profiles import zha
from zigpy.quirks.v2 import CustomDeviceV2, QuirkBuilder
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import Basic, OnOff

from zha.quirks import TUYA_PLUG_ONOFF
from zhaquirks.tuya import (
    TuyaZBE000Cluster,
    TuyaZBExternalSwitchTypeCluster,
    TuyaZBOnOffAttributeCluster,
)


class EyZEEFanLightTS0004NamedDevice(CustomDeviceV2):
    """EyZEE fan/light device with required TS000x initialization."""

    quirk_id = TUYA_PLUG_ONOFF

    async def apply_custom_configuration(self):
        """Send all six required Basic attributes in one ZCL request."""

        basic_cluster = self.endpoints[1].in_clusters[Basic.cluster_id]
        command = foundation.GeneralCommand.Read_Attributes
        schema = foundation.GENERAL_COMMANDS[command].schema

        await basic_cluster.request(
            True,
            command,
            schema,
            attribute_ids=[
                0x0004,  # manufacturerName
                0x0000,  # zclVersion
                0x0001,  # appVersion
                0x0005,  # modelId
                0x0007,  # powerSource
                0xFFFE,  # attributeReportingStatus
            ],
            manufacturer=None,
            expect_reply=True,
            disable_default_response=True,
        )
(
    QuirkBuilder("_TZ3000_fqyuqfbf", "TS0004")
    .applies_to("_TZ3000_ncb6mkx8", "TS0004")
    .device_class(EyZEEFanLightTS0004NamedDevice)

    # Keep all four relay endpoints on the ZHA switch platform.
    .replaces_endpoint(
        1,
        device_type=zha.DeviceType.ON_OFF_SWITCH,
    )
    .replaces_endpoint(
        2,
        device_type=zha.DeviceType.ON_OFF_SWITCH,
    )
    .replaces_endpoint(
        3,
        device_type=zha.DeviceType.ON_OFF_SWITCH,
    )
    .replaces_endpoint(
        4,
        device_type=zha.DeviceType.ON_OFF_SWITCH,
    )

    # Retain the same Tuya cluster replacements proven by the v1 quirk.
    .replaces(
        TuyaZBOnOffAttributeCluster,
        endpoint_id=1,
    )
    .replaces(
        TuyaZBOnOffAttributeCluster,
        endpoint_id=2,
    )
    .replaces(
        TuyaZBOnOffAttributeCluster,
        endpoint_id=3,
    )
    .replaces(
        TuyaZBOnOffAttributeCluster,
        endpoint_id=4,
    )
    .replaces(
        TuyaZBE000Cluster,
        endpoint_id=1,
    )
    .replaces(
        TuyaZBExternalSwitchTypeCluster,
        endpoint_id=1,
    )
    .replaces(
        TuyaZBExternalSwitchTypeCluster,
        endpoint_id=2,
    )
    .replaces(
        TuyaZBExternalSwitchTypeCluster,
        endpoint_id=3,
    )
    .replaces(
        TuyaZBExternalSwitchTypeCluster,
        endpoint_id=4,
    )

    # Rename the four ZHA Switch entities.
    .change_entity_metadata(
        endpoint_id=1,
        cluster_id=OnOff.cluster_id,
        new_translation_key="light",
        new_fallback_name="Light",
    )
    .change_entity_metadata(
        endpoint_id=2,
        cluster_id=OnOff.cluster_id,
        new_translation_key="fan_high",
        new_fallback_name="Fan high",
    )
    .change_entity_metadata(
        endpoint_id=3,
        cluster_id=OnOff.cluster_id,
        new_translation_key="fan_low",
        new_fallback_name="Fan low",
    )
    .change_entity_metadata(
        endpoint_id=4,
        cluster_id=OnOff.cluster_id,
        new_translation_key="fan_medium",
        new_fallback_name="Fan medium",
    )
    .add_to_registry()
)
