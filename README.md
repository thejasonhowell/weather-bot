![License](https://img.shields.io/github/license/thejasonhowell/weather-bot)
![Last Commit](https://img.shields.io/github/last-commit/thejasonhowell/weather-bot)

🌦️ Peoria Weather Bot
<br>
This is an automated weather bot that fetches real-time weather data from a WeatherFlow station and posts updates to social media platforms like Mastodon, Bluesky, Telegram, and Twitter. It’s designed for reliable, hands-off operation with simple manual overrides.


🚀 Features
Weather Updates every 15 minutes:
Temperature, humidity, UV index
Rainfall and snowfall (last hour, last day)
24-hour total rainfall and lightning strikes
Wind (current and max), wind direction
Brightness (lux level)
Posts Weather Reports To:
<br>🐘 Mastodon
<br>🔵 Bluesky
<br>🐦 Twitter
<br>📢 Telegram
<br><br>Heartbeat: Sends a ping to BetterStack every 30 minutes to confirm the bot is alive.
<br><br>Manual Update: Send a SIGUSR1 signal to trigger an immediate weather update.
<br>Local Storage: Maintains a rolling 24-hour log (weatherdata.json) to calculate total rainfall and lightning strikes over the past day.
<br><br>️🛡Security
No hardcoded API keys — all sensitive information is loaded from a .env file.
HTTPS connections to external APIs.
Local only logging — no external database or cloud storage.
Minimal external exposure — no open web ports, no server listeners.

Example Output

```
🕓 16:00 | 🥵 90.0°F | 💧 61% | ☀️ UV: 0.48
☔ Rain: 0.000 in (1h) / 0.000 in (day) | 24h Rain: 0.000 in
🍃 Wind: 0.2 mph (gust: 1.1 mph, 307° NW) | Max: 1.1 mph 😌 / 1.8 mph 🌬
⚡ Lightning: 0 (3hr), 24h Strikes: 927 | last: 16.2 mi @ 20:09
💡 6443 lux | #peoriaweather
```

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