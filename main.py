#!/usr/bin/env python3
# Last Modified: 2026-05-01
# To force an update of the weather bot while it's running,
# send a SIGUSR1 signal to its process.
# For instance, if the process ID is 1234, run:
#
#     kill -USR1 1234
#
# To locate the process ID, you can use:
#
#     ps aux | grep main.py
#
# This will trigger the force_update() function.

import tweepy
import requests
from mastodon import Mastodon
from bsky_bridge import BskySession, post_text
import logging
import os
import json
import time
from datetime import datetime
from telegram import Bot  # Import for Telegram Bot API
import asyncio  # For asynchronous operations
import signal  # To handle signals (force update)
# Load environment variables from a .env file
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[logging.StreamHandler()]
)

# Telegram configuration using your bot info
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(message):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        # Since send_message is asynchronous, we run it via asyncio.run
        asyncio.run(bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message))
        logging.info("Telegram: Message sent.")
    except Exception as e:
        logging.error(f"Telegram: Sending message failed. Error: {e}")


# Global variables to track daily maximum wind values and event info for lightning and rain
daily_max_wind_avg = 0.0
daily_max_wind_gust = 0.0
daily_date = datetime.now().strftime("%Y-%m-%d")
current_event_strike_total = 0
last_strike_epoch_global = None
current_rain_event_total = 0.0
rain_event_baseline = None
last_rain_epoch_global = None

# Daily stats for end-of-day summary
_daily_high_temp_f = None
_daily_low_temp_f = None
_daily_rain_total_in = 0.0
_last_daily_summary_date = None

# Rapid change alert tracking (in-memory)
_temp_history = []  # list of (epoch, temp_f)
_last_rapid_alert_epoch = 0


# Safely initialize Bluesky session
def initialize_bsky_session():
    session_file = "bsky_session.json"
    if os.path.exists(session_file):
        try:
            with open(session_file, "r") as file:
                credentials = json.load(file)
                handle = credentials.get("handle")
                password = credentials.get("password")
                if not handle or not password or str(password).startswith("REDACTED_"):
                    raise ValueError("Stored Bluesky credentials are incomplete or redacted.")
                logging.info("Session loaded from file.")
                return BskySession(handle, password)
        except Exception as e:
            logging.error(f"Error loading Bluesky session: {e}")

    try:
        bsky_handle = os.getenv("BSKY_HANDLE")
        bsky_password = os.getenv("BSKY_PASSWORD")
        if not bsky_handle or not bsky_password:
            logging.warning("Bluesky credentials are not configured. Skipping Bluesky posts.")
            return None
        session = BskySession(bsky_handle, bsky_password)
        with open(session_file, "w") as file:
            json.dump({"handle": bsky_handle, "password": bsky_password}, file)
        logging.info("New session created and saved to file.")
        return session
    except Exception as e:
        logging.error(f"Bluesky session initialization failed: {e}")
        return None


session = initialize_bsky_session()

# Initialize Mastodon client
mastodon = Mastodon(
    client_id=os.getenv("MASTODON_CLIENT_ID"),
    client_secret=os.getenv("MASTODON_CLIENT_SECRET"),
    access_token=os.getenv("MASTODON_ACCESS_TOKEN"),
    api_base_url=os.getenv("MASTODON_API_BASE_URL")
)

# Configure the Twitter client
client = tweepy.Client(
    consumer_key=os.getenv("TWITTER_CONSUMER_KEY"),
    consumer_secret=os.getenv("TWITTER_CONSUMER_SECRET"),
    access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
    access_token_secret=os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
)


# Utility function to convert degrees to cardinal direction
def degrees_to_cardinal(d):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[round(d / 45) % 8]


# New helper: Get temperature emoji based on Fahrenheit temperature thresholds.
def get_temperature_emoji(temp_f):
    if temp_f <= 32:
        return "🧊"  # Ice
    elif temp_f <= 45:
        return "🥶"  # Cold face
    elif temp_f < 80:
        return "👍🏽"  # Thumbs up
    else:
        return "🥵"  # Hot face


# New helper: Get a clock emoji based on the current half hour.
def get_clock_emoji():
    now = datetime.now()
    hour = now.hour % 12
    if hour == 0:
        hour = 12
    minute = now.minute
    if minute < 30:
        clock_map = {1: "🕐", 2: "🕑", 3: "🕒", 4: "🕓",
                     5: "🕔", 6: "🕕", 7: "🕖", 8: "🕗",
                     9: "🕘", 10: "🕙", 11: "🕚", 12: "🕛"}
        return clock_map.get(hour, "⏰")
    else:
        clock_map = {1: "🕜", 2: "🕝", 3: "🕞", 4: "🕟",
                     5: "🕠", 6: "🕡", 7: "🕢", 8: "🕣",
                     9: "🕤", 10: "🕥", 11: "🕦", 12: "🕧"}
        return clock_map.get(hour, "⏰")


