import os
import sys
import re
import json
import logging
import argparse
import subprocess
from datetime import datetime
import pandas as pd
from google import genai
from google.genai import types
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

def load_config():
    config_path = "customizations/configuration.json"
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            "Ensure customizations/configuration.json exists and is valid JSON."
        )
    with open(config_path, "r") as f:
        return json.load(f)

config = load_config()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

MODEL_NAME = config["model"]
SCRAPED_FILE = "scraped_jobs.xlsx"
RANKED_FILE = "matched_results/ranked_jobs.xlsx"
PROMPT_FILE = "customizations/cover_letter_prompt.txt"
NEW_TEMPLATE_FILE = "customizations/newtemplate.tex"
RESUME_FILE = "customizations/resume.txt"
OUTPUT_DIR = "cover_letters"

os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate a tailored cover letter for a specific job",
        epilog="Examples:\n  python generate_cover_letter.py 458420\n  python generate_cover_letter.py --all\n  python generate_cover_letter.py --custom",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("job_id", type=str, nargs='?', default=None, help="Job ID from scraped_jobs.xlsx")
    parser.add_argument("--all", action="store_true", help="Generate cover letters for ALL ranked jobs")
    parser.add_argument("--custom", action="store_true", help="Paste job info manually")
    parser.add_argument("--model", type=str, default=MODEL_NAME, help=f"Gemini model (default: {MODEL_NAME})")
    parser.add_argument("--no-pdf", action="store_true", help="Skip PDF generation, output .tex only")
    args = parser.parse_args()
    if not args.all and not args.custom and not args.job_id:
        parser.error("Provide a job_id, use --all, or use --custom")
    return args


def get_custom_job():
    """Parse pasted WaterlooWorks job posting text automatically."""
    print("\n📝 CUSTOM COVER LETTER MODE")
    print("="*60)
    print("Paste the full WaterlooWorks job posting text below.")
    print("Type END on a new line when done:\n")

    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    raw_text = "\n".join(lines)

    # Parse structured fields from WaterlooWorks format
    job = parse_waterlooworks_posting(raw_text)

    if not job.get('Job Title'):
        print("\n⚠️ Could not auto-parse. Falling back to manual input.")
        job['Job Title'] = input("Job Title: ").strip()
        job['Organization'] = input("Company Name: ").strip()
        job['City'] = input("City: ").strip() or "N/A"
        job['Job Description'] = raw_text

    # Extract job ID from the detailed posting section
    # It appears right after "Return to Job Search Overview" / "fiber_manual_record"
    job_id = None
    id_match = re.search(r'Return to Job Search Overview\s*(?:fiber_manual_record\s*)*(\d{5,7})', raw_text)
    if id_match:
        job_id = id_match.group(1)
    else:
        # Fallback: look for ID right before "Job Posting Information"
        id_match = re.search(r'(\d{5,7})\s*\n.*?\n.*?\nJob Posting Information', raw_text, re.DOTALL)
        if id_match:
            job_id = id_match.group(1)

    if not job_id:
        job_id = input("Could not find Job ID. Enter it manually: ").strip()

    # Check if cover letter already exists
    existing = get_existing_job_ids()
    if job_id in existing:
        print(f"\n⚠️  Cover letter for job {job_id} already exists!")
        overwrite = input("Overwrite? (y/n): ").strip().lower()
        if overwrite != 'y':
            print("Skipping. Exiting.")
            sys.exit(0)

    print(f"\n✅ Parsed: {job['Job Title']} @ {job['Organization']} ({job.get('City', 'N/A')}) [ID: {job_id}]")
    return job_id, job


