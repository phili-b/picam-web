"""Decode the Raspberry Pi ISP statistics that libcamera returns as metadata when the
StatsOutputEnable control is on (numpy only, no camera or Qt).

Raspberry Pi 5 (PiSP): metadata 'PispStatsOutput', the pisp_statistics struct of libpisp
(src/libpisp/frontend/pisp_statistics.h), 23200 bytes, little-endian:
  awb  zones[32*32] {R_sum, G_sum, B_sum, counted: u32}, floating[4] (same)
  agc  row_sums[512] u32, histogram[1024] u32, floating[4] {Y_sum u64, counted u32, pad u32}
  cdaf foms[8*8] u64, floating[4] u64
The ISP does not process statistics on every frame, so not every request carries them.
Raspberry Pi 4 (VC4) returns 'Bcm2835StatsOutput' in another layout, not decoded here.
"""

import numpy as np

_AWB_ZONE = np.dtype([("R", "<u4"), ("G", "<u4"), ("B", "<u4"), ("counted", "<u4")])
_AGC_ZONE = np.dtype([("Y", "<u8"), ("counted", "<u4"), ("pad", "<u4")])
PISP_STATS = np.dtype([
    ("awb_zones", _AWB_ZONE, (32 * 32,)),
    ("awb_floating", _AWB_ZONE, (4,)),
    ("agc_row_sums", "<u4", (512,)),
    ("agc_histogram", "<u4", (1024,)),
    ("agc_floating", _AGC_ZONE, (4,)),
    ("cdaf_foms", "<u8", (8 * 8,)),
    ("cdaf_floating", "<u8", (4,)),
])
assert PISP_STATS.itemsize == 23200


def decode(metadata):
    """Return the decoded statistics of a request's metadata, or None when it has none.

    Result: {'platform', 'histogram' (1024), 'row_sums' (512), 'zones_mean' (32x32, G mean per
    zone), 'zones_rgb' (32x32x3 means), 'focus' (8x8 figure of merit)}.
    """
    raw = metadata.get("PispStatsOutput")
    if raw is not None:
        buf = bytes(bytearray(raw))
        if len(buf) != PISP_STATS.itemsize:
            raise ValueError(f"PispStatsOutput is {len(buf)} bytes, expected {PISP_STATS.itemsize}")
        s = np.frombuffer(buf, dtype=PISP_STATS)[0]
        zones = s["awb_zones"]
        counted = np.maximum(zones["counted"].astype(np.float64), 1)
        rgb = np.stack([zones[c] / counted for c in ("R", "G", "B")], axis=-1).reshape(32, 32, 3)
        return {
            "platform": "pisp",
            "histogram": s["agc_histogram"].astype(np.int64),
            "row_sums": s["agc_row_sums"].astype(np.int64),
            "zones_rgb": rgb,
            "zones_mean": rgb[..., 1],
            "focus": s["cdaf_foms"].reshape(8, 8).astype(np.float64),
        }
    if metadata.get("Bcm2835StatsOutput") is not None:
        return {"platform": "vc4"}
    return None