# New helper: Returns emojis based on wind speed thresholds.
def wind_emoji(sustained, gust):
    # For sustained wind:
    if sustained <= 6:
        sustained_emoji = "😌"  # Calm
    elif sustained <= 30:
        sustained_emoji = "🍃"  # Moderate
    else:
        sustained_emoji = "💨"  # High wind

    # For wind gust:
    if gust <= 6:
        gust_emoji = "🌬"  # Calm/gentle
    elif gust <= 30:
        gust_emoji = "🍃"  # Moderate
    else:
        gust_emoji = "💨"  # Strong
    return sustained_emoji, gust_emoji


def _update_daily_stats(current_temp_f: float, rain_in_day: float):
    """Track daily high/low temperature and daily rain total for the summary."""
    global _daily_high_temp_f, _daily_low_temp_f, _daily_rain_total_in

    if _daily_high_temp_f is None or current_temp_f > _daily_high_temp_f:
        _daily_high_temp_f = current_temp_f
    if _daily_low_temp_f is None or current_temp_f < _daily_low_temp_f:
        _daily_low_temp_f = current_temp_f

    # WeatherFlow provides daily accumulation; keep the latest observed value.
    if rain_in_day is not None:
        _daily_rain_total_in = float(rain_in_day)


def check_rapid_changes(current_temp_f: float) -> str | None:
    """Detect rapid temperature drops (>= 10°F over ~1 hour) with 3-hour cooldown.

    Uses in-memory history; restarts reset history.
    """
    global _temp_history, _last_rapid_alert_epoch

    now_epoch = time.time()

    # Cooldown: 3 hours
    if _last_rapid_alert_epoch and (now_epoch - _last_rapid_alert_epoch) < 3 * 3600:
        # Still record history even if cooling down
        _temp_history.append((now_epoch, current_temp_f))
        _temp_history = [(t, temp) for (t, temp) in _temp_history if (now_epoch - t) <= 2 * 3600]
        return None

    # Record and keep ~2 hours of history
    _temp_history.append((now_epoch, current_temp_f))
    _temp_history = [(t, temp) for (t, temp) in _temp_history if (now_epoch - t) <= 2 * 3600]

    target = now_epoch - 3600
    # Find the reading closest to ~1 hour ago, but only from readings at or before the target time
    candidates = [(t, temp) for (t, temp) in _temp_history if t <= target]
    if not candidates:
        return None

    prev_t, prev_temp = min(candidates, key=lambda x: abs(x[0] - target))
    drop = prev_temp - current_temp_f

    if drop >= 10.0:
        _last_rapid_alert_epoch = now_epoch
        prev_time = datetime.fromtimestamp(prev_t).strftime("%H:%M")
        now_time = datetime.now().strftime("%H:%M")
        # Keep this concise for Twitter
        return (
            f"⚠️ Rapid temp drop: -{drop:.1f}°F in ~1h ({prev_temp:.1f}→{current_temp_f:.1f}). "
            f"{prev_time}→{now_time} #peoriaweather"
        )

    return None


def send_daily_summary():
    """Post an end-of-day summary at 23:59."""
    global _daily_high_temp_f, _daily_low_temp_f, _daily_rain_total_in

    date_str = datetime.now().strftime("%Y-%m-%d")

    hi = _daily_high_temp_f
    lo = _daily_low_temp_f
    rain = _daily_rain_total_in

    # Fallbacks in case we have limited data
    hi_str = f"{hi:.1f}°F" if hi is not None else "N/A"
    lo_str = f"{lo:.1f}°F" if lo is not None else "N/A"

    summary_message = (
        f"📊 Daily Summary ({date_str})\n"
        f"🌡 High/Low: {hi_str} / {lo_str}\n"
        f"☔ Rain (day): {rain:.3f} in\n"
        f"🍃 Max Wind: {daily_max_wind_avg:.1f} mph / {daily_max_wind_gust:.1f} mph\n"
        f"#peoriaweather"
    )

    # post_to_mastodon(summary_message)
    post_to_bluesky(summary_message)
    send_telegram_message(summary_message)
    # post_tweet(summary_message)


# Function to fetch weather data from the API
def fetch_weather_data():
    station_id = os.getenv("WEATHERFLOW_STATION_ID")
    api_token = os.getenv("WEATHERFLOW_API_TOKEN")
    url = f"https://swd.weatherflow.com/swd/rest/observations/station/{station_id}?token={api_token}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        # Use the first observation from the API response
        obs = data['obs'][0]

        # Rapid change alert (temp drop)
        temp_c = obs.get('air_temperature', 0)
        temp_f = temp_c * 9 / 5 + 32
        alert_message = check_rapid_changes(temp_f)
        if alert_message:
            # post_to_mastodon(alert_message)
            post_to_bluesky(alert_message)
            send_telegram_message(alert_message)
            # post_tweet(alert_message)

        return format_weather_data(obs)
    except requests.RequestException as e:
        logging.error(f"Error fetching weather data: {e}")
        return None


