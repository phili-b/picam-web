import RPi.GPIO as GPIO

class ExtTrigPWM:

    def __init__(self, ext_trig_pwm_pin=18, ext_trig_pwm_hz=1, ext_trig_pwm_dc=10):
        # Default: using Broadcom GPIO 18 (PCM CLK). Header position 12.
        GPIO.setmode(GPIO.BCM) # Broadcom pin-numbering scheme
        GPIO.setup(ext_trig_pwm_pin, GPIO.OUT) # PWM pin set as output
        self.pwm = GPIO.PWM(ext_trig_pwm_pin, ext_trig_pwm_hz)  # Initialize PWM to specified frequency
        self.dc = ext_trig_pwm_dc

    def start(self):
        self.pwm.start(self.dc) # Set Duty cycle

if __name__ == "__main__":

    # Default init. PWM pin is Broadcom GPIO 18 at header position 12.
    ext_trig_pwm = ExtTrigPWM()

    # Start PWM
    ext_trig_pwm.start()


