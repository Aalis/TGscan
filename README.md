# TGscan - Telegram Channel Scanner

A web-based tool for scanning and analyzing Telegram channels, built with FastAPI and Telethon.

## Features

- Parse channel members with filtering options:
  - Premium users
  - Users with phone numbers
  - Last seen status
  - Gender filter
- Parse channel comments with:
  - Unique user collection
  - Comment history
  - User activity tracking
- Modern web interface with progress tracking
- Export results functionality

## Prerequisites

- Python 3.8 or higher
- Telegram API credentials (API_ID and API_HASH)
- Bot Token from @BotFather

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Aalis/TGscan.git
cd TGscan
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root and add your Telegram credentials:
```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
```

## Usage

1. Start the server:
```bash
uvicorn main:app --reload
```

2. Open your browser and navigate to:
```
http://localhost:8000
```

3. Use the web interface to:
   - Parse channel members
   - Collect comment history
   - Export results

## Project Structure

```
TGscan/
├── main.py              # Main FastAPI application
├── templates/           # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── parse.html
│   └── comments.html
├── static/             # Static files (CSS, JS)
├── requirements.txt    # Project dependencies
└── .env               # Environment variables
```

## Security Notes

- Never commit your `.env` file or any sensitive credentials
- Keep your session files private
- Use virtual environment for dependencies

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [Telethon](https://github.com/LonamiWebs/Telethon) for the Telegram client
- [FastAPI](https://fastapi.tiangolo.com/) for the web framework 