# Function to format weather data with the requested condensed ordering:
# Line 1: Time | Temperature | Humidity | UV Index
# Line 2: Precipitation (1h/day & day total) | Rain Event Total
# Line 3: Wind info (current, gust, direction) | Max Wind info
# Line 4: Lightning info (3hr count, event total, last strike info)
# Line 5: Brightness | Hashtag
def format_weather_data(data):
    global daily_max_wind_avg, daily_max_wind_gust, daily_date
    global current_event_strike_total, last_strike_epoch_global
    global current_rain_event_total, rain_event_baseline, last_rain_epoch_global

    # Get current time and date
    current_time = datetime.now().strftime("%H:%M")
    current_date = datetime.now().strftime("%Y-%m-%d")
    if current_date != daily_date:
        daily_max_wind_avg = 0.0
        daily_max_wind_gust = 0.0
        daily_date = current_date
        # Reset lightning event info at the start of a new day
        current_event_strike_total = 0
        last_strike_epoch_global = None
        # Reset rain event info at the start of a new day
        current_rain_event_total = 0.0
        rain_event_baseline = None
        last_rain_epoch_global = None

        # Reset daily summary stats at the start of a new day
        global _daily_high_temp_f, _daily_low_temp_f, _daily_rain_total_in
        _daily_high_temp_f = None
        _daily_low_temp_f = None
        _daily_rain_total_in = 0.0

    current_temp_c = data.get('air_temperature', 0)
    current_temp_f = current_temp_c * 9 / 5 + 32
    temp_emoji = get_temperature_emoji(current_temp_f)

    wind_speed_mps = data.get('wind_avg', 0)
    wind_speed_mph = wind_speed_mps * 2.23694

    wind_gust_mps = data.get('wind_gust', 0)
    wind_gust_mph = wind_gust_mps * 2.23694

    if wind_speed_mph > daily_max_wind_avg:
        daily_max_wind_avg = wind_speed_mph
    if wind_gust_mph > daily_max_wind_gust:
        daily_max_wind_gust = wind_gust_mph

    wind_dir_degrees = data.get('wind_direction', 0)
    wind_dir_cardinal = degrees_to_cardinal(wind_dir_degrees)

    humidity = data.get('relative_humidity', 0)
    uv_index = data.get('uv', 0)
    brightness = data.get('brightness', 0)

    rain_mm_1h = data.get('precip_accum_last_1hr', 0)
    rain_mm_day = data.get('precip_accum_local_day', 0)
    rain_in_1h = rain_mm_1h * 0.0393701 if rain_mm_1h is not None else 0
    rain_in_day = rain_mm_day * 0.0393701 if rain_mm_day is not None else 0

    # Update daily stats for end-of-day summary
    _update_daily_stats(current_temp_f, rain_in_day)

    precip_str = ""
    if current_temp_f >= 33:
        precip_str = f"☔ Rain: {rain_in_1h:.3f} in (1h) / {rain_in_day:.3f} in (day)"
    elif current_temp_f <= 32:
        snow_in_1h = rain_in_1h * 10
        snow_in_day = rain_in_day * 10
        precip_str = f"❄️ Snow: {snow_in_1h:.3f} in (1h, est.) / {snow_in_day:.3f} in (day, est.)"

    # Rain event tracking:
    now_epoch = time.time()
    if rain_in_day > 0:
        if (last_rain_epoch_global is None) or ((now_epoch - last_rain_epoch_global) >= 3 * 3600):
            rain_event_baseline = rain_in_day
            current_rain_event_total = 0.0
        else:
            current_rain_event_total = rain_in_day - (rain_event_baseline if rain_event_baseline is not None else 0.0)
        last_rain_epoch_global = now_epoch
    else:
        current_rain_event_total = 0.0
        rain_event_baseline = rain_in_day
        last_rain_epoch_global = now_epoch

    # Retrieve lightning data
    lightning_count = data.get("lightning_strike_count_last_3hr", 0)
    lightning_distance_km = data.get("lightning_strike_last_distance", 0)
    lightning_distance_mi = lightning_distance_km * 0.621371
    lightning_epoch = data.get("lightning_strike_last_epoch", None)
    if lightning_epoch:
        last_strike_time = datetime.fromtimestamp(lightning_epoch).strftime("%H:%M")
        if (last_strike_epoch_global is None) or ((lightning_epoch - last_strike_epoch_global) >= 3 * 3600):
            current_event_strike_total = lightning_count
        else:
            current_event_strike_total = max(current_event_strike_total, lightning_count)
        last_strike_epoch_global = lightning_epoch
    else:
        last_strike_time = "N/A"
        current_event_strike_total = 0

    clock_emoji = get_clock_emoji()
    sustained_emoji, gust_emoji = wind_emoji(daily_max_wind_avg, daily_max_wind_gust)

    # Construct condensed message (5 lines)
    weather_message = (
        f"{clock_emoji} {current_time} | {temp_emoji} {current_temp_f:.1f}°F | 💧 {humidity}% | ☀️ UV: {uv_index}\n"
        f"{precip_str} | Rain Event: {current_rain_event_total:.3f} in\n"
        f"🍃 Wind: {wind_speed_mph:.1f} mph (gust: {wind_gust_mph:.1f} mph, {wind_dir_degrees}° {wind_dir_cardinal}) | Max: {daily_max_wind_avg:.1f} mph {sustained_emoji} / {daily_max_wind_gust:.1f} mph {gust_emoji}\n"
        f"⚡ Lightning: {lightning_count} (3hr), Event: {current_event_strike_total} | last: {lightning_distance_mi:.1f} mi @ {last_strike_time}\n"
        f"💡 {brightness} lux | #peoriaweather"
    )
    return weather_message


