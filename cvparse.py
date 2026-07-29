"""Pull structured fields out of an uploaded CV.

This is deliberately rule-based rather than a model call. The Build tab needs
the answer in the time it takes to pick a file, it has to work when
OPENROUTER_API_KEY is missing or rejected, and a wrong guess here is cheap -
every field lands in an editable input the candidate reviews before generating.

The strategy is section-first: find the headings a resume actually uses, slice
the document on them, and only fall back to whole-document heuristics for the
contact block, which usually sits above the first heading.
"""

import re

# Heading synonyms, longest-first within each bucket so "work experience"
# matches before "experience". Order of the dict is not significant - matching
# is done per line against every alias.
SECTION_ALIASES = {
    'summary': [
        'professional summary', 'career summary', 'executive summary',
        'summary of qualifications', 'personal statement', 'career objective',
        'about me', 'profile summary', 'objective', 'summary', 'profile',
    ],
    'skills': [
        'technical skills', 'core competencies', 'key skills', 'skills & abilities',
        'areas of expertise', 'technologies', 'tech stack', 'competencies',
        'expertise', 'skills',
    ],
    'experience': [
        'professional experience', 'work experience', 'employment history',
        'work history', 'career history', 'relevant experience', 'experience',
        'employment',
    ],
    'education': [
        'education & training', 'academic background', 'education', 'academics',
        'qualifications',
    ],
    'certifications': [
        'certifications & licenses', 'licenses & certifications', 'certifications',
        'certificates', 'licenses', 'courses & certifications', 'awards & certifications',
    ],
    'projects': [
        'personal projects', 'selected projects', 'key projects', 'projects',
        'portfolio',
    ],
}

# Sections we parse but do not surface in the Build form. Listed so their
# content is cut away from whatever section precedes them instead of being
# swept into it.
IGNORED_SECTIONS = [
    'references', 'interests', 'hobbies', 'languages', 'publications',
    'volunteering', 'volunteer experience', 'achievements', 'awards',
    'extracurricular activities', 'activities',
]

EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
# Deliberately strict: 7+ digits with optional separators. A looser pattern
# eats years ("2019 - 2022") and postcodes out of the header block.
PHONE_RE = re.compile(r'(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3,5}[\s.-]?\d{3,5}(?:[\s.-]?\d{2,4})?')
LINKEDIN_RE = re.compile(r'(?:https?://)?(?:[\w-]+\.)?linkedin\.com/[\w%/.+-]+', re.I)
URL_RE = re.compile(r'(?:https?://|www\.)[\w.-]+\.[a-z]{2,}(?:/[\w%./+-]*)?', re.I)
# A personal site is often written bare - "jordanlee.dev", "sam.github.io". Too
# loose to run over the whole document (it would match "e.g." style debris), so
# it is only applied to the header block, and only for TLDs people actually put
# on a resume.
BARE_DOMAIN_RE = re.compile(
    r'\b[\w-]+(?:\.[\w-]+)*\.(?:com|dev|io|me|net|org|co|app|xyz|page|site|tech|design|studio)'
    r'(?:/[\w%./+-]*)?\b', re.I
)
# "City, ST" / "City, Country" - two or three comma-separated words, no digits.
LOCATION_RE = re.compile(
    r'^[A-Z][a-zA-Z.\-\' ]{1,28},\s*(?:[A-Z][a-zA-Z.\-\' ]{1,28}|[A-Z]{2})'
    r'(?:,\s*[A-Z][a-zA-Z.\-\' ]{1,28})?$'
)

BULLET_CHARS = '•·◦‣▪–—*-‧'

# Extracting text from a PDF hands back the "no glyph" box wherever the source
# font could not draw a character. Sitting between two word characters it was a
# hyphen - "data<box>driven"; anywhere else it was a bullet or other list
# decoration, which the bullet handling below already knows how to strip. The
# private-use range covers Word's Wingdings bullets.
NOTDEF_CHARS = '■□�-'
_NOTDEF_AS_HYPHEN_RE = re.compile(rf'(?<=\w)[{NOTDEF_CHARS}](?=\w)')
_NOTDEF_RE = re.compile(rf'[{NOTDEF_CHARS}]')


def _repair_glyphs(text):
    return _NOTDEF_RE.sub('•', _NOTDEF_AS_HYPHEN_RE.sub('-', text))


def _clean(line):
    return line.replace(' ', ' ').strip()


