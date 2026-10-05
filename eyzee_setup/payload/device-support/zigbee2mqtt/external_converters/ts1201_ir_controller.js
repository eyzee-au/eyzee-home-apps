/**
 * EyZEE® TS1201 IR Controller
 *
 * Device:
 *   Zigbee model: TS1201
 *   Manufacturer: _TZ3290_j37rooaxrcdcqo5n
 *
 * Provides:
 *   - IR learning mode
 *   - Learned IR code output
 *   - IR code transmission
 *   - Battery percentage
 *   - Battery voltage
 */

import * as fz from "zigbee-herdsman-converters/converters/fromZigbee";
import * as exposes from "zigbee-herdsman-converters/lib/exposes";
import * as reporting from "zigbee-herdsman-converters/lib/reporting";
import * as zosung from "zigbee-herdsman-converters/lib/zosung";

const e = exposes.presets;
const fzZosung = zosung.fzZosung;
const tzZosung = zosung.tzZosung;
const ez = zosung.presetsZosung;

const definition = {
    fingerprint: [
        {
            modelID: "TS1201",
            manufacturerName: "_TZ3290_j37rooaxrcdcqo5n",
        },
    ],

    model: "EY-ZB-IR01",
    vendor: "EyZEE",
    description: "EyZEE Zigbee universal IR learning controller",

    fromZigbee: [
        fzZosung.zosung_send_ir_code_00,
        fzZosung.zosung_send_ir_code_01,
        fzZosung.zosung_send_ir_code_02,
        fzZosung.zosung_send_ir_code_03,
        fzZosung.zosung_send_ir_code_04,
        fzZosung.zosung_send_ir_code_05,
        fz.battery,
    ],

    toZigbee: [
        tzZosung.zosung_ir_code_to_send,
        tzZosung.zosung_learn_ir_code,
    ],

    exposes: [
        ez.learn_ir_code(),
        ez.learned_ir_code(),
        ez.ir_code_to_send(),
        e.battery(),
        e.battery_voltage(),
    ],

    configure: async (device, coordinatorEndpoint) => {
        const endpoint = device.getEndpoint(1);

        try {
            await endpoint.read("genPowerCfg", [
                "batteryVoltage",
                "batteryPercentageRemaining",
            ]);
        } catch (error) {
            // Some TS1201 variants do not respond to the initial battery read.
            console.warn(
                `EyZEE TS1201: initial battery read failed: ${error.message}`,
            );
        }

        try {
            await reporting.bind(endpoint, coordinatorEndpoint, ["genPowerCfg"]);
            await reporting.batteryPercentageRemaining(endpoint);
            await reporting.batteryVoltage(endpoint);
        } catch (error) {
            // Do not prevent the IR functions from loading if battery reporting
            // is unsupported by this firmware.
            console.warn(
                `EyZEE TS1201: battery reporting setup failed: ${error.message}`,
            );
        }
    },
};

export default definition;