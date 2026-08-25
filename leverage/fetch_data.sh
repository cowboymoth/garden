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
