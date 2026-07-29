"""The resume template catalogue and the ATS check behind each score.

Three templates are open to everyone. Seven more are the ATS pack: same
single-column, parser-safe skeleton, different typography and section order,
each one scored by `ats_score()` rather than given a number by hand.

The scorer reads the *rendered* HTML, so a template cannot claim a rating its
markup does not earn - if someone later adds a layout table or shrinks the body
copy to 8px, the badge on the page drops on the next request.
"""

import re

FREE_TEMPLATES = ['modern', 'classic', 'minimal']

# Section keys the shared skeleton knows how to emit. Order is per template -
# a graduate CV leads with education, a consultant CV leads with achievements.
ALL_SECTIONS = ['summary', 'skills', 'experience', 'education', 'certifications', 'projects']

TEMPLATES = {
    'modern': {
        'name': 'Modern',
        'blurb': 'Navy headings with pill-style skills. The default.',
        'tier': 'free',
        'sections': ['summary', 'skills', 'experience', 'education', 'certifications', 'projects'],
        'standalone': True,
    },
    'classic': {
        'name': 'Classic',
        'blurb': 'Serif, centred, conservative. Reads well in law and finance.',
        'tier': 'free',
        'sections': ALL_SECTIONS,
        'standalone': True,
    },
    'minimal': {
        'name': 'Minimal',
        'blurb': 'Plain type, generous space, nothing decorative.',
        'tier': 'free',
        'sections': ALL_SECTIONS,
        'standalone': True,
    },

    # --- The ATS pack -----------------------------------------------------
    'executive': {
        'name': 'Executive',
        'blurb': 'Senior-leadership layout: summary first, achievements up front.',
        'tier': 'ats',
        'sections': ['summary', 'experience', 'skills', 'education', 'certifications', 'projects'],
    },
    'recruiter': {
        'name': 'Recruiter',
        'blurb': 'Built for a six-second skim - heavy headings, wide leading.',
        'tier': 'ats',
        'sections': ['summary', 'skills', 'experience', 'education', 'certifications', 'projects'],
    },
    'technical': {
        'name': 'Technical',
        'blurb': 'Skills block above experience, for engineering keyword matches.',
        'tier': 'ats',
        'sections': ['skills', 'summary', 'experience', 'projects', 'education', 'certifications'],
    },
    'compact': {
        'name': 'Compact',
        'blurb': 'Tight leading for long careers that must stay on one page.',
        'tier': 'ats',
        'sections': ['summary', 'skills', 'experience', 'education', 'certifications', 'projects'],
    },
    'graduate': {
        'name': 'Graduate',
        'blurb': 'Education and projects lead - for first roles and internships.',
        'tier': 'ats',
        'sections': ['summary', 'education', 'projects', 'skills', 'experience', 'certifications'],
    },
    'consulting': {
        'name': 'Consulting',
        'blurb': 'Case-style entries with a clear dateline down the left.',
        'tier': 'ats',
        'sections': ['summary', 'experience', 'education', 'skills', 'certifications', 'projects'],
    },
    'federal': {
        'name': 'Public Sector',
        'blurb': 'Long-form and literal, the way government portals want it.',
        'tier': 'ats',
        'sections': ['summary', 'experience', 'education', 'certifications', 'skills', 'projects'],
    },
}

ATS_TEMPLATES = [k for k, v in TEMPLATES.items() if v['tier'] == 'ats']
VALID_TEMPLATES = set(TEMPLATES)


# --------------------------------------------------------------------------
# ATS scoring
#
# Each rule is something a real applicant tracking system trips over when it
# flattens a PDF back into text. Weights add to 100; a template keeps the
# points for every rule its rendered markup passes.
# --------------------------------------------------------------------------

def _no_layout_tables(html):
    """Multi-column tables are the single biggest parsing hazard: text is read
    cell by cell, so a two-column resume interleaves into nonsense."""
    return '<table' not in html.lower()


def _single_column(html):
    """Floats and absolute positioning produce the same interleaving as tables
    once the PDF is linearised."""
    css = _style_block(html)
    return not re.search(r'(float\s*:\s*(left|right)|position\s*:\s*absolute)', css)


def _standard_headings(html):
    """Parsers key off literal words. At least three of the canonical five
    have to appear as headings for the section split to survive."""
    text = _visible_text(html).lower()
    canonical = ['summary', 'experience', 'education', 'skills', 'certification', 'project']
    return sum(1 for word in canonical if word in text) >= 3


def _real_bullets(html):
    """<li> survives extraction as a line; a bullet glyph typed into a <div>
    often does not."""
    return '<li' in html.lower() or '<ul' not in html.lower()


def _readable_font_size(html):
    """Anything under 9px tends to come back from OCR fallbacks garbled."""
    sizes = [float(m) for m in re.findall(r'font-size\s*:\s*([\d.]+)px', _style_block(html))]
    return not sizes or min(sizes) >= 9


