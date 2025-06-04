python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
brew install tesseract
brew install ollama

# ## Receipt to Excel with AI (FastAPI + Ollama)
# - Upload receipt → OCR → Mistral LLM → Excel
#
# ### 🔧 Local Setup
# ```bash
# # ## Receipt to Excel with AI (FastAPI + Ollama)
# - Upload receipt → OCR → Mistral LLM → Excel
#
# ### 🔧 Local Setup
# ```bash
# pip install -r requirements.txt
# 

# ```
#
# ### ☁️ Deploy on Render
# - Connect this repo
# - Use Docker deploy
# - Use the included Dockerfile
# uvicorn main:app --reload
# ```
#
# ### ☁️ Deploy on Render
# - Connect this repo
# - Use Docker deploy
# - Use the included Dockerfile