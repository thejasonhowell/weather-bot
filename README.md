![License](https://img.shields.io/github/license/thejasonhowell/weather-bot)
![Last Commit](https://img.shields.io/github/last-commit/thejasonhowell/weather-bot)

🌦️ **Peoria Weather Bot**  
This automated bot fetches real-time data from a WeatherFlow station and posts compact, emoji-rich updates to Mastodon, Bluesky, Telegram, and Twitter. Designed for reliable, hands-off operation with simple manual overrides.

---

## 🚀 Features

- **Regular Updates**  
  - Fetches every **15 minutes**; **posts once immediately on startup**, then enters scheduler loop.  
- **Temperature**  
  - Actual & **Feels-Like (FL)** temperatures (°F) with context-sensitive emojis.  
- **Humidity & UV**  
  - Relative humidity (%) and UV index.  
- **Precipitation**  
  - **Instant** precip (in).  
  - Last **1 hour** total (in).  
  - Rolling **24 hour** total (in), persisted in `weatherdata.json`.  
- **Wind**  
  - Current speed, gust, and direction (mph & cardinal).  
  - Rolling **24 hour** maxima for wind and gusts.  
- **Lightning**  
  - Strikes in the last **3 hours**.  
  - Rolling **24 hour** strike count.  
  - Distance & time of last strike.  
- **Brightness**  
  - Ambient lux level.  
- **Manual Override**  
  - Send a `SIGUSR1` to trigger an immediate update:  
    ```bash
    ps aux | grep main.py
    kill -USR1 <PID>
    ```
- **Heartbeat**  
  - Pings BetterStack every **30 minutes** to confirm uptime.

---

## 📄 Example Output
```
🕓 16:00 | 🥵 90.0°F (FL 88.2°F) | 💧 61% | ☀️ UV 0.48
🌧️ 0.02 in inst | ☔ 0.10 in (1h) | 24 h total: 0.25 in
🍃 5.4 mph NW | Gust 12.3 mph 🌬
🌬️ 24 h max: 15.2 mph winds, 23.4 mph gusts
⚡ 2 strikes (3 h) | 15 strikes (24 h) | last 3.2 mi @ 15:42
💡 6443 lux | #peoriaweather
```

---

## ⚙️ How It Works

1. **Startup**  
   - Loads env vars from `.env`  
   - **Posts one update immediately**  
   - Initializes rolling-log file (`weatherdata.json`)  
2. **Scheduler Loop**  
   - Every **15 minutes**: fetch & post to Mastodon, Bluesky, Telegram  
   - Every **30 minutes**: additionally post to Twitter & send heartbeat  
3. **Manual Update**  
   - `SIGUSR1` triggers `force_update()` for an instant broadcast  
4. **Data Logging**  
   - Appends each fetch to the 24 hr JSON log  
   - Trims entries older than 24 h  
   - Sums values for accurate 24 hr totals

---


📄 Example .env file
<br>
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
    
🛠️ Manual Update
To manually trigger a weather update while the bot is running, send a SIGUSR1 signal to its process.


ps aux | grep main.py
kill -USR1 <PID>
    
📦 Requirements<br>
Python 3.10+<br>
tweepy - Twitter API client<br>
requests - HTTP library<br>
mastodon.py - Mastodon API client<br>
python-dotenv - Loads environment variables from .env file<br>
telegram - Telegram Bot API<br>
bsky-bridge - Bluesky API bridge<br>
⚙️ How It Works
Every 15 minutes, the bot fetches current weather observations from the WeatherFlow API.
The bot formats the weather data into a compact 5-line message including temperature, wind, rain, lightning, and brightness data.
The message is posted to Mastodon, Bluesky, Telegram, and every 30 minutes to Twitter.
A heartbeat ping is sent to BetterStack every 30 minutes to monitor uptime.
It saves a rolling 24-hour log of rain and lightning data for cumulative calculations.
Manual updates can be triggered via a Unix signal (SIGUSR1).
<br>
<br>📜 License
GPL-3.0 License — Free software, you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
