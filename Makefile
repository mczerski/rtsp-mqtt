
PREFIX ?= /usr/local
INITDIR_SYSTEMD = /etc/systemd/system
BINDIR = $(PREFIX)/bin

RM = rm
INSTALL = install -p
INSTALL_PROGRAM = $(INSTALL) -m755
INSTALL_SCRIPT = $(INSTALL) -m755
INSTALL_DATA = $(INSTALL) -m644
INSTALL_DIR = $(INSTALL) -d

Q = @

help:
	$(Q)echo "install - install scripts"
	$(Q)echo "uninstall - uninstall scripts"

install:
	$(Q)echo -e '\033[1;32mInstalling main scripts...\033[0m'
	$(INSTALL_DIR) "$(BINDIR)"
	$(INSTALL_PROGRAM) rtsp_mqtt.py "$(BINDIR)/rtsp_mqtt"
	$(INSTALL_DATA) rtsp_mqtt.service "$(INITDIR_SYSTEMD)/rtsp_mqtt.service"

uninstall:
	$(RM) "$(BINDIR)/rtsp_mqtt"
	systemctl disable rtsp_mqtt.service
	$(RM) "$(INITDIR_SYSTEMD)/rtsp_mqtt.service"

.PHONY: install uninstall
