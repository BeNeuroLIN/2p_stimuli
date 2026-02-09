#!/usr/bin/env python3
"""
FLIR/Point Grey (Spinnaker) capture script for heart-rate recordings using PySpin.

Features
- Free-run preview by default
- From free-run, you can arm a trigger and record a video on the next rising-edge
  (TTL > ~2.5 V is typically handled by your I/O hardware; in Spinnaker you set "RisingEdge")
- Saves AVI with consistent 2p-style suffix: ...A01, ...A02, ...
- Works with either direct free-run recording or triggered recording

Notes
- Triggered mode here uses TriggerSelector = AcquisitionStart:
  one rising edge starts the acquisition/recording, then frames stream until duration ends.
  If your camera/IO only supports FrameStart triggering, switch selector to "FrameStart"
  (but then you'll need a trigger for every frame).
"""

import argparse
import os
import re
import sys
import time
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

import PySpin


# -------------------------
# Naming helpers (2p-style)
# -------------------------

_SUFFIX_RE = re.compile(r"^(?P<base>.*)A(?P<num>\d{2})$")


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def next_2p_name(dest_dir: str, base_prefix: str, ext: str = ".avi") -> Tuple[str, str]:
    """
    Returns (stem, full_path) where stem ends with A## (zero-padded).
    Example: base_prefix="exp1_" -> "exp1_A01"
    If base_prefix already ends with A##, it increments that series.
    Otherwise it appends A01.
    """
    _ensure_dir(dest_dir)

    # If user provided base already ending in A##
    m = _SUFFIX_RE.match(base_prefix)
    if m:
        base = m.group("base")
        start_num = int(m.group("num"))
    else:
        base = base_prefix
        start_num = 1

    # Scan existing files to find max A##
    # Match: base + "A" + two digits + ext
    pattern = re.compile(re.escape(base) + r"A(?P<num>\d{2})" + re.escape(ext) + r"$")
    max_num = 0
    for fn in os.listdir(dest_dir):
        mm = pattern.match(fn)
        if mm:
            max_num = max(max_num, int(mm.group("num")))

    # If user gave A## explicitly and it's higher than scanned, respect it
    max_num = max(max_num, start_num - 1)

    new_num = max_num + 1
    stem = f"{base}A{new_num:02d}"
    full_path = os.path.join(dest_dir, stem + ext)
    return stem, full_path


# -------------------------
# PySpin configuration
# -------------------------

@dataclass
class CaptureConfig:
    dest_dir: str
    base_prefix: str
    duration_s: float
    fps: float
    triggered: bool
    trigger_line: str = "Line0"
    trigger_selector: str = "AcquisitionStart"  # or "FrameStart"
    pixel_format: str = "Mono8"  # good default for physiological signals
    exposure_us: Optional[float] = None  # set if you want fixed exposure
    gain_db: Optional[float] = None      # set if you want fixed gain
    timeout_ms: int = 2000               # image retrieval timeout


def _set_enum(nodemap, node_name: str, entry_name: str) -> None:
    node = PySpin.CEnumerationPtr(nodemap.GetNode(node_name))
    if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
        raise RuntimeError(f"Node {node_name} not writable/available.")
    entry = node.GetEntryByName(entry_name)
    if not PySpin.IsAvailable(entry) or not PySpin.IsReadable(entry):
        raise RuntimeError(f"Enum entry {entry_name} for {node_name} not readable/available.")
    node.SetIntValue(entry.GetValue())


def _set_float(nodemap, node_name: str, value: float) -> None:
    node = PySpin.CFloatPtr(nodemap.GetNode(node_name))
    if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
        raise RuntimeError(f"Node {node_name} not writable/available.")
    node.SetValue(value)


def _set_bool(nodemap, node_name: str, value: bool) -> None:
    node = PySpin.CBooleanPtr(nodemap.GetNode(node_name))
    if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
        raise RuntimeError(f"Node {node_name} not writable/available.")
    node.SetValue(value)


def configure_camera_for_freerun(cam: PySpin.CameraPtr, cfg: CaptureConfig) -> None:
    nodemap = cam.GetNodeMap()

    # Acquisition mode: Continuous
    _set_enum(nodemap, "AcquisitionMode", "Continuous")

    # Disable trigger
    _set_enum(nodemap, "TriggerMode", "Off")

    # Pixel format
    try:
        _set_enum(nodemap, "PixelFormat", cfg.pixel_format)
    except Exception:
        # Some cameras require using Stream/Device nodemaps or different naming
        # Keep going if PixelFormat can't be set; you'll get whatever default is.
        pass

    # Optional: fixed exposure/gain
    if cfg.exposure_us is not None:
        try:
            _set_enum(nodemap, "ExposureAuto", "Off")
            _set_float(nodemap, "ExposureTime", float(cfg.exposure_us))
        except Exception:
            pass

    if cfg.gain_db is not None:
        try:
            _set_enum(nodemap, "GainAuto", "Off")
            _set_float(nodemap, "Gain", float(cfg.gain_db))
        except Exception:
            pass


