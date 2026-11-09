// Plain-language names and explanations of the libcamera controls. A control that is not listed
// here still appears, under "Other", with its libcamera name.

export interface ControlInfo {
  label: string;
  group: string;
  help: string;
  options?: string[];   // enum controls: the name of each value, the index is the value
}

export const GROUPS = ["Auto exposure", "Image processing", "Noise and HDR", "Frame timing and crop", "Autofocus", "Other"];

export const CONTROL_INFO: Record<string, ControlInfo> = {
  AeMeteringMode: { label: "Metering", group: "Auto exposure", options: ["Centre weighted", "Spot", "Matrix", "Custom"],
    help: "Which part of the image auto exposure measures: mostly the centre, a small central spot, or the whole frame." },
  AeConstraintMode: { label: "Priority", group: "Auto exposure", options: ["Normal", "Highlight", "Shadows", "Custom"],
    help: "What auto exposure protects: Highlight keeps bright areas from clipping, Shadows keeps dark areas visible." },
  AeExposureMode: { label: "Exposure program", group: "Auto exposure", options: ["Normal", "Short", "Long", "Custom"],
    help: "How auto exposure divides brightness between time and gain: Short limits motion blur, Long limits gain and noise." },
  ExposureValue: { label: "Exposure compensation [EV]", group: "Auto exposure",
    help: "Makes auto exposure aim brighter or darker: +1 is twice as bright, -1 half as bright, 0 no change." },
  AeFlickerMode: { label: "Flicker correction", group: "Auto exposure", options: ["Off", "Manual", "Auto"],
    help: "Avoids banding under mains lighting by using exposure times that match the flicker period below." },
  AeFlickerPeriod: { label: "Flicker period [µs]", group: "Auto exposure",
    help: "Period of the light flicker, for Manual correction: 10000 for 50 Hz mains, 8333 for 60 Hz." },
  ExposureTimeMode: { label: "Exposure time mode", group: "Auto exposure", options: ["Auto", "Manual"],
    help: "Whether the exposure time alone is set by auto exposure or by hand." },
  AnalogueGainMode: { label: "Analogue gain mode", group: "Auto exposure", options: ["Auto", "Manual"],
    help: "Whether the analogue gain alone is set by auto exposure or by hand." },

  Brightness: { label: "Brightness", group: "Image processing",
    help: "Adds a constant to all pixels: 0 no change, negative darker, positive brighter." },
  Contrast: { label: "Contrast", group: "Image processing", help: "1 no change, below 1 flatter, above 1 punchier." },
  Saturation: { label: "Saturation", group: "Image processing", help: "Colour strength: 1 no change, 0 greyscale, above 1 more vivid." },
  Sharpness: { label: "Sharpness", group: "Image processing", help: "Edge enhancement: 1 the tuned default, 0 none, above 1 stronger." },
  ColourCorrectionMatrix: { label: "Colour matrix", group: "Image processing",
    help: "Nine numbers, row by row, mapping sensor RGB to output RGB. Only with auto white balance off; 1,0,0, 0,1,0, 0,0,1 leaves colours as they are." },

  NoiseReductionMode: { label: "Noise reduction", group: "Noise and HDR", options: ["Off", "Fast", "High quality", "Minimal", "Zero shutter lag"],
    help: "How strongly the ISP removes noise. Use Off to judge the sensor's own noise in the processed image." },
  HdrMode: { label: "HDR mode", group: "Noise and HDR", options: ["Off", "Multi exposure, unmerged", "Multi exposure", "Single exposure", "Night"],
    help: "Combines several frames, or tone maps one, to show a wider brightness range. Needs support in the tuning file." },

  FrameDurationLimits: { label: "Frame time limits [µs]", group: "Frame timing and crop",
    help: "Shortest and longest frame time, e.g. 33333, 33333 fixes 30 fps. The longest also limits the exposure time." },
  ScalerCrop: { label: "Crop (digital zoom)", group: "Frame timing and crop",
    help: "x, y, width, height in sensor pixels of the area the ISP outputs." },
  SyncMode: { label: "Multi-camera sync", group: "Frame timing and crop", options: ["Off", "Server", "Client"],
    help: "Lines frames up between Raspberry Pis: one Server, the others Clients." },
  SyncFrames: { label: "Sync frames", group: "Frame timing and crop",
    help: "Number of frames over which multi-camera sync is established." },

  AfMode: { label: "Focus mode", group: "Autofocus", options: ["Manual", "Auto (on trigger)", "Continuous"],
    help: "Manual uses the lens position below, Auto focuses once on a trigger, Continuous keeps refocusing." },
  AfRange: { label: "Focus range", group: "Autofocus", options: ["Normal", "Macro", "Full"], help: "The distances autofocus searches." },
  AfSpeed: { label: "Focus speed", group: "Autofocus", options: ["Normal", "Fast"], help: "How fast the lens moves while focusing." },
  AfMetering: { label: "Focus area", group: "Autofocus", options: ["Auto", "Windows"], help: "Where autofocus looks in the image." },
  AfTrigger: { label: "Focus trigger", group: "Autofocus", options: ["Start", "Cancel"], help: "Starts or cancels a focus scan in Auto mode." },
  AfPause: { label: "Focus pause", group: "Autofocus", options: ["Immediate", "Deferred", "Resume"], help: "Pauses or resumes continuous autofocus." },
  LensPosition: { label: "Lens position [dioptres]", group: "Autofocus", help: "Manual focus: 0 is infinity, 1 is 1 m, 2 is 50 cm, and so on." },

  StatsOutputEnable: { label: "ISP statistics output", group: "Other", help: "Adds the ISP's statistics to every frame's metadata; used by the ISP statistics view." },
  CnnEnableInputTensor: { label: "AI camera input tensor", group: "Other", help: "Adds the input image of the on-sensor neural network to the metadata (AI camera only)." },
};
