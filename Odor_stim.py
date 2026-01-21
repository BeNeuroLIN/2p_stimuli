## 2p olfactory stimualtion
# author: paula.pflitsch@lin-magdeburg.de

import numpy as np
from stytra import Stytra, Protocol #Required for stytra interface usage
import pandas as pd #Required for ContinuousRandomDotKinematogram
#from stytra.stimulation.stimuli.visual import Pause #Required for black screen "pauses" in stimuli
from lightparam import Param #Required so we can change parameters in the GUI
from stytra.stimulation.stimuli.arduino import WriteArduinoPin

from pypylon import pylon


# 1. Define a protocol
class Odor_protocol(Protocol):
    name = "Odor_protocol"  # every protocol must have a name.
    # In the stytra_config class attribute we specify a dictionary of
    # parameters that control camera, tracking, monitor, etc.
    # In this particular case, we add a stream of frames from a spinnaker camera
    stytra_config = dict(
        tracking=dict(embedded=True, method="tail"),
        camera=dict(camera=dict(type="basler",cam_idx=0)),
        #Change the arduino configuration here!
        #Before using a pin in the protocol it needs to be set up here.
        arduino_config=dict(
            com_port="COM3", #string - On which com port is the arduino?
            layout=[dict(pin=13, mode="output", ad="d"),
                    dict(pin=3, mode="output", ad="d"),
                    dict(pin=7, mode="output", ad="d"),
                    dict(pin=11, mode="output", ad="d")]
            #layout of the pins you want to use later
            #pin = int (Number of pin to configure)
            #mode = string (Mode of the pin) "input", "output", "pwm" or "servo"
            #ad = string (analog or digital pin?) "a" or "d"
        )
    )

# Define the parameters which will be changeable in the Graphical User Interface (GUI)
    def __init__(self):
        super().__init__()
        self.number_of_repeats = Param(1, limits=None)
        self.duration_of_stimulus_in_seconds = Param(10, limits=None)
        self.pause_before_stimulus = Param (0, limits=None)
        self.pause_after_stimulus = Param (0, limits=None)

# Define the sequence of stimuli in order
    # WriteArduinoPin = Apply voltage to pin(s) on a previously configured arduino
    def get_stim_sequence(self):
        stimuli = [
            ]
        for i in range (self.number_of_repeats):
            #test arduino is working with lightparam stimuli.append(
            print("Light ON")
            stimuli.append(
                WriteArduinoPin(
                    pin_values_dict={13: 1}, #{pin_number:voltage, ...} can be multiple
                    duration=5
                ),)
            print("Light OFF")
            stimuli.append(
                WriteArduinoPin(
                    pin_values_dict={13: 0},  # {pin_number:voltage, ...} can be multiple
                    duration=5
                ), )
            # water ON
            print("Water ON")
            stimuli.append(
                #The following commands change the voltage on arduino pins
                WriteArduinoPin(
                    pin_values_dict={11: 1}, #{pin_number:voltage, ...} can be multiple
                    duration=5
                ),)
            # water OFF
            print("Water OFF")
            stimuli.append(
                WriteArduinoPin(
                    pin_values_dict={11: 0}, #{pin_number:voltage, ...} can be multiple
                    duration=1
                ),)
            # cadaverine ON
            print("Cadaverine ON")
            stimuli.append(
                WriteArduinoPin(
                    pin_values_dict={3: 1},  # {pin_number:voltage, ...} can be multiple
                    duration=5
                ),)
            # cadaverine OFF
            print("Cadaverine OFF")
            stimuli.append(
                WriteArduinoPin(
                    pin_values_dict={3: 0},  # {pin_number:voltage, ...} can be multiple
                    duration=1
                ),)
            # water ON
            print("Water ON")
            stimuli.append(
                # The following commands change the voltage on arduino pins
                WriteArduinoPin(
                    pin_values_dict={11: 1},  # {pin_number:voltage, ...} can be multiple
                    duration=5
                ),)
        return stimuli

if __name__ == "__main__":
    # This is the line that actually opens stytra with the new protocol.
    st = Stytra(protocol=Odor_protocol(), camera=dict(type="basler",cam_idx=0))