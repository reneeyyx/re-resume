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

next steps:
- auto apply to job throuhg playwright given the customc over letter for that 
-> exception handling if they have diff things

- extra filters customize: degrees, duration, etc

 degrees = [
        "ENG - Electrical and Computer Engineering",
        "ENG - Software Engineering",
        "ENG - Systems Design",
        "MATH - Applied Mathematics",
        "MATH - Computer Science",
        "MATH - Computing and Financial Management"
    ]
    toggle_filter_category(page, "Targeted Degrees", degrees)