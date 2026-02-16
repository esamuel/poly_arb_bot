import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

def inspect_client():
    # Just need a dummy key for inspection, or we can inspect the class directly
    # But initializing it is safer to see instance methods
    # We'll use a random key for inspection purposes or just dir the class
    print("Inspecting ClobClient methods...")
    print(dir(ClobClient))

if __name__ == "__main__":
    inspect_client()