def parse_waterlooworks_posting(text):
    """Extract structured fields from raw WaterlooWorks job posting text."""
    job = {}

    # Extract labeled fields using "Label:\n Value" or "Label: Value" patterns
    field_map = {
        'Job Title': 'Job Title',
        'Organization': 'Organization',
        'Job - City': 'City',
        'Division': 'Division',
    }

    for field_label, key in field_map.items():
        # Match "Field Label:\nValue" (WaterlooWorks format: label on one line, value on next)
        pattern = re.compile(rf'^{re.escape(field_label)}:\s*\n(.+?)$', re.MULTILINE)
        match = pattern.search(text)
        if match:
            job[key] = match.group(1).strip()

    # Extract job description - everything from "Job Summary:" to the next major section
    summary_match = re.search(
        r'Job Summary:\s*\n(.*?)(?:\n(?:Job Responsibilities|Required Skills|Transportation|Compensation|Targeted Degrees|Application Information|Application Deadline|Company Information):)',
        text, re.DOTALL
    )
    if summary_match:
        desc = summary_match.group(1).strip()
    else:
        # Fallback: grab everything after "Job Summary:"
        summary_match = re.search(r'Job Summary:\s*\n(.*)', text, re.DOTALL)
        desc = summary_match.group(1).strip() if summary_match else text

    # Also grab responsibilities and required skills if present
    resp_match = re.search(r'Job Responsibilities:\s*\n(.*?)(?:\n(?:Required Skills|Transportation|Compensation|Targeted Degrees|Application Information):)', text, re.DOTALL)
    skills_match = re.search(r'Required Skills:\s*\n(.*?)(?:\n(?:Transportation|Compensation|Targeted Degrees|Application Information):)', text, re.DOTALL)

    full_desc = desc
    if resp_match:
        full_desc += "\n\nResponsibilities:\n" + resp_match.group(1).strip()
    if skills_match:
        full_desc += "\n\nRequired Skills:\n" + skills_match.group(1).strip()

    job['Job Description'] = full_desc
    return job


def find_job(job_id):
    """Look up job details from ranked or scraped data."""
    # Try ranked file first (has match score)
    for filepath in [RANKED_FILE, SCRAPED_FILE]:
        if os.path.exists(filepath):
            df = pd.read_excel(filepath)
            df['Job ID'] = df['Job ID'].astype(str).str.strip()
            match = df[df['Job ID'] == job_id.strip()]
            if not match.empty:
                logger.info(f"📂 Found job {job_id} in {filepath}")
                return match.iloc[0].to_dict()

    return None


def load_prompt():
    """Load cover letter generation prompt."""
    if not os.path.exists(PROMPT_FILE):
        logger.error(f"❌ Prompt file '{PROMPT_FILE}' not found!")
        return None
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()


