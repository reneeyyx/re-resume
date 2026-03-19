# Resume Scraper Matcher

Automated co-op job pipeline for WaterlooWorks — scrapes job listings, ranks them against your resume with AI, and generates tailored cover letters.

## Setup

**1. Prerequisites**
- Python 3.11+
- A Google Gemini API key
- `xelatex` for PDF generation (`brew install --cask mactex-no-gui`)

**2. Virtual environment**
```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/playwright install chromium
```

**3. Environment variables** — create `backend/.env`:
```
WW_USERNAME=your_waterlooworks_username
WW_PASSWORD=your_waterlooworks_password
GOOGLE_API_KEY=your_gemini_api_key
```

**4. Customization files** — copy each example and fill it in:
```bash
cp backend/customizations/resume.example.txt backend/customizations/resume.txt
cp backend/customizations/cover_letter_prompt.example.txt backend/customizations/cover_letter_prompt.txt
cp backend/customizations/newtemplate.example.tex backend/customizations/newtemplate.tex
```

Edit `backend/customizations/configuration.json` to set your degree filters, job category, and model preferences.

## Usage

### Full pipeline
```bash
./run_all.sh
```
Scrapes → ranks → prompts you for cover letter generation.

### Individual steps
```bash
./run_scrape.sh                        # scrape WaterlooWorks → results/scraped_jobs.xlsx
./run_match.sh                         # rank jobs with AI → results/ranked_jobs.xlsx
./run_cover_letter.sh --all            # generate cover letters for all ranked jobs
./run_cover_letter.sh <job_id>         # single job by ID
./run_cover_letter.sh --custom         # paste a job posting manually
./run_cover_letter.sh --all --new-template  # use fixed-body template (tailored paragraph only)
```

## Output

| Path | Contents |
|------|----------|
| `backend/results/scraped_jobs.xlsx` | Raw scraped job listings |
| `backend/results/ranked_jobs.xlsx` | Jobs ranked 0–100 with match reasons |
| `backend/results/tailored_resumes/` | Per-job tailored resume bullets |
| `backend/results/cover_letters/` | Generated `.tex` and `.pdf` cover letters |
