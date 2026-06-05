#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WebServer.h>
#include <LittleFS.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_INA219.h>
#include <RTClib.h>
#include <math.h>
#include <time.h>

// ================= CONFIG =================
#define MAX_SENSORS 4
#define BUFFER_SIZE 100
#define MAX_BATCH_ITEMS 20
#define READ_INTERVAL_MS 1000UL
#define SEND_INTERVAL_MS 5000UL
#define WIFI_CONNECT_TIMEOUT_MS 20000UL
#define WIFI_RETRY_INTERVAL_MS 5000UL
#define HEALTHCHECK_TIMEOUT_MS 3000UL
#define NTP_SYNC_TIMEOUT_MS 10000UL
#define NTP_SYNC_MAX_WAIT_MS 30000UL
#define NTP_RESYNC_INTERVAL_MS 60000UL
#define OLED_REFRESH_MS 400UL
#define AP_SSID_PREFIX "DataLogger-Setup"
#define CONFIG_PATH "/config.txt"
#define DEFAULT_SERVER_PORT 8000
#define OLED_WIDTH 128
#define OLED_HEIGHT 64
#define OLED_RESET_PIN -1
#define DEFAULT_AVG_WINDOW 8
#define MAX_AVG_WINDOW 32
#define DEFAULT_INA_HW_AVG 128
// The display is documented as 0x78 on the wire; Adafruit_SSD1306 expects the 7-bit value.
#define OLED_I2C_ADDRESS_RAW 0x78
#define OLED_I2C_ADDRESS ((OLED_I2C_ADDRESS_RAW > 0x3F) ? (OLED_I2C_ADDRESS_RAW >> 1) : OLED_I2C_ADDRESS_RAW)

#define INA219_REG_CONFIG 0x00
#define INA219_CONFIG_BVOLTAGERANGE_32V 0x2000
#define INA219_CONFIG_GAIN_8_320MV 0x1800
#define INA219_CONFIG_MODE_SANDBVOLT_CONTINUOUS 0x0007

const char* NTP_SERVER_1 = "0.in.pool.ntp.org";
const char* NTP_SERVER_2 = "time.nist.gov";

// Known INA219 addresses
uint8_t INA_ADDRS[MAX_SENSORS] = {0x40, 0x41, 0x44, 0x45};

// ================= DEVICE STATE =================
enum DeviceState {
  BOOT_INIT,
  LOAD_CONFIG,
  WIFI_CONNECTING,
  SERVER_VERIFYING,
  RUNNING,
  PROVISION_AP_START,
  PROVISION_AP_ACTIVE,
  PROVISION_AP_SUBMITTED,
  ERROR_RECOVERABLE
};

struct RuntimeConfig {
  String ssid;
  String password;
  String serverHost;
  uint16_t serverPort = DEFAULT_SERVER_PORT;
  String apiKey;
  String deviceId;
  uint8_t avgWindow = DEFAULT_AVG_WINDOW;
  uint16_t inaHwAvg = DEFAULT_INA_HW_AVG;
};

struct CalibrationProfile {
  uint8_t address = 0;
  float busVoltageGain = 1.0f;
  float busVoltageOffset = 0.0f;
  float currentGain = 1.0f;
  float currentOffset = 0.0f;
};

// ================= RTC / DISPLAY / WEB =================
RTC_DS3231 rtc;
ESP8266WebServer portalServer(80);
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET_PIN);

// ================= SENSOR =================
struct SensorConfig {
  uint8_t address;
  uint8_t index;
  float busVoltageGain = 1.0f;
  float busVoltageOffset = 0.0f;
  float currentGain = 1.0f;
  float currentOffset = 0.0f;
  bool active = false;
  Adafruit_INA219* ina = nullptr;
  float busVoltageSamples[MAX_AVG_WINDOW] = {0};
  float currentSamples[MAX_AVG_WINDOW] = {0};
  float busVoltageSum = 0.0f;
  float currentSum = 0.0f;
  uint8_t busVoltageSampleCount = 0;
  uint8_t currentSampleCount = 0;
  uint8_t busVoltageSampleCursor = 0;
  uint8_t currentSampleCursor = 0;
  bool hasReading = false;
  float lastRawBusVoltage = 0.0f;
  float lastRawShuntVoltage = 0.0f;
  float lastRawSupplyVoltage = 0.0f;
  float lastRawCurrent = 0.0f;
  float lastSmoothedBusVoltage = 0.0f;
  float lastSmoothedCurrent = 0.0f;
  float lastCorrectedBusVoltage = 0.0f;
  float lastCorrectedSupplyVoltage = 0.0f;
  float lastCorrectedCurrent = 0.0f;
  uint32_t lastSeq = 0;
};

SensorConfig sensors[MAX_SENSORS];
uint8_t sensorCount = 0;
CalibrationProfile calibrationProfiles[MAX_SENSORS];

struct PortalCalibrationDraft {
  String busVoltageGain;
  String busVoltageOffset;
  String currentGain;
  String currentOffset;
};

// ================= DATA =================
struct SensorReading {
  uint8_t sensor_index;
  float busVoltage;
  float shuntVoltage;
  float supplyVoltage;
  float current;
};

struct Reading {
  uint32_t seq;
  String timestamp;
  SensorReading sensorData[MAX_SENSORS];
  uint8_t sensorCount;
};

// ================= BUFFER =================
class CircularBuffer {
private:
  Reading buffer[BUFFER_SIZE];
  int head = 0;
  int tail = 0;
  int count = 0;
  uint32_t droppedCount = 0;

public:
  void push(const Reading& r) {
    buffer[head] = r;
    head = (head + 1) % BUFFER_SIZE;

    if (count < BUFFER_SIZE) {
      count++;
    } else {
      tail = (tail + 1) % BUFFER_SIZE;
      droppedCount++;
    }
  }

  int size() const { return count; }
  bool isEmpty() const { return count == 0; }
  uint32_t dropped() const { return droppedCount; }

  Reading& get(int index) {
    return buffer[(tail + index) % BUFFER_SIZE];
  }

  void pop(int n) {
    tail = (tail + n) % BUFFER_SIZE;
    count -= n;
    if (count < 0) {
      count = 0;
    }
  }
};

CircularBuffer buffer;

// ================= GLOBAL =================
DeviceState deviceState = BOOT_INIT;
RuntimeConfig currentConfig;
RuntimeConfig attemptedConfig;
RuntimeConfig portalDraftConfig;

bool oledAvailable = false;
bool rtcAvailable = false;
bool portalActive = false;
bool wifiConnectStarted = false;
bool configLoaded = false;
bool rtcHasValidTime = false;

uint32_t seqCounter = 0;
String bootId;
unsigned long stateStartedAt = 0;
unsigned long lastRead = 0;
unsigned long lastSend = 0;
unsigned long lastWiFiRetry = 0;
unsigned long lastOledRefresh = 0;
unsigned long lastNtpSyncAttempt = 0;
unsigned long ntpSyncStartedAt = 0;

