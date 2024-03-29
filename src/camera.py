#!/usr/bin/env python3

"""
MIT License

Copyright (c) 2021-2022 Marcin Sielski <marcin.sielski@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

# picamera module must be imported before gi module, 
# otherwise stack corruption occurs.
import picamera
import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstBase', '1.0')
gi.require_version('GstRtspServer', '1.0')
from gi.repository import Gst, GstBase, GstRtspServer, GLib
from signal import pause
from subprocess import call
from os import system
#from netifaces import ifaddresses
import threading
import time
import falcon
from wsgiserver import WSGIServer
import json
import logging
import inspect
from argparse import ArgumentParser, ArgumentTypeError
import signal
import os
import shutil
import psutil
from gpiozero import DiskUsage, CPUTemperature
import subprocess
import datetime
import arducam_mipicamera as arducam
import sys
#import tracemalloc
#tracemalloc.start()


def camera_revision():
	stdout_bk = os.dup(sys.stderr.fileno())
	pipefd = os.pipe2(0)
	os.dup2(pipefd[1], sys.stderr.fileno())
	arducam.mipi_camera().init_camera()
	os.close(pipefd[1])
	os.dup2(stdout_bk, sys.stderr.fileno())
	i = 0
	revision = ''
	while True:
		ch = os.read(pipefd[0],1)
		if i >= 13 and ch != b' ':
			revision = revision + ch.decode("utf-8")
				
		i = i + 1
		if ch == b' ' and i > 13 and i < 30:
			break
	return revision


def name(obj):

	"""
	Utility function that adds space before 'Serv' in the name of the object

	Args:
		obj (any): object

	Returns:
		str: returns human readable name of name of the specified object
	"""
	
	return type(obj).__name__.replace("Serv", " Serv")


class Server(object):

	"""
	Server Interface

	Args:
		object (object): base object
	"""


	def init(self):

		"""
		Initialize the Server
		"""

		pass


	def start(self):

		"""
		Starts execution of the Server
		"""

		pass


	def stop(self):

		"""
		Stops execution of the Server
		"""

		pass


	def restart(self):

		"""
		Restarts the Server
		"""

		self.stop()
		self.init()
		self.start()


class RTSPServer(Server):

	"""
	Real Time Streaming Protocol (RTSP) Server
	"""


	def __init__(
		self, camera_server, address='0.0.0.0', port='8000', path='/pi'):

		"""
		Initialize RTSP Server

		Args:
			address (str): ip address
			port (str): port
			path (str): path
		"""

		self.__address__ = address
		self.__port__ = port
		self.__path__ = path
		self.__camera_server__ = camera_server
		self.__main_loop__ = GLib.MainLoop()

		server = GstRtspServer.RTSPServer.new()
		#address = ifaddresses('wlan1')[2][0]['addr']
		launch_description = (
			'( udpsrc port=3141 ! application/x-rtp, '
			'media=video, encoding-name=H264, clock-rate=90000 ! rtph264depay '
			'! rtph264pay name=pay0 )')
		server.set_address(self.__address__)
		server.set_service(self.__port__)
		server.connect('client-connected', self.client_connected) 
		factory = GstRtspServer.RTSPMediaFactory.new()
		factory.set_launch(launch_description)
		factory.set_shared(True)
		factory.set_transport_mode(GstRtspServer.RTSPTransportMode.PLAY)
		mount_points = server.get_mount_points()
		mount_points.add_factory(self.__path__, factory)
		server.attach(None)


	def client_connected(self, server, client):

		"""
		Callback method executed upon client connection

		Args:
			server (RTSPServer): RTSP server
			client (RTSPClient): RTSP client
		"""

		logging.info(
			"RTSP Client connected from " + client.get_connection().get_ip())
		self.__camera_server__.send_keyframe()


	def start(self):

		"""
		Start RTSP Server
		"""

		logging.info(
			name(self) + " started at rtsp://" + self.__address__ + ":" + 
			self.__port__ + self.__path__)
		self.__main_loop__.run()


	def stop(self):

		"""
		Stop RTSP Server
		"""

		self.__main_loop__.quit()
		logging.info(name(self) + " stopped")


class CORSComponent(object):

	"""
	Cross-Origin Resource Sharing (CORS) Component as defined at
	https://falcon.readthedocs.io/en/stable/user/faq.html#how-do-i-implement-cors-with-falcon
	"""

	def process_response(self, req, resp, resource, req_succeeded):

		"""
		Process response from HTTPS Server and add CORS headers

		Args:
			req (Request): request
			resp (Response): response
			resource (HTTPSServer): HTTPS Server
			req_succeeded (bool): indicated if request succeeded
		"""

		resp.set_header('Access-Control-Allow-Origin', '*')

		if (
			req_succeeded and 
			req.method == 'OPTIONS' and 
			req.get_header('Access-Control-Request-Method')
		):
			# NOTE(kgriffs): This is a CORS preflight request. Patch the
			#   response accordingly.

			allow = resp.get_header('Allow')
			resp.delete_header('Allow')

			allow_headers = req.get_header(
				'Access-Control-Request-Headers',
				default='*'
			)

			resp.set_headers((
				('Access-Control-Allow-Methods', allow),
				('Access-Control-Allow-Headers', allow_headers),
				('Access-Control-Max-Age', '86400'),  # 24 hours
			))


class HTTPSServer(WSGIServer):

	"""
	HyperText Transfer Protocol Secure (HTTPS) Server
	"""

	def __init__(
		self, camera_server, address='0.0.0.0', port=8888, path='/',
		keyfile='/opt/camera/bin/key.pem', certfile='/opt/camera/bin/cert.pem'):

		"""
		Initialize HTTPS Server

		Args:
			camera_server (CameraServer): camera server
			address (str): address
			port (str): port
			path (str): path
			keyfile (str): path to keyfile
			certfile (str): path to certfile
		"""

		self.__camera_server__ = camera_server
		self.__address__ = address
		self.__port__ = port
		self.__path__ = path
		app = falcon.API(middleware=[CORSComponent()])
		#app.add_route('/pi', self)
		app.add_route(path, self)
		super().__init__(
			app, host=self.__address__, port=self.__port__, keyfile=keyfile, 
			certfile=certfile)


	def start(self):

		"""
		Start HTTPS Server
		"""

		logging.info(
			name(self) + " started at https://" + self.__address__ + ":" + 
			str(self.__port__) + self.__path__)
		super().start()


	def stop(self):

		"""
		Stop HTTPS Server
		"""

		super().stop()
		logging.info(name(self) + " stopped")


	def error_log(self, msg, level, traceback):

		"""
		Log error message

		Args:
			msg (str): error message
			level (int): log level
			traceback (bool): indicate whether to enable backtrace
		"""
  
		if msg != 'Error in HTTPServer.tick':
			logging.log(level, msg)
			if traceback:
				logging.log(level, logging.traceback.format_exc())


	def on_get(self, req, resp):

		"""
		Handle HTTP GET request

		Args:
			req (Request): request
			resp (Response): response
		"""

		logging.info(req.params)
		resp.status = falcon.HTTP_200

		# Quality

		if 'width' in req.params and 'height' in req.params:
			self.__camera_server__.set_resolution(int(req.params['width']),
			int(req.params['height']))
		if 'framerate' in req.params:
			self.__camera_server__.set_framerate(int(req.params['framerate']))
		if 'bitrate_mode' in req.params:
			self.__camera_server__.set_bitrate_mode(
				int(req.params['bitrate_mode']))
		if 'bitrate' in req.params:
			self.__camera_server__.set_bitrate(int(req.params['bitrate']))
		if 'sensor_mode' in req.params:
			self.__camera_server__.set_sensor_mode(
				int(req.params['sensor_mode']))

		# Effects

		if 'brightness' in req.params:
			self.__camera_server__.set_brightness(
				int(req.params['brightness']))
		if 'contrast' in req.params:
			self.__camera_server__.set_contrast(int(req.params['contrast']))
		if 'saturation' in req.params:
			self.__camera_server__.set_saturation(int(req.params['saturation']))
		if 'sharpness' in req.params:
			self.__camera_server__.set_sharpness(int(req.params['sharpness']))
		if 'drc' in req.params:
			self.__camera_server__.set_drc(int(req.params['drc']))
		if 'image_effect' in req.params:
			self.__camera_server__.set_image_effect(
				int(req.params['image_effect']))
		if 'awb_mode' in req.params:
			self.__camera_server__.set_awb_mode(int(req.params['awb_mode']))
		if 'awb_gain_blue' in req.params:
			self.__camera_server__.set_awb_gain_blue(
				int(req.params['awb_gain_blue']))
		if 'awb_gain_red' in req.params:
			self.__camera_server__.set_awb_gain_red(
				int(req.params['awb_gain_red']))

		# Controls

		if 'exposure_mode' in req.params:
			self.__camera_server__.set_exposure_mode(
				int(req.params['exposure_mode']))
		if 'exposure_compensation' in req.params:
			self.__camera_server__.set_exposure_compensation(
				int(req.params['exposure_compensation']))
		if 'metering_mode' in req.params:
			self.__camera_server__.set_metering_mode(
				int(req.params['metering_mode']))
		if 'iso' in req.params:
			self.__camera_server__.set_iso(int(req.params['iso']))
		if 'shutter_speed' in req.params:
			self.__camera_server__.set_shutter_speed(
				int(req.params['shutter_speed']))
		if 'video_stabilisation' in req.params:
			self.__camera_server__.set_video_stabilisation(
				req.params['video_stabilisation'] == '1')
		if 'gain' in req.params:
			self.__camera_server__.set_gain(int(req.params['gain']))
		if 'awb' in req.params:
			self.__camera_server__.set_awb(int(req.params['awb']))

		# Orientation

		if 'rotation' in req.params:
			self.__camera_server__.set_rotation(int(req.params['rotation']))
		if 'hflip' in req.params:
			self.__camera_server__.set_hflip(req.params['hflip'] == '1')
		if 'vflip' in req.params:
			self.__camera_server__.set_vflip(req.params['vflip'] == '1')
		if 'video_direction' in req.params:
			self.__camera_server__.set_video_direction(
				int(req.params['video_direction']))

		# Controls

		if 'logging_level' in req.params:
			self.__camera_server__.set_logging_level(
				int(req.params['logging_level']))
		if 'stats' in req.params:
			self.__camera_server__.set_stats(int(req.params['stats'],16))
		if 'rtsp' in req.params:
			self.__camera_server__.set_rtsp(req.params['rtsp'] == '1')
		if 'record' in req.params:
			self.__camera_server__.set_record(req.params['record'] == '1')
		if 'format' in req.params:
			self.__camera_server__.set_format(req.params['format'] == '1')
		if 'max_files' in req.params:
			self.__camera_server__.set_max_files(int(req.params['max_files']))
		if 'max_size_bytes' in req.params:
			self.__camera_server__.set_max_size_bytes(
				int(req.params['max_size_bytes']))
		if 'max_size_time' in req.params:
			self.__camera_server__.set_max_size_time(
				int(req.params['max_size_time']))
		if 'persistent' in req.params:
			self.__camera_server__.set_persistent(int(req.params['persistent']))
		if 'continuation' in req.params:
			self.__camera_server__.set_continuation(
				req.params['continuation'] == '1')
		if 'media' in req.params:
			resp.text = (self.__camera_server__.get_media())
			return
		if 'restart' in req.params:
			self.__camera_server__.restart()
		if 'remove' in req.params:
			self.__camera_server__.remove(req.params['remove'])
			resp.text = (self.__camera_server__.get_media())
			return
		if 'time' in req.params:
			self.__camera_server__.set_time(int(req.params['time']))

		resp.text = (self.__camera_server__.get_parameters())


class CameraServer(Server):
	
	"""
	Camera Server
	"""

	def __init__(self, args):

		"""
		Initialize Camera Server
		"""

		self.__camera_timeout__ = args.camera_timeout
		self.__throughput__ = args.throughput
		self.__default_logging_level__ = getattr(logging, args.debug.upper())
		self.__error_lock__ = threading.Lock()
		self.__main_lock__ = threading.Lock()
		#self.__stats_lock__ = threading.Lock()
		self.__restart_lock__ = threading.Lock()
		try:
			with picamera.PiCamera() as camera:
				self.__model__ = camera.revision
		except:
			self.__model__ = camera_revision()
		self.__stats_id__ = 0
		self.__extra_controls__ = 'encode,video_bitrate_mode={},h264_profile=0,\
			h264_level=11,video_bitrate={},h264_i_frame_period={}'
		parameters = None

		try:
			with open('camera.json', 'r') as config:
				parameters = json.load(config)
		except:
			logging.warning("'camera.json' not found")

		if parameters is not None and 'persistent' in parameters and \
			parameters['persistent'] == 1:

			logging.info("Loading parameters from 'camera.json'")
			
			# Quality

			if 'width' in parameters:
				self.__width__ = parameters['width']
			else:
				if self.__model__ == 'imx219' or self.__model__ == 'imx477':
					self.__width__ = 800
				if self.__model__ == 'ov9281':
					self.__width__ = 1280
			if 'height' in parameters:
				self.__height__ = parameters['height']
			else:
				if self.__model__ == 'imx219' or self.__model__ == 'imx477':
					self.__height__ = 608
				if self.__model__ == 'ov9281':
					self.__width__ = 800
			if 'framerate' in parameters:
				self.__framerate__ = parameters['framerate']
			else:
				self.__framerate__ = 30
			if 'bitrate_mode' in parameters:
				self.__bitrate_mode__ = parameters['bitrate_mode']
			else:
				self.__bitrate_mode__ = 0
			if 'bitrate' in parameters:
				self.__bitrate__ = parameters['bitrate']
			else:
				self.__bitrate__ = 3000000
			if 'sensor_mode' in parameters:
				self.__sensor_mode__ = parameters['sensor_mode']
			else:
				self.__sensor_mode__ = 0

			# Effects	

			if 'brightness' in parameters:
				self.__brightness__ = parameters['brightness']
			else:
				self.__brightness__ = 50
			if 'contrast' in parameters:
				self.__contrast__ = parameters['contrast']
			else:
				self.__contrast__ = 0
			if 'saturation' in parameters:
				self.__saturation__ = parameters['saturation']
			else:
				self.__saturation__ = 0
			if 'sharpness' in parameters:
				self.__sharpness__ = parameters['sharpness']
			else:
				self.sharpness = 0
			if 'drc' in parameters:
				self.__drc__ = parameters['drc']
			else:
				self.__drc = 0
			if 'image_effect' in parameters:
				self.__image_effect__ = parameters['image_effect']
			else:
				self.__image_effect__ = 0
			if 'awb_mode' in parameters:
				self.__awb_mode__ = parameters['awb_mode']
			else:
				self.__awb_mode__ = 1
			if 'awb_gain_blue' in parameters:
				self.__awb_gain_blue__ = parameters['awb_gain_blue']
			else:
				self.__awb_gain_blue__ = 0
			if 'awb_gain_red' in parameters:
				self.__awb_gain_red__ = parameters['awb_gain_red']
			else:
				self.__awb_gain_red__ = 0

			# Settings

			if 'exposure_mode' in parameters:
				self.__exposure_mode__ = parameters['exposure_mode']
			else:
				self.__exposure_mode__ = 1
			if 'metering_mode' in parameters:
				self.__metering_mode__ = parameters['metering_mode']
			else:
				self.__metering_mode__ = 0
			if 'exposure_compensation' in parameters:
				self.__exposure_compensation__ = \
					parameters['exposure_compensation']
			else:
				self.__exposure_compensation__ = 0
			if 'iso' in parameters:
				self.__iso__ = parameters['iso']
			else:
				self.__iso__ = 0
			if 'shutter_speed' in parameters:
				self.__shutter_speed__ = parameters['shutter_speed']
			else:
				self.__shutter_speed__ = 0
			if 'video_stabilisation' in parameters:
				self.__video_stabilisation__ = \
					(parameters['video_stabilisation'] == 1)
			else:
				self.__video_stabilisation__ = False
			if 'gain' in parameters:
				self.__gain__ = parameters['gain']
			else:
				self.__gain__ = 1
			if 'awb' in parameters:
				self.__awb__ = parameters['awb']
			else:
				self.__awb__ = 4

			# Orientation

			if 'rotation' in parameters:
				self.__rotation__ = parameters['rotation']
			else:
				self.__rotation__ = 0
			if 'hflip' in parameters:
				self.__hflip__ = (parameters['hflip'] == 1)
			else:
				self.__hflip__ = False
			if 'vflip' in parameters:
				self.__vflip__ = (parameters['vflip'] == 1)
			else:
				self.__vflip__ = False
			if 'video_direction' in parameters:
				self.__video_direction__ = parameters['video_direction']
			else:
				self.__video_direction__ = 0
	
			# Controls

			if 'logging_level' in parameters:
				self.__logging_level__ = parameters['logging_level']
			else:
				self.__logging_level__ = 0
			if 'stats' in parameters:
				self.__stats__ = int(parameters['stats'], 16)
			else:
				self.__stats__ = 0x00000000
			if 'rtsp' in parameters:
				self.__rtsp__ = (parameters['rtsp'] == 1)
			else:
				self.__rtsp__ = False
			if 'record' in parameters:
				self.__record__ = (parameters['record'] == 1)
			else:
				self.__record__ = False
			if 'format' in parameters:
				self.__format__ = (parameters['format'] == 1)
			else:
				self.__format__ = False
			if 'max_files' in parameters:
				self.__max_files__ = parameters['max_files']
			else:
				self.__max_files__ = 0
			if 'max_size_bytes' in parameters:
				self.__max_size_bytes__ = parameters['max_size_bytes']
			else:
				self.__max_size_bytes__ = 0
			if 'max_size_time' in parameters:
				self.__max_size_time__ = parameters['max_size_time']
			else:
				self.__max_size_time__ = 0
			if 'continuation' in parameters:
				self.__continuation__ = (parameters['continuation'] == 1)
				if self.__continuation__:
					self.__record__ = True
			else:
				self.__continuation__ = False
			if self.__continuation__:
				self.__fragment_id__ = parameters['fragment_id']
			else:
				self.__fragment_id__ = 0
			self.__persistent__ = (parameters['persistent'] == 1)
		
		else:
		
			# Quality

			if self.__model__ == 'imx219' or self.__model__ == 'imx477':
				self.__width__ = 800
				self.__height__ = 608
			if self.__model__ == 'ov9281':
				self.__width__ = 1280
				self.__height__ = 800				
			self.__framerate__ = 30
			self.__bitrate_mode__ = 0
			self.__bitrate__ = 3000000
			self.__sensor_mode__ = 0

			# Effects

			self.__brightness__ = 50
			self.__contrast__ = 0
			self.__saturation__ = 0
			self.__sharpness__ = 0
			self.__drc__ = 0
			self.__image_effect__ = 0
			self.__awb_mode__ = 1
			self.__awb_gain_blue__ = 0
			self.__awb_gain_red__ = 0

			# Settings

			self.__exposure_mode__ = 1
			self.__metering_mode__ = 0
			self.__exposure_compensation__ = 0
			self.__iso__ = 0
			self.__shutter_speed__ = 0
			# TODO(marcin.sielski): Change it to True
			self.__video_stabilisation__ = False
			self.__gain__ = 1
			self.__awb__ = 4

			# Orientation

			self.__rotation__ = 0
			self.__hflip__ = False
			self.__vflip__ = False
			self.__video_direction__ = 0

			# Controls

			self.__logging_level__ = 0
			self.__stats__ = 0x00000000
			self.__rtsp__ = False
			self.__record__ = False
			self.__format__ = False
			self.__max_files__ = 0
			self.__max_size_bytes__ = 0
			self.__max_size_time__ = 0
			self.__fragment_id__ = 0
			self.__continuation__ = False
			self.__persistent__ = False


		self.init()


	def set_time(self, time):
		
		"""
		Sets system time to specified time
		
		Args:
			time (int): time to set
		"""
		
		os.system('sudo timedatectl set-time @' + str(time))
		os.system('sudo fake-hwclock')
		os.sync()


	def send_keyframe(self):

		"""
		Forces to send key frame
		"""

		srcpad = self.__encoder__.get_static_pad( "src")
		structure = Gst.Structure.new_empty("GstForceKeyUnit")
		structure.set_value('all-headers', True)
		srcpad.send_event(
			Gst.Event.new_custom(Gst.EventType.CUSTOM_UPSTREAM,
			structure))



	def get_parameters(self):

		"""
		Return Camera Server parameters set

		Returns:
			json: Camera Server parameters set
		"""

		self.send_keyframe()
		return json.dumps(
			{
				'model': self.__model__, 

				# Quality

				'width': self.__width__, 
				'height': self.__height__, 
				'framerate': self.__framerate__, 
				'bitrate_mode': self.__bitrate_mode__,
				'bitrate': self.__bitrate__,
				'sensor_mode': self.__sensor_mode__,

				# Effects

				'brightness': self.__brightness__,
				'contrast': self.__contrast__,
				'saturation': self.__saturation__,
				'sharpness': self.__sharpness__,
				'drc': self.__drc__,
				'image_effect': self.__image_effect__, 
				'awb_mode': self.__awb_mode__,
				'awb_gain_blue': self.__awb_gain_blue__,
				'awb_gain_red': self.__awb_gain_red__, 

				# Settings

				'exposure_mode': self.__exposure_mode__,
				'metering_mode': self.__metering_mode__,
				'exposure_compensation': self.__exposure_compensation__,
				'iso': self.__iso__,
				'shutter_speed': self.__shutter_speed__,
				'video_stabilisation': int(self.__video_stabilisation__),
				'gain': self.__gain__,
				'awb': self.__awb__,

				# Orientation

				'rotation': self.__rotation__, 
				'hflip': int(self.__hflip__),
				'vflip': int(self.__vflip__),
				'video_direction': self.__video_direction__,

				# Controls

				'logging_level': int(self.__logging_level__),
				'stats': '{0:#0{1}x}'.format(self.__stats__,10),
				'rtsp': int(self.__rtsp__),
				'record': int(self.__record__),
				'format': int(self.__format__),
				'max_files': self.__max_files__,
				'max_size_bytes': self.__max_size_bytes__,
				'max_size_time': self.__max_size_time__,
				'persistent': int(self.__persistent__),
				'fragment_id': self.__fragment_id__,
				'continuation': int(self.__continuation__)
			},

			sort_keys=True)


	def __get_key__(self, e):
		
		"""
		Obtain key
		"""

		return e[0]


	def get_media(self):

		"""
		Obtain names of media files from the media folder

		Returns:
			json: list of media files from the media folder
		"""

		media = []
		_, _, free = shutil.disk_usage('/')
		media.append([str(free // (2**30))])
		_, _, filenames = next(os.walk('.'))	
		for filename in filenames:
			if filename.endswith('.mkv') or filename.endswith('.mp4'):
				media.append(
					[filename,  datetime.datetime.fromtimestamp(
						os.path.getmtime(
							filename)).strftime("%Y-%m-%d, %H:%M")])
		media.sort(key=self.__get_key__)
		return json.dumps(media, sort_keys=True)


	def init(self):

		"""
		Initialize streaming pipeline
		"""

		self.__pipeline__ = Gst.Pipeline('camera-server-pipeline')

		self.__source__ = self.__get_source__()
		self.__source_caps__ = Gst.Caps.new_empty_simple('video/x-raw')
		self.__source_caps__.set_value('width', self.__width__)
		self.__source_caps__.set_value('height', self.__height__)
		#if self.__shutter_speed__ > 0 and 1000000 / self.__shutter_speed__ < self.__framerate__:
		#	if 1000000 / self.__shutter_speed__ < 1:
		#		numerator = 1
		#		denominator = int(1000000 % self.__shutter_speed__)
		#	else:
		#		numerator = int(1000000 / self.__shutter_speed__)
		#		denominator = 1
		#else:
		#numerator = self.__framerate__
		#denominator = 1
		#self.__source_caps__.set_value(
		#	'framerate', Gst.Fraction(numerator, denominator))
		if self.__model__ == 'imx219' or self.__model__ == 'imx477':
			self.__source_caps__.set_value('format', 'I420')                        
		if self.__model__ == 'ov9281':
			self.__source_caps__.set_value('format', 'GRAY8')		
		self.__source_caps__.set_value(
			'framerate', Gst.Fraction(self.__framerate__, 1))

		self.__source_capsfilter__ = Gst.ElementFactory.make(
			'capsfilter', 'source-capsfilter')
		self.__source_capsfilter__.set_property('caps', self.__source_caps__)

		if self.__model__ == 'ov9281':
			self.__overlay__ = Gst.ElementFactory.make(
				'textoverlay', 'text-overlay')
			self.__overlay__.set_property('shaded-background', True)
			self.__overlay__.set_property('valignment','top')
			self.__overlay__.set_property('font-desc', 'Arial, 12')

		self.__raw_tee__ = Gst.ElementFactory.make('tee', 'raw-tee')

		if self.__model__ == 'ov9281':
			self.__converter__ = Gst.ElementFactory.make(
				'videoconvert', 'converter')
			self.__converter_caps__ = Gst.Caps.new_empty_simple('video/x-raw')
			self.__converter_caps__.set_value('width', self.__width__)
			self.__converter_caps__.set_value('height', self.__height__)
			self.__converter_caps__.set_value(
				'framerate', Gst.Fraction(self.__framerate__, 1))
			self.__converter_caps__.set_value('format', 'RGB')
			self.__converter_capsfilter__ = Gst.ElementFactory.make(
			'capsfilter', 'converter-capsfilter')
			self.__converter_capsfilter__.set_property(
				'caps', self.__converter_caps__)
				
		#self.__source_queue__ = Gst.ElementFactory.make(
		#	'queue', 'source-gueue')
		#self.__video_rate__ = Gst.ElementFactory.make(
		#	'videorate', 'video-rate')
		#self.__video_rate__.set_property('average-period', 9223372036854775807)
		#self.__video_rate__.set_property('rate', 0.9)
		#if self.__shutter_speed__ < 100000:
		#	self.__video_rate__.set_property('max-duplication-time', 10000000)
		#self.__video_rate_caps__ = Gst.Caps.new_empty_simple('video/x-raw')
		#self.__video_rate_caps__.set_value(
		#	'framerate', Gst.Fraction(self.__framerate__, 1))
		#self.__video_rate_capsfilter__ = Gst.ElementFactory.make(
		#	'capsfilter', 'video-rate-capsfilter')
		#self.__video_rate_capsfilter__.set_property(
		#	'caps', self.__video_rate_caps__)
		#self.__video_rate_queue__ = Gst.ElementFactory.make(
		#	'queue', 'video-rate-gueue')
		
		self.__encoder__ = Gst.ElementFactory.make('v4l2h264enc', 'encoder')
		self.__encoder__.set_property(
			'extra-controls', Gst.Structure.new_from_string(
				self.__extra_controls__.format(self.__bitrate_mode__,
				self.__bitrate__, self.__framerate__)))

		self.__encoder_caps__ = Gst.Caps.new_empty_simple('video/x-h264')
		self.__encoder_caps__.set_value('profile', 'baseline')
		self.__encoder_caps__.set_value('level', '4')

		self.__encoder_capsfilter__ = Gst.ElementFactory.make(
			'capsfilter', 'encoder-capsfilter')
		self.__encoder_capsfilter__.set_property('caps', self.__encoder_caps__)

		self.__parser__ = Gst.ElementFactory.make('h264parse', 'parser')
		GstBase.BaseParse.set_infer_ts(self.__parser__, True)	
		GstBase.BaseParse.set_pts_interpolation(self.__parser__, True)
		self.__parser__.set_property('config-interval', -1)

		self.__h264_tee__ = Gst.ElementFactory.make('tee', 'h264-tee')

		self.__payloader__ = Gst.ElementFactory.make('rtph264pay', 'payloader')
		self.__payloader__.set_property('config-interval', -1)

		self.__rtsp_tee__ = Gst.ElementFactory.make('tee', 'rtsp-tee')

		self.__sink_queue__ = Gst.ElementFactory.make('queue', 'sink-queue')
		self.__sink_queue__.set_property(
			'max-size-buffers', 0)
		self.__sink_queue__.set_property(
			'max-size-bytes', 0)
		self.__sink_queue__.set_property('max-size-time', 0)

		self.__sink__ = Gst.ElementFactory.make('udpsink', 'sink')
		self.__sink__.set_property('host', '127.0.0.1')
		self.__sink__.set_property('port', 31415)
		self.__sink__.set_property('sync', False)

		self.__pipeline__.add(self.__source__)
		self.__pipeline__.add(self.__source_capsfilter__)
		#self.__pipeline__.add(self.__source_queue__)
		#self.__pipeline__.add(self.__video_rate__)
		#self.__pipeline__.add(self.__video_rate_capsfilter__)
		#self.__pipeline__.add(self.__video_rate_queue__)
		
		
		if self.__model__ == 'ov9281':
			self.__pipeline__.add(self.__overlay__)
		self.__pipeline__.add(self.__raw_tee__)
		if self.__model__ == 'ov9281':
			self.__pipeline__.add(self.__converter__)
			self.__pipeline__.add(self.__converter_capsfilter__)
		self.__pipeline__.add(self.__encoder__)
		self.__pipeline__.add(self.__encoder_capsfilter__)
		self.__pipeline__.add(self.__parser__)
		self.__pipeline__.add(self.__h264_tee__)
		self.__pipeline__.add(self.__payloader__)
		self.__pipeline__.add(self.__rtsp_tee__)
		self.__pipeline__.add(self.__sink_queue__)
		self.__pipeline__.add(self.__sink__)

		self.__source__.link(self.__source_capsfilter__)
		#self.__source_capsfilter__.link(self.__source_queue__)
		#self.__source_capsfilter__.link(self.__video_rate__)
		#self.__video_rate__.link(self.__video_rate_capsfilter__)
		#self.__video_rate_capsfilter__.link(self.__video_rate_queue__)
		
		if self.__model__ == 'imx219' or self.__model__ == 'imx477':
			#self.__video_rate_capsfilter__.link(self.__raw_tee__)
			self.__source_capsfilter__.link(self.__raw_tee__)
			self.__raw_tee__.link(self.__encoder__) 
		if self.__model__ == 'ov9281':
			self.__source_capsfilter__.link(self.__overlay__)
			self.__overlay__.link(self.__raw_tee__)
			self.__raw_tee__.link(self.__converter__)  
			self.__converter__.link(self.__converter_capsfilter__)  
			self.__converter_capsfilter__.link(self.__encoder__)
		self.__encoder__.link(self.__encoder_capsfilter__)
		self.__encoder_capsfilter__.link(self.__parser__)
		self.__parser__.link(self.__h264_tee__)
		self.__h264_tee__.link(self.__payloader__)
		self.__payloader__.link(self.__rtsp_tee__)
		self.__rtsp_tee__.link(self.__sink_queue__)
		self.__sink_queue__.link(self.__sink__)
		
		self.bus = self.__pipeline__.get_bus()
		self.bus.set_sync_handler(self.__on_message__)

		self.__file_queue__ = None
		self.__file_rate__ = None
		self.__file_converter__ = None
		self.__file_encoder__ = None
		self.__file_sink__ = None
		self.__raw_framerate__ = 0


	def start(self):

		"""
		Start Camera Server
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		logging.info(name(self) + " started")
		self.set_logging_level(self.__logging_level__)
		self.__pipeline__.set_state(Gst.State.PLAYING)
		self.set_stats(self.__stats__)
		# if streaming is configured
		if self.__rtsp__:
			self.__rtsp__ = False
			# start streaming during startup
			logging.debug(
				function_name +
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			self.set_rtsp(True, True)
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			self.__restart_lock__.release()
			logging.debug(function_name + ": self.__restart_lock__.release()")
		# if recording is configured
		if self.__record__:
			self.__record__ = False
			# start recording during startup
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			self.set_record(True, True)
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			self.__restart_lock__.release()
			logging.debug(function_name + ": self.__restart_lock__.release()")
		logging.debug(function_name + ": exit")


	def stop(self):

		"""
		Stop Camera Server
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		if not self.__record__ and self.__stats__ == 0x0000040C:
			self.__stats__ = 0x000000000
		if self.__persistent__:
			logging.info("Writing parameters to 'camera.json' file")
			with open('camera.json', 'w') as config:
				config.write(self.get_parameters())
			os.system('sudo fake-hwclock')
			os.sync()
		else:
			parameters = None
			try:
				with open('camera.json', 'r') as config:
					parameters = json.load(config)
			except:
				pass
			if parameters is not None:
				parameters['persistent'] = self.__persistent__
				with open('camera.json', 'w') as config:
					json.dump(parameters, config)
		if self.__stats_id__ != 0:
			#logging.debug(
			#	function_name + 
			#	": self.__stats_lock__.acquire(blocking=True)")
			#self.__stats_lock__.acquire(blocking=True)
			GLib.source_remove(self.__stats_id__)
			self.__stats_id__ = 0
			#self.__stats_lock__.release()
			#logging.debug(function_name + ": self.__restart_lock__.release()")
		# if still streaming during shutdown
		if self.__rtsp__:
			# stop streaming during shutdown
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			self.set_rtsp(False, True)
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			self.__restart_lock__.release()
			logging.debug(function_name + ": self.__restart_lock__.release()")
		# if still recording during shutdown
		if self.__record__:
			# stop recording during shutdown
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			self.set_record(False, True)
			logging.debug(
				function_name + ": __restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			self.__restart_lock__.release()
			logging.debug(function_name + ": __restart_lock__.release()")
		# NOTE(marcin.sielski): Make sure pipeline elements are set to 
		# Gst.State.NULL so that the object can be safely disposed.
		
#		if self.__source__ is not None:
#			self.__source__.set_state(Gst.State.NULL)
#			self.__source__.unlink(self.__source_capsfilter__)
#			self.__pipeline__.remove(self.__source__)
#			self.__source__ = None
#			del self.__source__
#		if self.__source_capsfilter__ is not None:
#			self.__source_capsfilter__.set_state(Gst.State.NULL)
#			self.__source_capsfilter__.unlink(self.__raw_tee__)
#			self.__pipeline__.remove(self.__source_capsfilter__)
#			self.__source_capsfilter__ = None
#			self.__source_caps__ = None
#			del self.__source_caps__
#		if self.__raw_tee__ is not None:
#			self.__raw_tee__.set_state(Gst.State.NULL)
#			self.__raw_tee__.unlink(self.__converter__)
#			self.__pipeline__.remove(self.__raw_tee__)
#			self.__raw_tee__ = None
#			del self.__raw_tee__
#		if self.__converter__ is not None:
#			self.__converter__.set_state(Gst.State.NULL)
#			self.__converter__.unlink(self.__converter_capsfilter__)
#			self.__pipeline__.remove(self.__converter__)
#			self.__converter__ = None
#			del self.__converter__
#		if self.__converter_capsfilter__ is not None:
#			self.__converter_capsfilter__.set_state(Gst.State.NULL)
#			self.__converter_capsfilter__.unlink(self.__encoder__)
#			self.__pipeline__.remove(self.__converter_capsfilter__)
#			self.__converter_capsfilter__ = None
#			self.__converter_caps__ = None
#			del self.__converter_caps__
#		if self.__encoder__ is not None:
#			self.__encoder__.set_state(Gst.State.NULL)
#			self.__encoder__.unlink(self.__encoder_capsfilter__)
#			self.__pipeline__.remove(self.__encoder__)
#			self.__encoder__ = None
#			del self.__encoder__
#		if self.__encoder_capsfilter__ is not None:
#			self.__encoder_capsfilter__.set_state(Gst.State.NULL)
#			self.__encoder_capsfilter__.unlink(self.__parser__)
#			self.__pipeline__.remove(self.__encoder_capsfilter__)
#			self.__encoder_capsfilter__ = None
#			self.__encoder_caps__ = None
#			del self.__encoder_caps__
#		if self.__parser__ is not None:
#			self.__parser__.set_state(Gst.State.NULL)
#			self.__parser__.unlink(self.__h264_tee__)
#			self.__pipeline__.remove(self.__parser__)
#			self.__parser__ = None
#			del self.__parser__
#		if self.__h264_tee__ is not None:
#			self.__h264_tee__.set_state(Gst.State.NULL)
#			self.__h264_tee__.unlink(self.__payloader__)
#			self.__pipeline__.remove(self.__h264_tee__)
#			self.__h264_tee__ = None
#			del self.__h264_tee__
#		if self.__payloader__ is not None:
#			self.__payloader__.set_state(Gst.State.NULL)
#			self.__payloader__.unlink(self.__rtsp_tee__)
#			self.__pipeline__.remove(self.__payloader__)
#			self.__payloader__ = None
#			del self.__payloader__
#		if self.__rtsp_tee__ is not None:
#			self.__rtsp_tee__.set_state(Gst.State.NULL)
#			self.__rtsp_tee__.unlink(self.__sink_queue__)
#			self.__pipeline__.remove(self.__rtsp_tee__)
#			self.__rtsp_tee__ = None
#			del self.__rtsp_tee__
#		if self.__sink_queue__ is not None:
#			self.__sink_queue__.set_state(Gst.State.NULL)
#			self.__sink_queue__.unlink(self.__sink__)
#			self.__pipeline__.remove(self.__sink_queue__)
#			self.__sink_queue__ = None
#			del self.__sink_queue__
#		if self.__sink__ is not None:
#			self.__sink__.set_state(Gst.State.NULL)
#			self.__pipeline__.remove(self.__sink__)
#			self.__sink__ = None
#			del self.__sink__
#
#		if self.__file_queue__ is not None:
#			self.__file_queue__.set_state(Gst.State.NULL)
#			self.__file_queue__ = None
#		if self.__file_rate__ is not None:
#			self.__file_rate__.set_state(Gst.State.NULL)
#			self.__file_rate__ = None
#		if self.__file_converter__ is not None:
#			self.__file_converter__.set_state(Gst.State.NULL)
#			self.__file_converter__ = None
#		if self.__file_encoder__ is not None:
#			self.__file_encoder__.set_state(Gst.State.NULL)
#			self.__file_encoder__ = None
#		if self.__file_sink__ is not None:
#			self.__file_sink__.set_state(Gst.State.NULL)
#			self.__file_sink__ = None
		self.__pipeline__.set_state(Gst.State.NULL)
		logging.info(name(self) + " stopped")
		logging.debug(function_name + ": exit")


	def __on_error_lock_release__(self):

		"""
		Release self.__error_lock__

		Returns:
			bool: False to indicate execute once
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		if self.__error_lock__.locked():
			self.__error_lock__.release()
			logging.debug(function_name + ": __error_lock.release()")
		logging.debug(function_name + ": return False")
		return False


	def __on_restart__(self):
		
		"""
		Restart Camera Server to try to recover from error

		Returns:
			bool: False to indicate execute once
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		# NOTE(marcin.sielski): We are under error condition so try to restart 
		# only streaming.
		self.__record__ = False
		self.__rtsp__ = False
		self.__image_effect__ = 0
		self.restart(True)
		GLib.timeout_add_seconds(
			round((self.__camera_timeout__ + 500) / 1000), 
			self.__on_error_lock_release__)
		logging.debug(function_name + ": return False")
		return False


	def __on_stop__(self):

		"""
		Finalize recording

		Returns:
			bool: False to indicate execute only once
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		if self.__file_queue__ is not None:
			self.__file_queue__.set_state(Gst.State.NULL)
			self.__file_queue__ = None
		if self.__file_rate__ is not None:
			self.__file_rate__.set_state(Gst.State.NULL)
			self.__file_rate__ = None
		if self.__file_converter__ is not None:
			self.__file_converter__.set_state(Gst.State.NULL)
			self.__file_converter__ = None
		if self.__file_encoder__ is not None:
			self.__file_encoder__.set_state(Gst.State.NULL)
			self.__file_encoder__ = None
		if self.__file_sink__ is not None:
			self.__file_sink__.set_state(Gst.State.NULL)
			self.__file_sink__ = None
		self.__on_store__()
		if (
			(self.__model__ == 'imx219' or self.__model__ == 'imx477') and 
			self.__source__.get_property('annotation-mode') ==	0x0000040C
		):
			self.__source__.set_property('annotation-mode', 0x00000000)
		if self.__model__ == 'ov9281':
			self.set_stats(self.__stats__)
		logging.info("Recording stopped")
		# if request was executed in unsafe context
		if not self.__safe__:
			# if not unblocked by an error
			if self.__main_lock__.locked():
				# unblock concurrent requests
				self.__main_lock__.release()
				logging.debug(function_name + ": self.__main_lock__.release()")
		# if request was executed in safe context
		else:
			# if not unblocked by an error
			if self.__restart_lock__.locked():
				# unblock execution
				self.__restart_lock__.release()
				logging.debug(
					function_name + ": self.__restart_lock__.release()")
		logging.debug(function_name + ": return False")
		return False


	def __on_message__(self, bus, message):

		"""
		Handle messages on the bus

		Returns:
			BusSyncReply: with decision what to do further with the message
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		t = message.type
		logging.debug(function_name + ": "+str(t))
		if t == Gst.MessageType.EOS:
			logging.debug(function_name + ": Gst.MessageType.EOS")
			logging.info("EOS")
			GLib.timeout_add_seconds(0, self.__on_restart__)
			return Gst.BusSyncReply.DROP
		elif t == Gst.MessageType.ERROR:
			logging.debug(function_name + ": Gst.MessageType.ERROR")
			error, debug = message.parse_error()
			logging.error(str(error) + " at " + str(debug))
			if (
				str(error) == 
				"gst-stream-error-quark: Internal data stream error. (1)"
			):
				self.__pipeline__.set_state(Gst.State.PLAYING)
				sinkpad = self.__source__.get_static_pad("src").get_peer()
				if sinkpad is not None:
					sinkpad.send_event(Gst.Event.new_eos())
			else:
				# if error already is pending
				if self.__error_lock__.locked():
					# drop the message 
					return Gst.BusSyncReply.DROP
				# notify that server has pending error
				logging.debug(
					function_name + 
					": self.__error_lock__.acquire(blocking=True)")
				self.__error_lock__.acquire(blocking=True)
				# release any existing locks to resume execution
				if self.__main_lock__.locked():
					self.__main_lock__.release()
					logging.debug(
						function_name + ": self.__main_lock__.release()")
				if self.__restart_lock__.locked():
					self.__restart_lock__.release()
					logging.debug(
						function_name + ": self.__restart_lock__.release()")
		elif t == Gst.MessageType.ELEMENT:
			logging.debug(function_name + ": Gst.MessageType.ELEMENT")
			s = message.get_structure()
			if s.has_name("GstBinForwarded"):
				forward_msg = s.get_value("message")
				if forward_msg.type == Gst.MessageType.EOS:
					logging.info(
						"EOS received from element " + forward_msg.src.name)
					if forward_msg.src.name == 'file-sink':
						srcpad = self.__file_queue__.get_static_pad("src")
						if (
							srcpad is not None and 
							(srcpad.is_blocking() or srcpad.is_blocked())
						):
							srcpad.remove_probe(self.probe_id)
						# destroy pipeline
						self.__pipeline__.remove(self.__file_queue__)
						if self.__file_rate__ is not None:
						 	self.__pipeline__.remove(self.__file_rate__)
						if self.__file_converter__ is not None:
						 	self.__pipeline__.remove(self.__file_converter__)
						if self.__file_encoder__ is not None:
						 	self.__pipeline__.remove(self.__file_encoder__)
						self.__pipeline__.remove(self.__file_sink__)
						GLib.timeout_add_seconds(0, self.__on_stop__)
						return Gst.BusSyncReply.DROP
			# if s.has_name("GstMultiFileSink"):
			# 	self.__index__ = self.__file_sink__.get_property('index')
			# 	logging.debug(
			# 		function_name + ": self.__index__=" + str(self.__index__))
			# 	# NOTE(marcin.sielski): Workaround for index which cannot be set
			# 	# to -1.
			# 	if self.__index_changed__ and self.__index__ == 1:
			# 		self.__index__ = 0
			# 		self.__file_sink__.set_property('index', self.__index__)
			# 		self.__index_changed__ = False
			# 		filename = 'v_' + str(self.__width__) + 'x' +\
			# 			str(self.__height__) + '@' +\
			# 			str(self.__raw_framerate__) + '_I420_%02d.raw'
			# 		logging.debug(
			# 			function_name + ": " + 
			# 			filename.replace('_I420_%02d.raw','_I420_00.raw'))
			# 		self.__file_sink__.set_property('location',  filename)
			# 	elif self.__index__ >= self.__max_files__ - 1:
			# 		self.__index__ = 0
			# 		self.__file_sink__.set_property('index', self.__index__)
			# 		self.__index_changed__ = True
			# 		filename = 'v_' + str(self.__width__) + 'x' + \
			# 		str(self.__height__) + '@' + str(self.__raw_framerate__) + \
			# 		'_I420_00.raw'
			# 		logging.debug(
			# 			function_name + ": " + 
			# 			filename.replace('_I420_00.raw','_I420_09.raw'))
			# 		self.__file_sink__.set_property('location', filename)
			# 	elif self.__index__ == 0:
			# 		filename = 'v_' + str(self.__width__) + 'x' + \
			# 		str(self.__height__) + '@' + str(self.__raw_framerate__) + \
			# 		'_I420_00.raw'
			# 		logging.debug(function_name + ": " + filename)
			# 	elif self.__index_changed__:
			# 		filename = 'v_' + str(self.__width__) + 'x' + \
			# 		str(self.__height__) + '@' + str(self.__raw_framerate__) + \
			# 		'_I420_{0:0{1}}.raw'.format(self.__index__-1, 2)
			# 		logging.debug(function_name + ": " + filename)
			# 	else:
			# 		filename = 'v_' + str(self.__width__) + 'x' + \
			# 		str(self.__height__) + '@' + str(self.__raw_framerate__) + \
			# 		'_I420_{0:0{1}}.raw'.format(self.__index__, 2)
			# 		logging.debug(function_name + ": " + filename)

		elif t == Gst.MessageType.STATE_CHANGED:
			# if rtsp-sink or file-sink
			if (
				message.src.name == 'rtsp-sink' or 
				message.src.name == 'file-sink'
			):
				s = message.get_structure()
				# is PLAYING
				if (
					s.get_value('new-state') == Gst.State.PLAYING and
					s.get_value('pending-state') == Gst.State.VOID_PENDING
				):
					if message.src.name == 'rtsp-sink':
						logging.info("Streaming started")
					else:
						if (
							(self.__model__ == 'imx219' or 
							self.__model__ == 'imx477') and 
							self.__source__.get_property('annotation-mode') 
							== 0x00000000
						):
							self.__source__.set_property(
								'annotation-mode', 0x0000040C)
						if self.__model__ == 'ov9281':
							self.set_stats(self.__stats__)
						self.send_keyframe()
						logging.info("Recording started")
					# and request was executed in unsafe context
					if not self.__safe__:
						# if not unblocked by an error
						if self.__main_lock__.locked():
							# unblock concurrent requests
							self.__main_lock__.release()
							logging.debug(
								function_name + 
								": self.__main_lock__.release()")
					# and request was executed in safe context
					else:
						# if not unblocked by an error
						if self.__restart_lock__.locked():
							# unblock execution
							self.__restart_lock__.release()
							logging.debug(
								function_name + 
								": self.__restart_lock__.release()")
				
		return Gst.BusSyncReply.PASS


	def __get_source__(self):

		"""
		Return camera source

		Returns:
			GstRpiCamSrc: camera source
		"""

		if self.__model__ == 'imx219' or self.__model__ == 'imx477':
			source = Gst.ElementFactory.make('rpicamsrc', 'camera-source')
			source.set_property('preview', 0)
			source.set_property('annotation-mode', self.__stats__)
			source.set_property(
				'annotation-text', 
				'Copyright (c) 2021 Marcin Sielski\n\n' + self.__model__ + ' ')
			# NOTE(marcin.sielski): camera-timeout property is not available in 
			# regular GStreamer builds.
			source.set_property('camera-timeout', self.__camera_timeout__)

			# Quality

			source.set_property('sensor-mode', self.__sensor_mode__)

			# Effects

			source.set_property('brightness', self.__brightness__)
			source.set_property('contrast', self.__contrast__)
			source.set_property('saturation', self.__saturation__)
			source.set_property('sharpness', self.__sharpness__)
			source.set_property('drc', self.__drc__)
			source.set_property('image_effect', self.__image_effect__)
			source.set_property('awb-mode', self.__awb_mode__)
			source.set_property('awb-gain-blue', self.__awb_gain_blue__)
			source.set_property('awb-gain-red', self.__awb_gain_red__)

			# Controls

			source.set_property('exposure-mode', self.__exposure_mode__)
			source.set_property('metering-mode', self.__metering_mode__)
			source.set_property('exposure-compensation',
			self.__exposure_compensation__)
			source.set_property('iso', self.__iso__)
			source.set_property('shutter-speed', self.__shutter_speed__)
			source.set_property(
				'video-stabilisation', self.__video_stabilisation__)

			# Orientation

			source.set_property('rotation', self.__rotation__)
			source.set_property('hflip', self.__hflip__)
			source.set_property('vflip', self.__vflip__)
			source.set_property('video-direction', self.__video_direction__)

		if self.__model__ == 'ov9281':

			source = Gst.ElementFactory.make('arducamsrc', 'camera-source')

			# Controls

			source.set_property('exposure-mode', self.__exposure_mode__)
			source.set_property('shutter-speed', self.__shutter_speed__)
			source.set_property('gain', self.__gain__)
			source.set_property('awb', self.__awb__)

			# Orientation

			source.set_property('hflip', self.__hflip__)
			source.set_property('vflip', self.__vflip__)


		return source


	# Quality

	def set_resolution(self, width, height):

		"""
		Set resolution of the video

		Args:
			width (int): width of the video
			height (int): height of the video
		"""

		self.__width__ = width
		self.__height__ = height
		if (
			self.__sensor_mode__ == 6 and self.__width__ == 1280 and
			self.__height__ == 720 and self.__framerate__ > 60
		):
			self.__framerate__ = 60
		self.restart()


	def set_framerate(self, framerate):

		"""
		Set framerate of the video stream

		Args:
			framerate (int): framerate of the video stream
		"""

		self.__framerate__ = framerate
		self.restart()


	def set_bitrate_mode(self, bitrate_mode):

		"""
		Set desired bitrate mode of the video stream

		Args:
			bitrate_mode (int): desired bitrate mode of the video stream
		"""

		self.__bitrate_mode__ = bitrate_mode
		self.restart()


	def set_bitrate(self, bitrate):

		"""
		Set desired bitrate of the video stream

		Args:
			bitrate (int): desired bitrate of the video stream
		"""

		self.__bitrate__ = bitrate
		self.restart()


	def set_sensor_mode(self, sensor_mode):

		"""
		Set camera sensor mode

		Args:
			sensor_mode (int): camera sensor mode
		"""

		self.__sensor_mode__ = sensor_mode
		if self.__model__ == 'imx219' or self.__model__ == 'imx477':
			if self.__sensor_mode__ == 0:
				self.__framerate__ = 15
				self.__width__ = 800
				self.__height__ = 608
			if self.__sensor_mode__ == 1:
				self.__framerate__ = 15
				self.__width__ = 960
				self.__height__ = 544
			if self.__sensor_mode__ == 2:
				self.__framerate__ = 15
				self.__width__ = 800
				self.__height__ = 608
			if self.__sensor_mode__ == 3:
				self.__framerate__ = 15
				self.__width__ = 800
				self.__height__ = 608
			if self.__sensor_mode__ == 4:
				self.__framerate__ = 15
				self.__width__ = 800
				self.__height__ = 608
			if self.__sensor_mode__ == 5:
				self.__framerate__ = 15
				self.__width__ = 960
				self.__height__ = 544
			if self.__sensor_mode__ == 6:
				self.__framerate__ = 40
				self.__width__ = 960
				self.__height__ = 544
			if self.__sensor_mode__ == 7:
				self.__framerate__ = 40
				self.__width__ = 640
				self.__height__ = 480
		if self.__model__ == 'ov9281':
			if self.__sensor_mode__ == 0:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800
			if self.__sensor_mode__ == 1:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 720
			if self.__sensor_mode__ == 2:
				self.__framerate__ = 30
				self.__width__ = 640
				self.__height__ = 400
			if self.__sensor_mode__ == 3:
				self.__framerate__ = 30
				self.__width__ = 320
				self.__height__ = 200
			if self.__sensor_mode__ == 4:
				self.__framerate__ = 30
				self.__width__ = 160
				self.__height__ = 100
			if self.__sensor_mode__ == 5:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800
			if self.__sensor_mode__ == 6:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800
			if self.__sensor_mode__ == 7:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800
			if self.__sensor_mode__ == 8:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 720
			if self.__sensor_mode__ == 9:
				self.__framerate__ = 30
				self.__width__ = 640
				self.__height__ = 400
			if self.__sensor_mode__ == 10:
				self.__framerate__ = 30
				self.__width__ = 320
				self.__height__ = 200
			if self.__sensor_mode__ == 11:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800
			if self.__sensor_mode__ == 12:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800
			if self.__sensor_mode__ == 13:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 720
			if self.__sensor_mode__ == 14:
				self.__framerate__ = 30
				self.__width__ = 640
				self.__height__ = 400
			if self.__sensor_mode__ == 15:
				self.__framerate__ = 30
				self.__width__ = 320
				self.__height__ = 200
			if self.__sensor_mode__ == 16:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800
			if self.__sensor_mode__ == 17:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 720
			if self.__sensor_mode__ == 18:
				self.__framerate__ = 60
				self.__width__ = 640
				self.__height__ = 400
			if self.__sensor_mode__ == 19:
				self.__framerate__ = 80
				self.__width__ = 320
				self.__height__ = 200
			if self.__sensor_mode__ == 20:
				self.__framerate__ = 80
				self.__width__ = 160
				self.__height__ = 100
			if self.__sensor_mode__ == 21:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800
			if self.__sensor_mode__ == 22:
				self.__framerate__ = 30
				self.__width__ = 1280
				self.__height__ = 800

		self.restart()


	# Effects

	def set_brightness(self, brightness):

		"""
		Set brightness of the video

		Args:
			brightness (int): brightness of the video
		"""

		self.__brightness__ = brightness
		self.__source__.set_property('brightness', self.__brightness__)


	def set_contrast(self, contrast):

		"""
		Set contrast of video

		Args:
			contrast (int): contrast of the video
		"""

		self.__contrast__ = contrast
		self.__source__.set_property('contrast', self.__contrast__)


	def set_saturation(self, saturation):

		"""
		Set saturation of the video

		Args:
			saturation (int): saturation of the video
		"""

		self.__saturation__ = saturation
		self.__source__.set_property('saturation', self.__saturation__)


	def set_sharpness(self, sharpness):

		"""
		Set sharpness of the video

		Args:
			sharpness (int): sharpness of the video
		"""

		self.__sharpness__ = sharpness
		self.__source__.set_property('sharpness', self.__sharpness__)


	def set_drc(self, drc):

		"""
		Set Dynamic Range Control (DRC)

		Args:
			drc (int): dynamic range control level
		"""

		self.__drc__ = drc
		self.__source__.set_property('drc', self.__drc__)


	def set_image_effect(self, image_effect):

		"""
		Set image effect filter

		Args:
			image_effect (int): image effect filter
		"""

		self.__image_effect__ = image_effect
		self.__source__.set_property('image-effect', self.__image_effect__)


	def set_awb_mode(self, awb_mode):

		"""
		Set Auto White Balance mode (AWB)

		Args:
			awb_mode (int): auto white balance mode 
		"""

		self.__awb_mode__ = awb_mode
		self.__awb_gain_blue__ = 0
		self.__awb_gain_red__ = 0
		self.__source__.set_property('awb-gain-blue', self.__awb_gain_blue__)
		self.__source__.set_property('awb-gain-red', self.__awb_gain_red__)
		if self.__awb_mode__ == 0 or self.__awb_mode__ == 9:
			self.restart()	
		else:
			self.__source__.set_property('awb-mode', self.__awb_mode__)


	def set_awb_gain_blue(self, awb_gain_blue):
		
		"""
		Set White Balance Gain for blue channel and disable AWB

		Args:
			awb_gain_blue (int): white balance gain for blue channel
		"""

		self.__awb_gain_blue__ = awb_gain_blue
		self.__awb_mode__ = 0
		self.__source__.set_property('awb-mode', self.__awb_mode__)
		if self.__awb_gain_blue__ == 0:
			self.restart()			
		else:
			self.__source__.set_property(
				'awb-gain-blue', self.__awb_gain_blue__)


	def set_awb_gain_red(self, awb_gain_red):

		"""
		Set White Balance Gain for red channel and disable AWB

		Args:
			awb_gain_red (int): white balance gain for the red channel
		"""

		self.__awb_gain_red__ = awb_gain_red
		self.__awb_mode__ = 0
		self.__source__.set_property('awb-mode', self.__awb_mode__)
		if self.__awb_gain_red__ == 0:
			self.restart()
		else:
			self.__source__.set_property('awb-gain-red', self.__awb_gain_red__)


	# Controls

	def set_exposure_mode(self, exposure_mode):

		"""
		Set exposure mode

		Args:
			exposure_mode (int): exposure mode
		"""

		self.__exposure_mode__ = exposure_mode
		#if self.__exposure_mode__ == 1:
		#	self.__shutter_speed__ = 0
		if self.__exposure_mode__ == 0 and (
			self.__model__ == 'imx219' or self.__model__ == 'imx477'):
			self.restart()
		else:
			self.__source__.set_property('exposure-mode',
			self.__exposure_mode__)


	def set_metering_mode(self, metering_mode):

		"""
		Set metering mode

		Args:
			metering_mode (int): metering mode
		"""

		self.__metering_mode__ = metering_mode
		self.__source__.set_property('metering-mode', self.__metering_mode__)


	def set_exposure_compensation(self, exposure_compensation):

		"""
		Set exposure compensation

		Args:
			exposure_compensation (int): exposure compensation
		"""

		self.__exposure_compensation__ = exposure_compensation
		self.__source__.set_property('exposure-compensation',
		self.__exposure_compensation__)


	def set_iso(self, iso):

		"""
		Set ISO value

		Args:
			iso (int): ISO value
		"""

		self.__iso__ = iso
		self.__source__.set_property('iso', self.__iso__)


	def set_shutter_speed(self, shutter_speed):

		"""
		Set shutter speed in microseconds

		Args:
			shutter_speed (int): shutter speed
		"""

		self.__shutter_speed__ = shutter_speed
		#if self.__shutter_speed__ == 0:
		#	self.__exposure_mode__ = 1
		#else:
		#	self.__exposure_mode__ = 0
		if self.__model__ == 'imx219' or self.__model__ == 'imx477':
			self.restart()
		if self.__model__ == 'ov9281':
			self.__source__.set_property(
				'shutter-speed', self.__shutter_speed__)


	def set_video_stabilisation(self, video_stabilisation):

		"""
		Set video stabilisation

		Args:
			video_stabilisation (int): 
		"""

		self.__video_stabilisation__ = video_stabilisation
		if self.__video_stabilisation__:
			self.__source__.set_property(
				'video-stabilisation', self.__video_stabilisation__)
		else:			
			self.restart()


	def set_gain(self, gain):
	
		"""
		Set gain

		Args:
			gain (int): gain
		"""

		self.__gain__ = gain
		self.__source__.set_property('gain', self.__gain__)


	def set_awb(self, awb):
	
		"""
		Set awb

		Args:
			awb (int): awb
		"""

		self.__awb__ = awb
		self.__source__.set_property('awb', self.__awb__)


	# Orientation

	def set_rotation(self, rotation):

		"""
		Set rotation of the video stream

		Args:
			rotation (int): rotation of the video stream
		"""

		self.__rotation__ = rotation
		self.__source__.set_property('rotation', self.__rotation__)
		self.__flip__()


	def __flip__(self):

		"""
		Calculate video orientation based on rotation, hflip and vflip
		"""

		if (
			(
				self.__rotation__ == 0 and
				self.__hflip__ == False and
				self.__vflip__ == False
			)
			or
			(
				self.__rotation__ == 180 and
				self.__hflip__ == True and
				self.__vflip__ == True
			)
		):
			self.__video_direction__ = 0
		if (
			(
				self.__rotation__ == 90 and
				self.__hflip__ == False and
				self.__vflip__ == False
			)
			or
			(
				self.__rotation__ == 270 and
				self.__hflip__ == True and
				self.__vflip__ == True
			)
		):
			self.__video_direction__ = 1
		if (
			(
				self.__rotation__ == 0 and
				self.__hflip__ == True and
				self.__vflip__ == True
			)
			or 
			(
				self.__rotation__ == 180 and
				self.__hflip__ == False and
				self.__vflip__ == False
			)
		):
			self.__video_direction__ = 2
		if (
			(
				self.__rotation__ == 90 and 
				self.__hflip__ == True and 
				self.__vflip__ == True
			)
			or
			(
				self.__rotation__ == 270 and 
				self.__hflip__ == False and 
				self.__vflip__ == False
			)
		):
			self.__video_direction__ = 3
		if (
			(
				self.__rotation__ == 0 and 
				self.__hflip__ == True and 
				self.__vflip__ == False
			) 
			or 
			(
				self.__rotation__ == 180 and 
				self.__hflip__ == False and 
				self.__vflip__ == True
			)
		):
			self.__video_direction__ = 4
		if (
			(
				self.__rotation__ == 0 and 
				self.__hflip__ == False and 
				self.__vflip__ == True
			) 
			or
			(
				self.__rotation__ == 180 and 
				self.__hflip__ == True and 
				self.__vflip__ == False
			)
		):
			self.__video_direction__ = 5
		if (
			(
				self.__rotation__ == 90 and 
				self.__hflip__ == False and 
				self.__vflip__ == True
			) 
			or 
			(
				self.__rotation__ == 270 and 
				self.__hflip__ == True and 
				self.__vflip__ == False
			)
		):
			self.__video_direction__ = 6
		if (
			(
				self.__rotation__ == 90 and 
				self.__hflip__ == True and 
				self.__vflip__ == False
			) 
			or
			(
				self.__rotation__ == 270 and 
				self.__hflip__ == False and 
				self.__vflip__ == True
			)
		):
			self.__video_direction__ = 7


	def set_hflip(self, hflip):

		"""
		Set horizontal video stream flip

		Args:
			hflip (bool): True if video shall be horizontally flipped, False
				otherwise
		"""

		self.__hflip__ = hflip
		self.__source__.set_property('hflip', self.__hflip__)
		self.__flip__()


	def set_vflip(self, vflip):

		"""
		Set vertical video stream flip

		Args:
			vflip (bool): True if video stream shall be vertically flipped,
				False otherwise
		"""

		self.__vflip__ = vflip
		self.__source__.set_property('vflip', self.__vflip__)
		self.__flip__()


	def set_video_direction(self, video_direction):

		"""
		Set video stream direction

		Args:
			video_direction (int): direction of the video stream
		"""

		self.__video_direction__ = video_direction
		if self.__video_direction__ == 0:
			self.__rotation__ = 0
			self.__hflip__ = False
			self.__vflip__ = False
		if self.__video_direction__ == 1:
			self.__rotation__ = 90
			self.__hflip__ = False
			self.__vflip__ = False				
		if self.__video_direction__ == 2:
			self.__rotation__ = 180
			self.__hflip__ = False
			self.__vflip__ = False
		if self.__video_direction__ == 3:
			self.__rotation__ = 270
			self.__hflip__ = False
			self.__vflip__ = False		
		if self.__video_direction__ == 4:
			self.__rotation__ = 0
			self.__hflip__ = True
			self.__vflip__ = False
		if self.__video_direction__ == 5:
			self.__rotation__ = 0
			self.__hflip__ = False
			self.__vflip__ = True
		if self.__video_direction__ == 6:
			self.__rotation__ = 90
			self.__hflip__ = False
			self.__vflip__ = True	
		if self.__video_direction__ == 7:
			self.__rotation__ = 270
			self.__hflip__ = False
			self.__vflip__ = True		
		self.__source__.set_property(
			'video-direction', self.__video_direction__)


	def __on_stats__(self):
		
		"""
		Callback function executed in the background to collect statistics
		"""
		
		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		#if not self.__stats_lock__.locked():
		#	logging.debug(
		#		function_name + 
		#		": self.__stats_lock__.acquire(blocking=True)")
		#	self.__stats_lock__.acquire(blocking=True)
		if self.__model__ == 'imx219' or self.__model__ == 'imx477':
			if self.__stats__ == 0x0000040C or self.__stats__ == 0x00000000:
				self.__stats_id__ = 0
		#			self.__stats_lock__.release()
		#			logging.debug(function_name + ": false")
				return False
			# TODO: Fix subprocess.check_output during shutdown
			self.__source__.set_property(
				'annotation-text', 
				'CPU: ' + str(psutil.cpu_percent()) + 
				'% MEM: ' + str(psutil.virtual_memory().percent) + 
				'% TMP: ' + str(round(CPUTemperature().temperature, 1)) + 
				'C DSK: ' + str(round(DiskUsage().usage, 1)) + 
				'% THR: ' + subprocess.check_output(
					['vcgencmd', 'get_throttled']).decode('utf-8').replace(
						'throttled=','').strip() + '\n\n' + self.__model__ + 
						' ')
		if self.__model__ == 'ov9281':
			tm = time.localtime()
			if self.__record__ and self.__stats__ == 0x00000000:
				self.__overlay__.set_property(
						'text', str(tm.tm_hour) + ':' +
						str(tm.tm_min).zfill(2) + ':' +
						str(tm.tm_sec).zfill(2) + ' ' + str(tm.tm_mon) +
						'/' + str(tm.tm_mday) + '/' + str(tm.tm_year))
			else:
				shutter_speed = self.__source__.get_property(
					'shutter-speed')
				self.__overlay__.set_property(
					'text',
					'CPU: ' + str(psutil.cpu_percent()) + 
					'% MEM: ' + str(psutil.virtual_memory().percent) + 
					'% TMP: ' + str(round(CPUTemperature().temperature, 1))+ 
					'C DSK: ' + str(round(DiskUsage().usage, 1)) + 
					'% THR: ' + subprocess.check_output(
						['vcgencmd', 'get_throttled']).decode(
							'utf-8').replace('throttled=','').strip() + 
							'\n' + self.__model__ + ' ' + str(tm.tm_hour) +
							':' + str(tm.tm_min).zfill(2) + ':' + 
							str(tm.tm_sec).zfill(2) + ' ' + str(tm.tm_mon) +
							'/' + str(tm.tm_mday) + '/' + str(tm.tm_year) +
							'\n' + 'Shutter (current: ' +
							str(shutter_speed) + ', range: 30000)'	 
				)
		#	self.__stats_lock__.release()
		logging.debug(function_name + ": true")
		return True
		

	def set_stats(self, stats):
		
		"""
		Set stats overlay on the video stream

		Args:
			stats (int): stats to overlay on the video stream
		"""
		if self.__model__ == 'imx219' or self.__model__ == 'imx477':
			if self.__stats_id__ != 0:
				GLib.source_remove(self.__stats_id__)
				self.__stats_id__ = 0
				self.__source__.set_property(
					'annotation-text', 
					'Copyright (c) 2021 Marcin Sielski\n\n' + 
					self.__model__ + ' ')
			if self.__record__ and stats == 0x00000000:
				self.__stats__ = 0x0000040C
			else:
				self.__stats__ = stats
				self.__stats_id__ = GLib.timeout_add_seconds(
						1, self.__on_stats__)

			self.__source__.set_property('annotation-mode', self.__stats__)
		if self.__model__ == 'ov9281':
			if self.__stats_id__ != 0:
				GLib.source_remove(self.__stats_id__)
				self.__stats_id__ = 0
			if self.__record__ and stats == 0x00000000:
				self.__stats__ = stats
				tm = time.localtime()
				self.__overlay__.set_property(
					'text', str(tm.tm_hour) + ':' + str(tm.tm_min).zfill(2) + 
					':' + str(tm.tm_sec).zfill(2) + ' ' + str(tm.tm_mon) + '/' + 
					str(tm.tm_mday) + '/' + str(tm.tm_year))
				self.__overlay__.set_property('silent', False)
				self.__stats_id__ = GLib.timeout_add_seconds(
						1, self.__on_stats__)
			else:
				self.__stats__ = stats
				tm = time.localtime()
				if stats == 0x00000000 or (
					stats == 0x00000000 and not self.__record__):
					self.__overlay__.set_property('silent', True)
				else:
					self.__overlay__.set_property(
					'text', 'Copyright (c) 2021 Marcin Sielski\n' +
					self.__model__ + ' ' + str(tm.tm_hour).zfill(2) + ':' + 
					str(tm.tm_min).zfill(2) + ':' + str(tm.tm_sec).zfill(2) +
					' ' + str(tm.tm_mon) + '/' + str(tm.tm_mday) + '/' + 
					str(tm.tm_year))
					self.__overlay__.set_property('silent', False)
					self.__stats_id__ = GLib.timeout_add_seconds(
						1, self.__on_stats__)


	def __enable_disable_rtsp__(self, pad, info):

		"""
		Enable or disable RTSP streaming

		Args:
			pad (Pad): probe pad
			info (PadProbeInfo): pad probe info

		Returns:
			PadProbeReturn: DROP data in data probes
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		pad.remove_probe(info.id)
		# if this is start streaming request
		if self.__rtsp__:	
			# create pipeline
			self.__rtsp_queue__ = Gst.ElementFactory.make('queue', 'rtsp-queue')
			self.__rtsp_sink__ = Gst.ElementFactory.make('udpsink', 'rtsp-sink')
			self.__rtsp_sink__.set_property('host', '127.0.0.1')
			self.__rtsp_sink__.set_property('port', 3141)
			self.__rtsp_sink__.set_property('sync', False)
			self.__pipeline__.add(self.__rtsp_queue__)
			self.__pipeline__.add(self.__rtsp_sink__)
			self.__rtsp_tee__.link(self.__rtsp_queue__)
			self.__rtsp_queue__.link(self.__rtsp_sink__)
			self.__rtsp_queue__.set_state(Gst.State.PLAYING)
			self.__rtsp_sink__.set_state(Gst.State.PLAYING)
		# if this is stop streaming request
		else:
			# destroy pipeline
			self.__rtsp_queue__.set_state(Gst.State.NULL)
			self.__rtsp_sink__.set_state(Gst.State.NULL)
			self.__pipeline__.remove(self.__rtsp_queue__)
			self.__pipeline__.remove(self.__rtsp_sink__)
			logging.info("Streaming stopped")
			# if function is execute in the unsafe context
			if not self.__safe__:
				# if not unblocked by an error
				if self.__main_lock__.locked():
					self.__main_lock__.release()
					logging.debug(
						function_name + ": self.__main_lock__.release()")
			# if function is executed in safe context
			else:
				# if not unblocked by an error
				if self.__restart_lock__.locked():
					self.__restart_lock__.release()
					logging.debug(
						function_name + ": self.__restart_lock__.release()")
		logging.debug(function_name + ": return Gst.PadProbeReturn.DROP")
		return Gst.PadProbeReturn.DROP


	def set_rtsp(self, rtsp, safe=False):

		"""
		Set RTSP streaming

		Args:
			rtsp (bool): True if streaming shall be enabled, False otherwise
			safe (bool): indicate if function is executed in safe context
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(
			function_name + ": rtsp=" + str(rtsp) + ", safe=" + str(safe))
		# discard invalid requests
		if self.__rtsp__ == rtsp:
			logging.warning("Discarding invalid RTSP request")
			logging.debug(function_name + ": exit")
			return
		# if function is executed in unsafe context
		if not safe:
			# if error is pending
			if self.__error_lock__.locked():
				# discard the request
				logging.warning("Discarding RTSP request due to pending error")
				logging.debug(function_name + ": exit")
				return
			# block concurrent requests
			logging.debug(
				function_name + ": self.__main_lock__.acquire(blocking=True)")
			self.__main_lock__.acquire(blocking=True)
			# if error is pending
			if self.__error_lock__.locked():
				# discard the request
				logging.warning("Discarding RTSP request due to pending error")
				logging.debug(function_name + ": exit")
				return
		self.__safe__ = safe		
		self.__rtsp__ = rtsp
		#srcpad = self.__source__.get_static_pad( "src")
		srcpad = self.__payloader__.get_static_pad( "src")
		srcpad.add_probe(
			Gst.PadProbeType.BLOCK_DOWNSTREAM, self.__enable_disable_rtsp__)
		logging.debug(function_name + ": exit")


	def __push_eos__(self):

		"""
		Push EOS to the sinkpad

		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		sinkpad = self.__file_queue__.get_static_pad("src").get_peer()
		logging.info("Pushing EOS event on pad " + sinkpad.name)
		self.__pipeline__.set_property("message-forward", True)
		sinkpad.send_event(Gst.Event.new_eos())
		logging.debug(function_name + ": exit")


	def __on_store__(self):

		"""
		Store data on disk callback.
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		if self.__persistent__:
			logging.info("Writing parameters to 'camera.json' file")
			with open('camera.json', 'w') as config:
				config.write(self.get_parameters())
		os.system('sudo fake-hwclock')
		os.sync()
		logging.debug(function_name + ": exit")


	def __on_format_location__(self, splitmux, fragment_id):


		"""
		format-location callback executed when new file is about to be created

		Args:
			splitmux (GstSplitMuxSink): splitmux sink element
			fragment_id (int): fragment id

		Returns:
			str: file name
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": fragment_id=" + str(fragment_id))
		if self.__format__:
			result = 'v_' + str(self.__width__) + 'x' + str(self.__height__) + \
				'_HYUV_{0:0{1}}.mkv'.format(fragment_id, 2)
		else:
			result = 'v_' + str(self.__width__) + 'x' + str(self.__height__) + \
				'_H264_{0:0{1}}.mp4'.format(fragment_id, 2)
		self.__fragment_id__ = fragment_id + 1
		GLib.timeout_add_seconds(0, self.__on_store__)
		logging.debug(function_name + ": return " + result)
		return result


	# def __on_overrun__(self, queue):

	# 	"""
	# 	Queue overrun callback executed when queue is full

	# 	Args:
	# 		queue (GstQueue): queue
	# 	"""

	# 	function_name = "'" + threading.currentThread().name + "'." + \
	# 		type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
	# 	logging.debug(function_name + ": entry")
	# 	self.__raw_framerate__ = self.__raw_framerate__ - 1
	# 	if self.__raw_framerate__ <= 0:
	# 		self.__raw_framerate__ = 1
	# 	self.__file_rate__.set_property('max-rate', self.__raw_framerate__)
	# 	self.__file_sink__.set_property(
	# 				'location', 'v_' + str(self.__width__) + 'x' + 
	# 				str(self.__height__) + '@' + str(self.__raw_framerate__) + 
	# 				'_I420_%02d.raw')
	# 	logging.debug(function_name + ": exit")


	def __enable_disable_record__(self, pad, info):

		"""
		Enable or disable video recording

		Args:
			pad (Pad): probe pad
			info (PadProbeInfo): pad probe info

		Returns:
			PadProbeReturn: DROP data in data probes
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		# if this is record request
		if self.__record__:
			# create pipeline
			pad.remove_probe(info.id)
			self.__file_queue__ = Gst.ElementFactory.make('queue', 'file-queue')
			self.__file_queue__.set_property(
				'max-size-bytes', 0)
			self.__file_queue__.set_property(
				'max-size-buffers',  0)
			self.__file_queue__.set_property('max-size-time',  0)
			if self.__format__:
				if self.__throughput__ > 0:
					#self.__file_queue__.set_property('leaky', 1)
					# self.__file_queue__.connect(
					# 	'overrun', self.__on_overrun__)
					self.__file_rate__ = Gst.ElementFactory.make(
						'videorate', 'rate')
					# estimate required throughput
					throughput = round(self.__width__ * self.__height__ * 12 *\
						self.__framerate__ / (8 * 1024 * 1024))
					if throughput > self.__throughput__:
						self.__raw_framerate__ = \
							round(self.__throughput__ * 8 * 1024 * 1024 /
							(self.__width__ * self.__height__ * 12))
						if self.__raw_framerate__ <= 1:
							self.__raw_framerate__ = 1
					else:
				 		self.__raw_framerate__ = self.__framerate__
					logging.debug(
				 		function_name + ': self.__raw__framerate__=' + 
				 		str(self.__raw_framerate__))
					self.__file_rate__.set_property(
				 		'max-rate', self.__raw_framerate__)
					self.__file_rate__.set_property('drop-only', True)
				self.__file_converter__ =\
					Gst.ElementFactory.make('videoconvert','converter')
				self.__file_encoder__ = \
					Gst.ElementFactory.make('avenc_huffyuv','file-encoder')
				self.__file_muxer__ = \
					Gst.ElementFactory.make('matroskamux','file-muxer')
				self.__file_sink__ = Gst.ElementFactory.make(
					'splitmuxsink', 'file-sink')
				self.__file_sink__.set_property(
					'muxer', self.__file_muxer__)
				self.__file_sink__.set_property(
					'max-size-time', self.__max_size_time__)
				self.__file_sink__.set_property(
					'max-size-bytes', self.__max_size_bytes__)
				self.__file_sink__.set_property('max-files', self.__max_files__)
				logging.debug(
					function_name + ": self.__fragment_id__=" +
					str(self.__fragment_id__))
				self.__file_sink__.set_property(
					'start-index', self.__fragment_id__)
				self.__file_sink__.connect(
					'format-location', self.__on_format_location__)
				self.__file_sink__.set_property(
					'location', 'v_' + str(self.__width__) + 'x' + 
					str(self.__height__) + 
					'_HYUV_{0:0{1}}.mkv'.format(self.__fragment_id__, 2))
				# self.__file_sink__ = Gst.ElementFactory.make(
				# 	'multifilesink', 'file-sink')
				# self.__file_sink__.set_property(
				# 	'location', 'v_' + str(self.__width__) + 'x' + 
				# 	str(self.__height__) + '@' + str(self.__raw_framerate__) + 
				# 	'_I420_%02d.raw')
				# self.__index_changed__ = False
				# self.__file_sink__.set_property(
				# 	'max-file-duration', self.__max_size_time__)
				# self.__file_sink__.set_property(
				# 	'max-file-size', self.__max_size_bytes__)
				# self.__file_sink__.set_property('max-files', self.__max_files__)
				# if self.__max_size_time__ == 0 and self.__max_size_bytes__ == 0:
				# 	self.__next_file__ = 3
				# elif self.__max_size_time__ > 0 and self.__max_size_bytes__ > 0:
				# 	# NOTE(marcin.sielski): This is new option not available in 
				# 	# regular GStreamer builds.
				# 	self.__next_file__ = 6
				# elif self.__max_size_time__ > 0:
				# 	self.__next_file__ = 5
				# elif self.__max_size_bytes__ > 0:
				# 	self.__next_file__ = 4
				# 	logging.debug(
				# 		function_name + ": self.__next_file__=" + 
				# 		str(self.__next_file__))
				# self.__file_sink__.set_property('next-file', self.__next_file__)
				# self.__file_sink__.set_property('post-messages', True)
				# self.__file_sink__.set_property('async', True)
				# self.__file_sink__.set_property('sync', False)
				# if self.__index__ >= 10:
				# 	self.__index__ = 0
				# logging.debug(
				# 	function_name + ": self.__index__=" + str(self.__index__))
				# self.__file_sink__.set_property('index', self.__index__)
			else:
				self.__file_sink__ = Gst.ElementFactory.make(
					'splitmuxsink', 'file-sink')
				self.__file_sink__.set_property(
					'max-size-time', self.__max_size_time__)
				self.__file_sink__.set_property(
					'max-size-bytes', self.__max_size_bytes__)
				self.__file_sink__.set_property('max-files', self.__max_files__)
				logging.debug(
					function_name + ": self.__fragment_id__=" +
					str(self.__fragment_id__))
				self.__file_sink__.set_property(
					'start-index', self.__fragment_id__)
				self.__file_sink__.connect(
					'format-location', self.__on_format_location__)
				self.__file_sink__.set_property(
					'location', 'v_' + str(self.__width__) + 'x' + 
					str(self.__height__) + 
					'_H264_{0:0{1}}.mp4'.format(self.__fragment_id__, 2))
				self.__file_sink__.set_property('send-keyframe-requests', True)
			self.__pipeline__.add(self.__file_queue__)
			self.__pipeline__.add(self.__file_sink__)
			if self.__format__:
				if self.__throughput__ > 0:
					self.__pipeline__.add(self.__file_rate__)
				self.__pipeline__.add(self.__file_converter__)
				self.__pipeline__.add(self.__file_encoder__)
				self.__raw_tee__.link(self.__file_queue__)
				if self.__throughput__ > 0:
					self.__file_queue__.link(self.__file_rate__)
					self.__file_rate__.link(self.__file_converter__)
				else:
					self.__file_queue__.link(self.__file_converter__)
				self.__file_converter__.link(self.__file_encoder__)
				self.__file_encoder__.link(self.__file_sink__)
				if self.__throughput__ > 0:
					self.__file_rate__.set_state(Gst.State.PLAYING)
				self.__file_converter__.set_state(Gst.State.PLAYING)
				self.__file_encoder__.set_state(Gst.State.PLAYING)
			else:
				self.__h264_tee__.link(self.__file_queue__)
				self.__file_queue__.link(self.__file_sink__)
			self.__file_queue__.set_state(Gst.State.PLAYING)
			self.__file_sink__.set_state(Gst.State.PLAYING)

		logging.debug(function_name + ": return Gst.PadProbeReturn.DROP")
		return Gst.PadProbeReturn.DROP


	def set_record(self, record, safe=False):

		"""
		Set video recording

		Args:
			record (bool): True if recording shall started, False otherwise
			safe (bool): indicate if function is executed from safe context
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(
			function_name + ": record=" + str(record) + ", safe=" + str(safe))
		# discard invalid requests
		if self.__record__ == record:
			logging.warning("Discarding invalid record request")
			logging.debug(function_name + ": exit")
			return
		# if function is executed in unsafe context
		if not safe:
			# if error is pending
			if self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding record request due to pending error")
				logging.debug(function_name + ": exit")
				return
			# block concurrent requests
			logging.debug(
				function_name + ": self.__main_lock__.acquire(blocking=True)")
			self.__main_lock__.acquire(blocking=True)
			# if error is pending
			if self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding record request due to pending error")
				logging.debug(function_name + ": exit")
				return
		self.__safe__ = safe
		self.__record__ = record
		if self.__record__:
			srcpad = None
			if self.__format__:
				srcpad = self.__source__.get_static_pad( "src")
			else:
				srcpad = self.__encoder__.get_static_pad( "src")
			srcpad.add_probe(
				Gst.PadProbeType.BLOCK_DOWNSTREAM,
				self.__enable_disable_record__)
		else:
			# if self.__format__:
			# 	self.__index__ = self.__index__ + 1
			# 	if self.__index__ >= 10:
			# 		self.__index__ = 0
			srcpad = self.__file_queue__.get_static_pad("src")
			self.probe_id = srcpad.add_probe(
				Gst.PadProbeType.BLOCK | Gst.PadProbeType.BUFFER, 
				self.__enable_disable_record__)
			threading.Thread(target=self.__push_eos__, args=()).start()
		logging.debug(function_name + ": exit")


	def remove(self, filename):

		"""
		Remove file from media folder

		Args:
			filename (str): name of the file to remove
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name

		logging.debug(function_name + ": filename=" + str(filename))

		if filename == '':
			_, _, filenames = next(os.walk('.'))
			media = []
			for filename in filenames:
				if filename.endswith('.mkv') or filename.endswith('.mp4'):
					if os.path.exists(filename):
						os.remove(filename)
					else:
						logging.warning(
							function_name + ": filename=" + str(filename) + 
						" does not exist")
		else:
			if os.path.exists(filename):
				os.remove(filename)
			else:
				logging.warning(
					function_name + ": filename=" + str(filename) + 
					" does not exist")

		logging.debug(function_name + ": exit")


	def restart(self, safe=False):

		"""
		Restart Camera Server

		Args:
			safe (bool): indicate if function is executed in the safe context
		"""
		#snapshot1 = tracemalloc.take_snapshot()
		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": safe=" + str(safe))
		# if function is executed in unsafe context
		if not safe:
			# if error is pending
			if self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
			# block concurrent requests
			logging.debug(
				function_name + ": self.__main_lock__.acquire(blocking=True)")
			self.__main_lock__.acquire(blocking=True)
			# if error is pending
			if self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
		rtsp = self.__rtsp__
		record = self.__record__
		# if server is streaming
		if self.__rtsp__:
			# stop streaming
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			# if function is executed in unsafe context and if error is pending
			if not safe and self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
			self.set_rtsp(False, True)
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			# if function is executed in unsafe context and if error is pending
			if not safe and self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
			self.__restart_lock__.release()
			logging.debug(function_name + ": self.__restart_lock__.release()")
		# if server is recording
		if self.__record__:
			# stop recording
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			# if function is executed in unsafe context and if error is pending
			if not safe and self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return			
			self.set_record(False, True)
			logging.debug(
				function_name + ": __restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			# if function is executed in unsafe context and if error is pending
			if not safe and self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
			self.__restart_lock__.release()
			logging.debug(function_name + ": self.__restart_lock__.release()")
		super().restart()
		# if server was streaming before the restart 
		if rtsp:
			# start streaming
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			# if function is executed in unsafe context and if error is pending
			if not safe and self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
			self.set_rtsp(True, True)
			logging.debug(
				function_name + ": __restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			# if function is executed in unsafe context and if error is pending
			if not safe and self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
			self.__restart_lock__.release()
			logging.debug(function_name + ": self.__restart_lock__.release()")
		# if server was recording before the restart
		if record:
			# start recording
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			# if function is executed in unsafe context and if error is pending
			if not safe and self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
			self.set_record(True, True)
			logging.debug(
				function_name + 
				": self.__restart_lock__.acquire(blocking=True)")
			self.__restart_lock__.acquire(blocking=True)
			# if function is executed in unsafe context and if error is pending
			if not safe and self.__error_lock__.locked():
				# discard the request
				logging.warning(
					"Discarding restart request due to pending error")
				logging.debug(function_name + ": exit")
				return
			self.__restart_lock__.release()
			logging.debug(function_name + ": self.__restart_lock__.release()")
		# if function is executed in unsafe context and was not unblocked by
		# an error
		if not safe and self.__main_lock__.locked():
			# unblock concurrent requests
			self.__main_lock__.release()
			logging.debug(function_name + ": self.__main_lock__.release()")
		logging.debug(function_name + ": exit")
		#snapshot2 = tracemalloc.take_snapshot()
		#top_stats = snapshot2.compare_to(snapshot1, 'lineno')
		#for stat in top_stats[:10]:
		#	print(stat)


	def set_format(self, format):

		"""
		Set format of recorded video file

		Args:
			format (bool): format of recorded video file
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": format="+str(format))
		self.__format__ = format
		if self.__record__:
			self.set_record(False)
			self.set_record(True)
		logging.debug(function_name + ": exit")


	def set_max_files(self, max_files):

		"""
		Set maximum number of recorded video files to keep on storage device
		Once the maximum is reached old files start to be deleted to make room
		for new ones

		Args:
			max_files (int): maximum number of recorded video files
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": max_files=" + str(max_files))
		self.__max_files__ = max_files
		if self.__file_sink__ is not None:
			self.__file_sink__.set_property('max-files', self.__max_files__)
		logging.debug(function_name + ": exit")


	def set_max_size_bytes(self, max_size_bytes):

		"""
		Set maximum size of the recorded video file in bytes

		Args:
			max_size_bytes (int): maximum size of the recorded video file in
				bytes
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": max_size_bytes=" + str(max_size_bytes))
		self.__max_size_bytes__ = max_size_bytes
		if self.__record__:
			self.set_record(False)
			self.set_record(True)
		logging.debug(function_name + ": exit")


	def set_max_size_time(self, max_size_time):

		"""
		Set maximum size of the recorded video file in nanoseconds

		Args:
			max_size_time (int): maximum size of the recorded video file in
				nanoseconds
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": max_size_time=" + str(max_size_time))
		self.__max_size_time__ = max_size_time
		if self.__record__:
			self.set_record(False)
			self.set_record(True)
		logging.debug(function_name + ": exit")


	def set_persistent(self, persistent):

		"""
		Set configuration persistence

		Args:
			persistent (bool): True if configuration shall be persistent,
				False otherwise
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": persistent=" + str(persistent))
		self.__persistent__ = persistent
		logging.debug(function_name + ": exit")


	def set_continuation(self, continuation):

		"""
		Set configuration continuation

		Args:
			continuation (bool): True if recording shall continuation from last
			    fragment id, False otherwise
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": continuation=" + str(continuation))
		self.__continuation__ = continuation
		logging.debug(function_name + ": exit")


	def set_logging_level(self, logging_level):

		"""
		Set logging level

		Args:
			logging_level (int): logging level
		"""	

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": logging_level=" + str(logging_level))
		self.__logging_level__ = logging_level
		root = logging.getLogger()
		for h in root.handlers[:]:
			root.removeHandler(h)
			h.close()
		if self.__default_logging_level__ != 0:
			if self.__logging_level__ == 0:
				Gst.debug_set_active(False)
				logging.basicConfig(
					format="%(asctime)s %(levelname)s: %(message)s",
					level=self.__default_logging_level__)
			else:
				Gst.debug_set_colored(False)
				Gst.debug_set_default_threshold(
					(50-self.__logging_level__+10)/10)
				#Gst.debug_set_threshold_for_name("videorate", (50-self.__logging_level__+10)/10+1)
				Gst.debug_set_active(True)
				logging.basicConfig(
					format="%(asctime)s %(levelname)s: %(message)s",
					level=self.__logging_level__)
		logging.debug(function_name + ": exit")



class Servers(object):

	"""
	Servers
	"""

	def __init__(self, servers):

		"""
		Initialize servers

		Args:
			servers (list): list of servers
		"""

		self.__servers__ = servers
		self.__threads__ = []


	def start(self):

		"""
		Starts servers
		"""

		for server in self.__servers__:
			thread = threading.Thread(
				name=name(server) + ' Thread', target=server.start, args=())
			thread.deamon = True
			thread.start()
			self.__threads__.append(thread)


	def stop(self):

		"""
		Stop servers
		"""

		for server in self.__servers__:
			server.stop()
		for thread in self.__threads__:
			thread.join()


class CameraService:
	
	"""
		Camera Handler
	"""

	def __init__(self):

		"""
		Initialize Camera Service
		"""

		signal.signal(signal.SIGTERM, self.stop)
		#signal.signal(signal.SIGKILL, self.stop)
		self.__running__ = False


	def get_parser(self):

		"""
		Parse input arguments

		Returns:
			parser (ArgumentParser): argument parser
		"""

		# NOTE(marcin.sielski): Do not put here logging statements.
		parser = ArgumentParser()
		parser.add_argument(
			'-d', '--debug', type=str, nargs='?', const='DEBUG', default='INFO',
			help="enable debug level (DEBUG by default): NOTSET, DEBUG, INFO, "
			"WARNING, ERROR, CRITICAL")
		parser.add_argument(
			'-c', '--camera_timeout', type=int, nargs='?', const=7500,
			default=0, help="set camera timeout (Infinite by default)")
		# NOTE(marcin.sielski): Magic number 1 MiB/s depends on underlying
		# hardware capabilities and was estimated experimentally for
		# SanDisk Extreme 64 GB and overclocked SD Host Controller.
		parser.add_argument(
			'-t', '--throughput', type=int, nargs='?', const=1, default=1,
			help="set camera timeout (1 MiB by default)")
		return parser


	def start(self, args):

		"""
		Start servers
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		logging.info(name(self) + " started")
		Gst.init(None)
		camera_server = CameraServer(args)
		self.__servers__ = Servers(
			[HTTPSServer(camera_server), camera_server, 
			RTSPServer(camera_server)])
		self.__servers__.start()
		self.__running__ = True
		logging.debug(function_name + ": exit")


	def stop(self, signum=None, frame=None):

		"""
		Stop servers
		"""

		function_name = "'" + threading.currentThread().name + "'." + \
			type(self).__name__ + '.' + inspect.currentframe().f_code.co_name
		logging.debug(function_name + ": entry")
		if self.__running__:
			self.__running__ = False
			self.__servers__.stop()
		logging.info(name(self) + " stopped")		
		logging.debug(function_name + ": exit")
	

if __name__ == '__main__':

	"""
	Camera Service entry method
	"""

	camera_service = CameraService()

	args = camera_service.get_parser().parse_args()
	
	if getattr(logging, args.debug.upper()):
		logging.basicConfig(
			format="%(asctime)s %(levelname)s: %(message)s",
			level=getattr(logging, args.debug.upper()))

	try:
		with picamera.PiCamera() as camera:
			logging.info("'" + camera.revision + "' camera detected")
	except:
		if camera_revision() != "ov9281":
			logging.critical("Unable to acquire camera")
			exit(-1)

	camera_service.start(args)

	try:
		pause()
	except KeyboardInterrupt:
		pass
		
	camera_service.stop()
	
