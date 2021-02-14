/*******************************************************************************
MIT License

Copyright (c) 2021 Marcin Sielski <marcin.sielski@gmail.com>

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
*******************************************************************************/
// We make use of this 'server' variable to provide the address of the
// REST Janus API. By default, in this example we assume that Janus is
// co-located with the web server hosting the HTML pages but listening
// on a different port (8088, the default for HTTP in Janus), which is
// why we make use of the 'window.location.hostname' base address. Since
// Janus can also do HTTPS, and considering we don't really want to make
// use of HTTP for Janus if your demos are served on HTTPS, we also rely
// on the 'window.location.protocol' prefix to build the variable, in
// particular to also change the port used to contact Janus (8088 for
// HTTP and 8089 for HTTPS, if enabled).
// In case you place Janus behind an Apache frontend (as we did on the
// online demos at http://janus.conf.meetecho.com) you can just use a
// relative path for the variable, e.g.:
//
// 		var server = "/janus";
//
// which will take care of this on its own.
//
//
// If you want to use the WebSockets frontend to Janus, instead, you'll
// have to pass a different kind of address, e.g.:
//
// 		var server = "ws://" + window.location.hostname + ":8188";
//
// Of course this assumes that support for WebSockets has been built in
// when compiling the server. WebSockets support has not been tested
// as much as the REST API, so handle with care!
//
//
// If you have multiple options available, and want to let the library
// autodetect the best way to contact your server (or pool of servers),
// you can also pass an array of servers, e.g., to provide alternative
// means of access (e.g., try WebSockets first and, if that fails, fall
// back to plain HTTP) or just have failover servers:
//
//		var server = [
//			"ws://" + window.location.hostname + ":8188",
//			"/janus"
//		];
//
// This will tell the library to try connecting to each of the servers
// in the presented order. The first working server will be used for
// the whole session.
//
'use strict';
var server = null;
if(window.location.protocol === 'http:')
	server = "http://" + window.location.hostname + ":8088/janus";
else
	server = "https://" + window.location.hostname + ":8089/janus";

var janus = null;
var streaming = null;
var opaqueId = "camera-"+Janus.randomString(12);

var bitrateTimer = null;

var started = false;

var selectedStream = null;

var zoom = 0;

var sensor_mode = ['0','5','6','1','7']

