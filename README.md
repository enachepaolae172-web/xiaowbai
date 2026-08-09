# Enterprise AI Strategy Research Agent

企业战略研究助手是一款面向战略分析和商业研究场景的轻量 Agent。用户输入行业、地区、研究期间和战略问题后，系统将基于公开资料生成可追溯、可复核的战略研究报告。

## Current Status

**Node 1 / 8:** project scaffold and Streamlit workbench.

The current version provides the application shell only. Search, model calls, analysis, and report generation will be added after each review gate is approved.

## Planned Capabilities

- PEST, market analysis, and Porter's Five Forces
- Evidence-first web research with source identifiers
- Conditional concentration, value chain, key success factor, and lifecycle modules
- Sample mode without API calls
- Real-time mode using the visitor's Volcengine Ark and Tavily API keys
- Markdown report preview and download

## Tech Stack

- Python 3.12
- Streamlit
- Pydantic
- OpenAI Python SDK with Volcengine Ark compatibility
- Tavily
- pytest

No LangChain, database, vector store, or multi-agent framework is used in V0.1.

## Local Setup

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501` after the server starts.

## Tests

```powershell
python -m pytest
```

## Configuration

Copy `.env.example` to `.env` only when real-time mode is implemented. Real API keys must never be committed.

## Repository

- [Product requirements](PRD.md)
- [Documentation workspace](docs/README.md)
- [Prompt workspace](prompts/README.md)
- [Sample data workspace](data/sample/README.md)

## Security

- Real API keys are excluded by `.gitignore`.
- Public demos will not include an author-owned API key.
- Session keys must not be written to logs, generated reports, or source files.

## License

No license has been selected yet. A license will be added before the public V0.1 release.
