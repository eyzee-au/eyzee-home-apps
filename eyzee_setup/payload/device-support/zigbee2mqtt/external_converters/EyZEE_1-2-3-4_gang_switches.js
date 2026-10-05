// eyzee_ts000x_switches.js
//Supported fingerprints:ver 28092026
//- _TZ3000_bbebkwjk / TS0001
//- _TZ3000_zam8nhsp / TS0002
//- _TZ3000_sjhtrjg2 / TS0003
//- _TZ3000_a4uohq8u / TS0003
//- _TZ3000_2zwlkqrc / TS0003
//- _TZ3000_vyitm412 / TS0004
//- _TZ3000_g0h4wqfu / TS0004
//- _TZ3000_k2nx32wy / TS0004

const m = require('zigbee-herdsman-converters/lib/modernExtend');
const tuya = require('zigbee-herdsman-converters/lib/tuya');

function endpointMap(gangCount) {
    const endpoints = {};

    for (let i = 1; i <= gangCount; i++) {
        endpoints[`l${i}`] = i;
    }

    return endpoints;
}

function eyzeeSwitch({
    fingerprints,
    gangCount,
    model,
    description,
}) {
    const endpoints = endpointMap(gangCount);
    const endpointNames = Object.keys(endpoints);

    return {
        fingerprint: fingerprints,

        model,
        vendor: 'EyZEE',
        description,

        extend: [
            m.deviceEndpoints({
                endpoints,
            }),

            // Registers Tuya custom clusters including manuSpecificTuya3.
            tuya.modernExtend.tuyaBase(),

            tuya.modernExtend.tuyaOnOff({
                endpoints: endpointNames,
                powerOnBehavior2: true,
                indicatorMode: true,
                switchType: true,
            }),
        ],

        meta: {
            multiEndpoint: true,
        },
    };
}

module.exports = [
eyzeeSwitch({
    fingerprints: [
        {modelID: 'TS0001', manufacturerName: '_TZ3000_bbebkwjk'},
    ],
    gangCount: 1,
    model: 'EyZEE_1GANG_SWITCH_TS0002',
    description: '1 button smart switch with power-on behaviour, indicator mode and switch type',
}),

eyzeeSwitch({
    fingerprints: [
        {modelID: 'TS0002', manufacturerName: '_TZ3000_zam8nhsp'},
        {modelID: 'TS0002', manufacturerName: '_TZ3000_oykkhvyk'},
    ],
    gangCount: 2,
    model: 'EyZEE_2GANG_SWITCH_TS0002',
    description: '2 button smart switch with power-on behaviour, indicator mode and switch type',
}),

eyzeeSwitch({
    fingerprints: [
        {modelID: 'TS0003', manufacturerName: '_TZ3000_sjhtrjg2'},
        {modelID: 'TS0003', manufacturerName: '_TZ3000_2zwlkqrc'},
        {modelID: 'TS0003', manufacturerName: '_TZ3000_a4uohq8u'},
    ],
    gangCount: 3,
    model: 'EyZEE_3GANG_SWITCH_TS0003',
    description: '3 button smart switch with power-on behaviour, indicator mode and switch type',
}),

eyzeeSwitch({
    fingerprints: [
        {modelID: 'TS0004', manufacturerName: '_TZ3000_vyitm412'},
        {modelID: 'TS0004', manufacturerName: '_TZ3000_g0h4wqfu'},
        {modelID: 'TS0004', manufacturerName: '_TZ3000_k2nx32wy'},
    ],
    gangCount: 4,
    model: 'EyZEE_4GANG_SWITCH_TS0004',
    description: '4 button smart switch with power-on behaviour, indicator mode and switch type',
}),
];
