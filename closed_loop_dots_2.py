"""
stytra_nidaq_triggered.py
-------------------------
Stytra visual‑stimulation protocol with NI DAQ edge‑triggered start/stop.

HOW IT WORKS
------------
1.  Press **Play** in the Stytra GUI.  The protocol prints
        ">>> WAITING FOR RISING EDGE …"
    and does NOT advance to the first stimulus.

2.  A background thread continuously polls the configured digital‑input
    channel on your NI DAQ board.

3.  RISING EDGE detected  →  the stimulus sequence starts from the
    beginning (pre‑stim → coherent motion → post‑stim, repeated N times).

4.  FALLING EDGE detected →  the stimulus sequence is aborted
    immediately; the protocol prints a summary and returns to the
    waiting state so it can be re‑triggered without restarting the
    Stytra application.

INSTALL nidaqmx (choose ONE of the two commands below)
------------------------------------------------------
    conda install -c conda-forge nidaqmx          # preferred
        OR
    pip install nidaqmx                           # fallback

You also need the NI DAQmx driver installed on Windows.
Download from:  https://www.ni.com/en/support/downloads/software-products/download.daqmx.html

CONFIGURE
---------
Change the two constants near the top of this file to match your wiring:

    DAQ_DEVICE_NAME   – e.g. "Dev1"   (run `nidaqmx.system.System().devices`
                                         to list detected devices)
    DAQ_CHANNEL_PORT  – e.g. "port0/line0"

Then set the desired vigor threshold and other protocol parameters in
the VisualStim_dots.__init__ method as before.
"""

import numpy as np
import pandas as pd
import random
import time
import threading
import traceback

from stytra import Stytra, Protocol
from stytra.stimulation.stimuli.kinematograms import ContinuousRandomDotKinematogram
from lightparam import Param

from datetime import datetime
from pathlib import Path
from typing import Optional
import json

import nidaqmx
from nidaqmx.constants import LineGrouping

# ──────────────────────────────────────────────
# USER‑CONFIGURABLE  –  edit these two lines
# ──────────────────────────────────────────────
DAQ_DEVICE_NAME  = "Dev1"          # e.g. "Dev1", "Dev2" …
DAQ_CHANNEL_PORT = "port0/line0"   # e.g. "port0/line0"
# Full channel name is built automatically: "Dev1/port0/line0"

# How often (seconds) the background thread checks the DAQ line.
# 0.005 s  →  ~200 Hz polling  (plenty fast for behavioural paradigms)
_POLL_INTERVAL = 0.005


# ──────────────────────────────────────────────────────────
# Stimulus classes  (unchanged logic from original code)
# ──────────────────────────────────────────────────────────

class VigorResponsiveDotStim(ContinuousRandomDotKinematogram):
    """Drops coherence to 0 when the fish's tail‑vigor exceeds a threshold."""

    def __init__(self, *args, vigor_threshold=-5.0, original_coherence=1.0, **kwargs):
        self.vigor_threshold   = vigor_threshold
        self.original_coherence = original_coherence
        self.coherence_dropped  = False
        self.current_coherence  = original_coherence
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
                            self.coherence_dropped  = True
                            self.current_coherence  = 0.0
                            print(
                                f">>> VIGOR THRESHOLD EXCEEDED ({vigor:.2f} < "
                                f"{self.vigor_threshold}). COHERENCE DROPPED TO 0. <<<"
                            )

                    if hasattr(self._experiment, 'dynamic_log'):
                        self._experiment.dynamic_log.update_param(
                            'current_coherence', self.current_coherence
                        )
                except Exception as e:
                    print(f"Error getting vigor: {e}")

        super().update()


class TrackedDotStim(ContinuousRandomDotKinematogram):
    """Wrapper that logs the (constant) coherence value into the dynamic log."""

    def __init__(self, *args, tracked_coherence=0.0, **kwargs):
        self.coherence_value = tracked_coherence
        super().__init__(*args, **kwargs)

    def update(self):
        if hasattr(self, '_experiment') and self._experiment is not None:
            if hasattr(self._experiment, 'dynamic_log'):
                self._experiment.dynamic_log.update_param(
                    'current_coherence', self.coherence_value
                )
        super().update()


