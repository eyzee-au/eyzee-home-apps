// EyZEE TS0601 double GPO + middle light switch
// Fingerprint name must match your switch ie: _TZE200_4jvmbiph or _TZE284_4jvmbiph
// Stable version: 3 outputs + backlight + metering
//Note: this switch has RGB backlights not yet exposed
//To change backlight colour connect to Tuya App change colour and re-pair to HA

const exposes = require('zigbee-herdsman-converters/lib/exposes');
const tuya = require('zigbee-herdsman-converters/lib/tuya');

const e = exposes.presets;
const ea = exposes.access;

const definition = {
    fingerprint: [
        {modelID: 'TS0601', manufacturerName: '_TZE200_4jvmbiph'},
        {modelID: 'TS0601', manufacturerName: '_TZE284_4jvmbiph'},
    ],
    model: 'CC3-MG-GPO04ZSLP',
    vendor: 'EyZEE',
    description: 'Double GPO socket + middle light switch + backlight with metering',
    fromZigbee: [tuya.fz.datapoints],
    toZigbee: [tuya.tz.datapoints],
    onEvent: tuya.onEventSetTime,
    configure: tuya.configureMagicPacket,

    exposes: [
        e.binary('state_left', ea.STATE_SET, 'ON', 'OFF').withDescription('Left socket'),
        e.binary('state_middle', ea.STATE_SET, 'ON', 'OFF').withDescription('Middle light switch'),
        e.binary('state_right', ea.STATE_SET, 'ON', 'OFF').withDescription('Right socket'),
        e.binary('state_backlight', ea.STATE_SET, 'ON', 'OFF').withDescription('Button backlight'),
        e.binary('child_lock', ea.STATE_SET, 'ON', 'OFF').withDescription('Child lock'),

        e.numeric('voltage', ea.STATE).withUnit('V').withDescription('Line voltage'),
        e.numeric('current', ea.STATE).withUnit('A').withDescription('Line current'),
        e.numeric('energy_wh', ea.STATE).withUnit('Wh').withDescription('Accumulated energy'),
    ],

    endpoint: () => ({default: 1}),

    meta: {
    tuyaDatapoints: [
        [1, 'state_right', tuya.valueConverter.onOff],
        [2, 'state_middle', tuya.valueConverter.onOff],
        [3, 'state_left', tuya.valueConverter.onOff],
        [16, 'state_backlight', tuya.valueConverter.onOff],
        [101, 'child_lock', tuya.valueConverter.onOff],
        [21, 'current', tuya.valueConverter.divideBy1000],
        [22, 'energy_wh', tuya.valueConverter.raw],
        [23, 'voltage', tuya.valueConverter.divideBy10],
    ],
},
};

module.exports = definition;