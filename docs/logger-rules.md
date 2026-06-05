# Logger Logic & Rules

This document explains the physics and software constraints driving the telemetry logic in VoltWatch.

## Power Calculation Explanation
VoltWatch calculates power dynamically, but the foundational measurements are:
- **Bus Voltage ($V_{bus}$)**: The total voltage of the system being measured, taken between the load and ground. Measured in Volts.
- **Shunt Voltage ($V_{shunt}$)**: The tiny voltage drop across the INA219's onboard precision resistor (typically $0.1\Omega$). Measured in milliVolts.
- **Current ($I$)**: Calculated using Ohm's Law: $I = V_{shunt} / R_{shunt}$.
- **Power ($P$)**: Calculated natively by the INA219, or computed in the dashboard as $P = V_{bus} \times I$.

## The Buffer Rule
The ESP8266 has limited SRAM (~80KB total, ~40KB free). 
- To avoid heap fragmentation and Out-Of-Memory (OOM) crashes, we enforce a strict ring buffer of `20` JSON reading objects.
- If the Wi-Fi disconnects and 20 readings are taken, the oldest reading is overwritten (FIFO).
- Once Wi-Fi is restored, all available buffered readings are dispatched in a single bulk `POST` request.

## The RTC Rule (No Lookahead Bias)
A common pitfall in IoT logging is tagging the data with a timestamp *when it hits the server*. If a device disconnects for 5 minutes and then uploads a batch of 20 readings, applying the server timestamp will cluster all 20 readings into the same millisecond, ruining the time-series analysis.

By enforcing the use of the DS3231 RTC, the timestamp is strictly attached at the exact moment of I2C polling. The backend trusts this timestamp explicitly.

## Failure Handling Edge Cases
- **I2C Bus Lockup**: If the INA219 fails to respond, the ESP will log `NaN` values and signal a fault state, rather than blocking the execution loop indefinitely.
- **RTC Battery Death**: If the RTC battery dies, the RTC resets to year 2000. The ESP firmware detects this anomaly and will refuse to upload data until the RTC is synchronized (via NTP when internet is available).
