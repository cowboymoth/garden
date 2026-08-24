import csv
import re
import sys
from collections import defaultdict

csv.field_size_limit(sys.maxsize)

pattern = re.compile(r"\bovo\b", re.IGNORECASE)

album_songs = defaultdict(set)
album_has_ovo = defaultdict(bool)

with open("/Users/arakelian/Desktop/garden/drake/drake_data.xls", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        album = (row.get("album") or "").strip()
        title = (row.get("lyrics_title") or "").strip()
        lyrics = row.get("lyrics") or ""
        if not album or not title:
            continue
        album_songs[album].add(title)
        if pattern.search(lyrics):
            album_has_ovo[album] = True

EXCLUDE = {"Comeback Season", "Care Package", "Dark Lane Demo Tapes"}
studio = {a: songs for a, songs in album_songs.items() if len(songs) > 8 and a not in EXCLUDE}

total = len(studio)
hits = sum(1 for a in studio if album_has_ovo[a])
pct = (hits / total * 100) if total else 0

print(f"Studio albums (>8 songs): {total}")
print(f"With 'OVO': {hits}")
print(f"Percentage: {pct:.1f}%")
print()
for a in sorted(studio, key=lambda x: -len(studio[x])):
    mark = "OVO" if album_has_ovo[a] else "   "
    print(f"  [{mark}] {a} ({len(studio[a])} songs)")
