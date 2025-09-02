from stytra.hardware.video.cameras.interface import Camera

try:
    from pypylon import pylon
except ImportError as e:
    raise ImportError("pypylon not installed. Installed Basler pylon SDK and then 'pip install pypylon'.") from e

def _enum_set(nodemap, name, value):
    try:
        par=pylon.EnumerationParameter(nodemap, name)
        if par.IsWritable():
            choices = [e.GetSymbolic() for e in par.GetEntries() if e.IsWritable()]
            if value in choices:
                par.SetValue(value)
                return True
    except Exception:
        pass
    return False

def _float_set(nodemap,names, value):
    for nm in names:
        try:
            par=pylon.FloatParameter(nodemap,nm)
            if par.IsWritable():
                lo, hi=par.GetMin(), par.GetMax()
                par.SetValue(min(max(value,lo),hi))
                return True
        except Exception:
            continue
    return False


class BaslerCamera(Camera):
    """Class for simple control of a camera such as a webcam using opencv.
    Tested only on a simple USB Logitech 720p webcam. Exposure and framerate
    seem to work.
    Different cameras might have different problems because of the
    camera-agnostic opencv control modules. Moreover, it might not work on a
    macOS because of system-specific problems in the multiprocessing Queues().

    """
    '''
    def __init__(self, cam_idx=0, **kwargs):
        super().__init__(**kwargs)
        self.camera = pylon.InstantCamera(
            pylon.TlFactory.GetInstance().CreateFirstDevice()
        )
    '''

    def __init__(self, cam_idx=0, **kwargs):
        super().__init__(**kwargs)
        self.cam_idx=int(cam_idx)
        self.camera=None

    def open_camera(self):
        """ """
        # new
        tl=pylon.TlFactory.GetInstance()
        devs=tl.EnumerateDevices()
        if not devs:
            raise RuntimeError("No Basler camera found")
        if self.cam_idx >= len(devs):
            raise RuntimeError(f"cam_idx {self.cam_idx} out of range (found{len(devs)}.")

        self.camera=pylon.InstantCamera(tl.CreateDevice(devs.cam_idx))

        self.camera.Open()
        nm=self.camera.GetNodeMap()
        _enum_set(nm,"PixelFormat","Mono8")
        #self.camera.StartGrabbing(pylon.GrabStrategy_OneByOne)
        self.camera.StartGrabbing(pylon.GrabStrategy_OneByOne)
        return ["I:Basler camera opened"]

    def set(self, param, val):
        if self.cam is None:
            return "W: camera not open"

        nm = self.cam.GetNodeMap()

        try:
            if param == "exposure":
                # Stytra usually passes milliseconds; Basler wants microseconds
                us = float(val) * 1000.0
                _enum_set(nm, "ExposureAuto", "Off")
                ok = _float_set(nm, ["ExposureTime", "ExposureTimeAbs"], us)
                return "" if ok else "W: exposure control not supported on this model"

            elif param == "framerate":
                # Not all GigE models support this; try common nodes
                try:
                    pylon.BooleanParameter(nm, "AcquisitionFrameRateEnable").SetValue(True)
                except Exception:
                    pass
                ok = _float_set(nm, ["AcquisitionFrameRate", "AcquisitionFrameRateAbs"], float(val))
                return "" if ok else "W: framerate control not supported"

            elif param == "gain":
                _enum_set(nm, "GainAuto", "Off")
                ok = _float_set(nm, ["Gain", "GainRaw"], float(val))
                return "" if ok else "W: gain control not supported"

            elif param == "roi":
                # val = (x, y, w, h)
                try:
                    x, y, w, h = map(int, val)
                except Exception:
                    return "W: roi expects (x,y,w,h)"
                need_restart = self.cam.IsGrabbing()
                if need_restart:
                    self.cam.StopGrabbing()
                try:
                    for name, v in (("OffsetX", x), ("OffsetY", y), ("Width", w), ("Height", h)):
                        try:
                            par = pylon.IntegerParameter(nm, name)
                            if par.IsWritable():
                                inc = getattr(par, "GetInc", lambda: 1)()
                                lo, hi = par.GetMin(), par.GetMax()
                                vv = max(min(v - (v - lo) % max(1, inc), hi), lo)
                                par.SetValue(vv)
                        except Exception:
                            pass
                finally:
                    if need_restart:
                        self.cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
                return ""

            else:
                return f"W: {param} not implemented"

        except Exception as e:
            return f"W: set({param}) failed: {e}"

    def read(self):
        if self.cam is None or not self.cam.IsGrabbing():
            return None

        grab = self.cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
        try:
            if grab.GrabSucceeded():
                arr = grab.Array
                # ensure 2D grayscale for Stytra (drop channel if Bayer/RGB sneaks in)
                if arr.ndim == 3:
                    arr = arr[:, :, 0]
                return arr
            return None
        finally:
            grab.Release()

    def release(self):
        if self.cam:
            try:
                if self.cam.IsGrabbing():
                    self.cam.StopGrabbing()
            except Exception:
                pass
            try:
                if self.cam.IsOpen():
                    self.cam.Close()
            except Exception:
                pass
            self.cam = None