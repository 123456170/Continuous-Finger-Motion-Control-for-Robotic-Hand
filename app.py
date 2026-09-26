import streamlit as st
import numpy as np
import time
import math
import os
import tempfile
import threading
from collections import deque

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

try:
    import cv2
    CV2_AVAILABLE = True
except Exception:
    CV2_AVAILABLE = False

try:
    import mediapipe as mp
    MP_AVAILABLE = True
except Exception:
    MP_AVAILABLE = False

try:
    import imageio
    IMAGEIO_AVAILABLE = True
except Exception:
    IMAGEIO_AVAILABLE = False


st.set_page_config(
    page_title="Continuous Finger-Motion Control",
    page_icon="🖐️",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not CV2_AVAILABLE:
    st.error("OpenCV is required for this application. Install dependencies from requirements.txt.")
    st.stop()

if CV2_AVAILABLE:
    try:
        cv2.setNumThreads(1)
    except Exception:
        pass


# ============================================================
# Constants
# ============================================================

FRAME_W, FRAME_H = 640, 480
COMBINED_W = FRAME_W * 2

FINGERS = ["Thumb", "Index", "Middle", "Ring", "Pinky"]
JOINT_SUFFIX = ["J1", "J2", "J3"]
JOINT_LABELS = [f"{f} {j}" for f in FINGERS for j in JOINT_SUFFIX]

FINGER_TIPS = [4, 8, 12, 16, 20]
FINGER_MCP_INDICES = [1, 5, 9, 13, 17]

FINGER_LANDMARK_CHAINS = [
    (5, 6, 7, 8),
    (9, 10, 11, 12),
    (13, 14, 15, 16),
    (17, 18, 19, 20),
]

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]

ROBOT_MIN = np.zeros(15, dtype=float)
ROBOT_MAX = np.array(
    [
        60, 70, 60,
        90, 100, 80,
        90, 100, 80,
        90, 100, 80,
        80, 90, 70,
    ],
    dtype=float,
)

THUMB_CMC = np.array([-0.34, 0.18, 0.02], dtype=float)

FINGER_MCP_POSITIONS = {
    "Index": np.array([-0.22, 0.80, 0.00], dtype=float),
    "Middle": np.array([0.00, 0.85, 0.00], dtype=float),
    "Ring": np.array([0.22, 0.80, 0.00], dtype=float),
    "Pinky": np.array([0.42, 0.72, 0.00], dtype=float),
}

FINGER_LENGTHS = {
    "Thumb": np.array([0.20, 0.18, 0.15], dtype=float),
    "Index": np.array([0.32, 0.22, 0.16], dtype=float),
    "Middle": np.array([0.34, 0.24, 0.17], dtype=float),
    "Ring": np.array([0.31, 0.22, 0.16], dtype=float),
    "Pinky": np.array([0.26, 0.18, 0.14], dtype=float),
}

THUMB_INITIAL_DIR = np.array([0.45, 0.78, 0.25], dtype=float)
THUMB_AXIS = np.array([0.88, -0.30, 0.15], dtype=float)

FINGER_INITIAL_DIR = np.array([0.0, 1.0, 0.0], dtype=float)
FINGER_AXIS = np.array([1.0, 0.0, 0.0], dtype=float)


# ============================================================
# Utilities
# ============================================================

def rerun_app():
    try:
        st.rerun()
    except Exception:
        st.experimental_rerun()


def normalize_vec(v, fallback=None):
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n < 1e-9:
        if fallback is None:
            return np.array([0.0, 1.0, 0.0], dtype=float)
        return np.asarray(fallback, dtype=float)
    return v / n


def rotate_vec(v, axis, angle):
    v = np.asarray(v, dtype=float)
    axis = normalize_vec(axis)
    c = math.cos(angle)
    s = math.sin(angle)
    return v * c + np.cross(axis, v) * s + axis * np.dot(axis, v) * (1.0 - c)


def angle_between(v1, v2):
    v1 = np.asarray(v1, dtype=float)
    v2 = np.asarray(v2, dtype=float)
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)

    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0

    cos_val = np.dot(v1, v2) / (n1 * n2)
    cos_val = float(np.clip(cos_val, -1.0, 1.0))
    return float(np.degrees(np.arccos(cos_val)))


def low_pass(prev, raw, dt, tau):
    prev = np.asarray(prev, dtype=float)
    raw = np.asarray(raw, dtype=float)

    if tau <= 1e-4:
        return raw.copy()

    alpha = 1.0 - math.exp(-float(dt) / max(float(tau), 1e-4))
    return prev + alpha * (raw - prev)


def rate_limit(prev, target, max_rate, dt):
    prev = np.asarray(prev, dtype=float)
    target = np.asarray(target, dtype=float)
    max_delta = float(max_rate) * float(dt)
    delta = np.clip(target - prev, -max_delta, max_delta)
    return prev + delta


def wrap_angle(a):
    return math.atan2(math.sin(a), math.cos(a))


# ============================================================
# Hand normalization, joint extraction, forward kinematics
# ============================================================

def normalize_landmarks(pts):
    pts = np.asarray(pts, dtype=float).copy()
    pts = np.nan_to_num(pts, nan=0.0, posinf=0.0, neginf=0.0)

    if pts.shape != (21, 3):
        return pts

    wrist = pts[0].copy()
    pts -= wrist

    palm_len = np.linalg.norm(pts[9])
    if palm_len < 1e-6:
        palm_len = 1.0

    pts /= palm_len

    y_axis = normalize_vec(pts[9], fallback=[0.0, 1.0, 0.0])

    x_raw = pts[17] - pts[5]
    x_axis = normalize_vec(x_raw, fallback=[1.0, 0.0, 0.0])
    x_axis = x_axis - np.dot(x_axis, y_axis) * y_axis
    x_axis = normalize_vec(x_axis, fallback=[1.0, 0.0, 0.0])

    z_axis = np.cross(x_axis, y_axis)
    if np.linalg.norm(z_axis) < 1e-6:
        z_axis = np.array([0.0, 0.0, 1.0], dtype=float)

    z_axis = normalize_vec(z_axis)
    y_axis = normalize_vec(np.cross(z_axis, x_axis))

    R = np.column_stack((x_axis, y_axis, z_axis))

    if np.linalg.det(R) < 0:
        R[:, 2] *= -1.0

    normalized = pts @ R
    return np.nan_to_num(normalized, nan=0.0, posinf=0.0, neginf=0.0)


def extract_joint_angles(pts):
    pts = np.asarray(pts, dtype=float)
    pts = np.nan_to_num(pts, nan=0.0, posinf=0.0, neginf=0.0)

    angles = np.zeros(15, dtype=float)

    if pts.shape != (21, 3):
        return angles

    palm_dir = normalize_vec(pts[9] - pts[0], fallback=[0.0, 1.0, 0.0])

    v0 = normalize_vec(pts[1] - pts[0], fallback=[0.0, 1.0, 0.0])
    v1 = normalize_vec(pts[2] - pts[1], fallback=[0.0, 1.0, 0.0])
    v2 = normalize_vec(pts[3] - pts[2], fallback=[0.0, 1.0, 0.0])
    v3 = normalize_vec(pts[4] - pts[3], fallback=[0.0, 1.0, 0.0])

    angles[0] = angle_between(v0, v1)
    angles[1] = angle_between(v1, v2)
    angles[2] = angle_between(v2, v3)

    for k, (mcp, pip, dip, tip) in enumerate(FINGER_LANDMARK_CHAINS, start=1):
        u1 = normalize_vec(pts[pip] - pts[mcp], fallback=[0.0, 1.0, 0.0])
        u2 = normalize_vec(pts[dip] - pts[pip], fallback=[0.0, 1.0, 0.0])
        u3 = normalize_vec(pts[tip] - pts[dip], fallback=[0.0, 1.0, 0.0])

        angles[3 * k + 0] = angle_between(palm_dir, u1)
        angles[3 * k + 1] = angle_between(u1, u2)
        angles[3 * k + 2] = angle_between(u2, u3)

    return np.clip(np.nan_to_num(angles, nan=0.0, posinf=0.0, neginf=0.0), 0.0, 180.0)


