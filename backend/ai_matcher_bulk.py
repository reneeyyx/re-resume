import os
import time
import json
import logging
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
INPUT_FILE = "scraped_jobs.xlsx"
OUTPUT_DIR = "matched_results"
RESUME_FILE = "customizations/resume.txt"
RANKED_OUTPUT = os.path.join(OUTPUT_DIR, "ranked_jobs.xlsx")
TAILORED_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "tailored_resumes")

TOP_N = config["matcher"]["top_n"]
BATCH_SIZE = config["matcher"]["batch_size"]

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TAILORED_OUTPUT_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()


def load_resume():
    if not os.path.exists(RESUME_FILE):
        logger.error(f"❌ Resume file '{RESUME_FILE}' not found!")
        logger.error("Create a resume.txt file in the backend/customizations/ directory.")
        return None
    with open(RESUME_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()


def rank_batch(df_batch, resume, batch_num, total_batches):
    """Ranks a single batch of jobs against the resume."""
    logger.info(f"📊 Ranking batch {batch_num}/{total_batches} ({len(df_batch)} jobs)...")

    jobs_text = ""
    for _, row in df_batch.iterrows():
        summary = str(row.get('Summary', '')).replace('\n', ' ')[:400]
        jobs_text += f"ID: {row['Job ID']} | TITLE: {row['Job Title']} | SUMMARY: {summary}\n"

    prompt = f"""
    You are an expert technical recruiter. Review the candidate's resume and job list below.

    YOUR GOAL:
    Score each job from 0-100 based on fit with the candidate. Return ALL jobs with scores.

    SCORING CRITERIA:
    - 80-100: Strong direct match (skills, experience, and domain align well)
    - 60-79: Good match with transferable skills or relevant pivot
    - 40-59: Partial match, some relevant skills
    - 20-39: Weak match, mostly unrelated
    - 0-19: No meaningful connection

    Be generous with scoring for roles where the candidate's software engineering
    background provides value, even if the job title doesn't scream "software."

    CANDIDATE RESUME:
    {resume}

    JOB LIST:
    {jobs_text}

    OUTPUT JSON ONLY:
    {{
        "scored_jobs": [
            {{"id": "ID1", "score": 85, "reason": "brief 1-line reason"}},
            {{"id": "ID2", "score": 42, "reason": "brief 1-line reason"}}
        ]
    }}
    """

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"❌ Batch {batch_num} ranking failed: {e}")
        return None


def rank_all_jobs(df, resume):
    """Ranks all jobs in batches and returns a sorted list of top N."""
    all_scores = []
    total_batches = (len(df) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(df), BATCH_SIZE):
        batch = df.iloc[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1

        result = rank_batch(batch, resume, batch_num, total_batches)

        if result and "scored_jobs" in result:
            all_scores.extend(result["scored_jobs"])
        else:
            logger.warning(f"⚠️ Batch {batch_num} returned no results. Continuing...")

        # rate limit pause between batches
        if batch_num < total_batches:
            logger.info("⏳ Pausing between batches...")
            time.sleep(5)

    # sort by score descending, take top N
    all_scores.sort(key=lambda x: x.get("score", 0), reverse=True)
    top_scores = all_scores[:TOP_N]

    logger.info(f"✅ Ranked {len(all_scores)} total jobs. Top {len(top_scores)} selected.")
    return top_scores


def write_tailored_resume(job_row, resume):
    """Generates tailored resume content for one job."""
    job_title = job_row['Job Title']
    logger.info(f"✍️ Tailoring resume for: {job_title}...")

    job_context = f"""
    TITLE: {job_title}
    ORGANIZATION: {job_row.get('Organization', 'N/A')}
    SUMMARY: {job_row.get('Summary', 'N/A')}
    RESPONSIBILITIES: {job_row.get('Responsibilities', 'N/A')}
    SKILLS: {job_row.get('Skills', 'N/A')}
    """

    prompt = f"""
    You are a professional resume writer. Rewrite this Software Engineering resume to better match the job below.

    JOB DESCRIPTION:
    {job_context}

    RESUME:
    {resume}

    INSTRUCTIONS:
    1. Reframe experience bullets to highlight relevance to THIS specific job.
    2. Do NOT invent facts. Only rephrase and emphasize existing experience.
    3. Generate a "Summary of Qualifications" section tailored to this role.
    4. Write a compelling cover letter opening hook (2-3 sentences).

    Output JSON:
    {{
        "tailored_summary": "...",
        "key_skills": ["...", "..."],
        "experience_bullets": [{{"company": "...", "bullets": ["...", "..."]}}],
        "cover_letter_hook": "..."
    }}
    """

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"❌ Tailoring failed for {job_title}: {e}")
        return None


def to_str(val):
    """Safely convert any AI response value to a string."""
    if val is None:
        return ""
    if isinstance(val, list):
        return "\n".join(str(v) for v in val)
    return str(val)


