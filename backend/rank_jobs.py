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

BASE_RESUME = BASE_RESUME = """
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