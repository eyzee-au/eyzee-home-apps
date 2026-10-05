const exposes = require('zigbee-herdsman-converters/lib/exposes');
const tuya = require('zigbee-herdsman-converters/lib/tuya');

const e = exposes.presets;
const ea = exposes.access;

const DP_BACKLIGHT_SWITCH = 16;
const DP_CHILD_LOCK = 101;
const DP_BACKLIGHT_STATUS = 107;
const DP_STATE = 141;
const DP_BRIGHTNESS = 142;
const DP_BRIGHTNESS_MIN = 143;
const DP_BRIGHTNESS_MAX = 144;
const DP_COUNTDOWN = 145;
const DP_POWER_ON_BEHAVIOUR = 146;
const DP_ENERGY = 20;
const DP_CURRENT = 21;
const DP_POWER = 22;
const DP_VOLTAGE = 23;
const DP107_EXPECTED_LENGTH = 21;

// --- Colour palette ---
const ledColours = [
    'red', 'orange', 'yellow', 'green', 'blue', 'indigo', 
    'violet', 'white', 'magenta', 'cyan', 'warm_white', 
    'warm_yellow', 'gold'
];

const ledColourHueSat = {
    red: {hue: 2, saturation: 1000},
    orange: {hue: 30, saturation: 1000},
    yellow: {hue: 57, saturation: 853},
    green: {hue: 130, saturation: 1000},
    blue: {hue: 241, saturation: 1000},
    indigo: {hue: 265, saturation: 980},
    violet: {hue: 281, saturation: 980},
    white: {hue: 0, saturation: 0},
    magenta: {hue: 300, saturation: 1000},
    cyan: {hue: 180, saturation: 1000},
    warm_white: {hue: 40, saturation: 200},
    warm_yellow: {hue: 50, saturation: 500},
    gold: {hue: 16, saturation: 1000},
        // Custom gold #D6AD60 (RGB 214, 173, 96)
    custom_gold: {hue: 39, saturation: 551},
};

const clamp = (value, min, max) => {
    const number = Number(value);
    if (Number.isNaN(number)) return min;
    return Math.min(Math.max(number, min), max);
};

const safeColour = (value, fallback) => {
    return ledColourHueSat[value] ? value : fallback;
};

const closestColour = (hue) => {
    let closest = 'red';
    let smallestDiff = Number.MAX_SAFE_INTEGER;

    for (const [name, value] of Object.entries(ledColourHueSat)) {
        const diff = Math.abs(value.hue - hue);
        if (diff < smallestDiff) {
            smallestDiff = diff;
            closest = name;
        }
    }

    return closest;
};

const makeColourBlock = (colour, brightness) => {
    const c = ledColourHueSat[colour] || ledColourHueSat.red;
    const b = Math.round(clamp(brightness, 1, 100));

    return [
        b,
        (c.hue >> 8) & 0xff,
        c.hue & 0xff,
        (c.saturation >> 8) & 0xff,
        c.saturation & 0xff,
    ];
};

const readColourBlock = (block) => {
    const brightness = block[0];
    const hue = (block[1] << 8) + block[2];
    const saturation = (block[3] << 8) + block[4];

    if (saturation < 50) {
        return {colour: 'white', brightness};
    }

    return {colour: closestColour(hue), brightness};
};

// --- DP107: Center button only (up/down arrows removed) ---
const buildDp107Payload = (state) => {
    const onColour = safeColour(state.center_on_color, 'red');
    const offColour = safeColour(state.center_off_color, 'blue');
    const onBrightness = state.center_on_brightness || 100;
    const offBrightness = state.center_off_brightness || 100;

    const payload = [
        0x01, // Full color mode
        ...makeColourBlock(onColour, onBrightness),    // Bytes 1-5
        ...makeColourBlock(offColour, offBrightness),  // Bytes 6-10
    ];

    // Pad to 21 bytes with zeros (for arrows)
    while (payload.length < DP107_EXPECTED_LENGTH) {
        payload.push(0);
    }

    return Buffer.from(payload);
};

const decodeDp107Payload = (payload) => {
    const buffer = Buffer.isBuffer(payload) ? payload : Buffer.from(payload);
    const result = {};

    if (buffer.length < 11) return result;

    const mode = buffer[0];
    result.backlight_engine_mode = mode === 1 ? 'full' : 'basic';

    if (buffer.length >= 6) {
        const centerOn = readColourBlock(buffer.slice(1, 6));
        result.center_on_color = centerOn.colour;
        result.center_on_brightness = centerOn.brightness;
    }

    if (buffer.length >= 11) {
        const centerOff = readColourBlock(buffer.slice(6, 11));
        result.center_off_color = centerOff.colour;
        result.center_off_brightness = centerOff.brightness;
    }

    return result;
};

