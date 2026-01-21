# test if basler camera is visible to opencv

import cv2
from pypylon import pylon

# see if Basler camera is listed
tl=pylon.TlFactory.GetInstance()
devices = tl.EnumerateDevices()
print("Devices:",devices)

# capture an image
cap=cv2.VideoCapture(0) # try different numbers: 0,1,2,..
ret, frame = cap.read()
print("Got frame:", ret, frame.shape if ret else None)
cv2.imshow("Test", frame)
cv2.waitKey(0)

cap.release()
cv2.destroyAllWindows()



