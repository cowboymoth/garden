import csv
import re
import sys

csv.field_size_limit(sys.maxsize)

terms = {
    "21": r"\b21\b",
    "A$AP": r"(?:a\$ap|\basap\b)",
    "Compton": r"\bcompton\b",
    "Crypto / Bitcoin": r"\b(crypto|bitcoin)\b",
    "Drizzy": r"\bdrizzy\b",
    "Iceman": r"\biceman\b",
    "K-Dot": r"\bk[- ]?dot\b",
    "Kendrick": r"\bkendrick\b",
    "Kung Fu Kenny": r"\bkung[- ]?fu[- ]?kenny\b",
    "Metro": r"\bmetro\b",
    "OVO": r"\bovo\b",
    "Papi": r"\bpapi\b",
    "Pulitzer": r"\bpulitzer\b",
    "Raptors": r"\braptors\b",
    "Rick Ross": r"\brick ross\b",
    "Superbowl": r"\bsuper ?bowl\b",
    "Toronto": r"\btoronto\b",
    "Trump": r"\btrump\b",
}

results = {k: {"count": 0, "songs": set()} for k in terms}

with open("/Users/arakelian/Desktop/garden/drake/drake_data.xls", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        lyrics = (row.get("lyrics") or "").lower()
        title = row.get("lyrics_title") or ""
        if not lyrics:
            continue
        for label, pattern in terms.items():
            matches = re.findall(pattern, lyrics, flags=re.IGNORECASE)
            if matches:
                results[label]["count"] += len(matches)
                results[label]["songs"].add(title)

print(f"{'Term':<20} {'Total Uses':>12} {'Unique Songs':>14}")
print("-" * 48)
for label in terms:
    r = results[label]
    print(f"{label:<20} {r['count']:>12} {len(r['songs']):>14}")