// --- Custom fromZigbee for DP107 ---
const fzDp107Colour = {
    cluster: 'manuSpecificTuya',
    type: ['commandDataReport', 'commandDataResponse'],
    convert: (model, msg) => {
        const dpValues = msg.data.dpValues;
        if (!dpValues) return;

        const dp107 = dpValues.find((dpValue) => dpValue.dp === 107);
        if (!dp107) return;

        return decodeDp107Payload(dp107.data);
    },
};

// --- Custom toZigbee for DP107 ---
const tzDp107Colour = {
    key: ['center_on_color', 'center_off_color', 'center_on_brightness', 'center_off_brightness'],

    convertSet: async (entity, key, value, meta) => {
        const newState = {
            ...(meta.state || {}),
            [key]: value,
        };

        await tuya.sendDataPointBool(entity, DP_BACKLIGHT_SWITCH, true);
        await tuya.sendDataPointRaw(entity, DP_BACKLIGHT_STATUS, buildDp107Payload(newState));

        return {state: {[key]: value, backlight_switch: 'ON'}};
    },
};

// --- Updated tzLocal for backlight_mode ---
const tzLocal = {
    key: ['backlight_mode'],
    convertSet: async (entity, key, value, meta) => {
        if (key !== 'backlight_mode') {
            return {};
        }

        const allowedValues = new Set(['off', 'arrows_only', 'all']);
        if (!allowedValues.has(value)) {
            throw new Error(`Unsupported value for ${key}: ${value}`);
        }

        if (value === 'off') {
            await tuya.sendDataPointBool(entity, DP_BACKLIGHT_SWITCH, false);
            return {state: {backlight_mode: 'off', backlight_switch: 'OFF'}};
        }

        const currentState = meta?.state || {};
        const payload = buildDp107Payload(currentState);
        
        if (value === 'arrows_only') {
            payload[0] = 0; // Basic mode
        } else if (value === 'all') {
            payload[0] = 1; // Full color mode
        }

        await tuya.sendDataPointBool(entity, DP_BACKLIGHT_SWITCH, true);
        await tuya.sendDataPointRaw(entity, DP_BACKLIGHT_STATUS, payload);

        return {state: {backlight_mode: value, backlight_switch: 'ON'}};
    },
};

// --- Preserve original converters ---
const countdownConverter =
    (tuya.valueConverter && (tuya.valueConverter.value || tuya.valueConverter.countdown || tuya.valueConverter.raw)) ||
    tuya.valueConverter.raw;

const relayStatusEnum = tuya.valueConverterBasic.lookup({
    off: tuya.enum(0),
    on: tuya.enum(1),
    memory: tuya.enum(2),
});

// HA 0-100% <-> Tuya 10-1000
const tuyaBrightness10to1000 = {
    from: (value) => {
        const n = Number(value);
        if (!Number.isFinite(n)) return undefined;
        // Convert 0-100% to 10-1000
        const clamped = Math.min(100, Math.max(0, n));
        return Math.round((clamped * 990) / 100 + 10);
    },
    to: (value) => {
        const n = Number(value);
        if (!Number.isFinite(n)) return 0;
        // Convert 10-1000 to 0-100%
        const clamped = Math.min(1000, Math.max(10, n));
        return Math.round(((clamped - 10) * 100) / 990);
    },
};

function clampByte(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(255, Math.round(n)));
}

function bytesToCsv(bytes) {
    return bytes.map((byte) => String(clampByte(byte))).join(',');
}

function parseCsvBytes(value) {
    return String(value ?? '')
        .split(',')
        .map((part) => Number.parseInt(part.trim(), 10))
        .filter((part) => Number.isFinite(part))
        .map((part) => clampByte(part));
}

function decodeDp107(value) {
    let bytes;

    if (Buffer.isBuffer(value)) {
        bytes = [...value].map((byte) => clampByte(byte));
    } else if (Array.isArray(value)) {
        bytes = value.map((byte) => clampByte(byte));
    } else {
        bytes = parseCsvBytes(value);
    }

    const validLength = bytes.length === DP107_EXPECTED_LENGTH;
    const engineMode = bytes.length > 0 && bytes[0] === 1 ? 'full' : 'basic';

    let colorInfo = {};
    if (bytes.length >= 11) {
        const centerOn = readColourBlock(bytes.slice(1, 6));
        const centerOff = readColourBlock(bytes.slice(6, 11));
        colorInfo = {
            center_on_color: centerOn.colour,
            center_on_brightness: centerOn.brightness,
            center_off_color: centerOff.colour,
            center_off_brightness: centerOff.brightness,
        };
    }

    return {
        bytes,
        csv: bytesToCsv(bytes),
        length: bytes.length,
        validLength,
        engineMode,
        ...colorInfo,
    };
}

