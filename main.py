import tweepy
import requests
from mastodon import Mastodon
from bsky_bridge import BskySession, post_text
import logging

# Configure logging (optional, but recommended for larger scripts)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(message)s'
)

# Initialize Mastodon client
mastodon = Mastodon(
    client_id='YOUR_MASTODON_CLIENT_ID',
    client_secret='YOUR_MASTODON_CLIENT_SECRET',
    access_token='YOUR_MASTODON_ACCESS_TOKEN',
    api_base_url='https://masto.globaleas.org'  # Replace with your Mastodon instance URL
)

# Configure the Twitter client
client = tweepy.Client(
    consumer_key="YOUR_TWITTER_CONSUMER_KEY",
    consumer_secret="YOUR_TWITTER_CONSUMER_SECRET",
    access_token="YOUR_TWITTER_ACCESS_TOKEN",
    access_token_secret="YOUR_TWITTER_ACCESS_TOKEN_SECRET"
)

# Initialize Bluesky session
session = BskySession("YOUR_BLUESKY_USERNAME", "YOUR_BLUESKY_PASSWORD")

def fetch_weather_data():
    url = "https://swd.weatherflow.com/swd/rest/observations/station/118444?token=YOUR_WEATHERFLOW_API_TOKEN"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return format_weather_data(data['obs'][0])
    except requests.RequestException as e:
        return f"Failed to fetch weather data: {str(e)}"

def degrees_to_cardinal(d):
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    ix = round(d / 45) % 8
    return dirs[ix]

def calculate_heat_index(temperature_f, humidity):
    # Temperature in Fahrenheit and humidity in percentage (0-100)
    if temperature_f < 80 or humidity < 40:
        return temperature_f  # Below these values, heat index is roughly the same as temperature

    # Constants for the heat index formula
    c1, c2, c3 = -42.379, 2.04901523, 10.14333127
    c4, c5, c6 = -0.22475541, -6.83783e-3, -5.481717e-2
    c7, c8, c9 = 1.22874e-3, 8.5282e-4, -1.99e-6

    heat_index = (
        c1 + (c2 * temperature_f) + (c3 * humidity) +
        (c4 * temperature_f * humidity) +
        (c5 * temperature_f**2) +
        (c6 * humidity**2) +
        (c7 * temperature_f**2 * humidity) +
        (c8 * temperature_f * humidity**2) +
        (c9 * temperature_f**2 * humidity**2)
    )

    return heat_index

def calculate_wind_chill(temperature_f, wind_speed_mph):
    # Temperature in Fahrenheit and wind speed in mph
    if temperature_f > 50 or wind_speed_mph <= 3:
        return temperature_f  # Wind chill is roughly the same as temperature in these conditions

    wind_chill = (
        35.74 + (0.6215 * temperature_f) -
        (35.75 * (wind_speed_mph**0.16)) +
        (0.4275 * temperature_f * (wind_speed_mph**0.16))
    )

    return wind_chill

