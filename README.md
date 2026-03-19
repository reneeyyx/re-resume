flow:

customization:
- resume.txt
- newtemplate.tex/cover_letter_template.tex (cleanup later) -> template cover letter
- categories.txt to configure categories to scrape
- cover_letter_prompt -> customizable prompt to generate cover letter
-> generate this prompt with gemini & llm of ur choice + paste ur prompt


requirements:
- create/activate venv
- install requirements.txt
- fill in the details above
- set up latex generation (install packages)

chore:`
- get rid of two api keys in .env


to-do:
- migrate to google-genai from depricated
- first check if theres anything hardcoded in the program thats customizable (i.e., role that they're searching for) and if there is, make it customizable 
- moving all customizationf iles inside of customizations/ 
- setting up customization.json with the role that they're searching for (it's used in some prompts in ai_matcher_bulk.py)
- for the customization text files, make an .example file for each or a base file to start with. then i'm going to gitignore the personalized txt files
- make shell script to run workflows