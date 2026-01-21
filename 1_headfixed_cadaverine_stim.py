# 2p olfactory stimulation
# author: paula.pflitsch@lin-magdeburg.de


from stytra import Stytra, Protocol
from lightparam import Param
from stytra.stimulation.stimuli.arduino import WriteArduinoPin


class OdorProtocol(Protocol):
    name = "Odor_protocol"

    # Configure tracking/camera as you already have (basler backend working),

    # and IMPORTANT: configure BOTH Arduino pins as digital outputs.

    stytra_config = dict(

        tracking=dict(embedded=True, method="tail"),

        camera=dict(camera=dict(type="basler")),

        arduino_config=dict(

            com_port="COM3",  # update if your Arduino is on a different port

            layout=[

                dict(pin=11, mode="output", ad="d"),  # water valve

                dict(pin=3, mode="output", ad="d"),  # cadaverine valve

                dict(pin=7, mode="output", ad="d"),  # good odor valve

            ],

        ),

    )

    def __init__(self):
        super().__init__()

        # GUI-editable params (optional)

        self.water_on_1 = Param(60.0, limits=None)  # first water ON
        self.water_off_1 = Param(1.0, limits=None)  # water OFF
        self.cadav_on = Param(20.0, limits=None)  # cadaverine ON
        self.cadav_off = Param(20.0, limits=None)  # cadaverine OFF
        self.water_on_2 = Param(60.0, limits=None)  # second water ON
        self.water_off_2 = Param(1.0, limits=None)  # second water OFF
        self.odor2_on = Param(60.0, limits=None)  # second odor ON
        self.odor2_off = Param(1.0, limits=None)  # second odor ON
        self.repeats = Param(1, limits=None)

    def get_stim_sequence(self):
        stimuli = []

        for _ in range(int(self.repeats)):
            # WATER ON (pin 11 = HIGH) for water_on_1 seconds
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 1}, duration=float(self.water_on_1)))

            # WATER OFF (pin 11 = LOW)
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 0}, duration=float(self.water_off_1)))

            # CADAVERINE ON (pin 3 = HIGH)
            stimuli.append(WriteArduinoPin(pin_values_dict={3: 1}, duration=float(self.cadav_on)))

            # CADAVERINE OFF (pin 3 = LOW)
            stimuli.append(WriteArduinoPin(pin_values_dict={3: 0}, duration=float(self.cadav_off)))

            # WATER ON again
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 1}, duration=float(self.water_on_2)))

            # WATER OFF (pin 11 = LOW)
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 0}, duration=float(self.water_off_2)))

            # Test 3rd valve for odor2
            # ODOR 2 ON (pin 7 = HIGH)
            stimuli.append(WriteArduinoPin(pin_values_dict={7: 1}, duration=float(self.odor2_on)))

            # ODOR 2 OFF (pin 7 = LOW)
            stimuli.append(WriteArduinoPin(pin_values_dict={7: 0}, duration=float(self.odor2_off)))

            # Optional: ensure water is OFF at the end of the block
            stimuli.append(WriteArduinoPin(pin_values_dict={11: 0}, duration=0.5))

        return stimuli


if __name__ == "__main__":
    # Launch Stytra. Camera is your Basler backend; Arduino on COM3.

    st = Stytra(protocol=OdorProtocol(), camera=dict(type="basler"))