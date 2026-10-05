// eyzee_ts0601_uuvwd42v_mmwave.js

const tuya = require('zigbee-herdsman-converters/lib/tuya');
const exposes = require('zigbee-herdsman-converters/lib/exposes');

const e = exposes.presets;
const ea = exposes.access;

const valueConverter = {
    raw: {
        from: (v) => v,
        to: (v) => v,
    },

    divideBy10: {
        from: (v) => v / 10,
        to: (v) => Math.round(v * 10),
    },

    divideBy100: {
        from: (v) => v / 100,
        to: (v) => Math.round(v * 100),
    },

    occupancyBool: {
        from: (v) => {
            if (v === 0) return false;
            if (v === 1) return true;
            return null;
        },
        to: (v) => v ? 1 : 0,
    },
};

module.exports = {
    fingerprint: [
        {modelID: 'TS0601', manufacturerName: '_TZE284_uuvwd42v'},
        {modelID: 'TS0601', manufacturerName: '_TZE204_qrguyh1k'},
        {modelID: 'TS0601', manufacturerName: '_TZE204_ztqnh5cg'},
        {modelID: 'TS0601', manufacturerName: '_TZE204_vjdburop'},
        {modelID: 'TS0601', manufacturerName: '_TZE204_ztc6ggyl'},
    ],

    model: 'MMWAVE_SENSOR_TS0601_TZE284_TZE204',
    vendor: 'EyZEE-Tuya',
    description: 'EyZEE mmWave human presence sensor with illuminance',

    fromZigbee: [tuya.fz.datapoints],
    toZigbee: [tuya.tz.datapoints],

    exposes: [
        e.occupancy()
            .withDescription('Human presence detected, DP1.'),

        e.numeric('illuminance_lux', ea.STATE)
            .withDescription('Live illuminance reading from DP104. May briefly report null during sensor refresh.'),

        e.numeric('sensitivity', ea.STATE_SET)
            .withValueMin(0)
            .withValueMax(9)
            .withValueStep(1)
            .withDescription('Detection sensitivity, DP2.'),

        e.numeric('nearest_detection_distance', ea.STATE_SET)
            .withUnit('m')
            .withValueMin(0)
            .withValueMax(6)
            .withValueStep(0.1)
            .withDescription('Nearest detection distance, DP3. Raw 600 = 6.00m.'),

        e.numeric('max_detection_distance', ea.STATE_SET)
            .withUnit('m')
            .withValueMin(0)
            .withValueMax(6)
            .withValueStep(0.1)
            .withDescription('Maximum detection distance, DP5. Raw 60 = 6.0m.'),

        e.numeric('target_confirm_time', ea.STATE_SET)
            .withUnit('s')
            .withValueMin(0)
            .withValueMax(0.5)
            .withValueStep(0.1)
            .withDescription('Target confirmation time, DP101.'),

        e.numeric('disappearance_delay', ea.STATE_SET)
            .withUnit('s')
            .withValueMin(2)
            .withValueMax(1500)
            .withValueStep(1)
            .withDescription('Presence disappearance delay, DP102.'),

        e.numeric('indent_level', ea.STATE_SET)
            .withValueMin(0)
            .withValueMax(3)
            .withValueStep(1)
            .withDescription('Indent level, DP107.'),

        e.numeric('trigger_level', ea.STATE_SET)
            .withValueMin(0)
            .withValueMax(3)
            .withValueStep(1)
            .withDescription('Trigger level, DP108.'),
    ],

    meta: {
        tuyaDatapoints: [
            [1, 'occupancy', valueConverter.occupancyBool],
            [2, 'sensitivity', valueConverter.raw],
            [3, 'nearest_detection_distance', valueConverter.divideBy100],
            [5, 'max_detection_distance', valueConverter.divideBy10],
            [101, 'target_confirm_time', valueConverter.divideBy10],
            [102, 'disappearance_delay', valueConverter.divideBy10],
            [104, 'illuminance_lux', valueConverter.raw],
            [107, 'indent_level', valueConverter.raw],
            [108, 'trigger_level', valueConverter.raw],

            // Known but intentionally not exposed:
            // DP6: unknown status/event flag, range appears 0-1.
            // DP103: unknown toggle, appears to affect lux refresh/null behaviour.
        ],
    },
};