$(document).ready(function() {
	selectedStream=314
	// Initialize the library (all console debuggers enabled)
	Janus.init({debug: "all", callback: function() {
		// Use a button to start the demo
		if(started)
			return;
		started = true;
		$(this).attr('disabled', true).unbind('click');
		// Make sure the browser supports WebRTC
		if(!Janus.isWebrtcSupported()) {
			bootbox.alert("No WebRTC support... ");
			return;
		}
		// Create session
		janus = new Janus(
			{
				server: server,
				success: function() {
					// Attach to Streaming plugin
					janus.attach(
						{
							plugin: "janus.plugin.streaming",
							opaqueId: opaqueId,
							success: function(pluginHandle) {
								$('#details').remove();
								streaming = pluginHandle;
								Janus.log(
									"Plugin attached! (" + streaming.getPlugin()
									+ ", id=" + streaming.getId() + ")");
								// Setup streaming session
								$('#update-streams').click(updateStreamsList);
								updateStreamsList();
								startStream()
							},
							error: function(error) {
								Janus.error(
									"  -- Error attaching plugin... ", error);
								bootbox.alert(
									"Error attaching plugin... " + error);
							},
							iceState: function(state) {
								Janus.log("ICE state changed to " + state);
								if (state == "disconnected") {
									window.location.reload();
								}
							},
							webrtcState: function(on) {
								Janus.log(
									"Janus says our WebRTC PeerConnection is " +
									(on ? "up" : "down") + " now");
							},
							onmessage: function(msg, jsep) {
								Janus.debug(" ::: Got a message :::", msg);
								var result = msg["result"];
								if(result) {
									if(result["status"]) {
										var status = result["status"];
										if(status === 'starting')
											$('#status').removeClass('hide')
											.text("Starting, please wait...")
											.show();
										else if(status === 'started')
											$('#status').removeClass('hide')
											.text("Started")
											.show();
										else if(status === 'stopped')
											stopStream();
									} 
								} else if(msg["error"]) {
									bootbox.alert(msg["error"]);
									stopStream();
									return;
								}
								if(jsep) {
									Janus.debug(
										"Handling SDP as well...", jsep);
									var stereo = 
									(jsep.sdp.indexOf("stereo=1") !== -1);
									// Offer from the plugin, let's answer
									streaming.createAnswer(
										{
											jsep: jsep,
											// We want recvonly audio/video and,
											// if negotiated, datachannels
											media: { 
												audioSend: false, 
												videoSend: false, 
												data: true 
											},
											customizeSdp: function(jsep) {
												if(
													stereo && 
													jsep.sdp.indexOf('stereo=1')
													 == -1) {
													// Make sure that our offer 
													// contains stereo too
													jsep.sdp = 
													jsep.sdp.replace(
														'useinbandfec=1',
														'useinbandfec=1;'+
														'stereo=1');
												}
											},
											success: function(jsep) {
												Janus.debug("Got SDP!", jsep);
												var body = { request: 'start' };
												streaming.send({ 
													message: body, 
													jsep: jsep 
												});
											},
											error: function(error) {
												Janus.error(
													"WebRTC error:", error);
												window.location.reload();
											}
										});
								}
							},
							onremotestream: function(stream) {
								Janus.debug(
									" ::: Got a remote stream :::", stream);
								var addButtons = false;
								if($('#remotevideo').length === 0) {
									addButtons = true;
									$('#waitingvideo').remove();
									if(this.videoWidth)
										$('#remotevideo')
										.removeClass('hide').show();
									$('#stream').append(
										'<video class="hide" id="remotevideo"' +
										' width="100%" playsinline autoplay ' +
										'muted/>');
									// Show the stream and hide the spinner when
									// we get a playing event
									$("#remotevideo")
									.bind("playing", function () {
										fetch("https://" + 
										window.location.hostname + ":8888")
											.then(response => response.json())
											.then(data => {
												Janus.log(data)
												display(data)													
											})
											.catch(
												error => console.error(error))
										var videoTracks = 
										stream.getVideoTracks();
										if(!videoTracks || 
											videoTracks.length === 0)
											return;
										var width = this.videoWidth;
										var height = this.videoHeight;
										$('#curres').removeClass('hide')
										.text(width+'x'+height).show();
										if(Janus.webRTCAdapter.browserDetails
											.browser === "firefox") {
											// Firefox Stable has a bug: width 
											// and height are not immediately 
											// available after a playing
											setTimeout(function() {
												var width = $("#remotevideo")
												.get(0).videoWidth;
												var height = $("#remotevideo")
												.get(0).videoHeight;
												$('#curres').removeClass('hide')
												.text(width+'x'+height).show();
											}, 2000);
										}
									});
								}
								Janus.attachMediaStream(
									$('#remotevideo').get(0), stream);
								var videoTracks = stream.getVideoTracks();
								if(!videoTracks || videoTracks.length === 0) {
									// No remote video
									$('#remotevideo').hide();
									if($('#no-video-container').length === 0) {
										$('#stream').append(
											'<div id="no-video-container" ' +
											'style="text-align: center; ' +
											'font-size: 50vmin">' +
											'<i class="fas fa-video-slash">' +
											'</i>' +
											'</div>');
										$('#model').addClass('hide').hide()
										$('#curres').addClass('hide').hide()
										$('#zoom_button').addClass('hide')
										.hide()
										$('#zoom_in_button').addClass('hide')
										.hide()
										$('#zoom_out_button').addClass('hide')
										.hide()
										$('#sensor_mode_button')
										.addClass('hide').hide()
										$('#sensor_mode').addClass('hide')
										.hide()
										$('#framerate').addClass('hide').hide()
										$('#resolution').addClass('hide').hide()
										$('#framerate_button').addClass('hide')
										.hide()
										$('#resolution_button').addClass('hide')
										.hide()
									}
								} else {
									$('#no-video-container').remove();
									$('#remotevideo').removeClass('hide')
									.show();
								}
								if(!addButtons)
									return;
								if(videoTracks && videoTracks.length &&
									(Janus.webRTCAdapter.browserDetails
										.browser === "chrome" ||
									Janus.webRTCAdapter.browserDetails
									.browser === "firefox" ||
									Janus.webRTCAdapter.browserDetails
									.browser === "safari")) {
									$('#curbitrate').removeClass('hide').show();
									bitrateTimer = setInterval(function() {
										// Display updated bitrate, if supported
										var bitrate = streaming.getBitrate();
										$('#curbitrate').text(bitrate
											.replace('kbits/sec', 'Kbps'));
										// Check if the resolution changed too
										var width = $("#remotevideo").get(0)
										.videoWidth;
										var height = $("#remotevideo").get(0)
										.videoHeight;
										if(width > 0 && height > 0)
											$('#curres').removeClass('hide')
											.text(width+'x'+height).show();
									}, 1000);
								}
							},
							oncleanup: function() {
								Janus.log(
									" ::: Got a cleanup notification :::");
								$('#waitingvideo').remove();
								$('#remotevideo').remove();
								$('#no-video-container').remove();
								$('#bitrate').attr('disabled', true);
								$('#curbitrate').hide();
								if(bitrateTimer)
									clearInterval(bitrateTimer);
								bitrateTimer = null;
								$('#curres').hide();
								$('#metadata').empty();
								$('#info').addClass('hide').hide();
							},
							slowLink: function(uplink, lost) {
								Janus.log(
									" ::: Got a slowLink notification :::")
								if (lost > 500 && 
									parseInt($('#bitrate').val()) > 1000000) {
									$('#bitrate').val(String(
										parseInt($('#bitrate').val())) -
										1000000)
									change('bitrate')
								}
							}
						});
				},
				error: function(error) {
					Janus.error(error);
					bootbox.alert(error, function() {
						window.location.reload();
					});
				},
				destroyed: function() {
					window.location.reload();
				}
			});
	}});
});

