"""Simulated picamera2.outputs."""

import io


class FileOutput:
    """Writes frames to a file name or a file-like object (e.g. picam_web's StreamingOutput)."""

    def __init__(self, file=None, pts=None, split=None):
        self._file = file
        self._pts_path = pts
        self._fh = None
        self._pts = None

    def start(self):
        if isinstance(self._file, str):
            self._fh = open(self._file, "wb")
        elif isinstance(self._file, io.IOBase) or hasattr(self._file, "write"):
            self._fh = self._file
        if self._pts_path:
            self._pts = open(self._pts_path, "w")
            self._pts.write("# timecode format v2\n")

    def outputframe(self, frame, keyframe=True, timestamp=None, packet=None, audio=False):
        if self._fh is not None:
            self._fh.write(frame)
        if self._pts is not None and timestamp is not None:
            self._pts.write(f"{timestamp / 1e6:.3f}\n")

    def stop(self):
        if isinstance(self._file, str) and self._fh:
            self._fh.close()
        if self._pts:
            self._pts.close()
        self._fh = self._pts = None


class FfmpegOutput(FileOutput):
    def __init__(self, output_filename, audio=False, **kwargs):
        super().__init__(output_filename)
