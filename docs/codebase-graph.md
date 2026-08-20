# Codebase graph

A `graphify` knowledge-graph pass over the repo (40 files, ~87.8k words → 415 nodes, 810 edges, 30 communities). Snapshot from 2026-08-09; raw output in `graphify-out/graph.json` and `graphify-out/GRAPH_REPORT.md`, visual dashboard published at the artifact linked below. Does **not** include `mobile_api.py`, `mcp_gateway/`, `statarb_engine.py`, or `AGENTS.md` — all added after this graph was built; a rebuild was started and cancelled mid-run on 2026-08-20, so this doc still reflects the Aug 9 state rather than today's additions.

Extraction quality: 98% EXTRACTED (explicit in source: imports, calls, citations), 2% INFERRED (15 edges, avg confidence 0.79), 0% AMBIGUOUS-and-kept (1 AMBIGUOUS edge flagged for review, see below).

## The five functions everything routes through

Ranked by edge count — these are the de facto core abstractions, not by design intent but by what the graph actually shows every other module reaching into:

1. `is_alpaca_configured()` — 37 edges. The gate every Alpaca-dependent code path checks before doing anything.
2. `get_positions()` — 25 edges.
3. `render_bloomberg_tab()` — 23 edges. The Bloomberg Terminal screen is a hub, not a leaf.
4. `get_alpaca_credentials()` — 22 edges.
5. `app.py` (Streamlit entrypoint) — 20 edges.

`place_order()`, `get_account_info()`, and `get_alpaca_headers()` round out the top eight — all from `alpaca_trader.py`, confirming it functions as the single source of truth the way `CLAUDE.md` describes it, not just by convention but by measured connectivity.

## Community structure

30 communities total; 22 detailed (≥3 nodes), 6 thin (omitted from graphify's per-community breakdown but still present as graph nodes): Native PCA/K-Means Module, Data Cleaning Script, and the three per-index shortlist scripts (Nasdaq/Russell/S&P 500) plus Track Record Generator — all standalone utilities with no cross-module edges, consistent with `CLAUDE.md`'s description of them as "standalone/offline utilities."

The two largest communities are also the two weakest by cohesion — worth reading together, not as two separate facts:

- **Alpaca Order & Account Management** (52 nodes, cohesion 0.09) and **Bloomberg Terminal & Positions Data** (46 nodes, cohesion 0.08) are both large *and* loosely interconnected. graphify's own suggested questions flag both as candidates for splitting into smaller modules — the size comes from breadth (many order/account operations, many Bloomberg screens) rather than from tight coupling between their members.
- By contrast, small communities cluster tightly: **Dataset Clustering & PCA** (3 nodes, cohesion 0.60) and **TWAP/VWAP Execution Algo** (4 nodes, cohesion 0.29) are small because they *are* small, self-contained units — the cohesion score confirms it rather than just the node count implying it.

## Hyperedges (group relationships, not just pairs)

- **Alpaca Trader as Single Source of Truth** (EXTRACTED, 1.00) — `alpaca_trader.py` plus every module `CLAUDE.md` names as going through it: `risk_manager.py`, `options_ui.py`, `cashflow_ui.py`, `performance_ui.py`, `pairs_tracker.py`, `market_hedger.py`, `execution_algo.py`, `trade_strategy_runner.py`. The graph independently confirms the architecture doc's claim.
- **FastMCP-based MCP Server Layer** (EXTRACTED, 1.00) — `mcp_server.py`, `falcone_server.py`, `alpaca_trader.py`.
- **PDF Report Generation via reportlab** (INFERRED, 0.85) — `report_generator.py`, `generate_macro_reports.py`, `risk_manager.py`, and the `reportlab` requirement itself as a node.

## Surprising connections

The one edge graphify flagged as genuinely uncertain: `Falcone Capital (Trading Terminal Branding)` and `BlackGate Capital (Report Branding)` came back `semantically_similar_to` at AMBIGUOUS confidence, sourced from `CLAUDE.md` → `reports/risk_report_20260624_133605.pdf`. Both names appear in the repo for what looks like the same branding concept — worth a human check on whether that's an intentional rename in progress or two names that should be reconciled.

The other four INFERRED edges are lower-stakes: `README.md`'s feature descriptions (interactive dashboard, index scraper, Alpaca integration) each matched their implementing module (`app.py`, `screener.py`, `alpaca_trader.py`) at 0.65-0.85 confidence — expected given `README.md` and `CLAUDE.md` describe the same modules from different angles, not two independent discoveries.

## Known gaps

35 nodes have ≤1 connection, including `report_generator.py`, `generate_macro_reports.py`, `bloomberg_ui.py`, and `watchlist_manager.py` — either genuinely standalone or under-documented in a way that hides their real connections from a structural/semantic extraction pass. Not necessarily a problem, but a reasonable checklist if the next `graphify` rebuild is meant to also tighten documentation.

## Full interactive breakdown

Published as an artifact: **Codebase Graph** — https://claude.ai/code/artifact/08bfc8ff-8963-491f-82f7-2c9c1f5b9af6 (all god nodes, all 22 detailed communities, hyperedges, surprising connections, and graphify's suggested follow-up questions, in one dashboard).
