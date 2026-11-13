// Copy this file to secrets.h and fill it in. secrets.h is git-ignored, so your
// wifi password never ends up on GitHub.
#pragma once

#define WIFI_SSID "your-guest-network"
#define WIFI_PASSWORD "your-password"

// Where GitHub Pages publishes the dashboard: https://<github-user>.github.io/<repo>/dashboard.bin
#define DASHBOARD_URL "https://YOUR-USER.github.io/cycle-or-train/dashboard.bin"

// Optional static IP (skips DHCP, saves a second or two of radio time per wake).
// Leave USE_STATIC_IP at 0 unless you've reserved the address in your router.
#define USE_STATIC_IP 0
#define STATIC_IP 192, 168, 2, 50
#define STATIC_GATEWAY 192, 168, 2, 254
#define STATIC_SUBNET 255, 255, 255, 0
#define STATIC_DNS 1, 1, 1, 1

// Set to 1 if you also set rotate_180: true in config.yaml (device mounted upside down).
#define DISPLAY_ROTATE_180 0
