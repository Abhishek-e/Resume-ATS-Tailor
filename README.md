# Resumify — AI Resume & Career Toolkit

Resumify is a Flask web application for creating ATS-friendly resumes and cover letters, exploring matching job opportunities, and checking text for likely plagiarism. It can save a user's documents to Firebase/Firestore and export them as PDF or Word files.

## Features

- Generate structured, ATS-friendly resumes from raw candidate details
- Create tailored cover letters for a specific role and company
- Choose from modern, classic, and minimal document templates
- Download resumes and cover letters as PDF or DOCX
- Search for roles and generate a job-tailored CV draft
- Check pasted text or `.txt`, `.docx`, and `.pdf` uploads for likely plagiarism
- Export plagiarism reports as PDF
- Register, log in, manage profile details, and save generated documents

## Tech stack

- **Backend:** Flask, Gunicorn
- **AI:** OpenRouter (generation) and optional Google Gemini with Google Search grounding
- **Data:** Firebase Admin SDK and Cloud Firestore
- **Document handling:** python-docx, pypdf, xhtml2pdf
- **Frontend:** Jinja templates, HTML, CSS, and browser JavaScript

## Prerequisites

- Python 3.10 or later
- A Firebase project with **Cloud Firestore** enabled (needed for registration, saved documents, and profiles)
- An [OpenRouter API key](https://openrouter.ai/keys) (needed for resume, cover-letter, and fallback AI generation)
- Optionally, a Google Gemini API key for grounded job and plagiarism searches

## Local setup

1. Clone the repository and enter the project folder.

   ```bash
   git clone <your-repository-url>
   cd Resume-ATS-Tailor-main
   ```

2. Create and activate a virtual environment.

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

   On Windows PowerShell, use:

   ```powershell
   .venv\Scripts\Activate.ps1
   ```

3. Install dependencies.

   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root.

   ```env
   SECRET_KEY=replace-with-a-long-random-value
   OPENROUTER_API_KEY=your-openrouter-api-key
   OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
   GEMINI_API_KEY=your-optional-gemini-api-key
   FIREBASE_CREDENTIALS_PATH=serviceAccountKey.json
   FLASK_DEBUG=true
   ```

5. Configure Firebase credentials using one of the following approaches:

   - **Local development:** download a Firebase service-account JSON key, place it in the project root as `serviceAccountKey.json`, and keep `FIREBASE_CREDENTIALS_PATH=serviceAccountKey.json` in `.env`.
   - **Hosted deployment:** set `FIREBASE_CREDENTIALS_JSON` to the complete JSON contents of the service-account key as a secret environment variable.

   The credential file and `.env` are ignored by Git. Do not commit either one.

6. Start the application.

   ```bash
   python app.py
   ```

7. Open [http://localhost:5000](http://localhost:5000) in your browser.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | Yes for production | Secures Flask sessions. A development-only fallback exists, but must not be used in production. |
| `OPENROUTER_API_KEY` | Yes for AI generation | Generates resumes, cover letters, job-targeted CV text, and fallback job/plagiarism results. |
| `OPENROUTER_MODEL` | No | OpenRouter model to use. Defaults to `nvidia/nemotron-3-super-120b-a12b:free`. |
| `GEMINI_API_KEY` | No | Enables Gemini with Google Search grounding for live job and plagiarism checks. |
| `FIREBASE_CREDENTIALS_PATH` | Local Firebase setup | Path to the local service-account JSON file. Defaults to `serviceAccountKey.json`. |
| `FIREBASE_CREDENTIALS_JSON` | Hosted Firebase setup | Full service-account JSON, supplied as a deployment secret. |
| `FLASK_DEBUG` | No | Enables Flask debug mode locally; defaults to `true` when running `app.py`. |
| `PORT` | No | Port to bind to; defaults to `5000`. |

### AI behavior

OpenRouter handles document generation. If a Gemini key is configured and its grounded search succeeds, job search and plagiarism checking use live Google Search results. Otherwise, they fall back to a non-grounded OpenRouter response, which can provide plausible job suggestions or general-knowledge plagiarism assessment rather than verified live results.

## Firebase / Firestore data

The app stores the following Firestore collections:

- `users` — account identity, hashed password, creation date, and profile details
- `resumes` — saved resume inputs, generated content, template, and owner ID
- `cover_letters` — saved letter inputs, generated content, template, and owner ID

Authentication and saved-document features require Firebase. The public home page, jobs page, and plagiarism checker can still load without Firebase, but registration and saving are unavailable.

## Deploying to Render

The repository includes `render.yaml` for a Python web service. In Render:

1. Create a new Blueprint or web service from this repository.
2. Set the secret environment variables `FIREBASE_CREDENTIALS_JSON` and `OPENROUTER_API_KEY`.
3. Optionally set `GEMINI_API_KEY` to enable grounded searches.
4. Ensure `SECRET_KEY` is generated or set to a strong private value.

Render installs dependencies with `pip install -r requirements.txt` and starts the service with `gunicorn app:app`.

> **Note:** `OPENROUTER_API_KEY` is required by the application but is not currently declared in `render.yaml`; add it in the Render dashboard as a secret environment variable.

## Project structure

```text
.
├── app.py                         # Flask routes, AI integration, exports, and Firestore access
├── requirements.txt               # Python dependencies
├── render.yaml                    # Render deployment definition
├── static/
│   └── style.css                  # Shared styles
└── templates/
    ├── index.html                 # Landing page
    ├── jobs.html                  # Job search and tailored-CV workflow
    ├── generate_cv.html           # Resume builder
    ├── generate_cover_letter.html # Cover-letter builder
    ├── plagiarism_checker.html    # Public plagiarism checker
    ├── profile.html               # Saved documents and profile details
    ├── resume_templates/          # Resume print/export templates
    └── cover_letter_templates/    # Cover-letter print/export templates
```

## Security notes

- Never commit `.env`, Firebase service-account credentials, or API keys.
- Use a unique, high-entropy `SECRET_KEY` in production.
- Deploy over HTTPS and use restrictive Firestore security rules appropriate for your environment.
- AI-generated content and plagiarism assessments should be reviewed by a person before use; scores and sources may be incomplete or inaccurate.

## License

No license file is currently included. Add a license before distributing or reusing this project outside its intended scope.