def forward_chain(start, direction, axis, lengths, angles_deg):
    pts = []
    current = np.asarray(start, dtype=float).copy()
    dir_vec = normalize_vec(direction)
    axis_vec = normalize_vec(axis)

    for length, ang in zip(lengths, angles_deg):
        ang_rad = math.radians(float(ang))
        dir_vec = normalize_vec(rotate_vec(dir_vec, axis_vec, ang_rad))
        current = current + dir_vec * float(length)
        pts.append(current.copy())

    return np.array(pts, dtype=float)


def build_hand_from_angles(angles):
    angles = np.asarray(angles, dtype=float)
    angles = np.nan_to_num(angles, nan=0.0, posinf=0.0, neginf=0.0)

    pts = np.zeros((21, 3), dtype=float)
    pts[0] = np.zeros(3, dtype=float)

    pts[1] = THUMB_CMC
    thumb_chain = forward_chain(
        pts[1],
        THUMB_INITIAL_DIR,
        THUMB_AXIS,
        FINGER_LENGTHS["Thumb"],
        angles[0:3],
    )
    pts[2:5] = thumb_chain

    finger_names = ["Index", "Middle", "Ring", "Pinky"]
    mcp_indices = [5, 9, 13, 17]

    for i, name in enumerate(finger_names):
        mcp_pos = FINGER_MCP_POSITIONS[name]
        pts[mcp_indices[i]] = mcp_pos

        chain = forward_chain(
            mcp_pos,
            FINGER_INITIAL_DIR,
            FINGER_AXIS,
            FINGER_LENGTHS[name],
            angles[3 * (i + 1): 3 * (i + 2)],
        )

        pts[mcp_indices[i] + 1: mcp_indices[i] + 4] = chain

    return pts


NOMINAL_PALM_LENGTH = float(np.linalg.norm(build_hand_from_angles(np.zeros(15))[9]))
if NOMINAL_PALM_LENGTH < 1e-6:
    NOMINAL_PALM_LENGTH = 1.0


# ============================================================
# Synthetic demo generator
# ============================================================

def synthetic_joint_angles(t, preset):
    angles = np.zeros(15, dtype=float)
    t = float(t)

    def osc(freq, phase=0.0):
        return 0.5 + 0.5 * np.sin(freq * t + phase)

    if preset == "Open":
        angles[:] = 3.0
        return angles

    if preset == "Fist":
        angles[0:3] = [35.0, 55.0, 45.0]
        for f in range(1, 5):
            angles[3 * f: 3 * f + 3] = [55.0, 95.0, 75.0]
        return angles

    if preset == "Natural":
        for f in range(5):
            base = 15.0 + 50.0 * osc(0.8, f * 0.8)
            if f == 0:
                base *= 0.60

            angles[3 * f + 0] = 0.45 * base + 5.0 * np.sin(0.4 * t + f)
            angles[3 * f + 1] = base
            angles[3 * f + 2] = 0.65 * base + 4.0 * np.sin(0.6 * t + f)

    elif preset == "Grasp":
        g = 20.0 + 80.0 * osc(1.2, 0.0)
        angles[0:3] = [0.45 * g, 0.70 * g, 0.55 * g]

        for f in range(1, 5):
            angles[3 * f + 0] = 0.50 * g
            angles[3 * f + 1] = g
            angles[3 * f + 2] = 0.80 * g

    elif preset == "Point":
        index = 8.0 + 6.0 * osc(1.5, 0.0)
        angles[3:6] = [0.35 * index, index, 0.45 * index]

        thumb = 25.0 + 10.0 * osc(0.9, 0.7)
        angles[0:3] = [0.50 * thumb, thumb, 0.65 * thumb]

        for f in [2, 3, 4]:
            bend = 75.0 + 15.0 * osc(0.9, f * 0.5)
            angles[3 * f + 0] = 0.45 * bend
            angles[3 * f + 1] = bend
            angles[3 * f + 2] = 0.70 * bend

    elif preset == "Pinch":
        pinch = 30.0 + 30.0 * osc(1.3, 0.0)
        angles[0:3] = [0.55 * pinch, pinch, 0.75 * pinch]
        angles[3:6] = [0.40 * pinch, pinch, 0.55 * pinch]

        for f in [2, 3, 4]:
            small = 10.0 + 5.0 * osc(0.8, f)
            angles[3 * f: 3 * f + 3] = [0.4 * small, small, 0.5 * small]

    elif preset == "Wave":
        for f in range(5):
            a = 15.0 + 70.0 * osc(1.6, -f * 0.7)
            if f == 0:
                a *= 0.55

            angles[3 * f + 0] = 0.40 * a
            angles[3 * f + 1] = a
            angles[3 * f + 2] = 0.70 * a

    else:
        for f in range(5):
            a = 20.0 + 45.0 * osc(0.9, f * 0.6)
            angles[3 * f: 3 * f + 3] = [0.45 * a, a, 0.70 * a]

    return np.clip(angles, 0.0, 120.0)


def synthetic_landmarks(t, preset, noise=0.0):
    angles = synthetic_joint_angles(t, preset)
    pts = build_hand_from_angles(angles)
    pts = normalize_landmarks(pts)

    if noise is not None and noise > 1e-6:
        pts += np.random.normal(0.0, float(noise) * 0.006, pts.shape)

    return np.nan_to_num(pts, nan=0.0, posinf=0.0, neginf=0.0)


# ============================================================
# Threaded webcam capture and smoothing
# ============================================================

class WebcamReader:
    def __init__(self, index=0):
        self.index = index
        self.cap = None
        self.lock = threading.Lock()
        self.frame = None
        self.running = False
        self.failed = False
        self.thread = None

    def open(self):
        try:
            self.cap = cv2.VideoCapture(self.index)

            if not self.cap.isOpened():
                self.failed = True
                return False

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass

            try:
                self.cap.set(cv2.CAP_PROP_FPS, 30)
            except Exception:
                pass

            return True

        except Exception:
            self.failed = True
            return False

    def _loop(self):
        while self.running and self.cap is not None and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
            except Exception:
                ret = False
                frame = None

            if ret and frame is not None:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.005)

        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass

    def start(self):
        if self.running or self.failed:
            return

        if not self.open():
            return

        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def latest(self):
        with self.lock:
            if self.frame is None:
                return None
            return self.frame.copy()

    def stop(self):
        self.running = False


class ArrayEMA:
    def __init__(self):
        self.prev = None

    def reset(self):
        self.prev = None

    def __call__(self, x, dt, tau):
        x = np.asarray(x, dtype=float)

        if self.prev is None:
            self.prev = x.copy()
            return x.copy()

        tau = max(float(tau), 1e-4)
        alpha = 1.0 - math.exp(-float(dt) / tau)

        self.prev = self.prev + alpha * (x - self.prev)
        return self.prev.copy()