String portalMessage;
String lastError;
String lastUploadStatus = "Idle";
String lastHealthStatus = "Not checked";
String apSsid;
String portalAvgWindowInput;
String portalHwAvgInput;
PortalCalibrationDraft portalCalibrationDrafts[MAX_SENSORS];

// ================= UTIL =================
String currentTimestamp() {
  time_t systemNow = time(nullptr);
  if (systemNow >= 1700000000) {
    struct tm* utc = gmtime(&systemNow);
    if (utc != nullptr) {
      char buf[25];
      snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02dZ",
               utc->tm_year + 1900, utc->tm_mon + 1, utc->tm_mday,
               utc->tm_hour, utc->tm_min, utc->tm_sec);
      return String(buf);
    }
  }

  if (!rtcAvailable || !rtcHasValidTime) {
    return "1970-01-01T00:00:00Z";
  }

  DateTime now = rtc.now();
  char buf[25];
  snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02dZ",
           now.year(), now.month(), now.day(),
           now.hour(), now.minute(), now.second());
  return String(buf);
}

String trimCopy(String value) {
  value.trim();
  return value;
}

String stateName(DeviceState state) {
  switch (state) {
    case BOOT_INIT: return "BOOT_INIT";
    case LOAD_CONFIG: return "LOAD_CONFIG";
    case WIFI_CONNECTING: return "WIFI_CONNECTING";
    case SERVER_VERIFYING: return "SERVER_VERIFYING";
    case RUNNING: return "RUNNING";
    case PROVISION_AP_START: return "PROVISION_AP_START";
    case PROVISION_AP_ACTIVE: return "PROVISION_AP_ACTIVE";
    case PROVISION_AP_SUBMITTED: return "PROVISION_AP_SUBMITTED";
    case ERROR_RECOVERABLE: return "ERROR_RECOVERABLE";
    default: return "UNKNOWN";
  }
}

void setState(DeviceState nextState) {
  if (deviceState == nextState) {
    return;
  }
  deviceState = nextState;
  stateStartedAt = millis();
  Serial.printf("State -> %s\n", stateName(deviceState).c_str());
}

String htmlEscape(String input) {
  input.replace("&", "&amp;");
  input.replace("\"", "&quot;");
  input.replace("<", "&lt;");
  input.replace(">", "&gt;");
  return input;
}

String shortText(const String& value, size_t maxLen) {
  if (value.length() <= maxLen) {
    return value;
  }
  return value.substring(0, maxLen - 1) + "~";
}

String hostLabel() {
  if (currentConfig.serverHost.length() == 0) {
    return "unset";
  }
  return currentConfig.serverHost + ":" + String(currentConfig.serverPort);
}

String apIpString() {
  return WiFi.softAPIP().toString();
}

String defaultDeviceId() {
  return "esp8266-" + String(ESP.getChipId(), HEX);
}

String makeBootId(const RuntimeConfig& config) {
  String deviceId = trimCopy(config.deviceId);
  if (deviceId.length() == 0) {
    deviceId = defaultDeviceId();
  }

  uint32_t chipId = ESP.getChipId();
  unsigned long bootTicks = millis();
  unsigned long bootMicros = micros();
  String bootTimestamp = currentTimestamp();

  char buffer[128];
  snprintf(
      buffer,
      sizeof(buffer),
      "%s-%06lx-%s-%08lx-%08lx",
      deviceId.c_str(),
      static_cast<unsigned long>(chipId),
      bootTimestamp.c_str(),
      bootTicks,
      bootMicros);

  String generated(buffer);
  generated.replace(":", "");
  generated.replace("-", "");
  generated.replace(".", "");
  generated.replace(" ", "");
  return generated;
}

void refreshBootId(const RuntimeConfig& config) {
  bootId = makeBootId(config);
  Serial.printf("Boot identity boot_id=%s device=%s start_seq=%lu\n",
                bootId.c_str(),
                config.deviceId.c_str(),
                static_cast<unsigned long>(seqCounter));
}

int sensorAddressSlot(uint8_t address) {
  for (int i = 0; i < MAX_SENSORS; i++) {
    if (INA_ADDRS[i] == address) {
      return i;
    }
  }
  return -1;
}

String sensorAddressLabel(uint8_t address) {
  char buffer[7];
  snprintf(buffer, sizeof(buffer), "0x%02X", address);
  return String(buffer);
}

String formatFloat(float value, uint8_t decimals) {
  if (!isfinite(value)) {
    return "nan";
  }
  char buffer[24];
  dtostrf(value, 0, decimals, buffer);
  return String(buffer);
}

bool parseUInt16Strict(const String& input, uint16_t& value) {
  String trimmed = trimCopy(input);
  if (trimmed.length() == 0) {
    return false;
  }

  char* endPtr = nullptr;
  long parsed = strtol(trimmed.c_str(), &endPtr, 10);
  if (endPtr == trimmed.c_str() || *endPtr != '\0' || parsed < 0 || parsed > 65535) {
    return false;
  }

  value = static_cast<uint16_t>(parsed);
  return true;
}

bool parseFloatStrict(const String& input, float& value) {
  String trimmed = trimCopy(input);
  if (trimmed.length() == 0) {
    return false;
  }

  char* endPtr = nullptr;
  float parsed = strtof(trimmed.c_str(), &endPtr);
  if (endPtr == trimmed.c_str() || *endPtr != '\0' || !isfinite(parsed)) {
    return false;
  }

  value = parsed;
  return true;
}

bool isSupportedHwAverage(uint16_t value) {
  switch (value) {
    case 1:
    case 2:
    case 4:
    case 8:
    case 16:
    case 32:
    case 64:
    case 128:
      return true;
    default:
      return false;
  }
}

uint16_t hwAverageConfigBits(uint16_t avgSamples) {
  switch (avgSamples) {
    case 1: return 0x0180;
    case 2: return 0x0480;
    case 4: return 0x0500;
    case 8: return 0x0580;
    case 16: return 0x0600;
    case 32: return 0x0680;
    case 64: return 0x0700;
    case 128: return 0x0780;
    default: return 0x0780;
  }
}

CalibrationProfile& calibrationForAddress(uint8_t address) {
  int slot = sensorAddressSlot(address);
  if (slot < 0) {
    slot = 0;
  }
  calibrationProfiles[slot].address = address;
  return calibrationProfiles[slot];
}

void resetSensorSmoothing(SensorConfig& sensor) {
  sensor.busVoltageSum = 0.0f;
  sensor.currentSum = 0.0f;
  sensor.busVoltageSampleCount = 0;
  sensor.currentSampleCount = 0;
  sensor.busVoltageSampleCursor = 0;
  sensor.currentSampleCursor = 0;
  sensor.hasReading = false;
  sensor.lastRawBusVoltage = 0.0f;
  sensor.lastRawShuntVoltage = 0.0f;
  sensor.lastRawSupplyVoltage = 0.0f;
  sensor.lastRawCurrent = 0.0f;
  sensor.lastSmoothedBusVoltage = 0.0f;
  sensor.lastSmoothedCurrent = 0.0f;
  sensor.lastCorrectedBusVoltage = 0.0f;
  sensor.lastCorrectedSupplyVoltage = 0.0f;
  sensor.lastCorrectedCurrent = 0.0f;
  sensor.lastSeq = 0;

  for (int i = 0; i < MAX_AVG_WINDOW; i++) {
    sensor.busVoltageSamples[i] = 0.0f;
    sensor.currentSamples[i] = 0.0f;
  }
}

