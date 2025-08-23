import os
from dotenv import load_dotenv

print("Before load_dotenv():")
print(f"SPCLIENT_ID: {os.getenv('SPCLIENT_ID', 'NOT FOUND')}")
print(f"SPCLIENT_SECRET: {os.getenv('SPCLIENT_SECRET', 'NOT FOUND')}")

load_dotenv()

print("\nAfter load_dotenv():")
print(f"SPCLIENT_ID: {os.getenv('SPCLIENT_ID', 'NOT FOUND')}")
print(f"SPCLIENT_SECRET: {os.getenv('SPCLIENT_SECRET', 'NOT FOUND')}")

print("\nAll environment variables containing 'CLIENT':")
for key, value in os.environ.items():
    if 'CLIENT' in key:
        print(f"{key}: {value}")
