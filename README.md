# 3 CANDLE FIX WEB

This is an algorithmic trading application that connects with the Flattrade OMS using the Flattrade Python API.

## Project Structure

- **Strategies:** Includes multi-timeframe strategies (e.g. 5-min breakout, 1-min handling).
- **Backend/Execution:** Automated order placement, position management, and logging.
- **Desktop UI:** A dark-themed PyQt6 interface to view, configure, and monitor ongoing strategies.
- **Authentication:** Automated credential management using `flattradecred.yaml`.

## Setup

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Configure your credentials in `flattradecred.yaml` (or `.env`).
3. Run the application:
   ```bash
   python new_main.py
   ```

## Note

The original documentation for the FLATTRADE Python API can be found in `FLATTRADE_API_README.md`.
