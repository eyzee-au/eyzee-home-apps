"""EyZEE TS0001-TS0004 endpoint switches for ZHA.

Supported fingerprints:ver 28092026
- _TZ3000_bbebkwjk / TS0001
- _TZ3000_zam8nhsp / TS0002
- _TZ3000_sjhtrjg2 / TS0003
- _TZ3000_a4uohq8u / TS0003
- _TZ3000_2zwlkqrc / TS0003
- _TZ3000_vyitm412 / TS0004
- _TZ3000_g0h4wqfu / TS0004
- _TZ3000_k2nx32wy / TS0004

The relays use standard endpoint-specific Zigbee OnOff commands.  These Tuya
firmware variants must also receive one Basic-cluster Read Attributes request
containing attributes 0x0004, 0x0000, 0x0001, 0x0005, 0x0007 and 0xFFFE in a
single ZCL frame.  zigpy's normal read_attributes() helper splits after five
attributes, so apply_custom_configuration() deliberately uses the lower-level
request() method.

Tuya configuration features retained:
- OnOff cluster 0x0006: power-on behaviour (attribute 0x8002)
- Tuya cluster 0xE000: indicator/backlight mode
- Tuya cluster 0xE001: external switch type (toggle/state/momentary)
"""

from zigpy.profiles import zgp, zha
from zigpy.quirks import CustomDevice
from zigpy.zcl import foundation
from zigpy.zcl.clusters.general import (
    Basic,
    GreenPowerProxy,
    Groups,
    Identify,
    OnOff,
    Ota,
    Scenes,
    Time,
)

from zha.quirks import TUYA_PLUG_ONOFF
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.tuya import (
    TuyaZBE000Cluster,
    TuyaZBExternalSwitchTypeCluster,
    TuyaZBOnOffAttributeCluster,
)


def _signature(manufacturer: str, model: str, gang_count: int) -> dict:
    """Build the physical device signature for a TS000x GPP switch."""

    endpoints = {
        1: {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
            INPUT_CLUSTERS: [
                Basic.cluster_id,
                Identify.cluster_id,
                Groups.cluster_id,
                Scenes.cluster_id,
                OnOff.cluster_id,
                TuyaZBE000Cluster.cluster_id,
                TuyaZBExternalSwitchTypeCluster.cluster_id,
            ],
            OUTPUT_CLUSTERS: [Time.cluster_id, Ota.cluster_id],
        },
    }

    for endpoint_id in range(2, gang_count + 1):
        endpoints[endpoint_id] = {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: zha.DeviceType.ON_OFF_LIGHT,
            INPUT_CLUSTERS: [
                Groups.cluster_id,
                Scenes.cluster_id,
                OnOff.cluster_id,
                TuyaZBExternalSwitchTypeCluster.cluster_id,
            ],
            OUTPUT_CLUSTERS: [],
        }

    endpoints[242] = {
        PROFILE_ID: zgp.PROFILE_ID,
        DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
        INPUT_CLUSTERS: [],
        OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
    }

    return {
        MODELS_INFO: [(manufacturer, model)],
        ENDPOINTS: endpoints,
    }


def _replacement(gang_count: int) -> dict:
    """Build independent relay endpoints as switch entities."""

    endpoints = {
        1: {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
            INPUT_CLUSTERS: [
                Basic,
                Identify,
                Groups,
                Scenes,
                TuyaZBOnOffAttributeCluster,
                TuyaZBE000Cluster,
                TuyaZBExternalSwitchTypeCluster,
            ],
            OUTPUT_CLUSTERS: [Time, Ota],
        },
    }

    for endpoint_id in range(2, gang_count + 1):
        endpoints[endpoint_id] = {
            PROFILE_ID: zha.PROFILE_ID,
            DEVICE_TYPE: zha.DeviceType.ON_OFF_SWITCH,
            INPUT_CLUSTERS: [
                Groups,
                Scenes,
                TuyaZBOnOffAttributeCluster,
                TuyaZBExternalSwitchTypeCluster,
            ],
            OUTPUT_CLUSTERS: [],
        }

    endpoints[242] = {
        PROFILE_ID: zgp.PROFILE_ID,
        DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
        INPUT_CLUSTERS: [],
        OUTPUT_CLUSTERS: [GreenPowerProxy],
    }

    return {ENDPOINTS: endpoints}


class _EyZEE_TS000x_Base:
    """Common initialization required by the EyZEE TS000x firmware."""

    quirk_id = TUYA_PLUG_ONOFF

    async def apply_custom_configuration(self):
        """Send the unchunked six-attribute initialization request."""

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


class EyZEE_TS0001_1Gang(_EyZEE_TS000x_Base, CustomDevice):
    """EyZEE one-gang TS0001 switch."""

    signature = _signature("_TZ3000_bbebkwjk", "TS0001", 1)
    replacement = _replacement(1)


class EyZEE_TS0002_2Gang(_EyZEE_TS000x_Base, CustomDevice):
    """EyZEE two-gang TS0002 switch."""

    signature = _signature("_TZ3000_zam8nhsp", "TS0002", 2)
    replacement = _replacement(2)


class EyZEE_TS0003_3Gang(_EyZEE_TS000x_Base, CustomDevice):
    """EyZEE three-gang TS0003 switch."""

    signature = _signature("_TZ3000_sjhtrjg2", "TS0003", 3)

    signature[MODELS_INFO].extend(
        [
            ("_TZ3000_a4uohq8u", "TS0003"),
            ("_TZ3000_2zwlkqrc", "TS0003"),
        ]
    )

    replacement = _replacement(3)


class EyZEE_TS0004_4Gang(_EyZEE_TS000x_Base, CustomDevice):
    """EyZEE four-gang TS0004 switch."""

    signature = _signature("_TZ3000_vyitm412", "TS0004", 4)
        
    signature[MODELS_INFO].extend(
        [
            ("_TZ3000_g0h4wqfu", "TS0004"),
            ("_TZ3000_k2nx32wy", "TS0004"),
        ]
    )

    replacement = _replacement(4)
