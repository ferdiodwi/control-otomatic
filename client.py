# USAGE
# python client.py --server-ip SERVER_IP

# import the necessary packages
from imutils.video import VideoStream
import argparse
import imagezmq
import socket
import time
import cv2

# construct the argument parser and parse the arguments
ap = argparse.ArgumentParser()
ap.add_argument("-s", "--server-ip", required=True,
    help="ip address of the server to which the client will connect")
args = vars(ap.parse_args())

# initialize the ImageSender object with the socket address of the
# server
# Pastikan portnya sesuai dengan yang didengarkan oleh server (misal: 5555)
sender = imagezmq.ImageSender(connect_to="tcp://{}:5555".format(
    args["server_ip"]))

# get the host name, initialize the video stream, and allow the
# camera sensor to warmup
rpiName = socket.gethostname()
# Gunakan usePiCamera=True jika menggunakan PiCamera, atau src=0 untuk webcam USB
vs = VideoStream(usePiCamera=False, resolution=(640, 480)).start()
time.sleep(2.0)

print(f"[INFO] Client '{rpiName}' started, sending to tcp://{args['server_ip']}:5555")

try:
    while True:
        # read the frame from the camera
        frame = vs.read()

        # pastikan frame tidak None
        if frame is not None:
            # Kirim frame menggunakan send_image (lebih efisien karena tidak perlu encode ulang jika tidak perlu)
            sender.send_image(rpiName, frame)
        else:
            print("[ERROR] Could not read frame from video stream.")
            break

except (KeyboardInterrupt, SystemExit):
    print("\n[INFO] Client stopped.")
except Exception as e:
    print(f"[ERROR] An error occurred on the client: {e}")
finally:
    vs.stop()
    sender.close()