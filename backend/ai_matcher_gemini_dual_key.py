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
NAME: Renee Xu
EDUCATION: University of Waterloo, Computer Engineering (2025-2030)
EXPERIENCE:
1. Humanoid Vision Developer @ WATonomous: ROS-based message frameworks, stereo vision pipelines, PyTorch/TensorFlow models for scene segmentation.
2. Software Lead @ VEX Robotics: C++ driver routines, PID control, odometry-based localization, motion planning.
3. Program Director @ Fast Forward Into the Future: Directed STEM initiatives, Python/Java curriculum design, event logistics.
PROJECTS:
1. Medisyn: Python, React, C++, OpenCV. Telemetry webcam integration.
2. Mind Mart: Java, Swing. Game logic.
SKILLS: Python, C++, Java, SQL, React, ROS, Git, Docker, OpenCV, Pandas.
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
    You are a professional resume writer. Rewrite this Computer Engineering resume to better match the job below.
    
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