def configure_camera_for_triggered(cam: PySpin.CameraPtr, cfg: CaptureConfig) -> None:
    nodemap = cam.GetNodeMap()

    # Acquisition mode: Continuous (common for triggered AcquisitionStart)
    _set_enum(nodemap, "AcquisitionMode", "Continuous")

    # Configure the input line (if supported)
    # This sets the line as an input; actual voltage threshold is typically electrical/hardware-level.
    try:
        _set_enum(nodemap, "LineSelector", cfg.trigger_line)
        _set_enum(nodemap, "LineMode", "Input")
    except Exception:
        # Not all models expose LineMode/LineSelector the same way
        pass

    # Trigger settings
    _set_enum(nodemap, "TriggerMode", "Off")  # must be off to change settings

    # Choose whether we trigger AcquisitionStart (one pulse starts stream) or FrameStart (pulse per frame)
    _set_enum(nodemap, "TriggerSelector", cfg.trigger_selector)

    _set_enum(nodemap, "TriggerSource", cfg.trigger_line)
    _set_enum(nodemap, "TriggerActivation", "RisingEdge")

    # Turn trigger on
    _set_enum(nodemap, "TriggerMode", "On")

    # Pixel format
    try:
        _set_enum(nodemap, "PixelFormat", cfg.pixel_format)
    except Exception:
        pass

    # Optional: fixed exposure/gain
    if cfg.exposure_us is not None:
        try:
            _set_enum(nodemap, "ExposureAuto", "Off")
            _set_float(nodemap, "ExposureTime", float(cfg.exposure_us))
        except Exception:
            pass

    if cfg.gain_db is not None:
        try:
            _set_enum(nodemap, "GainAuto", "Off")
            _set_float(nodemap, "Gain", float(cfg.gain_db))
        except Exception:
            pass


# -------------------------
# Recording
# -------------------------

def _create_avi_recorder(output_path: str, fps: float) -> PySpin.SpinVideo:
    """
    Creates an MJPG AVI recorder via PySpin SpinVideo.
    """
    avi_opts = PySpin.AVIOption()
    avi_opts.frameRate = float(fps)
    avi_opts.quality = 75  # 1..100 (higher = better, larger files)

    recorder = PySpin.SpinVideo()
    recorder.Open(output_path, avi_opts)
    return recorder


def record_video(cam: PySpin.CameraPtr, cfg: CaptureConfig, wait_for_trigger_first_frame: bool) -> str:
    """
    Records a video to disk and returns the output file path.
    If wait_for_trigger_first_frame=True, the function blocks until the first image arrives
    (i.e., the trigger happens for AcquisitionStart, or first FrameStart trigger).
    """
    stem, out_path = next_2p_name(cfg.dest_dir, cfg.base_prefix, ext=".avi")
    print(f"[INFO] Recording will be saved as: {out_path}")

    recorder = _create_avi_recorder(out_path, cfg.fps)

    # Decide how many frames to capture
    target_frames = max(1, int(round(cfg.duration_s * cfg.fps)))
    print(f"[INFO] Target: {target_frames} frames at ~{cfg.fps} fps (~{cfg.duration_s:.2f} s)")

    t0 = time.time()
    frames_written = 0

    # If triggered, you often want to block until first frame (meaning trigger occurred)
    if wait_for_trigger_first_frame:
        print("[INFO] Waiting for rising-edge trigger (first frame)...")
        # Keep trying until we get an image (timeout loops are fine)
        while True:
            try:
                img = cam.GetNextImage(cfg.timeout_ms)
                if img.IsIncomplete():
                    img.Release()
                    continue
                # Got first valid frame: trigger happened
                recorder.Append(img)
                img.Release()
                frames_written = 1
                print("[INFO] Trigger received, recording started.")
                break
            except PySpin.SpinnakerException:
                # timeout - keep waiting
                continue

    # Now record remaining frames
    while frames_written < target_frames:
        try:
            img = cam.GetNextImage(cfg.timeout_ms)
            if img.IsIncomplete():
                img.Release()
                continue
            recorder.Append(img)
            img.Release()
            frames_written += 1
        except PySpin.SpinnakerException as e:
            # If in FrameStart trigger mode, timeouts can happen if triggers are slow.
            # Continue until we hit target_frames (or user stops the program).
            print(f"[WARN] Image grab issue/timeout: {e}")
            continue

    recorder.Close()
    dt = time.time() - t0
    print(f"[INFO] Saved {frames_written} frames in {dt:.2f}s -> {out_path}")
    print(f"[INFO] Output stem (2p-style): {stem}")
    return out_path


# -------------------------
# Simple interactive control
# -------------------------