def stop_camera_reader():
    reader = st.session_state.get("cam_reader")

    if reader is not None:
        try:
            reader.stop()
        except Exception:
            pass

    st.session_state.cam_reader = None
    st.session_state.camera_failed = False


def get_camera_reader():
    if not CV2_AVAILABLE:
        return None

    if st.session_state.get("camera_failed", False):
        return None

    if "cam_reader" not in st.session_state or st.session_state.cam_reader is None:
        reader = WebcamReader(0)
        reader.start()

        if reader.failed:
            st.session_state.camera_failed = True
            return None

        st.session_state.cam_reader = reader

    return st.session_state.cam_reader


def get_mp_hands():
    if not MP_AVAILABLE:
        return None

    if "mp_hands" not in st.session_state:
        try:
            st.session_state.mp_hands = mp.solutions.hands.Hands(
                max_num_hands=1,
                model_complexity=0,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7,
            )
        except Exception:
            st.session_state.mp_hands = None

    return st.session_state.mp_hands


def get_webcam_pose(cfg=None):
    cfg = cfg or {}

    if not CV2_AVAILABLE:
        return None, None, "OpenCV unavailable"

    reader = get_camera_reader()

    if reader is None:
        return None, None, "Camera unavailable"

    frame = reader.latest()

    if frame is None:
        return None, None, "Camera warming up"

    frame = cv2.resize(frame, (FRAME_W, FRAME_H))

    if MP_AVAILABLE:
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            hands = get_mp_hands()

            if hands is not None:
                results = hands.process(rgb)

                if results.multi_hand_landmarks:
                    hand = results.multi_hand_landmarks[0]

                    raw_img = np.array(
                        [[lm.x, lm.y, lm.z] for lm in hand.landmark],
                        dtype=float,
                    )

                    raw_img = np.nan_to_num(raw_img, nan=0.0, posinf=0.0, neginf=0.0)

                    now = time.time()
                    dt_img = now - st.session_state.get("last_img_landmark_time", now - 0.033)
                    dt_img = float(np.clip(dt_img, 0.005, 0.20))
                    st.session_state.last_img_landmark_time = now

                    if "img_smoother" not in st.session_state:
                        st.session_state.img_smoother = ArrayEMA()

                    camera_tau = float(cfg.get("camera_tau", 0.18))

                    smoothed_img = st.session_state.img_smoother(
                        raw_img,
                        dt_img,
                        camera_tau,
                    )

                    smoothed_img = np.clip(smoothed_img, -0.2, 1.2)

                    h, w = frame.shape[:2]

                    for a, b in HAND_CONNECTIONS:
                        pa = smoothed_img[a]
                        pb = smoothed_img[b]

                        if (
                            0.0 <= pa[0] <= 1.0
                            and 0.0 <= pa[1] <= 1.0
                            and 0.0 <= pb[0] <= 1.0
                            and 0.0 <= pb[1] <= 1.0
                        ):
                            p1 = (int(pa[0] * w), int(pa[1] * h))
                            p2 = (int(pb[0] * w), int(pb[1] * h))

                            cv2.line(frame, p1, p2, (0, 220, 120), 2, cv2.LINE_AA)

                    for p in smoothed_img:
                        if 0.0 <= p[0] <= 1.0 and 0.0 <= p[1] <= 1.0:
                            cv2.circle(
                                frame,
                                (int(p[0] * w), int(p[1] * h)),
                                3,
                                (0, 180, 255),
                                -1,
                                cv2.LINE_AA,
                            )

                    pts = np.column_stack(
                        (
                            smoothed_img[:, 0] - 0.5,
                            0.5 - smoothed_img[:, 1],
                            -2.0 * smoothed_img[:, 2],
                        )
                    )

                    if results.multi_handedness:
                        try:
                            label = results.multi_handedness[0].classification[0].label
                            if str(label).lower() == "left":
                                pts[:, 0] *= -1.0
                        except Exception:
                            pass

                    pts = normalize_landmarks(pts)
                    return frame, pts, "Webcam smoothed"

                else:
                    if "img_smoother" in st.session_state:
                        st.session_state.img_smoother.reset()

                    st.session_state.last_img_landmark_time = time.time()

        except Exception:
            pass

    return frame, None, "Webcam no landmarks"


def get_current_pose(cfg):
    source = cfg.get("source", "Synthetic demo")
    preset = cfg.get("preset", "Natural")
    noise = cfg.get("noise", 0.0)

    if source.startswith("Webcam"):
        frame, pts, msg = get_webcam_pose(cfg)

        if pts is not None:
            return frame, pts, msg, "webcam"

        fallback_pts = synthetic_landmarks(
            st.session_state.sim_time,
            preset,
            noise,
        )

        return frame, fallback_pts, msg + " -> synthetic fallback", "synthetic"

    stop_camera_reader()

    pts = synthetic_landmarks(
        st.session_state.sim_time,
        preset,
        noise,
    )

    return None, pts, "Synthetic demo", "synthetic"


# ============================================================
# Drawing and visualization
# ============================================================

def project_point(p, view, w, h):
    p = np.asarray(p, dtype=float)
    cx = int(w * 0.5)
    cy = int(h * 0.55)
    scale = 170

    if not np.all(np.isfinite(p)):
        return cx, cy

    if view == "sagittal":
        u = cx + int((p[2] + 0.15 * p[0]) * scale)
        v = cy - int(p[1] * scale)
    else:
        u = cx + int((p[0] + 0.35 * p[2]) * scale)
        v = cy - int((p[1] - 0.15 * p[2]) * scale)

    return int(u), int(v)


def draw_skeleton(img, pts, color, view="pseudo"):
    if pts is None:
        return

    pts = np.asarray(pts, dtype=float)

    if pts.shape != (21, 3):
        return

    h, w = img.shape[:2]
    proj = [project_point(p, view, w, h) for p in pts]

    for a, b in HAND_CONNECTIONS:
        cv2.line(img, proj[a], proj[b], (170, 170, 180), 2, cv2.LINE_AA)

    for p in proj:
        cv2.circle(img, p, 3, color, -1, cv2.LINE_AA)


