// Cycle or train — Xteink X4 firmware.
//
// The device is deliberately dumb. Every wake it:
//   1. keeps itself powered (GPIO13 battery latch),
//   2. joins wifi and sets the clock over NTP,
//   3. downloads dashboard.bin — 48 000 bytes, exactly one screen of pixels,
//   4. draws a battery icon on top and refreshes the e-ink panel,
//   5. sleeps until the next 04:00 or 18:00.
// Pressing the power button wakes it early and shows a status screen first.

#include <Adafruit_GFX.h>
#include <BatteryMonitor.h>
#include <BoardConfig.h>
#include <EInkDisplay.h>
#include <HTTPClient.h>
#include <PowerManager.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <XteinkDetect.h>
#include <driver/gpio.h>
#include <esp_sleep.h>
#include <time.h>

#include "secrets.h"

#ifndef DISPLAY_ROTATE_180
#define DISPLAY_ROTATE_180 0
#endif

// ---- Pins (Xteink X4, from the FreeInk board profile) ----------------------
constexpr int8_t EPD_SCLK = 8, EPD_MOSI = 10, EPD_CS = 21, EPD_DC = 4, EPD_RST = 5, EPD_BUSY = 6;
constexpr int8_t SPI_MISO = 7;
constexpr gpio_num_t BATTERY_LATCH = GPIO_NUM_13;  // HIGH = stay powered from the battery

// ---- Schedule ----------------------------------------------------------------
constexpr int WAKE_HOURS[] = {4, 18};                              // local time
constexpr char TZ_AMSTERDAM[] = "CET-1CEST,M3.5.0,M10.5.0/3";      // handles summer time
constexpr uint64_t RETRY_SECONDS = 20 * 60;                        // after a failed download
constexpr uint64_t NO_CLOCK_SECONDS = 6 * 3600;                    // if NTP failed too
constexpr int MAX_RETRIES = 3;

// Survives deep sleep (lives in RTC memory), reset by a full power cycle.
RTC_DATA_ATTR uint32_t bootCount = 0;
RTC_DATA_ATTR uint8_t failedAttempts = 0;

EInkDisplay display(EPD_SCLK, EPD_MOSI, EPD_CS, EPD_DC, EPD_RST, EPD_BUSY);

// Adafruit GFX drawing straight into the display framebuffer.
// Framebuffer layout: 1 bit per pixel, 100 bytes per row, bit set = white.
class FrameCanvas : public Adafruit_GFX {
 public:
  explicit FrameCanvas(uint8_t* fb) : Adafruit_GFX(800, 480), fb_(fb) {}
  void drawPixel(int16_t x, int16_t y, uint16_t black) override {
    // Adafruit_GFX hands us rotated coordinates via the protected rotation state.
    switch (getRotation()) {
      case 2:
        x = WIDTH - 1 - x;
        y = HEIGHT - 1 - y;
        break;
      default:
        break;
    }
    if (x < 0 || y < 0 || x >= WIDTH || y >= HEIGHT) return;
    uint8_t& byte = fb_[y * (WIDTH / 8) + x / 8];
    const uint8_t bit = 0x80 >> (x & 7);
    if (black) byte &= ~bit; else byte |= bit;
  }

 private:
  uint8_t* fb_;
};

struct Fetch {
  bool wifi = false;
  bool clock = false;
  int httpCode = 0;
  size_t bytes = 0;
  int rssi = 0;
};

const char* wakeReasonName(esp_sleep_wakeup_cause_t c) {
  switch (c) {
    case ESP_SLEEP_WAKEUP_TIMER: return "timer";
    case ESP_SLEEP_WAKEUP_GPIO: return "button";
    case ESP_SLEEP_WAKEUP_UNDEFINED: return "power on";
    default: return "other";
  }
}

// ---- Networking --------------------------------------------------------------
bool connectWifi(uint32_t timeoutMs = 15000) {
  WiFi.mode(WIFI_STA);
#if USE_STATIC_IP
  WiFi.config(IPAddress(STATIC_IP), IPAddress(STATIC_GATEWAY), IPAddress(STATIC_SUBNET), IPAddress(STATIC_DNS));
#endif
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) delay(100);
  return WiFi.status() == WL_CONNECTED;
}

bool syncClock(uint32_t timeoutMs = 8000) {
  configTzTime(TZ_AMSTERDAM, "pool.ntp.org", "time.google.com");
  struct tm t;
  return getLocalTime(&t, timeoutMs) && t.tm_year > 120;
}

