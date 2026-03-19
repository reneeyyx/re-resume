import os
import time
import json
import logging
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Step 1: Use 1.5 Pro for its huge context window (to read 50 jobs at once)
RANKING_MODEL_NAME = "gemini-1.5-pro" 
# Step 2: Use 3.0 Pro (or 1.5 Pro) for high-quality writing
WRITING_MODEL_NAME = "gemini-1.5-pro" # Switch to "gemini-3-pro-preview" if available

INPUT_FILE = "scraped_jobs.xlsx"
OUTPUT_DIR = "top_matched_resumes"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()

# --- YOUR BASE RESUME ---
BASE_RESUME = """
NAME: Dongwan (Jamie) Seoh
EDUCATION: University of Waterloo, Software Engineering (Sep 2025 - Present), 4.0/4.0 GPA
EXPERIENCE:
1. Full Stack Developer @ Nebula AI (Nov 2025 - Jan 2026): React Native, FastAPI, PostgreSQL. OCR+AI pipeline with Gemini/OpenAI, semantic search with 1,536-dim embeddings and IVFFlat indexing (40% faster retrieval), multi-tenant auth with Supabase RLS, Docker + GCP deployment, CI/CD to TestFlight.
2. Software Developer @ UW Orbital Satellite Mission Design Team (Sep 2025 - Nov 2025): React dashboards for satellite telemetry, REST APIs for async MCC requests, 95% UI test coverage with vitest.
3. Web Development Intern @ PNPT Co., Ltd. (Jul 2023 - Aug 2023): Figma + React prototyping, cross-browser compatibility fixes, early-stage startup website optimization.
PROJECTS:
1. Quota (DeltaHacks12 First Place): TypeScript, Next.js, React Flow, Gemini, LangChain, MongoDB. VS Code extension with AST parsing for API cost analysis (40% spend reduction), indexed codebases <3s (45x faster than AI IDEs), RAG chatbot for budget-aware system planning.
2. Personal CRM: Next.js, FastAPI, PostgreSQL, TailwindCSS. 20+ REST endpoints, caching + rate limiting (30% server load reduction), matrix-based contact ranking algorithm.
3. Melodie.ai: PyTorch, NumPy, Python, Music21. LSTM music generation, MIDI preprocessing, probabilistic sampling with temperature control and nucleus sampling.
SKILLS: Python, C/C++, TypeScript/JavaScript, SQL, Java, R, PyTorch, NumPy, React/React Native, Next.js, Svelte, FastAPI, Flask, Git, Docker, GCP, Azure, Vercel, MongoDB.
AWARDS: Euclid Math Contest Top 7.6% (2024-2025), STEM Fellowship Big Data Challenge Finalist (2025), Published paper DOI: 10.17975/sfj-2025-001.
"""
def rank_jobs(df):
    """
    Step 1: Sends ALL job summaries to AI and asks for the Top 5 matches.
    """
    logger.info(f"📊 PHASE 1: Ranking {len(df)} jobs...")

    # Prepare a lightweight list of jobs (ID + Title + Summary only) to save tokens
    jobs_summary_text = ""
    for index, row in df.iterrows():
        # specific format for the AI to parse easily
        jobs_summary_text += f"ID: {row['Job ID']} | TITLE: {row['Job Title']} | SUMMARY: {row['Summary'][:300]}...\n"

    prompt = f"""
    You are an expert technical recruiter. I have a list of {len(df)} job openings and a candidate's resume.
    
    YOUR GOAL:
    Identify the Top 5 jobs that are the best fit for this candidate.
    Prioritize roles where the candidate's "Computer Engineering" and "Robotics" background provides a unique advantage (e.g., automation, data analysis, scripting), even if the job is in a different field (like Transit or Operations).
    
    CANDIDATE RESUME:
    {BASE_RESUME}
    
    JOB LIST:
    {jobs_summary_text}
    
    OUTPUT FORMAT (JSON ONLY):
    {{
        "top_5_ids": ["ID1", "ID2", "ID3", "ID4", "ID5"],
        "reasoning": "Brief explanation of why these 5 were chosen"
    }}
    """

    try:
        model = genai.GenerativeModel(RANKING_MODEL_NAME)
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"❌ Ranking failed: {e}")
        return None

def write_tailored_resume(job_row):
    """
    Step 2: Writes the full resume for a single job.
    """
    job_title = job_row['Job Title']
    logger.info(f"✍️ PHASE 2: Writing tailored resume for: {job_title}...")

    job_context = f"""
    TITLE: {job_title}
    SUMMARY: {job_row['Summary']}
    RESPONSIBILITIES: {job_row['Responsibilities']}
    SKILLS: {job_row['Skills']}
    """

    prompt = f"""
    You are a professional resume writer. Rewrite this Software Engineering resume to better match the job below.
    
    JOB DESCRIPTION:
    {job_context}

    RESUME:
    {BASE_RESUME}

    INSTRUCTIONS:
    1. Pivot the experience: Frame robotics/coding skills as "Process Automation" or "Data Analysis" if relevant.
    2. Do not invent facts.
    3. Generate a "Summary of Qualifications" section.
    
    Output JSON:
    {{
        "tailored_summary": "...",
        "key_skills": ["...", "..."],
        "experience_bullets": [{{"company": "...", "bullet": "..."}}],
        "cover_letter_hook": "..."
    }}
    """
    
    try:
        model = genai.GenerativeModel(WRITING_MODEL_NAME)
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"❌ Writing failed for {job_title}: {e}")
        return None

def save_result(job_title, data):
    safe_title = "".join([c for c in job_title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
    filename = f"{OUTPUT_DIR}/TOP_MATCH_{safe_title.replace(' ', '_')}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"--- TOP MATCH: {job_title} ---\n\n")
        f.write("=== SUMMARY ===\n" + data.get('tailored_summary', '') + "\n\n")
        f.write("=== SKILLS ===\n" + ", ".join(data.get('key_skills', [])) + "\n\n")
        f.write("=== EXPERIENCE ===\n")
        for item in data.get('experience_bullets', []):
            f.write(f"[{item['company']}]: {item['bullet']}\n")
        f.write("\n=== COVER LETTER HOOK ===\n" + data.get('cover_letter_hook', ''))

    logger.info(f"✅ Saved: {filename}")

def main():
    if not os.path.exists(INPUT_FILE):
        logger.error("No scraped_jobs.xlsx found!")
        return

    df = pd.read_excel(INPUT_FILE)
    
    # --- STEP 1: RANKING ---
    rank_data = rank_jobs(df)
    
    if not rank_data:
        logger.error("Ranking failed. Exiting.")
        return

    top_ids = rank_data.get("top_5_ids", [])
    reasoning = rank_data.get("reasoning", "")
    
    print("\n" + "="*50)
    print(f"🤖 AI ANALYSIS COMPLETE")
    print(f"Reasoning: {reasoning}")
    print(f"Top 5 Jobs Selected: {top_ids}")
    print("="*50 + "\n")

    # --- STEP 2: TAILORING ---
    # Filter the dataframe to only get the top 5 rows
    # Convert IDs to string to ensure matching works
    df['Job ID'] = df['Job ID'].astype(str)
    matched_jobs = df[df['Job ID'].isin([str(x) for x in top_ids])]

    for index, row in matched_jobs.iterrows():
        # Call the writer
        resume_data = write_tailored_resume(row)
        
        if resume_data:
            save_result(row['Job Title'], resume_data)
        
        # Short wait to be polite to the API
        time.sleep(10)

if __name__ == "__main__":
    main()