String currentDisplayText(float currentMilliAmps) {
  if (!isfinite(currentMilliAmps)) {
    return "I nan";
  }
  if (fabsf(currentMilliAmps) >= 1000.0f) {
    return "I " + formatFloat(currentMilliAmps / 1000.0f, 3) + "A";
  }
  return "I " + formatFloat(currentMilliAmps, 1) + "mA";
}

void applyConfigDefaults(RuntimeConfig& config) {
  if (config.serverPort == 0) {
    config.serverPort = DEFAULT_SERVER_PORT;
  }
  if (trimCopy(config.deviceId).length() == 0) {
    config.deviceId = defaultDeviceId();
  }
  if (config.avgWindow == 0 || config.avgWindow > MAX_AVG_WINDOW) {
    config.avgWindow = DEFAULT_AVG_WINDOW;
  }
  if (!isSupportedHwAverage(config.inaHwAvg)) {
    config.inaHwAvg = DEFAULT_INA_HW_AVG;
  }

  for (int i = 0; i < MAX_SENSORS; i++) {
    calibrationProfiles[i].address = INA_ADDRS[i];
    if (!(calibrationProfiles[i].busVoltageGain > 0.0f) || !isfinite(calibrationProfiles[i].busVoltageGain)) {
      calibrationProfiles[i].busVoltageGain = 1.0f;
    }
    if (!isfinite(calibrationProfiles[i].busVoltageOffset)) {
      calibrationProfiles[i].busVoltageOffset = 0.0f;
    }
    if (!(calibrationProfiles[i].currentGain > 0.0f) || !isfinite(calibrationProfiles[i].currentGain)) {
      calibrationProfiles[i].currentGain = 1.0f;
    }
    if (!isfinite(calibrationProfiles[i].currentOffset)) {
      calibrationProfiles[i].currentOffset = 0.0f;
    }
  }
}

void writeCalibrationConfig(File& file) {
  for (int i = 0; i < MAX_SENSORS; i++) {
    CalibrationProfile& profile = calibrationProfiles[i];
    String addressLabel = sensorAddressLabel(profile.address);
    file.println("sensor_" + addressLabel + "_bus_voltage_gain=" + formatFloat(profile.busVoltageGain, 6));
    file.println("sensor_" + addressLabel + "_bus_voltage_offset=" + formatFloat(profile.busVoltageOffset, 6));
    file.println("sensor_" + addressLabel + "_current_gain=" + formatFloat(profile.currentGain, 6));
    file.println("sensor_" + addressLabel + "_current_offset=" + formatFloat(profile.currentOffset, 6));
  }
}

bool applyCalibrationValue(const String& key, const String& value) {
  if (!key.startsWith("sensor_0x")) {
    return false;
  }

  int secondUnderscore = key.indexOf('_', 10);
  if (secondUnderscore < 0) {
    return false;
  }

  String addressHex = key.substring(7, secondUnderscore);
  long address = strtol(addressHex.c_str(), nullptr, 16);
  int slot = sensorAddressSlot(static_cast<uint8_t>(address));
  if (slot < 0) {
    return false;
  }

  String field = key.substring(secondUnderscore + 1);
  float parsed = 0.0f;
  if (!parseFloatStrict(value, parsed)) {
    return false;
  }

  CalibrationProfile& profile = calibrationProfiles[slot];
  profile.address = static_cast<uint8_t>(address);
  if (field == "bus_voltage_gain" && parsed > 0.0f) {
    profile.busVoltageGain = parsed;
    return true;
  }
  if (field == "bus_voltage_offset") {
    profile.busVoltageOffset = parsed;
    return true;
  }
  if (field == "current_gain" && parsed > 0.0f) {
    profile.currentGain = parsed;
    return true;
  }
  if (field == "current_offset") {
    profile.currentOffset = parsed;
    return true;
  }
  return false;
}

String healthUrl(const RuntimeConfig& config) {
  return "http://" + config.serverHost + ":" + String(config.serverPort) + "/health";
}

String ingestUrl(const RuntimeConfig& config) {
  return "http://" + config.serverHost + ":" + String(config.serverPort) + "/api/v1/readings/batch";
}

bool syncRtcFromNtp(unsigned long timeoutMs) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("RTC sync skipped: WiFi not connected");
    return false;
  }

  configTime(0, 0, NTP_SERVER_1, NTP_SERVER_2);
  Serial.println("Syncing RTC from NTP...");

  time_t now = time(nullptr);
  unsigned long startedAt = millis();
  while (now < 1700000000 && millis() - startedAt < timeoutMs) {
    delay(200);
    yield();
    now = time(nullptr);
  }

  if (now < 1700000000) {
    Serial.println("RTC sync failed: NTP timeout");
    return false;
  }

  if (rtcAvailable) {
    rtc.adjust(DateTime(static_cast<uint32_t>(now)));
    rtcHasValidTime = true;
  }
  Serial.printf("RTC synced from NTP: %lu\n", static_cast<unsigned long>(now));
  return true;
}

void updateRtcValidityFromHardware() {
  rtcHasValidTime = false;
  if (!rtcAvailable) {
    return;
  }

  if (rtc.lostPower()) {
    Serial.println("RTC lost power; awaiting NTP sync");
    return;
  }

  DateTime now = rtc.now();
  if (now.unixtime() < 1700000000UL) {
    Serial.printf("RTC time invalid: %04d-%02d-%02dT%02d:%02d:%02dZ\n",
                  now.year(), now.month(), now.day(),
                  now.hour(), now.minute(), now.second());
    return;
  }

  rtcHasValidTime = true;
}

void maybeSyncRtcDuringRuntime(unsigned long now) {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  if (rtcHasValidTime && (now - lastNtpSyncAttempt) < NTP_RESYNC_INTERVAL_MS) {
    return;
  }

  lastNtpSyncAttempt = now;
  if (syncRtcFromNtp(NTP_SYNC_TIMEOUT_MS)) {
    lastHealthStatus = "RTC synced";
  } else if (!rtcHasValidTime) {
    lastHealthStatus = "RTC unsynced";
  }
}

