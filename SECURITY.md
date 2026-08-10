# Security Policy

## Secrets

Do not commit API keys, `.env`, `.streamlit/secrets.toml`, private keys, or exported session data. The application accepts Doubao and Tavily keys only through password widgets and does not include keys in research results, reports, or diagnostics.

If a secret is committed, revoke it immediately, remove it from the full Git history, and run the complete history scan before publishing again.

## Data and External Content

The application sends the research request and selected public-source content to configured external APIs. Do not submit confidential, personal, regulated, or contract-restricted information. Retrieved web content is untrusted input and remains subject to citation and evidence validation.

## Reporting a Vulnerability

Open a private security advisory in the GitHub repository. Do not include live credentials or sensitive datasets in a public issue.
