![License](https://img.shields.io/github/license/thejasonhowell/weather-bot)
![Last Commit](https://img.shields.io/github/last-commit/thejasonhowell/weather-bot)

🌦️ **Peoria Weather Bot**
This automated bot fetches real-time data from a WeatherFlow station and posts compact, emoji-rich updates to Mastodon, Bluesky, Telegram, and Twitter. Designed for reliable, hands-off operation with simple manual overrides.

---

## 🚀 Features

- **Regular Updates**
  - Fetches every **15 minutes**; enters scheduler loop.
- **Temperature & Alerts**
  - Actual & **Feels-Like (FL)** temperatures (°F).
  - **Rapid Change Alerts**: Notifies if temperature drops **≥ 10°F** over ~**1 hour** (3-hour cooldown).
- **Daily Summary**
  - Sends a wrap-up report at **11:59 PM** with daily high/low, daily rain (day total), and max wind.
- **Severe Weather**
  - Monitors NWS alerts and reposts warnings for the area.
- **Precipitation**
  - Reports 1-hour accumulation and WeatherFlow daily accumulation (day total).
  - Distinguishes between Rain and Snow based on temperature.
- **Wind**
  - Current speed, gust, and direction.
  - Tracks daily maximum wind and gust (resets at midnight).
- **Lightning**
  - Strikes in last **3 hours**.
- **Heartbeat**
  - Pings BetterStack every **30 minutes**.

---

## 📦 Requirements
- Python 3.10+
- `tweepy` - Twitter API client
- `requests` - HTTP library
- `mastodon.py` - Mastodon API client
- `python-dotenv` - Environment variable management
- `telegram` - Telegram Bot API
- `bsky-bridge` - Bluesky API bridge

---

## 📄 Example Output

```
🕓 16:00 | 🥵 90.0°F (FL 88.2°F) | 💧 61% | ☀️ UV 0.48
☔ 0.10 in (1h) | Rain (day): 0.25 in | Event: 0.12 in
🍃 5.4 mph NW | Gust 12.3 mph 🌬
⚡ 2 strikes (3 h) | last 3.2 mi @ 15:42
💡 6443 lux | #peoriaweather
```

### 📊 Daily Summary (11:59 PM)
```
📊 Daily Summary (2025-11-20)
🌡 High/Low: 75.2°F / 54.1°F
☔ Rain (day): 0.120 in
🍃 Max Wind: 12.5 mph / 18.2 mph
#peoriaweather
```

### ⚠️ Rapid Change Alert
```
⚠️ Rapid temp drop: -12.5°F in ~1h (74.5→62.0). 15:00→16:00 #peoriaweather
```

### 🚨 NWS Severe Weather Alert
```
⛈️ SEVERE THUNDERSTORM WARNING ⛈️ has been issued by NWS ILX on June 15, 2025, at 02:30 PM CDT
**Where:** Multiple counties including Peoria
**Expires:** June 15, 2025, at 03:15 PM CDT
https://forecast.weather.gov/MapClick.php?zoneid=ILZ029
#ILwx #cILwx
```

---

## ⚙️ How It Works

1. **Startup**
   - Loads env vars from `.env`
   - Initializes rolling-log file (`weatherdata.json`)
2. **Scheduler Loop**
   - Every **15 minutes**: fetch & post to Mastodon, Bluesky, Telegram
   - Every **30 minutes**: additionally post to Twitter & send heartbeat
   - **23:59**: Daily Summary
3. **Manual Update**
   - `SIGUSR1` triggers `force_update()` for an instant broadcast
4. **Data Logging**
   - Appends each fetch to a JSON log and trims entries older than 24 h.

---

## 🛠️ Configuration & Manual Control

### Environment Variables (`.env`)
```bash
TELEGRAM_TOKEN=your_telegram_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
BSKY_HANDLE=your_bluesky_handle_here
BSKY_PASSWORD=your_bluesky_password_here
MASTODON_CLIENT_ID=your_mastodon_client_id
MASTODON_CLIENT_SECRET=your_mastodon_client_secret
MASTODON_ACCESS_TOKEN=your_mastodon_access_token
MASTODON_API_BASE_URL=https://your.instance
TWITTER_CONSUMER_KEY=your_twitter_consumer_key
TWITTER_CONSUMER_SECRET=your_twitter_consumer_secret
TWITTER_ACCESS_TOKEN=your_twitter_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_twitter_access_token_secret
WEATHERFLOW_API_TOKEN=your_weatherflow_api_token
WEATHERFLOW_STATION_ID=your_station_id
OPENWEATHERMAP_API_KEY=your_openweathermap_api_key
BETTERSTACK_HEARTBEAT_URL=https://uptime.betterstack.com/api/v1/heartbeat/your_token_here
```

### Manual Trigger
To manually trigger a weather update while the bot is running, send a **SIGUSR1** signal to its process.

```bash
ps aux | grep main.py
kill -USR1 <PID>
```

---

## 📜 License
GPL-3.0 License
