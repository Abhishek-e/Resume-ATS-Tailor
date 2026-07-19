# AI Resume Agent — Feature Roadmap

This README is generated from the project discussion and outlines practical product ideas to evolve the app beyond keyword-based job fetching with Adzuna.

## Current Direction

You are using Adzuna API to fetch jobs based on keywords extracted from an uploaded resume.

## High-Impact Features to Add

### 1) Job–Resume Match Score (Must-have)
Rank each job by relevance:
- Skills overlap
- Title relevance
- Location fit
- Experience-level fit
- Salary fit (if available)

**Outcome:** Users see best-fit jobs first instead of an unranked list.

### 2) Skill Gap Analysis
For each recommended job, show:
- Matched skills ✅
- Missing skills ❌
- “Learn next” suggestions (top 3)

**Outcome:** App becomes advisory, not just search.

### 3) AI-Tailored Resume per Job
Generate resume variants for specific job descriptions:
- Rewrite summary
- Reorder bullets by relevance
- Add matching keywords naturally
- Keep ATS-safe formatting

**Outcome:** Better chances of shortlist/interview.

### 4) Cover Letter Generator
One-click personalized cover letter based on:
- Job description
- Candidate resume details
- Company + role context

**Outcome:** Faster, higher-quality applications.

### 5) Resume Quality + ATS Checks
Add scanner rules for:
- Missing contact links
- Weak action verbs
- Overly long bullets
- Lack of measurable impact
- ATS formatting risks (tables/icons/multi-column)

**Outcome:** Improves resume quality before applying.

### 6) Smart Filters + Preferences
User preferences:
- Remote / hybrid / onsite
- City / country
- Salary range
- Visa sponsorship
- Industry / company size

**Outcome:** Personalized and practical results.

### 7) Duplicate & Stale Job Cleanup
- Deduplicate the same job across sources
- Hide stale/expired jobs
- Add freshness indicators (e.g., posted X days ago)

**Outcome:** Cleaner, more trustworthy job list.

### 8) Job Tracker Board
Track pipeline stages:
- Saved
- Applied
- Interview
- Rejected
- Offer

Plus notes, deadlines, and reminders.

**Outcome:** End-to-end workflow in one app.

### 9) Application Assistant
Per job, generate:
- Likely interview questions
- Tailored elevator pitch
- Missing-doc checklist

**Outcome:** Better preparation and confidence.

### 10) Learning Plan from Skill Gaps
Create a 2–4 week upskilling plan:
- Topic sequence
- Mini projects
- Recommended resources

**Outcome:** Clear growth path to unlock better roles.

## Advanced Differentiators

- **Multi-agent pipeline:** Separate agents for parsing, scoring, and rewriting.
- **Explainable matching (RAG):** “Why this job matches you” grounded in JD + resume.
- **Feedback learning loop:** User marks relevant/not relevant and improves ranking.
- **Market insights dashboard:** In-demand skills, salary trends, role growth.

## Suggested Build Roadmap

1. Match scoring + ranking
2. Skill-gap analysis
3. Tailored resume bullets
4. Job tracker
5. Cover letter + interview prep

## Environment & Security Notes

Use environment variables for Adzuna credentials:
- `ADZUNA_APP_ID`
- `ADZUNA_API_KEY`

Never commit real secrets to GitHub. Keep local values in `.env` and production values in repository/deployment secrets.

---

If needed, this README can be expanded with architecture diagrams, API routes, DB schema, and prompt templates for each feature.
