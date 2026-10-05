"""EyZEE TS011F double GPO endpoint-control quirk for ZHA.

Manufacturer: _TZ3000_6ycqll7a
Model: TS011F
Firmware tested: 0x00000043

Physical endpoint mapping established by Zigbee2MQTT and ZHA diagnostics:
- Endpoint 1 = Right outlet
- Endpoint 2 = Left outlet

Purpose:
- Override the built-in Plug_TZ3000_2AC_var02 quirk.
- Keep both outlets on independent standard endpoint-specific OnOff control.
- Retain power-on state, indicator/backlight mode and child-lock support.
- Send the required six Basic attributes in one unchunked ZCL request.
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


class EyZEEDoubleGPOTS011F(CustomDevice):
    """EyZEE double GPO with independently controlled relay endpoints."""

    quirk_id = TUYA_PLUG_ONOFF

    signature = {
        MODELS_INFO: [("_TZ3000_6ycqll7a", "TS011F")],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_PLUG_IN_UNIT,
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
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_PLUG_IN_UNIT,
                INPUT_CLUSTERS: [
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    OnOff.cluster_id,
                    TuyaZBExternalSwitchTypeCluster.cluster_id,
                ],
                OUTPUT_CLUSTERS: [],
            },
            242: {
                PROFILE_ID: zgp.PROFILE_ID,
                DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy.cluster_id],
            },
        },
    }

    replacement = {
        ENDPOINTS: {
            # Endpoint 1 = right outlet. It also holds the device-wide Tuya
            # configuration attributes: child lock, backlight and power state.
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_PLUG_IN_UNIT,
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
            # Endpoint 2 = left outlet.
            2: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.ON_OFF_PLUG_IN_UNIT,
                INPUT_CLUSTERS: [
                    Groups,
                    Scenes,
                    TuyaZBOnOffAttributeCluster,
                    TuyaZBExternalSwitchTypeCluster,
                ],
                OUTPUT_CLUSTERS: [],
            },
            242: {
                PROFILE_ID: zgp.PROFILE_ID,
                DEVICE_TYPE: zgp.DeviceType.PROXY_BASIC,
                INPUT_CLUSTERS: [],
                OUTPUT_CLUSTERS: [GreenPowerProxy],
            },
        },
    }

    async def apply_custom_configuration(self):
        """Send the unchunked six-attribute Tuya initialization request."""

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