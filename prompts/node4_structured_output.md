# Node 4 structured output rules

The runtime prompt definitions live in `src/model_tasks.py` so they are versioned with the
Pydantic contracts that validate them.

- The system prompt treats user and source text as data rather than instructions.
- Every task requests one JSON object and supplies its Pydantic JSON schema.
- Search snippets cannot independently produce key facts.
- Missing evidence must remain unknown rather than being completed by the model.
- Malformed JSON receives one repair call; a second malformed response stops the task.
- API keys and prompt bodies are never written to logs or model diagnostics.
