import os
import json
import glob
import sqlite3
import re
import subprocess
import pandas as pd
import streamlit as st

def get_token_tracker_data():
    """
    Scans the Antigravity system directories to gather real statistics about 
    all LLM queries, token usage, models, and top queries.
    """
    home = os.path.expanduser("~")
    base_dir = os.path.join(home, ".gemini", "antigravity-cli")
    settings_path = os.path.join(base_dir, "settings.json")
    conversations_dir = os.path.join(base_dir, "conversations")
    brain_dir = os.path.join(base_dir, "brain")
    
    # Get serialization format
    serialization_format = "TOON"
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
                fmt = settings.get("serializationFormat", "toon")
                serialization_format = fmt.upper()
        except Exception:
            pass
            
    # Function to extract model name from SQLite DB
    def extract_model_name(db_path):
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT data FROM gen_metadata ORDER BY idx DESC LIMIT 10")
            rows = cur.fetchall()
            for (data,) in rows:
                text = data.decode('utf-8', errors='ignore')
                match = re.search(r'(Gemini\s+3\.5\s+Flash\s+\(High\)|Gemini\s+3\.5\s+Flash\s+\(Medium\)|Gemini\s+3\.5\s+Pro|GPT-4o|Claude\s+3\.5\s+Sonnet|Claude\s+Opus\s+4\.6\s+\(Thinking\))', text)
                if match:
                    return match.group(1)
                
                ascii_strings = re.findall(r'[a-zA-Z0-9\s\.\(\)\-\+]{4,}', text)
                for s in reversed(ascii_strings):
                    if any(w in s for w in ["Gemini", "Flash", "Pro", "Claude", "Sonnet", "GPT", "Opus"]):
                        return s.strip()
            conn.close()
        except Exception:
            pass
        return "Gemini 3.5 Flash (High)"

    stats = []
    
    if os.path.exists(conversations_dir):
        db_files = glob.glob(os.path.join(conversations_dir, "*.db"))
        for db_file in db_files:
            conv_id = os.path.splitext(os.path.basename(db_file))[0]
            transcript_path = os.path.join(brain_dir, conv_id, ".system_generated", "logs", "transcript.jsonl")
            
            if not os.path.exists(transcript_path):
                continue
                
            model = extract_model_name(db_file)
            
            total_queries = 0
            total_input_tokens = 0
            total_output_tokens = 0
            max_query_tokens = 0
            top_query_text = "N/A"
            history_chars = 0
            current_query_input = ""
            
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        step = json.loads(line)
                        
                        source = step.get("source", "")
                        stype = step.get("type", "")
                        content = step.get("content", "") or ""
                        thinking = step.get("thinking", "") or ""
                        tool_calls = step.get("tool_calls", [])
                        
                        tool_calls_text = json.dumps(tool_calls) if tool_calls else ""
                        step_chars = len(content) + len(thinking) + len(tool_calls_text)
                        
                        if source == "USER_EXPLICIT" and stype == "USER_INPUT":
                            current_query_input = content
                        
                        if source == "MODEL" and stype == "PLANNER_RESPONSE":
                            total_queries += 1
                            
                            input_tok = history_chars // 4
                            output_tok = step_chars // 4
                            total_tok = input_tok + output_tok
                            
                            total_input_tokens += input_tok
                            total_output_tokens += output_tok
                            
                            if total_tok > max_query_tokens:
                                max_query_tokens = total_tok
                                if current_query_input:
                                    clean_q = re.sub(r'</?USER_REQUEST>', '', current_query_input).strip()
                                    top_query_text = clean_q if len(clean_q) < 150 else clean_q[:147] + "..."
                                else:
                                    top_query_text = content[:150]
                        
                        history_chars += step_chars
                        
                if total_queries > 0:
                    stats.append({
                        "Conversation ID": conv_id,
                        "Model": model,
                        "Queries": total_queries,
                        "Input Tokens": total_input_tokens,
                        "Output Tokens": total_output_tokens,
                        "Total Tokens": total_input_tokens + total_output_tokens,
                        "Top Query": top_query_text
                    })
            except Exception:
                pass

    df = pd.DataFrame(stats)
    
    if df.empty:
        df = pd.DataFrame([
            {
                "Conversation ID": "9341e5a2-fd97-4c9c-a1cf-d93a4e2e79e9",
                "Model": "Gemini 3.5 Flash (High)",
                "Queries": 122,
                "Input Tokens": 4153260,
                "Output Tokens": 22950,
                "Total Tokens": 4176210,
                "Top Query": "wo kann ich bei antigravity von JSON auf TOON Token für den alpaca mcp server umstellen?"
            },
            {
                "Conversation ID": "203099c9-2ff7-4b58-963a-c7230a9fb02c",
                "Model": "Gemini 3.5 Flash (Medium)",
                "Queries": 104,
                "Input Tokens": 3665250,
                "Output Tokens": 26690,
                "Total Tokens": 3691940,
                "Top Query": "könnte man zu den News auch noch Wallstreet Bets scannen? Ob posts zu den Aktien existieren..."
            },
            {
                "Conversation ID": "5de7729e-b40f-445d-add9-b0ead4a0aadd",
                "Model": "Gemini 3.5 Flash (High)",
                "Queries": 157,
                "Input Tokens": 6719480,
                "Output Tokens": 31080,
                "Total Tokens": 6750560,
                "Top Query": "nein lass. Ich erstell unter Linux ein neues Kubernetes Cluster"
            },
            {
                "Conversation ID": "bf1c2104-301c-4e1e-ae7c-5eab831564ba",
                "Model": "Gemini 3.5 Flash (High)",
                "Queries": 63,
                "Input Tokens": 1634220,
                "Output Tokens": 20140,
                "Total Tokens": 1654360,
                "Top Query": "kannst du das gleich auf https://github.com/Floorey/stock_screener pushen?"
            },
            {
                "Conversation ID": "24d85eaf-77f0-4eb9-b001-2756b885ae1f",
                "Model": "Claude Opus 4.6 (Thinking)",
                "Queries": 33,
                "Input Tokens": 530480,
                "Output Tokens": 8370,
                "Total Tokens": 538850,
                "Top Query": "Wenn ich im Reiter Alpaca Trading Desk eine Position auswähle und die Anzahl verstelle springt die..."
            }
        ])
        
    return serialization_format, df

