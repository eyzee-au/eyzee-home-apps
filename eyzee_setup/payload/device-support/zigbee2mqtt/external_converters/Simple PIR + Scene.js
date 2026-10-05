const fz = require('zigbee-herdsman-converters/converters/fromZigbee');
const exposes = require('zigbee-herdsman-converters/lib/exposes');

const e = exposes.presets;
const ea = exposes.access;

const fzLocal = {
    telink_pir_scene_sensor: {
        cluster: 'ssIasZone',
        type: ['commandStatusChangeNotification'],
        convert: (model, msg, publish, options, meta) => {
            const zoneStatus = msg.data.zonestatus;

            const alarm1 = (zoneStatus & 1) > 0;
            const alarm2 = (zoneStatus & 2) > 0;
            const tamper = (zoneStatus & 4) > 0;
            const batteryLow = (zoneStatus & 8) > 0;

            const result = {
                occupancy: alarm1,
                alarm_1: alarm1,
                alarm_2: alarm2,
                tamper,
                battery_low: batteryLow,
            };

            // Treat alarm_2 as the scene/button trigger.
            // If this proves wrong, we can remap it later.
            if (alarm2) {
                result.action = 'scene_switch';
            }

            return result;
        },
    },
};

const definition = {
    fingerprint: [
        {
            modelID: 'TLSR82xx',
            manufacturerName: 'TELINK',
        },
    ],
    model: 'TLSR82xx_PIR_SCENE',
    vendor: 'EyZEE',
    description: 'PIR motion sensor with scene switch',
    fromZigbee: [
        fzLocal.telink_pir_scene_sensor,
        fz.battery,
    ],
    toZigbee: [],
    exposes: [
        e.occupancy(),
        e.battery(),
        e.battery_low(),
        e.tamper(),
        exposes.binary('alarm_1', ea.STATE, true, false)
            .withDescription('Raw IAS alarm 1, usually PIR motion'),
        exposes.binary('alarm_2', ea.STATE, true, false)
            .withDescription('Raw IAS alarm 2, likely scene switch trigger'),
        e.action(['scene_switch']),
    ],
};

module.exports = definition;