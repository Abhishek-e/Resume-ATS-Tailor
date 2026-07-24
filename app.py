import json
import os
import re
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, session
from google import genai
from google.genai import types
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
# Reads from environment; falls back to a dev-only value so local runs don't crash.
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-key-change-me")

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


def get_db_connection():
    """
    Connects using DATABASE_URL (provided automatically by Render when a
    Postgres database is linked in render.yaml). Falls back to local
    Postgres defaults for development.
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        # Render's connection string starts with postgres:// ; psycopg2 wants postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(database_url)

    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", "postgres"),
        dbname=os.environ.get("DB_NAME", "resumify_db"),
    )


# --- ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        hashed_pw = generate_password_hash(password)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
                (username, email, hashed_pw)
            )
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except psycopg2.Error:
            conn.rollback()
            flash('Email already exists or database error.', 'error')
        finally:
            cursor.close()
            conn.close()

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))


@app.route('/jobs')
def jobs():
    return render_template('jobs.html')


def _extract_json_array(text):
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("Model response did not contain a JSON array.")
    return json.loads(match.group(0))


def _search_jobs_with_gemini(job_title, location, experience_level, skills):
    prompt = f"""You are a job search assistant with access to Google Search.
Search the web for real, currently posted job openings matching:
- Role: {job_title}
- Location: {location or "Any"}
- Experience level: {experience_level or "Any"}
- Candidate's skills / experience: {skills or "Not provided"}

Find up to 6 relevant job postings. For each one, estimate the candidate's
chance of getting the job as a percentage (0-100), based on how well the
candidate's skills/experience match the role's likely requirements.

Respond with ONLY a JSON array (no markdown, no commentary) of objects with
exactly these keys:
- "title": job title
- "company": company name
- "location": job location
- "match_percentage": integer 0-100
- "description": a concise 2-line summary of the role
- "job_description": a fuller job description / requirements (4-8 sentences)
- "keywords": array of 5-10 important keywords/skills from the JD
- "source_url": link to the posting if known, else ""
"""

    try:
        response = genai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        return _extract_json_array(response.text), True
    except Exception:
        # Live grounded search unavailable (quota/billing) - fall back to a
        # non-grounded generation so the feature still works.
        fallback_prompt = prompt.replace(
            "You are a job search assistant with access to Google Search.",
            "You are a job search assistant. Live web search is unavailable, so "
            "generate realistic, plausible job postings typical for this role "
            "instead of real-time results.",
        )
        response = genai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=fallback_prompt,
        )
        return _extract_json_array(response.text), False


@app.route('/jobs/search', methods=['POST'])
def jobs_search():
    if not genai_client:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the server."}), 503

    data = request.get_json(silent=True) or {}
    job_title = (data.get('job_title') or '').strip()
    location = (data.get('location') or '').strip()
    experience_level = (data.get('experience_level') or '').strip()
    skills = (data.get('skills') or '').strip()

    if not job_title:
        return jsonify({"error": "Job title is required."}), 400

    try:
        jobs_data, live = _search_jobs_with_gemini(job_title, location, experience_level, skills)
    except Exception as e:
        return jsonify({"error": f"Failed to fetch job listings: {e}"}), 502

    return jsonify({"jobs": jobs_data, "live_search": live})


@app.route('/jobs/generate-cv', methods=['POST'])
def jobs_generate_cv():
    if not genai_client:
        return jsonify({"error": "GEMINI_API_KEY is not configured on the server."}), 503

    data = request.get_json(silent=True) or {}
    job_title = (data.get('title') or '').strip()
    company = (data.get('company') or '').strip()
    job_description = (data.get('job_description') or '').strip()
    keywords = data.get('keywords') or []
    skills = (data.get('skills') or '').strip()

    if not job_description:
        return jsonify({"error": "Job description is required."}), 400

    prompt = f"""Create a tailored, ATS-friendly CV/resume in plain text for a candidate
applying to this specific job.

Job Title: {job_title}
Company: {company or "N/A"}
Job Description:
{job_description}

Keywords to naturally incorporate: {", ".join(keywords) if keywords else "N/A"}

Candidate's current skills / experience / background:
{skills or "Not provided - infer a reasonable background suitable for this role."}

Write a complete CV with: a professional summary tailored to this role, a
skills section prominently featuring the keywords above, and a suggested
work experience section with bullet points. Do not fabricate specific
employers or degrees; use placeholders like [Your Previous Company] where
actual history is unknown. Output plain text only, no markdown symbols."""

    try:
        response = genai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        cv_text = response.text.strip()
    except Exception as e:
        return jsonify({"error": f"Failed to generate CV: {e}"}), 502

    return jsonify({"cv": cv_text})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