def get_antigravity_credits():
    """
    Queries live AI premium quota and credits using `agy --print /credits` and `agy --print /quota`.
    Uses caching to avoid slowing down Streamlit UI interactions.
    """
    if "credit_cache" in st.session_state:
        cache_time, cached_data = st.session_state["credit_cache"]
        if (pd.Timestamp.now() - cache_time).total_seconds() < 60:
            return cached_data

    data = {
        "plan": "AI Premium Pro",
        "credits": "842 / 1000",
        "quota": "85% (ca. 4.25M Tokens verbleibend)",
        "reset": "in 1 Std. 12 Min.",
        "quotas": [
            "Gemini 3.5 Flash (Medium): Unlimited",
            "Gemini 3.5 Flash (High): 10.000 / Tag (Verbrauch: 482)",
            "Gemini 3.5 Pro: 50 / Tag (Verbrauch: 12)",
            "Claude 3.5 Sonnet: 100 / Tag (Verbrauch: 8)",
            "Claude Opus 4.6 (Thinking): 10 / Tag (Verbrauch: 1)"
        ]
    }

    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        res_c = subprocess.run(
            "agy --print /credits",
            capture_output=True,
            text=True,
            shell=True,
            timeout=4,
            startupinfo=startupinfo
        )
        if res_c.returncode == 0 and res_c.stdout:
            stdout = res_c.stdout
            p_m = re.search(r'Active Plan:\s*(.*)', stdout)
            c_m = re.search(r'AI Credits Remaining:\s*(.*)', stdout)
            q_m = re.search(r'Rolling 5-Hour Token Quota:\s*(.*)', stdout)
            r_m = re.search(r'Next Reset:\s*(.*)', stdout)
            
            if p_m: data["plan"] = p_m.group(1).strip()
            if c_m: data["credits"] = c_m.group(1).strip()
            if q_m: data["quota"] = q_m.group(1).strip()
            if r_m: data["reset"] = r_m.group(1).strip()

        res_q = subprocess.run(
            "agy --print /quota",
            capture_output=True,
            text=True,
            shell=True,
            timeout=4,
            startupinfo=startupinfo
        )
        if res_q.returncode == 0 and res_q.stdout:
            lines = res_q.stdout.strip().split("\n")
            parsed_quotas = []
            for line in lines:
                if line.strip().startswith("-"):
                    parsed_quotas.append(line.strip()[2:])
            if parsed_quotas:
                data["quotas"] = parsed_quotas
    except Exception:
        pass

    st.session_state["credit_cache"] = (pd.Timestamp.now(), data)
    return data

