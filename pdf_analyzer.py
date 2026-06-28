import re
import pypdf
from typing import Dict, List, Any, Union
import requests
import lxml.html
import yfinance as yf

def extract_text_from_pdf(pdf_file) -> List[Dict[str, Any]]:
    """
    Extracts text page-by-page from a PDF file (either file path or file-like object / bytes).
    Returns a list of dictionaries with 'page_number' and 'content'.
    """
    pages_data = []
    
    reader = pypdf.PdfReader(pdf_file)
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            pages_data.append({
                "page_number": i + 1,
                "content": text
            })
        
    return pages_data

def detect_report_locale(pages_data: List[Dict[str, Any]]) -> str:
    """
    Scans the document pages for language-specific keywords to detect language/locale.
    Returns 'de' for German or 'en' for English.
    """
    german_keywords = ["und", "der", "die", "umsatz", "jahresüberschuss", "verbindlichkeiten", "bericht", "ergebnis"]
    german_count = 0
    english_keywords = ["and", "the", "revenue", "income", "debt", "report", "earnings", "balance"]
    english_count = 0
    
    sample_text = ""
    for page in pages_data[:5]:  # Look at the first 5 pages for reference
        sample_text += page["content"].lower()
        
    for word in german_keywords:
        german_count += len(re.findall(r'\b' + re.escape(word) + r'\b', sample_text))
    for word in english_keywords:
        english_count += len(re.findall(r'\b' + re.escape(word) + r'\b', sample_text))
        
    return "de" if german_count > english_count else "en"

def search_keywords_in_pdf(pages_data: List[Dict[str, Any]], keywords: List[str], context_window: int = 150) -> List[Dict[str, Any]]:
    """
    Searches for keywords in the extracted PDF pages.
    Returns a list of matches with page number, matched keyword, and surrounding context (with highlighted word).
    """
    matches = []
    for page in pages_data:
        content = page["content"]
        page_num = page["page_number"]
        
        for kw in keywords:
            # Case-insensitive search with regex for word boundaries
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            for match in pattern.finditer(content):
                start = max(0, match.start() - context_window)
                end = min(len(content), match.end() + context_window)
                
                snippet = content[start:end].replace("\n", " ").strip()
                matched_text = match.group(0)
                
                # Create a highlighted context snippet using markdown bold
                # We need to find the match within the snippet to highlight it
                highlight_pattern = re.compile(re.escape(matched_text), re.IGNORECASE)
                highlighted_snippet = highlight_pattern.sub(f" **{matched_text}** ", snippet)
                
                matches.append({
                    "page": page_num,
                    "keyword": kw,
                    "matched_text": matched_text,
                    "context": f"... {highlighted_snippet.strip()} ..."
                })
    return matches

def normalize_value_with_locale(val_str: str, locale: str = "en") -> float:
    """
    Normalizes a financial value string into a float, taking locale formatting into account.
    E.g. '$45,200 million' -> 45,200,000,000.0
         '12.540 Mio. €' -> 12,540,000,000.0
    """
    # Remove currency symbols first
    s = re.sub(r'[$€£¥]', '', val_str).strip()
    
    # Extract the first continuous sequence of digits, signs and separators
    num_match = re.search(r'([-+]?\s*\d[\d.,\s]*)', s)
    if not num_match:
        return 0.0
        
    num_part = num_match.group(0).strip()
    suffix_part = s.replace(num_match.group(0), '').strip().lower()
    
    # Check for suffix multiplier
    multiplier = 1.0
    if any(x in suffix_part for x in ['billion', 'milliarden', 'mrd', 'b']):
        multiplier = 1_000_000_000.0
    elif any(x in suffix_part for x in ['million', 'millionen', 'mio', 'm']):
        multiplier = 1_000_000.0
    elif any(x in suffix_part for x in ['thousand', 'tausend', 'k']):
        multiplier = 1_000.0
        
    # Clean the numeric part based on locale
    # Remove all spaces first
    num_clean = num_part.replace(' ', '')
    
    if locale == "de":
        # German format: 12.540,50 -> dot is thousands, comma is decimal
        if '.' in num_clean and ',' in num_clean:
            num_clean = num_clean.replace('.', '').replace(',', '.')
        elif ',' in num_clean:
            # Check if comma is thousands separator (like US format in German text)
            parts = num_clean.split(',')
            if len(parts[-1]) == 3 and len(parts) > 2:
                num_clean = num_clean.replace(',', '')
            else:
                num_clean = num_clean.replace(',', '.')
        elif '.' in num_clean:
            # Dot is thousands separator if followed by 3 digits
            parts = num_clean.split('.')
            if len(parts[-1]) == 3:
                num_clean = num_clean.replace('.', '')
    else:
        # English format: 12,540.50 -> comma is thousands, dot is decimal
        if ',' in num_clean and '.' in num_clean:
            num_clean = num_clean.replace(',', '')
        elif ',' in num_clean:
            num_clean = num_clean.replace(',', '')
            
    try:
        # Keep only digits, dots and negative sign
        num_clean = re.sub(r'[^\d.-]', '', num_clean)
        return float(num_clean) * multiplier
    except ValueError:
        return 0.0

