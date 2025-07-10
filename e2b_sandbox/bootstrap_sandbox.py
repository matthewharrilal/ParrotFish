"""
Bootstrap script to prep an E2B sandbox for browser-use agent execution.
Run this as the first step inside the sandbox to install dependencies, set up browser binaries, and verify config.
"""

import os
import subprocess
import sys

REQUIRED_ENV_VARS = ["OPENAI_API_KEY", "E2B_API_KEY"]

# Ensure Python 3.11+
if sys.version_info < (3, 11):
    raise EnvironmentError("Python 3.11 or higher is required in the sandbox.")

def verify_env_vars():
    missing = [var for var in REQUIRED_ENV_VARS if os.getenv(var) is None]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")
    print("✅ Environment variables loaded.")

def install_python_packages():
    packages = [
        "browser-use",
        "playwright",
        "python-dotenv",
        "openai",
        "e2b-code-interpreter"
        # Add any extras here if your scrapers use Anthropic, LangChain, etc.
    ]
    print("📦 Installing Python packages...")
    subprocess.run([sys.executable, "-m", "pip", "install", *packages], check=True)
    print("✅ Python packages installed.")

def install_playwright_browsers():
    print("🌐 Installing Playwright browser binaries (Chromium)...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    print("✅ Chromium installed and ready.")

def verify_browser_use():
    print("🔍 Verifying browser-use installation...")
    import browser_use
    from browser_use import BrowserSession, Agent
    print("✅ browser-use imports succeeded.")

def main():
    print("🚀 Starting sandbox bootstrap...")
    verify_env_vars()
    install_python_packages()
    install_playwright_browsers()
    verify_browser_use()
    print("🎉 Sandbox bootstrap completed successfully.")

if __name__ == "__main__":
    main() 