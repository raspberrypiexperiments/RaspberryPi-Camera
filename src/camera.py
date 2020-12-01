#!/usr/bin/python
"""
    Copyright (C) 2017 Marcin Sielski <marcin.sielski@gmail.com>

    camera.py: Camera service

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
import gi
gi.require_version("Gst", '1.0')
gi.require_version("GstRtspServer", "1.0")
from gi.repository import Gst, GstRtspServer, GLib
from gpiozero import Button
from signal import pause
from subprocess import call
from os import system
from netifaces import ifaddresses
import threading
import time

class RtspServer:
	"""
		RTSP Server
	"""
	def __init__(self):
		"""
			Initializes RTSP Server
		"""
		#GObject.threads_init()
		Gst.init(None)
		self.__main_loop__ = GLib.MainLoop()
		self.__thread__ = threading.Thread(target=self.run, args=())
		self.__thread__.daemon = True
		self.__thread__.start()

	def client_connected(self, arg1, arg2):
		"""
			Callback method executed up client connection
		"""
		print("RTSP Client connected.")

	def run(self):
		"""
			Implements RTSP Server
		"""
		server = GstRtspServer.RTSPServer.new()
		address = ifaddresses("wlan1")[2][0]["addr"]
		port = "8000"
		launch_description = ("( udpsrc port=3141 ! application/x-rtp, media=video, encoding-name=H264, "
		                      "clock-rate=90000 ! rtph264depay ! rtph264pay name=pay0 )")
		server.set_address(address)
		server.set_service(port)
		server.connect("client-connected", self.client_connected) 
		factory = GstRtspServer.RTSPMediaFactory.new()
		factory.set_launch(launch_description)
		factory.set_shared(True)
		factory.set_transport_mode(GstRtspServer.RTSPTransportMode.PLAY)
		mount_points = server.get_mount_points()
		mount_points.add_factory("/pi", factory)
		server.attach(None)
		print("RTSP Server started.")
		try:
			self.__main_loop__.run()
		except KeyboardInterrupt:
			pass
		print("RTSP Server stopped.")

	def stop(self):
		"""
			Shutdowns RTSP Server
		"""
		self.__main_loop__.quit()
		self.__thread__.join()

class CameraHandler:
	
	"""
		Camera Handler
	"""
	def __init__(self):
		"""
			Initializes Camera Handler
		"""
		self.__rtsp_server__ = None
		self.__push_switch__ = Button(27)
		self.__switch_on__ = Button(25)
		self.__switch_off__ = Button(24)
		self.__push_switch__.when_pressed = self.push_switch_pressed
		self.__push_switch__.when_released = self.push_switch_released
		self.__switch_on__.when_pressed = self.switch_on_pressed
		self.__switch_on__.when_released = self.switch_on_released
		self.__switch_off__.when_pressed = self.switch_off_pressed
		self.__switch_off__.when_released = self.switch_off_released
		if self.__switch_on__.is_pressed:
			print("Switch on is pressed.")
			self.switch_on_pressed()
		else:
			print("Switch on is released.")
		if self.__switch_off__.is_pressed:
			print("Switch off is pressed.")
		else:
			print("Switch off is released.")
			
	def push_switch_pressed(self):
		"""
			Callback method executed when push switch is pressed
		"""
		print("Push switch pressed.")

	def push_switch_released(self):
		"""
			Callback method executed when push switch is released
		"""
		print("Push switch released.")
		print("Power off...")
		call("sudo shutdown -h now", shell=True)

	def switch_on_pressed(self):
		"""
			Callback method executed when switch turn on is pressed
		"""
		print("Switch on pressed.")
		#system("gst-launch-1.0 -ve --gst-debug-no-color rpicamsrc preview=0 bitrate=2097152 keyframe-interval=30 ! "
		#	"video/x-h264,width=800,height=600,profile=baseline,framerate=30/1 ! h264parse ! tee name=t1 ! queue ! "
		#	"splitmuxsink async-handling=true location=video%02d.mp4 max-size-time=3600000000000 "
		#	"max-files=49 max-size-bytes=1073741824 t1. ! queue ! rtph264pay config-interval=1 ! tee name=t2 ! queue ! "
		#	"udpsink host=127.0.0.1 port=3141 sync=false t2.! queue ! udpsink host=127.0.0.1 port=31415 sync=false &")
		system("gst-launch-1.0 -ve --gst-debug-no-color rpicamsrc preview=0 bitrate=2097152 keyframe-interval=30 ! "
			"video/x-h264,width=800,height=600,profile=baseline,framerate=30/1 ! h264parse ! queue ! rtph264pay config-interval=1 ! tee name=t2 ! queue ! "
			"udpsink host=127.0.0.1 port=3141 sync=false t2. ! queue ! udpsink host=127.0.0.1 port=31415 sync=false &")
		print("Camera stream started.")
		if self.__rtsp_server__ is None:
			self.__rtsp_server__ = RtspServer()

	def switch_on_released(self):
		"""
			Callback method executed when switch turn on is released
		"""
		print("Switch on released.")

	def switch_off_pressed(self):
		"""
			Callback method executed when switch turn off is pressed
		"""
		print("Switch off pressed.")
		if self.__rtsp_server__ is not None:
			self.__rtsp_server__.stop()
			self.__rtsp_server__ = None
		call("PID=`ps aux | grep rpicamsrc | grep -v grep | awk '{ print $2 }'` && if [ \"x$PID\" != \"x\" ] ; then "
			"kill -2 $PID; fi", shell=True)
		print("Camera stream stopped.")

	def switch_off_released(self):
		"""
			Callback method executed when switch turn off is released
		"""
		print("Switch off released.")
	

if __name__ == "__main__":
	"""
		Camera Service entry method
	"""
	print("Camera Service started.")
	camera_handler = CameraHandler()
	try:
		pause()
	except KeyboardInterrupt:
		pass
		
	camera_handler.switch_off_pressed()
	print("Camera Service stopped.")
