import re
import unidecode

def clean_title(title):
    """Convert book title to SEO-friendly format"""
    if not title:
        return ""
    title = str(title)
    title = unidecode.unidecode(title)
    title = title.lower()
    title = re.sub(r'[^\w\s-]', '', title)
    title = re.sub(r'[\s]+', '-', title)
    title = re.sub(r'-+', '-', title)
    title = title.strip('-')
    return title if title else ""

def format_stt(stt):
    """Format STT to 3-digit string"""
    if not stt or stt == '':
        return "000"
    stt = str(stt).strip()
    return f"{int(stt):03d}" if stt.isdigit() else stt
