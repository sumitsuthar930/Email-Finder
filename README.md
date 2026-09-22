```text
 _____                 _ _   _____ _           _           
| ____|_ __ ___   __ _(_) | |  ___(_)_ __   __| | ___ _ __ 
|  _| | '_ ` _ \ / _` | | | | |_  | | '_ \ / _` |/ _ \ '__|
| |___| | | | | | (_| | | | |  _| | | | | | (_| |  __/ |   
|_____|_| |_| |_|\__,_|_|_| |_|   |_|_| |_|\__,_|\___|_|   

        PUBLIC CONTACT EMAIL FINDER // GUI EDITION
```

# Email Finder

A Python-based GUI tool for discovering public contact emails using Google search results via the Serper.dev API.

This project searches target keywords, extracts email addresses from search result snippets, and optionally deep-scans PDFs for email addresses found in public documents.

## Features

- GUI interface built with Tkinter
- Google search integration through Serper.dev
- Email extraction from search-result titles and snippets
- Optional PDF deep-scan support
- CSV export
- Copy discovered emails to the clipboard
- Search pagination with stop/cancel support

## Requirements

- Python 3.8 or newer
- A Serper.dev API key
- Tkinter, usually included with standard Python installations

## Cloning Process

Clone the repository and move into the project directory:

```bash
git clone https://github.com/sumitsuthar930/Email-Finder.git
cd Email-Finder
```

### Create a virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

Linux/macOS:

```bash
python3 -m venv venv
source venv/bin/activate
```

### Install dependencies

```bash
pip install requests python-dotenv pypdf
```

`pypdf` is optional. Install it to enable the **DEEP-SCAN PDFs** feature.

## Configuration

Create a file named `.env` in the same directory as `Email-Finder.py`:

```env
SERPER_API_KEY=your_api_key_here
```

Get an API key from [Serper.dev](https://serper.dev).

Do not commit your `.env` file or expose your API key publicly.

## Run the Tool

```bash
python Email-Finder.py
```

On some Linux/macOS systems, use:

```bash
python3 Email-Finder.py
```

Enter a search query, select the number of result pages, and click **RUN SEARCH**. Results can be copied or exported as a CSV file.

## How It Works

1. The application loads `SERPER_API_KEY` from `.env`.
2. It sends the search query to Serper.dev.
3. Email addresses are extracted from result titles and snippets.
4. If PDF deep scanning is enabled, public PDF results are downloaded and scanned for additional text-based email addresses.
5. Results are deduplicated and displayed in the GUI.

## Ethical and Legal Use

Use this tool only for lawful, ethical research and public-contact discovery. Respect privacy, website terms of service, applicable laws, and anti-spam regulations. Do not use discovered addresses for unsolicited messages, harassment, or abuse.

## Project Files

- `Email-Finder.py` — main GUI application
- `README.md` — setup and usage documentation
- `.env` — local API-key configuration; keep this file private

## License

This project is provided as-is for educational and research purposes.
