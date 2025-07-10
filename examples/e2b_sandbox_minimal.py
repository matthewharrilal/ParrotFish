from dotenv import load_dotenv
load_dotenv()
import os
from e2b_code_interpreter import Sandbox

# Ensure E2B_API_KEY is set in the environment
api_key = os.environ.get("E2B_API_KEY")
if not api_key:
    raise RuntimeError("E2B_API_KEY not set in environment. Please add it to your .env file.")

print("E2B_API_KEY loaded:", repr(os.environ.get("E2B_API_KEY")))

print("Launching E2B sandbox...")
with Sandbox() as sandbox:
    print("Running code: x = 1; x += 1; x")
    sandbox.run_code("x = 1")
    execution = sandbox.run_code("x += 1; x")
    print("Sandbox output:", execution.text)  # should output 2
print("Sandbox closed successfully.") 