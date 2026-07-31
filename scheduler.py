import os
import json
import urllib.request
import urllib.parse
import urllib.error
import re
import sys
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
        with urllib.request.urlopen(req, timeout=30) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res['candidates'][0]['content']['parts'][0]['text']
    except urllib.error.HTTPError as e:
        print(f"Gemini API HTTP Error {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Gemini API Connection Error: {e}")
    return None

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
{closet_data[:8000]}

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

def execute_style_check(api_key, tg_token, wa_creds, job):
    print("Running Daily Style Check...")
    
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
        
    closet_data = ""
    closet_path = os.path.join(WORKSPACE_DIR, "closet.json")
    if os.path.exists(closet_path):
        try:
            with open(closet_path, 'r') as f:
                closet_data = f.read()
        except Exception as e:
            print(f"Error reading closet.json: {e}")
            
    deals_data = "No recent deals found."
    deals_path = os.path.join(WORKSPACE_DIR, "latest_clothing_deals.md")
    if os.path.exists(deals_path):
        try:
            with open(deals_path, 'r') as f:
                deals_data = f.read()
        except Exception as e:
            print(f"Error reading latest_clothing_deals.md: {e}")
            
    prompt = f"""You are the Daily Style Check Agent, a personal wardrobe stylist.
Your task is to recommend a great outfit combination (OOTD) for the user today based on the weather, their wardrobe inventory, and yesterday's deals.

Current Weather:
{weather_str}

User Wardrobe Profile:
- Size: Tops L/M, bottoms 32-34W 32-34L.
- Color Palette: Favor rich jewel tones (emerald, sapphire, ruby), high contrast, warm earth tones.

Wardrobe Inventory (closet.json):
{closet_data[:8000]}

Yesterday's Deals:
{deals_data}

Please recommend a complete outfit combination from the user's wardrobe inventory (items that are actually in closet.json) that is suitable for today's weather.
Explain your styling choice and why it works for the weather.

Format your output exactly as follows for Telegram/WhatsApp delivery:
🌤️ **Weather**: {weather_str}
👔 **OOTD**: [Outfit description with item names/brands]
🛍️ **Deals**: [Summary of the deals from yesterday's deals file]
"""
    
    result = call_gemini(api_key, prompt)
    if result:
        print("Generated OOTD recommendation. Sending notification...")
        if tg_token:
            chat_id = job.get("delivery", {}).get("to", "8510312060")
            send_telegram(tg_token, chat_id, result)
            print("Telegram notification sent.")
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
                        success = execute_style_check(api_key, tg_token, wa_creds, job)
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
