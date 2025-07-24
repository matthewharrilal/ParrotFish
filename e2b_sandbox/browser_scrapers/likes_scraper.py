import shutil
import os
# from e2b_sandbox.browser_scrapers.base_browser_config import browser_settings
from dotenv import load_dotenv
load_dotenv()

from browser_use.llm import ChatOpenAI
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

llm = ChatOpenAI(model="gpt-4o")

extraction_script = """
(async function() {
  // Helper: sleep for ms milliseconds
  const sleep = ms => new Promise(res => setTimeout(res, ms));

  // Helper: remove null/undefined/empty array fields
  function cleanPost(post) {
    return Object.fromEntries(
      Object.entries(post).filter(
        ([, v]) =>
          v !== null &&
          v !== undefined &&
          !(Array.isArray(v) && v.length === 0)
      )
    );
  }

  // Helper: extract visible liked post data from all articles
  function extractPosts() {
    const articles = document.querySelectorAll('article');
    const posts = [];
    articles.forEach(article => {
      // Author display name and username
      let author = null, username = null;
      // Find all anchor tags that link to a user profile
      const userLinks = Array.from(article.querySelectorAll('a[href^="/"][role="link"]'));
      for (const link of userLinks) {
        const match = link.getAttribute('href').match(/^\/([^\/]+)$/);
        if (match) {
          username = match[1];
          const displaySpan = link.querySelector('span');
          if (displaySpan) {
            author = displaySpan.textContent;
          }
          break;
        }
      }

      // Date/time
      const timeElem = article.querySelector('time');
      const date = timeElem ? timeElem.getAttribute('datetime') : null;

      // Text
      const textElem = article.querySelector('div[data-testid="tweetText"]');
      const text = textElem ? textElem.innerText : '';

      // Permalink
      const linkElem = timeElem ? timeElem.parentElement : null;
      const permalink = linkElem && linkElem.getAttribute('href') ? 'https://x.com' + linkElem.getAttribute('href') : null;

      // Stats
      let likes = null, retweets = null, replies = null, views = null;
      article.querySelectorAll('div[data-testid]').forEach(el => {
        if (el.getAttribute('data-testid') === 'like') likes = el.innerText;
        if (el.getAttribute('data-testid') === 'retweet') retweets = el.innerText;
        if (el.getAttribute('data-testid') === 'reply') replies = el.innerText;
        if (el.getAttribute('data-testid') === 'viewCount') views = el.innerText;
      });

      // Media
      let media = [];
      article.querySelectorAll('img, video').forEach(m => {
        if (m.src && !m.src.includes('profile_images')) media.push(m.src);
      });

      // Quoted tweet (if present)
      let quoted = null;
      const quotedElem = article.querySelector('div[data-testid="tweet"] article');
      if (quotedElem) {
        const quotedTextElem = quotedElem.querySelector('div[data-testid="tweetText"]');
        quoted = quotedTextElem ? quotedTextElem.innerText : null;
      }

      // Clean and push only non-null fields
      posts.push(cleanPost({
        author,
        username,
        date,
        text,
        permalink,
        likes,
        retweets,
        replies,
        views,
        media,
        quoted
      }));
    });
    return posts;
  }

  // Robustly detect Likes page and username
  const urlParts = window.location.pathname.split('/').filter(Boolean);
  const username = urlParts[0] || 'unknown';
  const path = window.location.pathname.toLowerCase();
  if (!path.includes('likes')) {
    alert('This script is intended for the Likes page only.');
    return;
  }
  const pageType = 'likes';

  // Get today's date in YYYY-MM-DD
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, '0');
  const dd = String(today.getDate()).padStart(2, '0');
  const dateStr = `${yyyy}-${mm}-${dd}`;

  // Main: scroll and extract
  let lastHeight = 0, sameCount = 0, maxNoChange = 15;
  let allPosts = new Map();

  while (sameCount < maxNoChange) {
    // Extract posts
    extractPosts().forEach(post => {
      if (post.permalink && !allPosts.has(post.permalink)) {
        allPosts.set(post.permalink, post);
      }
    });

    // Scroll
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(3500); // Wait longer for more content to load

    // Check for new content
    let newHeight = document.body.scrollHeight;
    if (newHeight === lastHeight) {
      sameCount++;
    } else {
      sameCount = 0;
      lastHeight = newHeight;
    }
  }

  // Output as JSON
  const result = Array.from(allPosts.values());
  console.log("Extracted liked posts:", result);

  // Download as JSON file with dynamic name
  const filename = `${username}_${pageType}_${dateStr}.json`;
  const blob = new Blob([JSON.stringify(result, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
})();
"""

