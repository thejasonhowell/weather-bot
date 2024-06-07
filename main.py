#!/usr/bin/env python3
import requests
import tweepy
from mastodon import Mastodon

mastodon = Mastodon(
    client_id='YOUR_API_KEY',
    client_secret='YOUR_API_KEY',
    access_token='YOUR_API_KEY',
    api_base_url='https://masto.globaleas.org'


)


# Configure the Twitter client
client = tweepy.Client(
    consumer_key="YOUR_API_KEY",
    consumer_secret="YOUR_API_KEY",
    access_token="YOUR_API_KEY",
    access_token_secret="YOUR_API_KEY"
)

def fetch_weather_data():
    url = "https://swd.weatherflow.com/swd/rest/observations/station/118444?token=YOUR_API_KEY"
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

def format_weather_data(data):
    current_temp_f = data['air_temperature'] * 9 / 5 + 32
    pressure_inHg = data['barometric_pressure'] * 0.02953
    precip_in = data.get('precip', 0) * 0.03937
    precip_last_hour_mm = data.get('precip_accum_last_1hr', 0)
    precip_last_hour_in = precip_last_hour_mm * 0.0393701
    precip_local_day_in = data.get('precip_accum_local_day', 0) * 0.03937

    # Retrieve and convert lightning strike data
    lightning_last_distance_km = data.get('lightning_strike_last_distance', 0)
    lightning_last_distance_miles = lightning_last_distance_km * 0.621371
    lightning_strikes_3hr = data.get('lightning_strike_count_last_3hr', 0)  # Adjusted key

    # Wind details
    wind_speed_mph = data.get('wind_avg', 0)
    wind_dir_degrees = data.get('wind_direction', 0)
    wind_dir_cardinal = degrees_to_cardinal(wind_dir_degrees)
    wind_gusts_mph = data.get('wind_gust', 0)
    wind_gusts_dir = data.get('wind_gust_direction', 0)
    wind_gusts_cardinal = degrees_to_cardinal(wind_gusts_dir)

    return (
        f"Current temperature: {current_temp_f:.1f}°F\n"
        f"Wind: {wind_speed_mph} mph {wind_dir_degrees}° ({wind_dir_cardinal}), "
        f"Gusts: {wind_gusts_mph} mph {wind_gusts_dir}° ({wind_gusts_cardinal})\n"
        f"Humidity: {data['relative_humidity']}%\n"
        f"Pressure: {pressure_inHg:.2f} inHg\n"
        f"Lightning strikes last 3 hours: {lightning_strikes_3hr}, Distance: {lightning_last_distance_miles:.1f} miles\n"
        f"Precipitation: {precip_in:.2f} in, Last hour: {precip_last_hour_in:.2f} in, Local day: {precip_local_day_in:.2f} in\n"
        f"UV Index: {data.get('uv', 0)}\n"
        f"Brightness: {data.get('brightness', 0)} lux"
    )

def post_tweet():
    weather_data = fetch_weather_data()
    if "Failed" not in weather_data:
        try:
            client.create_tweet(text=weather_data)
            print("Weather data posted on Twitter and Mastodon!")
        except tweepy.HTTPException as e:
            print(f"Failed to post tweet due to API error: {e}")
        except tweepy.TweepyException as e:
            print(f"Failed to post tweet and toot: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
    else:
        print(weather_data)


# Post the weather data
weather_message = fetch_weather_data()
mastodon.toot(weather_message)
post_tweet()

