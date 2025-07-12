# base_browser_config.py
# Shared browser settings for all browser-use scrapers

browser_settings = {
    "headless": False,
    "viewport": {"width": 1280, "height": 720},
    "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "locale": "en-US",
    "timezoneId": "America/New_York",
    "geolocation": {"latitude": 40.7128, "longitude": -74.0060},
    "permissions": ["geolocation"],
    "bypassCSP": True
} 