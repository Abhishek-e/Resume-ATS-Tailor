"""
LinkedIn profile optimiser.

The score is computed here, in plain Python, not asked of a model. Every point
traces to a rule you can read below, which is what makes the report auditable -
a number a language model invented would move between runs on identical input
and could not be explained to the user.

The model is used only for the rewrite suggestions, where judgement genuinely
helps and where the user reads the result before pasting it anywhere.

Input is pasted text rather than a profile URL: LinkedIn blocks automated
fetching of profiles, so anything claiming to read one from a link is either
scraping against their terms or not really reading it.
"""
import re
from collections import Counter

# Words too common to count as keywords - matching on these inflates every
# score and tells the user nothing.
STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'if', 'then', 'than', 'as', 'at', 'by',
    'for', 'from', 'in', 'into', 'of', 'on', 'to', 'with', 'without', 'within',
    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'am', 'do', 'does', 'did',
    'have', 'has', 'had', 'will', 'would', 'can', 'could', 'should', 'may',
    'might', 'must', 'shall', 'this', 'that', 'these', 'those', 'it', 'its',
    'we', 'our', 'you', 'your', 'i', 'my', 'me', 'they', 'their', 'them', 'he',
    'she', 'his', 'her', 'who', 'whom', 'which', 'what', 'when', 'where', 'why',
    'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some',
    'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'too', 'very',
    'just', 'also', 'over', 'under', 'about', 'across', 'after', 'before',
    'between', 'during', 'through', 'up', 'down', 'out', 'off', 'again',
    'work', 'working', 'role', 'roles', 'team', 'teams', 'company', 'companies',
    'job', 'jobs', 'candidate', 'candidates', 'experience', 'experienced',
    'years', 'year', 'strong', 'good', 'great', 'excellent', 'ability', 'skills',
    'skill', 'including', 'etc', 'new', 'well', 'plus', 'must', 'looking',
}

ACTION_VERBS = {
    'led', 'built', 'shipped', 'designed', 'launched', 'grew', 'reduced',
    'increased', 'improved', 'delivered', 'owned', 'drove', 'created',
    'developed', 'implemented', 'migrated', 'automated', 'scaled', 'cut',
    'saved', 'negotiated', 'managed', 'mentored', 'rebuilt', 'introduced',
    'streamlined', 'resolved', 'analysed', 'analyzed', 'architected', 'founded',
    'established', 'coordinated', 'accelerated', 'eliminated', 'expanded',
}

# Section weights, summing to 100. Keyword match carries the most because it is
# what actually decides whether a recruiter's search surfaces the profile.
WEIGHTS = {
    'keywords': 30,
    'headline': 18,
    'about': 18,
    'experience': 22,
    'skills': 12,
}

HEADLINE_MIN, HEADLINE_MAX = 60, 220
ABOUT_MIN, ABOUT_GOOD = 300, 1200
SKILLS_TARGET = 25


def _words(text: str) -> list[str]:
    """
    Tokens, keeping the internal punctuation that is part of a real skill
    name - node.js, c++, c#, ci/cd's hyphenated cousins - but dropping it
    when it is just sentence punctuation, so "systems." and "systems" are not
    reported as two different missing keywords.
    """
    raw = re.findall(r"[a-zA-Z][a-zA-Z+#./\-']{1,}", (text or '').lower())
    return [w.rstrip(".-'/") for w in raw if w.rstrip(".-'/")]


def keywords(text: str, limit: int = 40) -> list[str]:
    """Content words by frequency, longest-first on ties."""
    counts = Counter(
        w for w in _words(text)
        if w not in STOPWORDS and len(w) > 2
    )
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))
    return [w for w, _n in ranked[:limit]]


def _pct(value, ceiling):
    return max(0.0, min(1.0, value / ceiling if ceiling else 0.0))


