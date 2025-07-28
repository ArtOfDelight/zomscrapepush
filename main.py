from playwright.sync_api import sync_playwright
import gspread
import re
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

SHEET_NAME = "Swiggy Zomato Dashboard"
WORKSHEET_NAME = "Zomato Order Data"

# ✅ Use env var for service account
def init_sheet():
    creds_json = os.getenv("GOOGLE_SERVICE_JSON")
    if not creds_json:
        raise Exception("Missing GOOGLE_SERVICE_JSON env variable")
    creds_dict = json.loads(creds_json)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
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
        outlet_id, data['history'], data['rating'], data['comment'], data['order_id'],
        data['datetime'], data['timeline'].get("Delivery Duration", ""),
        data['timeline'].get("Placed", ""), data['timeline'].get("Accepted", ""),
        data['timeline'].get("Ready", ""), data['timeline'].get("Delivery partner arrived", ""),
        data['timeline'].get("Picked up", ""), data['timeline'].get("Delivered", ""),
        " | ".join(formatted_items), data['distance']
    ]
    print("\n📤 Pushing row to sheet:", row)
    ws.append_row(row)

def extract_fields(text: str) -> dict:
    lines = text.strip().splitlines()
    output = {
        "history": "", "rating": "", "comment": "", "order_id": "", "datetime": "",
        "timeline": {}, "items": [], "distance": ""
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
            if i + 1 < len(lines): output["order_id"] = lines[i + 1].strip()
            if i + 2 < len(lines): output["datetime"] = lines[i + 2].strip()
        if "Delivered in" in line:
            output["timeline"]["Delivery Duration"] = line
        keys = ["Placed", "Accepted", "Ready", "Delivery partner arrived", "Picked up", "Delivered"]
        if line in keys and i + 1 < len(lines):
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
        if inside_items_section and line.strip():
            item_lines.append(line.strip())
        if not output["distance"] and "away" in line:
            output["distance"] = line
        i += 1
    return output

def run():
    IDs = ["20647827", "19501520", "20996205", "19418061", "19595967", "57750",
           "19501520", "20547934", "2113481", "20183353", "19595894", "18422924"]
    URL = "https://www.zomato.com/partners/onlineordering/reviews/"
    worksheet = init_sheet()
    existing_ids = get_existing_order_ids(worksheet)

    # ✅ Playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(storage_state=json.loads(os.getenv("ZOMATO_SESSION_JSON")))
        page = context.new_page()
        page.goto(URL)

        for index, outlet_id in enumerate(IDs):
            try:
                if index == 0:
                    search_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[3]/div[2]/div/div/div[1]/div[3]/div/div/div/div/div/div/div/input"
                    page.wait_for_selector(f"xpath={search_xpath}", timeout=10000)
                    page.locator(f"xpath={search_xpath}").fill(outlet_id)
                    page.wait_for_timeout(3000)
                    page.locator("text=Art Of Delight").first.click()
                else:
                    outlet_switch_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div[2]/div[3]/div/div/div[3]/img"
                    page.locator(f"xpath={outlet_switch_xpath}").click(force=True)
                    input_xpath = "/html/body/div[1]/div/div[2]/div/div/div/div/div[2]/div/div[2]/div[2]/div/div[2]/div/div[1]/div[2]/div[3]/div[2]/div[1]/div/div/div/div/div/div/div/input"
                    page.wait_for_selector(f"xpath={input_xpath}", timeout=10000)
                    page.locator(f"xpath={input_xpath}").fill(outlet_id)
                    page.wait_for_timeout(3000)
                    page.locator(f"text=ID: {outlet_id}").first.click()

                page.wait_for_timeout(3000)
                review_buttons = page.locator("text=View Review Details")
                count = min(review_buttons.count(), 10)

                for i in range(count):
                    review_buttons.nth(i).click()
                    page.wait_for_timeout(1000)
                    try:
                        page.locator("text=Order Details").first.click()
                        page.wait_for_timeout(1500)
                    except:
                        pass
                    try:
                        modal_section = page.locator("div:has-text('ORDER TIMELINE')").first
                        full_modal_text = modal_section.inner_text()
                        extracted = extract_fields(full_modal_text)
                        order_id = extracted['order_id'].strip()
                        if order_id not in existing_ids:
                            push_to_sheet(worksheet, outlet_id, extracted)
                            existing_ids.add(order_id)
                    except Exception as e:
                        print("❌ Extraction error:", e)
                    try:
                        page.locator("text=Close").first.click()
                    except:
                        pass
                    page.wait_for_timeout(1000)

            except Exception as e:
                print(f"❌ Failed for ID {outlet_id}:", e)

        browser.close()

if __name__ == "__main__":
    run()
