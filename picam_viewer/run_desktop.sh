#!/bin/bash
# Start the desktop (Qt) viewer. The web service owns the camera, so stop it while the desktop
# viewer runs and start it again afterwards.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_WAS_ACTIVE=0
if systemctl is-active --quiet picam-web; then
	SERVICE_WAS_ACTIVE=1
	sudo systemctl stop picam-web
fi
python3 "${DIR}/app_full.py" "$@"
STATUS=$?
[ "${SERVICE_WAS_ACTIVE}" = 1 ] && sudo systemctl start picam-web
exit ${STATUS}
