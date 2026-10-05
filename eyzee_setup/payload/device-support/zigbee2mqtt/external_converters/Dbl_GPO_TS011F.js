const tuya = require('zigbee-herdsman-converters/lib/tuya');

module.exports = {
    fingerprint: [{modelID: 'TS011F', manufacturerName: '_TZ3000_6ycqll7a'}],
    model: 'TS011F-GPO',
    vendor: 'EyZEE',
    description: 'Double GPO - Full control, no metering',
    options: [],

    extend: [
        tuya.modernExtend.tuyaOnOff({
            endpoints: ['left', 'right'],
            powerOutageMemory: true,
            indicatorMode: true,
            childLock: true,
        }),
    ],

    fromZigbee: [tuya.fz.datapoints],

    meta: {
        multiEndpoint: true,
        tuyaDatapoints: [
            [1, 'state_left', tuya.valueConverter.onOff],
            [2, 'state_right', tuya.valueConverter.onOff],
        ],
    },

    endpoint: (device) => {
        return {right: 1, left: 2};
    },

    configure: async (device, coordinatorEndpoint) => {
        await tuya.configureMagicPacket(device, coordinatorEndpoint);
        device.save();
    },
};