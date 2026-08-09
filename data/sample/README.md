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
