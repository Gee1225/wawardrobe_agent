import json
import os

CLOSET_FILE = "closet.json"

if not os.path.exists(CLOSET_FILE):
    print("closet.json not found.")
    exit(1)

with open(CLOSET_FILE, 'r') as f:
    items = json.load(f)

print(f"Original closet size: {len(items)}")

seen = {}
deduped = []

for item in items:
    # Build a signature from key fields
    brand = str(item.get("brand", "")).strip().lower()
    name = str(item.get("name", "")).strip().lower()
    color = str(item.get("color", "")).strip().lower()
    size = str(item.get("size", "")).strip().lower()
    
    # Normalize size a bit (e.g. "large (slim fit)" vs "large")
    if "large" in size:
        size_norm = "large"
    elif "medium" in size:
        size_norm = "medium"
    else:
        size_norm = size.replace("w", "").replace("l", "").replace(" ", "").replace("-", "")

    sig = (brand, name.split("(")[0].strip(), color, size_norm)
    
    if sig in seen:
        print(f"Duplicate found: '{item.get('name')}' ({item.get('id')}) vs existing ({seen[sig].get('id')})")
        # Keep the one that has a cleaner ID or more tags
        existing_item = seen[sig]
        if len(item.get("style_tags", [])) > len(existing_item.get("style_tags", [])):
            seen[sig] = item
    else:
        seen[sig] = item

deduped = list(seen.values())
print(f"De-duplicated closet size: {len(deduped)}")

# Save back to file
with open(CLOSET_FILE, 'w') as f:
    json.dump(deduped, f, indent=2)
print("Saved de-duplicated closet.json.")
