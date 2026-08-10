# Public Deployment

## GitHub

1. Create an empty public repository without a generated README or license.
2. Add it as the local `origin` remote.
3. Push `main` and the `v0.1.0` tag.
4. Confirm the GitHub Actions test workflow passes.
5. Create a release from `CHANGELOG.md` and attach no credential-bearing files.

```powershell
git remote add origin https://github.com/<account>/<repository>.git
git push -u origin main
git push origin v0.1.0
```

## Streamlit Community Cloud

Create a new app from the public repository using:

| Setting | Value |
|---|---|
| Branch | `main` |
| App file | `app.py` |
| Python | `3.12` via `runtime.txt` |

No deployment secret is required for sample mode. Do not add an author-owned Doubao or Tavily key to the public app. Visitors may optionally enter their own keys in password widgets for the current session.

## Verification

- Open the public URL without logging in.
- Confirm the Volcengine sample loads without API calls.
- Confirm all five result tabs and Markdown download work.
- Check desktop and mobile layouts.
- Enter visitor-owned keys only for an authorized real-time smoke test.
- Re-scan the repository and full Git history for secrets before publishing the release.
