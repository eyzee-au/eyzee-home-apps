// EyZEE 4-channel fan/light wall switch
// Model: TS0004
// Manufacturer: _TZ3000_fqyuqfbf
//
// Proven physical endpoint mapping:
//   Endpoint 1 = Light
//   Endpoint 2 = Fan high
//   Endpoint 3 = Fan low
//   Endpoint 4 = Fan medium
//
// The switch firmware provides the fan-speed interlock. Turning on a new fan
// speed automatically turns the previously selected speed off.

const exposes = require('zigbee-herdsman-converters/lib/exposes');
const m = require('zigbee-herdsman-converters/lib/modernExtend');
const reporting = require('zigbee-herdsman-converters/lib/reporting');
const tuya = require('zigbee-herdsman-converters/lib/tuya');

const e = exposes.presets;
const ea = exposes.access;

// Tuya manufacturer-specific attributes on endpoint 1 / genOnOff.
const TUYA_BACKLIGHT_ATTRIBUTE = 'tuyaBacklightMode'; // 0x8001

const BACKLIGHT_MODES = {
    red_on_off_off: 0,
    pink_on_off_off: 1,
    red_on_blue_off: 2,
    pink_on_blue_off: 3,
};

const BACKLIGHT_MODES_BY_VALUE = Object.fromEntries(
    Object.entries(BACKLIGHT_MODES).map(([name, value]) => [value, name]),
);

const fzLocal = {
    backlightMode: {
        cluster: 'genOnOff',
        type: ['attributeReport', 'readResponse'],
        convert: (model, msg) => {
            // Attribute 0x8001 is exposed by zigbee-herdsman as
            // "tuyaBacklightMode". Keep a numeric fallback for older builds.
            const raw = msg.data[TUYA_BACKLIGHT_ATTRIBUTE] ?? msg.data[0x8001];
            const mode = BACKLIGHT_MODES_BY_VALUE[raw];

            if (mode === undefined) {
                return {};
            }

            return {tuyabacklightmode: mode};
        },
    },
};

const tzLocal = {
    backlightMode: {
        key: ['tuyabacklightmode'],

        convertSet: async (entity, key, value) => {
            const mode = BACKLIGHT_MODES[value];

            if (mode === undefined) {
                throw new Error(`Invalid tuyabacklightmode: ${value}`);
            }

            // Backlight mode is a device-wide setting held on endpoint 1.
            const endpoint = entity.getEndpoint
                ? entity.getEndpoint(1)
                : entity;

            await endpoint.write(
                'genOnOff',
                {
                    [TUYA_BACKLIGHT_ATTRIBUTE]: mode,
                },
                {
                    disableDefaultResponse: true,
                },
            );

            return {
                state: {
                    tuyabacklightmode: value,
                },
            };
        },

        convertGet: async (entity) => {
            const endpoint = entity.getEndpoint
                ? entity.getEndpoint(1)
                : entity;

            await endpoint.read(
                'genOnOff',
                [TUYA_BACKLIGHT_ATTRIBUTE],
            );
        },
    },
};

const definition = {
    fingerprint: [
        {
            modelID: 'TS0004',
            manufacturerName: '_TZ3000_fqyuqfbf',
        },
    ],

    model: 'EyZEE_4GANG_FAN_LIGHT_TS0004',
    vendor: 'EyZEE',
    description:
        'Fan/light wall switch with light, low, medium and high fan-speed control',

    extend: [
        m.deviceEndpoints({
            endpoints: {
                light: 1,
                fan_high: 2,
                fan_low: 3,
                fan_medium: 4,
            },
        }),

        // Add Tuya initialization and custom clusters.
        tuya.modernExtend.tuyaBase(),

        // Standard endpoint-specific OnOff control and
        // Tuya power-on behaviour.
        tuya.modernExtend.tuyaOnOff({
            endpoints: [
                'light',
                'fan_high',
                'fan_low',
                'fan_medium',
            ],
            powerOnBehavior2: true,
        }),
    ],

    fromZigbee: [
        fzLocal.backlightMode,
    ],

    toZigbee: [
        tzLocal.backlightMode,
    ],

    exposes: [
        e
            .enum(
                'tuyabacklightmode',
                ea.ALL,
                Object.keys(BACKLIGHT_MODES),
            )
            .withDescription(
                'Colour behaviour of the switch indicator lights',
            )
            .withCategory('config'),
    ],

    meta: {
        multiEndpoint: true,
    },

    configure: async (device, coordinatorEndpoint) => {
        await tuya.configureMagicPacket(
            device,
            coordinatorEndpoint,
        );

        // Bind and configure OnOff reporting on every physical relay.
        // This provides feedback from MQTT commands, physical button
        // presses and the firmware-controlled fan-speed interlock.
        for (const endpointID of [1, 2, 3, 4]) {
            const endpoint = device.getEndpoint(endpointID);

            await reporting.bind(
                endpoint,
                coordinatorEndpoint,
                ['genOnOff'],
            );

            try {
                await reporting.onOff(endpoint);
            } catch {
                // Some Tuya firmware rejects reporting configuration
                // but still sends OnOff reports. Do not fail the
                // complete device interview.
            }
        }

        // Read the device-wide backlight setting from endpoint 1.
        const endpoint1 = device.getEndpoint(1);

        try {
            await endpoint1.read(
                'genOnOff',
                [TUYA_BACKLIGHT_ATTRIBUTE],
            );
        } catch {
            // Backlight control may still work even when the firmware
            // does not answer the initial read request.
        }

        device.powerSource = 'Mains (single phase)';
        device.save();
    },
};

module.exports = definition;