#!/usr/bin/env python3
# Last Modified: 2026-06-25
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
import sys
import time
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from astral import LocationInfo
from astral.sun import sun
from telegram import Bot  # Import for Telegram Bot API
import asyncio  # For asynchronous operations
import signal  # To handle signals (force update)
# Load environment variables from a .env file
from dotenv import load_dotenv
load_dotenv()

LOG_FILE = os.getenv("WEATHERBOT_LOG_FILE", "/tmp/weather.log")
_log_handlers = [logging.StreamHandler()]
try:
    _log_handlers.insert(0, logging.FileHandler(LOG_FILE))
except OSError as exc:
    print(f"Warning: could not open log file {LOG_FILE}: {exc}", file=sys.stderr)
    LOG_FILE = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=_log_handlers,
    force=True,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.info("Logging initialized%s", f" to {LOG_FILE}" if LOG_FILE else "")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        logging.warning("%s must be an integer. Falling back to %s.", name, default)
        return default


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

# NWS alert tracking
NWS_ALERT_ZONE = "ILC143"
NWS_POINT_LAT = 40.6936
NWS_POINT_LON = -89.5890
NWS_FORECAST_CACHE_SECONDS = 60 * 60
BLUESKY_CHAR_LIMIT = 300
ALERT_HISTORY_FILE = "alert_history.json"
_last_nws_alert_check_epoch = 0
_nws_forecast_url = None
_forecast_peek_cache = {
    "epoch": 0,
    "line": None,
}

# Posting behavior tuning
QUIET_HOURS_START = 23
QUIET_HOURS_END = 6
ROUTINE_POST_KEEPALIVE_SECONDS = 2 * 3600
QUIET_HOURS_KEEPALIVE_SECONDS = 4 * 3600
STORM_FOLLOW_UP_CHECK_INTERVAL = 5 * 60
STORM_FOLLOW_UP_COOLDOWN = 20 * 60
SUNRISE_NOTICE_MINUTES = _env_int("SUNRISE_NOTICE_MINUTES", 60)
SUNSET_NOTICE_MINUTES = _env_int("SUNSET_NOTICE_MINUTES", 60)
_last_posted_weather_snapshot = None
_last_posted_weather_epoch = 0
_latest_weather_snapshot = None
_last_storm_follow_up_check_epoch = 0
_last_storm_follow_up_epoch = 0
_last_sunrise_notice_date = None
_last_sunset_notice_date = None
_pressure_history = []
RIVER_GAUGES = {
    "PIAI2": "Illinois River at Peoria",
    "PRAI2": "Illinois River at Peoria Lock and Dam",
}
RIVER_HISTORY_FILE = "river_history.json"
POST_STATE_FILE = "post_state.json"
RIVER_CHECK_INTERVAL = 30 * 60
RIVER_POST_KEEPALIVE_SECONDS = 12 * 3600
_last_river_check_epoch = 0
PEORIA_TIMEZONE = ZoneInfo("America/Chicago")
PEORIA_LOCATION = LocationInfo("Peoria", "USA", "America/Chicago", NWS_POINT_LAT, NWS_POINT_LON)


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


