import os
import re
import time
import json
import requests
from io import StringIO
from datetime import datetime
from playwright.sync_api import sync_playwright
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# === CONFIG ===
SHEET_NAME = "Swiggy Zomato Dashboard"
WORKSHEET_NAME = "Zomato Order Data"
URL = "https://www.zomato.com/partners/onlineordering/reviews/"

GOOGLE_SERVICE_JSON = os.getenv("GOOGLE_SERVICE_JSON")
ZOMATO_SESSION_JSON = os.getenv("ZOMATO_SESSION_JSON")
APPS_SCRIPT_WEBHOOK_URL = os.getenv("https://script.google.com/macros/s/AKfycbzTjzoc5kxaPpDVpXWQ9VSg7I-XSM0VaoAMHcByZh37VIWxoZQQH8Lpctacg-3WuTyP/exec")  # ✅ Add this to your environment

# === SHEET SETUP ===
def init_sheet():
    print("🔧 Initializing Google Sheet...")
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = json.loads(GOOGLE_SERVICE_JSON)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME)
    try:
        worksheet = sheet.worksheet(WORKSHEET_NAME)
        print(f"✅ Found existing worksheet: '{WORKSHEET_NAME}'")
    except:
        print(f"📄 Worksheet '{WORKSHEET_NAME}' not found. Creating new one...")
        worksheet = sheet.add_worksheet(title=WORKSHEET_NAME, rows="1000", cols="20")
        worksheet.append_row([
            "Outlet ID", "Order History", "Customer Rating", "Comment", "Order ID", "Date & Time",
            "Delivery Duration", "Placed", "Accepted", "Ready", "Delivery partner arrived",
            "Picked up", "Delivered", "Items Ordered", "Customer Distance"
        ])
        print("✅ Worksheet created and headers set.")
    return worksheet

# === DATA EXTRACTION ===
def extract_review_data(text):
    outlet_match = re.search(r"Outlet: (.+)", text)
    outlet_id = outlet_match.group(1).strip() if outlet_match else ""

    rating_match = re.search(r"Customer Rating:\s+([0-5](\.\d)?)", text)
    rating = rating_match.group(1).strip() if rating_match else ""

    comment_match = re.search(r"Customer Comment:(.*?)Order ID:", text, re.DOTALL)
    comment = comment_match.group(1).strip() if comment_match else ""

    order_id_match = re.search(r"Order ID:\s*#?(\d+-\d+)", text)
    order_id = order_id_match.group(1).strip() if order_id_match else ""

    datetime_match = re.search(r"Order Time:\s+(.*)", text)
    date_time = datetime_match.group(1).strip() if datetime_match else ""

    duration_match = re.search(r"Delivery Duration:\s+(.*)", text)
    delivery_duration = duration_match.group(1).strip() if duration_match else ""

    timeline_match = re.findall(r"(Placed|Accepted|Ready|Delivery partner arrived|Picked up|Delivered):\s+([0-9:apm\s]+)", text)
    timeline_dict = {event: time for event, time in timeline_match}

    items_match = re.search(r"Items Ordered:\s+(.*)", text)
    items = items_match.group(1).strip() if items_match else ""

    distance_match = re.search(r"Customer Distance:\s+([\d.]+\s+\w+)", text)
    distance = distance_match.group(1).strip() if distance_match else ""

    return [
        outlet_id,
        "→".join(f"{k}:{v}" for k, v in timeline_dict.items()),
        rating,
        comment,
        order_id,
        date_time,
        delivery_duration,
        timeline_dict.get("Placed", ""),
        timeline_dict.get("Accepted", ""),
        timeline_dict.get("Ready", ""),
        timeline_dict.get("Delivery partner arrived", ""),
        timeline_dict.get("Picked up", ""),
        timeline_dict.get("Delivered", ""),
        items,
        distance
    ]

# === NOTIFY GOOGLE APPS SCRIPT ===
def notify_apps_script(order_id, date_time, outlet_id):
    if not APPS_SCRIPT_WEBHOOK_URL:
        print("⚠️ APPS_SCRIPT_WEBHOOK_URL not set. Skipping webhook.")
        return

    try:
        payload = {
            "platform": "zomato",
            "order_id": order_id,
            "timestamp": date_time,
            "outlet": outlet_id
        }
        res = requests.post(APPS_SCRIPT_WEBHOOK_URL, json=payload)
        if res.status_code == 200:
            print(f"📡 Webhook success: Matched with employees.")
        else:
            print(f"⚠️ Webhook failed: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Webhook error: {e}")

# === MAIN SCRIPT ===
def run():
    print("🚀 Starting Zomato review extraction...")
    worksheet = init_sheet()

    print("📥 Fetching existing Order IDs from sheet...")
    existing_order_ids = set(row[4] for row in worksheet.get_all_values()[1:] if row[4])
    print(f"📄 {len(existing_order_ids)} existing Order IDs loaded.")

    with sync_playwright() as p:
        print("🧭 Launching headless browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=json.loads(ZOMATO_SESSION_JSON))
        page = context.new_page()

        print(f"🌐 Navigating to: {URL}")
        page.goto(URL, wait_until="load")
        time.sleep(5)

        reviews = page.query_selector_all(".sc-cEvuZC.hNljIm")
        print(f"🔍 Found {len(reviews)} reviews on page.")

        for idx, review in enumerate(reviews):
            print(f"\n➡️ Processing review #{idx+1}...")
            review.click()
            time.sleep(3)
            page.wait_for_timeout(1000)

            try:
                text = page.inner_text(".sc-bkzZxe.bQUpTy")
                data = extract_review_data(text)
                order_id = data[4]
                date_time = data[5]
                outlet_id = data[0]

                if not order_id:
                    print("⚠️ No Order ID found. Skipping this review.")
                    continue

                if order_id not in existing_order_ids:
                    worksheet.append_row(data)
                    print(f"✅ Added new Order ID: {order_id}")
                    notify_apps_script(order_id, date_time, outlet_id)
                else:
                    print(f"⏭️ Skipped duplicate Order ID: {order_id}")

            except Exception as e:
                print(f"❌ Error while processing review #{idx+1}: {e}")

        browser.close()
        print("🏁 Script completed and browser closed.")

# === ENTRY POINT ===
if __name__ == "__main__":
    run()