def load_resume():
    """Load resume text for context."""
    if not os.path.exists(RESUME_FILE):
        logger.warning(f"⚠️ Resume file '{RESUME_FILE}' not found, continuing without it.")
        return ""
    with open(RESUME_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()



def generate_tailored_paragraph(job, prompt, model_name=MODEL_NAME):
    """Generate only the tailored paragraph for the new template."""
    job_title = job.get('Job Title', 'Unknown')
    org = job.get('Organization', 'Unknown')

    logger.info(f"✍️ Generating tailored paragraph for: {job_title} @ {org}")

    resume = load_resume()

    job_context = f"""
JOB TITLE: {job_title}
ORGANIZATION: {org}
CITY: {job.get('City', 'N/A')}
DEPARTMENT: {job.get('Division', 'N/A')}

JOB DESCRIPTION:
{job.get('Job Description', 'N/A')}
"""

    full_prompt = f"""
Here is the job I am applying to:

{job_context}

---

Here is my resume for context:
{resume}

---

IMPORTANT CONTEXT: The rest of the cover letter already covers the following topics. DO NOT repeat any of these:
- My Scratch origin story and early coding
- Quota (DeltaHacks, AST parsing, RAG chatbot)
- Nebula (React Native, FastAPI, semantic search)
- SolveXchange volunteer work
- Pinpoint internship (React, Figma, Korea)
- UW Orbital (React mission control, REST APIs, test coverage)
- Euclid Math Contest, CCC distinction
- Hack The Ridge, Ignition Hacks leadership
- Music background (clarinet, conducting)
- The closing line about building things that matter

---

I need you to write ONE tailored paragraph (3-5 sentences) that goes between the leadership section and the closing of the cover letter.;

This paragraph must:
- Be SPECIFIC to {org} and the {job_title} role. Research what the company does, their product/mission, and what makes them unique
- Reference something concrete about the company: their product, tech stack, a specific challenge they solve, their market, or their mission
- Explain why I genuinely want to work there and how my skills map to their specific needs
- Sound like a real person wrote it for THIS company, not a template
- Be SHORT (3-5 sentences max). The entire cover letter must fit on ONE PAGE with a header, logo, and signature
- Do NOT repeat anything already covered in the rest of the letter (listed above)
- Use **double asterisks** for 1-2 bold key phrases max
- Do NOT use em dashes, the word "passionate", or clichés
- Use the specific technologies/languages from the job description if I have experience with them

IMPORTANT: Return your response as JSON with this exact field:
{{
    "tailored_paragraph": "The 3-5 sentence tailored paragraph. No greeting, no closing."
}}
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=full_prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            try:
                return json.loads(response.text)
            except json.JSONDecodeError:
                match = re.search(r'\{[\s\S]*\}', response.text)
                if match:
                    return json.loads(match.group())
                logger.warning(f"⚠️ JSON parse failed (attempt {attempt + 1}/3), retrying...")
        except Exception as e:
            logger.warning(f"⚠️ Attempt {attempt + 1}/3 failed: {e}")
        import time
        time.sleep(2)

    logger.error("❌ Tailored paragraph generation failed after 3 attempts")
    return None


def escape_latex(text):
    """Escape special LaTeX characters in text."""
    # Order matters: & must be first since \ replacement adds &
    replacements = {
        '\\': r'\textbackslash{}',
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\textasciicircum{}',
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def escape_latex_preserving_commands(text):
    """Escape LaTeX special chars but preserve \\textbf{} commands."""
    bold_parts = []
    def save_bold(m):
        bold_parts.append(m.group(0))
        return f"ZZBOLD{len(bold_parts) - 1}ZZ"

    text = re.sub(r'\\textbf\{[^}]*\}', save_bold, text)
    text = escape_latex(text)
    for i, part in enumerate(bold_parts):
        text = text.replace(f"ZZBOLD{i}ZZ", part)
    return text



def compile_pdf(tex_path):
    """Compile LaTeX to PDF using xelatex."""
    output_dir = os.path.dirname(tex_path)

    try:
        result = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-output-directory", output_dir, tex_path],
            capture_output=True, text=True, timeout=30
        )
        pdf_path = tex_path.replace('.tex', '.pdf')
        if os.path.exists(pdf_path):
            logger.info(f"✅ PDF generated: {pdf_path}")
            # Clean up aux files
            for ext in ['.aux', '.log', '.out']:
                aux = tex_path.replace('.tex', ext)
                if os.path.exists(aux):
                    os.remove(aux)
            return pdf_path
        else:
            logger.error(f"❌ PDF compilation failed. Check {tex_path.replace('.tex', '.log')}")
            if result.stdout:
                # Print last 20 lines of output for debugging
                lines = result.stdout.strip().split('\n')
                for line in lines[-20:]:
                    logger.error(f"  {line}")
            return None
    except FileNotFoundError:
        logger.error("❌ xelatex not found! Install a LaTeX distribution:")
        logger.error("   macOS:  brew install --cask mactex-no-gui")
        logger.error("   Ubuntu: sudo apt install texlive-xetex")
        logger.error(f"📄 Your .tex file is saved at: {tex_path}")
        return None
    except subprocess.TimeoutExpired:
        logger.error("❌ LaTeX compilation timed out")
        return None


def get_existing_job_ids():
    """Return set of job IDs that already have cover letters generated."""
    existing = set()
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.endswith('.pdf'):
                job_id = f.split('_')[0]
                existing.add(job_id)
    return existing


def process_single_job(job_id, job, prompt, template, args):
    """Generate cover letter for a single job. Returns True on success."""
    job_title = job.get('Job Title', 'Unknown')
    org = job.get('Organization', 'Unknown')

    result = generate_tailored_paragraph(job, prompt, args.model)
    if not result:
        return False

    paragraph = result.get('tailored_paragraph', '')

    def bold_replace(m):
        inner = escape_latex(m.group(1))
        return f'\\textbf{{{inner}}}'

    paragraph_escaped = re.sub(r'\*\*(.+?)\*\*', bold_replace, paragraph)
    paragraph_escaped = escape_latex_preserving_commands(paragraph_escaped)

    filled = template.replace('((TAILORED_PARAGRAPH))', paragraph_escaped)

    safe_title = "".join(c for c in job_title if c.isalpha() or c.isdigit() or c == ' ').rstrip()
    safe_title = safe_title.replace(' ', '_')
    base_name = f"{job_id}_{safe_title}"

    tex_path = os.path.join(OUTPUT_DIR, f"{base_name}.tex")
    with open(tex_path, 'w', encoding='utf-8') as f:
        f.write(filled)
    logger.info(f"📄 Saved LaTeX: {tex_path}")

    txt_path = os.path.join(OUTPUT_DIR, f"{base_name}.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"Tailored paragraph for: {job_title} @ {org}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("="*60 + "\n\n")
        f.write(paragraph)

    if not args.no_pdf:
        pdf_path = compile_pdf(tex_path)
        if pdf_path:
            logger.info(f"✅ {job_id}: {job_title} @ {org}")
            return True
        else:
            logger.warning(f"⚠️ {job_id}: PDF failed, .tex saved")
            return True
    return True


def main():
    args = parse_arguments()

    prompt = load_prompt()
    if not prompt:
        sys.exit(1)

    template_path = NEW_TEMPLATE_FILE

    if not os.path.exists(template_path):
        logger.error(f"❌ Template not found: {template_path}")
        sys.exit(1)
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    if args.all:
        # --- BULK MODE ---
        if not os.path.exists(RANKED_FILE):
            logger.error(f"❌ {RANKED_FILE} not found. Run ai_matcher_bulk.py first.")
            sys.exit(1)

        ranked_df = pd.read_excel(RANKED_FILE)
        ranked_df['Job ID'] = ranked_df['Job ID'].astype(str).str.strip()
        existing = get_existing_job_ids()

        total = len(ranked_df)
        skipped = 0
        generated = 0
        failed = 0

        print(f"\n{'='*60}")
        print(f"📋 BULK COVER LETTER GENERATION")
        print(f"   Total ranked jobs: {total}")
        print(f"   Already generated: {len(existing)}")
        print(f"   To generate: {total - len(existing)}")
        print(f"{'='*60}\n")

        for idx, row in ranked_df.iterrows():
            job_id = str(row['Job ID']).strip()
            job_title = row.get('Job Title', 'Unknown')
            org = row.get('Organization', 'Unknown')
            score = row.get('Match Score', 'N/A')

            if job_id in existing:
                skipped += 1
                continue

            print(f"\n[{generated + failed + 1}/{total - len(existing)}] {job_title} @ {org} (score: {score})")

            job = row.to_dict()
            success = process_single_job(job_id, job, prompt, template, args)

            if success:
                generated += 1
            else:
                failed += 1

            # Rate limit pause
            import time
            time.sleep(3)

        print(f"\n{'='*60}")
        print(f"🎉 BULK GENERATION COMPLETE")
        print(f"   Generated: {generated}")
        print(f"   Skipped (existing): {skipped}")
        print(f"   Failed: {failed}")
        print(f"{'='*60}\n")

    elif args.custom:
        # --- CUSTOM MODE (auto-parse WaterlooWorks posting) ---
        job_id, job = get_custom_job()
        job_title = job['Job Title']
        org = job['Organization']

        print(f"\n{'='*60}")
        print(f"📋 JOB: {job_title}")
        print(f"🏢 ORG: {org}")
        print(f"📍 CITY: {job.get('City', 'N/A')}")
        print(f"{'='*60}\n")

        success = process_single_job(job_id, job, prompt, template, args)
        if not success:
            sys.exit(1)

        print(f"\n🎉 Done! Cover letter saved to cover_letters/")

    else:
        # --- SINGLE MODE ---
        job = find_job(args.job_id)
        if not job:
            logger.error(f"❌ Job ID '{args.job_id}' not found in {RANKED_FILE} or {SCRAPED_FILE}")
            sys.exit(1)

        job_title = job.get('Job Title', 'Unknown')
        org = job.get('Organization', 'Unknown')
        score = job.get('Match Score', 'N/A')

        print(f"\n{'='*60}")
        print(f"📋 JOB: {job_title}")
        print(f"🏢 ORG: {org}")
        print(f"📍 CITY: {job.get('City', 'N/A')}")
        if score != 'N/A':
            print(f"⭐ MATCH SCORE: {score}/100")
        print(f"{'='*60}\n")

        success = process_single_job(args.job_id, job, prompt, template, args)
        if not success:
            sys.exit(1)

        print(f"\n🎉 Done! Cover letter saved to cover_letters/")


if __name__ == "__main__":
    main()
