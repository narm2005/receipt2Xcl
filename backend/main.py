from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from PIL import Image
import pytesseract
import requests
import pandas as pd
import uuid
import os

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
def form_post(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    # Save uploaded image
    img_bytes = await file.read()
    filename = f"receipt_{uuid.uuid4().hex}.png"
    with open(filename, "wb") as f:
        f.write(img_bytes)

    # OCR with Tesseract
    text = pytesseract.image_to_string(Image.open(filename))

    print(text)
    # Send to Mistral via Ollama
    prompt = f"""
    Extract this receipt into JSON with fields: Vendor, Date, Items (name, qty, price), Total, Tax:
    {text}
    """
    response = requests.post("http://localhost:11434/api/generate", json={
        "model": "mistral",
        "prompt": prompt,
        "stream": False
    })

    json_data = response.json().get("response", "")
    json_data = json_data.strip().strip("`{} ")

    # You can replace this with proper JSON parsing if needed
    lines = [line.strip() for line in json_data.split("\n") if ":" in line]
    parsed = {}
    for line in lines:
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()

    # Convert to Excel
    df = pd.DataFrame([parsed])
    excel_file = f"receipt_{uuid.uuid4().hex}.xlsx"
    df.to_excel(excel_file, index=False)

    os.remove(filename)  # cleanup
    return FileResponse(excel_file, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename=excel_file)
