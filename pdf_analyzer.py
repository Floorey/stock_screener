import re
import pypdf
from typing import Dict, List, Any, Union

def extract_text_from_pdf(pdf_file) -> List[Dict[str, Any]]:
    """
    Extracts text page-by-page from a PDF file (either file path or file-like object / bytes).
    Returns a list of dictionaries with 'page_number' and 'content'.
    """
    pages_data = []
    
    try:
        reader = pypdf.PdfReader(pdf_file)
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages_data.append({
                    "page_number": i + 1,
                    "content": text
                })
    except Exception as e:
        print(f"Error reading PDF: {e}")
        
    return pages_data

def search_keywords_in_pdf(pages_data: List[Dict[str, Any]], keywords: List[str], context_window: int = 150) -> List[Dict[str, Any]]:
    """
    Searches for keywords in the extracted PDF pages.
    Returns a list of matches with page number, matched keyword, and surrounding context.
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
                # Format snippet to highlight matched word
                matched_text = match.group(0)
                
                matches.append({
                    "page": page_num,
                    "keyword": kw,
                    "matched_text": matched_text,
                    "context": f"... {snippet} ..."
                })
    return matches

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