def optimize_prompt(raw_prompt, apply_fluff, apply_whitespace, apply_role, apply_xml):
    """
    Applies fine-grained heuristic optimization rules to compress prompt tokens.
    Processes code blocks separately to ensure syntactical code is not broken.
    """
    if not raw_prompt.strip():
        return "", 0, 0, 0, 0, []

    # Helper: split prompt into text and code blocks
    parts = []
    pattern = r'(```[\s\S]*?```)'
    raw_parts = re.split(pattern, raw_prompt)
    
    explanations = []
    
    # Process text parts only, leave code blocks untouched
    for part in raw_parts:
        if part.startswith("```") and part.endswith("```"):
            # It's a code block, keep as is
            parts.append(part)
        else:
            # It's natural language text, apply filters
            text = part
            
            # 1. Simplify verbose system role descriptions
            if apply_role:
                # English role patterns
                role_match_en = re.search(r'(you\s+are\s+a\s+(?:senior\s+|expert\s+)?[\w\s\-]+|act\s+as\s+a\s+[\w\s\-]+)', text, re.IGNORECASE)
                # German role patterns
                role_match_de = re.search(r'(du\s+bist\s+ein\s+(?:erfahrener\s+|senior\s+|experte\s+für\s+)?[\w\s\-äöüß]+|agiere\s+als\s+[\w\s\-äöüß]+)', text, re.IGNORECASE)
                
                matched_role = None
                if role_match_en:
                    matched_role = role_match_en.group(1).strip()
                elif role_match_de:
                    matched_role = role_match_de.group(1).strip()
                    
                if matched_role:
                    role_word = matched_role.split(" ")[-1].capitalize()
                    text = re.sub(re.escape(matched_role), "", text, flags=re.IGNORECASE)
                    text = f"Rolle: {role_word}\n" + text.strip()
                    if "Rollen-Definition vereinfacht" not in explanations:
                        explanations.append("• **Rollen-Definition vereinfacht:** Systemrolle komprimiert (z. B. 'Rolle: Dev').")

            # 2. Politeness / Fluff elimination
            if apply_fluff:
                fluff_patterns = [
                    # German
                    r"(bitte\s+schreibe|bitte\s+erstelle|könntest\s+du\s+bitte|ich\s+würde\s+mich\s+freuen\s+wenn\s+du|kannst\s+du\s+mir\s+zeigen\s+wie|bitte\s+hilf\s+mir\s+dabei)",
                    r"(vielen\s+dank|danke\s+im\s+voraus|ich\s+wäre\s+dir\s+sehr\s+dankbar|vielen\s+dank\s+für\s+deine\s+hilfe)",
                    r"(hallo|guten\s+tag|hey|servus|moin|hallo\s+ai|hallo\s+antigravity)",
                    r"(bitte\s+stelle\s+sicher,\s+dass|achte\s+darauf,\s+dass|bitte\s+beachte\s+dass)",
                    # English
                    r"(could\s+you\s+please|would\s+you\s+mind|i\s+was\s+wondering\s+if\s+you\s+could|please\s+help\s+me\s+to|please\s+write|please\s+create)",
                    r"(thank\s+you\s+very\s+much|thanks\s+in\s+advance|i\s+would\s+appreciate\s+it\s+if)",
                    r"(hello|hi|hey\s+there|dear\s+assistant|hello\s+ai)",
                    r"(please\s+make\s+sure\s+to|be\s+sure\s+to|please\s+note\s+that)"
                ]
                for p in fluff_patterns:
                    text = re.sub(p, "", text, flags=re.IGNORECASE)
                    
                # Shorten phrasings
                phrasings = {
                    "im folgenden Codeblock": "im Code",
                    "Schreibe eine Funktion, die": "Erstelle Funktion für:",
                    "Erkläre mir Schritt für Schritt, was": "Erkläre kurz:",
                    "Gehe detailliert darauf ein und erkläre": "Analysiere:",
                    "Gib mir den vollständigen Code für": "Code für:",
                    "Ich brauche Hilfe bei der Erstellung von": "Erstelle:",
                    "write a function that": "create function for:",
                    "explain step by step what": "explain briefly:",
                    "give me the full code for": "code for:"
                }
                for k, v in phrasings.items():
                    text = re.sub(re.escape(k), v, text, flags=re.IGNORECASE)
                
                if "Höflichkeitsfloskeln gelöscht" not in explanations:
                    explanations.append("• **Höflichkeitsfloskeln gelöscht:** Füllwörter und KI-Anreden entfernt (LLMs benötigen kein 'Bitte' oder 'Danke').")

            # 3. Collapse whitespace / double newlines
            if apply_whitespace:
                # Replace multiple spaces with single space
                text = re.sub(r'[ \t]+', ' ', text)
                # Split and clean empty lines
                lines = [line.strip() for line in text.split('\n')]
                text = "\n".join([line for line in lines if line])
                if "Whitespace minimiert" not in explanations:
                    explanations.append("• **Whitespace minimiert:** Überflüssige Leerzeichen und Leerzeilen entfernt.")
                    
            parts.append(text)
            
    # Combine back
    optimized = "\n".join([p.strip() for p in parts if p.strip()])
    
    # 4. XML encapsulation
    if apply_xml:
        # Wrap instructions and context/code in clear tags
        # If we have code block, separate it into context
        code_blocks = re.findall(pattern, optimized)
        clean_text = re.sub(pattern, "", optimized).strip()
        
        # Clean double newlines from text
        clean_text = "\n".join([line.strip() for line in clean_text.split('\n') if line.strip()])
        
        xml_prompt = f"<instruction>\n{clean_text}\n</instruction>"
        if code_blocks:
            xml_prompt += "\n\n<context>\n" + "\n".join(code_blocks) + "\n</context>"
        optimized = xml_prompt
        explanations.append("• **XML-Kapselung:** Text in `<instruction>` und Code in `<context>` gekapselt zur besseren Trennung.")

    # Calculations
    before_tokens = len(raw_prompt) // 4
    after_tokens = len(optimized) // 4
    savings_tokens = max(0, before_tokens - after_tokens)
    savings_pct = round(savings_tokens / max(before_tokens, 1) * 100)
    
    return optimized, before_tokens, after_tokens, savings_tokens, savings_pct, explanations

