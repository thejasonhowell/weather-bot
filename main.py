#!/usr/bin/env python3

import tweepy
import requests
from mastodon import Mastodon
from bsky_bridge import BskySession, post_text
import logging
import os
import json

# Configure logging to console only (no file output)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler()  # Logs to terminal only
    ]
)

# Safely initialize Bluesky session
def initialize_bsky_session():
    session_file = "bsky_session.json"
    if os.path.exists(session_file):
        try:
            with open(session_file, "r") as file:
                credentials = json.load(file)
                return BskySession(credentials["handle"], credentials["password"])
        except Exception as e:
            logging.error(f"Error loading Bluesky session: {e}")
    else:
        try:
            session = BskySession(
                os.getenv("BLUESKY_HANDLE"), os.getenv("BLUESKY_PASSWORD")
            )
            with open(session_file, "w") as file:
                json.dump(
                    {
                        "handle": os.getenv("BLUESKY_HANDLE"),
                        "password": os.getenv("BLUESKY_PASSWORD")
                    },
                    file
                )
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

# Function to convert degrees to cardinal directions
def degrees_to_cardinal(d):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ix = round(d / 45) % 8
    return dirs[ix]

# Function to fetch weather data
def fetch_weather_data():
    url = os.getenv("WEATHER_API_URL")
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        obs = data['obs'][0]

        # Extract key values
        current_temp_c = obs.get('air_temperature', 0)
        current_temp_f = current_temp_c * 9 / 5 + 32
        wind_speed_mps = obs.get('wind_avg', 0)
        wind_speed_mph = wind_speed_mps * 2.23694

        weather_message = format_weather_data(obs)

        conditions = {
            "temp_f": current_temp_f,
            "wind_speed_mph": wind_speed_mph
        }

        return conditions, weather_message
    except requests.RequestException as e:
        logging.error(f"Error fetching weather data: {e}")
        return None, None

# Function to format weather data
def format_weather_data(data):
    # Temperature
    current_temp_c = data.get('air_temperature', 0)
    current_temp_f = current_temp_c * 9 / 5 + 32

    # Precipitation
    precip_mm = data.get('precip', 0)
    precip_in = precip_mm * 0.0393701  # Convert mm to inches

    # Last hour and daily totals
    precip_last_hour_mm = data.get('precip_accum_last_1hr', 0)
    precip_last_hour_in = precip_last_hour_mm * 0.0393701
    precip_local_day_mm = data.get('precip_accum_local_day', 0)
    precip_local_day_in = precip_local_day_mm * 0.0393701

    # Snow-to-liquid ratio
    if current_temp_f <= 32:  # Freezing or below
        ratio = 10  # Default 10:1 ratio for snow
        snowfall_hour = precip_last_hour_in * ratio
        snowfall_day = precip_local_day_in * ratio
        precip_emoji = (
            f"❄️ {snowfall_hour:.1f} in snow (1hr), {snowfall_day:.1f} in snow (day)"
            f" ({precip_last_hour_in:.2f} / {precip_local_day_in:.2f} in liquid)"
        )
    else:
        precip_emoji = (
            f"🌧 {precip_last_hour_in:.2f} in rain (1hr), {precip_local_day_in:.2f} in rain (day)"
        )

    # Wind
    wind_speed_mps = data.get('wind_avg', 0)
    wind_speed_mph = wind_speed_mps * 2.23694
    wind_dir_degrees = data.get('wind_direction', 0)
    wind_dir_cardinal = degrees_to_cardinal(wind_dir_degrees)

    # Other data
    humidity = data.get('relative_humidity', 0)
    uv_index = data.get('uv', 0)
    brightness = data.get('brightness', 0)

    # Construct final weather message
    return (
        f"🌡 {current_temp_f:.1f}°F\n"
        f"🍃 {wind_speed_mph:.1f} mph {wind_dir_degrees}° ({wind_dir_cardinal})\n"
        f"{precip_emoji}\n"
        f"💧 {humidity}%\n"
        f"☀️ UV Index: {uv_index}\n"
        f"💡 {brightness} lux\n"
        f"#peoriaweather"
    )

# Functions to post data
def post_to_bluesky(weather_message):
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

def send_heartbeat():
    url = os.getenv("HEARTBEAT_URL")
    try:
        requests.get(url).raise_for_status()
        logging.info("Heartbeat sent successfully!")
    except requests.RequestException as e:
        logging.error(f"Heartbeat: Sending failed. Error: {e}")

# Main function
def main():
    conditions, weather_message = fetch_weather_data()
    if weather_message is None: return
    post_to_bluesky(weather_message)
    post_to_mastodon(weather_message)
    post_tweet(weather_message)
    send_heartbeat()

if __name__ == "__main__":
    main()