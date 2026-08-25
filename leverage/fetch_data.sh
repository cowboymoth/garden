#!/bin/sh
# Download the 2024 Retrosheet season: 30 team event files (every pitch of every
# game) plus the two box-score files used to check the parser's arithmetic.
# ~25 MB, not committed. Run this once before parse_retrosheet.py.
set -e
cd "$(dirname "$0")"
mkdir -p data/rs2024
cd data/rs2024
BASE=https://raw.githubusercontent.com/chadwickbureau/retrosheet/master/seasons/2024

AL="ANA BAL BOS CHA CLE DET HOU KCA MIN NYA OAK SEA TBA TEX TOR"
NL="ARI ATL CHN CIN COL LAN MIA MIL NYN PHI PIT SDN SFN SLN WAS"

for t in $AL; do curl -sSLf -O "$BASE/2024$t.EVA" & done
for t in $NL; do curl -sSLf -O "$BASE/2024$t.EVN" & done
curl -sSLf -O "$BASE/2024.EBA" &
curl -sSLf -O "$BASE/2024.EBN" &
wait

echo "got $(ls | wc -l) files, $(grep -h -c '^id,' *.EV? | paste -sd+ | bc) games"

# --- published tables we read rather than derive ourselves -----------------
# Greg Stoll's Win Expectancy Finder data (github.com/gregstoll/baseballstats),
# computed from Retrosheet play-by-play across 195,573 games. probs.txt is the
# balls=0,strikes=0 slice of probswithballsstrikes.txt, so we only need the latter.
cd ../..
mkdir -p data/external
cd data/external
GS=https://raw.githubusercontent.com/gregstoll/baseballstats/master
curl -sSLf -o probswithballsstrikes.txt "$GS/probswithballsstrikes.txt"
curl -sSLf -o runsperinningstats        "$GS/runsperinningstats"
curl -sSLf -o leverage                  "$GS/statsyears/leverage"
echo "external tables: $(du -sh . | cut -f1)"
