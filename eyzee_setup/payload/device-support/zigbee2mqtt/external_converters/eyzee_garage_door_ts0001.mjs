import * as exposes from 'zigbee-herdsman-converters/lib/exposes';
import * as reporting from 'zigbee-herdsman-converters/lib/reporting';
import * as tuya from 'zigbee-herdsman-converters/lib/tuya';

const e = exposes.presets;
const ea = exposes.access;


// ============================================================
// EyZEE Garage Door Opener
//
// Zigbee model: TS0001
// Manufacturer: _TZ3210_sb8x2xci
//
// Endpoint 1:
//   Relay output to garage door motor
//
// Tuya DP103:
//   Magnetic door contact
//   0 = closed
//   1 = open
//
// The relay is intentionally NOT exposed as a normal switch.
// Activating "trigger" generates a short ON -> OFF pulse.
// ============================================================


const fzLocal = {

    garage_contact: {
        cluster: 'manuSpecificTuya',

        type: [
            'commandDataResponse',
            'commandDataReport',
            'commandActiveStatusReport',
        ],

        convert: (model, msg, publish, options, meta) => {

            if (!msg.data || !msg.data.dpValues) {
                return;
            }

            for (const dpValue of msg.data.dpValues) {

                if (dpValue.dp !== 103) {
                    continue;
                }

                const value = tuya.getDataValue(dpValue);

                return {
                    door_open: value === 1,
                };
            }
        },
    },


    // Consume relay reports without exposing them as a switch.
    relay_state_ignore: {
        cluster: 'genOnOff',

        type: [
            'attributeReport',
            'readResponse',
        ],

        convert: () => {
            return {};
        },
    },
};


const tzLocal = {

    garage_trigger: {

        key: ['trigger'],

        convertSet: async (entity, key, value, meta) => {

            if (
                value !== 'PRESS' &&
                value !== 'press' &&
                value !== 'ON'
            ) {
                return;
            }

            // Momentarily energise garage door input.
            await entity.command(
                'genOnOff',
                'on',
                {},
                {disableDefaultResponse: true},
            );

            await new Promise((resolve) =>
                setTimeout(resolve, 600)
            );

            await entity.command(
                'genOnOff',
                'off',
                {},
                {disableDefaultResponse: true},
            );

            return {
                state: {
                    trigger: 'PRESS',
                },
            };
        },
    },
};


const definition = {

    fingerprint: [
        {
            modelID: 'TS0001',
            manufacturerName: '_TZ3210_sb8x2xci',
        },
    ],

    model: 'EY-GARAGE-TS0001',

    vendor: 'EyZEE',

    description:
        'EyZEE Zigbee garage door opener with magnetic door sensor',

    fromZigbee: [
        fzLocal.garage_contact,
        fzLocal.relay_state_ignore,
    ],

    toZigbee: [
        tzLocal.garage_trigger,
    ],

    exposes: [

        exposes
            .enum(
                'trigger',
                ea.SET,
                ['PRESS'],
            )
            .withDescription(
                'Momentarily activate the garage door motor input',
            ),

        exposes
            .binary(
                'door_open',
                ea.STATE,
                true,
                false,
            )
            .withDescription(
                'Garage door magnetic sensor: open or closed',
            ),
    ],

    configure: async (
        device,
        coordinatorEndpoint,
        logger,
    ) => {

        const endpoint = device.getEndpoint(1);

        if (endpoint) {

            try {
                await reporting.bind(
                    endpoint,
                    coordinatorEndpoint,
                    ['genOnOff'],
                );
            } catch (error) {
                logger.debug(
                    `Garage door relay bind failed: ${error}`,
                );
            }

            try {
                await reporting.onOff(endpoint);
            } catch (error) {
                logger.debug(
                    `Garage door reporting setup failed: ${error}`,
                );
            }
        }
    },
};


export default definition;