# ──────────────────────────────────────────────────────────
# DAQ helper  –  runs in its own thread
# ──────────────────────────────────────────────────────────

class DAQEdgeMonitor:
    """
    Polls a single digital‑input line and fires callbacks on edges.

    Attributes / events that the protocol uses
    -------------------------------------------
    rising_edge_event  : threading.Event  – set when a rising edge is seen.
    falling_edge_event : threading.Event  – set when a falling edge is seen.
    """

    def __init__(self, device: str, port_line: str, poll_interval: float = _POLL_INTERVAL):
        self.channel_name  = f"{device}/{port_line}"
        self.poll_interval = poll_interval

        # Synchronisation primitives
        self.rising_edge_event  = threading.Event()
        self.falling_edge_event = threading.Event()

        # Internal state
        self._prev_state   = None        # last known line state (True / False)
        self._stop_flag    = threading.Event()   # set to stop the polling thread
        self._thread       = None

    # ── public API ────────────────────────────────────────

    def start(self):
        """Start the background polling thread."""
        self._stop_flag.clear()
        self.rising_edge_event.clear()
        self.falling_edge_event.clear()
        self._prev_state = None
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f"[DAQ] Monitoring {self.channel_name} …")

    def stop(self):
        """Stop the background polling thread."""
        self._stop_flag.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        print("[DAQ] Monitor stopped.")

    def clear_rising(self):
        self.rising_edge_event.clear()

    def clear_falling(self):
        self.falling_edge_event.clear()

    # ── internal ──────────────────────────────────────────

    def _poll_loop(self):
        """
        Opens a DAQmx task for the duration of the polling loop.
        Reads one sample at a time; detects transitions by comparing
        the current value to the previous one.
        """
        try:
            with nidaqmx.Task() as task:
                task.di_channels.add_di_chan(
                    self.channel_name,
                    line_grouping=LineGrouping.CHAN_PER_LINE
                )
                task.timing.cfg_samp_clk_timing(
                    rate=1000,                          # internal clock rate (Hz)
                    sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
                )

                while not self._stop_flag.is_set():
                    try:
                        # Read a single boolean sample (blocks up to poll_interval)
                        current = task.read(
                            number_of_samples_per_channel=1,
                            timeout=self.poll_interval
                        )
                        # `current` is a list of bool when reading 1 channel
                        state = bool(current[0]) if isinstance(current, list) else bool(current)
                    except nidaqmx.errors.WaitingForDataError:
                        # No new sample within timeout – that's fine, just loop
                        continue
                    except Exception as e:
                        print(f"[DAQ] Read error: {e}")
                        time.sleep(self.poll_interval)
                        continue

                    # Edge detection
                    if self._prev_state is not None:
                        if state and not self._prev_state:          # LOW → HIGH
                            print("[DAQ] *** RISING EDGE detected ***")
                            self.falling_edge_event.clear()
                            self.rising_edge_event.set()
                        elif not state and self._prev_state:        # HIGH → LOW
                            print("[DAQ] *** FALLING EDGE detected ***")
                            self.rising_edge_event.clear()
                            self.falling_edge_event.set()

                    self._prev_state = state

        except Exception as e:
            print(f"[DAQ] Fatal error in poll loop: {e}")
            traceback.print_exc()



# ──────────────────────────────────────────────────────────
# Safe‑save helper
# ──────────────────────────────────────────────────────────