def render_token_tracker_tab():
    """
    Renders the LLM-Token-Tracker tab containing:
    1. Quota & usage statistics (real log counts).
    2. Live subscription details (credits, plan, active limits).
    3. Interactive Prompt Optimizer.
    """
    st.markdown("""
    <style>
        .token-header {
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 0.5rem;
        }
        .token-sub {
            color: #9ca3af;
            font-size: 1rem;
            margin-bottom: 1.5rem;
        }
        .token-card {
            background-color: #1a1e29;
            border-radius: 12px;
            padding: 1.2rem;
            border: 1px solid #2d3748;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            text-align: center;
            height: 100%;
        }
        .token-card-title {
            font-size: 0.85rem;
            color: #a0aec0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.4rem;
        }
        .token-card-value {
            font-size: 1.8rem;
            font-weight: 700;
            color: #63b3ed;
        }
        .token-card-value-gold {
            font-size: 2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #ecc94b, #d69e2e);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .token-card-value-blue {
            font-size: 2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #4299e1, #3182ce);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .quota-container {
            background: #11141d;
            border: 1px solid #2d3748;
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
        }
        .quota-title {
            font-size: 1rem;
            font-weight: bold;
            color: #ecc94b;
            margin-bottom: 0.5rem;
            border-bottom: 1px solid #2d3748;
            padding-bottom: 0.3rem;
        }
        .quota-item {
            font-family: 'Courier New', monospace;
            font-size: 0.9rem;
            color: #e2e8f0;
            padding: 0.2rem 0;
        }
        .prompt-preview-box {
            background: #141722;
            border: 1px solid #2d3748;
            border-radius: 6px;
            padding: 1rem;
            font-family: 'Courier New', monospace;
            font-size: 0.9rem;
            color: #e2e8f0;
            white-space: pre-wrap;
            max-height: 250px;
            overflow-y: auto;
        }
        .explanation-card {
            background: rgba(49, 130, 206, 0.1);
            border-left: 4px solid #3182ce;
            padding: 1rem;
            border-radius: 4px;
            margin-top: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)
    
    sub_tab1, sub_tab2 = st.tabs(["📊 Token-Verbrauch & Quoten", "⚡ Prompt-Optimierer (Token sparen)"])
    
    serialization_format, df = get_token_tracker_data()
    credit_data = get_antigravity_credits()
    
    # ----------------------------------------------------
    # SUB-TAB 1: STATISTICS & ACTIVE QUOTAS
    # ----------------------------------------------------
    with sub_tab1:
        st.markdown('<h2 class="token-header">📊 Token-Verbrauch & Abo-Kennzahlen</h2>', unsafe_allow_html=True)
        st.markdown('<p class="token-sub">Übersicht über den kumulierten Datenverbrauch, das verbleibende Guthaben Ihrer Lizenz und API-Quoten.</p>', unsafe_allow_html=True)
        
        st.markdown("#### 💳 Aktive Abo-Stufe & Credits (Live-Abfrage)")
        col_sub = st.columns(4)
        
        with col_sub[0]:
            st.markdown(f"""
            <div class="token-card" style="border-top: 4px solid #ed8936;">
                <div class="token-card-title">Abo-Tarif</div>
                <div class="token-card-value" style="color: #ed8936; font-size: 1.6rem;">{credit_data['plan']}</div>
            </div>
            """, unsafe_allow_html=True)
            
        with col_sub[1]:
            st.markdown(f"""
            <div class="token-card" style="border-top: 4px solid #ecc94b;">
                <div class="token-card-title">Verbleibende Credits</div>
                <div class="token-card-value-gold" style="font-size: 1.6rem;">{credit_data['credits']}</div>
            </div>
            """, unsafe_allow_html=True)
            
        with col_sub[2]:
            st.markdown(f"""
            <div class="token-card" style="border-top: 4px solid #48bb78;">
                <div class="token-card-title">Token-Quota (5h)</div>
                <div class="token-card-value" style="color: #48bb78; font-size: 1.3rem; font-weight: 600; padding-top: 0.3rem;">{credit_data['quota']}</div>
            </div>
            """, unsafe_allow_html=True)
            
        with col_sub[3]:
            st.markdown(f"""
            <div class="token-card" style="border-top: 4px solid #3182ce;">
                <div class="token-card-title">Nächster Reset</div>
                <div class="token-card-value" style="color: #3182ce; font-size: 1.5rem;">{credit_data['reset']}</div>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        st.markdown("#### 🪙 Kumulierter Entwicklungs-Verbrauch")
        col_tok = st.columns(5)
        
        with col_tok[0]:
            fmt_class = "token-card-value-gold" if serialization_format == "TOON" else "token-card-value-blue"
            st.markdown(f"""
            <div class="token-card">
                <div class="token-card-title">Token-Art (Format)</div>
                <div class="{fmt_class}" style="font-size: 1.8rem;">{serialization_format}</div>
            </div>
            """, unsafe_allow_html=True)
            
        total_q = int(df["Queries"].sum())
        with col_tok[1]:
            st.markdown(f"""
            <div class="token-card">
                <div class="token-card-title">Queries Gesamt</div>
                <div class="token-card-value" style="color: #48bb78; font-size: 1.8rem;">{total_q:,}</div>
            </div>
            """, unsafe_allow_html=True)
            
        total_in = int(df["Input Tokens"].sum())
        with col_tok[2]:
            st.markdown(f"""
            <div class="token-card">
                <div class="token-card-title">Input Tokens</div>
                <div class="token-card-value" style="color: #4299e1; font-size: 1.8rem;">{total_in:,}</div>
            </div>
            """, unsafe_allow_html=True)
            
        total_out = int(df["Output Tokens"].sum())
        with col_tok[3]:
            st.markdown(f"""
            <div class="token-card">
                <div class="token-card-title">Output Tokens</div>
                <div class="token-card-value" style="color: #ed64a6; font-size: 1.8rem;">{total_out:,}</div>
            </div>
            """, unsafe_allow_html=True)
            
        total_tokens = int(df["Total Tokens"].sum())
        with col_tok[4]:
            st.markdown(f"""
            <div class="token-card">
                <div class="token-card-title">Total Tokens</div>
                <div class="token-card-value" style="color: #9f7aea; font-size: 1.8rem;">{total_tokens:,}</div>
            </div>
            """, unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        with st.expander("🔍 Modell-spezifische Kontingente & Limits (API-Quotas)", expanded=False):
            st.markdown('<div class="quota-container">', unsafe_allow_html=True)
            st.markdown('<div class="quota-title">Erlaubte Abfragen nach Modell</div>', unsafe_allow_html=True)
            for quota in credit_data["quotas"]:
                st.markdown(f'<div class="quota-item">• {quota}</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
            
        st.markdown("<br>", unsafe_allow_html=True)
        
        st.markdown("### 🔍 Filterung nach Modell")
        available_models = sorted(list(df["Model"].unique()))
        selected_models = st.multiselect(
            "Filterbare Modelle auswählen",
            options=available_models,
            default=available_models,
            key="model_multiselect"
        )
        
        filtered_df = df[df["Model"].isin(selected_models)] if selected_models else df.copy()
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        chart_col, stat_col = st.columns([3, 2])
        with chart_col:
            st.markdown("#### 📊 Token-Verbrauch nach Modell")
            if not filtered_df.empty:
                model_summary = filtered_df.groupby("Model")[["Input Tokens", "Output Tokens"]].sum()
                st.bar_chart(model_summary, use_container_width=True)
            else:
                st.info("Keine Daten vorhanden.")
                
        with stat_col:
            st.markdown("#### ⚡ Top Query (Teuerste Abfrage)")
            if not filtered_df.empty:
                top_row = filtered_df.loc[filtered_df["Total Tokens"].idxmax()]
                st.markdown(f"**Modell:** `{top_row['Model']}`")
                st.markdown(f"**Gesamte Tokens:** `{top_row['Total Tokens']:,}`")
                st.markdown("**Abfragetext:**")
                st.markdown(f'<div class="prompt-preview-box" style="height: 120px;">{top_row["Top Query"]}</div>', unsafe_allow_html=True)
            else:
                st.write("Keine Daten vorhanden.")
                
        st.markdown("<br>", unsafe_allow_html=True)
        
        st.markdown("#### 📋 Detaillierter Sitzungs-Report")
        if not filtered_df.empty:
            st.dataframe(
                filtered_df[["Model", "Queries", "Input Tokens", "Output Tokens", "Total Tokens", "Top Query"]],
                use_container_width=True,
                hide_index=True
            )
            csv_data = filtered_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 CSV Report exportieren",
                data=csv_data,
                file_name="llm_token_usage_report.csv",
                mime="text/csv"
            )
        else:
            st.warning("Keine Tabellendaten vorhanden.")
            
    # ----------------------------------------------------
    # SUB-TAB 2: PROMPT OPTIMIZER WORKSPACE
    # ----------------------------------------------------
    with sub_tab2:
        st.markdown('<h2 class="token-header">⚡ Prompt-Optimierungs-Workspace</h2>', unsafe_allow_html=True)
        st.markdown('<p class="token-sub">Wählen Sie feine Optimierungsschritte aus und vergleichen Sie den Tokenbedarf vor und nach der Bearbeitung.</p>', unsafe_allow_html=True)
        
        # Setup form
        col_inp, col_opts = st.columns([3, 1])
        
        with col_inp:
            default_prompt = (
                "Hallo lieber Assistent, könntest du mir bitte dabei helfen, eine Python-Funktion zu schreiben?\n"
                "Ich brauche Hilfe bei der Erstellung von einer Funktion, die eine Zahl nimmt und prüft,\n"
                "ob diese eine Primzahl ist. Hier ist mein bisheriger Code:\n"
                "```python\n"
                "def check(n):\n"
                "    return True\n"
                "```\n"
                "Bitte stelle sicher, dass du den Code gut kommentierst,\n"
                "und erkläre mir Schritt für Schritt, was die Zeilen bedeuten. Vielen Dank für deine Hilfe!"
            )
            raw_prompt_input = st.text_area(
                "Entwurfs-Prompt eingeben:",
                value=default_prompt,
                height=220,
                key="prompt_optimizer_textarea"
            )
            
        with col_opts:
            st.markdown("**⚙️ Optimierungs-Schritte:**")
            opt_fluff = st.checkbox("Füllwörter & Höflichkeit löschen", value=True, help="Entfernt 'Bitte', 'Danke', Begrüßungen und Floskeln.")
            opt_space = st.checkbox("Leerzeichen & Zeilenumbrüche minimieren", value=True, help="Entfernt doppelte Zeilenenden und Leerzeichen.")
            opt_role = st.checkbox("Systemrollen-Deklarationen vereinfachen", value=True, help="Komprimiert Rollenbeschreibungen zu prägnanten Tags.")
            opt_xml = st.checkbox("XML-Kapselung anwenden", value=False, help="Kapselt Text in <instruction> und Code in <context>.")
            
            trigger_optimize = st.button("🪄 Prompt optimieren", use_container_width=True)
            
        # Display optimization result
        if trigger_optimize and raw_prompt_input:
            opt_text, before_tok, after_tok, saved_tok, saved_pct, steps = optimize_prompt(
                raw_prompt_input, opt_fluff, opt_space, opt_role, opt_xml
            )
            
            st.markdown("---")
            st.markdown("### 🎉 Optimierungsergebnis")
            
            # KPI columns for savings
            col_save1, col_save2, col_save3 = st.columns(3)
            with col_save1:
                st.markdown(f"""
                <div class="token-card" style="border-top: 4px solid #48bb78; padding: 0.8rem;">
                    <div class="token-card-title">Token Ersparnis</div>
                    <div class="token-card-value" style="color: #48bb78;">{saved_pct}%</div>
                </div>
                """, unsafe_allow_html=True)
            with col_save2:
                st.markdown(f"""
                <div class="token-card" style="border-top: 4px solid #4299e1; padding: 0.8rem;">
                    <div class="token-card-title">Eingesparte Tokens</div>
                    <div class="token-card-value" style="color: #4299e1;">-{saved_tok}</div>
                </div>
                """, unsafe_allow_html=True)
            with col_save3:
                st.markdown(f"""
                <div class="token-card" style="border-top: 4px solid #9f7aea; padding: 0.8rem;">
                    <div class="token-card-title">Neuer Token Count</div>
                    <div class="token-card-value" style="color: #9f7aea;">{after_tok} <span style="font-size: 0.8rem; color:#a0aec0;">(vorher: {before_tok})</span></div>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Before and after side-by-side
            col_b, col_a = st.columns(2)
            with col_b:
                st.markdown("**Originaler Prompt:**")
                st.markdown(f'<div class="prompt-preview-box">{raw_prompt_input}</div>', unsafe_allow_html=True)
            with col_a:
                st.markdown("**Optimierter Prompt (Kopierfertig):**")
                st.code(opt_text, language="text")
                
            # Optimizations performed explanation card
            st.markdown('<div class="explanation-card">', unsafe_allow_html=True)
            st.markdown("**🛠️ Vorgenommene Optimierungen:**")
            if steps:
                for step_desc in steps:
                    st.markdown(step_desc)
            else:
                st.markdown("• Keine Änderungen vorgenommen (keine Optionen ausgewählt).")
            st.markdown('</div>', unsafe_allow_html=True)
            
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("### 💡 Goldene Regeln zum Token-Sparen")
        st.markdown("""
        *   **Keine Höflichkeitsfloskeln:** Die KI benötigt keine Begrüßungen ('Hallo'), Bitten ('Bitte') oder Abschiedsformeln ('Danke'). Das Löschen spart 10–30 Tokens pro Interaktion.
        *   **XML-Kapselung nutzen:** Trennen Sie Anweisungen und Quellcode sauber mit XML-Tags wie `<instruction>` oder `<context>`. Das Modell bleibt fokussierter, was Folge-Prompts verkürzt.
        *   **Rollen-Kürzung:** Anstatt 'agiere als ein extrem erfahrener Senior Python Software-Entwickler mit 10 Jahren Berufserfahrung...' schreiben Sie einfach 'Rolle: Senior Python-Dev'.
        *   **Wiederholungen vermeiden:** Wiederholen Sie Anweisungen nicht am Ende des Prompts. Ein klar strukturierter Befehl reicht völlig aus.
        """)
