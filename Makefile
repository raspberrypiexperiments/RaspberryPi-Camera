install:
	sudo apt update
	sudo apt upgrade -y
	sudo apt install -y python3-netifaces
	cd gst-rpicamsrc && ./autogen.sh --prefix=/usr/local --libdir=/usr/local/lib/arm-linux-gnueabihf/ && make && sudo make install 
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
	sudo mkdir -p /opt/camera/share/camera
	sudo cp /opt/janus/share/janus/demos/janus.js /opt/camera/share/camera
	sudo cp src/index.html /opt/camera/share/camera
	sudo cp src/camera.css /opt/camera/share/camera
	sudo cp src/camera.js /opt/camera/share/camera
	sudo cp src/camera.py /opt/camera/share/camera
	sudo patch -d / -p1 < src/0001_janus.plugin.streaming.jcfg.patch
	sudo systemctl restart janus.service
	sleep 3
	sudo systemctl status janus.service

uninstall:
	sudo systemctl daemon-reload
	sudo systemctl stop httpsserver.service
	sudo systemctl disable httpsserver.service || true
	sudo rm -rf /opt/camera
	cd gst-rpicamsrc && ./autogen.sh --prefix=/usr/local --libdir=/usr/local/lib/arm-linux-gnueabihf/ && sudo make uninstall
	sudo patch -d / -p1 -R < src/0001_janus.plugin.streaming.jcfg.patch
	sudo systemctl restart janus.service
	sleep 3
	sudo systemctl status janus.service

redeploy:
	sudo rm -rf /opt/camera/share/camera
	sudo mkdir -p /opt/camera/share/camera
	sudo cp /opt/janus/share/janus/demos/janus.js /opt/camera/share/camera
	sudo cp src/index.html /opt/camera/share/camera
	sudo cp src/camera.css /opt/camera/share/camera
	sudo cp src/camera.js /opt/camera/share/camera
	sudo cp src/camera.py /opt/camera/share/camera