def put_hud(img, lines, estop=False):
    y = 26

    for line in lines:
        cv2.putText(
            img,
            str(line),
            (12, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (235, 235, 235),
            1,
            cv2.LINE_AA,
        )
        y += 22

    if estop:
        cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), (0, 0, 220), 8)
        cv2.putText(
            img,
            "EMERGENCY STOP ACTIVE",
            (12, img.shape[0] - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (80, 80, 255),
            2,
            cv2.LINE_AA,
        )


def make_scene_frame(human_pts, robot_pts, left_image=None, info=None):
    info = info or {}

    left = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    left[:] = (25, 28, 35)

    if left_image is not None:
        left = cv2.resize(left_image, (FRAME_W, FRAME_H))
    else:
        draw_skeleton(left, human_pts, color=(80, 220, 120), view="pseudo")
        cv2.putText(
            left,
            "Human hand normalized",
            (12, FRAME_H - 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (200, 220, 200),
            1,
            cv2.LINE_AA,
        )

    right = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    right[:] = (20, 22, 30)

    draw_skeleton(right, robot_pts, color=(255, 180, 0), view="sagittal")

    cv2.putText(
        right,
        "Robot hand simulation",
        (12, FRAME_H - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (210, 210, 220),
        1,
        cv2.LINE_AA,
    )

    combined = np.hstack([left, right])

    hud_lines = [
        f"Source: {info.get('source', 'N/A')}",
        f"Mode: {info.get('control_mode', 'N/A')}",
        f"t={info.get('elapsed', 0.0):.1f}/{info.get('duration', 0.0):.0f}s  FPS={info.get('fps', 0.0):.0f}",
        f"Latency={info.get('latency', 0.0):.0f} ms  Error={info.get('error', 0.0):.1f} deg",
        str(info.get("message", "")),
    ]

    put_hud(combined, hud_lines, estop=bool(info.get("estop", False)))

    return combined


# ============================================================
# Video recorder
# ============================================================

class VideoRecorder:
    def __init__(self, fps, size):
        self.fps = int(fps)
        self.size = size
        self.ok = False
        self.backend = None
        self.path = None
        self.writer = None
        self._init_writer()

    def _init_writer(self):
        stamp = int(time.time())
        tmpdir = tempfile.gettempdir()

        if CV2_AVAILABLE:
            candidates = [
                ("mp4v", ".mp4"),
                ("avc1", ".mp4"),
                ("XVID", ".avi"),
                ("MJPG", ".avi"),
            ]

            for fourcc_str, ext in candidates:
                path = os.path.join(tmpdir, f"fingerbot_demo_{stamp}{ext}")

                try:
                    fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
                    writer = cv2.VideoWriter(path, fourcc, self.fps, self.size)

                    if writer.isOpened():
                        self.writer = writer
                        self.path = path
                        self.backend = "cv2"
                        self.ok = True
                        return

                except Exception:
                    pass

        if IMAGEIO_AVAILABLE:
            path = os.path.join(tmpdir, f"fingerbot_demo_{stamp}.mp4")

            try:
                self.writer = imageio.get_writer(
                    path,
                    fps=self.fps,
                    codec="libx264",
                    quality=8,
                    macro_block_size=1,
                )
                self.path = path
                self.backend = "imageio"
                self.ok = True
                return

            except Exception:
                try:
                    self.writer = imageio.get_writer(path, fps=self.fps)
                    self.path = path
                    self.backend = "imageio"
                    self.ok = True
                    return
                except Exception:
                    pass

    def write(self, frame_bgr):
        if not self.ok:
            return

        if self.backend == "cv2":
            self.writer.write(frame_bgr)
        elif self.backend == "imageio":
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            self.writer.append_data(rgb)

    def release(self):
        if not self.ok:
            return

        try:
            if self.backend == "cv2":
                self.writer.release()
            else:
                self.writer.close()
        except Exception:
            pass

        self.ok = False


# ============================================================
# Hardware abstraction layer
# ============================================================

class ServoHAL:
    def __init__(self, min_arr, max_arr, max_rate):
        self.min = np.asarray(min_arr, dtype=float).copy()
        self.max = np.asarray(max_arr, dtype=float).copy()
        self.max_rate = float(max_rate)

        self.command = np.zeros_like(self.min)
        self.actual = np.zeros_like(self.min)

        self.enabled = True
        self.saturation_events = 0

    def reset(self):
        self.command = np.zeros_like(self.min)
        self.actual = np.zeros_like(self.min)
        self.enabled = True
        self.saturation_events = 0

    def update(self, raw_targets, dt, estop=False, max_rate_override=None):
        raw_targets = np.asarray(raw_targets, dtype=float)
        raw_targets = np.nan_to_num(raw_targets, nan=0.0, posinf=0.0, neginf=0.0)

        max_rate = float(max_rate_override if max_rate_override is not None else self.max_rate)

        if estop:
            self.enabled = False
            self.command = self.actual.copy()
            return self.actual.copy(), True, self.saturation_events

        self.enabled = True

        clipped = np.clip(raw_targets, self.min, self.max)

        if not np.allclose(clipped, raw_targets):
            self.saturation_events += int(np.sum(~np.isclose(clipped, raw_targets)))

        self.command = rate_limit(self.command, clipped, max_rate, dt)

        tau = 0.05
        alpha = min(1.0, float(dt) / tau)
        self.actual = self.actual + alpha * (self.command - self.actual)

        self.actual = np.clip(self.actual, self.min, self.max)

        return self.actual.copy(), False, self.saturation_events


# ============================================================
# Mapping, IK, constraints
# ============================================================

def map_human_to_robot(human_angles, calib_min, calib_max, robot_min, robot_max):
    human_angles = np.asarray(human_angles, dtype=float)
    calib_min = np.asarray(calib_min, dtype=float)
    calib_max = np.asarray(calib_max, dtype=float)

    span = np.maximum(calib_max - calib_min, 1e-3)
    normalized = np.clip((human_angles - calib_min) / span, 0.0, 1.0)

    robot_min = np.asarray(robot_min, dtype=float)
    robot_max = np.asarray(robot_max, dtype=float)

    return robot_min + normalized * (robot_max - robot_min)


def fk2_from_relative(rel_angles, lengths):
    abs_angles = np.cumsum(rel_angles)
    pos = np.zeros(2, dtype=float)
    points = [pos.copy()]

    for length, ang in zip(lengths, abs_angles):
        pos = pos + length * np.array([math.cos(ang), math.sin(ang)], dtype=float)
        points.append(pos.copy())

    return points[-1], points


def ik_3link(target, lengths, limits, init, iterations=18, learning_rate=0.7):
    target = np.asarray(target, dtype=float)
    target = np.nan_to_num(target, nan=0.0, posinf=0.0, neginf=0.0)

    lengths = np.asarray(lengths, dtype=float)
    limits = np.asarray(limits, dtype=float)

    rel = np.asarray(init, dtype=float).copy()
    rel = np.nan_to_num(rel, nan=0.0, posinf=0.0, neginf=0.0)
    rel = np.clip(rel, limits[:, 0], limits[:, 1])

    for _ in range(iterations):
        ee, _ = fk2_from_relative(rel, lengths)

        if np.linalg.norm(ee - target) < 1e-4:
            break

        for i in range(len(lengths) - 1, -1, -1):
            ee, points = fk2_from_relative(rel, lengths)
            joint = points[i]

            v_current = ee - joint
            v_target = target - joint

            n1 = np.linalg.norm(v_current)
            n2 = np.linalg.norm(v_target)

            if n1 < 1e-6 or n2 < 1e-6:
                continue

            ang_current = math.atan2(v_current[1], v_current[0])
            ang_target = math.atan2(v_target[1], v_target[0])
            delta = wrap_angle(ang_target - ang_current)

            rel[i] += learning_rate * delta
            rel[i] = float(np.clip(rel[i], limits[i, 0], limits[i, 1]))

    return np.clip(rel, limits[:, 0], limits[:, 1])


def ik_targets_from_landmarks(norm_lm, direct_targets):
    targets = np.asarray(direct_targets, dtype=float).copy()

    if norm_lm is None:
        return targets

    norm_lm = np.asarray(norm_lm, dtype=float)
    norm_lm = np.nan_to_num(norm_lm, nan=0.0, posinf=0.0, neginf=0.0)

    if norm_lm.shape != (21, 3):
        return targets

    for f, name in enumerate(FINGERS):
        mcp_idx = FINGER_MCP_INDICES[f]
        tip_idx = FINGER_TIPS[f]

        vec = norm_lm[tip_idx] - norm_lm[mcp_idx]

        y = float(np.dot(vec, np.array([0.0, 1.0, 0.0])))
        z = float(np.dot(vec, np.array([0.0, 0.0, 1.0])))

        y = max(0.05, y)
        z = max(0.0, z)

        target = np.array([y, z], dtype=float)

        lengths = FINGER_LENGTHS[name] / NOMINAL_PALM_LENGTH
        max_reach = float(np.sum(lengths)) * 0.98
        min_reach = float(np.sum(lengths)) * 0.12

        r = float(np.linalg.norm(target))

        if r > max_reach and r > 1e-9:
            target *= max_reach / r
        elif r < min_reach and r > 1e-9:
            target *= min_reach / r
        else:
            target = np.array([min_reach, 0.0], dtype=float)

        limits = np.deg2rad(
            np.column_stack(
                (
                    ROBOT_MIN[3 * f: 3 * f + 3],
                    ROBOT_MAX[3 * f: 3 * f + 3],
                )
            )
        )

        init = np.deg2rad(targets[3 * f: 3 * f + 3])
        solved = ik_3link(target, lengths, limits, init)

        targets[3 * f: 3 * f + 3] = np.rad2deg(solved)

    return np.clip(targets, ROBOT_MIN, ROBOT_MAX)


def apply_collision_constraints(targets, enabled=True):
    targets = np.asarray(targets, dtype=float).copy()
    targets = np.nan_to_num(targets, nan=0.0, posinf=0.0, neginf=0.0)
    targets = np.clip(targets, ROBOT_MIN, ROBOT_MAX)

    if not enabled:
        return targets

    for _ in range(5):
        pts = build_hand_from_angles(targets)
        collision = False

        for f, tip_idx in enumerate(FINGER_TIPS):
            ref = pts[0] if f == 0 else pts[9]
            dist = float(np.linalg.norm(pts[tip_idx] - ref))
            min_dist = 0.09 if f == 0 else 0.11

            if dist < min_dist:
                targets[3 * f: 3 * f + 3] *= 0.90
                targets[3 * f: 3 * f + 3] = np.maximum(
                    targets[3 * f: 3 * f + 3],
                    ROBOT_MIN[3 * f: 3 * f + 3],
                )
                collision = True

        if not collision:
            break

    return np.clip(targets, ROBOT_MIN, ROBOT_MAX)


# ============================================================
# Session state
# ============================================================

if "app_initialized" not in st.session_state:
    st.session_state.app_initialized = True

    st.session_state.running = False
    st.session_state.estop = False

    st.session_state.fps = 10
    st.session_state.run_duration = 15.0
    st.session_state.record_enabled = True

    st.session_state.run_start_time = time.time()
    st.session_state.elapsed = 0.0
    st.session_state.frame_count = 0
    st.session_state.sim_time = 0.0
    st.session_state.last_tick = time.time()

    st.session_state.recorder = None
    st.session_state.recorder_failed = False

    st.session_state.video_path = None
    st.session_state.video_bytes = None
    st.session_state.video_ready = False

    st.session_state.hal = ServoHAL(ROBOT_MIN, ROBOT_MAX, 120.0)

    st.session_state.robot_actual = np.zeros(15, dtype=float)
    st.session_state.robot_cmd = np.zeros(15, dtype=float)

    st.session_state.human_raw = np.zeros(15, dtype=float)
    st.session_state.human_filt = np.zeros(15, dtype=float)
    st.session_state.mapped_target = np.zeros(15, dtype=float)

    st.session_state.calib_min = np.zeros(15, dtype=float)
    st.session_state.calib_max = np.full(15, 120.0, dtype=float)

    st.session_state.hist_t = deque(maxlen=360)
    st.session_state.hist_human_avg = deque(maxlen=360)
    st.session_state.hist_robot_avg = deque(maxlen=360)
    st.session_state.hist_vel = deque(maxlen=360)
    st.session_state.hist_latency = deque(maxlen=360)

    st.session_state.last_data = None
    st.session_state.last_human_pts = None

    st.session_state.auto_start_pending = True
    st.session_state.selected_finger = "Index"
    st.session_state.calib_message = ""

    st.session_state.cam_reader = None
    st.session_state.camera_failed = False

    st.session_state.img_smoother = ArrayEMA()
    st.session_state.last_img_landmark_time = time.time()


# ============================================================
# App control helpers
# ============================================================

def finalize_video():
    rec = st.session_state.get("recorder")

    if rec is None:
        return

    try:
        rec.release()
    except Exception:
        pass

    path = rec.path
    st.session_state.recorder = None

    if path and os.path.exists(path) and os.path.getsize(path) > 0:
        st.session_state.video_path = path

        try:
            with open(path, "rb") as f:
                st.session_state.video_bytes = f.read()
            st.session_state.video_ready = True
        except Exception:
            st.session_state.video_bytes = None
            st.session_state.video_ready = False
    else:
        st.session_state.video_path = None
        st.session_state.video_bytes = None
        st.session_state.video_ready = False


def start_demo(duration, record, fps):
    old_rec = st.session_state.get("recorder")

    if old_rec is not None:
        try:
            old_rec.release()
        except Exception:
            pass
        st.session_state.recorder = None

    st.session_state.running = True
    st.session_state.run_duration = float(duration)
    st.session_state.record_enabled = bool(record)
    st.session_state.fps = int(fps)

    st.session_state.run_start_time = time.time()
    st.session_state.elapsed = 0.0
    st.session_state.frame_count = 0
    st.session_state.sim_time = 0.0
    st.session_state.last_tick = time.time()

    st.session_state.recorder_failed = False

    st.session_state.video_ready = False
    st.session_state.video_bytes = None
    st.session_state.video_path = None

    st.session_state.hal.reset()

    st.session_state.robot_actual = np.zeros(15, dtype=float)
    st.session_state.robot_cmd = np.zeros(15, dtype=float)
    st.session_state.human_raw = np.zeros(15, dtype=float)
    st.session_state.human_filt = np.zeros(15, dtype=float)
    st.session_state.mapped_target = np.zeros(15, dtype=float)

    st.session_state.hist_t.clear()
    st.session_state.hist_human_avg.clear()
    st.session_state.hist_robot_avg.clear()
    st.session_state.hist_vel.clear()
    st.session_state.hist_latency.clear()

    st.session_state.last_data = None
    st.session_state.last_human_pts = None

    if "img_smoother" in st.session_state:
        st.session_state.img_smoother.reset()

    st.session_state.last_img_landmark_time = time.time()


def stop_demo(finalize=True):
    if finalize:
        finalize_video()

    st.session_state.running = False


def set_calibration(min_arr=None, max_arr=None):
    if min_arr is not None:
        st.session_state.calib_min = np.asarray(min_arr, dtype=float).copy()

    if max_arr is not None:
        st.session_state.calib_max = np.asarray(max_arr, dtype=float).copy()

    st.session_state.calib_min = np.nan_to_num(st.session_state.calib_min, nan=0.0)
    st.session_state.calib_max = np.nan_to_num(st.session_state.calib_max, nan=0.0)

    span = st.session_state.calib_max - st.session_state.calib_min
    bad = span < 5.0

    if np.any(bad):
        st.session_state.calib_max[bad] = st.session_state.calib_min[bad] + 20.0


def capture_calibration_angles(mode, cfg):
    if cfg.get("source", "Synthetic demo").startswith("Webcam"):
        _, pts, _ = get_webcam_pose(cfg)

        if pts is not None:
            return extract_joint_angles(pts)

    preset = "Open" if mode == "min" else "Fist"
    pts = synthetic_landmarks(0.0, preset, 0.0)

    return extract_joint_angles(pts)


# ============================================================
# Main simulation step
# ============================================================

def advance_step(cfg):
    tick_start = time.perf_counter()

    now = time.time()
    dt = now - st.session_state.last_tick
    dt = float(np.clip(dt, 0.005, 0.25))
    st.session_state.last_tick = now

    st.session_state.sim_time += dt * float(cfg.get("speed", 1.0))

    left_frame, human_pts, source_msg, source_kind = get_current_pose(cfg)

    if human_pts is None:
        if st.session_state.last_human_pts is not None:
            human_pts = st.session_state.last_human_pts
        else:
            human_pts = synthetic_landmarks(0.0, "Open", 0.0)

    st.session_state.last_human_pts = human_pts

    human_raw = extract_joint_angles(human_pts)
    human_raw = np.nan_to_num(human_raw, nan=0.0, posinf=0.0, neginf=0.0)
    st.session_state.human_raw = human_raw

    prev_filt = st.session_state.human_filt.copy()

    human_rate = float(cfg.get("human_rate", 120.0))
    human_raw_limited = rate_limit(prev_filt, human_raw, human_rate, dt)

    human_filt = low_pass(
        prev_filt,
        human_raw_limited,
        dt,
        cfg.get("tau", 0.18),
    )

    deadzone = float(cfg.get("deadzone", 0.35))
    delta = human_filt - prev_filt
    small_motion = np.abs(delta) < deadzone

    human_filt = np.where(small_motion, prev_filt, human_filt)

    st.session_state.human_filt = np.nan_to_num(
        human_filt,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    mapped = map_human_to_robot(
        st.session_state.human_filt,
        st.session_state.calib_min,
        st.session_state.calib_max,
        ROBOT_MIN,
        ROBOT_MAX,
    )

    if str(cfg.get("control_mode", "")).startswith("IK"):
        mapped = ik_targets_from_landmarks(human_pts, mapped)

    mapped = apply_collision_constraints(mapped, enabled=bool(cfg.get("use_collision", True)))
    mapped = np.clip(mapped, ROBOT_MIN, ROBOT_MAX)

    cmd = rate_limit(
        st.session_state.robot_cmd,
        mapped,
        cfg.get("max_rate", 120.0),
        dt,
    )

    prev_actual = st.session_state.robot_actual.copy()

    actual, estopped, saturation_events = st.session_state.hal.update(
        cmd,
        dt,
        estop=bool(cfg.get("estop", False)),
        max_rate_override=cfg.get("max_rate", 120.0),
    )

    st.session_state.robot_cmd = cmd
    st.session_state.robot_actual = actual
    st.session_state.mapped_target = mapped

    effective_target = actual if cfg.get("estop", False) else mapped

    error_deg = float(np.sqrt(np.mean((actual - effective_target) ** 2)))

    calib_span = np.maximum(st.session_state.calib_max - st.session_state.calib_min, 1e-3)
    human_norm = np.clip(
        (st.session_state.human_filt - st.session_state.calib_min) / calib_span,
        0.0,
        1.0,
    )

    robot_span = np.maximum(ROBOT_MAX - ROBOT_MIN, 1e-3)
    robot_norm = np.clip((actual - ROBOT_MIN) / robot_span, 0.0, 1.0)

    error_norm = float(np.sqrt(np.mean((human_norm - robot_norm) ** 2)))

    vel = np.abs(actual - prev_actual) / max(dt, 1e-6)
    mean_vel = float(np.mean(vel))

    robot_pts_unnormalized = build_hand_from_angles(actual)
    robot_pts = normalize_landmarks(robot_pts_unnormalized)

    frame = make_scene_frame(
        human_pts,
        robot_pts,
        left_frame,
        info={
            "source": source_msg,
            "control_mode": cfg.get("control_mode", ""),
            "elapsed": time.time() - st.session_state.run_start_time,
            "duration": cfg.get("duration", st.session_state.run_duration),
            "fps": cfg.get("fps", st.session_state.fps),
            "latency": 0.0,
            "error": error_deg,
            "message": source_kind,
            "estop": bool(cfg.get("estop", False)),
        },
    )

    if cfg.get("record", False):
        if st.session_state.recorder is None and not st.session_state.recorder_failed:
            st.session_state.recorder = VideoRecorder(
                cfg.get("fps", st.session_state.fps),
                (COMBINED_W, FRAME_H),
            )

            if not st.session_state.recorder.ok:
                st.session_state.recorder_failed = True
                st.session_state.recorder = None

        if st.session_state.recorder is not None:
            st.session_state.recorder.write(frame)

    st.session_state.frame_count += 1
    st.session_state.elapsed = time.time() - st.session_state.run_start_time

    compute_time = time.perf_counter() - tick_start
    latency_ms = compute_time * 1000.0

    st.session_state.hist_t.append(st.session_state.elapsed)
    st.session_state.hist_human_avg.append(float(np.mean(st.session_state.human_filt)))
    st.session_state.hist_robot_avg.append(float(np.mean(actual)))
    st.session_state.hist_vel.append(mean_vel)
    st.session_state.hist_latency.append(latency_ms)

    data = {
        "source": source_msg,
        "source_kind": source_kind,
        "frame": frame,
        "human_raw": st.session_state.human_raw.copy(),
        "human_filt": st.session_state.human_filt.copy(),
        "mapped_target": mapped.copy(),
        "robot_cmd": cmd.copy(),
        "robot_actual": actual.copy(),
        "error_deg": error_deg,
        "error_norm": error_norm,
        "velocity": mean_vel,
        "latency": latency_ms,
        "compute_time": compute_time,
        "elapsed": st.session_state.elapsed,
        "duration": cfg.get("duration", st.session_state.run_duration),
        "fps": cfg.get("fps", st.session_state.fps),
        "saturation": saturation_events,
        "estop": bool(cfg.get("estop", False)),
        "max_rate": float(cfg.get("max_rate", 120.0)),
    }

    st.session_state.last_data = data
    return data


# ============================================================
# Rendering
# ============================================================

def render_status(ph, data):
    with ph.container():
        if st.session_state.estop:
            st.error("EMERGENCY STOP ACTIVE - actuator outputs are disabled.")

        c1, c2, c3, c4, c5 = st.columns(5)

        c1.metric("Source", str(data.get("source", "—"))[:24])
        c2.metric("Latency", f"{data.get('latency', 0.0):.0f} ms")
        c3.metric("Angle RMSE", f"{data.get('error_deg', 0.0):.1f}°")
        c4.metric("Normalized error", f"{data.get('error_norm', 0.0):.2f}")
        c5.metric(
            "Time",
            f"{data.get('elapsed', 0.0):.1f}/{data.get('duration', 0.0):.0f} s",
        )


def render_side(ph, data):
    selected = st.session_state.get("selected_finger", "Index")

    if selected not in FINGERS:
        selected = "Index"

    f_idx = FINGERS.index(selected)
    sl = slice(3 * f_idx, 3 * f_idx + 3)

    refresh = (
        st.session_state.frame_count % 2 == 0
        or "side_fig" not in st.session_state
        or st.session_state.get("side_finger_cache") != selected
    )

    if refresh:
        mapped = np.asarray(data.get("mapped_target", np.zeros(15)), dtype=float)
        actual = np.asarray(data.get("robot_actual", np.zeros(15)), dtype=float)

        fig = go.Figure(
            data=[
                go.Bar(name="Human mapped target", x=JOINT_SUFFIX, y=mapped[sl]),
                go.Bar(name="Robot actual", x=JOINT_SUFFIX, y=actual[sl]),
            ]
        )

        fig.update_layout(
            title=f"{selected} joint angles",
            height=300,
            margin=dict(l=10, r=10, t=45, b=10),
            barmode="group",
            legend=dict(orientation="h"),
            yaxis_title="deg",
        )

        st.session_state.side_fig = fig
        st.session_state.side_finger_cache = selected

    with ph.container():
        st.plotly_chart(st.session_state.side_fig, use_container_width=True)
        st.caption(
            f"Source: {data.get('source', '—')} | "
            f"Saturation events: {data.get('saturation', 0)} | "
            f"E-stop: {'ON' if data.get('estop', False) else 'OFF'}"
        )


def render_angles(ph, data):
    human_filt = np.asarray(data.get("human_filt", np.zeros(15)), dtype=float)
    mapped = np.asarray(data.get("mapped_target", np.zeros(15)), dtype=float)
    actual = np.asarray(data.get("robot_actual", np.zeros(15)), dtype=float)

    span = np.maximum(st.session_state.calib_max - st.session_state.calib_min, 1e-3)

    calibrated_pct = 100.0 * np.clip(
        (human_filt - st.session_state.calib_min) / span,
        0.0,
        1.0,
    )

    df = pd.DataFrame(
        {
            "Human°": human_filt,
            "Calibrated %": calibrated_pct,
            "Robot target°": mapped,
            "Robot actual°": actual,
            "Error°": actual - mapped,
        },
        index=JOINT_LABELS,
    ).round(1)

    ph.dataframe(df, use_container_width=True, height=380)


def render_trends(ph, force=False):
    t = list(st.session_state.hist_t)

    if len(t) < 2:
        ph.info("Collecting real-time data...")
        return

    refresh = force or st.session_state.frame_count % 5 == 0 or "trend_fig" not in st.session_state

    if refresh:
        human_avg = list(st.session_state.hist_human_avg)
        robot_avg = list(st.session_state.hist_robot_avg)
        vel = list(st.session_state.hist_vel)
        latency = list(st.session_state.hist_latency)

        fig = make_subplots(
            rows=3,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            subplot_titles=(
                "Average joint position",
                "Mean absolute velocity",
                "Processing latency",
            ),
        )

        fig.add_trace(
            go.Scatter(x=t, y=human_avg, name="Human avg", mode="lines"),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(x=t, y=robot_avg, name="Robot avg", mode="lines"),
            row=1,
            col=1,
        )

        fig.add_trace(
            go.Scatter(x=t, y=vel, name="Velocity", mode="lines"),
            row=2,
            col=1,
        )

        fig.add_trace(
            go.Scatter(x=t, y=latency, name="Latency", mode="lines"),
            row=3,
            col=1,
        )

        fig.update_yaxes(title_text="deg", row=1, col=1)
        fig.update_yaxes(title_text="deg/s", row=2, col=1)
        fig.update_yaxes(title_text="ms", row=3, col=1)
        fig.update_xaxes(title_text="time s", row=3, col=1)

        fig.update_layout(
            height=620,
            margin=dict(l=10, r=10, t=45, b=10),
            legend=dict(orientation="h"),
            hovermode="x unified",
        )

        st.session_state.trend_fig = fig

    ph.plotly_chart(st.session_state.trend_fig, use_container_width=True)


def render_hardware(ph, data):
    df = pd.DataFrame(
        {
            "Servo": JOINT_LABELS,
            "Min°": ROBOT_MIN,
            "Max°": ROBOT_MAX,
            "Command°": np.asarray(data.get("robot_cmd", np.zeros(15)), dtype=float),
            "Actual°": np.asarray(data.get("robot_actual", np.zeros(15)), dtype=float),
        }
    ).round(1)

    with ph.container():
        st.markdown(
            f"**HAL status** | Enabled: `{not data.get('estop', False)}` | "
            f"Saturation events: `{data.get('saturation', 0)}` | "
            f"Velocity limit: `{data.get('max_rate', 0.0):.0f} deg/s`"
        )

        st.dataframe(df, use_container_width=True, height=400)


def render_video(ph):
    with ph.container():
        if st.session_state.video_ready and st.session_state.video_bytes is not None:
            path = st.session_state.video_path or "fingerbot_demo.mp4"
            fname = os.path.basename(path)
            mime = "video/mp4" if fname.lower().endswith(".mp4") else "video/x-msvideo"

            try:
                st.video(st.session_state.video_bytes, format=mime)
            except Exception:
                st.video(st.session_state.video_bytes)

            st.download_button(
                label="Download demo video",
                data=st.session_state.video_bytes,
                file_name=fname,
                mime=mime,
                use_container_width=True,
            )

        elif st.session_state.running and st.session_state.record_enabled:
            st.info(
                f"Recording live demo... frame {st.session_state.frame_count} / "
                f"{int(st.session_state.fps * st.session_state.run_duration)}"
            )

        elif st.session_state.recorder_failed:
            st.warning("Video encoder unavailable. Install imageio-ffmpeg or use OpenCV codecs.")

        else:
            st.info("Start the demo with recording enabled to generate a downloadable video.")


def make_idle_data():
    if st.session_state.last_data is not None:
        return st.session_state.last_data

    pts = synthetic_landmarks(0.8, "Natural", 0.0)
    human_raw = extract_joint_angles(pts)
    human_filt = human_raw.copy()

    mapped = map_human_to_robot(
        human_filt,
        st.session_state.calib_min,
        st.session_state.calib_max,
        ROBOT_MIN,
        ROBOT_MAX,
    )

    mapped = apply_collision_constraints(mapped, True)

    robot_actual = np.zeros(15, dtype=float)
    robot_pts = normalize_landmarks(build_hand_from_angles(robot_actual))

    frame = make_scene_frame(
        pts,
        robot_pts,
        None,
        info={
            "source": "Idle",
            "control_mode": "Ready",
            "elapsed": 0.0,
            "duration": 0.0,
            "fps": 0.0,
            "latency": 0.0,
            "error": 0.0,
            "message": "Press Start / Restart Demo",
            "estop": st.session_state.estop,
        },
    )

    return {
        "source": "Idle",
        "source_kind": "idle",
        "frame": frame,
        "human_raw": human_raw,
        "human_filt": human_filt,
        "mapped_target": mapped,
        "robot_cmd": mapped,
        "robot_actual": robot_actual,
        "error_deg": 0.0,
        "error_norm": 0.0,
        "velocity": 0.0,
        "latency": 0.0,
        "compute_time": 0.0,
        "elapsed": 0.0,
        "duration": 0.0,
        "fps": 0.0,
        "saturation": 0,
        "estop": st.session_state.estop,
        "max_rate": 0.0,
    }


# ============================================================
# Sidebar
# ============================================================

st.sidebar.title("FingerBot Control")

source = st.sidebar.selectbox(
    "Input source",
    ["Synthetic demo", "Webcam"],
    index=0,
)

if source == "Webcam" and not MP_AVAILABLE:
    st.sidebar.warning("MediaPipe is not available. Webcam mode will fall back to synthetic demo.")

preset = st.sidebar.selectbox(
    "Motion preset",
    ["Natural", "Grasp", "Point", "Pinch", "Wave", "Open", "Fist"],
    index=0,
)

speed = st.sidebar.slider("Motion speed", 0.2, 3.0, 1.0, 0.05)
noise = st.sidebar.slider("Sensor noise", 0.0, 1.0, 0.10, 0.01)

st.sidebar.markdown("### Run / Record")

fps = st.sidebar.select_slider(
    "Frame rate",
    options=[8, 10, 12, 15, 20],
    value=10,
)

duration = st.sidebar.slider("Duration seconds", 1, 80, 20)
record = st.sidebar.checkbox("Record demo video", True)

start_btn = st.sidebar.button("Start / Restart Demo")
stop_btn = st.sidebar.button("Stop & Finalize Video")

if st.sidebar.button("Reset camera"):
    stop_camera_reader()

st.sidebar.markdown("### Control")

control_mode = st.sidebar.radio(
    "Control mode",
    ["Direct joint mapping", "IK fingertip tracking"],
    horizontal=True,
)

camera_tau = st.sidebar.slider(
    "Camera landmark smoothing",
    0.02,
    0.60,
    0.18,
    0.01,
)

tau = st.sidebar.slider("Low-pass time constant s", 0.0, 0.40, 0.18, 0.01)

human_rate = st.sidebar.slider(
    "Human angle rate limit deg/s",
    30,
    300,
    120,
    5,
)

max_rate = st.sidebar.slider("Velocity limit deg/s", 30, 500, 120, 5)

deadzone = st.sidebar.slider(
    "Micro-shake deadzone deg",
    0.0,
    2.0,
    0.35,
    0.05,
)

use_collision = st.sidebar.checkbox("Collision constraints", True)

estop = st.sidebar.checkbox(
    "EMERGENCY STOP",
    value=st.session_state.estop,
)

st.session_state.estop = estop

selected_finger = st.sidebar.selectbox("Detail finger", FINGERS, index=1)
st.session_state.selected_finger = selected_finger


# ============================================================
# Actions
# ============================================================

if start_btn:
    st.session_state.auto_start_pending = False

    if st.session_state.estop:
        st.sidebar.warning("Disengage EMERGENCY STOP before starting.")
    else:
        start_demo(duration, record, fps)

if stop_btn:
    stop_demo(True)


current_cfg = {
    "source": source,
    "preset": preset,
    "speed": speed,
    "noise": noise,
    "control_mode": control_mode,
    "tau": tau,
    "max_rate": max_rate,
    "use_collision": use_collision,
    "estop": st.session_state.estop,
    "fps": int(fps),
    "record": bool(record),
    "duration": float(duration),
    "camera_tau": camera_tau,
    "human_rate": human_rate,
    "deadzone": deadzone,
}


# ============================================================
# Auto start
# ============================================================

if st.session_state.auto_start_pending and not st.session_state.running:
    st.session_state.auto_start_pending = False
    start_demo(duration=15, record=True, fps=10)


# ============================================================
# Layout
# ============================================================

st.title("Continuous Finger-Motion Control for Robotic Hand")

st.caption(
    "Webcam/synthetic hand capture → 3D landmarks → continuous joint angles → normalization → "
    "interpolation → filtering/velocity limits → IK/constraints → virtual servo HAL."
)

status_ph = st.empty()

view_col, side_col = st.columns([1.7, 1.0], gap="small")
view_ph = view_col.empty()
side_ph = side_col.empty()

tab_live, tab_trends, tab_calib, tab_hw, tab_video = st.tabs(
    ["Live Angles", "Trends", "Calibration", "Hardware / Safety", "Demo Video"]
)

angle_ph = tab_live.empty()
trend_ph = tab_trends.empty()
hardware_ph = tab_hw.empty()
video_ph = tab_video.empty()


# ============================================================
# Calibration tab
# ============================================================

with tab_calib:
    st.markdown(
        """
        Calibrate the human input range:

        - **Capture Min**: open hand / minimal flexion.
        - **Capture Max**: fist / maximum flexion.
        - In synthetic mode, these buttons automatically use generated Open/Fist poses.
        - In webcam mode, show your hand and click capture.
        """
    )

    c1, c2, c3 = st.columns(3)

    cal_min_btn = c1.button("Capture Min (Open)")
    cal_max_btn = c2.button("Capture Max (Fist)")
    cal_reset_btn = c3.button("Reset Calibration")

    cal_auto_btn = st.button("Auto-calibrate synthetic Open/Fist")
    calib_msg_ph = st.empty()

    if cal_min_btn:
        angles = capture_calibration_angles("min", current_cfg)
        set_calibration(min_arr=angles)
        st.session_state.calib_message = "Minimum calibration captured."

    if cal_max_btn:
        angles = capture_calibration_angles("max", current_cfg)
        set_calibration(max_arr=angles)
        st.session_state.calib_message = "Maximum calibration captured."

    if cal_reset_btn:
        st.session_state.calib_min = np.zeros(15, dtype=float)
        st.session_state.calib_max = np.full(15, 120.0, dtype=float)
        st.session_state.calib_message = "Calibration reset to defaults."

    if cal_auto_btn:
        min_angles = capture_calibration_angles("min", {"source": "Synthetic demo"})
        max_angles = capture_calibration_angles("max", {"source": "Synthetic demo"})
        set_calibration(min_arr=min_angles, max_arr=max_angles)
        st.session_state.calib_message = "Automatic synthetic calibration complete."

    if st.session_state.calib_message:
        calib_msg_ph.info(st.session_state.calib_message)

    cal_df = pd.DataFrame(
        {
            "Joint": JOINT_LABELS,
            "Calib Min°": st.session_state.calib_min,
            "Calib Max°": st.session_state.calib_max,
            "Robot Min°": ROBOT_MIN,
            "Robot Max°": ROBOT_MAX,
        }
    ).round(1)

    st.dataframe(cal_df, use_container_width=True, height=380)


# ============================================================
# Live loop
# ============================================================

if st.session_state.running:
    run_cfg = {
        "source": source,
        "preset": preset,
        "speed": speed,
        "noise": noise,
        "control_mode": control_mode,
        "tau": tau,
        "max_rate": max_rate,
        "use_collision": use_collision,
        "estop": st.session_state.estop,
        "fps": int(st.session_state.fps),
        "record": bool(st.session_state.record_enabled),
        "duration": float(st.session_state.run_duration),
        "camera_tau": camera_tau,
        "human_rate": human_rate,
        "deadzone": deadzone,
    }

    data = advance_step(run_cfg)

    render_status(status_ph, data)
    view_ph.image(data["frame"], channels="BGR", use_container_width=True)
    render_side(side_ph, data)
    render_angles(angle_ph, data)
    render_trends(trend_ph, force=False)
    render_hardware(hardware_ph, data)
    render_video(video_ph)

    finished = (
        st.session_state.elapsed >= st.session_state.run_duration
        or st.session_state.frame_count >= int(st.session_state.fps * st.session_state.run_duration)
    )

    if finished:
        stop_demo(True)
        render_video(video_ph)
    else:
        sleep_time = max(0.0, 1.0 / max(st.session_state.fps, 1) - data.get("compute_time", 0.0))
        time.sleep(sleep_time)
        rerun_app()

else:
    data = make_idle_data()

    render_status(status_ph, data)

    if "frame" in data:
        view_ph.image(data["frame"], channels="BGR", use_container_width=True)

    render_side(side_ph, data)
    render_angles(angle_ph, data)
    render_trends(trend_ph, force=True)
    render_hardware(hardware_ph, data)
    render_video(video_ph)