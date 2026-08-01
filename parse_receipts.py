import os
import json
import email
from email import policy
import sys
import shutil
import PyPDF2

# Import shared functions from scheduler.py
from scheduler import get_google_api_key, call_gemini, WORKSPACE_DIR

RAW_EMAILS_DIR = os.path.join(WORKSPACE_DIR, "Raw Emails")
PARSED_EMAILS_DIR = os.path.join(RAW_EMAILS_DIR, "parsed")
CLOSET_FILE = os.path.join(WORKSPACE_DIR, "closet.json")

def extract_pdf_text(file_path):
    text = ""
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""
    except Exception as e:
        print(f"Error reading PDF {file_path}: {e}")
    return text

def extract_eml_text(file_path):
    try:
        with open(file_path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        
        # Get body
        body_part = msg.get_body(preferencelist=('plain', 'html'))
        if body_part:
            content = body_part.get_content()
            # Simple HTML tag stripping if it's HTML
            if body_part.get_content_type() == 'text/html':
                import re
                content = re.sub(r'<[^>]+>', ' ', content)
                content = re.sub(r'\s+', ' ', content).strip()
            return f"Subject: {msg['subject']}\nFrom: {msg['from']}\nDate: {msg['date']}\n\n{content}"
    except Exception as e:
        print(f"Error reading EML {file_path}: {e}")
    return ""

def clean_json_response(text):
    text = text.strip()
    # Strip markdown wrapper if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def process_file(file_path, api_key):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        print(f"Extracting PDF: {os.path.basename(file_path)}")
        text = extract_pdf_text(file_path)
    elif ext == ".eml":
        print(f"Extracting EML: {os.path.basename(file_path)}")
        text = extract_eml_text(file_path)
    else:
        print(f"Skipping unsupported file type: {file_path}")
        return []

    if not text.strip():
        print(f"Warning: No text extracted from {file_path}")
        return []

    prompt = f"""You are an expert clothing inventory assistant.
Your task is to parse a raw receipt/order confirmation text and extract all clothing and accessory items that were purchased.

Here is the raw text from the receipt/confirmation:
---
{text[:15000]}
---

Extract each item into a JSON list of objects with the following fields:
- id: a unique, URL-safe, clean string ID. For brand shirts/pants, format it as: 'brandPrefix-skuOrName-sizeW-sizeL' or 'brandPrefix-skuOrName-size' (e.g. 'ct-trc0279tpe-34-32' or 'ct-jep0317wht-L'). Use 'ct' for Charles Tyrwhitt, 'br' for Banana Republic, 'jc' for J.Crew, 'th' for Theory, 'ss' for Suitsupply, 'jab' for Jos. A. Bank, 'bb' for Buckley Belts.
- name: The item name (e.g., 'Ultimate Non-Iron Chinos').
- brand: The brand name (e.g., 'Charles Tyrwhitt').
- color: The color name (e.g., 'Taupe').
- category: One of 'Top', 'Bottom', 'Outerwear', 'Accessories', 'Shoes'.
- sub_category: e.g. 'Chinos', 'Shirt', 'Sweater', 'Pants', 'Polo', 'Belt', 'Jeans'.
- size: The size string (e.g., '34W 32L', 'Large', '16.5 Collar 34 Sleeve').
- quantity: The number of items purchased (default 1).
- warmth: One of 'None', 'Light', 'Light-Medium', 'Medium', 'Medium-High', 'High', 'Extreme'.
- style_tags: A JSON array of string tags describing the style (e.g., ['Slim Fit', 'Ultimate', 'Non-Iron', 'Chino']).
- weather_compatibility: An object with fields:
  - min_temp: Integer (e.g., 50).
  - max_temp: Integer (e.g., 75).
  - conditions: A JSON array of strings (e.g. ['Any'], ['Sunny', 'Warm']).

Special Instructions:
1. If a 3-pack or multi-pack is bought (e.g. 'The Buckley Belt | 3-PACK' containing Black/Cognac/Brown), split it into separate individual items in the output list (e.g. one item for black, one for cognac, one for brown), with different ids like 'buckley-belt-black', 'buckley-belt-cognac', 'buckley-belt-brown'.
2. Respond with ONLY a valid raw JSON array of objects. Do not wrap the JSON in markdown blocks (e.g. do not include ```json ... ```) or any conversational text.
"""

    print("Querying Gemini API for structured extraction...")
    # Use gemini-3.5-flash which is configured by default in scheduler.py
    response_text = call_gemini(api_key, prompt)
    if not response_text:
        print("Error: Received no response from Gemini.")
        return []

    clean_json = clean_json_response(response_text)
    try:
        items = json.loads(clean_json)
        if isinstance(items, list):
            return items
        else:
            print("Error: Gemini returned a JSON object instead of a list.")
            return []
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        print("Raw response from Gemini:")
        print(response_text)
        return []

def main():
    api_key = get_google_api_key()
    if not api_key:
        print("Error: Gemini API Key is missing. Check your credentials.")
        sys.exit(1)

    if not os.path.exists(RAW_EMAILS_DIR):
        print(f"Directory {RAW_EMAILS_DIR} does not exist. Creating it.")
        os.makedirs(RAW_EMAILS_DIR)
        print("Please place your receipt PDF/EML files there.")
        return

    os.makedirs(PARSED_EMAILS_DIR, exist_ok=True)

    files = [f for f in os.listdir(RAW_EMAILS_DIR) if os.path.isfile(os.path.join(RAW_EMAILS_DIR, f)) and f.lower().endswith(('.pdf', '.eml'))]
    if not files:
        print("No new EML or PDF files found in 'Raw Emails' directory.")
        return

    print(f"Found {len(files)} file(s) to process.")

    # Load existing closet
    closet_items = []
    if os.path.exists(CLOSET_FILE):
        try:
            with open(CLOSET_FILE, 'r') as f:
                closet_items = json.load(f)
            print(f"Loaded {len(closet_items)} existing items from closet.json.")
        except Exception as e:
            print(f"Error reading closet.json: {e}")
            sys.exit(1)
    else:
        print("No closet.json found. A new one will be created.")

    existing_ids = {item.get("id") for item in closet_items if "id" in item}
    new_added_count = 0

    for file_name in files:
        file_path = os.path.join(RAW_EMAILS_DIR, file_name)
        extracted_items = process_file(file_path, api_key)
        
        if not extracted_items:
            print(f"Failed to extract any items from {file_name}. Skipping move.")
            continue

        print(f"Extracted {len(extracted_items)} item(s) from {file_name}:")
        
        file_success_count = 0
        for item in extracted_items:
            item_id = item.get("id")
            if not item_id:
                print(f" - Warning: Item '{item.get('name')}' is missing 'id'. Skipping.")
                continue
            
            if item_id in existing_ids:
                print(f" - [Duplicate] {item_id} ('{item.get('name')}') is already in closet.")
            else:
                closet_items.append(item)
                existing_ids.add(item_id)
                print(f" - [Added] {item_id} ('{item.get('name')}')")
                new_added_count += 1
                file_success_count += 1

        # Move the parsed file to parsed/ subfolder
        dest_path = os.path.join(PARSED_EMAILS_DIR, file_name)
        try:
            shutil.move(file_path, dest_path)
            print(f"Moved {file_name} to Raw Emails/parsed/")
        except Exception as e:
            print(f"Error moving file {file_name}: {e}")

    if new_added_count > 0:
        try:
            with open(CLOSET_FILE, 'w') as f:
                json.dump(closet_items, f, indent=2)
            print(f"\nSuccessfully added {new_added_count} new items to closet.json.")
        except Exception as e:
            print(f"Error writing closet.json: {e}")
    else:
        print("\nNo new items were added to closet.json.")

if __name__ == "__main__":
    main()
