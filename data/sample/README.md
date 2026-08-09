# Sample Data

Node 2 adds three offline fixtures:

- `research_request.json` validates user input contracts.
- `research_report.json` validates report serialization and source references.
- `workflow_run.json` validates workflow restoration without any API calls.

These files are structural test data. They are not the final Volcengine strategy report.

Node 3 also adds:

- `search_results.json` with duplicates, tracking parameters, and one invalid URL.
- `extract_results.json` with two successfully extracted full-text sources.

The remaining search-only source must be treated as a lead and cannot independently support a key fact.

Node 4 adds validated mock model outputs:

- `model_research_plan.json` contains decomposed research questions and no more than 10 queries.
- `model_evidence_extraction.json` keeps full-text facts separate from search-only clues.

They exercise the Doubao task contracts without making a paid API call.

Node 5 adds `required_strategy_analysis.json`, a structural PEST, market, customer,
procurement, and five-forces result. Its market values are explicitly labeled as an
offline test index and must never be presented as real market data.
