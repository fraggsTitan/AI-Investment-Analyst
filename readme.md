# AI Investment Analyst (Startup Funding RAG)

A **Retrieval-Augmented Generation (RAG)** system for startup funding data.  
It scrapes investment news, filings and reports, indexes the text with FAISS, and
exposes a simple FastAPI service that answers investor queries using an
LLM (Ollama) with live context.

> The project includes both ingestion scrapers and the RAG API server.  
> It's designed for data exploration, research and prototype tooling, not
> production finance advice.

---

## 🔍 Features

- **Data ingestion** via web scrapers
  - one‑off bulk loader (`master_scraper.py`) pulling CSVs, PDFs, headlines
  - continuous/daemon scraper (`dynamic_scraper.py`) polling RSS, news sites,
    GrowthList, etc., with deduplication
- **RAG API** built with FastAPI
  - `/ingest` endpoint for pushing text documents
  - `/rag` endpoint for question answering with session history
  - FAISS vector index and simple SQLite/SQLAlchemy document store
  - Embedding and chat via Ollama models
- **Dockerised services** for API and scraping jobs
- **Configuration** driven by environment variables (`.env` support)
- **Portable requirements** separated by component (base, API, scrapers)

---

## ✅ Requirements

- Python **3.8+** (project uses Python 3.11 in containers)
- `pip` for installing dependencies
- (Optional) Docker / docker-compose for containerised runs

---

## 🚀 Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/fraggsTitan/AI-Investment-Analyst.git
   cd AI-Investment-Analyst
   ```

2. **Create a virtual environment** (recommended)
   ```bash
   # Windows
   python -m venv venv
   venv\Scripts\activate

   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt             # core API + RAG
   pip install -r requirements.scraper.txt     # scraper helpers
   # or choose one of the extras, e.g. when running only the API
   pip install -r requirements-api.txt
   ```

---

## ⚙️ Configuration

Create a `.env` file in the project root containing the variables you need:

```env
OLLAMA_API_KEY=your_key_here
OLLAMA_EMBED_BASE_URL=http://ollama:11434           # if self‑hosted
DATABASE_URL=postgresql://user:pass@host/dbname      # defaults to sqlite
RAG_INGEST_URL=http://localhost:8000/ingest          # scraper target
```

Other settings such as `MAX_HISTORY` and scraping intervals are defined in
code and can be tweaked if necessary.

---

## 📦 Project Structure

```text
AI-Investment-Analyst/
├── main.py                 # FastAPI RAG server (ingest & QA)
├── master_scraper.py       # one-time bulk ingestion script
├── dynamic_scraper.py      # continuous/daemon scraper with dedup
├── Dockerfile*             # container definitions for API & scrapers
├── docker-compose.yml      # orchestrates multiple containers (API, scrapers)
├── nginx.conf              # optional proxy config
├── requirements*.txt       # dependency lists per component
├── data.json               # example dataset stub
├── logs/                   # runtime logs (scraper, etc.)
└── frontend/               # simple static UI (index.html)
```

---

## 🛠 Usage

### Run locally

Start the API:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Ingest a document manually:
```bash
curl -X POST localhost:8000/ingest \ \
     -H "Content-Type: application/json" \
     -d '{"text": "Some startup info", "source": "manual"}'
```

Ask a question:
```bash
curl -X POST localhost:8000/rag -H "Content-Type: application/json" \
     -d '{"query": "Which Indian startup raised seed funding in 2025?"}'
```

### Run the scrapers

Bulk load:
```bash
python master_scraper.py
```

Continuous daemon (runs until killed):
```bash
python dynamic_scraper.py
```

### Docker

Build and start everything with Compose:
```bash
docker-compose up --build
```

Or run a single container:
```bash
docker build -f Dockerfile.api -t ai-investment-api .
docker run -p 8000:8000 ai-investment-api
```

---

## 📌 Example commands

```bash
# ingest from a file
python -c "import requests, json; r=requests.post('http://localhost:8000/ingest', json=json.load(open('doc.json'))); print(r.text)"

# query the RAG service
python -c "import requests; print(requests.post('http://localhost:8000/rag', json={'query':'funding','session_id':None}).json())"
```

---

## 📦 Dependencies

Core libraries (see `requirements.txt`):
- fastapi, uvicorn
- sqlalchemy, psycopg2-binary
- faiss-cpu, numpy
- requests, python-dotenv, pydantic
- ollama client

Scraper extras (`requirements.scraper.txt`):
- requests, feedparser, pandas
- PyMuPDF, beautifulsoup4, lxml

API‑only extras (`requirements-api.txt`): embedding helpers, python-multipart

---

## 🤝 Contributing

Contributions are welcome!  
To contribute:
1. Fork the repo
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes (follow PEP 8, document your code)
4. Commit & push: `git commit -m "Add ..." && git push origin feature/your-feature`
5. Open a pull request with a clear description

---

## 📜 License

This project is open source under the **MIT License**.  See `LICENSE` file
(if present) or assume MIT terms.

---

## 📞 Support

For issues or questions:

- Open an issue on GitHub
- Review existing documentation or code comments
- Contact the project maintainer directly

---

> **Disclaimer:** This tool is intended for educational and informational use.
> It does **not** constitute financial advice. Always perform your own
> research and consult a licensed financial advisor before making
> investment decisions.

Happy scraping and investing! 📈