bool isConfigShapeValid(const RuntimeConfig& config, String& reason) {
  if (trimCopy(config.ssid).length() == 0) {
    reason = "WiFi SSID required";
    return false;
  }
  if (trimCopy(config.serverHost).length() == 0) {
    reason = "Server host required";
    return false;
  }
  if (config.serverPort == 0) {
    reason = "Server port invalid";
    return false;
  }
  if (config.avgWindow == 0 || config.avgWindow > MAX_AVG_WINDOW) {
    reason = "Average window must be 1-32";
    return false;
  }
  if (!isSupportedHwAverage(config.inaHwAvg)) {
    reason = "HW average must be 1/2/4/8/16/32/64/128";
    return false;
  }
  for (int i = 0; i < MAX_SENSORS; i++) {
    const CalibrationProfile& profile = calibrationProfiles[i];
    if (!(profile.busVoltageGain > 0.0f) || !isfinite(profile.busVoltageGain)) {
      reason = "Bus voltage gain invalid for " + sensorAddressLabel(profile.address);
      return false;
    }
    if (!isfinite(profile.busVoltageOffset)) {
      reason = "Bus voltage offset invalid for " + sensorAddressLabel(profile.address);
      return false;
    }
    if (!(profile.currentGain > 0.0f) || !isfinite(profile.currentGain)) {
      reason = "Current gain invalid for " + sensorAddressLabel(profile.address);
      return false;
    }
    if (!isfinite(profile.currentOffset)) {
      reason = "Current offset invalid for " + sensorAddressLabel(profile.address);
      return false;
    }
  }
  return true;
}

// ================= STORAGE =================
bool mountStorage() {
  if (LittleFS.begin()) {
    return true;
  }

  Serial.println("LittleFS mount failed, attempting format");
  if (!LittleFS.format()) {
    return false;
  }

  return LittleFS.begin();
}

bool saveConfig(const RuntimeConfig& config) {
  RuntimeConfig normalized = config;
  applyConfigDefaults(normalized);

  File file = LittleFS.open(CONFIG_PATH, "w");
  if (!file) {
    return false;
  }

  file.println("ssid=" + normalized.ssid);
  file.println("password=" + normalized.password);
  file.println("server_host=" + normalized.serverHost);
  file.println("server_port=" + String(normalized.serverPort));
  file.println("api_key=" + normalized.apiKey);
  file.println("device_id=" + normalized.deviceId);
  file.println("avg_window=" + String(normalized.avgWindow));
  file.println("ina_hw_avg=" + String(normalized.inaHwAvg));
  writeCalibrationConfig(file);
  file.close();
  return true;
}

bool loadConfig(RuntimeConfig& config) {
  if (!LittleFS.exists(CONFIG_PATH)) {
    return false;
  }

  File file = LittleFS.open(CONFIG_PATH, "r");
  if (!file) {
    return false;
  }

  RuntimeConfig loaded;
  while (file.available()) {
    String line = file.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) {
      continue;
    }

    int separator = line.indexOf('=');
    if (separator <= 0) {
      continue;
    }

    String key = line.substring(0, separator);
    String value = line.substring(separator + 1);

    if (key == "ssid") {
      loaded.ssid = value;
    } else if (key == "password") {
      loaded.password = value;
    } else if (key == "server_host") {
      loaded.serverHost = value;
    } else if (key == "server_port") {
      int parsed = value.toInt();
      loaded.serverPort = parsed > 0 ? static_cast<uint16_t>(parsed) : DEFAULT_SERVER_PORT;
    } else if (key == "api_key") {
      loaded.apiKey = value;
    } else if (key == "device_id") {
      loaded.deviceId = value;
    } else if (key == "avg_window") {
      uint16_t parsed = 0;
      if (parseUInt16Strict(value, parsed) && parsed >= 1 && parsed <= MAX_AVG_WINDOW) {
        loaded.avgWindow = static_cast<uint8_t>(parsed);
      }
    } else if (key == "ina_hw_avg") {
      uint16_t parsed = 0;
      if (parseUInt16Strict(value, parsed) && isSupportedHwAverage(parsed)) {
        loaded.inaHwAvg = parsed;
      }
    } else {
      applyCalibrationValue(key, value);
    }
  }
  file.close();

  applyConfigDefaults(loaded);

  String reason;
  if (!isConfigShapeValid(loaded, reason)) {
    return false;
  }

  config = loaded;
  return true;
}

bool configureIna219Averaging(uint8_t address, uint16_t avgSamples) {
  uint16_t adcBits = hwAverageConfigBits(avgSamples);
  uint16_t configValue = INA219_CONFIG_BVOLTAGERANGE_32V |
                         INA219_CONFIG_GAIN_8_320MV |
                         adcBits |
                         (adcBits >> 4) |
                         INA219_CONFIG_MODE_SANDBVOLT_CONTINUOUS;

  Wire.beginTransmission(address);
  Wire.write(INA219_REG_CONFIG);
  Wire.write((configValue >> 8) & 0xFF);
  Wire.write(configValue & 0xFF);
  return Wire.endTransmission() == 0;
}

void bindCalibrationToSensor(SensorConfig& sensor) {
  CalibrationProfile& profile = calibrationForAddress(sensor.address);
  sensor.busVoltageGain = profile.busVoltageGain;
  sensor.busVoltageOffset = profile.busVoltageOffset;
  sensor.currentGain = profile.currentGain;
  sensor.currentOffset = profile.currentOffset;
  resetSensorSmoothing(sensor);
}

void applyRuntimeConfigToSensors() {
  for (int i = 0; i < sensorCount; i++) {
    bindCalibrationToSensor(sensors[i]);
  }
}

void refreshSensorRuntimeState() {
  applyRuntimeConfigToSensors();
  for (int i = 0; i < sensorCount; i++) {
    if (!configureIna219Averaging(sensors[i].address, currentConfig.inaHwAvg)) {
      Serial.printf("INA219 avg config failed at 0x%X, keeping current device config\n", sensors[i].address);
    }
    printSensorConfigSummary(sensors[i]);
  }
}

void printSensorConfigSummary(const SensorConfig& sensor) {
  Serial.printf(
      "Sensor 0x%02X idx=%d hwAvg=%u swAvg=%u bvGain=%.6f bvOffset=%.6f cGain=%.6f cOffset=%.6f\n",
      sensor.address,
      sensor.index,
      currentConfig.inaHwAvg,
      currentConfig.avgWindow,
      sensor.busVoltageGain,
      sensor.busVoltageOffset,
      sensor.currentGain,
      sensor.currentOffset);
}

float updateMovingAverage(float samples[], float& sum, uint8_t& sampleCount, uint8_t& sampleCursor, uint8_t window, float value) {
  if (window == 0) {
    return value;
  }

  if (sampleCount < window) {
    samples[sampleCursor] = value;
    sum += value;
    sampleCount++;
    sampleCursor = (sampleCursor + 1) % window;
    return sum / sampleCount;
  }

  sum -= samples[sampleCursor];
  samples[sampleCursor] = value;
  sum += value;
  sampleCursor = (sampleCursor + 1) % window;
  return sum / window;
}

void syncPortalDraftCalibrationFromProfiles() {
  portalAvgWindowInput = String(portalDraftConfig.avgWindow);
  portalHwAvgInput = String(portalDraftConfig.inaHwAvg);
  for (int i = 0; i < MAX_SENSORS; i++) {
    portalCalibrationDrafts[i].busVoltageGain = formatFloat(calibrationProfiles[i].busVoltageGain, 6);
    portalCalibrationDrafts[i].busVoltageOffset = formatFloat(calibrationProfiles[i].busVoltageOffset, 6);
    portalCalibrationDrafts[i].currentGain = formatFloat(calibrationProfiles[i].currentGain, 6);
    portalCalibrationDrafts[i].currentOffset = formatFloat(calibrationProfiles[i].currentOffset, 6);
  }
}

