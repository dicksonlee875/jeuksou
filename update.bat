@echo off
REM Windows: scrape and rebuild. Run by hand or from Task Scheduler.
cd /d "%~dp0"
python scraper.py
python build.py
