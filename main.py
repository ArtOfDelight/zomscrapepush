from playwright.sync_api import sync_playwright
import gspread
import re
import os
import json
import requests
from oauth2client.service_account import ServiceAccountCredentials

SHEET_NAME = "Swiggy Zomato Dashboard"
WORKSHEET_NAME = "Zomato Order Data"
APPS_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbyHt37GPrtXQ64aYwNCz5huxX0wKHCysB4T1xf5M6Jfdl8DqEXQU3CvcAtVgJMqNwWtmQ/exec"  # Replace this with actual URL

def init_sheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_json = os.getenv("GOOGLE_SERVICE_JSON")
    if not creds_json:
        raise Exception("Missing GOOGLE_SERVICE_JSON environment variable")
    creds_dict = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME)
    try:
        worksheet = sheet.worksheet(WORKSHEET_NAME)
    except:
        worksheet = sheet.add_worksheet(title=WORKSHEET_NAME, rows="1000", cols="20")
        worksheet.append_row([
            "Outlet ID", "Order History", "Customer Rating", "Comment", "Order ID", "Date & Time",
            "Delivery Duration", "Placed", "Accepted", "Ready", "Delivery partner arrived",
            "Picked up", "Delivered", "Items Ordered", "Customer Distance"
        ])
    return worksheet

def get_existing_order_ids(worksheet):
    order_ids = worksheet.col_values(5)
    return set(order_ids[1:])

def push_to_sheet(ws, outlet_id, data):
    formatted_items = []
    for item in data['items']:
        formatted = re.sub(r'(\b\d+ x)', r'\n\1', item).strip()
        formatted_items.append(formatted)

    row = [
        outlet_id,
        data['history'],
        data['rating'],
        data['comment'],
        data['order_id'],
        data['datetime'],
        data['timeline'].get("Delivery Duration", ""),
        data['timeline'].get("Placed", ""),
        data['timeline'].get("Accepted", ""),
        data['timeline'].get("Ready", ""),
        data['timeline'].get("Delivery partner arrived", ""),
        data['timeline'].get("Picked up", ""),
        data['timeline'].get("Delivered", ""),
        " | ".join(formatted_items),
        data['distance']
    ]
    print("\n\n📤 Pushing row to sheet:", row)
    ws.append_row(row)

def extract_fields(text: str) -> dict:
    lines = text.strip().splitlines()
    output = {
        "history": "",
        "rating": "",
        "comment": "",
        "order_id": "",
        "datetime": "",
        "timeline": {},
        "items": [],
        "distance": ""
    }

    i = 0
    inside_items_section = False
    item_lines = []

    while i < len(lines):
        line = lines[i].strip()

        if not output["history"] and "order with you" in line:
            output["history"] = line

        if not output["rating"] and line.lower() == "customer rating" and i + 1 < len(lines):
            output["rating"] = lines[i + 1].strip()

        if not output["comment"]:
            quote_match = re.search(r'"([^"]+)"', line)
            if quote_match:
                output["comment"] = quote_match.group(1)

        if line == "ID:":
            if i + 1 < len(lines):
                output["order_id"] = lines[i + 1].strip()
            if i + 2 < len(lines):
                output["datetime"] = lines[i + 2].strip()

        if "Delivered in" in line:
            output["timeline"]["Delivery Duration"] = line

        timeline_keys = ["Placed", "Accepted", "Ready", "Delivery partner arrived", "Picked up", "Delivered"]
        if line in timeline_keys and i + 1 < len(lines):
            output["timeline"][line] = lines[i + 1].strip()

        if line in ["ORDER", "Order Details"]:
            inside_items_section = True
            item_lines = []
            i += 1
            continue

        if inside_items_section and "Restaurant Packaging Charges" in line:
            inside_items_section = False
            if item_lines:
                output["items"].append(" | ".join(item_lines))

        if inside_items_section:
            if line.strip():
                item_lines.append(line.strip())

        if not output["distance"] and "away" in line:
            output["distance"] = line

        i += 1

    return output

def trigger_apps_script():
    try:
        response = requests.get(APPS_SCRIPT_URL)
        response.raise_for_status()
        try:
            gas_response = response.json()
            if gas_response.get('success'):
                print(f"✅ Apps Script triggered: {gas_response.get('message')}")
            else:
                print(f"❌ Apps Script error: {gas_response.get('error')}")
        except json.JSONDecodeError:
            print(f"❌ Apps Script response is not valid JSON: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error triggering Apps Script: {e}")

def run():
    IDs = ["20647827", "19501520", "20996205", "19418061", "19595967", "57750", "19501520", "20547934", "2113481", "20183353", "19595894", "18422924"]
    URL = "https://www.zomato.com/partners/onlineordering/reviews/"
    worksheet = init_sheet()
    existing_ids = get_existing_order_ids(worksheet)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        session_json = os.getenv("ZOMATO_SESSION_JSON")
        if not session_json:
            raise Exception("Missing ZOMATO_SESSION_JSON environment variable")
        context = browser.new_context(storage_state=json.loads(session_json))
        page = context.new_page()
        page.goto(URL)

        for index, outlet_id in enumerate(IDs):
            try:
                print(f"🔄 Processing Outlet ID: {outlet_id}")
                if index == 0:
                    search_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[1]/div[3]/div/div/div/div/div/div/div/input"
                    page.wait_for_selector(f"xpath={search_xpath}", timeout=10000)
                    page.locator(f"xpath={search_xpath}").fill(outlet_id)
                    page.wait_for_timeout(3000)
                    page.wait_for_selector("text=Art Of Delight", timeout=10000)
                    page.locator("text=Art Of Delight").first.click()
                else:
                    outlet_switch_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div[2]/div[3]/div/div/div[3]/img"
                    page.locator(f"xpath={outlet_switch_xpath}").click()
                    input_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div[2]/div[3]/div[2]/div[1]/div/div/div/div/div/div/div/input"
                    page.wait_for_selector(f"xpath={input_xpath}", timeout=10000)
                    page.locator(f"xpath={input_xpath}").fill(outlet_id)
                    page.wait_for_timeout(3000)
                    page.locator(f"text=ID: {outlet_id}").first.click()

                page.wait_for_timeout(3000)
                review_buttons = page.locator("text=View Review Details")
                count = min(review_buttons.count(), 10)
                print(f"🔍 Found {count} review(s).")

                for i in range(count):
                    print(f"\n🔄 Opening review #{i + 1}...")
                    review_buttons.nth(i).click()
                    page.wait_for_timeout(1000)

                    try:
                        page.locator("text=Order Details").first.click()
                        page.wait_for_timeout(1500)
                    except:
                        print("⚠️ 'Order Details' not found.")

                    try:
                        modal_section = page.locator("div:has-text('ORDER TIMELINE')").first
                        full_modal_text = modal_section.inner_text()
                        extracted = extract_fields(full_modal_text)
                        order_id = extracted['order_id'].strip()

                        if order_id in existing_ids:
                            print(f"⏭️ Skipping duplicate Order ID: {order_id}")
                        else:
                            push_to_sheet(worksheet, outlet_id, extracted)
                            existing_ids.add(order_id)
                            print(f"✅ Added Order ID: {order_id}")

                    except Exception as e:
                        print("❌ Could not extract modal section:", e)

                    try:
                        page.locator("text=Close").first.click()
                    except:
                        pass
                    page.wait_for_timeout(1000)

            except Exception as e:
                print(f"❌ Script failed for ID {outlet_id}:", e)

        browser.close()
        trigger_apps_script()

if __name__ == "__main__":
    run()