String portalCalibrationArgName(uint8_t address, const String& suffix) {
  return "sensor_" + sensorAddressLabel(address) + "_" + suffix;
}

bool parsePortalCalibration(RuntimeConfig& submitted, String& reason) {
  uint16_t avgWindow = 0;
  if (!parseUInt16Strict(portalAvgWindowInput, avgWindow) || avgWindow < 1 || avgWindow > MAX_AVG_WINDOW) {
    reason = "Average window must be 1-32";
    return false;
  }
  submitted.avgWindow = static_cast<uint8_t>(avgWindow);

  uint16_t hwAvg = 0;
  if (!parseUInt16Strict(portalHwAvgInput, hwAvg) || !isSupportedHwAverage(hwAvg)) {
    reason = "HW average must be 1,2,4,8,16,32,64,128";
    return false;
  }
  submitted.inaHwAvg = hwAvg;

  for (int i = 0; i < MAX_SENSORS; i++) {
    CalibrationProfile& profile = calibrationProfiles[i];
    float parsed = 0.0f;

    if (!parseFloatStrict(portalCalibrationDrafts[i].busVoltageGain, parsed) || !(parsed > 0.0f)) {
      reason = "Bus voltage gain invalid for " + sensorAddressLabel(profile.address);
      return false;
    }
    profile.busVoltageGain = parsed;

    if (!parseFloatStrict(portalCalibrationDrafts[i].busVoltageOffset, parsed)) {
      reason = "Bus voltage offset invalid for " + sensorAddressLabel(profile.address);
      return false;
    }
    profile.busVoltageOffset = parsed;

    if (!parseFloatStrict(portalCalibrationDrafts[i].currentGain, parsed) || !(parsed > 0.0f)) {
      reason = "Current gain invalid for " + sensorAddressLabel(profile.address);
      return false;
    }
    profile.currentGain = parsed;

    if (!parseFloatStrict(portalCalibrationDrafts[i].currentOffset, parsed)) {
      reason = "Current offset invalid for " + sensorAddressLabel(profile.address);
      return false;
    }
    profile.currentOffset = parsed;
  }

  return true;
}

// ================= OLED =================
void drawScreen(const String lines[], size_t lineCount) {
  if (!oledAvailable) {
    return;
  }

  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);

  for (size_t i = 0; i < lineCount; i++) {
    display.println(lines[i]);
  }

  display.display();
}

void refreshDisplay() {
  String lines[6];

  switch (deviceState) {
    case BOOT_INIT:
      lines[0] = "DataLogger";
      lines[1] = "Booting...";
      lines[2] = "OLED " + String(oledAvailable ? "OK" : "OFF");
      lines[3] = "RTC " + String(rtcAvailable ? "OK" : "MISS");
      lines[4] = "Sensors " + String(sensorCount);
      break;
    case LOAD_CONFIG:
      lines[0] = "Loading config";
      lines[1] = configLoaded ? "Config found" : "Config missing";
      lines[2] = shortText(hostLabel(), 20);
      if (lastError.length()) {
        lines[3] = shortText(lastError, 20);
      }
      break;
    case WIFI_CONNECTING:
      lines[0] = "WiFi connect";
      lines[1] = shortText(attemptedConfig.ssid, 20);
      lines[2] = "Wait " + String((millis() - stateStartedAt) / 1000) + "s";
      lines[3] = shortText(lastError, 20);
      break;
    case SERVER_VERIFYING:
      lines[0] = "Server verify";
      lines[1] = shortText(attemptedConfig.serverHost, 20);
      lines[2] = "Port " + String(attemptedConfig.serverPort);
      lines[3] = shortText(lastHealthStatus, 20);
      break;
    case RUNNING:
      if (sensorCount == 1) {
        SensorConfig& sensor = sensors[0];
        lines[0] = "Running";
        lines[1] = "INA " + sensorAddressLabel(sensor.address);
        if (sensor.hasReading) {
          lines[2] = "BV " + formatFloat(sensor.lastCorrectedBusVoltage, 3);
          lines[3] = currentDisplayText(sensor.lastCorrectedCurrent);
        } else {
          lines[2] = "Waiting read";
          lines[3] = "Buf " + String(buffer.size());
        }
        lines[4] = shortText(WiFi.status() == WL_CONNECTED ? lastUploadStatus : "WiFi down", 20);
        lines[5] = shortText(hostLabel(), 20);
      } else {
        lines[0] = "Running";
        lines[1] = shortText(currentConfig.deviceId, 20);
        lines[2] = WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "WiFi down";
        lines[3] = "Sensors " + String(sensorCount) + " Buf " + String(buffer.size());
        lines[4] = shortText(lastUploadStatus, 20);
        lines[5] = shortText(hostLabel(), 20);
      }
      break;
    case PROVISION_AP_START:
      lines[0] = "Starting AP";
      lines[1] = shortText(apSsid, 20);
      break;
    case PROVISION_AP_ACTIVE:
      lines[0] = "Provision AP";
      lines[1] = shortText(apSsid, 20);
      lines[2] = apIpString();
      lines[3] = "Open / in browser";
      lines[4] = shortText(portalMessage, 20);
      break;
    case PROVISION_AP_SUBMITTED:
      lines[0] = "Validating";
      lines[1] = shortText(attemptedConfig.ssid, 20);
      lines[2] = shortText(attemptedConfig.serverHost, 20);
      lines[3] = shortText(portalMessage, 20);
      break;
    case ERROR_RECOVERABLE:
      lines[0] = "Recoverable err";
      lines[1] = shortText(lastError, 20);
      lines[2] = "Returning to AP";
      break;
  }

  drawScreen(lines, 6);
}

void initDisplay() {
  oledAvailable = display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDRESS);
  if (!oledAvailable) {
    Serial.println("OLED init failed");
    return;
  }

  display.clearDisplay();
  display.display();
}

void maybeRefreshDisplay(unsigned long now) {
  if (now - lastOledRefresh < OLED_REFRESH_MS) {
    return;
  }
  lastOledRefresh = now;
  refreshDisplay();
}

// ================= SENSOR MANAGER =================
void detectSensors() {
  Serial.println("Scanning INA219 sensors...");

  sensorCount = 0;
  for (int i = 0; i < MAX_SENSORS; i++) {
    uint8_t addr = INA_ADDRS[i];

    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Adafruit_INA219* candidate = new Adafruit_INA219(addr);
      if (candidate->begin()) {
        if (!configureIna219Averaging(addr, currentConfig.inaHwAvg)) {
          Serial.printf("INA219 avg config failed at 0x%X, using library defaults\n", addr);
        }
        sensors[sensorCount].address = addr;
        sensors[sensorCount].index = sensorCount;
        sensors[sensorCount].active = true;
        sensors[sensorCount].ina = candidate;
        bindCalibrationToSensor(sensors[sensorCount]);
        Serial.printf("Sensor found at 0x%X -> index %d\n", addr, sensorCount);
        sensorCount++;
      } else {
        Serial.printf("Sensor init failed at 0x%X\n", addr);
        delete candidate;
      }
    }
  }

  Serial.printf("Total sensors detected: %d\n", sensorCount);
}

