from dotenv import load_dotenv
load_dotenv()

from browser_use.llm import ChatOpenAI
from browser_use import Agent, BrowserSession
import asyncio

# Optional: Custom browser configuration
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

llm = ChatOpenAI(model="gpt-4o")

async def main():
    async with BrowserSession(browser_settings=browser_settings) as session:
        agent = Agent(
            task="Go to https://airbnb.com and return the main heading.",
            llm=llm,
            browser=session
        )
        result = await agent.run()
        print("Agent result:", result)

if __name__ == "__main__":
    asyncio.run(main()) 