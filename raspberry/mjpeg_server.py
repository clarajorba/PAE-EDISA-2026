#!/usr/bin/env python3
"""
Minimal MJPEG camera server for drone GCS.
Streams camera frames over HTTP — no ROS needed.

Usage:
  pip install flask
  python3 mjpeg_server.py [device] [port] [width] [height] [quality]

Defaults: device=0, port=8080, 640x480, quality=80
"""

import sys
import cv2
from flask import Flask, Response

DEVICE  = int(sys.argv[1]) if len(sys.argv) > 1 else 0
PORT    = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
WIDTH   = int(sys.argv[3]) if len(sys.argv) > 3 else 640
HEIGHT  = int(sys.argv[4]) if len(sys.argv) > 4 else 480
QUALITY = int(sys.argv[5]) if len(sys.argv) > 5 else 80

app = Flask(__name__)

cap = cv2.VideoCapture(DEVICE)
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

encode_params = [cv2.IMWRITE_JPEG_QUALITY, QUALITY]

def gen_frames():
    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        # V4L2 on RPi Camera returns RGB-ordered data despite cv2 expecting BGR — swap
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        _, buf = cv2.imencode('.jpg', frame, encode_params)
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' +
            buf.tobytes() +
            b'\r\n'
        )

@app.route('/cam1')
def cam1():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/health')
def health():
    return 'OK'

if __name__ == '__main__':
    if not cap.isOpened():
        print(f'ERROR: cannot open /dev/video{DEVICE}')
        sys.exit(1)
    print(f'Camera /dev/video{DEVICE} → http://0.0.0.0:{PORT}/cam1')
    app.run(host='0.0.0.0', port=PORT, threaded=True)
