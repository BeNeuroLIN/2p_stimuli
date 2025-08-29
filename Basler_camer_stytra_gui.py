from stytra import Stytra, Protocol

class LiveCameraOnly(Protocol):
    name = 'LiveCameraOnly'
    def get_stim_sequence(self):    #no stimuli, just testing
        return[]

    #use opencv for camera
    stytra_config =dict(
        tracking = dict(embedded=True, method =None),
        camera=dict(camera=dict(type='opencv',cam_idx=0)),
    )

if __name__ =='__main__':
    st=Stytra(
        protocol=LiveCameraOnly(),
        camera=dict(type='opencv',cam_idx=0),
        stim_plot=True,
    )