class CommandListener:
    """
    Reads stdin commands in a background thread.
    Commands:
      - 't' + Enter: arm trigger & record once
      - 'r' + Enter: record immediately in free-run
      - 'q' + Enter: quit
      - 'h' + Enter: help
    """
    def __init__(self):
        self.last_cmd = None
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop = True

    def pop(self) -> Optional[str]:
        cmd = self.last_cmd
        self.last_cmd = None
        return cmd

    def _run(self):
        while not self._stop:
            try:
                line = sys.stdin.readline()
                if not line:
                    # EOF
                    self._stop = True
                    return
                self.last_cmd = line.strip().lower()
            except Exception:
                self._stop = True
                return


def run(cfg: CaptureConfig) -> None:
    system = PySpin.System.GetInstance()
    cam_list = system.GetCameras()

    if cam_list.GetSize() < 1:
        cam_list.Clear()
        system.ReleaseInstance()
        raise RuntimeError("No FLIR cameras detected by PySpin/Spinnaker.")

    cam = cam_list.GetByIndex(0)
    cam.Init()

    try:
        # Default: free-run configuration
        configure_camera_for_freerun(cam, cfg)

        # Start acquisition so the camera is "live" in free-run
        cam.BeginAcquisition()

        listener = CommandListener()
        listener.start()

        print("\n[READY] Free-run mode (default).")
        print("Commands:")
        print("  t  -> arm trigger & record once when rising edge arrives")
        print("  r  -> record immediately (free-run recording)")
        print("  q  -> quit")
        print("  h  -> help\n")

        while True:
            cmd = listener.pop()
            if cmd is None:
                # Light-weight "heartbeat" so loop doesn't spin too hard
                time.sleep(0.05)
                continue

            if cmd == "h":
                print("Commands: t=triggered record, r=free-run record, q=quit, h=help")
                continue

            if cmd == "q":
                print("[INFO] Quitting.")
                break

            if cmd == "r":
                print("[INFO] Free-run record requested.")
                # Ensure free-run config
                cam.EndAcquisition()
                configure_camera_for_freerun(cam, cfg)
                cam.BeginAcquisition()
                record_video(cam, cfg, wait_for_trigger_first_frame=False)
                continue

            if cmd == "t":
                print("[INFO] Triggered record requested (arming trigger).")
                # Switch to triggered mode, arm trigger, record once, then return to free-run
                cam.EndAcquisition()
                configure_camera_for_triggered(cam, cfg)
                cam.BeginAcquisition()

                # Record (wait for trigger before first frame)
                record_video(cam, cfg, wait_for_trigger_first_frame=True)

                # Return to free-run default
                cam.EndAcquisition()
                configure_camera_for_freerun(cam, cfg)
                cam.BeginAcquisition()
                print("[INFO] Returned to free-run mode.")
                continue

            print(f"[WARN] Unknown command: {cmd!r}. Type 'h' for help.")

        listener.stop()
        cam.EndAcquisition()

    finally:
        cam.DeInit()
        del cam
        cam_list.Clear()
        system.ReleaseInstance()


def parse_args() -> CaptureConfig:
    p = argparse.ArgumentParser(description="FLIR heart-rate video capture with free-run + triggered mode (PySpin).")
    p.add_argument("--dest", required=True, help="Destination directory for saved videos.")
    p.add_argument("--prefix", required=True,
                   help="Base filename prefix (2p-style suffix A01/A02/... will be appended). "
                        "Example: 'mouse1_session1_' -> mouse1_session1_A01. "
                        "If you pass something ending with A## it will continue that series.")
    p.add_argument("--duration", type=float, default=10.0, help="Recording duration in seconds (default 10).")
    p.add_argument("--fps", type=float, default=60.0, help="Nominal FPS for output video metadata (default 60).")
    p.add_argument("--mode", choices=["free", "trigger"], default="free",
                   help="Start mode. Default free. In free mode you can still arm trigger with 't'.")
    p.add_argument("--trigger-line", default="Line0", help="Trigger input line (default Line0).")
    p.add_argument("--trigger-selector", choices=["AcquisitionStart", "FrameStart"], default="AcquisitionStart",
                   help="Trigger selector. AcquisitionStart = one trigger starts streaming; FrameStart = trigger each frame.")
    p.add_argument("--pixelformat", default="Mono8", help="Pixel format, e.g. Mono8 (default), Mono16, RGB8, etc.")
    p.add_argument("--exposure-us", type=float, default=None, help="Fixed exposure time in microseconds (optional).")
    p.add_argument("--gain-db", type=float, default=None, help="Fixed gain in dB (optional).")
    p.add_argument("--timeout-ms", type=int, default=2000, help="Image grab timeout in ms (default 2000).")
    a = p.parse_args()

    return CaptureConfig(
        dest_dir=a.dest,
        base_prefix=a.prefix,
        duration_s=a.duration,
        fps=a.fps,
        triggered=(a.mode == "trigger"),
        trigger_line=a.trigger_line,
        trigger_selector=a.trigger_selector,
        pixel_format=a.pixelformat,
        exposure_us=a.exposure_us,
        gain_db=a.gain_db,
        timeout_ms=a.timeout_ms,
    )


if __name__ == "__main__":
    cfg = parse_args()
    try:
        run(cfg)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)