function updateStreamsList() {
	$('#update-streams').unbind('click').addClass('fa-spin');
	var body = { request: "list" };
	Janus.debug("Sending message:", body);
	streaming.send({ message: body, success: function(result) {
		if(!result) {
			bootbox.alert("Got no response to our query for available streams");
			return;
		}
		if(result["list"]) {
			$('#streams').removeClass('hide').show();
			var list = result["list"];
			Janus.log("Got a list of available streams");
			Janus.debug(list);
			for(var mp in list) {
				Janus.debug("  >> [" + list[mp]["id"] + "] " + 
				list[mp]["description"] + " (" + list[mp]["type"] + ")");
			}
		}
	}});
}

function getStreamInfo() {
	$('#metadata').empty();
	$('#info').addClass('hide').hide();
	if(!selectedStream)
		return;
	// Send a request for more info on the mountpoint we subscribed to
	var body = { 
		request: "info", 
		id: parseInt(selectedStream) || selectedStream 
	};
	streaming.send({ message: body, success: function(result) {
		if(result && result.info && result.info.metadata) {
			$('#metadata').html(result.info.metadata);
			$('#info').removeClass('hide').show();
		}
	}});
}

function startStream() {
	Janus.log("Selected video id #" + selectedStream);
	if(!selectedStream) {
		bootbox.alert("Select a stream from the list");
		return;
	}
	var body = { 
		request: "watch", 
		id: parseInt(selectedStream) || selectedStream
	};
	streaming.send({ message: body });
	// No remote video yet
	$('#stream').append('<video id="waitingvideo" width="100%"/>');
	// Get some more info for the mountpoint to display, if any
	getStreamInfo();
}

