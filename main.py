#!/usr/bin/env python3
import tweepy
import requests
from mastodon import Mastodon

# Initialize Mastodon client with your API tokens
mastodon = Mastodon(
    client_id='YOUR_API_KEY',
    client_secret='YOUR_API_KEY',
    access_token='YOUR_API_KEY',
    api_base_url='https://masto.globaleas.org'
)

# Configure the Twitter client with your API tokens
client = tweepy.Client(
    consumer_key="YOUR_API_KEY",
    consumer_secret="YOUR_API_KEY",
    access_token="YOUR_API_KEY-YOUR_API_KEY",
    access_token_secret="YOUR_API_KEY"
)

def fetch_weather_data():
    url = "https://swd.weatherflow.com/swd/rest/observations/station/YOUR_API_KEY"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return format_weather_data(data['obs'][0])
    except requests.RequestException as e:
        return f"Failed to fetch weather data: {str(e)}"

def degrees_to_cardinal(d):
    if d is None or not isinstance(d, (int, float)):
        return "N/A"
    dirs = ["N", "NNE", "NE", "ENE",
            "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW",
            "W", "WNW", "NW", "NNW"]
    ix = int((d + 11.25)/22.5) % 16
    return dirs[ix]

def format_weather_data(data):
    # Temperature
    current_temp_c = data.get('air_temperature', 0)
    current_temp_f = current_temp_c * 9 / 5 + 32

    # Pressure
    barometric_pressure = data.get('barometric_pressure', 0)
    pressure_inHg = barometric_pressure * 0.02953  # Assuming pressure is in hPa
    pressure_trend = data.get('pressure_trend', 'steady')

    # Precipitation
    precip_mm = data.get('precip', 0)
    precip_in = precip_mm * 0.0393701
    precip_last_hour_mm = data.get('precip_accum_last_1hr', 0)
    precip_last_hour_in = precip_last_hour_mm * 0.0393701
    precip_local_day_mm = data.get('precip_accum_local_day', 0)
    precip_local_day_in = precip_local_day_mm * 0.0393701

    # Lightning data
    lightning_last_distance_km = data.get('lightning_strike_last_distance', None)
    lightning_strikes_3hr = data.get('lightning_strike_count_last_3hr', 0)
    if lightning_last_distance_km is not None:
        lightning_last_distance_miles = lightning_last_distance_km * 0.621371
        lightning_info = (
            f"⚡ Lightning strikes last 3 hours: {lightning_strikes_3hr}, "
            f"Distance: {lightning_last_distance_miles:.1f} miles\n"
        )
    else:
        lightning_info = f"⚡ Lightning strikes last 3 hours: {lightning_strikes_3hr}\n"

    # Wind details
    wind_speed_ms = data.get('wind_avg', 0)
    wind_speed_mph = wind_speed_ms * 2.23694

    wind_dir_degrees = data.get('wind_direction', None)
    wind_dir_cardinal = degrees_to_cardinal(wind_dir_degrees)
    wind_dir_degrees_str = f"{wind_dir_degrees}°" if wind_dir_degrees is not None else "N/A"

    # Remove gust direction and cardinal direction
    wind_gusts_ms = data.get('wind_gust', 0)
    wind_gusts_mph = wind_gusts_ms * 2.23694

    # Other details
    relative_humidity = data.get('relative_humidity', 'N/A')
    uv_index = data.get('uv', 'N/A')
    brightness = data.get('brightness', 'N/A')

    # Determine the temperature emoji
    if current_temp_f > 90:
        temp_emoji = f"🌡️ Temp: {current_temp_f:.2f}°F 🥵"
    elif current_temp_f < 40:
        temp_emoji = f"🌡️ Temp: {current_temp_f:.2f}°F 🥶"
    else:
        temp_emoji = f"🌡️ Temp: {current_temp_f:.2f}°F 😃"

    # Determine the pressure emoji
    if pressure_trend == 'falling':
        pressure_emoji = f"⬇️ Pressure: {pressure_inHg:.2f} inHg"
    elif pressure_trend == 'rising':
        pressure_emoji = f"⬆️ Pressure: {pressure_inHg:.2f} inHg"
    else:
        pressure_emoji = f"➡️ Pressure: {pressure_inHg:.2f} inHg"

    # Build the weather message
    weather_message = (
        f"{temp_emoji}\n"
        f"💨 Wind: {wind_speed_mph:.2f} mph {wind_dir_degrees_str} ({wind_dir_cardinal}), "
        f"Gusts: {wind_gusts_mph:.2f} mph\n"
        f"💧 Humidity: {relative_humidity}%\n"
        f"{pressure_emoji}\n"
        f"{lightning_info}"
        f"🌧 Precipitation: {precip_in:.2f} in, "
        f"Last hour: {precip_last_hour_in:.2f} in, "
        f"Local day: {precip_local_day_in:.2f} in\n"
        f"☀️ UV Index: {uv_index}\n"
        f"💡 Brightness: {brightness} lux"
    )

    return weather_message

def post_tweet(weather_message):
    if "Failed" not in weather_message:
        try:
            client.create_tweet(text=weather_message)
            print("Weather data posted on Twitter!")
        except tweepy.HTTPException as e:
            print(f"Failed to post tweet due to API error: {e}")
        except tweepy.TweepyException as e:
            print(f"Failed to post tweet: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
    else:
        print(weather_message)

def send_heartbeat():
    url = "https://uptime.betterstack.com/api/v1/heartbeat/YOUR_API_KEY"
    try:
        response = requests.get(url)
        response.raise_for_status()
        print("Heartbeat sent successfully!")
    except requests.RequestException as e:
        print(f"Failed to send heartbeat: {str(e)}")

# Post the weather data
weather_message = fetch_weather_data()
if "Failed" not in weather_message:
    try:
        mastodon.toot(weather_message)
        print("Weather data posted on Mastodon!")
    except Exception as e:
        print(f"Failed to post to Mastodon: {e}")
    post_tweet(weather_message)
else:
    print(weather_message)
send_heartbeat()