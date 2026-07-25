import io
import json
import os
import re
from datetime import datetime, timezone
from functools import wraps

import firebase_admin
from docx import Document
from docx.shared import Pt, RGBColor
from dotenv import load_dotenv
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from flask import (
    Flask, abort, jsonify, render_template, request, redirect, url_for,
    flash, send_file, session,
)
from google import genai
from google.genai import types
from openai import OpenAI
from pydantic import BaseModel
from pypdf import PdfReader
from werkzeug.security import generate_password_hash, check_password_hash
from xhtml2pdf import pisa

load_dotenv()

app = Flask(__name__)
# Reads from environment; falls back to a dev-only value so local runs don't crash.
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-secret-key-change-me")

GEMINI_MODEL = "gemini-3.5-flash"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Text generation (CV, cover letter, plagiarism write-up) runs on OpenRouter's
# free tier instead of Gemini, so it isn't capped by Gemini's 20 req/day quota.
# Get a key at https://openrouter.ai/keys - no billing required for :free models.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
) if OPENROUTER_API_KEY else None

RESUME_TEMPLATES = {"modern", "classic", "minimal"}


def _openrouter_generate(prompt, json_mode=False):
    """Runs a single-turn text generation on OpenRouter. Raises if the key
    isn't configured or the API call fails - callers handle/report that."""
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    completion = openrouter_client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )
    return completion.choices[0].message.content


def _init_firestore():
    """
    Loads Firebase Admin SDK credentials from either a JSON blob in
    FIREBASE_CREDENTIALS_JSON (used on Render, set as a secret env var) or a
    service account key file on disk (used locally). Returns None instead of
    raising if neither is configured yet, so the rest of the app can still
    run and surface a clear error only when a DB-backed route is hit.
    """
    try:
        if not firebase_admin._apps:
            cred_json = os.environ.get("FIREBASE_CREDENTIALS_JSON")
            if cred_json:
                cred = credentials.Certificate(json.loads(cred_json))
            else:
                cred_path = os.environ.get("FIREBASE_CREDENTIALS_PATH", "serviceAccountKey.json")
                cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        print(f"[WARN] Firebase/Firestore not configured: {e}")
        return None


db = _init_firestore()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please log in to continue.', 'error')
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


# --- ROUTES ---

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if db is None:
            flash('Database is not configured on the server.', 'error')
            return render_template('register.html')

        username = request.form['username']
        email = request.form['email'].strip().lower()
        password = request.form['password']

        user_ref = db.collection('users').document(email)
        if user_ref.get().exists:
            flash('Email already exists.', 'error')
        else:
            user_ref.set({
                'username': username,
                'email': email,
                'password': generate_password_hash(password),
                'created_at': firestore.SERVER_TIMESTAMP,
            })
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        user = None
        if db is not None:
            doc = db.collection('users').document(email).get()
            if doc.exists:
                user = doc.to_dict()

        if user and check_password_hash(user['password'], password):
            session['user_id'] = email
            session['username'] = user['username']
            flash('Login successful!', 'success')
            return redirect(request.form.get('next') or url_for('home'))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('login.html', next=request.args.get('next', ''))


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