class _SafeSaver:
    """
    Knows how to reach into Stytra's Experiment object and flush
    behaviour_log, stim_log, and metadata to disk *right now*, even
    if the normal end‑of‑protocol path hasn't fired yet.

    Stytra's Experiment stores logs in:
        experiment.behavior_log   – tracking DataFrame
        experiment.stim_log       – list of per‑stimulus dicts
        experiment.metadata       – dict with trial info

    It writes them via experiment.save().  We call that directly.
    If save() isn't available (version difference), we fall back to
    writing the three files ourselves into the same folder Stytra
    would have used.
    """

    @staticmethod
    def flush(protocol, extra_metadata: Optional[dict] = None):
        """
        Parameters
        ----------
        protocol        : the VisualStim_dots instance (has .experiment)
        extra_metadata  : optional dict merged into metadata before saving
                          (used to stamp rising/falling edge timestamps, abort flag, …)
        """
        experiment = getattr(protocol, 'experiment', None)
        if experiment is None:
            print("[SafeSaver] WARNING – no experiment object on protocol; "
                  "cannot save.")
            return

        # ── merge any extra metadata the protocol wants to record ──
        if extra_metadata:
            if hasattr(experiment, 'metadata') and isinstance(experiment.metadata, dict):
                experiment.metadata.update(extra_metadata)
            else:
                # metadata might be a Params object; try attribute‑setting
                for k, v in extra_metadata.items():
                    try:
                        setattr(experiment.metadata, k, v)
                    except Exception:
                        pass   # best‑effort

        # ── primary path: use Stytra's own save() ──────────────────
        if hasattr(experiment, 'save') and callable(experiment.save):
            try:
                experiment.save()
                print("[SafeSaver] experiment.save() completed successfully.")
                return
            except Exception as e:
                print(f"[SafeSaver] experiment.save() raised: {e} – "
                      "falling back to manual save.")
                traceback.print_exc()

        # ── fallback: write files ourselves ─────────────────────────
        # Determine output directory the same way Stytra does:
        #   experiment.folder  (Path or str)
        folder = getattr(experiment, 'folder', None)
        if folder is None:
            folder = Path.cwd() / "stytra_fallback_save"
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # behaviour log
        beh = getattr(experiment, 'behavior_log', None)
        if beh is not None:
            try:
                import pandas as _pd
                if isinstance(beh, _pd.DataFrame):
                    beh.to_csv(folder / f"{ts}_behavior_log.csv", index=False)
                    print(f"[SafeSaver] Wrote behavior_log → {folder}/{ts}_behavior_log.csv")
            except Exception as e:
                print(f"[SafeSaver] Could not write behavior_log: {e}")

        # stimulus log
        slog = getattr(experiment, 'stim_log', None)
        if slog is not None:
            try:
                with open(folder / f"{ts}_stim_log.json", "w") as f:
                    json.dump(slog, f, indent=2, default=str)
                print(f"[SafeSaver] Wrote stim_log → {folder}/{ts}_stim_log.json")
            except Exception as e:
                print(f"[SafeSaver] Could not write stim_log: {e}")

        # metadata
        meta = getattr(experiment, 'metadata', None)
        if meta is not None:
            try:
                # Could be a dict or a Params / dataclass; convert safely
                meta_dict = dict(meta) if not isinstance(meta, dict) else meta
                with open(folder / f"{ts}_metadata.json", "w") as f:
                    json.dump(meta_dict, f, indent=2, default=str)
                print(f"[SafeSaver] Wrote metadata → {folder}/{ts}_metadata.json")
            except Exception as e:
                print(f"[SafeSaver] Could not write metadata: {e}")


# ──────────────────────────────────────────────────────────
# Protocol
# ──────────────────────────────────────────────────────────

