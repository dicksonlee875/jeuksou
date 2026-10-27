#!/bin/sh
# Mac / Linux: scrape and rebuild. Run by hand or from cron.
cd "$(dirname "$0")" || exit 1
python3 scraper.py && python3 build.py
