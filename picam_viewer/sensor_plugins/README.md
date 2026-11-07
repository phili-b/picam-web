# Sensor plugins

Every `.py` file in this folder is imported when the viewer or the web service starts. A plugin
registers sensor profiles (named registers, banked register maps, driver register controls):

```python
import sensor_regs as sr

sr.register_profile(sr.SensorProfile("mysensor", registers=[("CHIP_ID", 0x0000, 2)]))
```

See [docs/registers.md](../../docs/registers.md#sensor-plugins). Plugins are ignored by git, so
private sensor data stays out of this repository.