def _extract_json_object(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("Model response did not contain a JSON object.")
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

    if genai_client:
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
            # Live grounded search unavailable (quota/billing) - fall through
            # to a non-grounded generation on OpenRouter instead.
            pass

    fallback_prompt = prompt.replace(
        "You are a job search assistant with access to Google Search.",
        "You are a job search assistant. Live web search is unavailable, so "
        "generate realistic, plausible job postings typical for this role "
        "instead of real-time results.",
    )
    raw = _openrouter_generate(fallback_prompt)
    return _extract_json_array(raw), False


@app.route('/jobs/search', methods=['POST'])
def jobs_search():
    if not genai_client and not openrouter_client:
        return jsonify({"error": "Neither GEMINI_API_KEY nor OPENROUTER_API_KEY is configured on the server."}), 503

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
    if not openrouter_client:
        return jsonify({"error": "OPENROUTER_API_KEY is not configured on the server."}), 503

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
        cv_text = _openrouter_generate(prompt).strip()
    except Exception as e:
        return jsonify({"error": f"Failed to generate CV: {e}"}), 502

    return jsonify({"cv": cv_text})


# --- GENERATE CV (BUILDER, TEMPLATES, EXPORTS, PROFILE) ---

class ResumeContact(BaseModel):
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    portfolio: str = ""


class ResumeExperience(BaseModel):
    title: str = ""
    company: str = ""
    dates: str = ""
    bullets: list[str] = []


class ResumeEducation(BaseModel):
    degree: str = ""
    school: str = ""
    dates: str = ""


class ResumeProject(BaseModel):
    name: str = ""
    description: str = ""


class ResumeContent(BaseModel):
    full_name: str = ""
    target_role: str = ""
    contact: ResumeContact = ResumeContact()
    summary: str = ""
    skills: list[str] = []
    experience: list[ResumeExperience] = []
    education: list[ResumeEducation] = []
    certifications: list[str] = []
    projects: list[ResumeProject] = []


def _slugify(text):
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', text or '').strip('-').lower()
    return slug or 'resume'


def _generate_resume_content(input_data):
    prompt = f"""You are an expert resume writer. Build an ATS-friendly resume from the
candidate's raw input below. Rewrite experience bullets to be concise,
action-oriented, quantified where reasonable, and keyword-rich for the
target role. Do not fabricate employers, dates, or degrees beyond what is
given here - only improve the wording and structure of what's provided. If
the raw input already contains bracketed placeholders (e.g.
"[Your Previous Company]", "[Graduation Year]"), keep those placeholders in
the output literally instead of dropping them - a section left as
placeholders is more useful to the candidate than an empty section.

Candidate input:
Full Name: {input_data.get('full_name', '')}
Target Role: {input_data.get('target_role', '')}
Email: {input_data.get('email', '')}
Phone: {input_data.get('phone', '')}
Location: {input_data.get('location', '')}
LinkedIn: {input_data.get('linkedin', '')}
Portfolio: {input_data.get('portfolio', '')}
Professional Summary (raw, optional): {input_data.get('summary', '')}
Skills (raw): {input_data.get('skills', '')}
Work Experience (raw): {input_data.get('experience', '')}
Education (raw): {input_data.get('education', '')}
Certifications (raw, optional): {input_data.get('certifications', '')}
Projects (raw, optional): {input_data.get('projects', '')}

Use empty strings/arrays for fields with no data. Do not invent employers,
dates, or degrees beyond what is given.

Respond with ONLY a JSON object (no markdown, no commentary) with exactly
these keys:
- "full_name": string
- "target_role": string
- "contact": object with "email", "phone", "location", "linkedin", "portfolio" (strings)
- "summary": string
- "skills": array of strings
- "experience": array of objects with "title", "company", "dates" (strings) and "bullets" (array of strings)
- "education": array of objects with "degree", "school", "dates" (strings)
- "certifications": array of strings
- "projects": array of objects with "name", "description" (strings)"""

    raw = _openrouter_generate(prompt, json_mode=True)
    data = _extract_json_object(raw)
    return ResumeContent(**data).model_dump()


def _render_resume_html(template, resume):
    if template not in RESUME_TEMPLATES:
        template = 'modern'
    return render_template(f'resume_templates/{template}.html', resume=resume)


def _html_to_pdf_bytes(html):
    buf = io.BytesIO()
    result = pisa.CreatePDF(io.StringIO(html), dest=buf)
    if result.err:
        raise RuntimeError("Failed to render PDF.")
    return buf.getvalue()


_TEMPLATE_ACCENTS = {
    "modern": RGBColor(0x1F, 0x3A, 0x5F),
    "classic": RGBColor(0x00, 0x00, 0x00),
    "minimal": RGBColor(0x33, 0x33, 0x33),
}


def _build_resume_docx(template, resume):
    doc = Document()
    accent = _TEMPLATE_ACCENTS.get(template, _TEMPLATE_ACCENTS["modern"])
    font_name = 'Georgia' if template == 'classic' else 'Calibri'

    base_style = doc.styles['Normal']
    base_style.font.name = font_name
    base_style.font.size = Pt(10.5)

    name_p = doc.add_paragraph()
    name_run = name_p.add_run(resume.get('full_name', ''))
    name_run.font.size = Pt(22)
    name_run.font.bold = True
    name_run.font.color.rgb = accent

    if resume.get('target_role'):
        role_run = doc.add_paragraph().add_run(resume['target_role'])
        role_run.font.size = Pt(12)
        role_run.italic = True

    contact = resume.get('contact') or {}
    contact_line = ' | '.join(filter(None, [
        contact.get('email'), contact.get('phone'), contact.get('location'),
        contact.get('linkedin'), contact.get('portfolio'),
    ]))
    if contact_line:
        doc.add_paragraph().add_run(contact_line).font.size = Pt(9.5)

    def add_heading(text):
        h = doc.add_paragraph()
        run = h.add_run(text.upper())
        run.font.bold = True
        run.font.size = Pt(12)
        run.font.color.rgb = accent
        h.paragraph_format.space_before = Pt(12)
        h.paragraph_format.space_after = Pt(2)

    if resume.get('summary'):
        add_heading('Summary')
        doc.add_paragraph(resume['summary'])

    if resume.get('skills'):
        add_heading('Skills')
        doc.add_paragraph(' • '.join(resume['skills']))

    if resume.get('experience'):
        add_heading('Experience')
        for job in resume['experience']:
            jp = doc.add_paragraph()
            jp.add_run(f"{job.get('title', '')} — {job.get('company', '')}").bold = True
            if job.get('dates'):
                jp.add_run(f"   ({job['dates']})").italic = True
            for bullet in job.get('bullets', []):
                doc.add_paragraph(bullet, style='List Bullet')

    if resume.get('education'):
        add_heading('Education')
        for edu in resume['education']:
            ep = doc.add_paragraph()
            ep.add_run(f"{edu.get('degree', '')} — {edu.get('school', '')}").bold = True
            if edu.get('dates'):
                ep.add_run(f"   ({edu['dates']})").italic = True

    if resume.get('certifications'):
        add_heading('Certifications')
        for cert in resume['certifications']:
            doc.add_paragraph(cert, style='List Bullet')

    if resume.get('projects'):
        add_heading('Projects')
        for proj in resume['projects']:
            pp = doc.add_paragraph()
            pp.add_run(proj.get('name', '')).bold = True
            if proj.get('description'):
                doc.add_paragraph(proj['description'])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@app.route('/generate-cv')
@login_required
def generate_cv():
    return render_template('generate_cv.html')


@app.route('/generate-cv/build', methods=['POST'])
@login_required
def generate_cv_build():
    if not openrouter_client:
        return jsonify({"error": "OPENROUTER_API_KEY is not configured on the server."}), 503

    input_data = request.get_json(silent=True) or {}
    if not (input_data.get('full_name') and input_data.get('target_role')):
        return jsonify({"error": "Full name and target role are required."}), 400

    try:
        resume = _generate_resume_content(input_data)
    except Exception as e:
        return jsonify({"error": f"Failed to generate resume: {e}"}), 502

    return jsonify({"resume": resume})


@app.route('/generate-cv/render', methods=['POST'])
@login_required
def generate_cv_render():
    data = request.get_json(silent=True) or {}
    return _render_resume_html(data.get('template', 'modern'), data.get('resume') or {})


@app.route('/generate-cv/download/pdf', methods=['POST'])
@login_required
def generate_cv_download_pdf():
    data = request.get_json(silent=True) or {}
    template = data.get('template', 'modern')
    resume = data.get('resume') or {}
    try:
        pdf_bytes = _html_to_pdf_bytes(_render_resume_html(template, resume))
    except Exception as e:
        return jsonify({"error": f"Failed to build PDF: {e}"}), 500
    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name=f"{_slugify(resume.get('full_name'))}.pdf",
    )