def format_weather_data(data):
    current_temp_c = data.get('air_temperature', 0)
    current_temp_f = current_temp_c * 9 / 5 + 32
    pressure_pa = data.get('barometric_pressure', 0)
    pressure_inHg = pressure_pa * 0.0002953  # Convert Pascals to inches of mercury
    pressure_trend = data.get('pressure_trend', 'steady')  # 'falling', 'rising', or 'steady'
    precip_mm = data.get('precip', 0)
    precip_in = precip_mm * 0.0393701  # Convert mm to inches
    precip_last_hour_mm = data.get('precip_accum_last_1hr', 0)
    precip_last_hour_in = precip_last_hour_mm * 0.0393701
    precip_local_day_mm = data.get('precip_accum_local_day', 0)
    precip_local_day_in = precip_local_day_mm * 0.0393701

    # Retrieve and convert lightning strike data
    lightning_last_distance_km = data.get('lightning_strike_last_distance', 0)
    lightning_last_distance_miles = lightning_last_distance_km * 0.621371
    lightning_strikes_3hr = data.get('lightning_strike_count_last_3hr', 0)

    # Wind details
    wind_speed_mps = data.get('wind_avg', 0)
    wind_speed_mph = wind_speed_mps * 2.23694  # Convert m/s to mph
    wind_dir_degrees = data.get('wind_direction', 0)
    wind_dir_cardinal = degrees_to_cardinal(wind_dir_degrees)
    wind_gusts_mps = data.get('wind_gust', 0)
    wind_gusts_mph = wind_gusts_mps * 2.23694

    # Humidity
    humidity = data.get('relative_humidity', 0)

    # Determine heat index or wind chill based on conditions
    if current_temp_f >= 80:
        feels_like = calculate_heat_index(current_temp_f, humidity)
        temp_emoji = f"🔥 {feels_like:.1f}°F (feels like)" if feels_like > current_temp_f else f"😃 {current_temp_f:.1f}°F"
    elif current_temp_f <= 50:
        feels_like = calculate_wind_chill(current_temp_f, wind_speed_mph)
        temp_emoji = f"🥶 {feels_like:.1f}°F (feels like)" if feels_like < current_temp_f else f"😃 {current_temp_f:.1f}°F"
    else:
        temp_emoji = f"😃 {current_temp_f:.1f}°F"

    # Determine the pressure emoji
    if pressure_trend == 'falling':
        pressure_emoji = f"⬇️ {pressure_inHg:.2f} inHg"
    elif pressure_trend == 'rising':
        pressure_emoji = f"⬆️ {pressure_inHg:.2f} inHg"
    else:
        pressure_emoji = f"➡️ {pressure_inHg:.2f} inHg"

    # Determine wind emoji
    if wind_speed_mph <= 10:
        wind_emoji = f"🍃 {wind_speed_mph:.1f} mph {wind_dir_degrees}° ({wind_dir_cardinal})"
    elif 10.1 <= wind_speed_mph <= 25:
        wind_emoji = f"🌬 {wind_speed_mph:.1f} mph {wind_dir_degrees}° ({wind_dir_cardinal})"
    else:  # Above 25 mph
        wind_emoji = f"💨 {wind_speed_mph:.1f} mph {wind_dir_degrees}° ({wind_dir_cardinal})"

    # Determine lightning emoji
    if lightning_strikes_3hr > 0:
        lightning_emoji = f"{lightning_strikes_3hr} ⚡ in last 3 hours, Distance: {lightning_last_distance_miles:.1f} miles"
    else:
        lightning_emoji = "No ⚡ in last 3 hours"

    # Determine precipitation emoji based on temperature
    if current_temp_f > 33:
        precip_emoji = f"🌧 {precip_in:.2f} in, Last hour: {precip_last_hour_in:.2f} in, Day: {precip_local_day_in:.2f} in"
    else:
        precip_emoji = f"❄️ {precip_in:.2f} in, Last hour: {precip_last_hour_in:.2f} in, Day: {precip_local_day_in:.2f} in"

    # UV index and brightness
    uv_index = data.get('uv', 0)
    brightness = data.get('brightness', 0)

    # Consolidated weather message
    return (
        f"{temp_emoji}\n"
        f"{wind_emoji}\n"
        f"💧 {humidity}%\n"
        f"{pressure_emoji}\n"
        f"{lightning_emoji}\n"
        f"{precip_emoji}\n"
        f"☀️ UV Index: {uv_index}\n"
        f"💡 {brightness} lux\n"
        f"#peoriaweather"
    )

def post_to_bluesky(weather_message):
    try:
        response = post_text(session, weather_message)
        print("Bluesky: Weather data posted.")
    except Exception as e:
        print("Bluesky: posting failed.")

def post_to_mastodon(weather_message):
    try:
        mastodon.toot(weather_message)
        print("Mastodon: Weather data posted.")
    except Exception as e:
        print("Mastodon: posting failed.")

def post_tweet(weather_message):
    if "Failed" not in weather_message:
        try:
            client.create_tweet(text=weather_message)
            print("Twitter: Weather data posted.")
        except tweepy.HTTPException:
            print("Twitter: posting failed.")
        except tweepy.TweepyException:
            print("Twitter: posting failed.")
        except Exception:
            print("Twitter: posting failed.")
    else:
        print(weather_message)

def send_heartbeat():
    url = "https://uptime.betterstack.com/api/v1/heartbeat/YOUR_HEARTBEAT_ID"
    try:
        response = requests.get(url)
        response.raise_for_status()
        print("Heartbeat sent successfully!")
    except requests.RequestException:
        print("Heartbeat: sending failed.")

def main():
    weather_message = fetch_weather_data()
    if "Failed" not in weather_message:
        # Post to Bluesky
        post_to_bluesky(weather_message)

        # Post to Mastodon
        post_to_mastodon(weather_message)

        # Post to Twitter
        post_tweet(weather_message)

        # Send heartbeat
        send_heartbeat()
    else:
        print("Failed to fetch weather data.")

if __name__ == "__main__":
    main()