# Build the agent's task prompt
agent_task = f"""
You are an expert browser automation agent. Your mission is to log in to X.com, navigate to the user's Likes tab, and execute a JavaScript extraction script. You must use the following credentials for login:

- Username: {X_USERNAME}
- Password: {X_PASSWORD}

**LOGIN ROBUSTNESS AND STREAMLINING**
- Your first and highest priority is to log in to X.com using the provided credentials.
- Handle all possible login flows, including:
  - Look for the username/email/phone input field with placeholder text like "Phone, email, or username" or "Email or username"
  - Enter the exact username "{X_USERNAME}" into this field
  - Click "Next" or "Continue" to proceed to password entry
  - Look for the password input field with placeholder text like "Password" or type="password"
  - Enter the exact password "{X_PASSWORD}" into this field
  - Multi-step login forms (e.g., username first, then password).
  - 2FA (two-factor authentication) prompts: if prompted, log the need for 2FA and pause for user input or retry as appropriate.
  - Captchas: if a captcha is encountered, log the event and attempt to solve if possible, otherwise log and pause.
  - Any additional verification steps (e.g., email/phone confirmation, security questions).
- Retry login up to 3 times if any step fails, intelligently varying the input method (username/email/phone) and handling errors.
- Only proceed to navigation after you have confirmed a successful login by detecting a unique logged-in element (such as the profile avatar, user menu, or a personalized home page element).
- If login fails after all retries, log a detailed error with the reason and halt further actions.
- Log all login attempts, errors, and the final login status.

**NAVIGATION TO LIKES TAB**
- After successful login, navigate to the user's profile page.
- Click on the "Likes" tab to access the liked posts.
- Confirm you are on the correct page (URL should contain "/likes").
- Wait for the page to fully load before proceeding to script injection.

**MANDATORY: SCRIPT INJECTION AND EXECUTION**
- After reaching the Likes tab, you MUST execute the provided JavaScript extraction script.
- Press F12 to open Developer Tools
- Click on the "Console" tab
- Paste the entire extraction script into the console
- Press Enter to execute it
- The script will handle all scrolling, extraction, and deduplication internally.
- Wait for the script to finish and trigger a file download (JSON).
- Do NOT attempt to extract data manually - only use the provided script.

**SCRIPT CONTENT TO INJECT:**
The following JavaScript code must be pasted into the console:

{extraction_script}

**Error Handling and Recovery**
- On any error (timeout, selector not found, navigation failure, script error), log the error and retry.
- If script injection fails, try different methods to open the console.
- Never give up on script execution - try all possible methods.
- If persistent errors occur, attempt to reload or re-navigate and resume.

**General Principles**
- Be maximally persistent and aggressive about script execution.
- Your mission is to get the extraction script running no matter what.
- Do not stop until the script has been successfully injected and executed.
- Use any means necessary to get the script into the browser console.

**You are to embody all of these principles and strategies in your actions.**
"""

async def main():
    async with BrowserSession(browser_settings=browser_settings) as session:
        agent = Agent(
            task=agent_task,
            llm=llm,
            browser=session
        )
        
        print("Starting agent to handle login, navigation, and script injection...")
        result = await agent.run()
        print("Agent completed. Result:", result)
        
        # Wait for any file downloads to complete
        print("Waiting for extraction to complete...")
        await asyncio.sleep(10)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main()) 