function stopStream() {
	var body = { request: "stop" };
	streaming.send({ message: body });
	streaming.hangup();
	$('#status').empty().hide();
	$('#bitrate').attr('disabled', true);
	$('#curbitrate').hide();
	if(bitrateTimer)
		clearInterval(bitrateTimer);
	bitrateTimer = null;
	$('#curres').empty().hide();
}

function display(data) {
	$('#model').removeClass('hide').text(data.model).show()

	// Quality

	$('#resolution').val(data.width+'x'+data.height)
	switch(parseInt(data.sensor_mode)) {
		case 0: // auto
			$('#framerate').html(' \
				<option value="60">60</option> \
				<option value="55">55</option> \
				<option value="50">50</option> \
				<option value="45">45</option> \
				<option value="40">40</option> \
				<option value="35">35</option> \
				<option value="30">30</option> \
				<option value="25">25</option> \
				<option value="20">20</option> \
				<option value="15">15</option> \
				<option value="10">10</option> \
				<option value="5">&nbsp;&nbsp;5</option> \
			')
			$('#hd').removeClass('hide').show() // 1280x720 16:9
			$('#xga').removeClass('hide').show() // 1024x768 4:3
			$('#qhd').removeClass('hide').show() // 960x544 16:9
			$('#svga').removeClass('hide').show() // 800x608 4:3
			$('#wvga').removeClass('hide').show() // 800x448 16:9
			$('#vga').removeClass('hide').show() // 640x480 4:3					
			break
		case 1: // 1920x1080 16:9 0.1-30fps partial
			$('#framerate').html(' \
				<option value="30">30</option> \
				<option value="29">29</option> \
				<option value="28">28</option> \
				<option value="27">27</option> \
				<option value="26">26</option> \
				<option value="25">25</option> \
				<option value="24">24</option> \
				<option value="23">23</option> \
				<option value="22">22</option> \
				<option value="21">21</option> \
				<option value="20">20</option> \
				<option value="19">19</option> \
				<option value="18">18</option> \
				<option value="17">17</option> \
				<option value="16">16</option> \
				<option value="15">15</option> \
				<option value="14">14</option> \
				<option value="13">13</option> \
				<option value="12">12</option> \
				<option value="11">11</option> \
				<option value="10">10</option> \
				<option value="9">&nbsp;&nbsp;9</option> \
				<option value="8">&nbsp;&nbsp;8</option> \
				<option value="7">&nbsp;&nbsp;7</option> \
				<option value="6">&nbsp;&nbsp;6</option> \
				<option value="5">&nbsp;&nbsp;5</option> \
				<option value="4">&nbsp;&nbsp;4</option> \
				<option value="3">&nbsp;&nbsp;3</option> \
				<option value="2">&nbsp;&nbsp;2</option> \
				<option value="1">&nbsp;&nbsp;1</option> \
			')
			$('#hd').removeClass('hide').show() // 1280x720 16:9
			$('#xga').addClass('hide').hide() // 1024x768 4:3
			$('#qhd').removeClass('hide').show() // 960x544 16:9
			$('#svga').addClass('hide').hide() // 800x608 4:3
			$('#wvga').removeClass('hide').show() // 800x448 16:9
			$('#vga').addClass('hide').hide() // 640x480 4:3
			break
		case 2: // 3280x2464 4:3 0.1-15fps full
		case 3: // 3280x2464 4:3 0.1-15fps full
			$('#framerate').html(' \
				<option value="15">15</option> \
				<option value="14">14</option> \
				<option value="13">13</option> \
				<option value="12">12</option> \
				<option value="11">11</option> \
				<option value="10">10</option> \
				<option value="9">&nbsp;&nbsp;9</option> \
				<option value="8">&nbsp;&nbsp;8</option> \
				<option value="7">&nbsp;&nbsp;7</option> \
				<option value="6">&nbsp;&nbsp;6</option> \
				<option value="5">&nbsp;&nbsp;5</option> \
				<option value="4">&nbsp;&nbsp;4</option> \
				<option value="3">&nbsp;&nbsp;3</option> \
				<option value="2">&nbsp;&nbsp;2</option> \
				<option value="1">&nbsp;&nbsp;1</option> \
			')
			$('#hd').addClass('hide').hide() // 1280x720 16:9
			$('#xga').removeClass('hide').show() // 1024x768 4:3
			$('#qhd').addClass('hide').hide() // 960x544 16:9
			$('#svga').removeClass('hide').show() // 800x608 4:3
			$('#wvga').addClass('hide').hide() // 800x448 16:9
			$('#vga').removeClass('hide').show() // 640x480 4:3					
			break
		case 4: // 1640x1232 4:3 0.1-40fps full
			$('#framerate').html(' \
				<option value="40">40</option> \
				<option value="39">39</option> \
				<option value="38">38</option> \
				<option value="37">37</option> \
				<option value="36">36</option> \
				<option value="35">35</option> \
				<option value="34">34</option> \
				<option value="33">33</option> \
				<option value="32">32</option> \
				<option value="31">31</option> \
				<option value="30">30</option> \
				<option value="29">29</option> \
				<option value="28">28</option> \
				<option value="27">27</option> \
				<option value="26">26</option> \
				<option value="25">25</option> \
				<option value="24">24</option> \
				<option value="23">23</option> \
				<option value="22">22</option> \
				<option value="21">21</option> \
				<option value="20">20</option> \
				<option value="19">19</option> \
				<option value="18">18</option> \
				<option value="17">17</option> \
				<option value="16">16</option> \
				<option value="15">15</option> \
				<option value="14">14</option> \
				<option value="13">13</option> \
				<option value="12">12</option> \
				<option value="11">11</option> \
				<option value="10">10</option> \
				<option value="9">&nbsp;&nbsp;9</option> \
				<option value="8">&nbsp;&nbsp;8</option> \
				<option value="7">&nbsp;&nbsp;7</option> \
				<option value="6">&nbsp;&nbsp;6</option> \
				<option value="5">&nbsp;&nbsp;5</option> \
				<option value="4">&nbsp;&nbsp;4</option> \
				<option value="3">&nbsp;&nbsp;3</option> \
				<option value="2">&nbsp;&nbsp;2</option> \
				<option value="1">&nbsp;&nbsp;1</option> \
			')
			$('#hd').addClass('hide').hide() // 1280x720 16:9
			$('#xga').removeClass('hide').show() // 1024x768 4:3
			$('#qhd').addClass('hide').hide() // 960x544 16:9
			$('#svga').removeClass('hide').show() // 800x608 4:3
			$('#wvga').addClass('hide').hide() // 800x448 16:9
			$('#vga').removeClass('hide').show() // 640x480 4:3
			break
		case 5: // 1640x922 16:9 0.1-40fps partial
			$('#framerate').html(' \
				<option value="40">40</option> \
				<option value="39">39</option> \
				<option value="38">38</option> \
				<option value="37">37</option> \
				<option value="36">36</option> \
				<option value="35">35</option> \
				<option value="34">34</option> \
				<option value="33">33</option> \
				<option value="32">32</option> \
				<option value="31">31</option> \
				<option value="30">30</option> \
				<option value="29">29</option> \
				<option value="28">28</option> \
				<option value="27">27</option> \
				<option value="26">26</option> \
				<option value="25">25</option> \
				<option value="24">24</option> \
				<option value="23">23</option> \
				<option value="22">22</option> \
				<option value="21">21</option> \
				<option value="20">20</option> \
				<option value="19">19</option> \
				<option value="18">18</option> \
				<option value="17">17</option> \
				<option value="16">16</option> \
				<option value="15">15</option> \
				<option value="14">14</option> \
				<option value="13">13</option> \
				<option value="12">12</option> \
				<option value="11">11</option> \
				<option value="10">10</option> \
				<option value="9">&nbsp;&nbsp;9</option> \
				<option value="8">&nbsp;&nbsp;8</option> \
				<option value="7">&nbsp;&nbsp;7</option> \
				<option value="6">&nbsp;&nbsp;6</option> \
				<option value="5">&nbsp;&nbsp;5</option> \
				<option value="4">&nbsp;&nbsp;4</option> \
				<option value="3">&nbsp;&nbsp;3</option> \
				<option value="2">&nbsp;&nbsp;2</option> \
				<option value="1">&nbsp;&nbsp;1</option> \
			')
			$('#hd').removeClass('hide').show() // 1280x720 16:9
			$('#xga').addClass('hide').hide() // 1024x768 4:3
			$('#qhd').removeClass('hide').show() // 960x544 16:9
			$('#svga').addClass('hide').hide() // 800x608 4:3
			$('#wvga').removeClass('hide').show() // 800x448 16:9
			$('#vga').addClass('hide').hide() // 640x480 4:3
			break
		case 6: // 1280x720 16:9 40-90fps partial
			if ($('#resolution').val() == '1280x720') {
				$('#framerate').html(' \
					<option value="60">60</option> \
					<option value="55">55</option> \
					<option value="50">50</option> \
					<option value="45">45</option> \
					<option value="40">40</option> \
				')
			} else {
				$('#framerate').html(' \
					<option value="90">90</option> \
					<option value="85">85</option> \
					<option value="80">80</option> \
					<option value="75">75</option> \
					<option value="70">70</option> \
					<option value="65">65</option> \
					<option value="60">60</option> \
					<option value="55">55</option> \
					<option value="50">50</option> \
					<option value="45">45</option> \
					<option value="40">40</option> \
				')
			}
			$('#hd').removeClass('hide').show() // 1280x720 16:9
			$('#xga').addClass('hide').hide() // 1024x768 4:3
			$('#qhd').removeClass('hide').show() // 960x544 16:9
			$('#svga').addClass('hide').hide() // 800x608 4:3
			$('#wvga').removeClass('hide').show() // 800x448 16:9
			$('#vga').addClass('hide').hide() // 640x480 4:3
			break
		case 7: // 640x480 4:3 40-200fps partial
			$('#framerate').html(' \
				<option value="200">200</option> \
				<option value="190">190</option> \
				<option value="180">180</option> \
				<option value="170">170</option> \
				<option value="160">160</option> \
				<option value="150">150</option> \
				<option value="140">140</option> \
				<option value="130">130</option> \
				<option value="120">120</option> \
				<option value="110">110</option> \
				<option value="100">100</option> \
				<option value="90">&nbsp;&nbsp;90</option> \
				<option value="80">&nbsp;&nbsp;80</option> \
				<option value="70">&nbsp;&nbsp;70</option> \
				<option value="60">&nbsp;&nbsp;60</option> \
				<option value="50">&nbsp;&nbsp;50</option> \
				<option value="40">&nbsp;&nbsp;40</option> \
			')
			$('#hd').addClass('hide').hide() // 1280x720 16:9
			$('#xga').addClass('hide').hide() // 1024x768 4:3
			$('#qhd').addClass('hide').hide() // 960x544 16:9
			$('#svga').addClass('hide').hide() // 800x608 4:3
			$('#wvga').addClass('hide').hide() // 800x448 16:9
			$('#vga').removeClass('hide').show() // 640x480 4:3
			break
	}
	$('#framerate').val(data.framerate)
	$('#framerate_button').removeClass('hide').show()
	$('#framerate').removeClass('hide').show()
	$('#resolution_button').removeClass('hide').show()
	$('#resolution').removeClass('hide').show()

	$('#bitrate').val(data.bitrate)
	$('#sensor_mode').val(data.sensor_mode)
	if (data.sensor_mode == '0' || data.sensor_mode == '2' ||
		data.sensor_mode == '3' || data.sensor_mode == '4') {
		zoom = 0
	}
	if (data.sensor_mode == '1') {
		zoom = 3
	}
	if (data.sensor_mode == '5') {
		zoom = 1
	}
	if (data.sensor_mode == '6') {
		zoom = 2
	}
	if (data.sensor_mode == '7') {
		zoom = 4
	}
	$('#zoom_button').removeClass('hide').show()
	$('#zoom_in_button').removeClass('hide').show()
	if (zoom == sensor_mode.length - 1) {
		$('#zoom_in_button').attr('disabled', true)
	} else if (zoom >= 0) {
		$('#zoom_in_button').attr('disabled', false)
	}
	$('#zoom_out_button').removeClass('hide').show()
	if (zoom == 0) {
		$('#zoom_out_button').attr('disabled', true)
	} else if (zoom <= sensor_mode.length - 1) {
		$('#zoom_out_button').attr('disabled', false)
	}
	$('#sensor_mode_button').removeClass('hide').show()
	$('#sensor_mode').removeClass('hide').show()
	if (data.model == 'ov5647') {
		$('#sensor_mode_0').text("auto")
		$('#sensor_mode_1').text("1920x1080 16:9   0.1-30fps partial")
		$('#sensor_mode_2').text("2592x1944  4:3   0.1-15fps full")
		$('#sensor_mode_3').text("2592x1944  4:3 0.1666-1fps full")
		$('#sensor_mode_4').text(" 1296x972  4:3     1-42fps full")
		$('#sensor_mode_5').text(" 1296x730 16:9     1-49fps full")
		$('#sensor_mode_6').text("  640x480  4:3  42.1-60fps full")
		$('#sensor_mode_7').text("  640x480  4:3  60.1-90fps full")														
	}
	if (data.model == 'imx219') {
		$('#sensor_mode_0').text("auto")
		$('#sensor_mode_1').text("1920x1080 16:9 0.1-30fps partial")
		$('#sensor_mode_2').text("3280x2464  4:3 0.1-15fps full")
		$('#sensor_mode_3').text("3280x2464  4:3 0.1-15fps full")
		$('#sensor_mode_4').text("1640x1232  4:3 0.1-40fps full")
		$('#sensor_mode_5').text(" 1640x922 16:9 0.1-40fps partial")
		$('#sensor_mode_6').text(" 1280x720 16:9  40-90fps partial")
		$('#sensor_mode_7').text("  640x480  4:3 40-200fps partial")
	}

	// Effects

	$('#brightness').val(data.brightness)
	$('#contrast').val(data.contrast)
	$('#saturation').val(data.saturation)
	$('#sharpness').val(data.sharpness)
	$('#drc').val(data.drc)
	$('#image_effect').val(data.image_effect)
	$('#awb_mode').val(data.awb_mode)
	$('#awb_gain_blue').val(data.awb_gain_blue)
	$('#awb_gain_red').val(data.awb_gain_red)

	// Settings

	$('#exposure_mode').val(data.exposure_mode)
	$('#metering_mode').val(data.metering_mode)
	$('#exposure_compensation').val(data.exposure_compensation)
	$('#iso').val(data.iso)
	$('#shutter_speed').val(data.shutter_speed)
	$('#video_stabilisation').val(data.video_stabilisation)
	if (data.video_stabilisation == '0') {
		$('#video_stabilisation').removeClass('active')
	} else {
		$('#video_stabilisation').addClass('active')
	}
	

	// Orientation

	$('#rotation').val(data.rotation)
	$('#hflip').val(data.hflip)
	if (data.hflip == '0') {
		$('#hflip').removeClass('active')
	} else {
		$('#hflip').addClass('active')
	}
	$('#vflip').val(data.vflip)
	if (data.vflip == '0') {
		$('#vflip').removeClass('active')
	} else {
		$('#vflip').addClass('active')
	}
	$('#video_direction').val(data.video_direction)

	// Controls

	$('#stats').val(data.stats)
	if (data.stats == '0x00000000') {
		$('#stats').removeClass('active')
	} else {
		$('#stats').addClass('active')
	}
	$('#rtsp').val(data.rtsp)
	if (data.rtsp == '0') {
		$('#rtsp').removeClass('active')
	} else {
		$('#rtsp').addClass('active')
	}
	$('#record').val(data.record)
	if (data.record == '0') {
		$('#record').removeClass('active')
	} else {
		$('#record').addClass('active')
	}
	$('#format').val(data.format)
	if (data.format == '0') {
		$('#format').html('<i class="fas fa-file-video"></i>')
	} else {
		$('#format').html('<i class="fas fa-file"></i>')
	}
	$('#max_files').val(data.max_files)
	$('#max_size_bytes').val(data.max_size_bytes)
	$('#max_size_time').val(data.max_size_time)
	$('#persistent').val(data.persistent)
	if (data.persistent == '0') {
		$('#persistent').removeClass('active')
	} else {
		$('#persistent').addClass('active')
	}
}

