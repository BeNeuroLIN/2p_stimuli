'''
author: paula.pflitsch@lin-magdeburg.de

This code contains a closed-loop moving dot stimulus.
It can be started with the stytra trigger function.
## The "Wait for trigger" option in stytra needs to be ticked.

'''
import numpy as np
from stytra import Stytra, Protocol
import pandas as pd
from stytra.stimulation.stimuli.kinematograms import ContinuousRandomDotKinematogram
from stytra.stimulation.stimuli.visual import Pause
from lightparam import Param
from PyQt5.QtCore import QRect
from PyQt5.QtGui import QBrush, QColor
from pypylon import pylon
import random
import time
import traceback

import stytra
print(stytra.__file__)

from stytra.hardware.video.cameras import camera_class_dict
print(sorted(camera_class_dict.keys()))

from pypylon import pylon
print(pylon.TlFactory.GetInstance().EnumerateDevices())

import time
import nidaqmx
from nidaqmx.constants import TerminalConfiguration
from stytra.triggering import Trigger

from PyQt5.QtCore import QTimer

# -----------------------
# Trigger for Stytra (waits for rising edge on Dev1/ai0)
# -----------------------

DEVICE_NAME = "Dev1"
AI_CHANNEL = "ai0"
THRESHOLD = 2.5
POLL_RATE = 0.02  # 200 Hz
full_channel = f"{DEVICE_NAME}/{AI_CHANNEL}"

class NIRiseOnlyTrigger(Trigger):
    def __init__(self, channel, threshold=2.5, poll_rate=0.01):
        super().__init__()
        self.channel = channel
        self.threshold = float(threshold)
        self.poll_rate = float(poll_rate)
        self._task = None
        self._prev_above = None

    def _ensure_task(self):
        if self._task is not None:
            return
        self._task = nidaqmx.Task()
        self._task.ai_channels.add_ai_voltage_chan(
            self.channel,
            terminal_config=TerminalConfiguration.RSE,
            min_val=-10.0,
            max_val=10.0,
        )
        print(f"[Trigger] Armed on {self.channel}: start > {self.threshold}V")

    def check_trigger(self):
        self._ensure_task()

        voltage = float(self._task.read())
        above = voltage > self.threshold

        if self._prev_above is None:
            self._prev_above = above
            time.sleep(self.poll_rate)
            return False

        # rising edge only
        fired = (above and not self._prev_above)
        if fired:
            print(f"[Trigger] RISING: {voltage:.3f}V")
        self._prev_above = above
        time.sleep(self.poll_rate)
        return fired

    def close(self):
        try:
            if self._task is not None:
                self._task.close()
                self._task = None
        except Exception:
            pass


# -----------------------
# Your stimulus classes (unchanged)
# -----------------------
class VigorResponsiveDotStim(ContinuousRandomDotKinematogram):
    def __init__(self, *args, vigor_threshold=-5.0, original_coherence=1.0, **kwargs):
        self.vigor_threshold = vigor_threshold
        self.original_coherence = original_coherence
        self.coherence_dropped = False
        self.current_coherence = original_coherence
        super().__init__(*args, **kwargs)

    def update(self):
        if hasattr(self, '_experiment') and self._experiment is not None:
            if hasattr(self._experiment, 'estimator') and self._experiment.estimator is not None:
                try:
                    vigor = self._experiment.estimator.get_velocity()

                    if vigor is not None and vigor < -5.0:
                        print(f"Current vigor: {vigor:.3f}")

                    if vigor is not None and vigor < self.vigor_threshold:
                        if not self.coherence_dropped:
                            self.df_param.loc[:, 'coherence'] = 0
                            self.coherence_dropped = True
                            self.current_coherence = 0.0
                            print(
                                f">>> VIGOR THRESHOLD EXCEEDED ({vigor:.2f} < {self.vigor_threshold}). "
                                f"COHERENCE DROPPED TO 0. <<<"
                            )

                    if hasattr(self._experiment, 'dynamic_log'):
                        self._experiment.dynamic_log.update_param('current_coherence', self.current_coherence)

                except Exception as e:
                    print(f"Error getting vigor: {e}")

        super().update()