def _heading_key(line):
    """Return the section key a line announces, or None if it is body text.

    A heading is short, has no sentence punctuation, and matches an alias
    outright once decoration (colons, underscores, leading bullets) is gone.
    """
    text = _clean(line).strip(':').strip('_').strip('-').strip()
    if not text or len(text) > 45:
        return None
    lowered = re.sub(r'[^a-z& ]+', '', text.lower()).strip()
    if not lowered:
        return None

    for key, aliases in SECTION_ALIASES.items():
        if lowered in aliases:
            return key
    if lowered in IGNORED_SECTIONS:
        return '_ignored'
    return None


def _split_sections(lines):
    """Slice the document into {section_key: [lines]} plus a 'header' block."""
    sections = {'header': []}
    current = 'header'
    for line in lines:
        key = _heading_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _strip_bullet(line):
    return _clean(line).lstrip(BULLET_CHARS).strip()


def _nonempty(lines):
    return [_clean(l) for l in lines if _clean(l)]


def _contact_parts(line):
    """Contact rows are usually one line of several values divided by pipes,
    bullets or wide gaps. Each value has to be tested on its own - a location
    only matches when it is not sharing the line with an email and a phone."""
    return [p.strip() for p in re.split(r'[|•·]|\s{3,}|\s+[-–—]\s+', _clean(line)) if p.strip()]


def _find_portfolio(header_lines, whole_text, email):
    def usable(url):
        low = url.lower()
        if 'linkedin.com' in low:
            return False
        # The domain half of an email address is not a portfolio.
        return not (email and low in email.lower())

    for match in URL_RE.finditer(whole_text):
        if usable(match.group(0)):
            return match.group(0)

    for line in header_lines[:12]:
        stripped = EMAIL_RE.sub(' ', _clean(line))
        for match in BARE_DOMAIN_RE.finditer(stripped):
            if usable(match.group(0)):
                return match.group(0)
    return ''


def _extract_contact(header_lines, whole_text):
    """Email/phone/links come from the whole document, name and location from
    the header - a footer repeat of the email is still the right email, but the
    first plausible name line is only ever at the top."""
    contact = {'email': '', 'phone': '', 'location': '', 'linkedin': '', 'portfolio': ''}

    email = EMAIL_RE.search(whole_text)
    if email:
        contact['email'] = email.group(0).rstrip('.')

    linkedin = LINKEDIN_RE.search(whole_text)
    if linkedin:
        contact['linkedin'] = linkedin.group(0)

    contact['portfolio'] = _find_portfolio(header_lines, whole_text, contact['email'])

    # Phone hunting is limited to the header: a bare digit run in the body is
    # far more likely to be a metric in an achievement bullet.
    for line in header_lines[:12]:
        candidate = _clean(line)
        if EMAIL_RE.search(candidate):
            candidate = EMAIL_RE.sub(' ', candidate)
        for match in PHONE_RE.finditer(candidate):
            digits = re.sub(r'\D', '', match.group(0))
            if 7 <= len(digits) <= 15:
                contact['phone'] = match.group(0).strip(' .-')
                break
        if contact['phone']:
            break

    for line in header_lines[:12]:
        for part in _contact_parts(line):
            if LOCATION_RE.match(part):
                contact['location'] = part
                break
        if contact['location']:
            break

    return contact


def _looks_like_name(line):
    text = _clean(line)
    if not text or len(text) > 48:
        return False
    if EMAIL_RE.search(text) or URL_RE.search(text) or re.search(r'\d', text):
        return False
    words = text.split()
    if not 1 < len(words) <= 5:
        return False
    # Accept "Jordan Lee" and "JORDAN LEE", reject "Led a team of engineers".
    return all(w[0].isupper() for w in words if w[:1].isalpha())


def _extract_name_and_role(header_lines):
    lines = _nonempty(header_lines)
    name = ''
    role = ''
    name_index = None

    for i, line in enumerate(lines[:6]):
        if _looks_like_name(line):
            name = line
            name_index = i
            break

    if name_index is not None:
        for line in lines[name_index + 1:name_index + 4]:
            if EMAIL_RE.search(line) or URL_RE.search(line):
                continue
            if LOCATION_RE.match(line):
                continue
            if re.sub(r'\D', '', line) and len(re.sub(r'\D', '', line)) >= 7:
                continue
            # A job title is a noun phrase, not a sentence: no closing full
            # stop, and short. Without this, a one-line bio under the name
            # ("Nothing else here really.") lands in Target Role.
            if line.endswith(('.', '!', '?')) or len(line.split()) > 7:
                continue
            if 2 <= len(line) <= 60:
                role = line.strip('|').strip('-').strip()
                break

    if name.isupper():
        name = name.title()
    return name, role


