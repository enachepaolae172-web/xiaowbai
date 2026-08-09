# Node 5 mandatory strategy analysis rules

The runtime instruction is stored in `src/model_tasks.py` and validated against
`src/strategy_models.py`.

- PEST always contains political, economic, social, and technological assessments.
- Market analysis always covers total market, growth stage, customer structure, five customer roles,
  and procurement drivers. Missing data remains unknown.
- Comparable market series must keep year, region, unit, statistical scope, and source ID. CAGR is
  calculated by application code rather than accepted from the model.
- Porter assessments contain every force. Scores are optional; a 1-5 score requires facts, sources,
  reasoning, counterpoints, uncertainty, and recommendations.
- Facts, judgments, and recommendations remain separate fields.
- Search snippets cannot support facts, quantitative points, conclusions, or force scores.