void readSensors() {
  if (sensorCount == 0) {
    lastUploadStatus = "No sensors";
    return;
  }

  Reading reading;
  reading.seq = seqCounter++;
  reading.timestamp = currentTimestamp();
  reading.sensorCount = sensorCount;

  for (int i = 0; i < sensorCount; i++) {
    SensorConfig& sensor = sensors[i];
    float rawBusVoltage = sensor.ina->getBusVoltage_V();
    float rawShuntVoltage = sensor.ina->getShuntVoltage_mV();
    float rawCurrent = sensor.ina->getCurrent_mA();
    float rawSupplyVoltage = rawBusVoltage + (rawShuntVoltage / 1000.0f);
    float smoothedBusVoltage = updateMovingAverage(
        sensor.busVoltageSamples,
        sensor.busVoltageSum,
        sensor.busVoltageSampleCount,
        sensor.busVoltageSampleCursor,
        currentConfig.avgWindow,
        rawBusVoltage);
    float smoothedCurrent = updateMovingAverage(
        sensor.currentSamples,
        sensor.currentSum,
        sensor.currentSampleCount,
        sensor.currentSampleCursor,
        currentConfig.avgWindow,
        rawCurrent);
    float correctedBusVoltage = smoothedBusVoltage * sensor.busVoltageGain + sensor.busVoltageOffset;
    float correctedSupplyVoltage = correctedBusVoltage + (rawShuntVoltage / 1000.0f);
    float correctedCurrent = smoothedCurrent * sensor.currentGain + sensor.currentOffset;

    sensor.hasReading = true;
    sensor.lastSeq = reading.seq;
    sensor.lastRawBusVoltage = rawBusVoltage;
    sensor.lastRawShuntVoltage = rawShuntVoltage;
    sensor.lastRawSupplyVoltage = rawSupplyVoltage;
    sensor.lastRawCurrent = rawCurrent;
    sensor.lastSmoothedBusVoltage = smoothedBusVoltage;
    sensor.lastSmoothedCurrent = smoothedCurrent;
    sensor.lastCorrectedBusVoltage = correctedBusVoltage;
    sensor.lastCorrectedSupplyVoltage = correctedSupplyVoltage;
    sensor.lastCorrectedCurrent = correctedCurrent;

    reading.sensorData[i] = {sensor.index, correctedBusVoltage, rawShuntVoltage, correctedSupplyVoltage, correctedCurrent};
  }

  buffer.push(reading);
  Serial.printf("Reading added | seq=%lu | buffer=%d\n", reading.seq, buffer.size());
}

// ================= PORTAL =================
String renderProvisionPage() {
  String page;
  page.reserve(5200);
  page += "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">";
  page += "<title>DataLogger Provisioning</title>";
  page += "<style>body{font-family:Arial,sans-serif;background:#f4f1ea;margin:0;padding:24px;color:#1f2933;}";
  page += "main{max-width:560px;margin:0 auto;background:#fff;padding:24px;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.08);}";
  page += "h1{margin-top:0;}label{display:block;margin:12px 0 6px;font-weight:700;}input{width:100%;padding:10px;border:1px solid #cbd2d9;border-radius:10px;box-sizing:border-box;}";
  page += "button{margin-top:18px;background:#0f766e;color:#fff;border:0;padding:12px 16px;border-radius:10px;font-weight:700;width:100%;}";
  page += ".msg{margin:0 0 16px;padding:12px;background:#fef3c7;border-radius:10px;}.section{margin-top:24px;padding-top:12px;border-top:1px solid #e5e7eb;}";
  page += ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;}.card{margin-top:16px;padding:16px;background:#f8fafc;border-radius:12px;}</style></head><body><main>";
  page += "<h1>DataLogger Setup</h1>";
  page += "<p>Connect device Wi-Fi and backend settings. This device will test Wi-Fi and <code>/health</code> before entering run mode.</p>";
  if (portalMessage.length()) {
    page += "<div class=\"msg\">" + htmlEscape(portalMessage) + "</div>";
  }
  page += "<form method=\"POST\" action=\"/provision\">";
  page += "<label for=\"ssid\">Wi-Fi SSID</label><input id=\"ssid\" name=\"ssid\" value=\"" + htmlEscape(portalDraftConfig.ssid) + "\" required>";
  page += "<label for=\"password\">Wi-Fi Password</label><input id=\"password\" name=\"password\" type=\"password\" value=\"" + htmlEscape(portalDraftConfig.password) + "\">";
  page += "<label for=\"server_host\">Server Host/IP</label><input id=\"server_host\" name=\"server_host\" value=\"" + htmlEscape(portalDraftConfig.serverHost) + "\" required>";
  page += "<label for=\"server_port\">Server Port</label><input id=\"server_port\" name=\"server_port\" type=\"number\" min=\"1\" max=\"65535\" value=\"" + String(portalDraftConfig.serverPort ? portalDraftConfig.serverPort : DEFAULT_SERVER_PORT) + "\" placeholder=\"" + String(DEFAULT_SERVER_PORT) + "\">";
  page += "<label for=\"api_key\">API Key</label><input id=\"api_key\" name=\"api_key\" value=\"" + htmlEscape(portalDraftConfig.apiKey) + "\">";
  page += "<label for=\"device_id\">Device ID</label><input id=\"device_id\" name=\"device_id\" value=\"" + htmlEscape(portalDraftConfig.deviceId) + "\" placeholder=\"" + htmlEscape(defaultDeviceId()) + "\">";
  page += "<div class=\"section\"><h2>Averaging</h2>";
  page += "<div class=\"grid\">";
  page += "<div><label for=\"avg_window\">Software Average Window</label><input id=\"avg_window\" name=\"avg_window\" type=\"number\" min=\"1\" max=\"32\" value=\"" + htmlEscape(portalAvgWindowInput) + "\"></div>";
  page += "<div><label for=\"ina_hw_avg\">INA219 HW Samples</label><input id=\"ina_hw_avg\" name=\"ina_hw_avg\" type=\"number\" min=\"1\" max=\"128\" step=\"1\" value=\"" + htmlEscape(portalHwAvgInput) + "\"></div>";
  page += "</div></div>";
  page += "<div class=\"section\"><h2>Per-Sensor Calibration</h2>";
  for (int i = 0; i < MAX_SENSORS; i++) {
    String addressLabel = sensorAddressLabel(calibrationProfiles[i].address);
    page += "<div class=\"card\"><strong>INA219 " + addressLabel + "</strong><div class=\"grid\">";
    page += "<div><label for=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "bus_voltage_gain") + "\">Bus Voltage Gain</label><input id=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "bus_voltage_gain") + "\" name=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "bus_voltage_gain") + "\" value=\"" + htmlEscape(portalCalibrationDrafts[i].busVoltageGain) + "\"></div>";
    page += "<div><label for=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "bus_voltage_offset") + "\">Bus Voltage Offset</label><input id=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "bus_voltage_offset") + "\" name=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "bus_voltage_offset") + "\" value=\"" + htmlEscape(portalCalibrationDrafts[i].busVoltageOffset) + "\"></div>";
    page += "<div><label for=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "current_gain") + "\">Current Gain</label><input id=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "current_gain") + "\" name=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "current_gain") + "\" value=\"" + htmlEscape(portalCalibrationDrafts[i].currentGain) + "\"></div>";
    page += "<div><label for=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "current_offset") + "\">Current Offset</label><input id=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "current_offset") + "\" name=\"" + portalCalibrationArgName(calibrationProfiles[i].address, "current_offset") + "\" value=\"" + htmlEscape(portalCalibrationDrafts[i].currentOffset) + "\"></div>";
    page += "</div></div>";
  }
  page += "</div>";
  page += "<button type=\"submit\">Save and Validate</button></form></main></body></html>";
  return page;
}

