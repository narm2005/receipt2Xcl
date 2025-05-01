
from flask import Flask, request, render_template, send_file
import pytesseract
from PIL import Image
import pandas as pd
import io
import re

app = Flask(__name__)

def parse_receipt_text(text):
    # print("text:", text)
    # vendor = text.split('\n')[0]
    #
    # date_match = re.search(r'(\d{2}/\d{2}/\d{4})', text)
    # total_match = re.search(r'Total\s*[:\-]?\s*\$?(\d+\.\d{2})', text, re.IGNORECASE)
    #
    # return {
    #     'Vendor': vendor.strip(),
    #     'Date': date_match.group(1) if date_match else 'N/A',
    #     'Total': total_match.group(1) if total_match else 'N/A'
    # }
    lines = text.splitlines()
    result = {
        "Vendor": lines[0].strip() if lines else "Unknown",
        "Date": "N/A",
        "Total": "N/A",
        "Tax": "N/A",
        "Items": []
    }

    for line in lines:
        if "date" in line.lower():
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})', line)
            if date_match:
                result["Date"] = date_match.group(1)

        elif "total" in line.lower():
            total_match = re.search(r'(\d+\.\d{2})', line)
            if total_match:
                result["Total"] = total_match.group(1)

        elif "tax" in line.lower():
            tax_match = re.search(r'(\d+\.\d{2})', line)
            if tax_match:
                result["Tax"] = tax_match.group(1)

        tokens = line.split()
        if len(tokens) == 3:
            item, qty, price = tokens
            if re.match(r'^\d+$', qty) and re.match(r'^\d+\.\d{2}$', price):
                result["Items"].append({
                    "Item": item,
                    "Qty": int(qty),
                    "Price": float(price)
                })

    print("Result:",result)
    return result

@app.route('/', methods=['GET', 'POST'])
def upload_receipt():
    if request.method == 'POST':
        file = request.files['receipt']
        image = Image.open(file.stream)
        text = pytesseract.image_to_string(image)
        data = parse_receipt_text(text)

        df = pd.DataFrame([data])
        output = io.BytesIO()
        df.to_excel(output, index=False)
        output.seek(0)

        return send_file(output, download_name="receipt.xlsx", as_attachment=True)

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
