## 2p visual stimulus

import numpy as np
from stytra import Stytra, Protocol #Required for stytra interface usage
import pandas as pd #Required for ContinuousRandomDotKinematogram
from stytra.stimulation.stimuli.kinematograms import ContinuousRandomDotKinematogram #Required for moving dots stimulus
from stytra.stimulation.stimuli.visual import Pause #Required for black screen "pauses" in stimuli
from lightparam import Param #Required so we can change parameters in the GUI
from PyQt5.QtCore import QRect
from PyQt5.QtGui import QBrush,QColor
from pypylon import pylon
import random #Allow random choice of stimulus direction
import time
import traceback

#test if edited package is installed
import stytra; print(stytra.__file__)

# see if key is registered
from stytra.hardware.video.cameras import camera_class_dict
print(sorted(camera_class_dict.keys()))

# verify pypylon sees camera
from pypylon import pylon
print(pylon.TlFactory.GetInstance().EnumerateDevices())


#1. Define A visual Stimulus (for projector)
# closed loop visual stimulus with moving dots
# 10s 0% coherence, 40s 100% coherence either left or right, 10s  0% coherence
# screen turns black if the fish's tail vigor exceeds threshold

# 2. Custom class that switches to black screen when vigor exceeds threshold
class VigorResponsiveDotStim(ContinuousRandomDotKinematogram):
    def __init__(self, *args, vigor_threshold=30.0,**kwargs):
        super().__init__(*args,**kwargs)
        self.vigor_threshold=vigor_threshold
        self.blackout=False

    def paint(self, p,w,h):
        p.setBrush(QBrush(QColor(*self.color))) #use chosen color
        p.drawRect(QRect(0,0,w,h))

    def update(self):
        fish_vel=self._experiment.estimator.get_velocity()
        if fish_vel < -5:
            self.color = (0,0,0)

        # check for vigor and enable blackout if threshold is passed
        #if hasattr(self, "experiment") and hasattr(self.experiment, "vigor"):
         #   if self.experiment.vigor is not None and self.experiment.vigor > self.vigor_threshold:
          #      self.blackout = True
        #super().update(t, *args,**kwargs)

    '''
    def draw_frame(self, frame, t):
        if self.blackout:
            frame.fill(0) #black screen
        else:
            super().draw_frame(frame, t)
    '''
# 3. Define a protocol subclass
class VisualStim_dots(Protocol):
    name = "VisualStim_dots"  # every protocol must have a name.
    # In the stytra_config class attribute we specify a dictionary of
    # parameters that control camera, tracking, monitor, etc.
    # In this particular case, we add a stream of frames from a spinnaker camera
    stytra_config = dict(
        tracking=dict(embedded=True, method="tail", estimator="vigor"),
        camera=dict(camera=dict(type="basler", cam_idx=0)),
    )

# Define the parameters which will be changeable in the Graphical User Interface (GUI)
    def __init__(self):
        super().__init__()
        self.number_of_repeats = Param(1, limits=None)
        self.duration_of_stimulus_in_seconds = Param(10, limits=None)
        self.pause_before_stimulus = Param (0, limits=None)
        self.pause_after_stimulus = Param (0, limits=None)
        self.left_right = [0, 3] #Create a list with parameters for right (0) or left (3)

# Define the sequence of stimuli in order
    # Pause = Black Screen
    # ContinuousRandomDotKinematogram = Moving Dots

    def get_stim_sequence(self):
        stimuli = [
            ]
        for i in range (self.number_of_repeats):
            # pre-stimulus 0% coherence
            stimuli.append(
                ContinuousRandomDotKinematogram(
                    dot_density=0.3,
                    dot_radius=0.6, #0.4
                    df_param=pd.DataFrame(
                        dict(
                            # t=[self.duration_of_stimulus_in_seconds],
                            t=30,
                            coherence=[0],  # 0: 0% coherence
                            frozen=[0],  # frozen describes the time (in seconds) that the dots remain frozen on screen
                            theta_relative=[random.choice(self.left_right)]
                            # theta_relative describes direction of the moving dots;
                            # For choice in GUI (stays the same): theta_relative = self.direction_of_dots
                        )
                    ),
                ),
            )
            # 100% coherence left or right
            stimuli.append(
                ContinuousRandomDotKinematogram(
                    dot_density=0.3,
                    dot_radius=0.6,
                    df_param=pd.DataFrame(
                        dict(
                            # t describes the time (in seconds) the stimulus is shown
                            # currently it is set as a parameter changeable in the GUI (self.duration_of_stimulus)
                            # This parameter is defined above in "def __init__(self):"
                            #t=[self.duration_of_stimulus_in_seconds],
                            t=40,
                            # coherence describes how many of the dots move coherently in one direction
                            # vs. dots moving randomly
                            # 1 = 100% coherence (Dots move to the right)
                            # -1 = 100% coherence (Dots move to the left)
                            # Decimals in-between can be used for a percentage of dots to move randomly
                            coherence=[1],
                            # frozen describes the time (in seconds) that the dots remain frozen on screen
                            frozen=[0],
                            # theta_relative describes direction of the moving dots;
                            # currently it is set as a parameter changeable in the GUI (self.direction_of_dots)
                            # This parameter is defined above in "def __init__(self):"
                            # 0 = dots move to the right (with coherence = 1)
                            # 3 = dots move to the left (with coherence = 1)
                            theta_relative = [random.choice(self.left_right)]
                            #For choice in GUI (stays the same): theta_relative = self.direction_of_dots
                        )
                    ),
                    #vigor_threshold=30.0
                ),
            )
            stimuli.append(
                ContinuousRandomDotKinematogram(
                    dot_density=0.3,
                    dot_radius=0.6,
                    df_param=pd.DataFrame(
                        dict(
                            #t=[self.duration_of_stimulus_in_seconds],
                            t=10,
                            coherence=[0], # 0: 0% coherence
                            frozen=[0], # frozen describes the time (in seconds) that the dots remain frozen on screen
                            theta_relative=[random.choice(self.left_right)] # theta_relative describes direction of the moving dots;
                            # For choice in GUI (stays the same): theta_relative = self.direction_of_dots
                        )
                    ),
                ),
            )



        return stimuli


if __name__ == "__main__":
    # This is the line that actually opens stytra with the new protocol.
    st = Stytra(protocol=VisualStim_dots(), camera=dict(type="basler",cam_idx=0),stim_plot=True)
