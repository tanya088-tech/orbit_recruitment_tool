"""WHERE the collector searches (the "seed" locations).

LinkedIn can only be asked about a place by name, so a run needs a list of places to ask about.
This list is that list - nothing else. It is NOT what the dashboard shows: the dashboard builds
its Location Scope (Within India / Outside India / All Locations) from the location text of the
jobs that were actually collected, so a city that turns up in the data is handled without editing
anything here.

Edit freely: add a city, remove one, or add a country. Names should be written the way LinkedIn
writes them ("City, State, India" or just a country name).
"""
from __future__ import annotations

# "India" alone asks LinkedIn for India-wide results, in addition to the individual cities.
INDIA_SEARCH_LOCATIONS: list[str] = [
    "India",
    "Bengaluru, Karnataka, India", "Hyderabad, Telangana, India", "Pune, Maharashtra, India",
    "Mumbai, Maharashtra, India", "Delhi, India", "Gurugram, Haryana, India", "Noida, Uttar Pradesh, India",
    "Chennai, Tamil Nadu, India", "Kolkata, West Bengal, India", "Ahmedabad, Gujarat, India",
    "Jaipur, Rajasthan, India", "Kochi, Kerala, India", "Thiruvananthapuram, Kerala, India",
    "Coimbatore, Tamil Nadu, India", "Chandigarh, India", "Indore, Madhya Pradesh, India",
    "Bhopal, Madhya Pradesh, India", "Lucknow, Uttar Pradesh, India", "Nagpur, Maharashtra, India",
    "Surat, Gujarat, India", "Vadodara, Gujarat, India", "Bhubaneswar, Odisha, India",
    "Visakhapatnam, Andhra Pradesh, India", "Vijayawada, Andhra Pradesh, India", "Mysuru, Karnataka, India",
    "Mangaluru, Karnataka, India", "Nashik, Maharashtra, India", "Patna, Bihar, India", "Ranchi, Jharkhand, India",
    "Raipur, Chhattisgarh, India", "Dehradun, Uttarakhand, India", "Guwahati, Assam, India", "Goa, India",
    "Faridabad, Haryana, India", "Ghaziabad, Uttar Pradesh, India", "Kanpur, Uttar Pradesh, India",
    "Madurai, Tamil Nadu, India",
]

INTERNATIONAL_SEARCH_LOCATIONS: list[str] = [
    "United Arab Emirates", "Singapore", "United Kingdom", "Ireland", "Germany", "Netherlands",
    "United States", "Canada", "Australia", "Qatar", "Saudi Arabia", "Hong Kong", "Malaysia", "Japan",
]

SCOPES = {
    "india": "India only",
    "both": "India and international",
    "international": "International only",
}


def search_locations(scope: str) -> list[str]:
    if scope == "india":
        return list(INDIA_SEARCH_LOCATIONS)
    if scope == "international":
        return list(INTERNATIONAL_SEARCH_LOCATIONS)
    if scope == "both":
        return list(INDIA_SEARCH_LOCATIONS) + list(INTERNATIONAL_SEARCH_LOCATIONS)
    raise ValueError(f"unknown collection scope: {scope!r}")