void handlePortalRoot() {
  portalServer.send(200, "text/html", renderProvisionPage());
}

void handlePortalProvision() {
  RuntimeConfig submitted;
  submitted.ssid = trimCopy(portalServer.arg("ssid"));
  submitted.password = portalServer.arg("password");
  submitted.serverHost = trimCopy(portalServer.arg("server_host"));
  submitted.apiKey = trimCopy(portalServer.arg("api_key"));
  submitted.deviceId = trimCopy(portalServer.arg("device_id"));
  portalAvgWindowInput = trimCopy(portalServer.arg("avg_window"));
  portalHwAvgInput = trimCopy(portalServer.arg("ina_hw_avg"));

  for (int i = 0; i < MAX_SENSORS; i++) {
    uint8_t address = calibrationProfiles[i].address;
    portalCalibrationDrafts[i].busVoltageGain = trimCopy(portalServer.arg(portalCalibrationArgName(address, "bus_voltage_gain")));
    portalCalibrationDrafts[i].busVoltageOffset = trimCopy(portalServer.arg(portalCalibrationArgName(address, "bus_voltage_offset")));
    portalCalibrationDrafts[i].currentGain = trimCopy(portalServer.arg(portalCalibrationArgName(address, "current_gain")));
    portalCalibrationDrafts[i].currentOffset = trimCopy(portalServer.arg(portalCalibrationArgName(address, "current_offset")));
  }

  int port = portalServer.arg("server_port").toInt();
  submitted.serverPort = port > 0 ? static_cast<uint16_t>(port) : DEFAULT_SERVER_PORT;

  String reason;
  portalDraftConfig = submitted;
  if (!parsePortalCalibration(submitted, reason)) {
    portalMessage = reason;
    portalServer.send(400, "text/html", renderProvisionPage());
    return;
  }
  applyConfigDefaults(submitted);
  if (!isConfigShapeValid(submitted, reason)) {
    portalMessage = reason;
    portalServer.send(400, "text/html", renderProvisionPage());
    return;
  }

  if (!saveConfig(submitted)) {
    portalMessage = "Failed to save config";
    portalServer.send(500, "text/html", renderProvisionPage());
    return;
  }

  portalMessage = "Saved locally, validating WiFi and server...";
  portalServer.send(200, "text/html", renderProvisionPage());

  attemptedConfig = submitted;
  currentConfig = submitted;
  refreshSensorRuntimeState();
  wifiConnectStarted = false;
  lastError = "";
  setState(PROVISION_AP_SUBMITTED);
}

void handlePortalNotFound() {
  portalServer.sendHeader("Location", "/", true);
  portalServer.send(302, "text/plain", "");
}

void startProvisioningPortal() {
  if (portalActive) {
    setState(PROVISION_AP_ACTIVE);
    return;
  }

  WiFi.mode(WIFI_AP_STA);
  apSsid = String(AP_SSID_PREFIX) + "-" + String(ESP.getChipId(), HEX);
  WiFi.softAP(apSsid.c_str());

  portalServer.on("/", HTTP_GET, handlePortalRoot);
  portalServer.on("/provision", HTTP_POST, handlePortalProvision);
  portalServer.onNotFound(handlePortalNotFound);
  portalServer.begin();

  portalActive = true;
  portalMessage = portalMessage.length() ? portalMessage : "Enter WiFi and server details";
  Serial.printf("Provisioning AP active SSID=%s IP=%s\n", apSsid.c_str(), apIpString().c_str());
  setState(PROVISION_AP_ACTIVE);
}

void stopProvisioningPortal() {
  if (!portalActive) {
    return;
  }

  portalServer.stop();
  WiFi.softAPdisconnect(true);
  portalActive = false;
  portalMessage = "";
}

// ================= NETWORK =================
void startWiFiConnect(const RuntimeConfig& config) {
  attemptedConfig = config;
  wifiConnectStarted = true;
  lastError = "";
  ntpSyncStartedAt = 0;
  lastNtpSyncAttempt = 0;

  WiFi.persistent(false);
  WiFi.mode(portalActive ? WIFI_AP_STA : WIFI_STA);
  WiFi.disconnect();
  WiFi.begin(config.ssid.c_str(), config.password.c_str());

  setState(WIFI_CONNECTING);
  Serial.printf("Connecting to WiFi SSID=%s\n", config.ssid.c_str());
}

bool verifyServerHealth(const RuntimeConfig& config, String& reason) {
  if (WiFi.status() != WL_CONNECTED) {
    reason = "WiFi not connected";
    return false;
  }

  WiFiClient client;
  client.setTimeout(HEALTHCHECK_TIMEOUT_MS / 1000);

  HTTPClient http;
  String url = healthUrl(config);
  if (!http.begin(client, url)) {
    reason = "Health request setup failed";
    return false;
  }

  http.setTimeout(HEALTHCHECK_TIMEOUT_MS);
  if (config.apiKey.length() > 0) {
    http.addHeader("X-API-Key", config.apiKey);
  }

  int httpCode = http.GET();
  http.end();

  if (httpCode == 200) {
    reason = "Health OK";
    return true;
  }
  if (httpCode == 401) {
    reason = "Invalid API key";
    return false;
  }
  if (httpCode <= 0) {
    reason = "Server unreachable";
    return false;
  }

  reason = "Health HTTP " + String(httpCode);
  return false;
}

