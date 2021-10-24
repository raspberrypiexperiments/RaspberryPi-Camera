# MIT License
#
# Copyright (c) 2021 Marcin Sielski <marcin.sielski@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

dependencies:
	sudo apt update
	sudo apt upgrade -y
	#sudo apt install -y python3-netifaces
	sudo apt install npm -y
	sudo npm -g install n
	sudo n lts
	sudo npm i uglify-js -g
	pip3 install --user falcon
	pip3 install --user wsgiserver

config:
	sudo sysctl -w net.core.rmem_max=1342177280
	sudo sysctl -w net.core.wmem_max=516777216
	sudo sysctl -w net.core.rmem_default=10000000
	sudo sysctl -w net.core.wmem_default=10000000
	sudo sysctl -w net.core.netdev_max_backlog=416384
	sudo sysctl -w net.core.optmem_max=524288 
	sudo sysctl -w net.ipv4.udp_mem="11416320 15221760 22832640"
	sudo sysctl -w net.core.netdev_budget=1024
	sudo sysctl -p

install: dependencies config
	if ! patch -R -d /home/$$USER/.local -p1 -s -f --dry-run < src/0002_wsgiserver.py.patch; then patch -d /home/$$USER/.local -p1 < src/0002_wsgiserver.py.patch; fi
	rm -rf httpsserver.js
	wget https://gist.githubusercontent.com/bencentra/909830fb705d5892b9324cffbca3926f/raw/a80edf0fdf0f38e4a43210e6438cbe511acc21a7/server.js -O httpsserver.js
	sudo mkdir -p /opt/camera/bin
	sudo mv httpsserver.js /opt/camera/bin
	cd /opt/camera/bin && sudo npm install express
	sudo openssl req -x509 -newkey rsa:4096 -config src/cert.cfg -keyout /opt/camera/bin/key.pem -out /opt/camera/bin/cert.pem -days 365 -nodes
	sudo chown $$USER:$$USER /opt/camera/bin/key.pem
	sudo chown $$USER:$$USER /opt/camera/bin/cert.pem
	sudo cp src/httpsserver.service /etc/systemd/system
	sudo systemctl enable httpsserver.service
	sudo systemctl start httpsserver.service
	sleep 3
	sudo systemctl status httpsserver.service
	sudo rm -rf /opt/camera/share/camera
	sudo mkdir -p /opt/camera/share/camera
	sudo bash -c "uglifyjs /opt/janus/share/janus/demos/janus.js > /opt/camera/share/camera/janus.min.js"
	sudo cp src/index.html /opt/camera/share/camera
	sudo cp src/camera.css /opt/camera/share/camera
	sudo cp src/camera.js /opt/camera/share/camera
	sudo cp src/favicon.ico /opt/camera/share/camera
	cd /opt/camera/share/camera && sudo npm i webrtc-adapter
	cd /opt/camera/share/camera && sudo npm i jquery
	cd /opt/camera/share/camera && sudo npm i bootstrap
	cd /opt/camera/share/camera && sudo npm i bootbox
	cd /opt/camera/share/camera && sudo npm i @fortawesome/fontawesome-free
	sudo bash -c "uglifyjs /opt/camera/share/camera/node_modules/webrtc-adapter/out/adapter.js > /opt/camera/share/camera/node_modules/webrtc-adapter/out/adapter.min.js"
	if ! patch -R -d / -p1 -s -f --dry-run <src/0001_janus.plugin.streaming.jcfg.patch; then sudo patch -d / -p1 < src/0001_janus.plugin.streaming.jcfg.patch; fi
	sudo systemctl restart janus.service
	sleep 3
	sudo systemctl status janus.service
	sudo cp src/camera.py /opt/camera/bin
	mkdir -p /home/pi/camera
	sudo cp src/camera.service /etc/systemd/system
	sudo ln -s /home/pi/camera /opt/camera/share/camera/media
	sudo systemctl enable camera.service
	if [ `raspi-config nonint get_camera` -eq 1 ]; then sudo raspi-config nonint do_camera 0; sudo reboot; fi
	sudo systemctl start camera.service
	sleep 3
	sudo systemctl status camera.service

uninstall:
	sudo systemctl daemon-reload
	sudo systemctl stop httpsserver.service
	sudo systemctl disable httpsserver.service || true
	sudo rm -rf /etc/systemd/system/httpsserver.service
	sudo systemctl stop camera.service
	sudo systemctl disable camera.service || true
	sudo rm -rf /etc/systemd/system/camera.service
	sudo rm -rf /opt/camera
	sudo rm -rf /home/pi/camera
	sudo patch -d / -p1 -R < src/0001_janus.plugin.streaming.jcfg.patch
	sudo systemctl restart janus.service
	sleep 3
	sudo systemctl status janus.service
	#sudo apt remove -y python3-netifaces

redeploy:
	sudo systemctl stop httpsserver.service
	sudo systemctl disable httpsserver.service
	sudo cp src/httpsserver.service /etc/systemd/system
	sudo systemctl enable httpsserver.service
	sudo systemctl start httpsserver.service
	sleep 3
	sudo systemctl status httpsserver.service
	sudo rm -rf /opt/camera/share/camera
	sudo mkdir -p /opt/camera/share/camera
	sudo bash -c "uglifyjs /opt/janus/share/janus/demos/janus.js > /opt/camera/share/camera/janus.min.js"
	#sudo cp /opt/janus/share/janus/demos/janus.js /opt/camera/share/camera
	sudo bash -c "cp src/index.html /opt/camera/share/camera/index.html"
	sudo bash -c "cp src/camera.css /opt/camera/share/camera/camera.css"
	sudo bash -c "uglifyjs src/camera.js > /opt/camera/share/camera/camera.js"
	sudo cp src/favicon.ico /opt/camera/share/camera
	cd /opt/camera/share/camera && sudo npm i webrtc-adapter
	cd /opt/camera/share/camera && sudo npm i jquery
	cd /opt/camera/share/camera && sudo npm i bootstrap
	cd /opt/camera/share/camera && sudo npm i bootbox
	cd /opt/camera/share/camera && sudo npm i @fortawesome/fontawesome-free
	sudo bash -c "uglifyjs /opt/camera/share/camera/node_modules/webrtc-adapter/out/adapter.js > /opt/camera/share/camera/node_modules/webrtc-adapter/out/adapter.min.js"
	sudo cp src/camera.py /opt/camera/bin
	sudo ln -s /home/pi/camera /opt/camera/share/camera/media
	sudo systemctl stop camera.service
	sudo systemctl disable camera.service
	sudo cp src/camera.service /etc/systemd/system
	sudo systemctl enable camera.service
	sudo systemctl start camera.service
	sleep 3 
	sudo systemctl status camera.service

swapon:
	sudo cp /etc/dphys-swapfile.bak /etc/dphys-swapfile
	sudo dphys-swapfile setup
	sudo dphys-swapfile swapon

swapoff:
	sudo cp /etc/dphys-swapfile dphys-swapfile.bak
	sudo bash -c "echo 'CONF_SWAPSIZE=0' > /etc/dphys-swapfile"
	sudo dphys-swapfile swapoff

swap:
	sudo bash -c "echo 3 >'/proc/sys/vm/drop_caches' && sudo dphys-swapfile swapoff && sudo dphys-swapfile swapon && printf '\n%s\n' 'Ram-cache and Swap Cleared'"
	
status:
	sudo systemctl status camera

stop:
	sudo systemctl stop camera

restart:
	sudo systemctl restart camera

run:
	python3 src/camera.py