// Stream the file straight into the framebuffer. Returns bytes read.
size_t download(uint8_t* fb, size_t size, int& httpCode) {
  WiFiClientSecure client;
  client.setInsecure();  // it's a public weather picture; skipping cert checks keeps this tiny
  HTTPClient http;
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  http.setTimeout(15000);
  if (!http.begin(client, DASHBOARD_URL)) return 0;
  httpCode = http.GET();
  size_t got = 0;
  if (httpCode == HTTP_CODE_OK && http.getSize() == static_cast<int>(size)) {
    WiFiClient* s = http.getStreamPtr();
    const uint32_t start = millis();
    while (got < size && millis() - start < 20000) {
      const int n = s->readBytes(fb + got, size - got);
      if (n > 0) got += n; else delay(10);
    }
  }
  http.end();
  return got;
}

// ---- Drawing -----------------------------------------------------------------
void drawBattery(FrameCanvas& c, uint16_t percent) {
  // Top-right corner; the server leaves this area blank for us.
  const int x = 724, y = 24, w = 40, h = 18;
  c.fillRect(x - 4, y - 4, w + 12, h + 8, 0);  // clear
  c.drawRect(x, y, w, h, 1);
  c.drawRect(x + 1, y + 1, w - 2, h - 2, 1);
  c.fillRect(x + w, y + 5, 4, h - 10, 1);
  const int fill = (w - 6) * min<uint16_t>(percent, 100) / 100;
  c.fillRect(x + 3, y + 3, fill, h - 6, 1);
  if (percent < 15) {  // nudge to charge: an exclamation mark beside it
    c.fillRect(x - 10, y, 3, 11, 1);
    c.fillRect(x - 10, y + 14, 3, 3, 1);
  }
}

void drawStats(FrameCanvas& c, const Fetch& f, const BatteryMonitor& bat, esp_sleep_wakeup_cause_t wake, time_t nextWake) {
  display.clearScreen(0xFF);
  c.setTextColor(1);
  c.setTextSize(3);
  c.setCursor(30, 30);
  c.print("Cycle or train - status");
  c.drawFastHLine(30, 64, 740, 1);
  c.setTextSize(2);

  char line[96];
  int y = 90;
  auto row = [&](const char* k, const char* v) {
    c.setCursor(30, y);
    c.print(k);
    c.setCursor(260, y);
    c.print(v);
    y += 30;
  };
  snprintf(line, sizeof line, "%lu", static_cast<unsigned long>(bootCount)); row("Boots", line);
  row("Woke by", wakeReasonName(wake));
  snprintf(line, sizeof line, "%u%%  (%u mV)", bat.readPercentage(), bat.readMillivolts()); row("Battery", line);
  if (f.wifi) {
    snprintf(line, sizeof line, "%s  %d dBm  %s", WIFI_SSID, f.rssi, WiFi.localIP().toString().c_str());
  } else {
    snprintf(line, sizeof line, "could not join %s", WIFI_SSID);
  }
  row("Wifi", line);
  struct tm t;
  if (f.clock && getLocalTime(&t, 0)) strftime(line, sizeof line, "%a %d %b %H:%M", &t); else strcpy(line, "unknown");
  row("Time", line);
  snprintf(line, sizeof line, "HTTP %d, %u bytes", f.httpCode, static_cast<unsigned>(f.bytes)); row("Server", line);
  if (nextWake > 0) {
    localtime_r(&nextWake, &t);
    strftime(line, sizeof line, "%a %H:%M", &t);
  } else {
    snprintf(line, sizeof line, "in %u min", static_cast<unsigned>(RETRY_SECONDS / 60));
  }
  row("Next update", line);
  row("Panel", display.getControllerName());
  snprintf(line, sizeof line, "%u", failedAttempts); row("Failed tries", line);
}

// ---- Scheduling ----------------------------------------------------------------
// Seconds until the next WAKE_HOURS slot, at least 5 minutes away.
uint64_t secondsUntilNextSlot(time_t now, time_t& when) {
  struct tm t;
  localtime_r(&now, &t);
  time_t best = 0;
  for (int day = 0; day < 2 && !best; ++day) {
    for (int h : WAKE_HOURS) {
      struct tm c = t;
      c.tm_mday += day;
      c.tm_hour = h;
      c.tm_min = 0;
      c.tm_sec = 0;
      c.tm_isdst = -1;
      const time_t cand = mktime(&c);
      if (cand > now + 300 && (!best || cand < best)) best = cand;
    }
  }
  when = best;
  return static_cast<uint64_t>(best - now);
}

