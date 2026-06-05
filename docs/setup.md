# Setup Guide

This document details the complete end-to-end setup process for VoltWatch.

## 1. Hardware Requirements
- **ESP8266 Microcontroller** (e.g., NodeMCU v2 or Wemos D1 Mini)
- **INA219** High Side DC Current Sensor Breakout
- **DS3231** Precision RTC Module
- Appropriate logic level shifters (if your INA219 breakout is strict 5V, though most Adafruit-style boards have 3.3V regulators).

### Wiring
| Module | Pin | ESP8266 Pin |
|--------|-----|-------------|
| INA219 | SDA | D2 (GPIO 4) |
| INA219 | SCL | D1 (GPIO 5) |
| DS3231 | SDA | D2 (GPIO 4) |
| DS3231 | SCL | D1 (GPIO 5) |
| Both   | VCC | 3.3V        |
| Both   | GND | GND         |

## 2. Software Prerequisites
- Python 3.11+
- Arduino IDE (or VSCode with PlatformIO / Arduino CLI)

## 3. Backend Setup
1. Open a terminal in the `backend` folder.
2. Create the virtual environment: `python -m venv .venv`
3. Activate it:
   - Windows: `.\.venv\Scripts\Activate.ps1`
   - Mac/Linux: `source .venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Run the server: `python run.py` (App starts on `http://localhost:8000`)

## 4. Dashboard Setup
1. Open a second terminal in the `dashboard` folder.
2. Create and activate a new virtual environment as above.
3. Install dependencies: `pip install -r requirements.txt`
4. Run Streamlit: `streamlit run app.py`

## 5. Firmware Setup
1. Open `esp-ina219-datalogger.ino` in Arduino IDE.
2. Ensure you have the `esp8266` board manager installed.
3. Install the required libraries via the Library Manager: `Adafruit INA219`, `Adafruit BusIO`, `Adafruit GFX Library`, `Adafruit SSD1306`, `RTClib`, `ArduinoJson`.
4. Compile and upload.
5. On first boot, connect your phone to the `VoltWatch Setup` Wi-Fi AP.
6. Enter your real Wi-Fi credentials and the IP address of your backend server (e.g., `192.168.1.50`). 