def _extract_skills(lines):
    """Skills arrive as commas, bullets, pipes or "Category: a, b, c" rows.
    Everything is flattened to one comma-separated string for the textarea."""
    skills = []
    for line in _nonempty(lines):
        text = _strip_bullet(line)
        if not text:
            continue
        # "Languages: Python, Go" -> keep only the right-hand side.
        if ':' in text and len(text.split(':', 1)[0]) <= 30:
            text = text.split(':', 1)[1]
        for part in re.split(r'[,;|•·]|\s{3,}', text):
            part = part.strip(' .')
            if 1 < len(part) <= 40:
                skills.append(part)

    seen = set()
    unique = []
    for skill in skills:
        key = skill.lower()
        if key not in seen:
            seen.add(key)
            unique.append(skill)
    return ', '.join(unique[:40])


def _extract_block(lines):
    """Experience/education/projects keep their shape - the AI writer (and the
    deterministic fallback) both read them better as the original lines than as
    something we have flattened."""
    kept = []
    for line in lines:
        text = _clean(line)
        if not text:
            # Collapse runs of blank lines but keep entry separation.
            if kept and kept[-1] != '':
                kept.append('')
            continue
        kept.append(text)
    while kept and kept[-1] == '':
        kept.pop()
    return '\n'.join(kept)


def _extract_list_block(lines):
    items = [_strip_bullet(l) for l in _nonempty(lines)]
    return '\n'.join(i for i in items if i)


MAX_FIELD_CHARS = 4000


def parse_resume_text(text):
    """Return the Build-form field map plus a list of the fields we filled.

    Every value is a string, matching the form inputs one-for-one, so the front
    end can assign them without a translation layer.
    """
    text = _repair_glyphs((text or '').replace('\r\n', '\n').replace('\r', '\n'))
    lines = text.split('\n')
    sections = _split_sections(lines)

    header = sections.get('header', [])
    contact = _extract_contact(header, text)
    name, role = _extract_name_and_role(header)

    summary = _extract_block(sections.get('summary', []))
    if not summary:
        # No summary heading: an unlabelled paragraph in the header, below the
        # contact details, is the usual place a profile blurb hides.
        leftovers = [
            l for l in _nonempty(header)
            if l != name and l != role
            and not EMAIL_RE.search(l) and not URL_RE.search(l)
            and not LOCATION_RE.match(l)
            and len(l.split()) > 8
        ]
        summary = ' '.join(leftovers[:3])

    fields = {
        'full_name': name,
        'target_role': role,
        'email': contact['email'],
        'phone': contact['phone'],
        'location': contact['location'],
        'linkedin': contact['linkedin'],
        'portfolio': contact['portfolio'],
        'summary': summary,
        'skills': _extract_skills(sections.get('skills', [])),
        'experience': _extract_block(sections.get('experience', [])),
        'education': _extract_block(sections.get('education', [])),
        'certifications': _extract_list_block(sections.get('certifications', [])),
        'projects': _extract_block(sections.get('projects', [])),
    }

    fields = {k: (v or '')[:MAX_FIELD_CHARS] for k, v in fields.items()}
    filled = [k for k, v in fields.items() if v.strip()]
    return {'fields': fields, 'filled': filled}


# --------------------------------------------------------------------------
# Build-form input -> the resume shape the templates render.
#
# The reverse trip. Used when no model provider is configured: the candidate
# still gets a formatted, exportable resume, just in their own wording.
# --------------------------------------------------------------------------

DATE_RE = re.compile(
    r'((?:19|20)\d{2}\s*(?:[-–—to]+\s*(?:(?:19|20)\d{2}|present|current|now))?|'
    r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(?:19|20)?\d{2}'
    r'(?:\s*[-–—]+\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(?:19|20)?\d{2}|present|current))?)',
    re.I,
)


def _split_entries(block):
    """Split a free-text block into entries.

    A blank line is the strongest signal. Failing that, a line that is not a
    bullet starts a new entry - which is how most people type a job history
    into a textarea.
    """
    if not block.strip():
        return []

    if '\n\n' in block:
        chunks = [c for c in block.split('\n\n') if c.strip()]
    else:
        chunks, current = [], []
        for line in block.split('\n'):
            is_bullet = _clean(line)[:1] in BULLET_CHARS
            if current and not is_bullet:
                chunks.append('\n'.join(current))
                current = []
            current.append(line)
        if current:
            chunks.append('\n'.join(current))
    return [c for c in chunks if c.strip()]


