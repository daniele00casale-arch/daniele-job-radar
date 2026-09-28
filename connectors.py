"""
API connectors for Daniele Job Radar.

Each fetch_* function returns a list of plain dicts with a common shape:

    {
        "source": str,            # human-readable source name
        "source_id": str,         # id/slug/guid, used for de-duplication
        "title": str,
        "company": str,
        "location": str,          # free-text location / restriction string
        "worldwide": bool,        # True only when we are confident it's open worldwide
        "description": str,       # plain text (HTML stripped)
        "employment_type": str,   # "Full Time", "Contract", ...
        "seniority": str,         # ALWAYS a plain string (never a list)
        "salary": str,            # human-readable, "" when unknown
        "url": str,               # original application link
        "published_at": str,      # ISO date when possible
    }

Every network call is wrapped by the caller (app.py) in a try/except, so a
single connector failing (timeout, schema change, HTTP error) never brings
down the whole dashboard - it is reported in the "Avvisi connettori" panel
instead.
"""
import os
import re
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "DanieleJobRadar/1.0 (personal job search dashboard)"}
