import * as exposes from 'zigbee-herdsman-converters/lib/exposes';
import * as tuya from 'zigbee-herdsman-converters/lib/tuya';

const e = exposes.presets;
const ea = exposes.access;

const fzLocal = {
    eyzee_tuya_lock_debug: {
        cluster: 'manuSpecificTuya',
        type: ['commandDataReport', 'commandDataResponse', 'commandActiveStatusReport'],
        convert: (model, msg, publish, options, meta) => {
            console.log(`EYZZEE LOCK RAW TUYA MSG: ${JSON.stringify(msg.data)}`);

            const result = {};

            if (msg.data?.dpValues) {
                for (const dpValue of msg.data.dpValues) {
                    const dp = dpValue.dp;
                    const datatype = dpValue.datatype;
                    const data = dpValue.data;

                    console.log(
                        `EYZZEE LOCK DP ${dp}, datatype ${datatype}, raw ${JSON.stringify(data)}`,
                    );

                    result[`dp_${dp}`] = {
                        datatype,
                        raw: data,
                    };
                }
            }

            return result;
        },
    },
};

const definition = {
    fingerprint: [
        {
            modelID: 'TY0A01',
            manufacturerName: '_TYST12_bfejtdig',
        },
    ],

    model: 'TY0A01',
    vendor: 'EyZEE / Tuya',
    description: 'EyZEE compatible Tuya Zigbee door lock - discovery converter',

    fromZigbee: [
        tuya.fz.datapoints,
        fzLocal.eyzee_tuya_lock_debug,
    ],

    toZigbee: [
        tuya.tz.datapoints,
    ],

    exposes: [
        e.battery(),
        e.lock(),
        e.binary('door', ea.STATE, true, false)
            .withDescription('Door/contact state if reported by firmware'),

        e.text('last_unlock_method', ea.STATE)
            .withDescription('Raw unlock method discovery value'),

        e.text('last_alarm', ea.STATE)
            .withDescription('Raw alarm discovery value'),

        e.text('motor_state', ea.STATE)
            .withDescription('Raw motor state discovery value'),

        e.text('dp_1', ea.STATE),
        e.text('dp_2', ea.STATE),
        e.text('dp_3', ea.STATE),
        e.text('dp_5', ea.STATE),
        e.text('dp_8', ea.STATE),
        e.text('dp_9', ea.STATE),
        e.text('dp_10', ea.STATE),
        e.text('dp_12', ea.STATE),
        e.text('dp_14', ea.STATE),
        e.text('dp_21', ea.STATE),
        e.text('dp_35', ea.STATE),
        e.text('dp_41', ea.STATE),
        e.text('dp_47', ea.STATE),
        e.text('dp_57', ea.STATE),
        e.text('dp_61', ea.STATE),
        e.text('dp_62', ea.STATE),
    ],

configure: async (device, coordinatorEndpoint, logger) => {
    const endpoint = device.getEndpoint(1);

    logger.info('EyZEE TY0A01 lock: running Tuya configure');

    await tuya.configureMagicPacket(device, coordinatorEndpoint, logger);

    try {
        await endpoint.command('manuSpecificTuya', 'dataQuery', {}, {
            disableDefaultResponse: true,
        });
        logger.info('EyZEE TY0A01 lock: Tuya data query sent');
    } catch (error) {
        logger.warning(`EyZEE TY0A01 lock: Tuya data query failed: ${error}`);
    }
},

    meta: {
        tuyaDatapoints: [
            [1, 'last_unlock_method', tuya.valueConverter.raw],
            [2, 'last_unlock_method', tuya.valueConverter.raw],
            [3, 'temporary_pin', tuya.valueConverter.raw],
            [5, 'last_unlock_method', tuya.valueConverter.raw],
            [8, 'state', tuya.valueConverter.lockUnlock],
            [9, 'last_alarm', tuya.valueConverter.raw],
            [10, 'battery', tuya.valueConverter.raw],
            [12, 'reverse_lock', tuya.valueConverter.raw],
            [14, 'doorbell', tuya.valueConverter.raw],
            [21, 'remote_unlock', tuya.valueConverter.raw],
            [35, 'hijack_alarm', tuya.valueConverter.raw],
            [41, 'app_unlock', tuya.valueConverter.raw],
            [47, 'door', tuya.valueConverter.raw],
            [57, 'motor_state', tuya.valueConverter.raw],
            [61, 'single_use_password', tuya.valueConverter.raw],
            [62, 'voice_unlock', tuya.valueConverter.raw],
        ],
    },
};

export default definition;