def _friendly_time(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%I:%M %p").lstrip("0")


def _sun_times(now: datetime | None = None) -> dict:
    now = now or datetime.now(PEORIA_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PEORIA_TIMEZONE)
    else:
        now = now.astimezone(PEORIA_TIMEZONE)
    return sun(PEORIA_LOCATION.observer, date=now.date(), tzinfo=PEORIA_TIMEZONE)


def _is_daylight(now: datetime | None = None) -> bool:
    now = now or datetime.now(PEORIA_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PEORIA_TIMEZONE)
    else:
        now = now.astimezone(PEORIA_TIMEZONE)
    sun_times = _sun_times(now)
    return sun_times["sunrise"] <= now <= sun_times["sunset"]


def _minutes_until_sunrise(now: datetime | None = None) -> int:
    now = now or datetime.now(PEORIA_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PEORIA_TIMEZONE)
    else:
        now = now.astimezone(PEORIA_TIMEZONE)
    sunrise = _sun_times(now)["sunrise"]
    return round((sunrise - now).total_seconds() / 60)


def _minutes_until_sunset(now: datetime | None = None) -> int:
    now = now or datetime.now(PEORIA_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PEORIA_TIMEZONE)
    else:
        now = now.astimezone(PEORIA_TIMEZONE)
    sunset = _sun_times(now)["sunset"]
    return round((sunset - now).total_seconds() / 60)


def _sunrise_detail_line(now: datetime | None = None) -> str | None:
    now = now or datetime.now(PEORIA_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PEORIA_TIMEZONE)
    else:
        now = now.astimezone(PEORIA_TIMEZONE)

    sunrise = _sun_times(now)["sunrise"]
    minutes_until = round((sunrise - now).total_seconds() / 60)

    if now.hour >= 12 or minutes_until < -30:
        return None
    if minutes_until < 0:
        return f"Sunrise was {_friendly_time(sunrise)}"
    return f"Sunrise {_friendly_time(sunrise)}"


def _sunset_detail_line(now: datetime | None = None) -> str | None:
    now = now or datetime.now(PEORIA_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PEORIA_TIMEZONE)
    else:
        now = now.astimezone(PEORIA_TIMEZONE)

    sunset = _sun_times(now)["sunset"]
    minutes_until = round((sunset - now).total_seconds() / 60)

    if now.hour < 12 or minutes_until < -30:
        return None
    if minutes_until < 0:
        return f"Sunset was {_friendly_time(sunset)}"
    return f"Sunset {_friendly_time(sunset)}"


def _format_sunrise_notice(snapshot: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(PEORIA_TIMEZONE)
    sunrise = _sun_times(now)["sunrise"]
    minutes_until = max(0, _minutes_until_sunrise(now))
    if minutes_until >= 90:
        lead_text = f"Sunrise is about {round(minutes_until / 60)} hours away in Peoria."
    elif minutes_until >= 45:
        lead_text = "Sunrise is about an hour away in Peoria."
    else:
        lead_text = f"Sunrise is about {minutes_until} minutes away in Peoria."

    return "\n".join([
        lead_text,
        "",
        f"Sunrise today: {_friendly_time(sunrise)}",
        f"Current read: {round(snapshot['current_temp_f'])}°F, {_headline_wind_phrase(snapshot['wind_speed_mph'], snapshot['wind_dir_cardinal'])}, {snapshot['headline_condition']}.",
        "#peoriaweather",
    ])


def _format_sunset_notice(snapshot: dict, now: datetime | None = None) -> str:
    now = now or datetime.now(PEORIA_TIMEZONE)
    sunset = _sun_times(now)["sunset"]
    minutes_until = max(0, _minutes_until_sunset(now))
    if minutes_until >= 90:
        lead_text = f"Sunset is about {round(minutes_until / 60)} hours away in Peoria."
    elif minutes_until >= 45:
        lead_text = "Sunset is about an hour away in Peoria."
    else:
        lead_text = f"Sunset is about {minutes_until} minutes away in Peoria."

    return "\n".join([
        lead_text,
        "",
        f"Sunset today: {_friendly_time(sunset)}",
        f"Current read: {round(snapshot['current_temp_f'])}°F, {_headline_wind_phrase(snapshot['wind_speed_mph'], snapshot['wind_dir_cardinal'])}, {snapshot['headline_condition']}.",
        "#peoriaweather",
    ])


def _snapshot_log_summary(snapshot: dict | None) -> str:
    if not snapshot:
        return "no snapshot"

    observed_at = snapshot.get("observed_at")
    if isinstance(observed_at, datetime):
        observed_text = observed_at.strftime("%I:%M %p").lstrip("0")
    else:
        observed_text = "unknown time"

    temp_f = snapshot.get("current_temp_f")
    wind_speed = snapshot.get("wind_speed_mph")
    gust = snapshot.get("wind_gust_mph")
    rain_1h = snapshot.get("rain_in_1h", 0.0) or 0.0
    condition = snapshot.get("headline_condition", "unknown")
    lightning_count = snapshot.get("lightning_count", 0)

    temp_text = f"{round(temp_f)}F" if temp_f is not None else "?F"
    wind_text = f"{round(wind_speed)} mph" if wind_speed is not None else "? mph"
    gust_text = f"{round(gust)}" if gust is not None else "?"
    return (
        f"{observed_text} {temp_text}, {condition}, wind {wind_text}, "
        f"gust {gust_text}, rain {rain_1h:.2f}\"/h, lightning {lightning_count}"
    )


def _serialize_snapshot(snapshot: dict | None) -> dict | None:
    if not snapshot:
        return None
    payload = dict(snapshot)
    observed_at = payload.get("observed_at")
    if isinstance(observed_at, datetime):
        payload["observed_at"] = observed_at.isoformat()
    return payload


def _deserialize_snapshot(snapshot_data: dict | None) -> dict | None:
    if not snapshot_data:
        return None
    snapshot = dict(snapshot_data)
    observed_at = snapshot.get("observed_at")
    if isinstance(observed_at, str):
        try:
            snapshot["observed_at"] = datetime.fromisoformat(observed_at)
        except ValueError:
            snapshot["observed_at"] = None
    return snapshot


def _save_post_state():
    payload = {
        "last_posted_weather_snapshot": _serialize_snapshot(_last_posted_weather_snapshot),
        "last_posted_weather_epoch": _last_posted_weather_epoch,
        "last_sunrise_notice_date": _last_sunrise_notice_date,
        "last_sunset_notice_date": _last_sunset_notice_date,
    }
    try:
        with open(POST_STATE_FILE, "w") as file:
            json.dump(payload, file)
    except Exception as e:
        logging.error(f"Error saving post state: {e}")


def _load_post_state():
    global _last_posted_weather_snapshot, _last_posted_weather_epoch
    global _last_sunrise_notice_date, _last_sunset_notice_date

    if not os.path.exists(POST_STATE_FILE):
        return

    try:
        with open(POST_STATE_FILE, "r") as file:
            payload = json.load(file)

        snapshot = _deserialize_snapshot(payload.get("last_posted_weather_snapshot"))
        epoch = float(payload.get("last_posted_weather_epoch", 0) or 0)
        _last_sunrise_notice_date = payload.get("last_sunrise_notice_date")
        _last_sunset_notice_date = payload.get("last_sunset_notice_date")

        if snapshot:
            _last_posted_weather_snapshot = snapshot
            _last_posted_weather_epoch = epoch
            if not _last_posted_weather_epoch and isinstance(snapshot.get("observed_at"), datetime):
                _last_posted_weather_epoch = snapshot["observed_at"].timestamp()
            logging.info(
                "Restored last posted weather state from %s (%s, mode=%s).",
                POST_STATE_FILE,
                _snapshot_log_summary(snapshot),
                snapshot.get("post_mode", "unknown"),
            )
    except Exception as e:
        logging.error(f"Error loading post state: {e}")


def _seconds_since_last_post() -> float | None:
    if not _last_posted_weather_epoch:
        return None
    return max(0.0, time.time() - _last_posted_weather_epoch)


def _routine_suppression_reason(snapshot: dict, quiet_mode: bool) -> str:
    keepalive_seconds = (
        QUIET_HOURS_KEEPALIVE_SECONDS if quiet_mode else ROUTINE_POST_KEEPALIVE_SECONDS
    )
    last_age = _seconds_since_last_post()
    last_age_text = f"{int(last_age // 60)}m ago" if last_age is not None else "unknown age"
    return (
        f"low change since last post {last_age_text} "
        f"(keepalive {keepalive_seconds // 3600}h, last={_snapshot_log_summary(_last_posted_weather_snapshot)}, "
        f"current={_snapshot_log_summary(snapshot)})"
    )


def _headline_wind_phrase(wind_speed_mph: float, wind_dir_cardinal: str) -> str:
    rounded_speed = round(wind_speed_mph)
    if rounded_speed <= 2:
        return "calm air"
    if rounded_speed <= 7:
        return f"light {wind_dir_cardinal} wind"
    if rounded_speed <= 14:
        return f"gentle {wind_dir_cardinal} wind"
    if rounded_speed <= 24:
        return f"breezy {wind_dir_cardinal} wind"
    if rounded_speed <= 34:
        return f"windy {wind_dir_cardinal} wind"
    return f"strong {wind_dir_cardinal} wind"


def _headline_condition(rain_in_1h: float, lightning_count: int) -> str:
    if lightning_count > 0:
        return "stormy"
    if rain_in_1h >= 0.10:
        return "rainy"
    if rain_in_1h >= 0.01:
        return "light rain"
    return "dry"


def _condition_phrase(condition: str) -> str:
    phrases = {
        "dry": "dry conditions",
        "light rain": "light rain",
        "rainy": "steady rain",
        "stormy": "storms nearby",
    }
    return phrases.get(condition, condition)


def _local_station_lead(snapshot: dict) -> str:
    observed_at = snapshot["observed_at"]
    time_text = _friendly_time(observed_at)
    temp_text = f"{round(snapshot['current_temp_f'])}°F"
    wind_phrase = _headline_wind_phrase(snapshot["wind_speed_mph"], snapshot["wind_dir_cardinal"])
    condition = snapshot["headline_condition"]
    condition_text = _condition_phrase(condition)

    if snapshot["lightning_count"] > 0:
        templates = [
            f"Storms are close enough to watch in Peoria at {time_text}: {temp_text}, {wind_phrase}.",
            f"Peoria storm check at {time_text}: {temp_text}, {wind_phrase}, {condition_text}.",
            f"Active weather near Peoria at {time_text}: {temp_text} with {wind_phrase}.",
        ]
    elif snapshot["rain_in_1h"] >= 0.10:
        templates = [
            f"Rain is making itself known in Peoria at {time_text}: {temp_text}, {wind_phrase}.",
            f"A wet read from Peoria at {time_text}: {temp_text}, {wind_phrase}, {condition_text}.",
            f"Peoria weather at {time_text}: {temp_text} with {condition_text} and {wind_phrase}.",
        ]
    elif snapshot["rain_in_1h"] >= 0.01:
        templates = [
            f"Light rain is passing through Peoria at {time_text}: {temp_text}, {wind_phrase}.",
            f"Peoria has a little rain in the mix at {time_text}: {temp_text}, {wind_phrase}.",
            f"A damp check-in from Peoria at {time_text}: {temp_text}, {wind_phrase}.",
        ]
    elif snapshot["wind_gust_mph"] >= 20 or snapshot["wind_speed_mph"] >= 15:
        templates = [
            f"Breezes are doing the talking in Peoria at {time_text}: {temp_text}, {wind_phrase}, {condition_text}.",
            f"Peoria weather at {time_text}: {temp_text}, {wind_phrase}, still {condition}.",
            f"A windier read from Peoria at {time_text}: {temp_text} with {wind_phrase}.",
        ]
    elif snapshot["current_temp_f"] >= 85:
        templates = [
            f"A warm stretch continues in Peoria at {time_text}: {temp_text}, {wind_phrase}, {condition_text}.",
            f"Peoria is running warm at {time_text}: {temp_text} with {wind_phrase}.",
            f"Summer has the wheel in Peoria at {time_text}: {temp_text}, {wind_phrase}, {condition_text}.",
        ]
    elif snapshot["current_temp_f"] <= 32:
        templates = [
            f"A cold read from Peoria at {time_text}: {temp_text}, {wind_phrase}, {condition_text}.",
            f"Peoria is below freezing at {time_text}: {temp_text} with {wind_phrase}.",
            f"Cold air is settled into Peoria at {time_text}: {temp_text}, {wind_phrase}.",
        ]
    elif round(snapshot["wind_speed_mph"]) <= 2:
        templates = [
            f"Still calm across Peoria at {time_text}: {temp_text}, {wind_phrase}, {condition}.",
            f"A quiet read from Peoria at {time_text}: {temp_text} with {wind_phrase} and {condition_text}.",
            f"Peoria is holding steady at {time_text}: {temp_text}, {wind_phrase}, {condition}.",
        ]
    else:
        templates = [
            f"Peoria weather at {time_text}: {temp_text}, {wind_phrase}, {condition}.",
            f"A steady check-in from Peoria at {time_text}: {temp_text}, {wind_phrase}, {condition_text}.",
            f"Here is the Peoria read at {time_text}: {temp_text} with {wind_phrase} and {condition_text}.",
            f"Peoria is sitting at {temp_text} at {time_text}: {wind_phrase}, {condition}.",
        ]

    index = (
        observed_at.hour
        + observed_at.minute // 15
        + round(snapshot["current_temp_f"])
        + round(snapshot["wind_speed_mph"])
    ) % len(templates)
    return templates[index]


def _daily_summary_narrative(hi: float | None, rain: float, gust: float) -> str:
    if hi is None:
        temp_phrase = "Uneventful"
    elif hi >= 90:
        temp_phrase = "A hot"
    elif hi >= 80:
        temp_phrase = "A warm"
    elif hi >= 65:
        temp_phrase = "A mild"
    elif hi >= 50:
        temp_phrase = "A cool"
    else:
        temp_phrase = "A cold"

    if gust >= 30:
        wind_phrase = "windy day"
    elif gust >= 20:
        wind_phrase = "breezy day"
    else:
        wind_phrase = "fairly calm day"

    if rain >= 0.25:
        rain_phrase = "with steady rain."
    elif rain >= 0.05:
        rain_phrase = "with a passing shower."
    elif rain > 0:
        rain_phrase = "with a trace of rain."
    else:
        rain_phrase = "with dry conditions."

    return f"{temp_phrase} {wind_phrase} {rain_phrase}"


def _format_alert_time(iso_time: str | None) -> str:
    if not iso_time:
        return "Unknown time"
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00")).astimezone()
        now_local = datetime.now(dt.tzinfo)
        if dt.date() == now_local.date():
            return _friendly_time(dt)
        return dt.strftime("%b %d %I:%M %p").replace(" 0", " ").lstrip("0")
    except ValueError:
        return "Unknown time"


def _get_alert_emoji(event_name: str) -> str:
    text = event_name.upper()
    specific_badges = [
        ("TORNADO WARNING", "🟥🌪️"),
        ("TORNADO WATCH", "🟨🌪️"),
        ("HURRICANE WARNING", "🟥🌀"),
        ("HURRICANE WATCH", "🟪🌀"),
        ("TROPICAL STORM WARNING", "🟥🌀"),
        ("TROPICAL STORM WATCH", "🟧🌀"),
        ("STORM SURGE WARNING", "🟪🌊"),
        ("STORM SURGE WATCH", "🟪🌊"),
        ("SEVERE THUNDERSTORM WARNING", "🟧⛈️"),
        ("SEVERE THUNDERSTORM WATCH", "🟪⛈️"),
        ("FLASH FLOOD WARNING", "🟥🌊"),
        ("FLOOD WARNING", "🟩🌊"),
        ("FLOOD WATCH", "🟩🌊"),
        ("FLOOD ADVISORY", "🟩🌊"),
        ("SPECIAL WEATHER STATEMENT", "🟨⚠️"),
        ("EXTREME WIND WARNING", "🟧💨"),
        ("HIGH WIND WARNING", "🟧💨"),
        ("WIND ADVISORY", "🟨💨"),
        ("EXCESSIVE HEAT WARNING", "🟪🌡️"),
        ("HEAT ADVISORY", "🟧🌡️"),
    ]
    for alert_text, badge in specific_badges:
        if alert_text in text:
            return badge

    if "TORNADO" in text:
        return "🌪️"
    if "SEVERE THUNDERSTORM" in text:
        return "⛈️"
    if "FLASH FLOOD" in text or "FLOOD" in text:
        return "🌊"
    if "WINTER" in text or "BLIZZARD" in text or "SNOW" in text:
        return "❄️"
    if "ICE" in text or "FREEZE" in text or "FROST" in text:
        return "🧊"
    if "HEAT" in text:
        return "🌡️"
    if "WIND" in text:
        return "💨"
    if "AIR QUALITY" in text:
        return "🫁"
    return "⚠️"


def _format_alert_area(area_desc: str) -> str:
    counties = [c.strip() for c in area_desc.split(";") if c.strip()]
    peoria_counties = [c for c in counties if "Peoria" in c]
    if not counties:
        return "Peoria County"
    if peoria_counties and len(counties) == 1:
        return peoria_counties[0]
    if peoria_counties:
        return "Peoria County and nearby areas"
    return counties[0]


def _is_river_flood_alert(properties: dict) -> bool:
    text = " ".join([
        properties.get("event") or "",
        properties.get("headline") or "",
        properties.get("description") or "",
        properties.get("instruction") or "",
    ]).lower()
    return "flood" in text and "river" in text


def _collapse_whitespace(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = " ".join(str(text).split())
    return cleaned or None


def _extract_nws_bullet(description: str, label: str) -> str | None:
    marker = f"* {label.upper()}..."
    collecting = False
    collected = []

    for raw_line in description.splitlines():
        line = raw_line.strip()
        if line.startswith("* ") and "..." in line:
            if collecting:
                break
            if line.upper().startswith(marker):
                collecting = True
                collected.append(line.split("...", 1)[1])
            continue
        if collecting:
            collected.append(line)

    return _collapse_whitespace(" ".join(collected))


def _extract_river_stage_lines(description: str) -> list[str]:
    useful_lines = []
    lines = description.splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip().lstrip("-").strip()
        lower = line.lower()
        if not line:
            continue
        if "stage was" in lower:
            useful_lines.append(f"Stage: {_collapse_whitespace(line)}")
        elif lower.startswith("forecast") and "river" in lower:
            next_line = ""
            if index + 1 < len(lines):
                candidate = lines[index + 1].strip().lstrip("-").strip()
                if candidate and not candidate.startswith("* ") and not candidate.lower().startswith("flood stage"):
                    next_line = f" {candidate}"
            forecast_text = f"{line}{next_line}".replace("Forecast...", "")
            useful_lines.append(f"Forecast: {_collapse_whitespace(forecast_text)}")
        elif lower.startswith("flood stage"):
            useful_lines.append(f"Flood stage: {_collapse_whitespace(line.replace('Flood stage is ', ''))}")
        if len(useful_lines) >= 3:
            break
    return [line for line in useful_lines if line]


def _format_nws_alert_summary_lines(properties: dict) -> list[str]:
    description = properties.get("description") or ""
    summary_lines = []
    for label in ("WHAT", "WHERE", "WHEN"):
        value = _extract_nws_bullet(description, label)
        if value:
            summary_lines.append(f"{label.title()}: {value}")

    if _is_river_flood_alert(properties):
        summary_lines.extend(_extract_river_stage_lines(description))

    return summary_lines[:6]


def _nws_office_source_url(properties: dict) -> str:
    office_id = None
    parameters = properties.get("parameters") or {}

    for vtec in parameters.get("VTEC", []):
        parts = str(vtec).split(".")
        if len(parts) > 3 and parts[3].startswith("K"):
            office_id = parts[3][1:]
            break

    if not office_id:
        for identifier in parameters.get("AWIPSidentifier", []):
            text = str(identifier)
            if len(text) >= 3:
                office_id = text[-3:]
                break

    if office_id:
        return f"https://www.weather.gov/{office_id.lower()}/"

    web_url = properties.get("web")
    if web_url and web_url != "http://www.weather.gov":
        return web_url.replace("http://", "https://")
    return "https://www.weather.gov/alerts"


def _load_alert_history() -> dict:
    if os.path.exists(ALERT_HISTORY_FILE):
        try:
            with open(ALERT_HISTORY_FILE, "r") as file:
                return json.load(file)
        except Exception as e:
            logging.error(f"Error loading alert history: {e}")
    return {}


def _save_alert_history(history: dict):
    try:
        with open(ALERT_HISTORY_FILE, "w") as file:
            json.dump(history, file)
    except Exception as e:
        logging.error(f"Error saving alert history: {e}")


def _cleanup_alert_history(history: dict) -> dict:
    now_epoch = time.time()
    return {key: value for key, value in history.items() if now_epoch - value < 86400}


def fetch_nws_alerts():
    url = f"https://api.weather.gov/alerts/active?zone={NWS_ALERT_ZONE}"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "PeoriaWeatherBot/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        return response.json().get("features", [])
    except requests.RequestException as e:
        logging.error(f"Error fetching NWS alerts: {e}")
        return []


def format_nws_alert_post(alert) -> str:
    properties = alert.get("properties", {})
    event_name = properties.get("event", "Weather Alert")
    display_event = event_name
    if _is_river_flood_alert(properties) and "river" not in event_name.lower():
        display_event = f"River {event_name}"
    area_text = _format_alert_area(properties.get("areaDesc", "Peoria County"))
    expires_time = _format_alert_time(properties.get("expires"))
    sent_time = _format_alert_time(properties.get("sent"))
    emoji = _get_alert_emoji(event_name)

    lines = [
        f"{emoji} NWS {display_event} for {area_text}.",
        "",
    ]
    lines.extend(_format_nws_alert_summary_lines(properties))
    lines.extend([
        f"Issued at {sent_time}",
        f"Until {expires_time}",
    ])

    lines.append(f"Source: {_nws_office_source_url(properties)}")

    lines.append("#peoriaweather")
    return "\n".join(lines)


def _get_nws_forecast_url() -> str | None:
    global _nws_forecast_url
    if _nws_forecast_url:
        return _nws_forecast_url

    url = f"https://api.weather.gov/points/{NWS_POINT_LAT},{NWS_POINT_LON}"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "PeoriaWeatherBot/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        _nws_forecast_url = response.json().get("properties", {}).get("forecast")
        return _nws_forecast_url
    except requests.RequestException as e:
        logging.error(f"Error fetching NWS forecast point metadata: {e}")
        return None


def _format_forecast_period(period: dict) -> str | None:
    name = period.get("name")
    short_forecast = period.get("shortForecast")
    temperature = period.get("temperature")
    unit = period.get("temperatureUnit", "F")
    is_daytime = period.get("isDaytime")

    if not name or not short_forecast or temperature is None:
        return None

    temp_word = "high" if is_daytime else "low"
    return f"Forecast: {name} {short_forecast.lower()}, {temp_word} near {round(temperature)}°{unit}."


def fetch_nws_forecast_peek() -> str | None:
    now_epoch = time.time()
    cached_line = _forecast_peek_cache.get("line")
    if cached_line and (now_epoch - _forecast_peek_cache.get("epoch", 0)) < NWS_FORECAST_CACHE_SECONDS:
        return cached_line

    forecast_url = _get_nws_forecast_url()
    if not forecast_url:
        return None

    try:
        response = requests.get(
            forecast_url,
            headers={"User-Agent": "PeoriaWeatherBot/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        periods = response.json().get("properties", {}).get("periods", [])
        for period in periods[:2]:
            line = _format_forecast_period(period)
            if line:
                _forecast_peek_cache["epoch"] = now_epoch
                _forecast_peek_cache["line"] = line
                logging.info("Forecast peek refreshed: %s", line)
                return line
        logging.warning("Forecast peek unavailable: NWS forecast had no usable periods.")
    except requests.RequestException as e:
        logging.error(f"Error fetching NWS forecast peek: {e}")

    _forecast_peek_cache["epoch"] = now_epoch
    _forecast_peek_cache["line"] = None
    return None


def _normalized_nws_alert_id(alert_id: str) -> str:
    base_id, separator, suffix = str(alert_id).rpartition(".")
    if separator and suffix.isdigit():
        return base_id
    return str(alert_id)


def check_nws_alerts():
    global _last_nws_alert_check_epoch

    now_epoch = time.time()
    if now_epoch - _last_nws_alert_check_epoch < 5 * 60:
        return
    _last_nws_alert_check_epoch = now_epoch

    history = _cleanup_alert_history(_load_alert_history())
    alerts = fetch_nws_alerts()

    if not alerts:
        _save_alert_history(history)
        return

    for alert in alerts:
        properties = alert.get("properties", {})
        alert_id = alert.get("id", "unknown")
        alert_sent = properties.get("sent") or properties.get("effective") or ""
        normalized_alert_id = _normalized_nws_alert_id(alert_id)
        history_key = f"{normalized_alert_id}|{alert_sent}"
        legacy_history_key = f"{alert_id}|{alert_sent}"

        if history_key in history:
            continue
        if legacy_history_key in history:
            history[history_key] = history[legacy_history_key]
            continue

        alert_message = format_nws_alert_post(alert)
        post_to_bluesky(alert_message)
        send_telegram_message(alert_message)
        history[history_key] = now_epoch

    _save_alert_history(history)


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_pressure_inhg(data) -> float | None:
    for key in ("station_pressure", "sea_level_pressure", "barometric_pressure", "pressure"):
        raw_value = data.get(key)
        value = _safe_float(raw_value)
        if value is None or value <= 0:
            continue
        if value > 100:
            return value * 0.0295299830714
        return value
    return None


def _update_pressure_history(observed_at: datetime, pressure_inhg: float | None):
    global _pressure_history
    if pressure_inhg is None:
        return
    now_epoch = observed_at.timestamp()
    _pressure_history.append((now_epoch, pressure_inhg))
    _pressure_history = [(t, p) for (t, p) in _pressure_history if (now_epoch - t) <= 6 * 3600]


def _compute_dew_point_f(temp_f: float, humidity: float) -> float | None:
    if humidity is None or humidity <= 0 or humidity > 100:
        return None
    temp_c = (temp_f - 32) * 5 / 9
    gamma = math.log(humidity / 100.0) + ((17.625 * temp_c) / (243.04 + temp_c))
    dew_point_c = (243.04 * gamma) / (17.625 - gamma)
    return dew_point_c * 9 / 5 + 32


def _dew_point_phrase(dew_point_f: float) -> str:
    if dew_point_f <= 35:
        return "dry air"
    if dew_point_f < 60:
        return "comfortable air"
    if dew_point_f < 65:
        return "slightly humid air"
    if dew_point_f < 70:
        return "sticky air"
    if dew_point_f < 75:
        return "muggy air"
    return "tropical air"


def _dew_point_line(current_temp_f: float, dew_point_f: float | None) -> str | None:
    if dew_point_f is None:
        return None
    if dew_point_f <= 35:
        return f"Dew point {round(dew_point_f)}°F, dry air"
    if current_temp_f >= 68 or dew_point_f >= 60:
        return f"Dew point {round(dew_point_f)}°F, {_dew_point_phrase(dew_point_f)}"
    return None


def _pressure_trend_line(snapshot: dict) -> str | None:
    pressure_inhg = snapshot.get("pressure_inhg")
    if pressure_inhg is None:
        return None

    if len(_pressure_history) < 2:
        return f"Pressure {pressure_inhg:.2f} inHg"

    now_epoch = snapshot["observed_at"].timestamp()
    target = now_epoch - 3 * 3600
    candidates = [(t, pressure) for (t, pressure) in _pressure_history if t <= target]
    if not candidates:
        return f"Pressure {pressure_inhg:.2f} inHg"

    _, previous_pressure = min(candidates, key=lambda item: abs(item[0] - target))
    delta = pressure_inhg - previous_pressure

    if delta <= -0.08 and snapshot["headline_condition"] in {"stormy", "rainy", "light rain"}:
        return f"Pressure {pressure_inhg:.2f} inHg and falling ahead of storms."
    if delta <= -0.05:
        return f"Pressure {pressure_inhg:.2f} inHg and falling."
    if delta >= 0.08:
        return f"Pressure {pressure_inhg:.2f} inHg and rising."
    return f"Pressure {pressure_inhg:.2f} inHg"


def _load_river_history() -> dict:
    if os.path.exists(RIVER_HISTORY_FILE):
        try:
            with open(RIVER_HISTORY_FILE, "r") as file:
                return json.load(file)
        except Exception as e:
            logging.error(f"Error loading river history: {e}")
    return {}


def _save_river_history(history: dict):
    try:
        with open(RIVER_HISTORY_FILE, "w") as file:
            json.dump(history, file)
    except Exception as e:
        logging.error(f"Error saving river history: {e}")


def _river_category_rank(category: str | None) -> int:
    category = (category or "").lower()
    ranks = {
        "not_defined": 0,
        "no_flooding": 0,
        "action": 1,
        "minor": 2,
        "moderate": 3,
        "major": 4,
    }
    return ranks.get(category, 0)


def _river_emoji(category: str | None) -> str:
    category = (category or "").lower()
    if category == "major":
        return "🚨"
    if category == "moderate":
        return "⚠️"
    return "🌊"


def _format_local_valid_time(iso_time: str | None) -> str:
    if not iso_time:
        return "Unknown time"
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00")).astimezone()
        now_local = datetime.now(dt.tzinfo)
        if dt.date() == now_local.date():
            return _friendly_time(dt)
        return dt.strftime("%b %d %I:%M %p").replace(" 0", " ").lstrip("0")
    except ValueError:
        return "Unknown time"


def _nearest_river_impact(gauge: dict, stage_ft: float | None) -> str | None:
    if stage_ft is None:
        return None
    impacts = gauge.get("flood", {}).get("impacts", [])
    eligible = [impact for impact in impacts if _safe_float(impact.get("stage")) is not None and impact["stage"] <= stage_ft]
    if not eligible:
        return None
    chosen = max(eligible, key=lambda impact: impact["stage"])
    return chosen.get("statement")


def fetch_river_gauge(gauge_id: str):
    url = f"https://api.water.noaa.gov/nwps/v1/gauges/{gauge_id}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        gauge = response.json()
        gauge["_configured_gauge_id"] = gauge_id
        return gauge
    except requests.RequestException as e:
        logging.error(f"Error fetching river gauge data for {gauge_id}: {e}")
        return None


def format_river_status_post(gauge: dict) -> str:
    gauge_id = gauge.get("_configured_gauge_id") or gauge.get("lid") or gauge.get("id") or ""
    gauge_name = RIVER_GAUGES.get(gauge_id, gauge.get("name", "Illinois River at Peoria"))
    observed = gauge.get("status", {}).get("observed", {})
    forecast = gauge.get("status", {}).get("forecast", {})
    observed_stage = _safe_float(observed.get("primary"))
    forecast_stage = _safe_float(forecast.get("primary"))
    observed_category = observed.get("floodCategory", "action")
    forecast_category = forecast.get("floodCategory", "action")
    flood_stage = _safe_float(gauge.get("flood", {}).get("categories", {}).get("minor", {}).get("stage"))
    impact_statement = _nearest_river_impact(gauge, observed_stage)
    lead_category = observed_category if _river_category_rank(observed_category) >= 1 else forecast_category
    emoji = _river_emoji(lead_category)

    if _river_category_rank(observed_category) >= 1 and observed_stage is not None:
        lead = f"{emoji} {gauge_name} is in {observed_category} flood at {observed_stage:.1f} ft."
    else:
        lead = f"{emoji} {gauge_name} is forecast to reach {forecast_category} flood."
    lines = [
        lead,
        "",
    ]
    if observed_stage is not None:
        lines.append(f"Observed at {_format_local_valid_time(observed.get('validTime'))}: {observed_stage:.1f} ft")

    if forecast_stage is not None and forecast_stage > -900:
        lines.append(
            f"Forecast crest: {forecast_stage:.1f} ft by {_format_local_valid_time(forecast.get('validTime'))}"
        )
    if flood_stage is not None:
        lines.append(f"Flood stage: {flood_stage:.1f} ft")
    if impact_statement:
        lines.append(impact_statement)

    lines.append("#peoriaweather")
    return "\n".join(lines)


def check_river_flood_status():
    global _last_river_check_epoch

    now_epoch = time.time()
    if now_epoch - _last_river_check_epoch < RIVER_CHECK_INTERVAL:
        return
    _last_river_check_epoch = now_epoch

    history = _load_river_history()
    gauge_histories = history.setdefault("gauges", {})

    for gauge_id, gauge_name in RIVER_GAUGES.items():
        gauge = fetch_river_gauge(gauge_id)
        if not gauge:
            continue

        observed = gauge.get("status", {}).get("observed", {})
        forecast = gauge.get("status", {}).get("forecast", {})
        observed_category = observed.get("floodCategory", "")
        forecast_category = forecast.get("floodCategory", "")
        observed_stage = _safe_float(observed.get("primary"))
        forecast_stage = _safe_float(forecast.get("primary"))
        observed_stage_text = f"{observed_stage:.1f} ft" if observed_stage is not None else "unknown stage"
        forecast_stage_text = f"{forecast_stage:.1f} ft" if forecast_stage is not None else "unknown stage"

        highest_rank = max(_river_category_rank(observed_category), _river_category_rank(forecast_category))
        gauge_history = gauge_histories.setdefault(gauge_id, {})
        if gauge_id == "PIAI2" and history.get("observed_category") and not gauge_history:
            for key in (
                "last_posted_epoch",
                "observed_category",
                "forecast_category",
                "observed_stage",
                "forecast_stage",
                "last_checked_epoch",
            ):
                if key in history:
                    gauge_history[key] = history[key]

        should_post = False
        if highest_rank >= 1:
            if not gauge_history.get("last_posted_epoch"):
                should_post = True
            elif gauge_history.get("observed_category") != observed_category:
                should_post = True
            elif gauge_history.get("forecast_category") != forecast_category:
                should_post = True
            elif (
                forecast_stage is not None
                and _safe_float(gauge_history.get("forecast_stage")) is not None
                and abs(forecast_stage - float(gauge_history["forecast_stage"])) >= 0.5
            ):
                should_post = True
            elif (now_epoch - float(gauge_history.get("last_posted_epoch", 0))) >= RIVER_POST_KEEPALIVE_SECONDS:
                should_post = True

        if highest_rank < 1:
            logging.info(
                "River check %s: below action stage (observed=%s %s, forecast=%s %s).",
                gauge_id,
                observed_category or "no_flooding",
                observed_stage_text,
                forecast_category or "no_flooding",
                forecast_stage_text,
            )
        elif not should_post:
            logging.info(
                "River check %s: no posting change (observed=%s %s, forecast=%s %s).",
                gauge_id,
                observed_category or "unknown",
                observed_stage_text,
                forecast_category or "unknown",
                forecast_stage_text,
            )

        if should_post and observed_stage is not None:
            logging.info(
                "River check %s: posting update for %s (observed=%s %s, forecast=%s %s).",
                gauge_id,
                gauge_name,
                observed_category or "unknown",
                observed_stage_text,
                forecast_category or "unknown",
                forecast_stage_text,
            )
            river_message = format_river_status_post(gauge)
            post_to_bluesky(river_message)
            send_telegram_message(river_message)
            gauge_history["last_posted_epoch"] = now_epoch
        elif should_post:
            logging.warning("River check %s: update triggered but observed stage is unavailable.", gauge_id)

        gauge_history.update({
            "name": gauge_name,
            "observed_category": observed_category,
            "forecast_category": forecast_category,
            "observed_stage": observed_stage,
            "forecast_stage": forecast_stage,
            "last_checked_epoch": now_epoch,
        })

    _save_river_history(history)


def _is_quiet_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return now.hour >= QUIET_HOURS_START or now.hour < QUIET_HOURS_END


def _is_notable_weather(snapshot: dict) -> bool:
    return any([
        snapshot["lightning_count"] > 0,
        snapshot["rain_in_1h"] >= 0.01,
        snapshot["current_rain_event_total"] >= 0.05,
        snapshot["wind_gust_mph"] >= 20,
        snapshot["current_temp_f"] >= 85,
        snapshot["current_temp_f"] <= 32,
    ])


def _storm_monitor_active(snapshot: dict | None) -> bool:
    if not snapshot:
        return False
    return any([
        snapshot["lightning_count"] > 0,
        snapshot["rain_in_1h"] >= 0.05,
        snapshot["current_rain_event_total"] >= 0.10,
    ])


def _record_weather_post(snapshot: dict, post_mode: str):
    global _last_posted_weather_snapshot, _last_posted_weather_epoch
    _last_posted_weather_snapshot = {**snapshot, "post_mode": post_mode}
    _last_posted_weather_epoch = time.time()
    _save_post_state()


def _record_sunrise_notice(date_text: str):
    global _last_sunrise_notice_date
    _last_sunrise_notice_date = date_text
    _save_post_state()


def _record_sunset_notice(date_text: str):
    global _last_sunset_notice_date
    _last_sunset_notice_date = date_text
    _save_post_state()


def _should_suppress_routine_post(snapshot: dict, quiet_mode: bool) -> bool:
    if not _last_posted_weather_snapshot:
        return False

    keepalive_seconds = (
        QUIET_HOURS_KEEPALIVE_SECONDS if quiet_mode else ROUTINE_POST_KEEPALIVE_SECONDS
    )
    if _last_posted_weather_epoch and (time.time() - _last_posted_weather_epoch) >= keepalive_seconds:
        return False

    last_snapshot = _last_posted_weather_snapshot

    if snapshot["headline_condition"] != last_snapshot.get("headline_condition"):
        return False
    if abs(snapshot["current_temp_f"] - last_snapshot.get("current_temp_f", snapshot["current_temp_f"])) >= 2:
        return False
    if abs(snapshot["wind_speed_mph"] - last_snapshot.get("wind_speed_mph", snapshot["wind_speed_mph"])) >= 3:
        return False
    if abs(snapshot["wind_gust_mph"] - last_snapshot.get("wind_gust_mph", snapshot["wind_gust_mph"])) >= 5:
        return False
    if abs(snapshot["rain_in_1h"] - last_snapshot.get("rain_in_1h", snapshot["rain_in_1h"])) >= 0.02:
        return False
    if abs(snapshot["rain_in_day"] - last_snapshot.get("rain_in_day", snapshot["rain_in_day"])) >= 0.05:
        return False
    if (
        snapshot.get("pressure_inhg") is not None
        and last_snapshot.get("pressure_inhg") is not None
        and abs(snapshot["pressure_inhg"] - last_snapshot["pressure_inhg"]) >= 0.05
    ):
        return False
    if (
        snapshot.get("dew_point_f") is not None
        and last_snapshot.get("dew_point_f") is not None
        and abs(snapshot["dew_point_f"] - last_snapshot["dew_point_f"]) >= 3
    ):
        return False
    if (
        abs(
            snapshot["current_rain_event_total"]
            - last_snapshot.get("current_rain_event_total", snapshot["current_rain_event_total"])
        )
        >= 0.05
    ):
        return False
    if snapshot["lightning_count"] != last_snapshot.get("lightning_count", 0):
        return False
    if snapshot["lightning_count"] > 0 and last_snapshot.get("lightning_count", 0) > 0:
        last_distance = last_snapshot.get("lightning_distance_mi")
        if last_distance is not None and abs(snapshot["lightning_distance_mi"] - last_distance) >= 5:
            return False
    if _is_notable_weather(snapshot) != _is_notable_weather(last_snapshot):
        return False

    return True


def _storm_follow_up_reason(snapshot: dict) -> str | None:
    if not _last_posted_weather_snapshot:
        return None

    last_snapshot = _last_posted_weather_snapshot
    previous_lightning = last_snapshot.get("lightning_count", 0)
    current_lightning = snapshot["lightning_count"]
    previous_distance = last_snapshot.get("lightning_distance_mi")
    current_distance = snapshot["lightning_distance_mi"]

    if current_lightning > 0:
        if previous_lightning <= 0 and current_distance <= 15:
            return "lightning_started"
        if current_distance <= 5 and (previous_distance is None or previous_distance > 5):
            return "lightning_nearby"
        if (
            previous_distance is not None
            and (previous_distance - current_distance) >= 5
            and current_distance <= 15
        ):
            return "lightning_closer"
        if (current_lightning - previous_lightning) >= 5 and current_lightning >= 8:
            return "storm_intensifying"

    rain_delta = snapshot["current_rain_event_total"] - last_snapshot.get("current_rain_event_total", 0.0)
    if snapshot["rain_in_1h"] >= 0.15 and rain_delta >= 0.10:
        return "rain_ramping"
    if snapshot["current_rain_event_total"] >= 0.35 and rain_delta >= 0.15:
        return "rain_adding_up"

    return None


def _storm_follow_up_is_urgent(reason: str) -> bool:
    return reason == "lightning_nearby"


def _storm_follow_up_lead(snapshot: dict, reason: str) -> str:
    time_text = _friendly_time(snapshot["observed_at"])
    lead_map = {
        "lightning_started": "lightning is now showing up nearby.",
        "lightning_nearby": "lightning is now within 5 miles.",
        "lightning_closer": "lightning is moving closer to town.",
        "storm_intensifying": "storms are getting more active nearby.",
        "rain_ramping": "rain is picking up.",
        "rain_adding_up": "rain is adding up quickly.",
    }
    detail = lead_map.get(reason, "conditions are changing quickly.")
    return f"Storm update for Peoria at {time_text}: {detail}"


def _build_wind_line(snapshot: dict) -> str:
    wind_line = f"Wind {round(snapshot['wind_speed_mph'])} mph from {snapshot['wind_dir_cardinal']}"
    if round(snapshot["wind_gust_mph"]) > round(snapshot["wind_speed_mph"]):
        wind_line += f", gusting to {round(snapshot['wind_gust_mph'])}"
    return wind_line


def _temperature_trend_line(current_temp_f: float) -> str | None:
    if len(_temp_history) < 2:
        return None

    now_epoch = time.time()
    target = now_epoch - 30 * 60
    candidates = [(t, temp) for (t, temp) in _temp_history if t <= target]
    if not candidates:
        return None

    prev_t, prev_temp = min(candidates, key=lambda x: abs(x[0] - target))
    delta = current_temp_f - prev_temp

    if delta <= -5:
        return "Temperatures are falling quickly."
    if delta >= 5:
        return "Temperatures are climbing quickly."
    return None


def _wind_trend_line(wind_speed_mph: float, wind_gust_mph: float) -> str | None:
    if wind_gust_mph >= 20 and (wind_gust_mph - wind_speed_mph) >= 6:
        return "Gusts are starting to kick up."
    if wind_speed_mph >= 18:
        return "Winds are staying noticeably up."
    return None


def _rain_trend_line(rain_in_1h: float, current_rain_event_total: float) -> str | None:
    if rain_in_1h >= 0.01 and current_rain_event_total <= 0.03:
        return "Rain just started."
    if current_rain_event_total >= 0.25:
        return "Rain is adding up across town."
    return None


def _lightning_trend_line(lightning_count: int, lightning_distance_mi: float) -> str | None:
    if lightning_count <= 0:
        return None
    if lightning_distance_mi <= 5:
        return "Storms remain nearby."
    return "Lightning is still in the area."


def _should_include_hashtag(
    current_temp_f: float,
    rain_in_1h: float,
    lightning_count: int,
    wind_gust_mph: float,
    current_rain_event_total: float,
) -> bool:
    return any([
        current_temp_f >= 85,
        current_temp_f <= 32,
        rain_in_1h >= 0.01,
        current_rain_event_total >= 0.05,
        lightning_count > 0,
        wind_gust_mph >= 20,
    ])


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
        prev_time = _friendly_time(datetime.fromtimestamp(prev_t))
        now_time = _friendly_time()
        return (
            f"Rapid temperature drop in Peoria: down {round(drop)}°F in about an hour.\n\n"
            f"{round(prev_temp)}°F to {round(current_temp_f)}°F from {prev_time} to {now_time}\n"
            f"#peoriaweather"
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
    narrative = _daily_summary_narrative(hi, rain, daily_max_wind_gust)

    if hi is not None and lo is not None:
        summary_message = (
            f"Peoria weather summary for {date_str}:\n\n"
            f"{narrative}\n"
            f"High {round(hi)}°F, low {round(lo)}°F\n"
            f"Rain: {rain:.2f}\"\n"
            f"Peak wind: {round(daily_max_wind_avg)} mph, gusting to {round(daily_max_wind_gust)}\n"
            f"#peoriaweather"
        )
    else:
        summary_message = (
            f"Peoria weather summary for {date_str}:\n\n"
            f"{narrative}\n"
            f"High/low: {hi_str} / {lo_str}\n"
            f"Rain: {rain:.2f}\"\n"
            f"Peak wind: {round(daily_max_wind_avg)} mph, gusting to {round(daily_max_wind_gust)}\n"
            f"#peoriaweather"
        )

    # post_to_mastodon(summary_message)
    post_to_bluesky(summary_message)
    send_telegram_message(summary_message)
    # post_tweet(summary_message)


def fetch_station_observation():
    station_id = os.getenv("WEATHERFLOW_STATION_ID")
    api_token = os.getenv("WEATHERFLOW_API_TOKEN")
    url = f"https://swd.weatherflow.com/swd/rest/observations/station/{station_id}?token={api_token}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data["obs"][0]
    except requests.RequestException as e:
        logging.error(f"Error fetching weather data: {e}")
        return None


def _maybe_send_rapid_change_alert(temp_f: float):
    alert_message = check_rapid_changes(temp_f)
    if alert_message:
        # post_to_mastodon(alert_message)
        post_to_bluesky(alert_message)
        send_telegram_message(alert_message)
        # post_tweet(alert_message)


def fetch_current_weather_snapshot():
    obs = fetch_station_observation()
    if not obs:
        return None

    temp_c = obs.get("air_temperature", 0)
    temp_f = temp_c * 9 / 5 + 32
    _maybe_send_rapid_change_alert(temp_f)
    return _build_weather_snapshot(obs)


def fetch_weather_data(post_mode: str = "routine", followup_reason: str | None = None):
    snapshot = fetch_current_weather_snapshot()
    if not snapshot:
        return None
    return format_weather_post(snapshot, post_mode=post_mode, followup_reason=followup_reason)


def _build_weather_snapshot(data):
    global daily_max_wind_avg, daily_max_wind_gust, daily_date
    global current_event_strike_total, last_strike_epoch_global
    global current_rain_event_total, rain_event_baseline, last_rain_epoch_global
    global _latest_weather_snapshot

    observed_at = datetime.now()
    current_date = observed_at.strftime("%Y-%m-%d")
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
    feels_like_c = data.get('feels_like', current_temp_c)
    feels_like_f = feels_like_c * 9 / 5 + 32

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
    pressure_inhg = _extract_pressure_inhg(data)
    _update_pressure_history(observed_at, pressure_inhg)
    dew_point_f = _compute_dew_point_f(current_temp_f, humidity)

    rain_mm_1h = data.get('precip_accum_last_1hr', 0)
    rain_mm_day = data.get('precip_accum_local_day', 0)
    rain_in_1h = rain_mm_1h * 0.0393701 if rain_mm_1h is not None else 0
    rain_in_day = rain_mm_day * 0.0393701 if rain_mm_day is not None else 0

    # Update daily stats for end-of-day summary
    _update_daily_stats(current_temp_f, rain_in_day)

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
        last_strike_time = _friendly_time(datetime.fromtimestamp(lightning_epoch))
        if (last_strike_epoch_global is None) or ((lightning_epoch - last_strike_epoch_global) >= 3 * 3600):
            current_event_strike_total = lightning_count
        else:
            current_event_strike_total = max(current_event_strike_total, lightning_count)
        last_strike_epoch_global = lightning_epoch
    else:
        last_strike_time = "N/A"
        current_event_strike_total = 0

    snapshot = {
        "observed_at": observed_at,
        "current_temp_f": current_temp_f,
        "feels_like_f": feels_like_f,
        "wind_speed_mph": wind_speed_mph,
        "wind_gust_mph": wind_gust_mph,
        "wind_dir_cardinal": wind_dir_cardinal,
        "humidity": humidity,
        "uv_index": uv_index,
        "pressure_inhg": pressure_inhg,
        "dew_point_f": dew_point_f,
        "rain_in_1h": rain_in_1h,
        "rain_in_day": rain_in_day,
        "current_rain_event_total": current_rain_event_total,
        "lightning_count": lightning_count,
        "lightning_distance_mi": lightning_distance_mi,
        "last_strike_time": last_strike_time,
        "headline_condition": _headline_condition(rain_in_1h, lightning_count),
    }
    _latest_weather_snapshot = snapshot
    return snapshot


def format_weather_post(snapshot: dict, post_mode: str = "routine", followup_reason: str | None = None):
    trend_lines = [
        _temperature_trend_line(snapshot["current_temp_f"]),
        _wind_trend_line(snapshot["wind_speed_mph"], snapshot["wind_gust_mph"]),
        _rain_trend_line(snapshot["rain_in_1h"], snapshot["current_rain_event_total"]),
        _lightning_trend_line(snapshot["lightning_count"], snapshot["lightning_distance_mi"]),
        _pressure_trend_line(snapshot),
    ]

    lead_line = _local_station_lead(snapshot)

    if post_mode == "storm_followup":
        lines = [
            _storm_follow_up_lead(snapshot, followup_reason or ""),
            "",
            f"{round(snapshot['current_temp_f'])}°F, feels like {round(snapshot['feels_like_f'])}°F",
        ]
        if snapshot["rain_in_1h"] >= 0.01 or snapshot["rain_in_day"] >= 0.01:
            lines.append(
                f"Rain {snapshot['rain_in_1h']:.2f}\" last hour, {snapshot['rain_in_day']:.2f}\" today"
            )
        if snapshot["current_rain_event_total"] >= 0.01:
            lines.append(f"This rain event: {snapshot['current_rain_event_total']:.2f}\"")
        lines.append(_build_wind_line(snapshot))
        if snapshot["lightning_count"] > 0:
            lines.append(f"Lightning: {snapshot['lightning_count']} strikes in the last 3 hours")
            if snapshot["last_strike_time"] != "N/A":
                lines.append(
                    f"Closest strike: {round(snapshot['lightning_distance_mi'])} mi at {snapshot['last_strike_time']}"
                )
        lines.append("#peoriaweather")
        return "\n".join(lines)

    lines = [
        lead_line,
        "",
        f"Feels like {round(snapshot['feels_like_f'])}°F",
    ]

    if snapshot["current_temp_f"] >= 33:
        if snapshot["rain_in_1h"] >= 0.01 or snapshot["rain_in_day"] >= 0.01:
            lines.append(
                f"Rain {snapshot['rain_in_1h']:.2f}\" last hour, {snapshot['rain_in_day']:.2f}\" today"
            )
        if snapshot["current_rain_event_total"] >= 0.01:
            lines.append(f"This rain event: {snapshot['current_rain_event_total']:.2f}\"")
    else:
        snow_in_1h = snapshot["rain_in_1h"] * 10
        snow_in_day = snapshot["rain_in_day"] * 10
        if snow_in_1h >= 0.1 or snow_in_day >= 0.1:
            lines.append(f"Snow est. {snow_in_1h:.1f}\" last hour, {snow_in_day:.1f}\" today")

    lines.append(_build_wind_line(snapshot))

    if post_mode != "quiet":
        for trend_line in trend_lines:
            if trend_line and trend_line not in lines:
                lines.append(trend_line)

    if snapshot["lightning_count"] > 0:
        lines.append(f"Lightning: {snapshot['lightning_count']} strikes in the last 3 hours")
        if snapshot["last_strike_time"] != "N/A":
            lines.append(
                f"Closest strike: {round(snapshot['lightning_distance_mi'])} mi at {snapshot['last_strike_time']}"
            )
    elif post_mode != "quiet":
        dew_point_line = _dew_point_line(snapshot["current_temp_f"], snapshot.get("dew_point_f"))
        if dew_point_line:
            lines.append(dew_point_line)
        if snapshot["uv_index"] >= 3 and _is_daylight(snapshot["observed_at"]):
            lines.append(f"UV index {round(snapshot['uv_index'])}")
        sunrise_line = _sunrise_detail_line(snapshot["observed_at"])
        if sunrise_line:
            lines.append(sunrise_line)
        sunset_line = _sunset_detail_line(snapshot["observed_at"])
        if sunset_line:
            lines.append(sunset_line)
        forecast_line = fetch_nws_forecast_peek()
        if forecast_line:
            lines.append(forecast_line)

    if _should_include_hashtag(
        snapshot["current_temp_f"],
        snapshot["rain_in_1h"],
        snapshot["lightning_count"],
        snapshot["wind_gust_mph"],
        snapshot["current_rain_event_total"],
    ):
        lines.append("#peoriaweather")
    return "\n".join(lines)


def format_weather_data(data, post_mode: str = "routine", followup_reason: str | None = None):
    snapshot = _build_weather_snapshot(data)
    return format_weather_post(snapshot, post_mode=post_mode, followup_reason=followup_reason)


def post_weather_update(weather_message: str, snapshot: dict, post_mode: str):
    logging.info("Sending %s weather post (%s).", post_mode, _snapshot_log_summary(snapshot))
    # post_to_mastodon(weather_message)
    post_to_bluesky(weather_message)
    send_telegram_message(weather_message)
    # post_tweet(weather_message)
    _record_weather_post(snapshot, post_mode)


def check_storm_follow_up():
    global _last_storm_follow_up_check_epoch, _last_storm_follow_up_epoch

    monitor_snapshot = _latest_weather_snapshot or _last_posted_weather_snapshot
    if not _storm_monitor_active(monitor_snapshot):
        return

    now_epoch = time.time()
    if (now_epoch - _last_storm_follow_up_check_epoch) < STORM_FOLLOW_UP_CHECK_INTERVAL:
        return
    _last_storm_follow_up_check_epoch = now_epoch

    snapshot = fetch_current_weather_snapshot()
    if not snapshot:
        return

    reason = _storm_follow_up_reason(snapshot)
    if not reason:
        return

    if (
        _last_storm_follow_up_epoch
        and (now_epoch - _last_storm_follow_up_epoch) < STORM_FOLLOW_UP_COOLDOWN
        and not _storm_follow_up_is_urgent(reason)
    ):
        return

    weather_message = format_weather_post(snapshot, post_mode="storm_followup", followup_reason=reason)
    post_weather_update(weather_message, snapshot, "storm_followup")
    _last_storm_follow_up_epoch = time.time()


def check_sunrise_notice(now: datetime | None = None):
    now = now or datetime.now(PEORIA_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PEORIA_TIMEZONE)
    else:
        now = now.astimezone(PEORIA_TIMEZONE)

    today = now.strftime("%Y-%m-%d")
    if _last_sunrise_notice_date == today:
        return

    minutes_until = _minutes_until_sunrise(now)
    if minutes_until < 0 or minutes_until > SUNRISE_NOTICE_MINUTES:
        return

    snapshot = fetch_current_weather_snapshot()
    if not snapshot:
        logging.warning("Sunrise notice skipped: could not fetch a weather snapshot.")
        return

    logging.info(
        "Sunrise notice: posting %s minutes before sunrise (%s).",
        minutes_until,
        _sunrise_detail_line(now),
    )
    weather_message = _format_sunrise_notice(snapshot, now)
    post_weather_update(weather_message, snapshot, "sunrise_notice")
    _record_sunrise_notice(today)


def check_sunset_notice(now: datetime | None = None):
    now = now or datetime.now(PEORIA_TIMEZONE)
    if now.tzinfo is None:
        now = now.replace(tzinfo=PEORIA_TIMEZONE)
    else:
        now = now.astimezone(PEORIA_TIMEZONE)

    today = now.strftime("%Y-%m-%d")
    if _last_sunset_notice_date == today:
        return

    minutes_until = _minutes_until_sunset(now)
    if minutes_until < 0 or minutes_until > SUNSET_NOTICE_MINUTES:
        return

    snapshot = fetch_current_weather_snapshot()
    if not snapshot:
        logging.warning("Sunset notice skipped: could not fetch a weather snapshot.")
        return

    logging.info(
        "Sunset notice: posting %s minutes before sunset (%s).",
        minutes_until,
        _sunset_detail_line(now),
    )
    weather_message = _format_sunset_notice(snapshot, now)
    post_weather_update(weather_message, snapshot, "sunset_notice")
    _record_sunset_notice(today)


# Functions to post to social media platforms
def _fit_bluesky_text(message: str) -> str:
    if len(message) <= BLUESKY_CHAR_LIMIT:
        return message

    lines = message.splitlines()
    source_lines = [line for line in lines if line.startswith("Source: ")]
    body_lines = [line for line in lines if line not in source_lines and not line.startswith("#")]
    header_lines = []
    remaining_lines = body_lines
    if body_lines:
        header_lines = [body_lines[0]]
        if len(body_lines) > 1 and body_lines[1] == "":
            header_lines.append("")
            remaining_lines = body_lines[2:]
        else:
            remaining_lines = body_lines[1:]

    suffix_lines = []
    if source_lines:
        suffix_lines.append(source_lines[-1])
    suffix = ("\n" + "\n".join(suffix_lines)) if suffix_lines else ""
    budget = BLUESKY_CHAR_LIMIT - len(suffix)

    priority_prefixes = ("Where:", "Stage:", "Flood stage:", "Forecast:", "What:", "When:")
    low_priority_prefixes = ("Issued at", "Until ")
    prioritized_lines = [line for line in remaining_lines if not line.startswith(low_priority_prefixes)]
    low_priority_lines = [line for line in remaining_lines if line.startswith(low_priority_prefixes)]
    ordered_lines = list(header_lines)
    for prefix in priority_prefixes:
        for line in prioritized_lines:
            if line.startswith(prefix) and line not in ordered_lines:
                ordered_lines.append(line)
    for line in prioritized_lines:
        if line not in ordered_lines:
            ordered_lines.append(line)
    ordered_lines.extend(low_priority_lines)

    kept_lines = []
    for line in ordered_lines:
        candidate = "\n".join(kept_lines + [line]).strip()
        if len(candidate) + len("\n...") <= budget:
            kept_lines.append(line)

    body = "\n".join(kept_lines).strip()
    body = f"{body}\n..." if body else "..."
    fitted = f"{body}{suffix}".strip()

    if len(fitted) > BLUESKY_CHAR_LIMIT:
        fitted = fitted[: BLUESKY_CHAR_LIMIT - 3].rstrip() + "..."
    return fitted


def post_to_bluesky(weather_message):
    if session is None:
        logging.warning("Bluesky session not initialized. Skipping Bluesky post.")
        return False
    post_message = _fit_bluesky_text(weather_message)
    if post_message != weather_message:
        logging.info(
            "Bluesky: shortened post from %s to %s characters.",
            len(weather_message),
            len(post_message),
        )
    try:
        post_text(session, post_message)
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
        logging.info("Heartbeat sent successfully for %s.", _friendly_time())
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
    snapshot = fetch_current_weather_snapshot()
    if snapshot:
        weather_message = format_weather_post(snapshot, post_mode="routine")
        post_weather_update(weather_message, snapshot, "force")
    else:
        logging.warning("Force update skipped: no weather snapshot available.")


# Register the signal handler for SIGUSR1
signal.signal(signal.SIGUSR1, force_update)
_load_post_state()


# Scheduler function that runs the weather bot at defined intervals
def scheduler():
    while True:
        now = datetime.now(PEORIA_TIMEZONE)
        minute = now.minute
        hour = now.hour
        today = now.strftime("%Y-%m-%d")

        check_nws_alerts()
        check_river_flood_status()
        check_sunrise_notice(now)
        check_sunset_notice(now)
        if minute % 15 != 0:
            check_storm_follow_up()

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
            logging.info("Routine cycle %s: checking current conditions.", _friendly_time(now))
            snapshot = fetch_current_weather_snapshot()
            if snapshot:
                quiet_mode = _is_quiet_hours(now) and not _is_notable_weather(snapshot)
                if _should_suppress_routine_post(snapshot, quiet_mode):
                    logging.info(
                        "Routine cycle %s: suppressed (%s).",
                        _friendly_time(now),
                        _routine_suppression_reason(snapshot, quiet_mode),
                    )
                else:
                    post_mode = "quiet" if quiet_mode else "routine"
                    logging.info(
                        "Routine cycle %s: posting mode=%s (%s).",
                        _friendly_time(now),
                        post_mode,
                        _snapshot_log_summary(snapshot),
                    )
                    weather_message = format_weather_post(snapshot, post_mode=post_mode)
                    post_weather_update(weather_message, snapshot, post_mode)
            else:
                logging.warning("Routine cycle %s: could not fetch a weather snapshot.", _friendly_time(now))

        # Send a heartbeat every 30 minutes
        if minute % 30 == 0:
            send_heartbeat()

        # Sleep until the start of the next minute
        time.sleep(60 - datetime.now().second)


# Main execution block
if __name__ == "__main__":
    try:
        logging.info("Weather bot starting.")
        scheduler()
    except KeyboardInterrupt:
        logging.info("Weather bot stopped manually.")