bool sendBatch() {
  if (buffer.isEmpty()) {
    lastUploadStatus = "Buffer empty";
    return true;
  }

  if (WiFi.status() != WL_CONNECTED) {
    lastUploadStatus = "WiFi disconnected";
    return false;
  }

  WiFiClient client;
  client.setTimeout(HEALTHCHECK_TIMEOUT_MS / 1000);

  HTTPClient http;
  String url = ingestUrl(currentConfig);
  if (!http.begin(client, url)) {
    lastUploadStatus = "Upload setup failed";
    return false;
  }

  http.setTimeout(HEALTHCHECK_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  if (currentConfig.apiKey.length() > 0) {
    http.addHeader("X-API-Key", currentConfig.apiKey);
  }

  String payload;
  payload.reserve(4096);
  payload = "{";
  payload += "\"device_id\":\"" + currentConfig.deviceId + "\",";
  payload += "\"boot_id\":\"" + bootId + "\",";
  payload += "\"batch\":[";

  int batchSize = min(buffer.size(), MAX_BATCH_ITEMS);
  for (int i = 0; i < batchSize; i++) {
    Reading& reading = buffer.get(i);
    payload += "{";
    payload += "\"seq\":" + String(reading.seq) + ",";
    payload += "\"timestamp\":\"" + reading.timestamp + "\",";
    payload += "\"sensors\":[";

    for (int j = 0; j < reading.sensorCount; j++) {
      payload += "{";
      payload += "\"sensor_index\":" + String(reading.sensorData[j].sensor_index) + ",";
      payload += "\"bus_voltage\":" + String(reading.sensorData[j].busVoltage, 3) + ",";
      payload += "\"shunt_voltage\":" + String(reading.sensorData[j].shuntVoltage, 3) + ",";
      payload += "\"supply_voltage\":" + String(reading.sensorData[j].supplyVoltage, 3) + ",";
      payload += "\"current\":" + String(reading.sensorData[j].current, 3);
      payload += "}";
      if (j < reading.sensorCount - 1) {
        payload += ",";
      }
    }

    payload += "]}";
    if (i < batchSize - 1) {
      payload += ",";
    }
  }
  payload += "]}";

  int httpCode = http.POST(payload);
  http.end();

  if (httpCode == 200) {
    buffer.pop(batchSize);
    lastUploadStatus = "Upload ok " + String(batchSize);
    Serial.printf("Batch sent OK (%d items) | boot_id=%s | dropped=%lu\n", batchSize, bootId.c_str(), buffer.dropped());
    return true;
  }

  lastUploadStatus = httpCode == 401 ? "Upload auth fail" : "Upload fail " + String(httpCode);
  Serial.printf("Send failed: %d\n", httpCode);
  return false;
}

void ensureRuntimeWiFi(unsigned long now) {
  if (WiFi.status() == WL_CONNECTED) {
    maybeSyncRtcDuringRuntime(now);
    return;
  }

  if (now - lastWiFiRetry < WIFI_RETRY_INTERVAL_MS) {
    return;
  }

  lastWiFiRetry = now;
  WiFi.mode(WIFI_STA);
  WiFi.begin(currentConfig.ssid.c_str(), currentConfig.password.c_str());
  lastUploadStatus = "WiFi reconnecting";
}

// ================= STATE MACHINE =================
void handleBootFlow() {
  setState(LOAD_CONFIG);
  configLoaded = loadConfig(currentConfig);
  applyConfigDefaults(currentConfig);
  portalDraftConfig = currentConfig;
  syncPortalDraftCalibrationFromProfiles();

  if (!configLoaded) {
    portalMessage = "No saved config found";
    lastError = "Config missing";
    setState(PROVISION_AP_START);
    return;
  }

  refreshBootId(currentConfig);
  refreshSensorRuntimeState();
  startWiFiConnect(currentConfig);
}

void handleWiFiConnecting(unsigned long now) {
  if (WiFi.status() == WL_CONNECTED) {
    if (rtcHasValidTime) {
      lastHealthStatus = "RTC synced, checking /health";
      setState(SERVER_VERIFYING);
      return;
    }

    if (ntpSyncStartedAt == 0) {
      ntpSyncStartedAt = now;
    }

    if (now - lastNtpSyncAttempt >= NTP_SYNC_TIMEOUT_MS) {
      lastHealthStatus = "Syncing RTC";
      lastNtpSyncAttempt = now;
      if (syncRtcFromNtp(NTP_SYNC_TIMEOUT_MS)) {
        lastHealthStatus = "RTC synced, checking /health";
        setState(SERVER_VERIFYING);
        return;
      }
    }

    if (now - ntpSyncStartedAt >= NTP_SYNC_MAX_WAIT_MS) {
      lastError = "RTC sync timeout";
      lastHealthStatus = "RTC sync failed";
      portalMessage = "Connected to WiFi, but time sync failed. Check internet access or NTP reachability and retry.";
      setState(PROVISION_AP_START);
    }
    return;
  }

  if (now - stateStartedAt >= WIFI_CONNECT_TIMEOUT_MS) {
    lastError = "WiFi connect timeout";
    portalMessage = "WiFi failed. Update credentials and retry.";
    setState(PROVISION_AP_START);
  }
}

void handleServerVerifying() {
  String reason;
  bool ok = verifyServerHealth(attemptedConfig, reason);
  lastHealthStatus = reason;

  if (ok) {
    currentConfig = attemptedConfig;
    portalDraftConfig = currentConfig;
    syncPortalDraftCalibrationFromProfiles();
    refreshBootId(currentConfig);
    refreshSensorRuntimeState();
    stopProvisioningPortal();
    WiFi.mode(WIFI_STA);
    lastError = "";
    lastUploadStatus = "Ready";
    setState(RUNNING);
    return;
  }

  lastError = reason;
  portalMessage = reason + ". Update settings and retry.";
  setState(PROVISION_AP_START);
}

void handleStateMachine(unsigned long now) {
  switch (deviceState) {
    case BOOT_INIT:
      handleBootFlow();
      break;
    case LOAD_CONFIG:
      handleBootFlow();
      break;
    case WIFI_CONNECTING:
      handleWiFiConnecting(now);
      break;
    case SERVER_VERIFYING:
      handleServerVerifying();
      break;
    case RUNNING:
      break;
    case PROVISION_AP_START:
      startProvisioningPortal();
      break;
    case PROVISION_AP_ACTIVE:
      break;
    case PROVISION_AP_SUBMITTED:
      if (!wifiConnectStarted) {
        startWiFiConnect(attemptedConfig);
      }
      break;
    case ERROR_RECOVERABLE:
      setState(PROVISION_AP_START);
      break;
  }
}

// ================= SETUP =================
void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(100000);
  applyConfigDefaults(currentConfig);
  portalDraftConfig = currentConfig;
  syncPortalDraftCalibrationFromProfiles();

  initDisplay();
  rtcAvailable = rtc.begin();
  if (!rtcAvailable) {
    Serial.println("RTC not found");
  } else {
    updateRtcValidityFromHardware();
  }

  if (!mountStorage()) {
    lastError = "LittleFS mount failed";
    portalMessage = "Storage unavailable";
  }

  detectSensors();
  refreshBootId(currentConfig);
  Serial.printf("Boot ready boot_id=%s sensors=%d seq_start=%lu\n",
                bootId.c_str(),
                sensorCount,
                static_cast<unsigned long>(seqCounter));
  setState(BOOT_INIT);
}

// ================= LOOP =================
void loop() {
  unsigned long now = millis();

  if (portalActive) {
    portalServer.handleClient();
  }

  handleStateMachine(now);

  if (deviceState == RUNNING) {
    if (now - lastRead >= READ_INTERVAL_MS) {
      lastRead = now;
      readSensors();
    }

    if (now - lastSend >= SEND_INTERVAL_MS) {
      lastSend = now;
      ensureRuntimeWiFi(now);
      if (WiFi.status() == WL_CONNECTED) {
        sendBatch();
      }
    }
  }

  maybeRefreshDisplay(now);
}
