import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Advanced Storm Conductor",
    page_icon="⛈️",
    layout="wide",
)

st.markdown(
    """
    <style>
    html, body {
        background: #03060c;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

APP_HTML = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
    :root {
        color-scheme: dark;
    }

    * {
        box-sizing: border-box;
    }

    html, body {
        margin: 0;
        padding: 0;
        width: 100%;
        height: 100%;
        overflow: hidden;
        background: #03060c;
        color: #f8fafc;
        font-family: Arial, Helvetica, sans-serif;
    }

    #app {
        position: relative;
        width: 100%;
        height: 100%;
    }

    canvas {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: contain;
        background: #000;
        touch-action: none;
    }

    #ui {
        position: absolute;
        top: 12px;
        left: 12px;
        z-index: 30;
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        max-width: min(94vw, 1150px);
        padding: 10px 12px;
        border-radius: 16px;
        background: rgba(2, 8, 20, 0.58);
        border: 1px solid rgba(255, 255, 255, 0.12);
        backdrop-filter: blur(10px);
        box-shadow: 0 12px 34px rgba(0, 0, 0, 0.30);
    }

    button,
    select,
    input[type="range"] {
        border: none;
        outline: none;
    }

    button {
        border-radius: 10px;
        padding: 8px 11px;
        background: rgba(148, 163, 184, 0.16);
        color: #f8fafc;
        cursor: pointer;
        font-weight: 700;
        font-size: 12px;
        border: 1px solid rgba(255, 255, 255, 0.10);
        transition: transform 0.12s ease, background 0.12s ease;
    }

    button:hover {
        transform: translateY(-1px);
        background: rgba(148, 163, 184, 0.24);
    }

    button.active {
        background: rgba(34, 197, 94, 0.22);
        border-color: rgba(34, 197, 94, 0.45);
    }

    button.rec {
        background: rgba(185, 28, 28, 0.30);
        border-color: rgba(248, 113, 113, 0.45);
    }

    label {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 12px;
        color: #dbeafe;
        background: rgba(15, 23, 42, 0.35);
        padding: 6px 8px;
        border-radius: 10px;
        border: 1px solid rgba(255, 255, 255, 0.08);
    }

    input[type="range"] {
        width: 90px;
        accent-color: #38bdf8;
    }

    input[type="checkbox"] {
        accent-color: #38bdf8;
        transform: scale(1.1);
    }

    #status {
        position: absolute;
        right: 12px;
        bottom: 12px;
        z-index: 30;
        padding: 8px 10px;
        border-radius: 10px;
        font-size: 12px;
        color: #e2e8f0;
        background: rgba(2, 8, 20, 0.55);
        border: 1px solid rgba(255, 255, 255, 0.10);
        backdrop-filter: blur(8px);
    }
</style>
</head>
<body>
<div id="app">
    <canvas id="scene"></canvas>

    <div id="ui">
        <button id="autoBtn" class="active">Auto Demo: ON</button>
        <button id="calibrateBtn">Recalibrate</button>
        <button id="crescendoBtn">Crescendo</button>
        <button id="calmBtn">Calm</button>
        <button id="soundBtn">Sound: OFF</button>

        <label>
            Amplitude
            <input id="ampRange" type="range" min="0" max="1" step="0.01" value="0.45" />
        </label>

        <label>
            Speed
            <input id="speedRange" type="range" min="0" max="2.5" step="0.01" value="1.0" />
        </label>

        <label>
            Hold Arms High
            <input id="raiseCheck" type="checkbox" />
        </label>

        <select id="recordLength">
            <option value="5">5s</option>
            <option value="10">10s</option>
            <option value="20" selected>20s</option>
            <option value="40">40s</option>
            <option value="60">60s</option>
            <option value="80">80s max</option>
        </select>

        <button id="recordBtn">Record Video</button>
    </div>

    <div id="status">Starting...</div>
</div>

<script>
const W = 960;
const H = 540;

const canvas = document.getElementById('scene');
const ctx = canvas.getContext('2d');
canvas.width = W;
canvas.height = H;

const statusEl = document.getElementById('status');

const autoBtn = document.getElementById('autoBtn');
const calibrateBtn = document.getElementById('calibrateBtn');
const crescendoBtn = document.getElementById('crescendoBtn');
const calmBtn = document.getElementById('calmBtn');
const soundBtn = document.getElementById('soundBtn');
const ampRange = document.getElementById('ampRange');
const speedRange = document.getElementById('speedRange');
const raiseCheck = document.getElementById('raiseCheck');
const recordBtn = document.getElementById('recordBtn');
const recordLength = document.getElementById('recordLength');

function clamp(v, a = 0, b = 1) {
    return Math.max(a, Math.min(b, v));
}

function lerp(a, b, t) {
    return a + (b - a) * t;
}

function smoothstep(e0, e1, x) {
    if (e0 === e1) return x < e0 ? 0 : 1;
    const t = clamp((x - e0) / (e1 - e0), 0, 1);
    return t * t * (3 - 2 * t);
}

function lerpColor(c1, c2, t) {
    t = clamp(t);
    return [
        Math.round(lerp(c1[0], c2[0], t)),
        Math.round(lerp(c1[1], c2[1], t)),
        Math.round(lerp(c1[2], c2[2], t))
    ];
}

function rgba(c, a = 1) {
    return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
}

function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
}

const BAND_NAMES = [
    'Light overcast',
    'Rain',
    'Wind-bent rain + dark sky',
    'Lightning + thunder'
];

const state = {
    t: 0,
    last: performance.now() / 1000,
    fps: 60,

    auto: true,
    calibrated: false,
    calibT: 0,
    calibDur: 2.0,
    calibSamples: [],
    neutralWristRelPx: H * 0.205,

    intensity: 0,
    raw: 0,
    band: 0,
    bandCandidate: 0,
    bandCandidateT: 0,

    crescendoUntil: -1,
    lastCrescendo: -10,
    raiseHold: 0,

    wind: 0,

    flash: {
        start: -10,
        duration: 0.15,
        bolt: null,
        distance: 0
    },
    flashEvents: [],
    thunderEvents: [],
    lastFlashInfo: null,
    lastThunderInfo: null,

    drops: [],
    splashes: [],
    clouds: [],

    trailL: [],
    trailR: [],

    wristHistory: [],
    pointerHistory: [],

    manualAmp: 0.45,
    manualSpeed: 1.0,
    manualRaise: false,

    soundOn: false,

    recording: false,
    recordStopAt: 0,
    chunks: []
};

let recorder = null;
let audioCtx = null;
let masterGain = null;
let noiseBuffer = null;

function makeCloudSprite(w, h, alpha) {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const g = c.getContext('2d');

    const grad = g.createRadialGradient(w / 2, h / 2, 8, w / 2, h / 2, w / 2);
    grad.addColorStop(0, `rgba(255,255,255,${alpha})`);
    grad.addColorStop(1, 'rgba(255,255,255,0)');

    g.fillStyle = grad;
    g.beginPath();
    g.ellipse(w / 2, h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
    g.fill();

    return c;
}

const cloudSprites = [
    makeCloudSprite(260, 95, 0.72),
    makeCloudSprite(190, 75, 0.64),
    makeCloudSprite(330, 125, 0.54)
];

function initClouds() {
    state.clouds = [];
    for (let i = 0; i < 18; i++) {
        state.clouds.push({
            sprite: cloudSprites[i % cloudSprites.length],
            x: Math.random() * W,
            y: 18 + Math.random() * 180,
            scale: 0.45 + Math.random() * 1.35,
            speed: 3 + Math.random() * 17,
            alpha: 0.45 + Math.random() * 0.45
        });
    }
}

initClouds();

function bandFromIntensity(v) {
    if (v < 3) return 0;
    if (v < 6) return 1;
    if (v < 9) return 2;
    return 3;
}

function resetCalm() {
    state.intensity = 0;
    state.raw = 0;
    state.band = 0;
    state.bandCandidate = 0;
    state.bandCandidateT = state.t;
    state.crescendoUntil = -1;
    state.raiseHold = 0;
    state.flashEvents = [];
    state.thunderEvents = [];
    state.drops = [];
    state.splashes = [];
    state.trailL = [];
    state.trailR = [];
    state.lastFlashInfo = null;
    state.lastThunderInfo = null;
}

function startCalibration() {
    resetCalm();
    state.calibrated = false;
    state.calibT = 0;
    state.calibSamples = [];
}

function autoControls(t) {
    const dur = 80;
    const tt = t % dur;

    if (tt < state.calibDur) {
        return { amp: 0, speed: 0, raise: false };
    }

    const p = (tt - state.calibDur) / Math.max(1e-6, dur - state.calibDur);

    if (p < 0.16) {
        const q = smoothstep(0.0, 0.16, p);
        return {
            amp: 0.02 + 0.05 * q,
            speed: 0.25 + 0.25 * q,
            raise: false
        };
    }

    if (p < 0.45) {
        const q = smoothstep(0.16, 0.45, p);
        return {
            amp: 0.07 + 0.17 * q,
            speed: 0.50 + 0.90 * q,
            raise: false
        };
    }

    if (p < 0.70) {
        const q = smoothstep(0.45, 0.70, p);
        return {
            amp: 0.24 + 0.12 * q,
            speed: 1.40 + 0.80 * q,
            raise: false
        };
    }

    if (p < 0.76) {
        return { amp: 0.34, speed: 1.70, raise: true };
    }

    if (p < 0.88) {
        return { amp: 0.38, speed: 2.20, raise: true };
    }

    const q = smoothstep(0.88, 1.0, p);
    return {
        amp: 0.34 - 0.30 * q,
        speed: 2.00 - 1.60 * q,
        raise: q < 0.15
    };
}

function targetPose(t) {
    let amp = 0;
    let speed = 0;
    let raise = false;

    if (state.auto) {
        const c = autoControls(t);
        amp = c.amp;
        speed = c.speed;
        raise = c.raise;
    } else {
        amp = state.manualAmp * 0.38;
        speed = state.manualSpeed;
        raise = state.manualRaise;
    }

    if (t < state.crescendoUntil) {
        amp = Math.max(amp, 0.38);
        speed = Math.max(speed, 2.2);
        raise = true;
    }

    const cx = W * 0.5 + Math.sin(t * 0.7) * 14;
    const shoulderY = H * 0.52 + Math.sin(t * 1.2) * 4;

    const ls = { x: cx - W * 0.085, y: shoulderY };
    const rs = { x: cx + W * 0.085, y: shoulderY };
    const lh = { x: cx - W * 0.095, y: H * 0.88 };
    const rh = { x: cx + W * 0.095, y: H * 0.88 };
    const nose = { x: cx, y: shoulderY - H * 0.12 };

    let lw, rw, le, re;

    if (raise) {
        const lift = H * (0.30 + amp * 0.22);

        lw = {
            x: cx - W * 0.155 + Math.sin(t * 7.3) * 12,
            y: shoulderY - lift + Math.sin(t * 9.1) * 8
        };

        rw = {
            x: cx + W * 0.155 + Math.cos(t * 6.7) * 12,
            y: shoulderY - lift + Math.cos(t * 8.3) * 8
        };

        le = { x: cx - W * 0.135, y: shoulderY - lift * 0.45 };
        re = { x: cx + W * 0.135, y: shoulderY - lift * 0.45 };
    } else {
        const base = shoulderY + H * 0.205;
        const phase = t * Math.max(0.05, speed) * Math.PI * 2;

        const liftL = H * amp * (0.5 + 0.5 * Math.sin(phase));
        const liftR = H * amp * (0.5 + 0.5 * Math.sin(phase + 0.65));

        lw = {
            x: cx - W * 0.170 - Math.sin(phase * 0.82) * 42,
            y: base - liftL
        };

        rw = {
            x: cx + W * 0.170 + Math.cos(phase * 0.74) * 42,
            y: base - liftR
        };

        le = {
            x: lerp(ls.x, lw.x, 0.52) - 20,
            y: lerp(ls.y, lw.y, 0.52) + 16
        };

        re = {
            x: lerp(rs.x, rw.x, 0.52) + 20,
            y: lerp(rs.y, rw.y, 0.52) + 16
        };
    }

    return { cx, shoulderY, ls, rs, le, re, lw, rw, lh, rh, nose };
}

let currentPose = targetPose(0);

function updatePose(dt) {
    const target = targetPose(state.t);
    const k = 1 - Math.exp(-dt * 14);

    const keys = ['ls', 'rs', 'le', 're', 'lw', 'rw', 'lh', 'rh', 'nose'];

    for (const key of keys) {
        currentPose[key].x = lerp(currentPose[key].x, target[key].x, k);
        currentPose[key].y = lerp(currentPose[key].y, target[key].y, k);
    }

    currentPose.cx = lerp(currentPose.cx, target.cx, k);
    currentPose.shoulderY = (currentPose.ls.y + currentPose.rs.y) / 2;

    state.trailL.push({ x: currentPose.lw.x, y: currentPose.lw.y, t: state.t });
    state.trailR.push({ x: currentPose.rw.x, y: currentPose.rw.y, t: state.t });

    while (state.trailL.length && state.t - state.trailL[0].t > 0.55) state.trailL.shift();
    while (state.trailR.length && state.t - state.trailR[0].t > 0.55) state.trailR.shift();
}

function updateCalibration(dt) {
    if (state.calibrated) return;

    state.calibT += dt;

    const wrY = (currentPose.lw.y + currentPose.rw.y) / 2;
    const rel = wrY - currentPose.shoulderY;
    state.calibSamples.push(rel);

    if (state.calibSamples.length > 220) state.calibSamples.shift();

    if (state.calibT >= state.calibDur) {
        state.calibrated = true;

        if (state.calibSamples.length) {
            const avg = state.calibSamples.reduce((a, b) => a + b, 0) / state.calibSamples.length;
            if (Number.isFinite(avg)) state.neutralWristRelPx = avg;
        }
    }
}

function computePointerRaw() {
    while (state.pointerHistory.length && state.t - state.pointerHistory[0].t > 1.0) {
        state.pointerHistory.shift();
    }

    if (state.pointerHistory.length < 5) return 0;

    let minY = Infinity;
    let maxY = -Infinity;
    let dist = 0;

    for (let i = 0; i < state.pointerHistory.length; i++) {
        const p = state.pointerHistory[i];
        minY = Math.min(minY, p.y);
        maxY = Math.max(maxY, p.y);

        if (i > 0) {
            const q = state.pointerHistory[i - 1];
            dist += Math.hypot(p.x - q.x, p.y - q.y);
        }
    }

    const first = state.pointerHistory[0];
    const last = state.pointerHistory[state.pointerHistory.length - 1];
    const dt = last.t - first.t;

    if (dt <= 0) return 0;

    const speed = dist / dt;
    const rangeY = maxY - minY;

    const rangeScore = clamp(rangeY / (H * 0.45));
    const speedScore = clamp(speed / (W * 1.8));

    return 10 * (0.55 * rangeScore + 0.45 * speedScore);
}

function updateIntensity(dt) {
    const wrX = (currentPose.lw.x + currentPose.rw.x) / 2;
    const wrY = (currentPose.lw.y + currentPose.rw.y) / 2;
    const rel = wrY - currentPose.shoulderY;

    state.wristHistory.push({ t: state.t, rel, x: wrX, y: wrY });

    while (state.wristHistory.length && state.t - state.wristHistory[0].t > 1.0) {
        state.wristHistory.shift();
    }

    let poseRaw = 0;

    if (state.calibrated && state.wristHistory.length > 4) {
        let minLift = Infinity;
        let maxLift = -Infinity;
        let dist = 0;

        for (let i = 0; i < state.wristHistory.length; i++) {
            const p = state.wristHistory[i];
            const lift = state.neutralWristRelPx - p.rel;
            minLift = Math.min(minLift, lift);
            maxLift = Math.max(maxLift, lift);

            if (i > 0) {
                const q = state.wristHistory[i - 1];
                dist += Math.hypot(p.x - q.x, p.y - q.y);
            }
        }

        const first = state.wristHistory[0];
        const last = state.wristHistory[state.wristHistory.length - 1];
        const windowDt = last.t - first.t;

        const verticalRange = Math.max(0, maxLift - minLift);
        const speed = windowDt > 0 ? dist / windowDt : 0;

        const rangeScore = clamp(verticalRange / (H * 0.34));
        const speedScore = clamp(speed / (H * 2.6));

        poseRaw = 10 * (0.58 * rangeScore + 0.42 * speedScore);
    }

    if (!state.calibrated) poseRaw = 0;

    if (state.t < state.crescendoUntil) poseRaw = 10;

    const pointerRaw = state.auto ? 0 : computePointerRaw();
    const raw = Math.max(poseRaw, pointerRaw);

    state.raw = raw;

    const tau = 0.22;
    let next = state.intensity + (raw - state.intensity) * (1 - Math.exp(-dt / tau));

    if (state.t < state.crescendoUntil) next = 10;

    state.intensity = clamp(next, 0, 10);

    const b = bandFromIntensity(state.intensity);

    if (b !== state.bandCandidate) {
        state.bandCandidate = b;
        state.bandCandidateT = state.t;
    }

    if (state.t - state.bandCandidateT > 0.25) {
        state.band = state.bandCandidate;
    }
}

function updateCrescendoDetection(dt) {
    const sh = currentPose.shoulderY;
    const high =
        currentPose.lw.y < sh - H * 0.09 &&
        currentPose.rw.y < sh - H * 0.09;

    if (high) {
        state.raiseHold += dt;
    } else {
        state.raiseHold = 0;
    }

    if (
        state.raiseHold > 0.85 &&
        state.t > state.crescendoUntil + 0.5 &&
        state.t - state.lastCrescendo > 6.0
    ) {
        triggerCrescendo(false);
    }
}

function triggerCrescendo(force = false) {
    if (!force && state.t - state.lastCrescendo < 6.0) return;

    state.crescendoUntil = state.t + 3.0;
    state.lastCrescendo = state.t;

    const distances = [150, 320, 560];

    distances.forEach((d, i) => {
        state.flashEvents.push({
            time: state.t + 0.05 + i * 0.95,
            distance: d
        });
    });
}

function makeBolt() {
    const segs = [];
    const pts = [];

    let x = W * (0.2 + Math.random() * 0.6);
    let y = 0;

    pts.push([x, y]);

    while (y < H * 0.68) {
        x += (Math.random() - 0.5) * 95;
        y += 25 + Math.random() * 58;
        pts.push([x, y]);
    }

    for (let i = 1; i < pts.length; i++) {
        segs.push([
            pts[i - 1][0],
            pts[i - 1][1],
            pts[i][0],
            pts[i][1]
        ]);
    }

    const branches = 2 + Math.floor(Math.random() * 3);

    for (let b = 0; b < branches; b++) {
        const idx = 1 + Math.floor(Math.random() * Math.max(1, pts.length - 2));
        let [bx, by] = pts[idx];

        for (let j = 0; j < 4; j++) {
            const nx = bx + (Math.random() - 0.5) * 90;
            const ny = by + 20 + Math.random() * 50;

            segs.push([bx, by, nx, ny]);

            bx = nx;
            by = ny;
        }
    }

    return segs;
}

function startFlash(distance) {
    state.flash.start = state.t;
    state.flash.distance = distance;
    state.flash.bolt = makeBolt();
    state.lastFlashInfo = { distance, t: state.t };

    state.thunderEvents.push({
        time: state.t + distance / 343.0,
        distance
    });
}

function updateStormEvents(dt) {
    if (state.intensity >= 8.7 && state.t >= state.crescendoUntil) {
        const p = clamp((state.intensity - 8.7) / 1.3) * 1.2 + 0.12;

        if (Math.random() < p * dt) {
            state.flashEvents.push({
                time: state.t + Math.random() * 0.05,
                distance: 110 + Math.random() * 540
            });
        }
    }

    state.flashEvents = state.flashEvents.filter(e => {
        if (e.time <= state.t) {
            startFlash(e.distance);
            return false;
        }
        return true;
    });

    state.thunderEvents = state.thunderEvents.filter(e => {
        if (e.time <= state.t) {
            if (state.soundOn) playThunder(e.distance);
            state.lastThunderInfo = { distance: e.distance, t: state.t };
            return false;
        }
        return true;
    });
}

function updateClouds(dt) {
    for (const c of state.clouds) {
        c.x += (c.speed + state.wind * 0.30) * dt;

        const w = c.sprite.width * c.scale;

        if (c.x - w / 2 > W) {
            c.x = -w / 2;
            c.y = 18 + Math.random() * 180;
        }
    }
}

function addSplash(x, y) {
    if (state.splashes.length > 90) state.splashes.shift();

    state.splashes.push({
        x,
        y,
        r: 1,
        t: 0,
        life: 0.28
    });
}

function updateRain(dt) {
    const target = state.intensity < 3
        ? 0
        : Math.floor(70 + (state.intensity - 3) * 70);

    while (state.drops.length < target) {
        state.drops.push({
            x: Math.random() * W,
            y: -80 - Math.random() * 80,
            len: 8 + Math.random() * 18,
            vy: 320 + Math.random() * 220,
            drift: -20 + Math.random() * 40
        });
    }

    if (state.drops.length > target) {
        state.drops.length = target;
    }

    const windTarget = state.intensity < 6
        ? 0
        : 25 + (state.intensity - 6) * 38;

    state.wind = lerp(state.wind, windTarget, 1 - Math.exp(-dt * 2.0));

    const next = [];

    for (const d of state.drops) {
        d.vy = lerp(d.vy, 340 + state.intensity * 42, 1 - Math.exp(-dt * 1.2));
        d.x += (state.wind + d.drift) * dt;
        d.y += d.vy * dt;

        if (d.y < H + 30) {
            next.push(d);
        } else {
            if (state.intensity > 5 && Math.random() < 0.25) {
                addSplash(d.x, H - 2);
            }

            if (next.length < target) {
                d.x = Math.random() * W;
                d.y = -80 - Math.random() * 80;
                d.len = 8 + Math.random() * 18;
                d.drift = -20 + Math.random() * 40;
                next.push(d);
            }
        }
    }

    state.drops = next;

    const nextSplashes = [];

    for (const s of state.splashes) {
        s.t += dt;
        s.r += 90 * dt;

        if (s.t < s.life) nextSplashes.push(s);
    }

    state.splashes = nextSplashes;
}

function initAudio() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;

    audioCtx = new AC();

    const len = Math.floor(audioCtx.sampleRate * 2);
    noiseBuffer = audioCtx.createBuffer(1, len, audioCtx.sampleRate);

    const data = noiseBuffer.getChannelData(0);

    let last = 0;

    for (let i = 0; i < len; i++) {
        const white = Math.random() * 2 - 1;
        last = (last + 0.02 * white) / 1.02;
        data[i] = last * 3.5;
    }

    masterGain = audioCtx.createGain();
    masterGain.gain.value = 0.75;
    masterGain.connect(audioCtx.destination);
}

function playThunder(distance) {
    if (!audioCtx || !noiseBuffer || !state.soundOn) return;

    const src = audioCtx.createBufferSource();
    src.buffer = noiseBuffer;
    src.loop = true;

    const filter = audioCtx.createBiquadFilter();
    filter.type = 'lowpass';

    const gain = audioCtx.createGain();

    const now = audioCtx.currentTime;
    const near = clamp(1 - distance / 800, 0.15, 1);
    const dur = 1.2 + distance / 400;

    filter.frequency.setValueAtTime(180 + 700 * near, now);
    filter.frequency.exponentialRampToValueAtTime(45, now + dur);

    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(0.65 + 0.3 * near, now + 0.04);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + dur);

    src.connect(filter);
    filter.connect(gain);
    gain.connect(masterGain);

    src.start(now);
    src.stop(now + dur + 0.1);
}

function drawBackground() {
    const severity = state.intensity / 10;

    const top = lerpColor([232, 218, 202], [18, 15, 26], severity);
    const bottom = lerpColor([246, 241, 236], [62, 55, 66], severity);

    const grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, rgba(top));
    grad.addColorStop(1, rgba(bottom));

    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);
}

function drawClouds() {
    const severity = state.intensity / 10;
    const cloudAlpha = lerp(0.55, 0.22, severity);

    for (const c of state.clouds) {
        const w = c.sprite.width * c.scale;
        const h = c.sprite.height * c.scale;

        ctx.globalAlpha = c.alpha * cloudAlpha;
        ctx.drawImage(c.sprite, c.x - w / 2, c.y - h / 2, w, h);
    }

    ctx.globalAlpha = 1;
}

function drawRain() {
    if (state.band < 1 || !state.drops.length) return;

    const slant = state.band >= 2 ? state.wind * 0.045 : 0;

    ctx.strokeStyle = 'rgba(215,228,255,0.48)';
    ctx.lineWidth = 1.3;
    ctx.beginPath();

    for (const d of state.drops) {
        const dx = slant * (d.len / 18);
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x + dx, d.y + d.len);
    }

    ctx.stroke();

    if (state.splashes.length) {
        ctx.lineWidth = 1.5;

        for (const s of state.splashes) {
            const a = 0.35 * clamp(1 - s.t / s.life);
            ctx.strokeStyle = `rgba(230,240,255,${a})`;

            ctx.beginPath();
            ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
            ctx.stroke();
        }
    }
}

function drawTrail() {
    const trails = [state.trailL, state.trailR];

    ctx.lineCap = 'round';

    for (const trail of trails) {
        for (let i = 1; i < trail.length; i++) {
            const age = state.t - trail[i].t;
            const alpha = clamp(1 - age / 0.55) * 0.28;

            ctx.strokeStyle = `rgba(56,255,216,${alpha})`;
            ctx.lineWidth = 4;

            ctx.beginPath();
            ctx.moveTo(trail[i - 1].x, trail[i - 1].y);
            ctx.lineTo(trail[i].x, trail[i].y);
            ctx.stroke();
        }
    }
}

function drawPose() {
    const p = currentPose;

    const connections = [
        ['ls', 'le'],
        ['le', 'lw'],
        ['rs', 're'],
        ['re', 'rw'],
        ['ls', 'rs'],
        ['ls', 'lh'],
        ['rs', 'rh'],
        ['lh', 'rh'],
        ['nose', 'ls'],
        ['nose', 'rs']
    ];

    ctx.lineWidth = 4;
    ctx.strokeStyle = 'rgba(0,255,190,0.82)';
    ctx.beginPath();

    for (const [a, b] of connections) {
        ctx.moveTo(p[a].x, p[a].y);
        ctx.lineTo(p[b].x, p[b].y);
    }

    ctx.stroke();

    const points = ['nose', 'ls', 'rs', 'le', 're', 'lw', 'rw', 'lh', 'rh'];

    for (const key of points) {
        ctx.beginPath();
        ctx.arc(p[key].x, p[key].y, key === 'lw' || key === 'rw' ? 6 : 4, 0, Math.PI * 2);
        ctx.fillStyle = key === 'lw' || key === 'rw'
            ? 'rgba(255,214,102,0.95)'
            : 'rgba(0,200,255,0.92)';
        ctx.fill();
    }
}

function drawLightning() {
    const activeT = state.t - state.flash.start;

    if (activeT > state.flash.duration) return;

    const progress = clamp(activeT / state.flash.duration);

    if (progress < 0.7 && state.flash.bolt) {
        ctx.save();
        ctx.globalCompositeOperation = 'lighter';
        ctx.shadowColor = 'rgba(170,225,255,0.95)';
        ctx.shadowBlur = 18;
        ctx.strokeStyle = 'rgba(245,250,255,0.96)';
        ctx.lineWidth = 3;

        ctx.beginPath();

        for (const s of state.flash.bolt) {
            ctx.moveTo(s[0], s[1]);
            ctx.lineTo(s[2], s[3]);
        }

        ctx.stroke();
        ctx.restore();
    }

    const alpha = 0.9 * (1 - progress);

    if (alpha > 0.01) {
        ctx.fillStyle = `rgba(255,255,255,${alpha})`;
        ctx.fillRect(0, 0, W, H);
    }
}

function drawHUD() {
    ctx.save();

    ctx.fillStyle = 'rgba(4,10,22,0.52)';
    roundRect(12, 12, 390, 104, 16);
    ctx.fill();

    ctx.fillStyle = '#ffd166';
    ctx.font = '700 24px Arial';
    ctx.fillText('Advanced Storm Conductor', 24, 43);

    ctx.font = '14px Arial';
    ctx.fillStyle = '#e5e7eb';
    ctx.fillText(`Mode: ${state.auto ? 'Auto demo' : 'Manual conductor'}`, 24, 66);
    ctx.fillText(`Band: ${BAND_NAMES[state.band]}`, 24, 84);

    ctx.fillStyle = state.calibrated ? '#bef264' : '#7dd3fc';
    ctx.fillText(
        state.calibrated
            ? 'Calibrated'
            : `Calibrating ${Math.max(0, state.calibDur - state.calibT).toFixed(1)}s`,
        24,
        102
    );

    const meterX = W - 62;
    const meterY = 44;
    const meterW = 28;
    const meterH = H - 132;

    ctx.fillStyle = 'rgba(3,8,17,0.56)';
    roundRect(meterX - 8, meterY - 26, meterW + 16, meterH + 64, 16);
    ctx.fill();

    ctx.fillStyle = 'rgba(255,255,255,0.10)';
    roundRect(meterX, meterY, meterW, meterH, 10);
    ctx.fill();

    const fillH = meterH * clamp(state.intensity / 10);
    const grad = ctx.createLinearGradient(0, meterY + meterH, 0, meterY);
    grad.addColorStop(0, '#22c55e');
    grad.addColorStop(0.45, '#eab308');
    grad.addColorStop(0.75, '#f97316');
    grad.addColorStop(1, '#ef4444');

    if (fillH > 1) {
        ctx.fillStyle = grad;
        roundRect(meterX, meterY + meterH - fillH, meterW, fillH, 10);
        ctx.fill();
    }

    ctx.fillStyle = '#f8fafc';
    ctx.font = '700 18px Arial';
    ctx.fillText(state.intensity.toFixed(1), meterX - 2, meterY - 34);

    ctx.font = '12px Arial';
    ctx.fillStyle = '#cbd5e1';
    ctx.fillText('0-10', meterX + 2, meterY + meterH + 22);

    if (state.lastFlashInfo && state.t - state.lastFlashInfo.t < 4.0) {
        const d = state.lastFlashInfo.distance;
        const delay = d / 343;

        ctx.fillStyle = 'rgba(4,10,22,0.52)';
        roundRect(12, H - 54, 430, 36, 12);
        ctx.fill();

        ctx.fillStyle = '#bae6fd';
        ctx.font = '13px Arial';
        ctx.fillText(
            `Lightning ${Math.round(d)} m -> thunder in ${delay.toFixed(2)}s`,
            24,
            H - 31
        );
    }

    if (state.t < state.crescendoUntil) {
        ctx.font = '900 44px Arial';
        ctx.fillStyle = 'rgba(255,80,80,0.92)';
        ctx.shadowColor = 'rgba(255,80,80,0.55)';
        ctx.shadowBlur = 18;
        ctx.textAlign = 'center';
        ctx.fillText('CRESCENDO', W / 2, H * 0.17);
        ctx.shadowBlur = 0;
        ctx.textAlign = 'left';
    }

    ctx.restore();
}

function drawCalibration() {
    if (state.calibrated) return;

    ctx.fillStyle = 'rgba(2,6,12,0.52)';
    ctx.fillRect(0, 0, W, H);

    ctx.textAlign = 'center';

    ctx.fillStyle = '#ffffff';
    ctx.font = '700 32px Arial';
    ctx.fillText('Calibration: stand still / wait', W / 2, H * 0.44);

    ctx.fillStyle = '#7dd3fc';
    ctx.font = '900 52px Arial';
    ctx.fillText(
        Math.max(0, state.calibDur - state.calibT).toFixed(1),
        W / 2,
        H * 0.58
    );

    ctx.textAlign = 'left';
}

function drawRecording() {
    if (!state.recording) return;

    ctx.save();

    ctx.fillStyle = 'rgba(239,68,68,0.95)';
    ctx.beginPath();
    ctx.arc(W - 24, 24, 8, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = '#fecaca';
    ctx.font = '700 14px Arial';
    ctx.textAlign = 'right';
    ctx.fillText('REC', W - 40, 29);

    ctx.restore();
}

function update(dt) {
    state.t += dt;

    updatePose(dt);
    updateCalibration(dt);
    updateIntensity(dt);
    updateCrescendoDetection(dt);
    updateStormEvents(dt);
    updateClouds(dt);
    updateRain(dt);

    if (
        state.recording &&
        state.t >= state.recordStopAt &&
        recorder &&
        recorder.state === 'recording'
    ) {
        recorder.stop();
    }
}

function render() {
    drawBackground();
    drawClouds();
    drawRain();
    drawTrail();
    drawPose();
    drawLightning();
    drawHUD();
    drawCalibration();
    drawRecording();
}

let lastStatusUpdate = 0;

function updateStatus() {
    if (state.t - lastStatusUpdate < 0.12) return;
    lastStatusUpdate = state.t;

    statusEl.textContent =
        `Intensity ${state.intensity.toFixed(1)}/10 | ` +
        `${BAND_NAMES[state.band]} | ` +
        `FPS ${Math.round(state.fps)} | ` +
        `${state.recording ? 'Recording' : 'Live'}`;
}

function frame() {
    const now = performance.now() / 1000;
    let dt = now - state.last;
    state.last = now;

    dt = clamp(dt, 0.0001, 0.05);

    state.fps = lerp(state.fps, 1 / dt, 0.05);

    update(dt);
    render();
    updateStatus();

    requestAnimationFrame(frame);
}

requestAnimationFrame(frame);

canvas.addEventListener('pointermove', e => {
    const rect = canvas.getBoundingClientRect();

    const x = (e.clientX - rect.left) / rect.width * W;
    const y = (e.clientY - rect.top) / rect.height * H;

    state.pointerHistory.push({ t: state.t, x, y });

    if (state.pointerHistory.length > 140) {
        state.pointerHistory.shift();
    }
});

autoBtn.addEventListener('click', () => {
    state.auto = !state.auto;
    autoBtn.textContent = `Auto Demo: ${state.auto ? 'ON' : 'OFF'}`;
    autoBtn.classList.toggle('active', state.auto);
});

calibrateBtn.addEventListener('click', () => {
    startCalibration();
});

crescendoBtn.addEventListener('click', () => {
    triggerCrescendo(true);
});

calmBtn.addEventListener('click', () => {
    resetCalm();
});

soundBtn.addEventListener('click', async () => {
    if (!audioCtx) initAudio();

    if (audioCtx && audioCtx.state === 'suspended') {
        await audioCtx.resume();
    }

    state.soundOn = !state.soundOn;
    soundBtn.textContent = `Sound: ${state.soundOn ? 'ON' : 'OFF'}`;
    soundBtn.classList.toggle('active', state.soundOn);
});

ampRange.addEventListener('input', e => {
    state.manualAmp = parseFloat(e.target.value);
});

speedRange.addEventListener('input', e => {
    state.manualSpeed = parseFloat(e.target.value);
});

raiseCheck.addEventListener('change', e => {
    state.manualRaise = e.target.checked;
});

function pickMime() {
    const candidates = [
        'video/webm;codecs=vp9',
        'video/webm;codecs=vp8',
        'video/webm',
        'video/mp4'
    ];

    for (const c of candidates) {
        if (window.MediaRecorder && MediaRecorder.isTypeSupported(c)) {
            return c;
        }
    }

    return '';
}

function toggleRecording() {
    if (state.recording) {
        if (recorder && recorder.state === 'recording') {
            recorder.stop();
        }
        return;
    }

    if (!window.MediaRecorder) {
        statusEl.textContent = 'Recording not supported in this browser.';
        return;
    }

    const mime = pickMime();

    if (!mime) {
        statusEl.textContent = 'No supported video format found.';
        return;
    }

    const stream = canvas.captureStream(60);

    state.chunks = [];

    recorder = new MediaRecorder(stream, {
        mimeType: mime,
        videoBitsPerSecond: 6_000_000
    });

    recorder.ondataavailable = e => {
        if (e.data && e.data.size > 0) {
            state.chunks.push(e.data);
        }
    };

    recorder.onstop = () => {
        const blob = new Blob(state.chunks, { type: mime });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = `storm-conductor-${recordLength.value}s.webm`;

        document.body.appendChild(a);
        a.click();
        a.remove();

        setTimeout(() => URL.revokeObjectURL(url), 3000);

        state.recording = false;
        recordBtn.classList.remove('rec');
        recordBtn.textContent = 'Record Video';
    };

    const len = parseInt(recordLength.value, 10);

    state.recording = true;
    state.recordStopAt = state.t + len;

    recordBtn.classList.add('rec');
    recordBtn.textContent = `Stop ${len}s`;

    recorder.start(250);
}

recordBtn.addEventListener('click', toggleRecording);

startCalibration();
</script>
</body>
</html>
"""

components.html(APP_HTML, height=880, scrolling=False)