def _score_headline(headline: str, target_terms: set) -> dict:
    text = (headline or '').strip()
    length = len(text)
    issues, wins = [], []

    if not text:
        return {"score": 0.0, "issues": ["No headline at all — this is the single most "
                                         "searched field on the profile."], "wins": []}

    if length < HEADLINE_MIN:
        issues.append(f"Headline is {length} characters; LinkedIn allows 220 and the "
                      f"extra room is free keyword space.")
        length_score = _pct(length, HEADLINE_MIN)
    elif length > HEADLINE_MAX:
        issues.append(f"Headline is {length} characters — it will be truncated in search "
                      f"results past about 220.")
        length_score = 0.8
    else:
        wins.append(f"Headline length ({length} characters) uses the field well.")
        length_score = 1.0

    hits = target_terms & set(_words(text))
    if target_terms:
        keyword_score = _pct(len(hits), max(3, len(target_terms) * 0.15))
        if hits:
            wins.append("Headline already carries: " + ", ".join(sorted(hits)[:6]) + ".")
        else:
            issues.append("Headline shares no wording with the roles you are targeting.")
    else:
        keyword_score = 0.5

    separated = bool(re.search(r'[|•·—\-]', text))
    if separated:
        wins.append("Headline is segmented, so it scans quickly.")
    else:
        issues.append("Headline reads as one phrase — separating role, specialism and "
                      "result with | makes it scannable.")

    score = length_score * 0.4 + keyword_score * 0.45 + (1.0 if separated else 0.0) * 0.15
    return {"score": score, "issues": issues, "wins": wins}


def _score_about(about: str, target_terms: set) -> dict:
    text = (about or '').strip()
    length = len(text)
    issues, wins = [], []

    if not text:
        return {"score": 0.0, "issues": ["The About section is empty. It is indexed by "
                                         "search and it is the only place you control the "
                                         "narrative."], "wins": []}

    if length < ABOUT_MIN:
        issues.append(f"About is {length} characters; under ~300 rarely says enough to rank "
                      f"or to convince.")
        length_score = _pct(length, ABOUT_MIN)
    else:
        wins.append(f"About is a usable length ({length} characters).")
        length_score = min(1.0, 0.7 + 0.3 * _pct(length, ABOUT_GOOD))

    first_person = bool(re.search(r'\b(i|my|me)\b', text.lower()))
    if first_person:
        wins.append("Written in first person, which reads as a person rather than a CV.")
    else:
        issues.append("About is written in third person — first person performs better here.")

    hits = target_terms & set(_words(text))
    keyword_score = _pct(len(hits), max(5, len(target_terms) * 0.3)) if target_terms else 0.5
    if target_terms and not hits:
        issues.append("About shares no wording with your target roles.")
    elif hits:
        wins.append(f"About covers {len(hits)} target term{'' if len(hits) == 1 else 's'}.")

    cta = bool(re.search(r'(reach out|get in touch|contact me|open to|connect with me|'
                         r'message me|hiring|available for|email me)', text.lower()))
    if cta:
        wins.append("Ends with a clear way to start a conversation.")
    else:
        issues.append("No call to action — say what you want next and how to reach you.")

    score = length_score * 0.3 + keyword_score * 0.4 + \
        (1.0 if first_person else 0.0) * 0.15 + (1.0 if cta else 0.0) * 0.15
    return {"score": score, "issues": issues, "wins": wins}


def _score_experience(experience: str, target_terms: set) -> dict:
    text = (experience or '').strip()
    issues, wins = [], []
    if not text:
        return {"score": 0.0, "issues": ["No experience pasted, so nothing to assess."],
                "wins": []}

    lines = [l.strip(' -•\t') for l in text.splitlines() if l.strip(' -•\t')]
    bullets = [l for l in lines if len(l) > 25]

    if len(bullets) < 3:
        issues.append(f"Only {len(bullets)} substantial bullet{'' if len(bullets) == 1 else 's'} "
                      f"— aim for 3-5 per recent role.")
    else:
        wins.append(f"{len(bullets)} bullets give recruiters something to read.")
    volume_score = _pct(len(bullets), 6)

    quantified = [b for b in bullets if re.search(r'\d', b)]
    quant_ratio = len(quantified) / len(bullets) if bullets else 0
    if quant_ratio < 0.4:
        issues.append(f"Only {len(quantified)} of {len(bullets)} bullets contain a number. "
                      f"Figures are the difference between a claim and evidence.")
    else:
        wins.append(f"{len(quantified)} of {len(bullets)} bullets are quantified.")

    strong = [b for b in bullets if b.split() and b.split()[0].lower().strip('.,') in ACTION_VERBS]
    verb_ratio = len(strong) / len(bullets) if bullets else 0
    if verb_ratio < 0.5:
        issues.append("Most bullets do not open with an action verb — start with what you "
                      "did, not with 'Responsible for'.")
    else:
        wins.append("Bullets open with action verbs.")

    hits = target_terms & set(_words(text))
    keyword_score = _pct(len(hits), max(6, len(target_terms) * 0.35)) if target_terms else 0.5

    score = volume_score * 0.25 + quant_ratio * 0.3 + verb_ratio * 0.2 + keyword_score * 0.25
    return {"score": score, "issues": issues, "wins": wins}