class TrackedDotStim(ContinuousRandomDotKinematogram):
    def __init__(self, *args, tracked_coherence=0.0, **kwargs):
        self.coherence_value = tracked_coherence
        super().__init__(*args, **kwargs)

    def update(self):
        if hasattr(self, '_experiment') and self._experiment is not None:
            if hasattr(self._experiment, 'dynamic_log'):
                self._experiment.dynamic_log.update_param('current_coherence', self.coherence_value)
        super().update()


class VisualStim_dots(Protocol):
    name = "VisualStim_dots"

    stytra_config = dict(
        tracking=dict(embedded=True, method="tail", estimator="vigor"),
        camera=dict(camera=dict(type="basler", cam_idx=0)),
    )

    def __init__(self):
        super().__init__()
        self.number_of_repeats = Param(1, limits=None)
        self.duration_of_stimulus_in_seconds = Param(10, limits=None)
        self.pause_before_stimulus = Param(0, limits=None)
        self.pause_after_stimulus = Param(0, limits=None)
        self.vigor_threshold = Param(-1.0, limits=(-100, 100))
        self.left_right = [0, 3]

    def get_stim_sequence(self):
        stimuli = []

        for i in range(self.number_of_repeats):
            stimuli.append(
                TrackedDotStim(
                    dot_density=0.3,
                    dot_radius=0.6,
                    df_param=pd.DataFrame(
                        dict(
                            t=[30],
                            coherence=[0],
                            frozen=[0],
                            theta_relative=[random.choice(self.left_right)]
                        )
                    ),
                    tracked_coherence=0.0
                ),
            )

            vigor_stim = VigorResponsiveDotStim(
                dot_density=0.3,
                dot_radius=0.6,
                df_param=pd.DataFrame(
                    dict(
                        t=[40],
                        coherence=[1],
                        frozen=[0],
                        theta_relative=[random.choice(self.left_right)]
                    )
                ),
                vigor_threshold=float(self.vigor_threshold),
                original_coherence=1.0
            )
            stimuli.append(vigor_stim)

            stimuli.append(
                TrackedDotStim(
                    dot_density=0.3,
                    dot_radius=0.6,
                    df_param=pd.DataFrame(
                        dict(
                            t=[10],
                            coherence=[0],
                            frozen=[0],
                            theta_relative=[random.choice(self.left_right)]
                        )
                    ),
                    tracked_coherence=0.0
                ),
            )

        return stimuli


if __name__ == "__main__":
    # Your protocol class must already be defined above this point
    trigger = NIRiseOnlyTrigger(full_channel, threshold=THRESHOLD, poll_rate=POLL_RATE)

    st = Stytra(
        protocol=VisualStim_dots(),
        camera=dict(type="basler", cam_idx=0),
        stim_plot=True,
        scope_triggering=trigger,
        exec=False,
    )
    app = st.exp.app
    app.exec_()


    def stop_on_fall():
        # only stop if a protocol is currently running
        # (attribute name can vary a bit across Stytra versions)
        protocol_running = getattr(st.exp, "protocol_running", None)
        if callable(protocol_running):
            running = protocol_running()
        else:
            running = bool(getattr(st.exp, "running", True))

        v = float(stop_task.read())
        above = v > THRESHOLD

        if state["prev_above"] is None:
            state["prev_above"] = above
            return

        # Arm the stop logic only once we have actually started running
        if running:
            state["armed_stop"] = True

        # Falling edge: only stop if we were armed (i.e., had a started trial)
        if state["armed_stop"] and (not above) and state["prev_above"]:
            if not state["stop_done"]:
                state["stop_done"] = True
                print(f"[Stopper] FALLING: {v:.3f}V -> stopping protocol (save=True)")
                try:
                    st.exp.end_protocol(save=True)
                finally:
                    # re-arm for the next trigger/trial:
                    state["stop_done"] = False
                    state["armed_stop"] = False

        state["prev_above"] = above


    timer = QTimer()
    timer.timeout.connect(stop_on_fall)
    timer.start(10)  # 100 Hz-ish