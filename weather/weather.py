from typing import Any, Dict
import httpx
from mcp.server.fastmcp import FastMCP
import os
import json
from pathlib import Path
from typing import Dict, Optional
from fastmcp import FastMCP
from dotenv import load_dotenv
from aiohttp import ClientSession
import asyncio

# Initialize FastMCP server
mcp = FastMCP("weather")

load_dotenv()

# Constants
NWS_API_BASE = "https://api.weather.gov"
USER_AGENT = "weather-app/1.0"



async def make_nws_request(url: str) -> dict[str, Any] | None:
    """Make a request to the NWS API with proper error handling."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/geo+json"
    }
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            return None

def format_alert(feature: dict) -> str:
    """Format an alert feature into a readable string."""
    props = feature["properties"]
    return f"""
Event: {props.get('event', 'Unknown')}
Area: {props.get('areaDesc', 'Unknown')}
Severity: {props.get('severity', 'Unknown')}
Description: {props.get('description', 'No description available')}
Instructions: {props.get('instruction', 'No specific instructions provided')}
"""


@mcp.tool()
async def get_alerts(state: str) -> str:
    """Get weather alerts for a US state.

    Args:
        state: Two-letter US state code (e.g. CA, NY)
    """
    url = f"{NWS_API_BASE}/alerts/active/area/{state}"
    data = await make_nws_request(url)

    if not data or "features" not in data:
        return "Unable to fetch alerts or no alerts found."

    if not data["features"]:
        return "No active alerts for this state."

    alerts = [format_alert(feature) for feature in data["features"]]
    return "\n---\n".join(alerts)

@mcp.tool()
async def get_forecast(latitude: float, longitude: float) -> str:
    """Get weather forecast for a location.

    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
    """
    # First get the forecast grid endpoint
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)

    if not points_data:
        return "Unable to fetch forecast data for this location."

    # Get the forecast URL from the points response
    forecast_url = points_data["properties"]["forecast"]
    forecast_data = await make_nws_request(forecast_url)

    if not forecast_data:
        return "Unable to fetch detailed forecast."

    # Format the periods into a readable forecast
    periods = forecast_data["properties"]["periods"]
    forecasts = []
    for period in periods[:5]:  # Only show next 5 periods
        forecast = f"""
{period['name']}:
Temperature: {period['temperature']}°{period['temperatureUnit']}
Wind: {period['windSpeed']} {period['windDirection']}
Forecast: {period['detailedForecast']}
"""
        forecasts.append(forecast)

    return "\n---\n".join(forecasts)

CACHE_DIR = Path.home() / ".cache" / "weather"
LOCATION_CACHE_FILE = CACHE_DIR / "location_cache.json"

def get_cached_location_key(location: str) -> Optional[str]:
    """Get location key from cache."""
    if not LOCATION_CACHE_FILE.exists():
        return None
    
    try:
        with open(LOCATION_CACHE_FILE, "r") as f:
            cache = json.load(f)
            return cache.get(location)
    except (json.JSONDecodeError, FileNotFoundError):
        return None

def cache_location_key(location: str, location_key: str):
    """Cache location key for future use."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        if LOCATION_CACHE_FILE.exists():
            with open(LOCATION_CACHE_FILE, "r") as f:
                cache = json.load(f)
        else:
            cache = {}
        
        cache[location] = location_key
        
        with open(LOCATION_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to cache location key: {e}")

@mcp.tool()
async def get_hourly_weather(location: str) -> Dict:
    """Get hourly weather forecast for a location."""
    api_key = os.getenv("ACCUWEATHER_API_KEY")
    base_url = "http://dataservice.accuweather.com"
    
    # Try to get location key from cache first
    location_key = get_cached_location_key(location)
    
    async with ClientSession() as session:
        if not location_key:
            location_search_url = f"{base_url}/locations/v1/cities/search"
            params = {
                "apikey": api_key,
                "q": location,
            }
            async with session.get(location_search_url, params=params) as response:
                locations = await response.json()
                if response.status != 200:
                    raise Exception(f"Error fetching location data: {response.status}, {locations}")
                if not locations or len(locations) == 0:
                    raise Exception("Location not found")
            
            location_key = locations[0]["Key"]
            # Cache the location key for future use
            cache_location_key(location, location_key)
        
        # Get current conditions
        current_conditions_url = f"{base_url}/currentconditions/v1/{location_key}"
        params = {
            "apikey": api_key,
        }
        async with session.get(current_conditions_url, params=params) as response:
            current_conditions = await response.json()
            
        # Get hourly forecast
        forecast_url = f"{base_url}/forecasts/v1/hourly/12hour/{location_key}"
        params = {
            "apikey": api_key,
            "metric": "true",
        }
        async with session.get(forecast_url, params=params) as response:
            forecast = await response.json()
        
        # Format response
        hourly_data = []
        for i, hour in enumerate(forecast, 1):
            hourly_data.append({
                "relative_time": f"+{i} hour{'s' if i > 1 else ''}",
                "temperature": {
                    "value": hour["Temperature"]["Value"],
                    "unit": hour["Temperature"]["Unit"]
                },
                "weather_text": hour["IconPhrase"],
                "precipitation_probability": hour["PrecipitationProbability"],
                "precipitation_type": hour.get("PrecipitationType"),
                "precipitation_intensity": hour.get("PrecipitationIntensity"),
            })
        
        # Format current conditions
        if current_conditions and len(current_conditions) > 0:
            current = current_conditions[0]
            current_data = {
                "temperature": {
                    "value": current["Temperature"]["Metric"]["Value"],
                    "unit": current["Temperature"]["Metric"]["Unit"]
                },
                "weather_text": current["WeatherText"],
                "relative_humidity": current.get("RelativeHumidity"),
                "precipitation": current.get("HasPrecipitation", False),
                "observation_time": current["LocalObservationDateTime"]
            }
        else:
            current_data = "No current conditions available"
        
        return {
            "location": locations[0]["LocalizedName"],
            "location_key": location_key,
            "country": locations[0]["Country"]["LocalizedName"],
            "current_conditions": current_data,
            "hourly_forecast": hourly_data
        } 


if __name__ == "__main__":
    # Initialize and run the server
    mcp.run(transport='stdio')