def _score_skills(skills: str, target_terms: set) -> dict:
    listed = [s.strip() for s in re.split(r'[,\n;]+', skills or '') if s.strip()]
    issues, wins = [], []

    if not listed:
        return {"score": 0.0, "issues": ["No skills listed. LinkedIn allows 50 and recruiter "
                                         "filters read this field directly."], "wins": []}

    if len(listed) < SKILLS_TARGET:
        issues.append(f"{len(listed)} skills listed — LinkedIn allows 50, and each one is a "
                      f"filter you can appear in.")
    else:
        wins.append(f"{len(listed)} skills listed.")
    count_score = _pct(len(listed), SKILLS_TARGET)

    listed_words = set(_words(' '.join(listed)))
    hits = target_terms & listed_words
    keyword_score = _pct(len(hits), max(4, len(target_terms) * 0.2)) if target_terms else 0.5
    if hits:
        wins.append("Skills overlap your targets on: " + ", ".join(sorted(hits)[:6]) + ".")

    score = count_score * 0.45 + keyword_score * 0.55
    return {"score": score, "issues": issues, "wins": wins}


def analyse(profile: dict) -> dict:
    """
    Scores a pasted profile against target roles.

    Returns the overall percentage, a per-section breakdown, and the keyword
    gaps. Everything here is deterministic - the same input always produces
    the same report.
    """
    target = profile.get('target', '') or ''
    target_terms = set(keywords(target, limit=60))

    whole_profile = ' '.join([
        profile.get('headline', ''), profile.get('about', ''),
        profile.get('experience', ''), profile.get('skills', ''),
    ])
    profile_words = set(_words(whole_profile))

    covered = sorted(target_terms & profile_words)
    missing = sorted(target_terms - profile_words)

    sections = {
        'headline': _score_headline(profile.get('headline', ''), target_terms),
        'about': _score_about(profile.get('about', ''), target_terms),
        'experience': _score_experience(profile.get('experience', ''), target_terms),
        'skills': _score_skills(profile.get('skills', ''), target_terms),
    }

    keyword_score = (len(covered) / len(target_terms)) if target_terms else 0.0
    sections['keywords'] = {
        "score": keyword_score,
        "issues": ([f"{len(missing)} target terms appear nowhere on the profile."]
                   if missing else []),
        "wins": ([f"{len(covered)} of {len(target_terms)} target terms already present."]
                 if covered else []),
    }

    earned = sum(sections[name]['score'] * weight for name, weight in WEIGHTS.items())
    overall = round(earned)

    breakdown = []
    for name, weight in WEIGHTS.items():
        section = sections[name]
        breakdown.append({
            "key": name,
            "label": name.replace('_', ' ').title(),
            "weight": weight,
            "earned": round(section['score'] * weight),
            "percent": round(section['score'] * 100),
            "issues": section['issues'],
            "wins": section['wins'],
        })
    breakdown.sort(key=lambda s: s['percent'])

    return {
        "overall": overall,
        "grade": ("Strong" if overall >= 80 else
                  "Workable" if overall >= 60 else
                  "Needs work" if overall >= 40 else "Weak"),
        "breakdown": breakdown,
        "covered": covered,
        "missing": missing[:30],
        "issue_count": sum(len(s['issues']) for s in sections.values()),
        "win_count": sum(len(s['wins']) for s in sections.values()),
        "has_target": bool(target_terms),
    }