function change(parameter) {
	let url = 'https://' + window.location.hostname + ':8888'
	switch(parameter) {
		case 'resolution':
			let value = $('#resolution').val()
			let width = value.split('x')[0];
			let height = value.split('x')[1];
			url = url.concat('/?width=' + width + '&height=' + height)
			break
		case 'restart':
			url = url.concat('/?' + parameter)
			break
		case 'video_stabilisation':
		case 'hflip':
		case 'vflip':
		case 'rtsp':
		case 'record':
		case 'persistent':
			if ($('#'+parameter).val() == '0') {
				$('#'+parameter).val('1')
				$('#'+parameter).addClass('active')
			} else {
				$('#'+parameter).val('0')
				$('#'+parameter).removeClass('active')
			}
			url = url.concat('/?' + parameter + '=' + $('#'+parameter).val())
			break	
		case 'format':
			if ($('#format').val() == '0') {
				$('#format').val('1')
				$('#format').html('<i class="fas fa-file"></i>')
			} else {
				$('#format').val('0')
				$('#format').html('<i class="fas fa-file-video"></i>')
			}
			url = url.concat('/?format=' + $('#format').val())
			break
		case 'stats':
			if ($('#'+parameter).val() == '0x00000000') {
				$('#'+parameter).val('0x0000065d')
				$('#'+parameter).addClass('active')
			} else {
				$('#'+parameter).val('0x00000000')
				$('#'+parameter).removeClass('active')
			}
			url = url.concat('/?' + parameter + '=' + $('#'+parameter).val())
			break
		default:
			url = url.concat('/?' + parameter + '=' + $('#'+parameter).val())
			break
	}
	fetch(url).then(response => response.json())
		.then(data => {
			Janus.log(data)
			display(data)
		})
		.catch(error => Janus.error(error));
}

function zoom_in() {
	if (zoom < sensor_mode.length - 1) {
		zoom = zoom + 1
		$('#sensor_mode').val(sensor_mode[zoom])
		change('sensor_mode')
	} 	
}

function zoom_out() {
	if (zoom > 0) {
		zoom = zoom - 1
		$('#sensor_mode').val(sensor_mode[zoom])
		change('sensor_mode')
	} 
}

function collapse() {
	$('#collapseOne').collapse('hide')
	$('#collapseTwo').collapse('hide')
	$('#collapseThree').collapse('hide')
	$('#collapseFour').collapse('hide')
	$('#collapseFive').collapse('hide')
}