def save_tailored_result(job_id, job_title, score, reason, tailored_data):
    """Saves one tailored resume to a text file."""
    safe_title = "".join(c for c in job_title if c.isalpha() or c.isdigit() or c == ' ').rstrip()
    filename = os.path.join(TAILORED_OUTPUT_DIR, f"{job_id}_{safe_title.replace(' ', '_')}.txt")

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"{'='*60}\n")
        f.write(f"JOB: {job_title}\n")
        f.write(f"ID: {job_id} | MATCH SCORE: {score}/100\n")
        f.write(f"WHY: {reason}\n")
        f.write(f"{'='*60}\n\n")

        f.write("=== TAILORED SUMMARY ===\n")
        f.write(to_str(tailored_data.get('tailored_summary', '')) + "\n\n")

        f.write("=== KEY SKILLS ===\n")
        skills = tailored_data.get('key_skills', [])
        if isinstance(skills, list):
            f.write(", ".join(str(s) for s in skills) + "\n\n")
        else:
            f.write(to_str(skills) + "\n\n")

        f.write("=== EXPERIENCE ===\n")
        for item in tailored_data.get('experience_bullets', []):
            f.write(f"\n[{item.get('company', 'N/A')}]\n")
            bullets = item.get('bullets', item.get('bullet', []))
            if isinstance(bullets, str):
                bullets = [bullets]
            for b in bullets:
                f.write(f"  • {b}\n")

        f.write(f"\n{'='*60}\n")
        f.write("=== COVER LETTER HOOK ===\n")
        f.write(to_str(tailored_data.get('cover_letter_hook', '')) + "\n")

    logger.info(f"💾 Saved: {filename}")


def main():
    # 1. Load inputs
    if not os.path.exists(INPUT_FILE):
        logger.error(f"❌ {INPUT_FILE} not found. Run jobhunter_h.py first.")
        return

    resume = load_resume()
    if not resume:
        return

    df = pd.read_excel(INPUT_FILE)
    df['Job ID'] = df['Job ID'].astype(str)
    logger.info(f"📂 Loaded {len(df)} jobs from {INPUT_FILE}")

    # 2. Rank all jobs (or load existing rankings)
    if os.path.exists(RANKED_OUTPUT):
        logger.info(f"📂 Found existing rankings: {RANKED_OUTPUT}. Skipping ranking phase.")
        ranked_df = pd.read_excel(RANKED_OUTPUT)
        ranked_df['Job ID'] = ranked_df['Job ID'].astype(str)
        score_map = {}
        for _, row in ranked_df.iterrows():
            jid = str(row['Job ID']).strip()
            score_map[jid] = {
                'id': jid,
                'score': row.get('Match Score', 0),
                'reason': row.get('Match Reason', '')
            }
        print(f"\n✅ Loaded {len(ranked_df)} ranked jobs from {RANKED_OUTPUT}")
        print(f"   Score range: {ranked_df['Match Score'].min()} - {ranked_df['Match Score'].max()}\n")
    else:
        print("\n" + "="*60)
        print("🤖 PHASE 1: RANKING ALL JOBS")
        print("="*60 + "\n")

        top_scores = rank_all_jobs(df, resume)

        if not top_scores:
            logger.error("Ranking failed. Exiting.")
            return

        # save ranked results to excel
        top_ids = [s['id'] for s in top_scores]
        score_map = {s['id']: s for s in top_scores}

        ranked_df = df[df['Job ID'].str.strip().isin([str(x).strip() for x in top_ids])].copy()
        ranked_df['Match Score'] = ranked_df['Job ID'].apply(lambda x: score_map.get(x.strip(), {}).get('score', 0))
        ranked_df['Match Reason'] = ranked_df['Job ID'].apply(lambda x: score_map.get(x.strip(), {}).get('reason', ''))
        ranked_df = ranked_df.sort_values('Match Score', ascending=False)
        ranked_df.to_excel(RANKED_OUTPUT, index=False)

        print(f"\n✅ Top {len(ranked_df)} jobs saved to {RANKED_OUTPUT}")
        print(f"   Score range: {ranked_df['Match Score'].min()} - {ranked_df['Match Score'].max()}\n")

    # 3. Tailor resumes for each
    print("="*60)
    print(f"✍️ PHASE 2: TAILORING RESUMES ({len(ranked_df)} jobs)")
    print("="*60 + "\n")

    # check for already-tailored files to support resume
    existing_files = set(os.listdir(TAILORED_OUTPUT_DIR)) if os.path.exists(TAILORED_OUTPUT_DIR) else set()

    for idx, (_, row) in enumerate(ranked_df.iterrows()):
        job_id = str(row['Job ID']).strip()
        job_title = row['Job Title']
        score = score_map.get(job_id, {}).get('score', 0)
        reason = score_map.get(job_id, {}).get('reason', '')

        # skip if already tailored
        safe_title = "".join(c for c in job_title if c.isalpha() or c.isdigit() or c == ' ').rstrip()
        expected_file = f"{job_id}_{safe_title.replace(' ', '_')}.txt"
        if expected_file in existing_files:
            logger.info(f"⏭️ [{idx+1}/{len(ranked_df)}] Already tailored: {job_title}")
            continue

        logger.info(f"[{idx+1}/{len(ranked_df)}] Processing: {job_title} (Score: {score})")

        tailored = write_tailored_resume(row, resume)
        if tailored:
            save_tailored_result(job_id, job_title, score, reason, tailored)

        # rate limit
        time.sleep(4)

    print("\n" + "="*60)
    print("🎉 ALL DONE!")
    print(f"📊 Ranked jobs: {RANKED_OUTPUT}")
    print(f"📝 Tailored resumes: {TAILORED_OUTPUT_DIR}/")
    print("="*60)


if __name__ == "__main__":
    main()