class VisualStim_dots(Protocol):
    """
    Edge‑triggered dot‑kinematogram protocol.

    Play flow
    ---------
    Play pressed  →  DAQ monitor starts  →  prints "WAITING FOR RISING EDGE"
                  →  blocks until rising edge
    Rising edge   →  stimulus sequence runs (pre / coherent / post × N)
                  →  each stimulus checks falling_edge_event every frame;
                      if set, the sequence is aborted immediately.
    Sequence ends (naturally or aborted)
                  →  returns to WAITING state (no need to press Play again).
    """

    name = "VisualStim_dots"

    stytra_config = dict(
        tracking=dict(embedded=True, method="tail", estimator="vigor"),
        camera=dict(camera=dict(type="basler", cam_idx=0)),
    )

    def __init__(self):
        super().__init__()
        self.number_of_repeats             = Param(1, limits=None)
        self.duration_of_stimulus_in_seconds = Param(10, limits=None)
        self.pause_before_stimulus         = Param(0,  limits=None)
        self.pause_after_stimulus          = Param(0,  limits=None)
        self.vigor_threshold               = Param(-1.0, limits=(-100, 100))
        self.left_right                    = [0, 3]   # 0 = right, 3 = left

        # DAQ monitor instance (created once, reused across re‑triggers)
        self._daq = DAQEdgeMonitor(DAQ_DEVICE_NAME, DAQ_CHANNEL_PORT)

        # ── per‑trial bookkeeping (reset on every rising edge) ──
        self._rising_edge_time  = None   # datetime when rising edge arrived
        self._falling_edge_time = None   # datetime when falling edge arrived
        self._sequence_aborted  = False  # True if sequence was cut short

    # ── Stytra lifecycle hooks ────────────────────────────

    def start(self):
        """
        Called by Stytra when the user presses Play.

        Flow
        ----
        1. Reset per‑trial bookkeeping.
        2. Start DAQ monitor & block until rising edge.
        3. Run the stimulus sequence (super().start()) inside a
           try / finally so that logs are ALWAYS flushed to disk,
           regardless of how the sequence ends.
        """
        # ── 1. reset per‑trial state ──────────────────────────
        self._rising_edge_time  = None
        self._falling_edge_time = None
        self._sequence_aborted  = False
        self._daq.clear_falling()

        # ── 2. start DAQ monitor & wait ───────────────────────
        self._daq.start()
        self._wait_for_rising_edge()           # blocks until rising edge

        # ── 3. run sequence; guarantee save on every exit path ─
        try:
            super().start()                    # runs get_stim_sequence loop
        except Exception as e:
            print(f"[Protocol] Exception during stimulus sequence: {e}")
            traceback.print_exc()
        finally:
            # ── stamp falling‑edge time if we were aborted ──────
            if self._sequence_aborted and self._falling_edge_time is None:
                self._falling_edge_time = datetime.now()

            # ── build extra metadata to stamp into the saved files
            extra = dict(
                rising_edge_timestamp  = (self._rising_edge_time.isoformat()
                                          if self._rising_edge_time else None),
                falling_edge_timestamp = (self._falling_edge_time.isoformat()
                                          if self._falling_edge_time else None),
                sequence_aborted       = self._sequence_aborted,
                daq_device             = DAQ_DEVICE_NAME,
                daq_channel            = DAQ_CHANNEL_PORT,
            )

            # ── flush behaviour_log + stim_log + metadata ───────
            print("\n[Protocol] Flushing logs to disk …")
            _SafeSaver.flush(self, extra_metadata=extra)

            if self._sequence_aborted:
                print("  >>> Sequence was ABORTED by falling edge. "
                      "All logs saved. <<<\n")
            else:
                print("  >>> Sequence completed normally. "
                      "All logs saved. <<<\n")

    def _wait_for_rising_edge(self):
        print("\n" + "=" * 60)
        print("  >>> WAITING FOR RISING EDGE ON DAQ … <<<")
        print("=" * 60 + "\n")

        # Block this thread until the rising edge event is set by DAQ monitor
        self._daq.rising_edge_event.wait()          # blocks indefinitely
        self._daq.clear_rising()                    # consume the event

        self._rising_edge_time = datetime.now()     # ── stamp timestamp
        print(f"\n  >>> RISING EDGE RECEIVED at {self._rising_edge_time.isoformat()} "
              f"– starting stimulus sequence <<<\n")

    # ── stimulus sequence ─────────────────────────────────

    def get_stim_sequence(self):
        """
        Returns the stimulus list.  Each stimulus is wrapped so that its
        update() loop also checks for a falling edge; if detected the
        stimulus is told to finish immediately.
        """
        stimuli = []

        for i in range(self.number_of_repeats):
            # ── 1. Pre‑stimulus  (30 s, 0 % coherence) ──────────
            stimuli.append(
                self._wrap(
                    TrackedDotStim(
                        dot_density=0.3,
                        dot_radius=0.6,
                        df_param=pd.DataFrame(dict(
                            t=[30],
                            coherence=[0],
                            frozen=[0],
                            theta_relative=[random.choice(self.left_right)]
                        )),
                        tracked_coherence=0.0
                    )
                )
            )

            # ── 2. Coherent motion with vigor response  (40 s) ───
            stimuli.append(
                self._wrap(
                    VigorResponsiveDotStim(
                        dot_density=0.3,
                        dot_radius=0.6,
                        df_param=pd.DataFrame(dict(
                            t=[40],
                            coherence=[1],
                            frozen=[0],
                            theta_relative=[random.choice(self.left_right)]
                        )),
                        vigor_threshold=float(self.vigor_threshold),
                        original_coherence=1.0
                    )
                )
            )

            # ── 3. Post‑stimulus  (10 s, 0 % coherence) ──────────
            stimuli.append(
                self._wrap(
                    TrackedDotStim(
                        dot_density=0.3,
                        dot_radius=0.6,
                        df_param=pd.DataFrame(dict(
                            t=[10],
                            coherence=[0],
                            frozen=[0],
                            theta_relative=[random.choice(self.left_right)]
                        )),
                        tracked_coherence=0.0
                    )
                )
            )

        return stimuli

    # ── helper: monkey‑patch a stimulus so its update() checks for
    #     falling edge and forces the stimulus to end early
    # ─────────────────────────────────────────────────────────────

    def _wrap(self, stim):
        """
        Replaces stim.update with a version that, on each frame, also
        checks the DAQ falling‑edge event.  When the falling edge fires:
          • the protocol‑level abort flag & timestamp are set (once)
          • the stimulus's duration is collapsed to 0 so Stytra advances
          • every subsequent stimulus does the same → whole sequence exits
        The abort flag is what start()'s finally block reads to decide
        what to stamp into metadata before saving.
        """
        original_update = stim.update
        daq             = self._daq       # closure: the DAQ monitor
        protocol        = self           # closure: the protocol instance

        def guarded_update():
            if daq.falling_edge_event.is_set():
                # ── stamp abort state exactly once ─────────────────
                if not protocol._sequence_aborted:
                    protocol._sequence_aborted  = True
                    protocol._falling_edge_time = datetime.now()
                    print(f"[STIM] *** FALLING EDGE at "
                          f"{protocol._falling_edge_time.isoformat()} – "
                          f"aborting sequence ***")

                # Collapse remaining time so Stytra considers this stim done
                stim.df_param.loc[:, 't'] = 0
                return                          # skip normal update

            original_update()                   # normal frame processing

        stim.update = guarded_update
        return stim

    # ── cleanup ───────────────────────────────────────────

    def end(self):
        """
        Called by Stytra when the protocol is stopped via the GUI
        (e.g. the Stop button) or when the application shuts down.

        start()'s finally block has already flushed logs by this point
        in normal operation; we guard against double‑save here.  The
        DAQ stop is idempotent so it is always safe to call.
        """
        self._daq.stop()
        print("\n  >>> Protocol.end() called. DAQ monitor stopped. <<<\n")
        super().end()


# ──────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # ── quick sanity checks ───────────────────────────────
    import stytra as _stytra
    print(f"[stytra]  {_stytra.__file__}")

    from stytra.hardware.video.cameras import camera_class_dict
    print(f"[cameras] {sorted(camera_class_dict.keys())}")

    from pypylon import pylon
    print(f"[pylon]   {pylon.TlFactory.GetInstance().EnumerateDevices()}")

    # ── verify NI DAQ driver & device ─────────────────────
    try:
        system = nidaqmx.system.System.local()
        print(f"[nidaqmx] Detected devices: {[d.name for d in system.devices]}")
    except Exception as e:
        print(f"[nidaqmx] WARNING – could not enumerate devices: {e}")

    # ── launch Stytra ─────────────────────────────────────
    st = Stytra(
        protocol=VisualStim_dots(),
        camera=dict(type="basler", cam_idx=0),
        stim_plot=True
    )