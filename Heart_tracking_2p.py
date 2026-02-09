'''
Author: paula.pflitsch@lin-magdeburg.de


This code accesses a FLIR Camera connected to the computer.
The camera can be used in a free-run mode or in a triggered mode. In the triggered mode it waits for the rising edge
signal (above a threshold of 2.5) before it records and saves a video in a specified destination.

Remarks.
Make sure the file naming is consistent with the 2p file naming:

"...A01" continued with A02,...

Include a switch between the free-run and the triggered mode. The default should be the free-run and you can start the
trigger from that mode.

Please install Spinnaker SDK from here. The version should be newer than 1.27.0.48.
https://www.teledynevisionsolutions.com/support/support-center/software-firmware-downloads/iis/spinnaker-sdk-download/spinnaker-sdk--download-files/?pn=Spinnaker+SDK&vn=Spinnaker+SDK

'''

"""
FLIR Camera Video Capture with Free-Run and Triggered Modes

This script controls a FLIR camera using the Spinnaker SDK.
It supports:
- Free-run mode: Continuous video preview
- Triggered mode: Hardware trigger (rising edge, 2.5V threshold) to record video

File naming follows the pattern: ...A01, A02, A03, etc.

Requirements:
- Spinnaker SDK >= 1.27.0.48
- PySpin (Python wrapper for Spinnaker)

Installation:
1. Download and install Spinnaker SDK from:
   https://www.flir.com/products/spinnaker-sdk/
2. Install PySpin: pip install spinnaker-python
"""

import PySpin
import cv2
import numpy as np
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")

