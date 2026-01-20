import os
import json
import logging
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY_1"))

# Gemini 3.0 Pro Preview (Best reasoning)
MODEL_NAME = "gemini-3-pro-preview" 

INPUT_FILE = "scraped_jobs.xlsx"
OUTPUT_FILE = "picked_jobs.xlsx"

# MAX number of jobs to pick (it can pick fewer)
TOP_N = 5 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger()

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

def rank_jobs(df, top_n):
    logger.info(f"📊 AI ({MODEL_NAME}) is analyzing {len(df)} jobs...")

    jobs_summary_text = ""
    for index, row in df.iterrows():
        clean_summary = str(row['Summary']).replace('\n', ' ')[:400]
        jobs_summary_text += f"ID: {row['Job ID']} | TITLE: {row['Job Title']} | SUMMARY: {clean_summary}...\n"

    prompt = f"""
    You are an expert technical recruiter. 
    Review the candidate's resume and the job list below.
    
    YOUR GOAL:
    Select **UP TO {top_n}** jobs that are a strong strategic fit.
    
    CRITICAL RULES:
    1. **Quality over Quantity:** If only 1 job is good, return only 1. 
    2. **No Forced Matches:** If NO jobs are a good fit, return an empty list []. Do not hallucinate a fit.
    3. **The Criteria:** - Strong fit for Computer Engineering / Robotics (Python, C++, Automation).
       - Valid "Pivots" (e.g. Operations roles requiring data automation).
       - Avoid unrelated roles (e.g. pure manual labor, non-technical HR) unless they explicitly need a dev.
    
    CANDIDATE:
    {BASE_RESUME}
    
    JOB LIST:
    {jobs_summary_text}
    
    OUTPUT JSON ONLY:
    {{
        "top_ids": ["ID1", "ID2"],
        "reasoning": "Brief explanation of why these specific jobs were chosen (or why none were)."
    }}
    """

    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(
            prompt, 
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"❌ Ranking failed: {e}")
        return None

def main():
    if not os.path.exists(INPUT_FILE):
        logger.error(f"❌ {INPUT_FILE} not found. Run jobhunter.py first.")
        return

    df = pd.read_excel(INPUT_FILE)
    df['Job ID'] = df['Job ID'].astype(str)

    result = rank_jobs(df, TOP_N)
    
    if not result:
        return

    top_ids = result.get("top_ids", [])
    reasoning = result.get("reasoning", "")
    
    print("\n" + "="*50)
    print(f"🤖 AI SELECTION COMPLETE")
    print(f"Reasoning: {reasoning}")
    
    if not top_ids:
        print("❌ No jobs matched the criteria. (The list was empty).")
        print("Tip: Try scraping more jobs or adjusting the resume/criteria.")
        return

    print(f"IDs Selected: {top_ids}")
    print("="*50 + "\n")

    clean_top_ids = [str(x).strip() for x in top_ids]
    picked_df = df[df['Job ID'].str.strip().isin(clean_top_ids)]

    if picked_df.empty:
        logger.warning("⚠️ No rows matched the returned IDs. Check formatting.")
    else:
        picked_df.to_excel(OUTPUT_FILE, index=False)
        logger.info(f"✅ Saved {len(picked_df)} jobs to '{OUTPUT_FILE}'")

if __name__ == "__main__":
    main()