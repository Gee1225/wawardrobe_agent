import os
import json
import urllib.request
import urllib.parse
import urllib.error
import re
import sys
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Make WORKSPACE_DIR dynamic to support running locally and in GitHub Actions
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR") or os.path.dirname(os.path.abspath(__file__))
JOBS_FILE = os.path.join(WORKSPACE_DIR, "jobs.json")
STATE_FILE = os.path.join(WORKSPACE_DIR, "scheduler_state.json")

# For credentials, search current workspace first, then fall back to parent directory if running locally
def find_config_file(filename):
    path = os.path.join(WORKSPACE_DIR, filename)
    if os.path.exists(path):
        return path
    parent_path = os.path.join(os.path.dirname(WORKSPACE_DIR), filename)
    if os.path.exists(parent_path):
        return parent_path
    return path # default fallback

OPENCLAW_FILE = find_config_file("openclaw.json")
AUTH_PROFILES_FILE = find_config_file("auth-profiles.json")

def get_telegram_token():
    # 1. Check environment variable first
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    # 2. Fall back to openclaw.json
    try:
        if os.path.exists(OPENCLAW_FILE):
            with open(OPENCLAW_FILE, 'r') as f:
                config = json.load(f)
            return config.get("channels", {}).get("telegram", {}).get("botToken")
    except Exception as e:
        print(f"Error reading openclaw.json for Telegram token: {e}")
    return None

def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            res = response.read().decode("utf-8")
            return json.loads(res)
    except Exception as e:
        print(f"Error sending Telegram message to {chat_id}: {e}")
        return None

def get_whatsapp_credentials():
    # 1. Check environment variables first
    enabled = os.environ.get("WHATSAPP_ENABLED", "").lower() == "true"
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    to = os.environ.get("WHATSAPP_TO")
    
    if token and phone_number_id and to:
        return {
            "token": token,
            "phone_number_id": phone_number_id,
            "to": to,
            "enabled": enabled or True
        }
        
    # 2. Fall back to openclaw.json
    try:
        if os.path.exists(OPENCLAW_FILE):
            with open(OPENCLAW_FILE, 'r') as f:
                config = json.load(f)
            wa = config.get("channels", {}).get("whatsapp", {})
            return {
                "token": wa.get("accessToken"),
                "phone_number_id": wa.get("phoneNumberId"),
                "to": wa.get("to"),
                "enabled": wa.get("enabled", False)
            }
    except Exception as e:
        print(f"Error reading WhatsApp config from openclaw.json: {e}")
    return None

def send_whatsapp(token, phone_number_id, to, text):
    url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as response:
            res = response.read().decode("utf-8")
            return json.loads(res)
    except Exception as e:
        print(f"Error sending WhatsApp message to {to}: {e}")
        return None

def get_google_api_key():
    # 1. Check environment variables
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    # 2. Fall back to auth-profiles.json
    try:
        if os.path.exists(AUTH_PROFILES_FILE):
            with open(AUTH_PROFILES_FILE, 'r') as f:
                config = json.load(f)
            key = config.get("profiles", {}).get("google:default", {}).get("key")
            if key:
                return key
    except Exception as e:
        print(f"Error reading auth-profiles.json: {e}")
    # 3. Fall back to openclaw.json
    try:
        if os.path.exists(OPENCLAW_FILE):
            with open(OPENCLAW_FILE, 'r') as f:
                config = json.load(f)
            key = config.get("models", {}).get("providers", {}).get("google", {}).get("apiKey")
            if key:
                return key
    except Exception as e:
        print(f"Error reading openclaw.json for Google API key: {e}")
    return None

