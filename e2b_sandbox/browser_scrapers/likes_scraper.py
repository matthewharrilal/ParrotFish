import shutil
import os
# from e2b_sandbox.browser_scrapers.base_browser_config import browser_settings
from dotenv import load_dotenv
load_dotenv()

from browser_use.llm import ChatOllama
from browser_use import Agent, BrowserSession
import asyncio
import time

# Ensure a clean browser-use profile for every run
profile_path = os.path.expanduser("~/.config/browseruse/profiles/default")
if os.path.exists(profile_path):
    shutil.rmtree(profile_path)

# Extract credentials from environment variables
X_USERNAME = os.getenv("X_USERNAME")
X_PASSWORD = os.getenv("X_PASSWORD")
TARGET_HANDLE = os.getenv("TARGET_HANDLE", X_USERNAME)  # Default to self if not set

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

# Build the agent's task prompt
agent_task = f"""
You are an expert browser automation agent. Your mission is to extract every single liked post from the user's X.com (Twitter) Likes tab, no matter how many there are, with maximal persistence, speed, and completeness. You must use the following credentials for login:

- Username: {X_USERNAME}
- Password: {X_PASSWORD}

You must handle all possible login flows, including multi-step, phone/email confirmation, 2FA, and captchas. Always use these credentials and retry login up to 2 times if needed. Never proceed until you have confirmed a successful login (e.g., by detecting the profile avatar or a unique logged-in element).

**MANDATORY: AGGRESSIVE, EXHAUSTIVE, AND UNSTOPPABLE EXTRACTION**

1. **Persistence and Error Immunity**
- Never stop for any banner, warning, or non-blocking error (e.g., "Your likes are private", "JavaScript required", missing media, rate limits, or any informational message).
- If a single tweet cannot be read, is missing fields, or throws an error, SKIP IT and continue. Do not let a single extraction failure halt or slow the process. Log the error and move on immediately.
- If a scroll or extraction step fails, retry up to 2 times, then continue. Never let a single failed action stop the overall process.
- If the page displays a static or error state (e.g., JavaScript disabled), attempt to reload or re-navigate and resume extraction.

2. **Aggressive, Efficient Scrolling**
- After each extraction, scroll down by a large amount (2–3 pages, or 1200–1800 pixels) to load as many new posts as possible per scroll.
- Wait only as long as needed for new posts to appear (detect DOM changes or new <article> elements). Do not use arbitrary timeouts.
- If no new posts appear after a scroll, retry up to 2 times, then continue.
- Only stop if, after 3 consecutive large scrolls, no new posts are found and the DOM contains no new post containers.

3. **Batch Extraction and Deduplication**
- After each scroll, extract all visible posts in a single batch, not one at a time.
- Maintain a running set of unique post IDs or a hash of (author+handle+time+snippet). Before extracting, check if a post is already in your set; if so, skip it and do not infer on it again.
- Output all extracted posts as a single deduplicated JSON array.

4. **Robust Selectors and Fallbacks**
- Use robust, attribute-based selectors (e.g., <div role='article'>, <article>, data-testid, aria-label, etc.) to find post containers and fields (author, handle, time, snippet).
- If a selector fails, try alternatives and log all attempts. If the DOM structure changes, adapt and log the new structure.
- Always prefer semantic selectors and visible text over index-based selectors.

5. **Data Completeness and Field Preference**
- For each post, always expand or click any “show more” or similar button to reveal the full caption/text before extraction.
- Extract the post URL for each liked post.
- For the post text, always prefer the most complete field available, in this order: full_caption, caption, full_text, text, or fallback to snippet. If multiple are present, use the most complete one.

6. **Speed and Efficiency**
- Minimize delays between actions. Do not wait for unnecessary animations or timeouts.
- Extract all visible posts in a batch after each scroll, and only run extraction if the DOM has changed or new posts are visible.
- If the page is slow to load, retry scrolling or extraction up to 2 times, then continue.

7. **Stopping Condition**
- Only stop if, after 3 consecutive large scrolls, no new posts are found and the DOM contains no new post containers.
- Your goal is to reach and extract ALL likes, including the very first (oldest) like. Scroll aggressively, extract in batches, and never stop for non-blocking issues.

8. **Logging and Output**
- Log only actionable events to the console: extraction success/failure, browser closure with reason, and any critical warnings or errors. Avoid noisy or verbose logs in the console.
- Output all extracted posts as a single deduplicated JSON array with fields: author, handle, time, the most complete text field (see above), and post URL.
- At the end, output a summary of total posts extracted, skipped, and any critical issues encountered.
- Save a detailed log file with all steps, selectors, errors, and summary statistics, but keep console output minimal.

9. **Error Handling and Recovery**
- On any error (timeout, selector not found, navigation failure), log the error, save a screenshot and HTML if possible, and continue.
- If persistent errors occur, attempt to reload or re-navigate and resume extraction.
- Never let a single error, missing field, or failed extraction stop or slow the overall process.
- Log browser closure reasons and handle infrastructure timeouts gracefully.

10. **Session & Output Management**
- Before each run, clear the output directory where extracted posts are stored.
- Aggregate all extracted posts into a single JSON file at the end of the run.
- Ensure all outputs are stored in a git-ignored directory.

11. **General Principles**
- Be maximally persistent, aggressive, and exhaustive. Only stop when you are certain there are no more posts to extract.
- Never stop for a single tweet, error, or warning. Always continue, retry, and recover.
- Your mission is to extract every possible liked post, as quickly and completely as possible, regardless of minor issues.

**You are to embody all of these principles and strategies in your actions.**
"""

llm = ChatOllama(model="mistral:7b-instruct")

async def main():
    async with BrowserSession(browser_settings=browser_settings) as session:
        agent = Agent(
            task=agent_task,
            llm=llm,
            browser=session
        )
        result = await agent.run()
        print("Agent result joe rogan:", result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 