class FLIRCameraController:
    """
    Controller for FLIR camera with free-run and triggered recording modes.
    """

    def __init__(self, output_dir="./recordings", base_filename="video"):
        """
        Initialize the camera controller.

        Args:
            output_dir: Directory to save recorded videos
            base_filename: Base name for video files (will append A01, A02, etc.)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.base_filename = base_filename
        self.system = None
        self.cam = None
        self.nodemap = None
        self.nodemap_tldevice = None

        self.recording = False
        self.video_writer = None
        self.current_recording_number = self._get_next_recording_number()

        self.mode = "free-run"  # Default mode: "free-run" or "triggered"
        self.running = True

        # Video settings
        self.fps = 40
        self.codec = cv2.VideoWriter_fourcc(*'XVID')

        #trigger
        self.waiting_for_trigger = False

    def _get_next_recording_number(self):
        """
        Find the next available recording number based on existing files.
        Returns the next number in sequence (e.g., if A01 and A02 exist, returns 3).
        """
        existing_files = list(self.output_dir.glob(f"{self.base_filename}A*.avi"))
        if not existing_files:
            return 1

        # Extract numbers from filenames
        numbers = []
        for file in existing_files:
            # Extract the number after 'A' from filename like "videoA01.avi"
            name = file.stem
            try:
                # Find 'A' and extract digits after it
                a_index = name.rfind('A')
                if a_index != -1:
                    num_str = name[a_index + 1:]
                    numbers.append(int(num_str))
            except (ValueError, IndexError):
                continue

        return max(numbers) + 1 if numbers else 1

    def _get_current_filename(self):
        """Generate filename with current recording number."""
        return self.output_dir / f"{self.base_filename}A{self.current_recording_number:02d}.avi"

    def initialize_camera(self):
        """Initialize the Spinnaker system and camera."""
        try:
            # Retrieve singleton reference to system object
            self.system = PySpin.System.GetInstance()

            # Retrieve list of cameras
            cam_list = self.system.GetCameras()

            if cam_list.GetSize() == 0:
                print("ERROR: No cameras detected!")
                cam_list.Clear()
                self.system.ReleaseInstance()
                return False

            # Use the first camera
            self.cam = cam_list[0]

            # Initialize camera
            self.cam.Init()

            # Retrieve GenICam nodemap
            self.nodemap = self.cam.GetNodeMap()
            self.nodemap_tldevice = self.cam.GetTLDeviceNodeMap()

            # Print camera info
            self._print_camera_info()

            # Configure camera
            self._configure_camera()

            print(f"Camera initialized successfully in {self.mode} mode")
            return True

        except PySpin.SpinnakerException as ex:
            print(f"ERROR: {ex}")
            return False

    def _print_camera_info(self):
        """Print camera device information."""
        try:
            node_device_information = PySpin.CCategoryPtr(
                self.nodemap_tldevice.GetNode('DeviceInformation'))

            if PySpin.IsAvailable(node_device_information) and \
                    PySpin.IsReadable(node_device_information):
                features = node_device_information.GetFeatures()
                print("\n*** CAMERA INFORMATION ***")
                for feature in features:
                    node_feature = PySpin.CValuePtr(feature)
                    print(f"{node_feature.GetName()}: {node_feature.ToString()}")
                print()
        except PySpin.SpinnakerException as ex:
            print(f"Error printing camera info: {ex}")

    def _configure_camera(self):
        """Configure camera settings."""
        try:
            # Set acquisition mode to continuous
            node_acquisition_mode = PySpin.CEnumerationPtr(
                self.nodemap.GetNode('AcquisitionMode'))
            if not PySpin.IsAvailable(node_acquisition_mode) or \
                    not PySpin.IsWritable(node_acquisition_mode):
                print("Unable to set acquisition mode. Aborting...")
                return False

            node_acquisition_mode_continuous = node_acquisition_mode.GetEntryByName('Continuous')
            acquisition_mode_continuous = node_acquisition_mode_continuous.GetValue()
            node_acquisition_mode.SetIntValue(acquisition_mode_continuous)
            print("Acquisition mode set to continuous")

            # Configure trigger mode based on current mode setting
            if self.mode == "triggered":
                self._configure_trigger_mode(enable=True)
            else:
                self._configure_trigger_mode(enable=False)

            # Set pixel format to BGR8 for OpenCV compatibility
            try:
                node_pixel_format = PySpin.CEnumerationPtr(
                    self.nodemap.GetNode('PixelFormat'))
                if PySpin.IsAvailable(node_pixel_format) and \
                        PySpin.IsWritable(node_pixel_format):
                    node_pixel_format_bgr8 = node_pixel_format.GetEntryByName('BGR8')
                    if PySpin.IsAvailable(node_pixel_format_bgr8) and \
                            PySpin.IsReadable(node_pixel_format_bgr8):
                        pixel_format_bgr8 = node_pixel_format_bgr8.GetValue()
                        node_pixel_format.SetIntValue(pixel_format_bgr8)
                        print("Pixel format set to BGR8")
            except PySpin.SpinnakerException as ex:
                print(f"Unable to set pixel format (will convert): {ex}")

            return True

        except PySpin.SpinnakerException as ex:
            print(f"Error configuring camera: {ex}")
            return False

    def _configure_trigger_mode(self, enable=True, line="Line2", selector="AcquisitionStart"):
        """
        Configure hardware trigger mode.
        enable=True  -> triggered
        enable=False -> free-run
        """
        try:
            # Ensure camera is not acquiring
            try:
                if self.cam.IsStreaming():
                    self.cam.EndAcquisition()
            except Exception:
                pass

            node_trigger_mode = PySpin.CEnumerationPtr(self.nodemap.GetNode('TriggerMode'))
            if not PySpin.IsAvailable(node_trigger_mode) or not PySpin.IsWritable(node_trigger_mode):
                print("Unable to access TriggerMode")
                return False

            # Always turn trigger OFF before changing other trigger settings
            node_trigger_mode_off = node_trigger_mode.GetEntryByName('Off')
            node_trigger_mode.SetIntValue(node_trigger_mode_off.GetValue())

            if enable:
                # TriggerSelector (FrameStart vs AcquisitionStart)
                node_trigger_selector = PySpin.CEnumerationPtr(self.nodemap.GetNode('TriggerSelector'))
                if PySpin.IsAvailable(node_trigger_selector) and PySpin.IsWritable(node_trigger_selector):
                    entry = node_trigger_selector.GetEntryByName(selector)
                    if PySpin.IsAvailable(entry) and PySpin.IsReadable(entry):
                        node_trigger_selector.SetIntValue(entry.GetValue())
                    else:
                        print(f"TriggerSelector entry '{selector}' not available; leaving default.")
                else:
                    print("TriggerSelector not available on this camera (OK).")

                # TriggerSource (Line2)
                node_trigger_source = PySpin.CEnumerationPtr(self.nodemap.GetNode('TriggerSource'))
                if PySpin.IsAvailable(node_trigger_source) and PySpin.IsWritable(node_trigger_source):
                    entry = node_trigger_source.GetEntryByName(line)
                    if PySpin.IsAvailable(entry) and PySpin.IsReadable(entry):
                        node_trigger_source.SetIntValue(entry.GetValue())
                    else:
                        print(f"TriggerSource '{line}' not available.")
                        return False
                else:
                    print("TriggerSource not available.")
                    return False

                # TriggerActivation (RisingEdge)
                node_trigger_activation = PySpin.CEnumerationPtr(self.nodemap.GetNode('TriggerActivation'))
                if PySpin.IsAvailable(node_trigger_activation) and PySpin.IsWritable(node_trigger_activation):
                    entry = node_trigger_activation.GetEntryByName('RisingEdge')
                    if PySpin.IsAvailable(entry) and PySpin.IsReadable(entry):
                        node_trigger_activation.SetIntValue(entry.GetValue())
                else:
                    print("TriggerActivation not available (OK).")

                # Configure the physical line as input (if supported)
                node_line_selector = PySpin.CEnumerationPtr(self.nodemap.GetNode('LineSelector'))
                if PySpin.IsAvailable(node_line_selector) and PySpin.IsWritable(node_line_selector):
                    entry = node_line_selector.GetEntryByName(line)
                    if PySpin.IsAvailable(entry) and PySpin.IsReadable(entry):
                        node_line_selector.SetIntValue(entry.GetValue())

                        node_line_mode = PySpin.CEnumerationPtr(self.nodemap.GetNode('LineMode'))
                        if PySpin.IsAvailable(node_line_mode) and PySpin.IsWritable(node_line_mode):
                            entry2 = node_line_mode.GetEntryByName('Input')
                            if PySpin.IsAvailable(entry2) and PySpin.IsReadable(entry2):
                                node_line_mode.SetIntValue(entry2.GetValue())

                # Finally turn trigger ON
                node_trigger_mode_on = node_trigger_mode.GetEntryByName('On')
                node_trigger_mode.SetIntValue(node_trigger_mode_on.GetValue())

                print(f"Trigger ENABLED: {selector}, {line}, RisingEdge")

            else:
                print("Trigger DISABLED (free-run)")

            return True

        except PySpin.SpinnakerException as ex:
            print(f"Error configuring trigger: {ex}")
            return False

    def switch_mode(self, new_mode):
        if new_mode not in ["free-run", "triggered"]:
            print(f"Invalid mode: {new_mode}")
            return False
        if new_mode == self.mode:
            print(f"Already in {new_mode} mode")
            return True

        print(f"Switching from {self.mode} to {new_mode} mode...")

        if self.recording:
            self.stop_recording()

        if self.cam and self.cam.IsStreaming():
            self.cam.EndAcquisition()

        self.mode = new_mode

        if new_mode == "triggered":
            ok = self._configure_trigger_mode(enable=True, line="Line2", selector="AcquisitionStart")
        else:
            ok = self._configure_trigger_mode(enable=False)

        if not ok:
            print("Failed to switch mode.")
            return False

        self.cam.BeginAcquisition()
        print(f"Switched to {new_mode} mode successfully")
        return True

    def start_recording(self):
        """Start recording video."""
        if self.recording:
            print("Already recording!")
            return False

        try:
            # Get the first image to determine frame size
            timeout = 10 if (self.mode == "triggered" and self.waiting_for_trigger) else 1000
            image_result = self.cam.GetNextImage(timeout)

            if image_result.IsIncomplete():
                print("Image incomplete")
                image_result.Release()
                return False

            # Get image dimensions
            width = image_result.GetWidth()
            height = image_result.GetHeight()

            # Release the image
            image_result.Release()

            # Get filename
            filename = str(self._get_current_filename())

            # Create video writer
            self.video_writer = cv2.VideoWriter(
                filename,
                self.codec,
                self.fps,
                (width, height)
            )

            if not self.video_writer.isOpened():
                print("Failed to open video writer")
                return False

            self.recording = True
            print(f"Started recording: {filename}")
            return True


        except PySpin.SpinnakerException as ex:
            # very common in triggered mode when no trigger has happened yet
            if self.mode == "triggered" and self.waiting_for_trigger:
                # keep UI alive
                key = cv2.waitKey(1) & 0xFF
                continue
            print(f"Error: {ex}")
            continue

    def stop_recording(self):
        """Stop recording video."""
        if not self.recording:
            return

        self.recording = False

        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None

        print(f"Stopped recording: {self._get_current_filename()}")

        # Increment recording number for next recording
        self.current_recording_number += 1

    def run(self):
        """Main loop for camera operation."""
        if not self.cam:
            print("Camera not initialized!")
            return

        try:
            # Begin acquisition
            self.cam.BeginAcquisition()
            print(f"\nStarted acquisition in {self.mode} mode")
            print("\nControls:")
            print("  'r' - Start/stop recording (free-run mode)")
            print("  't' - Switch to triggered mode")
            print("  'f' - Switch to free-run mode")
            print("  'q' - Quit")
            print("\nIn triggered mode, recording starts automatically on trigger signal.\n")

            while self.running:
                try:
                    # Get next image
                    image_result = self.cam.GetNextImage(1000)

                    if image_result.IsIncomplete():
                        print(f"Image incomplete: {image_result.GetImageStatus()}")
                    else:
                        # Convert to numpy array
                        image_data = image_result.GetNDArray()

                        # Convert to BGR if necessary
                        if len(image_data.shape) == 2:  # Grayscale
                            image_bgr = cv2.cvtColor(image_data, cv2.COLOR_GRAY2BGR)
                        else:
                            image_bgr = image_data

                        # Add status overlay
                        status_text = f"Mode: {self.mode.upper()}"
                        if self.recording:
                            status_text += " | RECORDING"
                            cv2.circle(image_bgr, (30, 30), 10, (0, 0, 255), -1)

                        cv2.putText(image_bgr, status_text, (50, 35),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                        # Write frame if recording
                        if self.recording and self.video_writer:
                            self.video_writer.write(image_bgr)

                        # Display frame
                        cv2.imshow('FLIR Camera', image_bgr)

                    # Release image
                    image_result.Release()

                    # Handle keyboard input
                    key = cv2.waitKey(1) & 0xFF

                    if key == ord('q'):
                        print("Quitting...")
                        self.running = False
                    elif key == ord('r') and self.mode == "free-run":
                        if self.recording:
                            self.stop_recording()
                        else:
                            self.start_recording()
                    elif key == ord('t'):
                        self.switch_mode("triggered")
                        self.waiting_for_trigger = True
                        print("Triggered mode armed. Waiting for first trigger/frame...")
                    elif key == ord('f'):
                        self.switch_mode("free-run")
                        self.waiting_for_trigger = False



                except PySpin.SpinnakerException as ex:
                    print(f"Error: {ex}")
                    continue

            # Cleanup
            if self.recording:
                self.stop_recording()

            self.cam.EndAcquisition()
            cv2.destroyAllWindows()

        except PySpin.SpinnakerException as ex:
            print(f"Error: {ex}")

    def cleanup(self):
        """Clean up camera and system resources."""
        try:
            if self.recording:
                self.stop_recording()

            if self.cam:
                if self.cam.IsStreaming():
                    self.cam.EndAcquisition()

                self.cam.DeInit()
                del self.cam

            if self.system:
                # Clear camera list before releasing system
                cam_list = self.system.GetCameras()
                cam_list.Clear()

                self.system.ReleaseInstance()

            cv2.destroyAllWindows()
            print("Camera resources released")

        except PySpin.SpinnakerException as ex:
            print(f"Error during cleanup: {ex}")


def main():
    """Main function."""
    import argparse

    # If we are armed in triggered mode and first frame arrived, start recording NOW
    if self.mode == "triggered" and self.waiting_for_trigger and not self.recording:
        self.start_recording()
        self.waiting_for_trigger = False


    parser = argparse.ArgumentParser(
        description='FLIR Camera Control with Free-Run and Triggered Modes')
    parser.add_argument('--output-dir', '-o', default='./recordings',
                        help='Output directory for recordings (default: ./recordings)')
    parser.add_argument('--base-filename', '-b', default='video',
                        help='Base filename for recordings (default: video)')
    parser.add_argument('--fps', '-fps', type=int, default=30,
                        help='Frame rate for recordings (default: 30)')
    parser.add_argument('--mode', '-m', choices=['free-run', 'triggered'],
                        default='free-run',
                        help='Initial mode (default: free-run)')

    args = parser.parse_args()

    # Create controller
    # Create date folder inside output-dir
    date_str = today_yyyymmdd()
    dated_output_dir = Path(args.output_dir) / date_str

    # Force base filename to be like 20260209_
    base_filename = f"{date_str}_"

    controller = FLIRCameraController(
        output_dir=str(dated_output_dir),
        base_filename=base_filename
    )
    controller.fps = args.fps
    controller.mode = args.mode

    # Initialize camera
    if not controller.initialize_camera():
        print("Failed to initialize camera")
        return 1

    try:
        # Run main loop
        controller.run()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        # Cleanup
        controller.cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())

    if self.mode == "triggered" and self.waiting_for_trigger and not self.recording:
        self.start_recording()
        self.waiting_for_trigger = False








