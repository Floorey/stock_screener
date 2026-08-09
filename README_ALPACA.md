# Alpaca Analyst CLI Tool

A standalone, professional-grade Python CLI tool for interacting with the Alpaca Paper Trading API.

## Prerequisites

1.  **Environment Variables**: Ensure you have a `.env` file in the project root with the following keys:
    ```env
    APCA_API_KEY_ID=your_api_key
    APCA_API_SECRET_KEY=your_api_secret
    APCA_API_BASE_URL=https://paper-api.alpaca.markets
    ```

2.  **Dependencies**: Install the required packages:
    ```bash
    pip install alpaca-py pandas python-dotenv
    ```

## Usage

### Interactive Mode
Launch the interactive shell:
```bash
python alpaca_analyst.py
```

Available commands:
- `status`: Show connection status and current parameters.
- `params <key> <value>`: Update parameters (e.g., `params symbol AAPL`, `params start_date 2023-01-01`).
- `fetch_positions`: Retrieve and display current portfolio positions.
- `fetch_trades`: Retrieve and display trade history based on parameters.
- `export <trades|positions>`: Export the last fetched data to CSV or JSON.
- `help`: Show available commands.
- `exit`: Close the tool.

### Non-Interactive Mode
Run commands directly from the terminal:
```bash
# Fetch and display positions
python alpaca_analyst.py --fetch positions

# Fetch trades for a specific symbol and export to CSV
python alpaca_analyst.py --fetch trades --symbol AAPL --days 60 --export csv
```

## Architecture
- `AlpacaAnalyst`: Handles SDK initialization and core API logic.
- `AlpacaCLI`: Provides the interactive `cmd`-based interface and argument parsing.
- Data is processed as Pandas DataFrames for consistent display and export.
