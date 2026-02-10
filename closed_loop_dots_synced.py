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

# Triggering
from stytra.triggering import Trigger
import nidaqmx
from nidaqmx.constants import TerminalConfiguration
import time

# -----------------------
# NI DAQ
# -----------------------
from stytra.triggering import Trigger
import nidaqmx
from nidaqmx.constants import TerminalConfiguration
import time

DEVICE_NAME = "Dev1"
AI_CHANNEL = "ai0"
THRESHOLD = 2.5
POLL_RATE = 0.01  # 100 Hz
full_channel = f"{DEVICE_NAME}/{AI_CHANNEL}"

# -----------------------
# Stytra checks / prints (kept)
# -----------------------
import stytra
print(stytra.__file__)

from stytra.hardware.video.cameras import camera_class_dict
print(sorted(camera_class_dict.keys()))

from pypylon import pylon
print(pylon.TlFactory.GetInstance().EnumerateDevices())

# -----------------------
# Trigger for Stytra (waits for rising edge on Dev1/ai0)
# -----------------------

# Drop-in replacement trigger class (put this where your other trigger was)

class _Stopper(QObject):
    """
    Helper QObject that runs on the Qt/main thread and performs the actual stop calls.
    We emit 'stop_req' from the trigger thread; the connected slot executes in the
    Qt thread and calls Stytra's stop_recording/stop methods.
    """
    stop_req = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stop_req.connect(self._do_stop, type=0)  # default connection; queued across threads

    @pyqtSlot()
    def _do_stop(self):
        try:
            exp = getattr(self, "experiment_obj", None)
            if exp is None:
                print("[Stopper] No experiment object found on stopper.")
                return
            print("[Stopper] Calling experiment.stop_recording() on main thread")
            try:
                exp.stop_recording()
            except Exception as e:
                print(f"[Stopper] Exception in stop_recording(): {e}")
            print("[Stopper] Calling experiment.stop() on main thread")
            try:
                exp.stop()
            except Exception as e:
                print(f"[Stopper] Exception in stop(): {e}")
        except Exception as e:
            print(f"[Stopper] Unexpected error in _do_stop(): {e}")


class NIRiseFallTrigger(Trigger):
    """
    Start on rising edge (> threshold) and stop recording on falling edge (< threshold).
    Uses a helper Qt QObject with a signal to ensure the stop calls run on the main Qt thread.
    """
    def __init__(self, channel, threshold=2.5, poll_rate=0.01):
        super().__init__()
        self.channel = channel
        self.threshold = float(threshold)
        self.poll_rate = float(poll_rate)

        self._task = None
        self._prev_above = None
        self._armed = False
        self._stopped = False

        # stopper will be created in on_start (so we can attach experiment)
        self._stopper = None

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
        print(f"[Trigger] Armed on {self.channel}: start > {self.threshold}V, stop < {self.threshold}V")

    def check_trigger(self):
        """
        Called repeatedly BEFORE experiment starts. Return True to start the experiment.
        """
        try:
            self._ensure_task()
            voltage = self._task.read()
        except Exception as e:
            print(f"[Trigger] Error reading DAQ in check_trigger(): {e}")
            time.sleep(self.poll_rate)
            return False

        above = voltage > self.threshold

        if self._prev_above is not None and above != self._prev_above:
            if above:
                print(f"RISING:  voltage crossed above {self.threshold}V → {voltage:.3f}V")
                self._armed = True
                self._prev_above = above
                return True
            else:
                print(f"FALLING (pre-start): voltage dropped below {self.threshold}V → {voltage:.3f}V")

        self._prev_above = above
        time.sleep(self.poll_rate)
        return False

    def on_start(self):
        """
        Called once the experiment actually starts. Create the stopper and attach experiment.
        """
        print("[Trigger] Experiment started, creating stopper and monitoring for stop trigger")
        # Create stopper and attach the experiment object so the stopper can call stop methods.
        try:
            self._stopper = _Stopper()
            # attach experiment object for use by the stopper
            try:
                # self.experiment should be available (Stytra sets this on the trigger)
                self._stopper.experiment_obj = self.experiment
                print("[Trigger] Stopper attached to experiment.")
            except Exception as e:
                print(f"[Trigger] Could not attach experiment to stopper: {e}")
        except Exception as e:
            print(f"[Trigger] Error creating stopper: {e}")

    def update(self):
        """
        Called repeatedly DURING the experiment. On falling edge, request stopper to execute stop on main thread.
        """
        if not self._armed or self._stopped:
            # nothing to do
            return

        try:
            voltage = self._task.read()
        except Exception as e:
            print(f"[Trigger] Error reading DAQ during update(): {e}")
            time.sleep(self.poll_rate)
            return

        above = voltage > self.threshold

        if not above:
            print(f"STOP:    voltage fell below {self.threshold}V → {voltage:.3f}V")

            # Primary: emit Qt signal to stopper (this is queued and executes on the Qt/main thread)
            try:
                if self._stopper is not None:
                    self._stopper.stop_req.emit()
                else:
                    print("[Trigger] Stopper not available to emit signal.")
            except Exception as e:
                print(f"[Trigger] Exception emitting stopper signal: {e}")

            # Fallback: also schedule via QTimer.singleShot(0, ...) to be extra robust
            try:
                if hasattr(self, "experiment") and self.experiment is not None:
                    QTimer.singleShot(0, lambda: (
                        (print("[Trigger] Fallback: calling stop_recording() via QTimer"),
                         (self.experiment.stop_recording() if hasattr(self.experiment, "stop_recording") else None),
                         (self.experiment.stop() if hasattr(self.experiment, "stop") else None)
                        )
                    ))
            except Exception as e:
                print(f"[Trigger] Exception scheduling fallback stop via QTimer: {e}")

            self._stopped = True

        time.sleep(self.poll_rate)

    def __del__(self):
        try:
            if self._task is not None:
                self._task.close()
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
    trigger = NIRiseFallTrigger(
        channel=full_channel,
        threshold=THRESHOLD,
        poll_rate=POLL_RATE,
    )

    st = Stytra(
        protocol=VisualStim_dots(),
        camera=dict(type="basler", cam_idx=0),
        stim_plot=True,
        scope_triggering=trigger,
    )