# Functions to post to social media platforms
def post_to_bluesky(weather_message):
    if session is None:
        logging.warning("Bluesky session not initialized. Skipping Bluesky post.")
        return False
    try:
        post_text(session, weather_message)
        logging.info("Bluesky: Weather data posted.")
        return True
    except Exception as e:
        logging.error(f"Bluesky: Posting failed. Error: {e}")
        return False


def post_to_mastodon(weather_message):
    try:
        mastodon.toot(weather_message)
        logging.info("Mastodon: Weather data posted.")
        return True
    except Exception as e:
        logging.error(f"Mastodon: Posting failed. Error: {e}")
        return False


def post_tweet(weather_message):
    try:
        client.create_tweet(text=weather_message)
        logging.info("Twitter: Weather data posted.")
        return True
    except Exception as e:
        logging.error(f"Twitter: Posting failed. Error: {e}")
        return False


# Heartbeat function to signal the bot is active
def send_heartbeat():
    url = os.getenv("BETTERSTACK_HEARTBEAT_URL")
    if not url:
        logging.warning("Heartbeat URL is not configured. Skipping heartbeat.")
        return

    try:
        requests.get(url).raise_for_status()
        logging.info("Heartbeat sent successfully!")
    except requests.RequestException as e:
        logging.error(f"Heartbeat: Sending failed. Error: {e}")


# Signal handler to force an update outside of the scheduled interval
# To force an update of the weather bot while it's running,
# send a SIGUSR1 signal to its process.
# For instance, if the process ID is 1234, run:
#
#     kill -USR1 1234
#
# To locate the process ID, you can use:
#
#     ps aux | grep main.py
#
# This will trigger the force_update() function.
def force_update(signum, frame):
    logging.info("Force update signal received.")
    weather_message = fetch_weather_data()
    if weather_message:
        # post_to_mastodon(weather_message)
        post_to_bluesky(weather_message)
        send_telegram_message(weather_message)
        # post_tweet(weather_message)


# Register the signal handler for SIGUSR1
signal.signal(signal.SIGUSR1, force_update)


# Scheduler function that runs the weather bot at defined intervals
def scheduler():
    while True:
        now = datetime.now()
        minute = now.minute
        hour = now.hour
        today = now.strftime("%Y-%m-%d")

        # Daily summary at 23:59 (once per day)
        global _last_daily_summary_date
        if hour == 23 and minute == 59 and _last_daily_summary_date != today:
            send_daily_summary()
            _last_daily_summary_date = today
            # Sleep briefly to avoid double-send within the same minute
            time.sleep(61)
            continue

        # At every 15-minute mark, fetch and post weather data
        if minute % 15 == 0:
            weather_message = fetch_weather_data()
            if weather_message:
                # post_to_mastodon(weather_message)
                post_to_bluesky(weather_message)
                send_telegram_message(weather_message)
                # At every 30-minute mark, also post to Twitter
                if minute % 30 == 0:
                    # post_tweet(weather_message)
                    pass

        # Send a heartbeat every 30 minutes
        if minute % 30 == 0:
            send_heartbeat()

        # Sleep until the start of the next minute
        time.sleep(60 - datetime.now().second)


# Main execution block
if __name__ == "__main__":
    try:
        scheduler()
    except KeyboardInterrupt:
        logging.info("Weather bot stopped manually.")