def ddg_search(query):
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(
        url, 
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
            results = []
            for m in re.finditer(r'<a class="result__url"[^>]*>([^<]+)</a>.*?<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL):
                url_text = m.group(1).strip()
                snippet = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                results.append(f"Source: {url_text}\nSnippet: {snippet}")
            return "\n\n".join(results[:5])
    except Exception as e:
        return f"Error searching DuckDuckGo: {e}"

def call_gemini(api_key, prompt, model="gemini-3.5-flash"):
    if not api_key:
        print("Error: Gemini API Key is missing. Cannot invoke model.")
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    req = urllib.request.Request(
        url, 
        data=json.dumps(payload).encode("utf-8"), 
        headers=headers, 
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res['candidates'][0]['content']['parts'][0]['text']
    except urllib.error.HTTPError as e:
        print(f"Gemini API HTTP Error {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Gemini API Connection Error: {e}")
    return None

HISTORY_FILE = os.path.join(WORKSPACE_DIR, "style_history.json")

def load_style_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading style_history.json: {e}")
    return []

def save_style_history(history):
    try:
        # Keep only the last 100 entries to prevent the file from growing indefinitely
        history_to_save = history[-100:]
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history_to_save, f, indent=2)
        print(f"Saved style history to {HISTORY_FILE}")
        return True
    except Exception as e:
        print(f"Error saving style history: {e}")
        return False

def find_item_in_closet(item_desc, closet_items):
    if not item_desc:
        return None
    # 1. Match by ID
    item_id = item_desc.get("id")
    if item_id:
        for item in closet_items:
            if item.get("id") == item_id:
                return item
    
    # 2. Fallback: match by brand/name/color
    brand_desc = str(item_desc.get("brand", "")).strip().lower()
    name_desc = str(item_desc.get("name", "")).strip().lower()
    color_desc = str(item_desc.get("color", "")).strip().lower()
    
    best_match = None
    best_score = 0
    for item in closet_items:
        item_brand = str(item.get("brand", "")).strip().lower()
        item_name = str(item.get("name", "")).strip().lower()
        item_color = str(item.get("color", "")).strip().lower()
        
        score = 0
        if brand_desc and brand_desc in item_brand:
            score += 1
        # Check name overlap
        if name_desc:
            if name_desc in item_name or item_name in name_desc:
                score += 2
            elif any(w in item_name for w in name_desc.split() if len(w) > 3):
                score += 1
        if color_desc and (color_desc in item_color or item_color in color_desc):
            score += 1
            
        if score > best_score:
            best_score = score
            best_match = item
            
    if best_score >= 2: # At least a decent match
        return best_match
    return None

def get_broad_weather(weather_str):
    # Try to parse temperature in Fahrenheit
    temp_f = None
    # Check for something like +85°F or 85 °F or 85F
    temp_match = re.search(r'([+-]?\d+)\s*(?:°F|F)', weather_str)
    if temp_match:
        temp_f = int(temp_match.group(1))
    else:
        # Check for generic number
        temp_match = re.search(r'([+-]?\d+)', weather_str)
        if temp_match:
            temp_f = int(temp_match.group(1))
    
    if temp_f is None:
        return "Mild", "Treat temperature as comfortable (approx 70°F)."
        
    if temp_f >= 80:
        category = "Hot"
        advice = "Avoid heavy sweaters, hoodies, or thick outerwear. Prioritize light/breathable fabrics like short sleeves or polos."
    elif temp_f >= 65:
        category = "Warm/Mild"
        advice = "Perfect for standard shirts, polos, light chinos. Layering is optional."
    elif temp_f >= 50:
        category = "Cool"
        advice = "Good for long-sleeves, sweaters, light jackets, or layering."
    else:
        category = "Cold"
        advice = "Prioritize warm sweaters, layering, and outerwear."
        
    return f"{category} ({temp_f}°F)", advice


def execute_deal_hunter(api_key):
    print("Running Evening Deal Hunter...")
    
    closet_data = ""
    closet_path = os.path.join(WORKSPACE_DIR, "closet.json")
    if os.path.exists(closet_path):
        try:
            with open(closet_path, 'r') as f:
                closet_data = f.read()
        except Exception as e:
            print(f"Error reading closet.json: {e}")
            
    print("Searching for wardrobe deals...")
    q1 = ddg_search("J.Crew Banana Republic men's sale deals 2026")
    q2 = ddg_search("Theory Suitsupply men's sale deals 2026")
    search_results = f"--- J.Crew / Banana Republic ---\n{q1}\n\n--- Theory / Suitsupply ---\n{q2}"
    
    prompt = f"""You are the Evening Deal Hunter, a professional personal shopping assistant.
Your task is to find the best current online sales/deals for men's professional clothing at J.Crew, Banana Republic, Theory, and Suitsupply that fit the user's size and style profile.

User Wardrobe Profile:
- Size: Tops L/M, bottoms 32-34W 32-34L.
- Color Palette: Favor rich jewel tones (emerald, sapphire, ruby), high contrast, warm earth tones.
- Preferred Brands: J.Crew, Banana Republic, Theory, Suitsupply.

User Closet Inventory (for matching and context):
{closet_data}

Search Grounding Context from DuckDuckGo:
{search_results}

Please identify the top 2-3 specific deals or current sale events matching the profile.
Format your output as a clean markdown document. For each deal, provide:
1. **Brand & Item/Sale Name**
2. **Details / Price** (e.g., "50% off select styles" or specific item price)
3. **Link**: A markdown link (use the source URLs from the search context, or clean direct store links)
4. **Styling Insight**: Explain why this fits the user's wardrobe and matches their color/size profile.

Do not include any wrapper or backticks (like ```markdown). Just output the raw markdown text.
"""
    
    result = call_gemini(api_key, prompt)
    if result:
        deals_path = os.path.join(WORKSPACE_DIR, "latest_clothing_deals.md")
        try:
            with open(deals_path, 'w') as f:
                f.write(result)
            print(f"Successfully saved deals to {deals_path}")
            return True
        except Exception as e:
            print(f"Error writing latest_clothing_deals.md: {e}")
    else:
        print("Failed to get deals from Gemini.")
    return False

def draw_ootd_card(weather_str, top, bottom, belt, output_path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not available. Skipping image generation.")
        return False

    try:
        # Create a 800x800 image with a rich dark background
        img = Image.new("RGB", (800, 800), "#121216")
        draw = ImageDraw.Draw(img)
        
        # Draw a gold accent top border
        draw.rectangle([0, 0, 800, 12], fill="#D4AF37")
        
        # Helper to load system font
        def get_font(size):
            font_paths = [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "Arial.ttf"
            ]
            for path in font_paths:
                if os.path.exists(path):
                    try:
                        return ImageFont.truetype(path, size)
                    except Exception:
                        pass
            return ImageFont.load_default()

        # Title (clean plain text, no emojis to prevent missing glyphs)
        font_title = get_font(36)
        draw.text((50, 50), "DAILY STYLE CHECK", fill="#D4AF37", font=font_title)
        
        # Subtitle
        font_sub = get_font(20)
        draw.text((50, 100), "Styled by Gee", fill="#8E8E93", font=font_sub)
        
        # Weather Box
        draw.rounded_rectangle([50, 150, 750, 240], radius=15, fill="#1C1C24", outline="#2C2C35", width=2)
        font_weather = get_font(22)
        # Clean weather string of emojis for drawing
        clean_weather = weather_str.replace("🌤️", "").replace("☀️", "").replace("🌧️", "").replace("❄️", "").replace("☁️", "").strip()
        draw.text((70, 175), f"Weather: {clean_weather}", fill="#FFFFFF", font=font_weather)
        
        # Outfit Section Title
        font_section = get_font(28)
        draw.text((50, 280), "TODAY'S OOTD", fill="#FFFFFF", font=font_section)
        
        # Outfit Items
        font_item_label = get_font(20)
        font_item_name = get_font(24)
        
        y_offset = 340
        items = [
            ("TOP", top.get("name", "Unknown Top"), top.get("brand", "Unknown Brand"), top.get("color", "Unknown")),
            ("BOTTOM", bottom.get("name", "Unknown Bottom"), bottom.get("brand", "Unknown Brand"), bottom.get("color", "Unknown")),
            ("ACCESSORY", belt.get("name", "Unknown Accessory"), belt.get("brand", "Unknown Brand"), belt.get("color", "Unknown"))
        ]
        
        # Color mapping for swatches
        color_map = {
            "navy": "#1B2A4A",
            "taupe": "#B5A695",
            "cognac": "#9E5624",
            "brown": "#5C3A21",
            "black": "#111111",
            "white": "#F5F5F5",
            "pink": "#F0C0C0",
            "green": "#2C5E43",
            "blue": "#2F5C8F",
            "gray": "#8C8C8C",
            "grey": "#8C8C8C",
            "stone": "#D4D1C9",
            "lemon": "#EBE3A3",
            "lilac": "#C8A2C8",
            "purple": "#5D2E8C",
            "teal": "#008080",
            "beige": "#F5F5DC",
            "red": "#A32B2B",
            "orange": "#E67E22",
            "yellow": "#F1C40F"
        }
        
        for label, name, brand, color in items:
            # Draw item card
            draw.rounded_rectangle([50, y_offset, 750, y_offset + 100], radius=12, fill="#1C1C24")
            
            # Find matching swatch color
            color_lower = color.lower()
            hex_color = "#8E8E93" # default grey
            for key, val in color_map.items():
                if key in color_lower:
                    hex_color = val
                    break
                    
            draw.ellipse([70, y_offset + 25, 120, y_offset + 75], fill=hex_color, outline="#3A3A45", width=2)
            
            # Text details
            draw.text((150, y_offset + 15), label, fill="#D4AF37", font=font_item_label)
            draw.text((150, y_offset + 40), f"{brand} - {name}", fill="#FFFFFF", font=font_item_name)
            draw.text((150, y_offset + 68), f"Color: {color}", fill="#8E8E93", font=font_item_label)
            
            y_offset += 120

        # Save image
        img.save(output_path, "PNG")
        return True
    except Exception as e:
        print(f"Error rendering OOTD card: {e}")
        return False

def execute_style_check(api_key, tg_token, wa_creds, job, target_date=None):
    if target_date is None:
        target_date = datetime.now(ZoneInfo("America/Chicago"))
        
    print(f"Running Daily Style Check for target date: {target_date.strftime('%Y-%m-%d')}...")
    
    weather_str = "Unknown weather"
    try:
        req = urllib.request.Request(
            "http://wttr.in/Bentonville+AR?format=%l:+%c+%t+%w",
            headers={"User-Agent": "curl/7.79.1"}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            weather_str = response.read().decode("utf-8").strip()
    except Exception as e:
        print(f"Error fetching weather: {e}")
        
    broad_weather, weather_advice = get_broad_weather(weather_str)
    
    history = load_style_history()
    
    # Analyze history relative to target_date to avoid duplicates
    worn_ids_7d = set()
    worn_ids_30d = set()
    item_stats = {} # id -> {"last_worn_date": str, "days_ago": int, "times_worn": int}
    
    for entry in history:
        entry_date_str = entry.get("date")
        try:
            entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d").replace(tzinfo=ZoneInfo("America/Chicago"))
        except Exception:
            try:
                entry_date = datetime.fromisoformat(entry_date_str).astimezone(ZoneInfo("America/Chicago"))
            except Exception:
                continue
                
        days_diff = (target_date.date() - entry_date.date()).days
        
        if days_diff <= 0:
            continue
            
        ootd = entry.get("ootd", {})
        for slot, item in ootd.items():
            item_id = item.get("id")
            if not item_id:
                continue
                
            if days_diff <= 7:
                worn_ids_7d.add(item_id)
            if days_diff <= 30:
                worn_ids_30d.add(item_id)
                
            if item_id not in item_stats:
                item_stats[item_id] = {
                    "last_worn_date": entry_date_str,
                    "days_ago": days_diff,
                    "times_worn": 1
                }
            else:
                item_stats[item_id]["times_worn"] += 1
                if days_diff < item_stats[item_id]["days_ago"]:
                    item_stats[item_id]["days_ago"] = days_diff
                    item_stats[item_id]["last_worn_date"] = entry_date_str
                    
    closet_items = []
    closet_path = os.path.join(WORKSPACE_DIR, "closet.json")
    if os.path.exists(closet_path):
        try:
            with open(closet_path, 'r') as f:
                closet_items = json.load(f)
        except Exception as e:
            print(f"Error reading closet.json: {e}")
            
    # Group closet by categories
    grouped = {
        "Top": [],
        "Bottom": [],
        "Belt": []
    }
    
    for item in closet_items:
        cat = item.get("category")
        sub_cat = item.get("sub_category", "")
        
        if cat == "Top":
            grouped["Top"].append(item)
        elif cat == "Bottom":
            grouped["Bottom"].append(item)
        elif cat == "Accessories" and sub_cat == "Belt":
            grouped["Belt"].append(item)
            
    filtered_closet = []
    
    # Exclude 7-day repetitions with safe fallbacks
    limits = {
        "Top": 5,
        "Bottom": 3,
        "Belt": 2
    }
    
    for cat_name, items in grouped.items():
        min_rem = limits.get(cat_name, 2)
        not_worn_7d = [i for i in items if i.get("id") not in worn_ids_7d]
        
        if len(not_worn_7d) >= min_rem:
            selected_items = not_worn_7d
        else:
            # Fallback: keep the least recently recommended items
            def sort_key(item):
                stats = item_stats.get(item.get("id"))
                if not stats:
                    return -999999
                return -stats["days_ago"]
                
            sorted_items = sorted(items, key=sort_key)
            selected_items = sorted_items[:min_rem]
            
        # Add metadata for model reasoning
        for item in selected_items:
            item_id = item.get("id")
            stats = item_stats.get(item_id)
            item_copy = dict(item)
            if stats:
                item_copy["last_recommended"] = f"{stats['days_ago']} days ago"
                item_copy["times_recommended_last_30_days"] = stats["times_worn"]
            else:
                item_copy["last_recommended"] = "never"
                item_copy["times_recommended_last_30_days"] = 0
            filtered_closet.append(item_copy)
            
    recent_recommendations_str = ""
    if history:
        recent_entries = []
        for entry in history[-10:]:
            entry_date_str = entry.get("date")
            ootd = entry.get("ootd", {})
            t_info = f"{ootd.get('top', {}).get('brand', '')} {ootd.get('top', {}).get('name', '')} ({ootd.get('top', {}).get('color', '')})"
            b_info = f"{ootd.get('bottom', {}).get('brand', '')} {ootd.get('bottom', {}).get('name', '')} ({ootd.get('bottom', {}).get('color', '')})"
            belt_info = f"{ootd.get('belt', {}).get('brand', '')} {ootd.get('belt', {}).get('name', '')} ({ootd.get('belt', {}).get('color', '')})"
            recent_entries.append(f"- {entry_date_str}: Top: {t_info} | Bottom: {b_info} | Belt: {belt_info}")
        recent_recommendations_str = "\n".join(recent_entries)
    else:
        recent_recommendations_str = "None"
        
    is_friday = target_date.weekday() == 4
    
    deals_data = None
    if is_friday:
        deals_path = os.path.join(WORKSPACE_DIR, "latest_clothing_deals.md")
        if os.path.exists(deals_path):
            try:
                with open(deals_path, 'r') as f:
                    deals_data = f.read()
            except Exception as e:
                print(f"Error reading latest_clothing_deals.md: {e}")
                
    deals_section_prompt = ""
    deals_format_prompt = ""
    if is_friday and deals_data:
        deals_section_prompt = f"\nYesterday's Deals:\n{deals_data}\n"
        deals_format_prompt = "\n🛍️ **Deals**: [Summary of the deals from yesterday's deals file]"
    else:
        deals_format_prompt = "\n🛍️ **Deals**: No deals today (deals are sent on Fridays)"

    prompt = f"""You are the Daily Style Check Agent, a personal wardrobe stylist.
Your task is to recommend a great outfit combination (OOTD) for the user today based on the weather, their wardrobe inventory, and style history.{deals_section_prompt}

Current Weather:
- Raw weather data: {weather_str}
- Broad category: {broad_weather}
- Styling Advice: {weather_advice}

User Wardrobe Profile:
- Size: Tops L/M, bottoms 32-34W 32-34L.
- Color Palette: Favor rich jewel tones (emerald, sapphire, ruby), high contrast, warm earth tones.

Recent Style History (Last 30 Days):
{recent_recommendations_str}

CRITICAL RULES FOR ROTATION AND VARIETY:
1. **NO WEEKLY REPETITION**: You MUST NOT recommend any item that has been worn in the last 7 days. If a category (like belts) has limited choices, prioritize the item worn longest ago.
2. **MONTHLY VARIETY**: Avoid repeating items that have been worn in the last 30 days. Prioritize items labeled "last_recommended: never" or with a low frequency ("times_recommended_last_30_days"). Do NOT repeat the exact same combination of top, bottom, and belt.
3. **REDUCE WEATHER OVER-OPTIMIZATION**: Treat the weather category as a loose guide. If it is hot, simply avoid heavy sweaters or long sleeves; you do not need to choose the same short-sleeve polo shirt every hot day. Choose from a wide range of shirts, t-shirts, and light tops to ensure variety. Rotate through colors (emerald, sapphire, ruby, slate, etc.) and styles.

Available Wardrobe Inventory (Pre-filtered to support rotation):
{json.dumps(filtered_closet, indent=2)}

Please recommend a complete outfit combination from the provided available wardrobe inventory (choose strictly from items in the list above) that is suitable for today's weather category.
Explain your styling choice and why it works, and comment on the rotation choice (e.g., noting that this item hasn't been worn in a while).

Format your output exactly as follows for Telegram/WhatsApp delivery:
🌤️ **Weather**: {weather_str}
👔 **OOTD**: [Outfit description with item names/brands]{deals_format_prompt}

Additionally, you MUST output the following two blocks at the very end of your response:

1. A raw JSON block inside a block tagged with [JSON_START] and [JSON_END], listing the OOTD items chosen (make sure to copy the "id" exactly from the available inventory list):
[JSON_START]
{{
  "top": {{"id": "item-id", "brand": "Brand", "name": "Item Name", "color": "Color"}},
  "bottom": {{"id": "item-id", "brand": "Brand", "name": "Item Name", "color": "Color"}},
  "belt": {{"id": "item-id", "brand": "Brand", "name": "Item Name", "color": "Color"}}
}}
[JSON_END]

2. An image generation prompt inside a block tagged with [IMAGE_PROMPT_START] and [IMAGE_PROMPT_END].
The prompt MUST describe the exact clothing items recommended above, but simplified so a text-to-image AI model can render them accurately.
CRITICAL: Do NOT include brand names, collection names, trademark symbols (like ®), or model numbers. Instead, use only simple, descriptive color and garment words (e.g., "a teal short-sleeve polo shirt", "stone-colored chino pants", "a cognac brown leather belt").
The prompt must look exactly like this format:
[IMAGE_PROMPT_START]
A photorealistic, high-quality, professional full-body portrait of a darkskinned black man wearing: [simplified top description with color], [simplified pants/bottoms description with color], and [simplified belt/accessory description with color]. Standing in a modern minimalist office with soft lighting.
[IMAGE_PROMPT_END]
"""
    
    result = call_gemini(api_key, prompt)
    if result:
        print("Generated OOTD recommendation. Parsing structured details...")
        
        # Parse the image prompt payload
        image_prompt = None
        match_prompt = re.search(r'\[IMAGE_PROMPT_START\](.*?)\[IMAGE_PROMPT_END\]', result, re.DOTALL)
        if match_prompt:
            image_prompt = match_prompt.group(1).strip()
            result = result.replace(match_prompt.group(0), "").strip()

        # Parse the JSON payload out of the response text
        ootd_json = None
        match_json = re.search(r'\[JSON_START\](.*?)\[JSON_END\]', result, re.DOTALL)
        if match_json:
            try:
                ootd_json = json.loads(match_json.group(1).strip())
                result = result.replace(match_json.group(0), "").strip()
            except Exception as e:
                print(f"Error parsing OOTD JSON block: {e}")
                
        # Resolve recommended items and save to history
        if ootd_json:
            resolved_ootd = {}
            for slot in ["top", "bottom", "belt"]:
                item_desc = ootd_json.get(slot, {})
                matched = find_item_in_closet(item_desc, closet_items)
                if matched:
                    resolved_ootd[slot] = {
                        "id": matched.get("id"),
                        "brand": matched.get("brand"),
                        "name": matched.get("name"),
                        "color": matched.get("color")
                    }
                else:
                    resolved_ootd[slot] = {
                        "id": item_desc.get("id") or "",
                        "brand": item_desc.get("brand") or "",
                        "name": item_desc.get("name") or "",
                        "color": item_desc.get("color") or ""
                    }
            
            rec_date_str = target_date.strftime("%Y-%m-%d")
            # Remove any existing entry for today's date to avoid duplicates on retries
            history = [h for h in history if h.get("date") != rec_date_str]
            history.append({
                "date": rec_date_str,
                "ootd": resolved_ootd
            })
            save_style_history(history)

        # Attempt to draw or generate OOTD photo
        image_path = os.path.join(WORKSPACE_DIR, "ootd.png")
        image_generated = False
        
        if image_prompt:
            print(f"Generating OOTD photo using Pollinations AI: {image_prompt}")
            try:
                full_prompt = f"{image_prompt}, photorealistic, professional photography, high quality"
                # Use a random seed to force generating a fresh new image variation
                seed = random.randint(1, 1000000)
                url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(full_prompt)}?seed={seed}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    img_data = response.read()
                    if img_data:
                        with open(image_path, 'wb') as f:
                            f.write(img_data)
                        print("Successfully generated OOTD photo.")
                        image_generated = True
            except Exception as e:
                print(f"Failed to generate AI OOTD photo: {e}")

        # Fallback to Pillow card drawing if AI photo generation failed
        if not image_generated and ootd_json:
            print("Falling back to Pillow OOTD card card...")
            image_generated = draw_ootd_card(weather_str, ootd_json.get("top", {}), ootd_json.get("bottom", {}), ootd_json.get("belt", {}), image_path)

        # Send photo to Telegram
        image_sent = False
        if image_generated:
            try:
                import requests
                if tg_token:
                    chat_id = job.get("delivery", {}).get("to", "8510312060")
                    # 1. Send the OOTD image card first with a short, clean caption
                    url_photo = f"https://api.telegram.org/bot{tg_token}/sendPhoto"
                    clean_weather = weather_str.replace("🌤️", "").replace("☀️", "").replace("🌧️", "").replace("❄️", "").replace("☁️", "").strip()
                    short_caption = f"Style Check for today! ({clean_weather})"
                    
                    with open(image_path, "rb") as f:
                        files = {"photo": f}
                        data = {"chat_id": chat_id, "caption": short_caption}
                        response = requests.post(url_photo, files=files, data=data, timeout=30)
                        if response.status_code == 200:
                            print("Telegram photo sent successfully.")
                            image_sent = True
                        else:
                            print(f"Failed to send Telegram photo: {response.text}")
                    
                    # 2. Send the detailed text recommendation as a follow-up
                    if image_sent:
                        send_telegram(tg_token, chat_id, result)
                        print("Telegram OOTD details sent as follow-up.")
            except Exception as e:
                print(f"Error sending Telegram photo: {e}")

        # Fall back to text if image generation/sending failed
        if not image_sent:
            if tg_token:
                chat_id = job.get("delivery", {}).get("to", "8510312060")
                send_telegram(tg_token, chat_id, result)
                print("Telegram text notification sent.")

        if wa_creds and wa_creds.get("enabled"):
            wa_token = wa_creds.get("token")
            wa_phone_id = wa_creds.get("phone_number_id")
            wa_to = job.get("delivery", {}).get("to") or wa_creds.get("to")
            if wa_token and wa_phone_id and wa_to:
                wa_to_clean = "".join(c for c in wa_to if c.isdigit())
                send_whatsapp(wa_token, wa_phone_id, wa_to_clean, result)
                print("WhatsApp notification sent.")
        return True
    else:
        print("Failed to get styling recommendation from Gemini.")
    return False

def match_cron_field(pattern, value):
    if pattern == '*':
        return True
    for part in pattern.split(','):
        if '-' in part:
            start, end = map(int, part.split('-'))
            if start <= value <= end:
                return True
        else:
            if int(part) == value:
                return True
    return False

def match_cron(expr, dt):
    parts = expr.split()
    if len(parts) != 5:
        return False
    m, h, dom, mon, dow = parts
    
    cron_dow = (dt.weekday() + 1) % 7
    
    def match_dow(pattern, dt_val):
        if pattern == '*':
            return True
        for part in pattern.split(','):
            if '-' in part:
                start, end = map(int, part.split('-'))
                allowed = set()
                curr = start
                while True:
                    allowed.add(curr % 7)
                    if curr % 7 == end % 7:
                        break
                    curr += 1
                if dt_val in allowed:
                    return True
            else:
                val = int(part)
                if val in (0, 7) and dt_val == 0:
                    return True
                elif val == dt_val:
                    return True
        return False

    return (match_cron_field(m, dt.minute) and
            match_cron_field(h, dt.hour) and
            match_cron_field(dom, dt.day) and
            match_cron_field(mon, dt.month) and
            match_dow(dow, cron_dow))

def is_static_telegram_job(message_body):
    return "Use the 'message' tool to send this exact text" in message_body

def extract_telegram_text(message_body):
    parts = message_body.split(":\n\n", 1)
    if len(parts) < 2:
        parts = message_body.split(":\\n\\n", 1)
    return parts[1] if len(parts) >= 2 else message_body

def main():
    api_key = get_google_api_key()
    tg_token = get_telegram_token()
    wa_creds = get_whatsapp_credentials()
    
    # Check CLI options
    if "--run-style-check" in sys.argv:
        style_check_job = {}
        if os.path.exists(JOBS_FILE):
            try:
                with open(JOBS_FILE, 'r') as f:
                    jobs_data = json.load(f)
                    for j in jobs_data.get("jobs", []):
                        if j.get("name") == "Good morning! Time for your daily style check.":
                            style_check_job = j
                            break
            except Exception:
                pass
        execute_style_check(api_key, tg_token, wa_creds, style_check_job)
        return

    if "--run-deal-hunter" in sys.argv:
        execute_deal_hunter(api_key)
        return
    
    if not tg_token and (not wa_creds or not wa_creds.get("enabled")):
        print("--- SCHEDULER DIAGNOSTIC INFO ---")
        print(f"WORKSPACE_DIR: {WORKSPACE_DIR}")
        print(f"JOBS_FILE exists: {os.path.exists(JOBS_FILE)}")
        print(f"TELEGRAM_BOT_TOKEN env var set: {bool(os.environ.get('TELEGRAM_BOT_TOKEN'))}")
        print(f"GEMINI_API_KEY env var set: {bool(os.environ.get('GEMINI_API_KEY'))}")
        print(f"openclaw.json found at: {OPENCLAW_FILE} (exists: {os.path.exists(OPENCLAW_FILE)})")
        print(f"auth-profiles.json found at: {AUTH_PROFILES_FILE} (exists: {os.path.exists(AUTH_PROFILES_FILE)})")
        print("---------------------------------")
        print("No notification channels (Telegram or WhatsApp) configured/enabled. Exiting.")
        return

    now = datetime.now(ZoneInfo("America/Chicago"))
    
    last_run_str = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
                last_run_str = state.get("last_run")
        except Exception as e:
            print(f"Error reading state file: {e}")

    if last_run_str:
        last_run = datetime.fromisoformat(last_run_str).astimezone(ZoneInfo("America/Chicago"))
    else:
        last_run = now - timedelta(minutes=30)

    if last_run >= now:
        print(f"Scheduler already ran at {last_run_str}. Current time is {now.isoformat()}. Skipping.")
        return

    try:
        with open(JOBS_FILE, 'r') as f:
            jobs_data = json.load(f)
            jobs = jobs_data.get("jobs", [])
    except Exception as e:
        print(f"Error loading jobs.json: {e}")
        return

    print(f"Evaluating cron jobs between {last_run.isoformat()} and {now.isoformat()}...")

    due_ai_jobs = []
    sent_tg_reminders = 0
    sent_wa_reminders = 0

    current_eval = last_run + timedelta(minutes=1)
    current_eval = current_eval.replace(second=0, microsecond=0)
    now_truncated = now.replace(second=0, microsecond=0)

    while current_eval <= now_truncated:
        for job in jobs:
            if not job.get("enabled", True):
                continue
            
            schedule_expr = job.get("schedule", {}).get("expr")
            if not schedule_expr:
                continue

            tz_name = job.get("schedule", {}).get("tz", "America/Chicago")
            dt_local = current_eval.astimezone(ZoneInfo(tz_name))

            if match_cron(schedule_expr, dt_local):
                payload = job.get("payload", {})
                message_body = payload.get("message", "")
                
                if is_static_telegram_job(message_body):
                    clean_text = extract_telegram_text(message_body)
                    
                    if tg_token:
                        chat_id = job.get("delivery", {}).get("to", "8510312060")
                        print(f"[{dt_local.isoformat()}] Sending Telegram reminder: '{job['name']}' to {chat_id}")
                        res = send_telegram(tg_token, chat_id, clean_text)
                        if res and res.get("ok"):
                            print(" -> Telegram Success")
                            sent_tg_reminders += 1
                        else:
                            print(" -> Telegram Failed")

                    if wa_creds and wa_creds.get("enabled"):
                        wa_token = wa_creds.get("token")
                        wa_phone_id = wa_creds.get("phone_number_id")
                        wa_to = None
                        if job.get("delivery", {}).get("channel") == "whatsapp":
                            wa_to = job.get("delivery", {}).get("to")
                        if not wa_to:
                            wa_to = wa_creds.get("to")
                        
                        if wa_token and wa_phone_id and wa_to:
                            wa_to_clean = "".join(c for c in wa_to if c.isdigit())
                            print(f"[{dt_local.isoformat()}] Sending WhatsApp reminder: '{job['name']}' to {wa_to_clean}")
                            res = send_whatsapp(wa_token, wa_phone_id, wa_to_clean, clean_text)
                            if res and "messages" in res:
                                print(" -> WhatsApp Success")
                                sent_wa_reminders += 1
                            else:
                                print(" -> WhatsApp Failed")
                else:
                    # AI Agent Job
                    job_name = job.get("name")
                    print(f"[{dt_local.isoformat()}] Triggering AI Job: '{job_name}'")
                    
                    if job_name == "Good morning! Time for your daily style check.":
                        success = execute_style_check(api_key, tg_token, wa_creds, job, target_date=dt_local)
                    elif job_name == "Evening Deal Hunter":
                        success = execute_deal_hunter(api_key)
                    else:
                        # Generic AI job runner
                        print(f" -> Running generic AI job '{job_name}' using Gemini")
                        success = False
                        result = call_gemini(api_key, message_body)
                        if result:
                            success = True
                            if tg_token:
                                chat_id = job.get("delivery", {}).get("to") or "8510312060"
                                send_telegram(tg_token, chat_id, result)
                                print(" -> Generic Telegram notification sent.")
                            if wa_creds and wa_creds.get("enabled"):
                                wa_token = wa_creds.get("token")
                                wa_phone_id = wa_creds.get("phone_number_id")
                                wa_to = job.get("delivery", {}).get("to") or wa_creds.get("to")
                                if wa_token and wa_phone_id and wa_to:
                                    wa_to_clean = "".join(c for c in wa_to if c.isdigit())
                                    send_whatsapp(wa_token, wa_phone_id, wa_to_clean, result)
                                    print(" -> Generic WhatsApp notification sent.")
                    
                    due_ai_jobs.append({
                        "id": job.get("id"),
                        "name": job_name,
                        "time": dt_local.isoformat(),
                        "executed": success
                    })

        current_eval += timedelta(minutes=1)

    try:
        with open(STATE_FILE, 'w') as f:
            json.dump({"last_run": now.isoformat()}, f, indent=2)
    except Exception as e:
        print(f"Error writing state file: {e}")

    print("\n--- RUN SUMMARY ---")
    print(f"Total Telegram reminders sent: {sent_tg_reminders}")
    print(f"Total WhatsApp reminders sent: {sent_wa_reminders}")
    print(f"Total AI tasks evaluated: {len(due_ai_jobs)}")
    
    if due_ai_jobs:
        print("\n--- DUE AI JOBS ---")
        for job in due_ai_jobs:
            print(f"AI_JOB: {job['name']} (Executed: {job['executed']}) at {job['time']}")
        print("-------------------")
    else:
        print("\nNo AI jobs due.")

if __name__ == "__main__":
    main()
