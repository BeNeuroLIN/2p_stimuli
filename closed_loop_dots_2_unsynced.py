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

# Test if edited package is installed
import stytra

print(stytra.__file__)

# See if key is registered
from stytra.hardware.video.cameras import camera_class_dict

print(sorted(camera_class_dict.keys()))

# Verify pypylon sees camera
from pypylon import pylon

print(pylon.TlFactory.GetInstance().EnumerateDevices())


# Custom class that drops coherence when vigor exceeds threshold
class VigorResponsiveDotStim(ContinuousRandomDotKinematogram):
    def __init__(self, *args, vigor_threshold=-5.0, original_coherence=1.0, **kwargs):
        # Remove custom parameters before passing to parent
        self.vigor_threshold = vigor_threshold
        self.original_coherence = original_coherence
        self.coherence_dropped = False
        self.current_coherence = original_coherence  # Track current coherence
        super().__init__(*args, **kwargs)

    def update(self):
        # Get current vigor from the experiment's estimator
        if hasattr(self, '_experiment') and self._experiment is not None:
            if hasattr(self._experiment, 'estimator') and self._experiment.estimator is not None:
                try:
                    vigor = self._experiment.estimator.get_velocity()

                    # Print vigor value only when it's lower than -5 (significant activity)
                    if vigor is not None and vigor < -5.0:
                        print(f"Current vigor: {vigor:.3f}")

                    # If vigor is lower than threshold, drop coherence to 0
                    if vigor is not None and vigor < self.vigor_threshold:
                        if not self.coherence_dropped:
                            # Modify the dataframe to set coherence to 0
                            self.df_param.loc[:, 'coherence'] = 0
                            self.coherence_dropped = True
                            self.current_coherence = 0.0  # Update current coherence
                            print(
                                f">>> VIGOR THRESHOLD EXCEEDED ({vigor:.2f} < {self.vigor_threshold}). COHERENCE DROPPED TO 0. <<<")

                    # Update the experiment's dynamic log with current coherence
                    if hasattr(self._experiment, 'dynamic_log'):
                        self._experiment.dynamic_log.update_param('current_coherence', self.current_coherence)

                except Exception as e:
                    print(f"Error getting vigor: {e}")

        # Call parent update method
        super().update()


# Wrapper class for tracking coherence in non-responsive stimuli
class TrackedDotStim(ContinuousRandomDotKinematogram):
    def __init__(self, *args, tracked_coherence=0.0, **kwargs):
        # Store coherence value and remove it from kwargs before passing to parent
        self.coherence_value = tracked_coherence
        super().__init__(*args, **kwargs)

    def update(self):
        # Update the experiment's dynamic log with current coherence
        if hasattr(self, '_experiment') and self._experiment is not None:
            if hasattr(self._experiment, 'dynamic_log'):
                self._experiment.dynamic_log.update_param('current_coherence', self.coherence_value)

        # Call parent update method
        super().update()


# Define a protocol subclass
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
        self.vigor_threshold = Param(-1.0, limits=(-100, 100))  # Add vigor threshold as parameter with explicit limits
        self.left_right = [0, 3]  # Right (0) or left (3)

    def get_stim_sequence(self):
        stimuli = []

        for i in range(self.number_of_repeats):
            # Pre-stimulus 0% coherence (30 seconds)
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
                    tracked_coherence=0.0  # Track that coherence is 0
                ),
            )

            # 100% coherence left or right - WITH VIGOR RESPONSE (40 seconds)
            vigor_stim = VigorResponsiveDotStim(
                dot_density=0.3,
                dot_radius=0.6,
                df_param=pd.DataFrame(
                    dict(
                        t=[40],
                        coherence=[1],  # Start at 100% coherence
                        frozen=[0],
                        theta_relative=[random.choice(self.left_right)]
                    )
                ),
                vigor_threshold=float(self.vigor_threshold),  # Ensure it's passed as float
                original_coherence=1.0
            )
            stimuli.append(vigor_stim)

            # Post-stimulus 0% coherence (10 seconds)
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
                    tracked_coherence=0.0  # Track that coherence is 0
                ),
            )

        return stimuli


if __name__ == "__main__":
    # This is the line that actually opens stytra with the new protocol
    st = Stytra(
        protocol=VisualStim_dots(),
        camera=dict(type="basler", cam_idx=0),
        stim_plot=True
    )