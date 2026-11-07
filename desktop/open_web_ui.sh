#!/bin/sh
# Open the web UI of the camera service in its own window (Chromium app mode: no address bar or
# tabs). Falls back to the default browser. Usage: open_web_ui.sh [url]
URL="${1:-http://localhost/}"
for browser in chromium chromium-browser; do
	if command -v "$browser" > /dev/null; then
		exec "$browser" --app="$URL" --class=picam-web
	fi
done
exec xdg-open "$URL"
