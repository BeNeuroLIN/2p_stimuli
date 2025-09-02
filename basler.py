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
        """

        Parameters
        ----------
        param :

        val :


        Returns
        -------

        """
        # pass
        # # try:

        if self.cam is None:
            return "W: camera not open"
        nm=self.camera.GetNodeMap()

        if param == "exposure":
            self.camera.ExposureTime = val * 1000
            return ""
        # elif param == "framerate":
        #     self.camera.FrameRate = 100
        elif param == "gain":
            self.camera.Gain = val
        else:
            return "W: " + param + " not implemented"

    def read(self):
        """ """
        grabResult = self.camera.RetrieveResult(
            5000, pylon.TimeoutHandling_ThrowException
        )

        if grabResult.GrabSucceeded():
            # Access the image data.
            # print("SizeX: ", grabResult.Width)
            # print("SizeY: ", grabResult.Height)
            img = grabResult.Array
            # print("Gray value of first pixel: ", img[0, 0])
            grabResult.Release()
            return img

        else:
            return None

        # return res.Array

    def release(self):
        """ """
        pass
        # self.camera.stopGrabbing()


if __name__ == "__main__":
    camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice())
    i = camera.GetNodeMap()

    # camera.Open()
    # camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
    # res = camera.RetrieveResult(0, pylon.TimeoutHandling_Return)
    # print(res)
    # re.
    # print(res.Array)
    # camera.stopGrabbing()
    # camera.Close()

    # camera = pylon.InstantCamera(
    #     pylon.TlFactory.GetInstance().CreateFirstDevice())
    camera.StartGrabbing(pylon.GrabStrategy_OneByOne)
    camera.FrameRate = 10

    # while camera.IsGrabbing():
    grabResult = camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)

    if grabResult.GrabSucceeded():
        # Access the image data.
        print("SizeX: ", grabResult.Width)
        print("SizeY: ", grabResult.Height)
        img = grabResult.Array
        print("Gray value of first pixel: ", img[0, 0])

    grabResult.Release()