ROLE_WORDS = (
    'engineer', 'developer', 'designer', 'manager', 'analyst', 'consultant',
    'scientist', 'architect', 'director', 'lead', 'head of', 'intern',
    'specialist', 'associate', 'administrator', 'officer', 'coordinator',
    'assistant', 'president', 'founder', 'accountant', 'nurse', 'teacher',
    'researcher', 'strategist', 'writer', 'editor', 'marketer', 'recruiter',
)


def _looks_like_job_title(text):
    low = (text or '').lower()
    return any(word in low for word in ROLE_WORDS)


def _parse_experience_entry(chunk):
    lines = _nonempty(chunk.split('\n'))
    if not lines:
        return None

    head = lines[0]
    bullets = [_strip_bullet(l) for l in lines[1:] if _strip_bullet(l)]

    dates = ''
    match = DATE_RE.search(head)
    if match:
        dates = match.group(0).strip(' ,-')
        head = head.replace(match.group(0), ' ')

    # The head line arrives in either order - the form asks for "Company, role"
    # but "Senior Engineer at Stripe" is just as common. Decide by looking for
    # a job-title word instead of trusting the order, and only fall back to the
    # form's own convention when neither half looks like a title.
    parts = [p.strip(' ,-–—|') for p in re.split(r'\s+[-–—|]\s+|,|\s+\bat\b\s+', head) if p.strip(' ,-–—|')]
    first = parts[0] if parts else ''
    second = parts[1] if len(parts) > 1 else ''

    if _looks_like_job_title(second):
        title, company = second, first
    elif _looks_like_job_title(first):
        title, company = first, second
    else:
        title, company = second or first, first if second else ''

    if not (title or company or bullets):
        return None
    return {'title': title, 'company': company, 'dates': dates, 'bullets': bullets}


def _parse_education_entry(chunk):
    line = ' '.join(_nonempty(chunk.split('\n')))
    if not line:
        return None
    dates = ''
    match = DATE_RE.search(line)
    if match:
        dates = match.group(0).strip(' ,-')
        line = line.replace(match.group(0), ' ')
    parts = [p.strip(' ,-–—|') for p in re.split(r'\s+[-–—|]\s+|,', line) if p.strip(' ,-–—|')]
    return {
        'degree': parts[0] if parts else '',
        'school': ', '.join(parts[1:]) if len(parts) > 1 else '',
        'dates': dates,
    }


def _parse_project_entry(chunk):
    lines = _nonempty(chunk.split('\n'))
    if not lines:
        return None
    head = _strip_bullet(lines[0])
    rest = ' '.join(_strip_bullet(l) for l in lines[1:])
    # "name - description" on one line is the common shorthand.
    split = re.split(r'\s+[-–—:]\s+', head, maxsplit=1)
    name = split[0].strip()
    description = (split[1].strip() if len(split) > 1 else '')
    description = ' '.join(filter(None, [description, rest]))
    return {'name': name, 'description': description} if name else None


def structure_resume(input_data):
    """Turn the Build form's raw strings into the template resume shape."""
    get = lambda k: (input_data.get(k) or '').strip()  # noqa: E731

    skills = [s.strip() for s in re.split(r'[,;\n•·|]', get('skills')) if s.strip()]
    certifications = [_strip_bullet(l) for l in get('certifications').split('\n') if _strip_bullet(l)]

    experience = [e for e in (_parse_experience_entry(c) for c in _split_entries(get('experience'))) if e]
    education = [e for e in (_parse_education_entry(c) for c in _split_entries(get('education'))) if e]
    projects = [p for p in (_parse_project_entry(c) for c in _split_entries(get('projects'))) if p]

    summary = get('summary')
    if not summary:
        role = get('target_role')
        top = ', '.join(skills[:4])
        summary = ' '.join(filter(None, [
            f"{role}." if role else '',
            f"Working with {top}." if top else '',
        ])).strip()

    return {
        'full_name': get('full_name'),
        'target_role': get('target_role'),
        'contact': {
            'email': get('email'), 'phone': get('phone'), 'location': get('location'),
            'linkedin': get('linkedin'), 'portfolio': get('portfolio'),
        },
        'summary': summary,
        'skills': skills,
        'experience': experience,
        'education': education,
        'certifications': certifications,
        'projects': projects,
    }
