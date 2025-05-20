'''2p visual stimulus'''

from stytra import Stytra, Protocol #Required for stytra interface usage
import pandas as pd #Required for ContinuousRandomDotKinematogram
from stytra.stimulation.stimuli.kinematograms import ContinuousRandomDotKinematogram #Required for moving dots stimulus
from stytra.stimulation.stimuli.visual import Pause #Required for black screen "pauses" in stimuli
from lightparam import Param #Required so we can change parameters in the GUI

import random #Allow random choice of stimulus direction

#1. Define A visual Stimulus (for projector)



# 2. Define a protocol subclass
class VisualStim_dots(Protocol):
    name = "VisualStim_dots"  # every protocol must have a name.
    # In the stytra_config class attribute we specify a dictionary of
    # parameters that control camera, tracking, monitor, etc.
    # In this particular case, we add a stream of frames from a spinnaker camera
    stytra_config = dict(
        tracking=dict(embedded=True, method="tail"),
        camera=dict(camera=dict(type="spinnaker")),
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
    # NISetVoltageStimulus = Apply voltage to an NI board ao channel
    def get_stim_sequence(self):
        stimuli = [
            ]
        for i in range (self.number_of_repeats):
            stimuli.append(
                ContinuousRandomDotKinematogram(
                    dot_density=0.3,
                    dot_radius=0.4,
                    df_param=pd.DataFrame(
                        dict(
                            # t=[self.duration_of_stimulus_in_seconds],
                            t=10,
                            coherence=[0],  # 0: 0% coherence
                            frozen=[0],  # frozen describes the time (in seconds) that the dots remain frozen on screen
                            theta_relative=[random.choice(self.left_right)]
                            # theta_relative describes direction of the moving dots;
                            # For choice in GUI (stays the same): theta_relative = self.direction_of_dots
                        )
                    ),
                ),
            )
            stimuli.append(
                ContinuousRandomDotKinematogram(
                    dot_density=0.3,
                    dot_radius=0.4,
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
                ),
            )
            stimuli.append(
                ContinuousRandomDotKinematogram(
                    dot_density=0.3,
                    dot_radius=0.4,
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
    st = Stytra(protocol=VisualStim_dots(), camera=dict(type="spinnaker"),stim_plot=True)
