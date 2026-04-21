import requests
from datetime import datetime
import pytz

# Define the API URL and default values
API_URL = "http://ip-api.com/json"
default_coords = "37.2400, 25.1603"
default_zone = 'EET'
default_tz = "+2"  # Default timezone offset as string

def get_ip_data():
    # Temporary bypass
    return default_coords, default_zone, default_tz

    try:
        response = requests.get(API_URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            coords = f"{data.get('lat')}, {data.get('lon')}"
            zone = data.get('countryCode', default_zone)
            tz_name = data.get('timezone') or country_to_timezone.get(zone)

            if tz_name:
                tz_offset = calculate_utc_offset(tz_name)
            else:
                tz_offset = default_tz

            return coords, tz_name, tz_offset
        else:
            print(f"API request failed with status: {response.status_code}")
    except requests.RequestException as e:
        print(f"Error querying IP API: {e}")

    # Fallback to defaults if any issue occurs
    return default_coords, default_zone, default_tz

def calculate_utc_offset(tz_name):
    """Calculate the UTC offset of the given timezone."""
    try:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        offset_seconds = now.utcoffset().total_seconds()
        offset_hours = int(offset_seconds / 3600)  # Convert seconds to hours
        return f"{offset_hours:+d}"  # Format as +X or -X
    except Exception as e:
        print(f"Error calculating offset: {e}")
        return default_tz  # Return default in case of error

# Usage
#coords, zone, tz_offset = get_ip_data()
#print(f"Coordinates: {coords}")
#print(f"Zone: {zone}")
#print(f"UTC Offset: {tz_offset}")
