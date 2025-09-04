# 2p visual stimulus — closed loop with vigor-triggered blackout

import numpy as np
import pandas as pd
import random, time

from stytra import Stytra, Protocol
from lightparam import Param
from stytra.stimulation.stimuli.kinematograms import ContinuousRandomDotKinematogram

from PyQt5.QtCore import QRect
from PyQt5.QtGui import QBrush, QColor

# ------------------ closed-loop subclass ------------------

from PyQt5.QtCore import QRect
from PyQt5.QtGui import QBrush, QColor
import time
from stytra.stimulation.stimuli.kinematograms import ContinuousRandomDotKinematogram

class VigorResponsiveDotStim(ContinuousRandomDotKinematogram):
    """
    Moving dots with vigor-triggered blackout (and BLACKOUT_ON/OFF event logs).
    NOTE: Do not store Qt objects on self; Stytra deep-copies stimuli.
    """
    def __init__(self, *args,
                 vigor_threshold=30.0,
                 hysteresis=5.0,
                 blackout_min_ms=150,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.vigor_threshold = float(vigor_threshold)
        self.hysteresis = float(hysteresis)
        self.blackout_min_ms = int(blackout_min_ms)
        self._blackout = False
        self._last_switch_ms = 0  # ms since epoch

    # ---------- helpers ----------
    def _get_vigor(self):
        exp = getattr(self, "_experiment", None)
        if exp is None or not hasattr(exp, "estimator"):
            return None
        # prefer estimator.vigor if present
        vig = getattr(exp.estimator, "vigor", None)
        if vig is not None:
            try:
                return float(vig)
            except Exception:
                return None
        # fallback to |velocity|
        if hasattr(exp.estimator, "get_velocity"):
            try:
                return abs(float(exp.estimator.get_velocity()))
            except Exception:
                return None
        return None

    def _switch_blackout(self, new_state: bool):
        self._blackout = new_state
        self._last_switch_ms = int(time.time() * 1000)
        # Log event to Stytra’s run log (seconds resolution)
        if hasattr(self, "log_event"):
            label = "BLACKOUT_ON" if new_state else "BLACKOUT_OFF"
            self.log_event(label, value=self._last_switch_ms / 1000.0)

    def _maybe_toggle_blackout(self):
        now = int(time.time() * 1000)
        if (now - self._last_switch_ms) < self.blackout_min_ms:
            return
        vig = self._get_vigor()
        if vig is None:
            return
        if not self._blackout and vig >= self.vigor_threshold:
            self._switch_blackout(True)
        elif self._blackout and vig <= (self.vigor_threshold - self.hysteresis):
            self._switch_blackout(False)

    # ---------- stimulus API ----------
    def update(self, *args, **kwargs):
        self._maybe_toggle_blackout()
        try:
            return super().update(*args, **kwargs)
        except TypeError:
            return super().update()

    def paint(self, p, w, h):
        if self._blackout:
            # Create Qt objects as locals (pickle-safe)
            p.setBrush(QBrush(QColor(0, 0, 0)))
            p.drawRect(QRect(0, 0, w, h))
        else:
            super().paint(p, w, h)

    # (Optional) make deepcopy/pickle extra safe:
    def __getstate__(self):
        # Return only pickle-safe state; base class state is pickleable.
        return {
            "vigor_threshold": self.vigor_threshold,
            "hysteresis": self.hysteresis,
            "blackout_min_ms": self.blackout_min_ms,
            "_blackout": self._blackout,
            "_last_switch_ms": self._last_switch_ms,
        }

    def __setstate__(self, state):
        self.vigor_threshold = state["vigor_threshold"]
        self.hysteresis = state["hysteresis"]
        self.blackout_min_ms = state["blackout_min_ms"]
        self._blackout = state["_blackout"]
        self._last_switch_ms = state["_last_switch_ms"]


# ------------------ protocol ------------------

class VisualStim_dots(Protocol):
    name = "VisualStim_dots"

    stytra_config = dict(
        tracking=dict(embedded=True, method="tail", estimator="vigor"),
        camera=dict(camera=dict(type="basler", cam_idx=0)),  # use device_idx=0 if your backend expects it
    )

    def __init__(self):
        super().__init__()
        self.number_of_repeats = Param(1)
        self.left_right = [0, 3]  # 0 = right, 3 = left

        self.dot_density = Param(0.3)
        self.dot_radius  = Param(0.6)
        self.t_pre       = Param(30.0)
        self.t_closed    = Param(40.0)
        self.t_post      = Param(10.0)
        self.vigor_thr   = Param(30.0)
        self.hyst        = Param(5.0)

    def _crdk(self, t, coherence, theta):
        return ContinuousRandomDotKinematogram(
            dot_density=float(self.dot_density),
            dot_radius=float(self.dot_radius),
            df_param=pd.DataFrame(dict(
                t=[float(t)],
                coherence=[float(coherence)],
                frozen=[0],
                theta_relative=[theta],
            ))
        )

    def _crdk_closedloop(self, t, coherence, theta):
        return VigorResponsiveDotStim(
            dot_density=float(self.dot_density),
            dot_radius=float(self.dot_radius),
            df_param=pd.DataFrame(dict(
                t=[float(t)],
                coherence=[float(coherence)],
                frozen=[0],
                theta_relative=[theta],
            )),
            vigor_threshold=float(self.vigor_thr),
            hysteresis=float(self.hyst),
            blackout_min_ms=150,
        )

    def get_stim_sequence(self):
        stimuli = []
        for _ in range(int(self.number_of_repeats)):
            stimuli.append(self._crdk(self.t_pre, 0, random.choice(self.left_right)))
            stimuli.append(self._crdk_closedloop(self.t_closed, 1, random.choice(self.left_right)))
            stimuli.append(self._crdk(self.t_post, 0, random.choice(self.left_right)))
        return stimuli

# ------------------ launcher ------------------

if __name__ == "__main__":
    st = Stytra(
        protocol=VisualStim_dots(),
        camera=dict(type="basler", cam_idx=0),  # or device_idx=0
        stim_plot=True
    )