def _standard_font_family(html):
    """Stick to the families every PDF reader has metrics for."""
    css = _style_block(html).lower()
    families = re.findall(r'font-family\s*:\s*([^;}]+)', css)
    safe = ('helvetica', 'arial', 'times', 'georgia', 'garamond', 'calibri',
            'verdana', 'tahoma', 'serif', 'sans-serif')
    return all(any(s in fam for s in safe) for fam in families) if families else True


def _no_images(html):
    """Text baked into a logo or a headshot is invisible to the parser, and
    photos get resumes auto-rejected in several markets."""
    return '<img' not in html.lower() and 'background-image' not in html.lower()


def _contact_is_text(html):
    """The contact block has to be selectable text, not an icon row."""
    text = _visible_text(html)
    return bool(re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)) or 'contact' in html.lower()


def _no_page_furniture(html):
    """xhtml2pdf @frame headers/footers repeat on every page and land in the
    middle of the extracted text."""
    css = _style_block(html)
    return '@frame' not in css and '-pdf-frame' not in css


def _skills_as_one_run(html):
    """Skills drawn as separate pills come back as isolated fragments, so a
    parser scoring "Python, SQL" as a phrase never sees one."""
    block = re.search(r'class="skills[^"]*"[^>]*>(.*?)</div>', html, re.S | re.I)
    if not block:
        return True
    return len(re.findall(r'<span', block.group(1), re.I)) <= 3


def _standard_entry_separator(html):
    """Title and employer on one line should be split by a comma or a pipe.
    Dash and slash separators are what most parsers mis-attribute."""
    titles = re.findall(r'class="entry-title"[^>]*>(.*?)</div>', html, re.S | re.I)
    return not any(re.search(r'\s(?:&mdash;|—|–|/)\s', t) for t in titles)


RULES = [
    (16, 'Single-column flow', _single_column),
    (15, 'No layout tables', _no_layout_tables),
    (13, 'Standard section headings', _standard_headings),
    (11, 'Real bullet lists', _real_bullets),
    (9, 'Selectable contact details', _contact_is_text),
    (9, 'No images or graphics', _no_images),
    (8, 'Body text 9px or larger', _readable_font_size),
    (7, 'Parser-safe font family', _standard_font_family),
    (5, 'No repeating headers/footers', _no_page_furniture),
    (4, 'Skills as one text run', _skills_as_one_run),
    (3, 'Comma-separated title and employer', _standard_entry_separator),
]


def _style_block(html):
    return ' '.join(re.findall(r'<style[^>]*>(.*?)</style>', html, re.S | re.I))


def _visible_text(html):
    without_style = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.S | re.I)
    return re.sub(r'<[^>]+>', ' ', without_style)


def ats_score(html):
    """Score rendered resume HTML 0-100 and say which rules it passed."""
    passed, failed, score = [], [], 0
    for weight, label, rule in RULES:
        if rule(html):
            score += weight
            passed.append(label)
        else:
            failed.append(label)
    return {'score': score, 'passed': passed, 'failed': failed}


def catalogue(render_html):
    """Build the list the Generate CV page renders.

    `render_html(key)` is injected rather than imported so this module stays
    free of Flask - it is called once per template with a sample resume and
    the resulting markup is what gets scored.
    """
    rows = []
    for key, spec in TEMPLATES.items():
        result = ats_score(render_html(key))
        rows.append({
            'key': key,
            'name': spec['name'],
            'blurb': spec['blurb'],
            'tier': spec['tier'],
            'ats': result['score'],
            'passed': result['passed'],
            'failed': result['failed'],
        })
    return rows


# A resume with every section populated, used only to render each template for
# scoring. Real candidate data never touches this.
SAMPLE_RESUME = {
    'full_name': 'Sample Candidate',
    'target_role': 'Senior Analyst',
    'contact': {
        'email': 'sample@example.com', 'phone': '+1 555 010 0100',
        'location': 'Austin, TX', 'linkedin': 'linkedin.com/in/sample',
        'portfolio': 'sample.dev',
    },
    'summary': 'Analyst with eight years in demand forecasting and pricing.',
    'skills': ['SQL', 'Python', 'Forecasting', 'Tableau'],
    'experience': [{
        'title': 'Senior Analyst', 'company': 'Northwind', 'dates': '2021 - Present',
        'bullets': ['Cut forecast error 18% across 400 SKUs.',
                    'Built the pricing model now used by three regions.'],
    }],
    'education': [{'degree': 'BSc Economics', 'school': 'State University', 'dates': '2013 - 2017'}],
    'certifications': ['Certified Analytics Professional'],
    'projects': [{'name': 'openforecast', 'description': 'Open-source demand forecasting toolkit.'}],
}