@app.route('/generate-cv/download/docx', methods=['POST'])
@login_required
def generate_cv_download_docx():
    data = request.get_json(silent=True) or {}
    template = data.get('template', 'modern')
    resume = data.get('resume') or {}
    try:
        docx_bytes = _build_resume_docx(template, resume)
    except Exception as e:
        return jsonify({"error": f"Failed to build Word document: {e}"}), 500
    return send_file(
        io.BytesIO(docx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True, download_name=f"{_slugify(resume.get('full_name'))}.docx",
    )


@app.route('/generate-cv/save', methods=['POST'])
@login_required
def generate_cv_save():
    if db is None:
        return jsonify({"error": "Database is not configured on the server."}), 503

    data = request.get_json(silent=True) or {}
    template = data.get('template', 'modern')
    input_data = data.get('input_data') or {}
    resume = data.get('resume') or {}

    if not resume:
        return jsonify({"error": "No generated resume to save."}), 400

    doc_ref = db.collection('resumes').document()
    doc_ref.set({
        'user_id': session['user_id'],
        'template': template,
        'full_name': resume.get('full_name', ''),
        'target_role': resume.get('target_role', ''),
        'input_data': input_data,
        'generated_content': resume,
        'created_at': firestore.SERVER_TIMESTAMP,
    })

    return jsonify({"id": doc_ref.id})


def _fetch_user_docs(collection):
    if db is None:
        return []
    docs = db.collection(collection).where(filter=FieldFilter('user_id', '==', session['user_id'])).stream()
    items = []
    for d in docs:
        data = d.to_dict()
        data['id'] = d.id
        items.append(data)
    items.sort(key=lambda r: r.get('created_at') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items


def _get_owned_doc(collection, doc_id):
    if db is None:
        abort(404)
    doc = db.collection(collection).document(doc_id).get()
    if not doc.exists or doc.to_dict().get('user_id') != session['user_id']:
        abort(404)
    data = doc.to_dict()
    data['id'] = doc.id
    return data


@app.route('/profile')
@login_required
def profile():
    resumes = _fetch_user_docs('resumes')
    cover_letters = _fetch_user_docs('cover_letters')
    profile_details = {}
    if db is not None:
        user_doc = db.collection('users').document(session['user_id']).get()
        if user_doc.exists:
            profile_details = user_doc.to_dict().get('details') or {}
    return render_template(
        'profile.html', resumes=resumes, cover_letters=cover_letters, profile_details=profile_details,
    )


@app.route('/profile/details/save', methods=['POST'])
@login_required
def profile_details_save():
    if db is None:
        return jsonify({"error": "Database is not configured on the server."}), 503

    data = request.get_json(silent=True) or {}
    details = {
        'full_name': (data.get('full_name') or '').strip(),
        'id_card_number': (data.get('id_card_number') or '').strip(),
        'college_name': (data.get('college_name') or '').strip(),
        'location': (data.get('location') or '').strip(),
        'github': (data.get('github') or '').strip(),
        'linkedin': (data.get('linkedin') or '').strip(),
        'other': (data.get('other') or '').strip(),
    }
    db.collection('users').document(session['user_id']).update({'details': details})
    return jsonify({"ok": True, "details": details})


@app.route('/resume/<resume_id>/download/pdf')
@login_required
def resume_download_pdf(resume_id):
    row = _get_owned_doc('resumes', resume_id)
    pdf_bytes = _html_to_pdf_bytes(_render_resume_html(row['template'], row['generated_content']))
    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name=f"{_slugify(row['full_name'])}.pdf",
    )


@app.route('/resume/<resume_id>/download/docx')
@login_required
def resume_download_docx(resume_id):
    row = _get_owned_doc('resumes', resume_id)
    docx_bytes = _build_resume_docx(row['template'], row['generated_content'])
    return send_file(
        io.BytesIO(docx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True, download_name=f"{_slugify(row['full_name'])}.docx",
    )


@app.route('/resume/<resume_id>/delete', methods=['POST'])
@login_required
def resume_delete(resume_id):
    _get_owned_doc('resumes', resume_id)
    db.collection('resumes').document(resume_id).delete()
    return jsonify({"ok": True})


# --- GENERATE COVER LETTER (BUILDER, TEMPLATES, EXPORTS, PROFILE) ---

COVER_LETTER_TEMPLATES = {"modern", "classic", "minimal"}


class CoverLetterContent(BaseModel):
    full_name: str = ""
    target_role: str = ""
    company_name: str = ""
    contact: ResumeContact = ResumeContact()
    salutation: str = ""
    body_paragraphs: list[str] = []
    closing: str = ""


def _generate_cover_letter_content(input_data):
    prompt = f"""You are an expert cover letter writer. Write a concise, ATS-friendly
cover letter from the candidate's raw input below, tailored to the target
role and company. Keep it to 3-4 short paragraphs: an opening hook, why
they're a fit (tied to the job description if given), a highlight or two
from their background, and a confident closing call to action. Do not
fabricate employers, achievements, or facts beyond what is given here -
only improve the wording and structure.

Candidate input:
Full Name: {input_data.get('full_name', '')}
Target Role: {input_data.get('target_role', '')}
Company Name: {input_data.get('company_name', '')}
Email: {input_data.get('email', '')}
Phone: {input_data.get('phone', '')}
Location: {input_data.get('location', '')}
LinkedIn: {input_data.get('linkedin', '')}
Portfolio: {input_data.get('portfolio', '')}
Hiring Manager Name (optional): {input_data.get('hiring_manager', '')}
Job Description / Key Requirements (raw, optional): {input_data.get('job_description', '')}
Your Background / Key Achievements (raw): {input_data.get('background', '')}

Use "Dear Hiring Manager," as the salutation if no hiring manager name is
given, otherwise "Dear {{name}},". body_paragraphs is a list of 3-4
plain-text paragraphs (no headers, no markdown). closing is a short
sign-off phrase like "Sincerely," - do not repeat the candidate's name in
it, that is rendered separately.

Respond with ONLY a JSON object (no markdown, no commentary) with exactly
these keys:
- "full_name": string
- "target_role": string
- "company_name": string
- "contact": object with "email", "phone", "location", "linkedin", "portfolio" (strings)
- "salutation": string
- "body_paragraphs": array of strings
- "closing": string"""

    raw = _openrouter_generate(prompt, json_mode=True)
    data = _extract_json_object(raw)
    return CoverLetterContent(**data).model_dump()


def _render_cover_letter_html(template, letter):
    if template not in COVER_LETTER_TEMPLATES:
        template = 'modern'
    return render_template(
        f'cover_letter_templates/{template}.html',
        letter=letter, today=datetime.now().strftime('%B %d, %Y'),
    )


def _build_cover_letter_docx(template, letter):
    doc = Document()
    accent = _TEMPLATE_ACCENTS.get(template, _TEMPLATE_ACCENTS["modern"])
    font_name = 'Georgia' if template == 'classic' else 'Calibri'

    base_style = doc.styles['Normal']
    base_style.font.name = font_name
    base_style.font.size = Pt(11)

    name_p = doc.add_paragraph()
    name_run = name_p.add_run(letter.get('full_name', ''))
    name_run.font.size = Pt(18)
    name_run.font.bold = True
    name_run.font.color.rgb = accent

    contact = letter.get('contact') or {}
    contact_line = ' | '.join(filter(None, [
        contact.get('email'), contact.get('phone'), contact.get('location'),
        contact.get('linkedin'), contact.get('portfolio'),
    ]))
    if contact_line:
        doc.add_paragraph().add_run(contact_line).font.size = Pt(9.5)

    doc.add_paragraph().add_run(datetime.now().strftime('%B %d, %Y')).font.size = Pt(10)

    if letter.get('company_name'):
        doc.add_paragraph().add_run(letter['company_name']).font.size = Pt(10)

    doc.add_paragraph()

    doc.add_paragraph(letter.get('salutation') or 'Dear Hiring Manager,')

    for para in letter.get('body_paragraphs', []):
        p = doc.add_paragraph(para)
        p.paragraph_format.space_after = Pt(10)

    doc.add_paragraph(letter.get('closing') or 'Sincerely,')
    doc.add_paragraph(letter.get('full_name', ''))

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@app.route('/generate-cover-letter')
@login_required
def generate_cover_letter():
    return render_template('generate_cover_letter.html')


@app.route('/generate-cover-letter/build', methods=['POST'])
@login_required
def generate_cover_letter_build():
    if not openrouter_client:
        return jsonify({"error": "OPENROUTER_API_KEY is not configured on the server."}), 503

    input_data = request.get_json(silent=True) or {}
    if not (input_data.get('full_name') and input_data.get('target_role') and input_data.get('company_name')):
        return jsonify({"error": "Full name, target role, and company name are required."}), 400

    try:
        letter = _generate_cover_letter_content(input_data)
    except Exception as e:
        return jsonify({"error": f"Failed to generate cover letter: {e}"}), 502

    return jsonify({"letter": letter})


@app.route('/generate-cover-letter/render', methods=['POST'])
@login_required
def generate_cover_letter_render():
    data = request.get_json(silent=True) or {}
    return _render_cover_letter_html(data.get('template', 'modern'), data.get('letter') or {})


@app.route('/generate-cover-letter/download/pdf', methods=['POST'])
@login_required
def generate_cover_letter_download_pdf():
    data = request.get_json(silent=True) or {}
    template = data.get('template', 'modern')
    letter = data.get('letter') or {}
    try:
        pdf_bytes = _html_to_pdf_bytes(_render_cover_letter_html(template, letter))
    except Exception as e:
        return jsonify({"error": f"Failed to build PDF: {e}"}), 500
    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name=f"{_slugify(letter.get('full_name'))}-cover-letter.pdf",
    )


@app.route('/generate-cover-letter/download/docx', methods=['POST'])
@login_required
def generate_cover_letter_download_docx():
    data = request.get_json(silent=True) or {}
    template = data.get('template', 'modern')
    letter = data.get('letter') or {}
    try:
        docx_bytes = _build_cover_letter_docx(template, letter)
    except Exception as e:
        return jsonify({"error": f"Failed to build Word document: {e}"}), 500
    return send_file(
        io.BytesIO(docx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True, download_name=f"{_slugify(letter.get('full_name'))}-cover-letter.docx",
    )


@app.route('/generate-cover-letter/save', methods=['POST'])
@login_required
def generate_cover_letter_save():
    if db is None:
        return jsonify({"error": "Database is not configured on the server."}), 503

    data = request.get_json(silent=True) or {}
    template = data.get('template', 'modern')
    input_data = data.get('input_data') or {}
    letter = data.get('letter') or {}

    if not letter:
        return jsonify({"error": "No generated cover letter to save."}), 400

    doc_ref = db.collection('cover_letters').document()
    doc_ref.set({
        'user_id': session['user_id'],
        'template': template,
        'full_name': letter.get('full_name', ''),
        'target_role': letter.get('target_role', ''),
        'company_name': letter.get('company_name', ''),
        'input_data': input_data,
        'generated_content': letter,
        'created_at': firestore.SERVER_TIMESTAMP,
    })

    return jsonify({"id": doc_ref.id})


@app.route('/cover-letter/<letter_id>/download/pdf')
@login_required
def cover_letter_download_pdf(letter_id):
    row = _get_owned_doc('cover_letters', letter_id)
    pdf_bytes = _html_to_pdf_bytes(_render_cover_letter_html(row['template'], row['generated_content']))
    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name=f"{_slugify(row['full_name'])}-cover-letter.pdf",
    )


@app.route('/cover-letter/<letter_id>/download/docx')
@login_required
def cover_letter_download_docx(letter_id):
    row = _get_owned_doc('cover_letters', letter_id)
    docx_bytes = _build_cover_letter_docx(row['template'], row['generated_content'])
    return send_file(
        io.BytesIO(docx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True, download_name=f"{_slugify(row['full_name'])}-cover-letter.docx",
    )


@app.route('/cover-letter/<letter_id>/delete', methods=['POST'])
@login_required
def cover_letter_delete(letter_id):
    _get_owned_doc('cover_letters', letter_id)
    db.collection('cover_letters').document(letter_id).delete()
    return jsonify({"ok": True})


# --- PLAGIARISM CHECKER (PUBLIC, NO LOGIN REQUIRED) ---

MAX_PLAGIARISM_TEXT_CHARS = 8000


class PlagiarismMatch(BaseModel):
    excerpt: str = ""
    similarity_percentage: int = 0
    source_description: str = ""
    source_url: str = ""


class PlagiarismReport(BaseModel):
    originality_percentage: int = 100
    plagiarism_percentage: int = 0
    summary: str = ""
    matches: list[PlagiarismMatch] = []


def _extract_text_from_upload(file_storage):
    filename = (file_storage.filename or '').lower()
    raw = file_storage.read()

    if filename.endswith('.txt'):
        return raw.decode('utf-8', errors='ignore')

    if filename.endswith('.docx'):
        doc = Document(io.BytesIO(raw))
        return '\n'.join(p.text for p in doc.paragraphs)

    if filename.endswith('.pdf'):
        reader = PdfReader(io.BytesIO(raw))
        return '\n'.join((page.extract_text() or '') for page in reader.pages)

    raise ValueError('Unsupported file type. Please upload a .txt, .docx, or .pdf file.')


def _check_plagiarism_with_gemini(text, exclude_citations):
    citation_instruction = (
        "Ignore text that appears to be a direct quotation or citation (e.g. in "
        "quotation marks, or clearly attributed to another source) when judging "
        "originality - do not flag properly quoted/cited material as plagiarism."
        if exclude_citations else
        "Treat all text as the author's own claimed work, including quoted passages."
    )

    prompt = f"""You are a plagiarism detection assistant with access to Google Search.
Analyze the following text for originality. Search the web to check whether
passages closely match existing published content (articles, papers, websites).
{citation_instruction}

Break the text into meaningful excerpts/sentences and check each one for close
matches elsewhere on the web. For every excerpt with a notable match, report the
excerpt, an estimated similarity percentage (0-100), a short description of the
matching source, and its URL if you found one.

Then give:
- "originality_percentage": overall estimated originality (0-100, where 100 is
  fully original)
- "plagiarism_percentage": 100 minus originality, roughly weighted by how much
  of the text is covered by matches
- "summary": a 2-3 sentence plain-English summary of the findings
- "matches": array of the flagged excerpts as described above (empty array if
  no notable matches found)

Text to analyze:
\"\"\"
{text}
\"\"\"

Respond with ONLY a JSON object (no markdown, no commentary) with exactly these
keys: "originality_percentage", "plagiarism_percentage", "summary", "matches"
(each match an object with "excerpt", "similarity_percentage",
"source_description", "source_url")."""

    if genai_client:
        try:
            response = genai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            return _extract_json_object(response.text), True
        except Exception:
            # Live grounded search unavailable (quota/billing) - fall through
            # to a non-grounded assessment on OpenRouter instead.
            pass

    fallback_prompt = prompt.replace(
        "You are a plagiarism detection assistant with access to Google Search.",
        "You are a plagiarism detection assistant. Live web search is "
        "unavailable, so use your general knowledge to flag text that "
        "resembles widely known published content instead of live results.",
    )
    fallback_prompt += (
        '\n\nRespond with ONLY a JSON object (no markdown, no commentary) with '
        'exactly these keys: "originality_percentage" (int), '
        '"plagiarism_percentage" (int), "summary" (string), "matches" (array of '
        'objects with "excerpt", "similarity_percentage" (int), '
        '"source_description", "source_url").'
    )
    raw = _openrouter_generate(fallback_prompt, json_mode=True)
    data = _extract_json_object(raw)
    return PlagiarismReport(**data).model_dump(), False


@app.route('/plagiarism-checker')
def plagiarism_checker():
    return render_template('plagiarism_checker.html')


@app.route('/plagiarism-checker/check', methods=['POST'])
def plagiarism_checker_check():
    if not genai_client and not openrouter_client:
        return jsonify({"error": "Neither GEMINI_API_KEY nor OPENROUTER_API_KEY is configured on the server."}), 503

    if request.content_type and 'multipart/form-data' in request.content_type:
        exclude_citations = request.form.get('exclude_citations') == 'true'
        uploaded = request.files.get('file')
        if uploaded and uploaded.filename:
            try:
                text = _extract_text_from_upload(uploaded)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
        else:
            text = request.form.get('text') or ''
    else:
        data = request.get_json(silent=True) or {}
        text = data.get('text') or ''
        exclude_citations = bool(data.get('exclude_citations'))

    text = text.strip()
    if not text:
        return jsonify({"error": "Please paste some text or upload a document."}), 400
    if len(text) < 50:
        return jsonify({"error": "Please provide at least a few sentences to check."}), 400

    truncated = len(text) > MAX_PLAGIARISM_TEXT_CHARS
    text = text[:MAX_PLAGIARISM_TEXT_CHARS]

    try:
        report, live = _check_plagiarism_with_gemini(text, exclude_citations)
    except Exception as e:
        return jsonify({"error": f"Failed to check plagiarism: {e}"}), 502

    return jsonify({"report": report, "live_search": live, "truncated": truncated, "text": text})


@app.route('/plagiarism-checker/download/pdf', methods=['POST'])
def plagiarism_checker_download_pdf():
    data = request.get_json(silent=True) or {}
    text = data.get('text') or ''
    report = data.get('report') or {}

    if not report:
        return jsonify({"error": "No report to export."}), 400

    html = render_template(
        'plagiarism_report_pdf.html', report=report, text=text,
        generated_on=datetime.now().strftime('%B %d, %Y'),
    )
    try:
        pdf_bytes = _html_to_pdf_bytes(html)
    except Exception as e:
        return jsonify({"error": f"Failed to build PDF: {e}"}), 500

    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name='plagiarism-report.pdf',
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
