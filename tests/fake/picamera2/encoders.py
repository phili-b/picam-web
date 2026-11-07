"""Simulated picamera2.encoders: JPEG for real (Pillow), the others write the stream bytes."""

import enum
import io


class Quality(enum.IntEnum):
    VERY_LOW = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    VERY_HIGH = 4


class Encoder:
    """Null encoder: writes the buffers as they are (raw video)."""

    def __init__(self):
        self.output = None
        self.frame_skip_count = 1
        self._count = 0

    def _start(self, output):
        if output is not None:
            output.start()

    def _stop(self, output):
        if output is not None:
            output.stop()

    def _encode(self, request, name, output):
        self._count += 1
        if self._count % max(1, self.frame_skip_count):
            return
        output.outputframe(self._data(request, name), timestamp=request.metadata.get("SensorTimestamp"))

    def _data(self, request, name):
        return request.make_buffer(name).tobytes()


class JpegEncoder(Encoder):
    def __init__(self, q=85, **kwargs):
        super().__init__()
        self.q = q

    def _data(self, request, name):
        buf = io.BytesIO()
        request.make_image(name).save(buf, format="JPEG", quality=self.q)
        return buf.getvalue()


class H264Encoder(Encoder):
    def __init__(self, bitrate=None, repeat=False, iperiod=None, **kwargs):
        super().__init__()


class MJPEGEncoder(JpegEncoder):
    pass
