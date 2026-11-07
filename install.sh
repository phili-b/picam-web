#!/bin/bash -e
# Install the Picam-web viewer in place on a Raspberry Pi:
#  - apt dependencies
#  - the web service (picam-web.service, port 80): owns the camera, serves the web UI and the API
#  - menu entries and a desktop shortcut (web UI; the desktop viewer is in the menu)
# Run from where it should live, e.g.
#   sudo git clone <repo> /opt/picam_viewer && sudo /opt/picam_viewer/install.sh
# Also works inside an image build chroot.
#
# The user that runs the service and gets the shortcut: $VIEWER_USER, else $SUDO_USER, else pi.

cd "$(dirname "${BASH_SOURCE[0]}")"
VIEWER_DIR=${PWD}
VIEWER_USER=${VIEWER_USER:-${SUDO_USER:-pi}}

if [ "$(id -u)" -ne 0 ]; then
	echo "Run as root: sudo $0"
	exit 1
fi

fill() { sed -e "s|@VIEWER_DIR@|${VIEWER_DIR}|g" -e "s|@VIEWER_USER@|${VIEWER_USER}|g" "$1"; }

echo "### Installing apt packages"
apt-get install -y $(grep -v -E '^\s*(#|$)' requirements-apt.txt)
chmod 755 picam_viewer/run_desktop.sh picam_web/server.py desktop/open_web_ui.sh

echo "### Installing the web service"
# Root-owned copy of the camera model helper: the service may run only this one with sudo
install -m 755 -o root -g root tools/picam-camera-overlay /usr/local/sbin/picam-camera-overlay
fill systemd/picam-web.service > /etc/systemd/system/picam-web.service
fill systemd/picam-web.sudoers > /etc/sudoers.d/picam-web
chmod 440 /etc/sudoers.d/picam-web
visudo -cf /etc/sudoers.d/picam-web
systemctl enable picam-web.service
# Start it now on a running system (not inside the image build's chroot)
if [ "$(systemctl is-system-running 2>/dev/null)" != "offline" ] && [ -d /run/systemd/system ]; then
	systemctl daemon-reload
	systemctl restart picam-web.service
fi

echo "### Installing menu entries"
for f in picam_web picam_viewer; do
	fill "desktop/${f}.desktop" > "/usr/share/applications/${f}.desktop"
	chmod 644 "/usr/share/applications/${f}.desktop"
done

USER_HOME=$(getent passwd "${VIEWER_USER}" | cut -d: -f6)
if [ -n "${USER_HOME}" ]; then
	echo "### Installing desktop shortcut for ${VIEWER_USER}"
	install -d -o "${VIEWER_USER}" -g "${VIEWER_USER}" "${USER_HOME}/Desktop"
	install -m 755 -o "${VIEWER_USER}" -g "${VIEWER_USER}" /usr/share/applications/picam_web.desktop "${USER_HOME}/Desktop/"
	rm -f "${USER_HOME}/Desktop/picam_viewer.desktop"  # older versions put this one there too
fi

echo "### Done. Web UI: http://$(hostname).local/ (API docs: /docs)."
echo "    Desktop viewer: ${VIEWER_DIR}/picam_viewer/run_desktop.sh"
