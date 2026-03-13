# 100% coherent dot motion with melatonin delivery
# author: paula.pflitsch@lin-magdeburg.de
# 13/03/2026

'''
The program is based on the Portugues lab's Stytra program. https://portugueslab.com/stytra/overview/0_motivation.html
This code alternates between baseline (0% coherence) and directional (100% coherent) dot motion stimuli.
During the duration of the experiment a constant water flow will be directed at the fish. This will be interlaced with
presentations of a second liquid, a low melatonin concentration in this case, delivered through an odor delivery pen
placed in front of the fish.
The visual stimuli will repeat for the water and melatonin deliveries.
Water flow
    0% coherence dots
    100% coherence dots
    0% coherence dots
Melatonin flow
    0% coherence dots
    100% coherence dots
    0% coherence dots
Water flow
    0% coherence dots
    100% coherence dots
    0% coherence dots


'''

from stytra import Stytra, Protocol
from lightparam import Param
from stytra.stimulation.stimuli.arduino import WriteArduinoPin

from stytra.stimulation.stimuli.kinematograms import ContinuousRandomDotKinematogram
import random
import pandas as pd

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
# Triggered by two-photon computer --> Labview record start
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
# Visual stimulus protocol
# Random dot motion
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


#-----------------
# Order of stimuli (arduino on off and visual stimuli)
#-----------------
class Stimulus_protocol(Protocol):
    name = "Stimulus_protocol"

    # Configure tracking/camera as you already have (basler backend working),
    # and IMPORTANT: configure BOTH Arduino pins as digital outputs.
    stytra_config = dict(
        tracking=dict(embedded=True, method="tail", estimator="vigor"),
        camera=dict(camera=dict(type="basler", cam_idx=0)),
        arduino_config=dict(
            com_port="COM3",  # update if your Arduino is on a different port
            layout=[
                # water: arduino pin 11
                dict(pin=11, mode="output", ad="d"),  # water valve
                # melatonin: arduino pin 7
                dict(pin=7, mode="output", ad="d"),  # melatonin valve
            ],
        ),
    )

    def __init__(self):
        super().__init__()
        self.total_repeats = Param(1, limits=None)
        self.visual_repeats = Param(20, limits=None)

        # visual stimulus parameters
        self.duration_of_stimulus_in_seconds = Param(10, limits=None)
        self.pause_before_stimulus = Param(60, limits=None)
        self.pause_after_stimulus = Param(0, limits=None)
        self.vigor_threshold = Param(-1.0, limits=(-100, 100))
        self.left_right = [0, 3]

        # melatonin stimulus parameters
        self.water_on = Param(60.0, limits=None)  # water ON
        self.water_off = Param(1.0, limits=None)  # water OFF
        self.mel_on = Param(20.0, limits=None)  # melatonin ON
        self.mel_off = Param(20.0, limits=None)  # melatonin OFF

    def get_stim_sequence(self):
        stimuli = []

        for i in range(self.total_repeats):
            # WATER ON (pin 11 = HIGH) for water_on_1 seconds
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 1}, duration=float(self.water_on)))
            stimuli.append(self.pause_before_stimulus)

            for j in range(self.visual_repeats):
                # visual stimulus start
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

            # WATER OFF (pin 11 = LOW)
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 0}, duration=float(self.water_off)))

            # melatonin ON (pin 7 = HIGH)
            stimuli.append(WriteArduinoPin(pin_values_dict={7: 1}, duration=float(self.mel_on)))

            for j in range(self.visual_repeats):
                # repeat the same stimuli
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

            # melatonin OFF (pin 7 = LOW)
            stimuli.append(WriteArduinoPin(pin_values_dict={7: 0}, duration=float(self.mel_off)))

            # WATER ON again
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 1}, duration=float(self.water_on)))

            for j in range(self.visual_repeats):
                # repeat the stimuli again
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


            # Optional: ensure water is OFF at the end of the block
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 0}, duration=0.5))

        return stimuli


if __name__ == "__main__":
    # Your protocol class must already be defined above this point
    trigger = NIRiseOnlyTrigger(full_channel, threshold=THRESHOLD, poll_rate=POLL_RATE)

    st = Stytra(
        protocol=Stimulus_protocol(),
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
    timer.start(20)  # 200 Hz-ish