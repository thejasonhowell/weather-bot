![License](https://img.shields.io/github/license/thejasonhowell/weather-bot)
![Last Commit](https://img.shields.io/github/last-commit/thejasonhowell/weather-bot)

🌦️ **Peoria Weather Bot**
This automated bot fetches real-time data from a WeatherFlow station and posts human-readable weather updates to Bluesky and Telegram. Designed for reliable, hands-off operation with simple manual overrides.

---

## 🚀 Features

- **Regular Updates**
  - Fetches every **15 minutes** in a scheduler loop.
- **Human-Friendly Social Format**
  - Leads with a readable summary line such as `Peoria weather at 8:15 PM: 78°F, light NW wind, dry.`
  - Varies the lead sentence by condition so posts feel more like a local station update and less like a fixed template.
  - Uses cleaner social rounding for wind, rain, and lightning distance.
  - Hides low-value fields such as UV or lightning when they do not matter.
  - Uses local sunrise/sunset times for Peoria so UV only appears during daylight.
  - Adds morning sunrise and afternoon/evening sunset timing with optional once-daily pre-sunrise and pre-sunset notices.
  - Adds a cached NWS forecast peek to fuller routine posts.
- **Temperature & Alerts**
  - Includes actual and **feels like** temperature in routine updates.
  - Sends **rapid temperature drop alerts** when the temperature falls **10°F or more** in about **1 hour** with a **3-hour cooldown**.
  - Sends **storm follow-up posts** between normal cycles when nearby lightning or rain intensity ramps up quickly.
- **Daily Summary**
  - Sends a more narrative wrap-up at **11:59 PM** with high/low, rain total, and peak wind.
- **Precipitation**
  - Reports last-hour and daily rain totals.
  - Tracks the current rain event separately from the daily total.
  - Switches to estimated snowfall output when temperatures are at or below freezing.
- **Wind**
  - Reports current wind, gusts, and direction in a cleaner plain-language format.
  - Tracks daily maximum sustained wind and gusts, resetting at midnight.
- **Comfort & Pressure**
  - Adds dew point based comfort wording such as `comfortable`, `sticky`, `muggy`, or `tropical`.
  - Includes barometer trend language like `pressure rising` or `pressure falling ahead of storms`.
- **Lightning**
  - Reports strikes from the last **3 hours** only when lightning is present.
  - Includes closest strike distance and time when available.
- **NWS Alerts**
  - Polls active National Weather Service alerts for **Peoria County / ILC143**.
  - Posts new alerts to Bluesky and Telegram from the main bot process with a cleaner NWS office source link.
  - Summarizes NWS alert details such as `What`, `Where`, `When`, and river stage details when available.
  - Shortens only the Bluesky copy when a post would exceed the platform character limit, dropping hashtags before higher-value alert details such as river stage; Telegram still receives the fuller message.
  - Dedupes alert posts locally with `alert_history.json`, including paired NWS alert records that differ only by their final numeric suffix.
- **Storm Prediction Center Outlooks**
  - Checks official SPC Day 1, Day 2, and Day 3 categorical outlook GeoJSON.
  - Uses Peoria's coordinates against SPC risk polygons instead of relying on whether the text literally says `Peoria`.
  - Posts when Peoria is inside a **Marginal Risk** or higher and that local risk signature changes.
  - Attaches official SPC outlook graphics to Bluesky posts when available, with text-only fallback.
  - Dedupes SPC outlook posts locally with `spc_history.json`.
- **Forecast Office Products**
  - Checks ILX Area Forecast Discussions and Hazardous Weather Outlooks through the official NWS product API.
  - Posts concise AFD key-message summaries and Peoria-relevant HWO hazard summaries when notable weather is mentioned.
  - Parses recent ILX Local Storm Reports and posts new Peoria-area reports for tornado/funnel clouds, hail, wind damage, flooding, heavy rain, and other high-impact events.
  - Watches the SPC RSS feed for mesoscale discussions and posts only when they appear locally relevant to ILX / central Illinois / Peoria.
  - Attaches official SPC mesoscale discussion graphics to Bluesky posts when the RSS item includes one.
  - Dedupes these product posts locally with `forecast_product_history.json`.
- **USGS Earthquake Awareness**
  - Checks the official USGS earthquake API for regional earthquakes near Peoria.
  - Posts only for locally meaningful events: **M2.5+ within 250 km**, **M4.0+ within 750 km**, or notable felt-report activity.
  - Dedupes earthquake posts locally with `earthquake_history.json`.
- **River / Flood Awareness**
  - Polls NOAA NWPS river gauges for **Illinois River at Peoria (`PIAI2`)** and **Illinois River at Peoria Lock and Dam (`PRAI2`)**.
  - Posts separate river-status updates when flood category changes, crest forecasts shift, or a flood keepalive is needed.
- **Posting Controls**
  - Uses a lighter overnight posting mode during quiet hours.
  - Suppresses low-change routine posts to cut down on duplicate social noise while still sending BetterStack heartbeats.
- **Heartbeat**
  - Pings BetterStack every **30 minutes**.
- **Manual Overrides**
  - Supports **SIGUSR1** to force an immediate weather update without waiting for the next scheduler run.

---

## 📦 Requirements
- Python 3.10+
- `tweepy` - Twitter API client
- `requests` - HTTP library
- `mastodon.py` - Mastodon API client
- `python-dotenv` - Environment variable management
- `telegram` - Telegram Bot API
- `astral` - Local sunrise/sunset calculations
- `bsky-bridge` - Bluesky API bridge

### Current Active Posting Targets
- Bluesky
- Telegram

### Currently Disabled Posting Targets
- Mastodon
- Twitter

---

## 📄 Example Output

```
Peoria weather at 8:15 PM: 78°F, light NW wind, dry.

Feels like 80°F
Wind 6 mph from NW, gusting to 12
Dew point 60°F, slightly humid air
Sunset 8:34 PM
Forecast: Tonight partly cloudy, low near 67°F.
#peoriaweather
```

### 🌇 Sunset Notice
```
Sunset is about an hour away in Peoria.

Sunset today: 8:34 PM
Current read: 78°F, light W wind, dry.
#peoriaweather
```

### 🌅 Sunrise Notice
```
Sunrise is about an hour away in Peoria.

Sunrise today: 5:29 AM
Current read: 67°F, calm air, dry.
#peoriaweather
```

### 📊 Daily Summary (11:59 PM)
```
Peoria weather summary for 2026-06-18:

A warm breezy day with a passing shower.
High 84°F, low 67°F
Rain: 0.18"
Peak wind: 14 mph, gusting to 27
#peoriaweather
```

### ⚠️ Rapid Change Alert
```
Rapid temperature drop in Peoria: down 12°F in about an hour.

74°F to 62°F from 3:00 PM to 4:00 PM
#peoriaweather
```

### 🌧 Rain Event Example
```
Peoria weather at 8:15 PM: 72°F, gentle SE wind, light rain.

Feels like 72°F
Rain 0.08" last hour, 0.21" today
This rain event: 0.12"
Wind 9 mph from SE, gusting to 15
Dew point 69°F, sticky air
#peoriaweather
```

### ⛈ Lightning Example
```
Peoria weather at 8:15 PM: 74°F, breezy SW wind, stormy.

Feels like 76°F
Rain 0.05" last hour, 0.15" today
Wind 12 mph from SW, gusting to 22
Lightning: 6 strikes in the last 3 hours
Closest strike: 4 mi at 8:07 PM
#peoriaweather
```

### 🌊 River Flood Example
```
🌊 Illinois River at Peoria is in minor flood at 19.8 ft.

Observed at 7:45 AM: 19.8 ft
Forecast crest: 20.2 ft by Jun 25 7:00 AM
Flood stage: 18.0 ft
Some flooding begins to bottomland not protected by levees.
#peoriaweather
```

### 🚨 NWS Alert Example
```
🟩🌊 NWS River Flood Warning for Peoria County and nearby areas.

What: Minor flooding is occurring and minor flooding is forecast.
Where: Illinois River at Peoria.
When: Until further notice.
Stage: At 9:45 AM CDT Thursday the stage was 20.6 feet.
Flood stage: 18.0 feet.
Source: https://www.weather.gov/ilx/
#peoriaweather
```

### 🟧 SPC Outlook Example
```
🟧 SPC has Peoria in a Slight Risk for severe storms.

Outlook: Day 1
Timing: Valid 8:00 PM to Jun 30 7:00 AM
Source: https://www.spc.noaa.gov/products/outlook/day1otlk.html
#peoriaweather
```

### ⚠️ HWO Example
```
⚠️ NWS Hazardous Weather Outlook for Peoria and central IL.

Today: Heat index readings will climb to near 105 degrees this afternoon.
Next several days: Hot and humid weather persists with heat index readings peaking at 105 to 110 degrees.
Spotter activation: not anticipated through tonight
Source: https://forecast.weather.gov/product.php?site=ILX&issuedby=ILX&product=HWO
#peoriaweather
```

### 📝 AFD Example
```
📝 NWS Lincoln AFD highlights for Peoria/central IL.

- Hot and humid weather will prevail for the next several days.
- Rain chances gradually return late week into the holiday weekend.
Source: https://forecast.weather.gov/product.php?site=ILX&issuedby=ILX&product=AFD
#peoriaweather
```

### 📍 Local Storm Report Example
```
🟧💨 Local Storm Report from NWS Lincoln.

6:42 PM: thunderstorm wind damage near Peoria, Peoria County.
Reported by: Emergency Manager
Report: Tree limbs down near Glen Oak Park.
Source: https://forecast.weather.gov/product.php?site=ILX&issuedby=ILX&product=LSR
#peoriaweather
```

### 🟫 USGS Earthquake Example
```
🟫 USGS earthquake report for the Peoria region.

Magnitude 3.1
Location: 8 mi SE of Havana, Illinois
Distance from Peoria: about 38 mi
Depth: 5.2 mi
Reported: 2:14 AM
Source: https://earthquake.usgs.gov/earthquakes/eventpage/example
#peoriaweather
```

---

## ⚙️ How It Works

1. **Startup**
   - Loads environment variables from `.env` in the local script
   - Initializes posting clients and in-memory daily/event tracking
2. **Scheduler Loop**
   - Every **15 minutes**: fetch and post the current weather update
   - Every **5 minutes**: check for new NWS alerts for `ILC143`
   - Every **30 minutes**: check SPC Day 1/2/3 outlook polygons for Peoria risk changes
   - Every **30 minutes**: check USGS earthquake data for locally meaningful regional events
   - Every **30 minutes**: check ILX AFD/HWO/LSR products and local-relevant SPC mesoscale discussions
   - About once per hour as needed: refresh a short NWS forecast peek for routine posts
   - Once per day: send pre-sunrise and pre-sunset notices when each is within the configured lead time
   - Between routine cycles: watch for fast-changing storm conditions and send follow-up storm posts when warranted
   - On an internal interval: check the NOAA river gauge for Peoria flood-stage or crest changes
   - Every **30 minutes**: send BetterStack heartbeat
   - **23:59**: send daily summary
3. **Manual Update**
   - `SIGUSR1` triggers `force_update()` for an immediate post
4. **Event Tracking**
   - Maintains rolling in-memory state for rain events, lightning events, pressure trends, rapid temp-drop alerts, storm follow-up thresholds, and daily summary values
   - Stores seen NWS alerts in `alert_history.json` so the same alert is not reposted repeatedly
   - Stores last posted SPC outlook signatures in `spc_history.json`
   - Stores seen AFD/HWO/LSR/SPC MD products in `forecast_product_history.json`
   - Stores seen USGS earthquake IDs in `earthquake_history.json`
   - Stores last river flood state in `river_history.json` for category/crest change detection

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
BETTERSTACK_HEARTBEAT_URL=https://uptime.betterstack.com/api/v1/heartbeat/your_token_here
SUNRISE_NOTICE_MINUTES=60
SUNSET_NOTICE_MINUTES=60
```

### Pi-Star Variant
`main-pistar.py` mirrors the same weather logic and posting format, but keeps its credentials hardcoded for simpler deployment on Pi-Star style environments.

### Manual Trigger
To manually trigger a weather update while the bot is running, send a **SIGUSR1** signal to its process.

```bash
ps aux | grep main.py
kill -USR1 <PID>
```

---

## 📜 License
GPL-3.0 License

## Acknowledgment
Development of this project included AI-assisted coding support from ChatGPT/Codex. Final decisions, configuration, and deployment remain maintained by the project owner.
