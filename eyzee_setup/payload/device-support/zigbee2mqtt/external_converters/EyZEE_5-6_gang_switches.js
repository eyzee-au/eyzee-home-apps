// eyzee_ts0601_5_6gang_switches.js

const exposes = require('zigbee-herdsman-converters/lib/exposes');
const tuya = require('zigbee-herdsman-converters/lib/tuya');

const e = exposes.presets;
const ea = exposes.access;

const indicatorModeEnum = tuya.valueConverterBasic.lookup({
    off: tuya.enum(0),
    on_off_status: tuya.enum(1),
    switch_position: tuya.enum(2),
});

// Decouplar® helper on DP15.
// OFF = normal coupled mode.
// ON  = Decouplar® trigger mode.
const decouplarModeEnum = tuya.valueConverterBasic.lookup({
    OFF: tuya.enum(1),
    ON: tuya.enum(2),
});

function makeSwitchExposes(gangCount) {
    return Array.from({length: gangCount}, (_, i) =>
        e.switch()
            .withEndpoint(`l${i + 1}`)
            .withDescription(`Switch ${i + 1}`)
    );
}

function makePowerOnExposes(gangCount) {
    return Array.from({length: gangCount}, (_, i) =>
        e.enum(`power_on_behavior_l${i + 1}`, ea.STATE_SET, ['off', 'on', 'previous'])
            .withDescription(`Power-on behaviour for switch ${i + 1}`)
    );
}

function makeEndpointMap(gangCount) {
    const endpoints = {};

    for (let i = 1; i <= gangCount; i++) {
        endpoints[`l${i}`] = 1;
    }

    return endpoints;
}

function makeTuyaDatapoints(gangCount) {
    const datapoints = [];

    for (let i = 1; i <= gangCount; i++) {
        datapoints.push([i, `state_l${i}`, tuya.valueConverter.onOff]);
    }

    for (let i = 1; i <= gangCount; i++) {
        datapoints.push([6 + i, `timer_l${i}`, tuya.valueConverter.countdown]);
    }

    datapoints.push([14, 'restart_status', tuya.valueConverter.onOff]);

    // DP15 is shared by indicator mode and Decouplar® helper.
    datapoints.push([15, 'indicator_mode', indicatorModeEnum]);
    datapoints.push([15, 'decouplar_mode', decouplarModeEnum]);

    for (let i = 1; i <= gangCount; i++) {
        datapoints.push([28 + i, `power_on_behavior_l${i}`, tuya.valueConverter.powerOnBehaviorEnum]);
    }

    return datapoints;
}

function eyzeeTs0601Switch({gangCount, fingerprints}) {
    return {
        fingerprint: fingerprints,

        model: `EyZEE_${gangCount}GANG_SWITCH_TS0601`,
        vendor: 'EyZEE',
        description: `EyZEE ${gangCount} Gang Zigbee Touch Switch`,

        fromZigbee: [tuya.fz.datapoints],
        toZigbee: [tuya.tz.datapoints],
        onEvent: tuya.onEventSetTime,
        configure: tuya.configureMagicPacket,

        exposes: [
            ...makeSwitchExposes(gangCount),

            e.binary('decouplar_mode', ea.STATE_SET, 'ON', 'OFF')
                .withDescription(
                    'Decouplar® mode helper. Use only with EyZEE Decouplar® switches. ' +
                    'Set ON, then double-tap the physical button to activate Decouplar® mode. ' +
                    'Set OFF, then double-tap the physical button to return to normal coupled mode.'
                ),

            e.enum('indicator_mode', ea.STATE_SET, ['off', 'on_off_status', 'switch_position'])
                .withDescription(
                    'Indicator mode: off = indicator off, ' +
                    'on_off_status = red when ON / blue when OFF, ' +
                    'switch_position = pink when ON / off when OFF.'
                ),

            ...makePowerOnExposes(gangCount),

            e.binary('restart_status', ea.STATE_SET, 'ON', 'OFF')
                .withDescription('Global power restoration status'),
        ],

        endpoint: () => makeEndpointMap(gangCount),

        meta: {
            multiEndpoint: true,
            tuyaDatapoints: makeTuyaDatapoints(gangCount),
        },
    };
}

module.exports = [
    eyzeeTs0601Switch({
        gangCount: 5,
        fingerprints: [
            {modelID: 'TS0601', manufacturerName: '_TZE284_0kihjsys'},
            {modelID: 'TS0601', manufacturerName: '_TZE204_ez0byyqa'},
            {modelID: 'TS0601', manufacturerName: '_TZE284_ez0byyqa'},
        ],
    }),

    eyzeeTs0601Switch({
        gangCount: 6,
        fingerprints: [
            {modelID: 'TS0601', manufacturerName: '_TZE204_jgujzjwh'},
            {modelID: 'TS0601', manufacturerName: '_TZE284_qvipre57'},
            {modelID: 'TS0601', manufacturerName: '_TZE200_tnc1ttnt'},
        ],
    }),
];