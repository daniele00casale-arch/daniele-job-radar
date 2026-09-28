import mailbox, email, re
from bs4 import BeautifulSoup
from pathlib import Path

def parse_eml_bytes(raw, source="Email alert"):
    msg=email.message_from_bytes(raw)
    body=""
    if msg.is_multipart():
        for p in msg.walk():
            if p.get_content_type() in ("text/html","text/plain") and "attachment" not in str(p.get("Content-Disposition","")):
                try: body += p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8",errors="ignore")
                except Exception: pass
    else:
        body=(msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8",errors="ignore")
    soup=BeautifulSoup(body,"html.parser")
    text=soup.get_text(" ",strip=True)
    links=[a.get("href") for a in soup.find_all("a",href=True)]
    # Email alerts vary. The MVP stores one email record and exposes links for review.
    return {"source":source,"source_id":msg.get("Message-ID",msg.get("Date","")),"title":msg.get("Subject","Job alert"),
      "company":"Multiple companies","location":"From email","description":text,"employment_type":"","seniority":"",
      "url":next((x for x in links if "job" in x.lower()),links[0] if links else ""),"published_at":msg.get("Date",""),
      "salary":"","worldwide":bool(re.search(r"worldwide|anywhere in the world|work from anywhere",text,re.I))}
