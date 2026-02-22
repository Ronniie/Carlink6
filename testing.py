import base64
import requests

API_KEY = ""
ACCOUNT_ID = 0

token = base64.b64encode(f"@apikey:{API_KEY}".encode()).decode()

headers = {
    "Authorization": f"Basic {token}",
    "Accept": "application/json",
    "User-Agent": "okhttp/4.9.0",
    "Content-Type": "application/json"
}

url = f"https://api.m2msuite.com/v1.1/109.3/{ACCOUNT_ID}/Assets"

r = requests.get(url, headers=headers)

print(r.status_code)
print(r.text)