function normaliseDp107ForWrite(value) {
    const decoded = decodeDp107(value);
    const bytes = decoded.bytes.slice(0, DP107_EXPECTED_LENGTH);

    while (bytes.length < DP107_EXPECTED_LENGTH) {
        bytes.push(0);
    }

    return bytes;
}

// --- Definition ---
const definition = {
    fingerprint: [
        {modelID: 'TS0601', manufacturerName: '_TZE200_6fjev1mn'},
        {modelID: 'TS0601', manufacturerName: '_TZE200_7iqgciln'}
    ],
    model: 'EyZEE-TS0601-Dimmer-Prod-v1.1',
    vendor: 'EyZEE',
    description: 'Tuya Zigbee dimmer - with RGB backlight control for center button',
    fromZigbee: [tuya.fz.datapoints, fzDp107Colour],
    toZigbee: [tzLocal, tzDp107Colour, tuya.tz.datapoints],
    onEvent: tuya.onEventSetTime,
    configure: async (device, coordinatorEndpoint, logger) => {
        await tuya.configureMagicPacket(device, coordinatorEndpoint, logger);
    },
    meta: {
        tuyaDatapoints: [
            [DP_STATE, 'state', tuya.valueConverter.onOff],
            [DP_BRIGHTNESS, 'brightness', tuyaBrightness10to1000],
            [DP_BRIGHTNESS_MIN, 'brightness_min', tuyaBrightness10to1000],
            [DP_BRIGHTNESS_MAX, 'brightness_max', tuyaBrightness10to1000],
            [DP_POWER_ON_BEHAVIOUR, 'power_on_behavior', relayStatusEnum],
            [DP_COUNTDOWN, 'countdown', countdownConverter],
            [DP_BACKLIGHT_SWITCH, 'backlight_switch', tuya.valueConverter.onOff],
            [DP_CHILD_LOCK, 'child_lock', tuya.valueConverter.onOff],
            [DP_ENERGY, 'energy', tuya.valueConverter.divideBy100],
            [DP_CURRENT, 'current', tuya.valueConverter.raw],
            [DP_POWER, 'power', tuya.valueConverter.raw],
            [DP_VOLTAGE, 'voltage', tuya.valueConverter.divideBy10],
        ],
    },
    exposes: [
        e.light().withBrightness().withDescription('Dimmer control'),
        
        // --- Center Button Backlight ---
        e.enum('center_on_color', ea.ALL, ledColours).withDescription('Center button color when dimmer is ON'),
        e.numeric('center_on_brightness', ea.ALL).withValueMin(1).withValueMax(100).withValueStep(1).withUnit('%').withDescription('Center button brightness when dimmer is ON'),
        e.enum('center_off_color', ea.ALL, ledColours).withDescription('Center button color when dimmer is OFF'),
        e.numeric('center_off_brightness', ea.ALL).withValueMin(1).withValueMax(100).withValueStep(1).withUnit('%').withDescription('Center button brightness when dimmer is OFF'),
        
        e
            .enum('backlight_mode', ea.ALL, ['off', 'arrows_only', 'all'])
            .withDescription('Backlight mode: off = all LEDs off, arrows_only = outer arrows only (basic), all = all LEDs with colors (full)'),
        e
            .binary('backlight_switch', ea.ALL, 'ON', 'OFF')
            .withDescription('Master backlight switch (use backlight_mode for higher-level control)'),
        e.binary('child_lock', ea.ALL, 'ON', 'OFF').withDescription('Child lock; prevents button presses'),
        e.numeric('brightness_min', ea.ALL).withValueMin(0).withValueMax(100).withValueStep(1).withUnit('%').withDescription('Minimum brightness limit'),
        e.numeric('brightness_max', ea.ALL).withValueMin(0).withValueMax(100).withValueStep(1).withUnit('%').withDescription('Maximum brightness limit'),
        e.numeric('countdown', ea.ALL).withUnit('s').withDescription('Countdown timer in seconds'),
        e.enum('power_on_behavior', ea.ALL, ['off', 'on', 'memory']).withDescription('Behaviour when power is restored'),
        e.power().withDescription('Current power consumption (watts)'),
        e.energy().withDescription('Accumulated energy usage (kWh)'),
        e.numeric('current', ea.STATE).withUnit('mA').withDescription('Electrical current (milliamps)'),
        e.numeric('voltage', ea.STATE).withUnit('V').withDescription('Voltage (volts)'),
        e.text('backlight_status_raw', ea.STATE).withDescription('Raw DP107 snapshot as comma-separated bytes'),
    ],
};

module.exports = definition;