def scan_for_financial_metrics(pages_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Scans the PDF pages for potential financial statements or figures.
    Uses regex patterns (supporting both English and German) to find key items like Revenue, Net Income, Debt, etc.
    """
    # Key metrics to look for and their common aliases in English and German
    patterns = {
        "Revenue / Umsatz": [
            r"(total)?\s*revenue(s)?", r"net\s*sales", r"total\s*sales",
            r"umsatz(erlöse)?", r"gesamtumsatz", r"erlöse"
        ],
        "Net Income / Konzernergebnis": [
            r"net\s*income", r"net\s*earnings", r"net\s*loss",
            r"jahresüberschuss", r"konzernergebnis", r"konzerngewinn", r"jahresergebnis", r"reingewinn"
        ],
        "Operating Income / EBIT / Betriebsergebnis": [
            r"operating\s*income", r"operating\s*profit", r"operating\s*loss",
            r"ebit", r"betriebsergebnis", r"operatives\s*ergebnis"
        ],
        "Total Debt / Verbindlichkeiten": [
            r"total\s*debt", r"long-term\s*debt", r"short-term\s*debt",
            r"finanzverbindlichkeiten", r"verbindlichkeiten", r"schulden", r"fremdkapital"
        ],
        "Cash Flow": [
            r"cash\s*provided\s*by\s*operating\s*activities", r"operating\s*cash\s*flow", r"free\s*cash\s*flow",
            r"cashflow\s*aus\s*der\s*betrieblichen\s*tätigkeit", r"operativer\s*cashflow", r"freier\s*cashflow"
        ]
    }
    
    findings = {key: [] for key in patterns}
    
    for page in pages_data:
        page_num = page["page_number"]
        lines = page["content"].split("\n")
        
        for line in lines:
            # Look for numbers in the line to filter out headers and explanatory text
            if not any(char.isdigit() for char in line):
                continue
                
            for metric, aliases in patterns.items():
                for alias in aliases:
                    if re.search(alias, line, re.IGNORECASE):
                        findings[metric].append({
                            "page": page_num,
                            "line": line.strip()
                        })
                        break # Only match one alias per line
                        
    return findings

def extract_structured_financials(pages_data: List[Dict[str, Any]], locale: str = "en") -> List[Dict[str, Any]]:
    """
    Extracts structured financial numbers from the pages, pairing them with the correct years.
    Returns a list of dictionaries containing metric name, year, raw value, normalized value in Mio,
    and page/source line details.
    """
    patterns = {
        "Revenue / Umsatz": [
            r"(total)?\s*revenue(s)?", r"net\s*sales", r"total\s*sales",
            r"umsatz(erlöse)?", r"gesamtumsatz", r"erlöse"
        ],
        "Net Income / Konzernergebnis": [
            r"net\s*income", r"net\s*earnings", r"net\s*loss",
            r"jahresüberschuss", r"konzernergebnis", r"konzerngewinn", r"jahresergebnis", r"reingewinn"
        ],
        "Operating Income / EBIT / Betriebsergebnis": [
            r"operating\s*income", r"operating\s*profit", r"operating\s*loss",
            r"ebit", r"betriebsergebnis", r"operatives\s*ergebnis"
        ],
        "Total Debt / Verbindlichkeiten": [
            r"total\s*debt", r"long-term\s*debt", r"short-term\s*debt",
            r"finanzverbindlichkeiten", r"verbindlichkeiten", r"schulden", r"fremdkapital"
        ],
        "Cash Flow": [
            r"cash\s*provided\s*by\s*operating\s*activities", r"operating\s*cash\s*flow", r"free\s*cash\s*flow",
            r"cashflow\s*aus\s*der\s*betrieblichen\s*tätigkeit", r"operativer\s*cashflow", r"freier\s*cashflow"
        ]
    }
    
    extracted_data = []
    year_regex = re.compile(r'\b(20[12]\d)\b')
    value_regex = re.compile(
        r'(?<!\d)(?:[$€£¥]\s*)?\d+(?:[.,\s]\d{3})*(?:[.,]\d+)?\s*(?:billion|million|milliarden|millionen|mrd|mio|thousand|[mbk])?\b',
        re.IGNORECASE
    )
    
    for page in pages_data:
        page_num = page["page_number"]
        lines = page["content"].split("\n")
        
        for line in lines:
            if not any(char.isdigit() for char in line):
                continue
                
            for metric, aliases in patterns.items():
                matched_alias = None
                for alias in aliases:
                    if re.search(alias, line, re.IGNORECASE):
                        matched_alias = alias
                        break
                        
                if matched_alias:
                    years = year_regex.findall(line)
                    raw_values = value_regex.findall(line)
                    
                    # Filter out values that are actually years
                    clean_values = []
                    for val in raw_values:
                        val_strip = val.strip()
                        if val_strip in years:
                            continue
                        if not any(c.isdigit() for c in val_strip):
                            continue
                        clean_values.append(val_strip)
                        
                    pairs = []
                    if len(years) == len(clean_values) and len(years) > 0:
                        pairs = [(int(years[i]), clean_values[i]) for i in range(len(years))]
                    elif len(years) > 0 and len(clean_values) > 0:
                        # Match by order of appearance
                        for i in range(min(len(years), len(clean_values))):
                            pairs.append((int(years[i]), clean_values[i]))
                    elif len(clean_values) > 0:
                        for val in clean_values:
                            pairs.append((None, val))
                            
                    for year, raw_val in pairs:
                        normalized = normalize_value_with_locale(raw_val, locale)
                        extracted_data.append({
                            "Metric": metric,
                            "Year": year,
                            "Raw Value": raw_val,
                            "Value (Mio)": round(normalized / 1_000_000.0, 2),
                            "Normalized Value": normalized,
                            "Page": page_num,
                            "Context": line.strip()
                        })
                    break # Matches one metric type per line
                    
    return extracted_data

def fetch_sec_filings(ticker_symbol: str) -> List[Dict[str, Any]]:
    """
    Fetches the list of SEC filings for a ticker symbol using yfinance.
    Returns a list of dicts with keys 'date', 'type', 'title', 'url'.
    """
    ticker = yf.Ticker(ticker_symbol)
    filings = []
    try:
        raw_filings = ticker.sec_filings
        if raw_filings:
            for f in raw_filings:
                exhibits = f.get("exhibits", {})
                url = None
                ftype = f.get("type", "")
                
                # Prefer the main filing type exhibit (e.g. '10-K' or '10-Q')
                if ftype in exhibits:
                    url = exhibits[ftype]
                elif "10-K" in exhibits:
                    url = exhibits["10-K"]
                elif "10-Q" in exhibits:
                    url = exhibits["10-Q"]
                elif exhibits:
                    url = list(exhibits.values())[0]
                    
                if url:
                    filings.append({
                        "date": str(f.get("date", "N/A")),
                        "type": ftype,
                        "title": f.get("title", ftype),
                        "url": url
                    })
    except Exception:
        pass
    return filings

def download_and_parse_filing(url: str) -> List[Dict[str, Any]]:
    """
    Downloads the HTML filing from the URL, extracts the text content,
    and returns a list of dictionaries with 'page_number' and 'content'
    by chunking the text into pseudo-pages.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    # Parse HTML text
    root = lxml.html.fromstring(response.content)
    text = root.text_content()
    
    # Clean text: remove empty lines and strip whitespace
    lines = [line.strip() for line in text.split("\n")]
    non_empty_lines = [line for line in lines if line]
    
    pages_data = []
    lines_per_page = 60
    for i in range(0, len(non_empty_lines), lines_per_page):
        page_num = (i // lines_per_page) + 1
        page_lines = non_empty_lines[i : i + lines_per_page]
        pages_data.append({
            "page_number": page_num,
            "content": "\n".join(page_lines)
        })
        
    return pages_data