[[noreturn]] void sleepFor(uint64_t seconds) {
  display.deepSleep();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);

  // The trap from the blog post: stock firmware drops GPIO13 before sleeping,
  // which cuts the battery — so the timer can never wake us. Hold it HIGH.
  gpio_hold_dis(BATTERY_LATCH);
  gpio_set_direction(BATTERY_LATCH, GPIO_MODE_OUTPUT);
  gpio_set_level(BATTERY_LATCH, 1);
  gpio_hold_en(BATTERY_LATCH);

  esp_sleep_enable_timer_wakeup(seconds * 1000000ULL);
  freeink::PowerManager::waitForPowerButtonRelease();
  freeink::PowerManager::armPowerButtonWakeup();
  Serial.printf("Sleeping %llu s\n", seconds);
  Serial.flush();
  freeink::PowerManager::deepSleep();  // also arms gpio_deep_sleep_hold_en()
  while (true) {}
}

// ---- Main ----------------------------------------------------------------------
void setup() {
  // Latch power first, before anything slow can happen.
  gpio_hold_dis(BATTERY_LATCH);
  pinMode(BATTERY_LATCH, OUTPUT);
  digitalWrite(BATTERY_LATCH, HIGH);

  Serial.begin(115200);
  ++bootCount;
  const esp_sleep_wakeup_cause_t wake = esp_sleep_get_wakeup_cause();
  const bool showStats = wake != ESP_SLEEP_WAKEUP_TIMER;

  // Board + panel bring-up. Some X4 batches use a different panel controller;
  // applyXteinkDisplayController() detects that and picks the right driver.
  BoardConfig::selectDevice(BoardConfig::Board::XteinkX4);
  freeink::applyXteinkDisplayController();
  SPI.begin(EPD_SCLK, SPI_MISO, EPD_MOSI, EPD_CS);
  display.begin();

  BatteryMonitor battery;
  uint8_t* fb = display.getFrameBuffer();
  const size_t fbSize = display.getBufferSize();
  FrameCanvas canvas(fb);
  canvas.setRotation(DISPLAY_ROTATE_180 ? 2 : 0);

  Fetch f;
  f.wifi = connectWifi();
  if (f.wifi) {
    f.rssi = WiFi.RSSI();
    f.clock = syncClock();
    f.bytes = download(fb, fbSize, f.httpCode);
  }
  const bool ok = f.bytes == fbSize;
  failedAttempts = ok ? 0 : failedAttempts + 1;

  time_t nextWake = 0;
  uint64_t sleepSeconds;
  if (!ok && failedAttempts <= MAX_RETRIES) {
    sleepSeconds = RETRY_SECONDS;
  } else if (f.clock) {
    sleepSeconds = secondsUntilNextSlot(time(nullptr), nextWake);
  } else {
    sleepSeconds = NO_CLOCK_SECONDS;
  }
  Serial.printf("boot=%lu wake=%s wifi=%d http=%d bytes=%u\n", static_cast<unsigned long>(bootCount),
                wakeReasonName(wake), f.wifi, f.httpCode, static_cast<unsigned>(f.bytes));

  if (showStats) {
    // Stats replace the framebuffer, so keep the dashboard aside while they show.
    uint8_t* saved = ok ? static_cast<uint8_t*>(malloc(fbSize)) : nullptr;
    if (saved) memcpy(saved, fb, fbSize);
    canvas.setRotation(0);
    drawStats(canvas, f, battery, wake, nextWake);
    display.displayBuffer(EInkDisplay::FULL_REFRESH);
    delay(8000);
    canvas.setRotation(DISPLAY_ROTATE_180 ? 2 : 0);
    if (saved) {
      memcpy(fb, saved, fbSize);
      free(saved);
    }
  }

  if (ok) {
    drawBattery(canvas, battery.readPercentage());
    display.displayBuffer(EInkDisplay::FULL_REFRESH);
  }
  // On failure the panel keeps showing the last good picture: e-ink needs no power to hold it.

  sleepFor(sleepSeconds);
}

void loop() {}
