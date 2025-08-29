# test if basler camera is visible to opencv

import cv2

cap=cv2.VideoCapture(3) # try different numbers: 0,1,2,..
ret, frame = cap.read()
print("Got frame:", ret, frame.shape if ret else None)
cv2.imshow("Test", frame)
cv2.waitKey(0)

cap.release()
cv2.destroyAllWindows()



