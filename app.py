"""
Flask Backend for Document Extractor (GST, Cheque & Passbook)
Production-ready with environment variables - Backend Only
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import json
from datetime import datetime
import google.generativeai as genai
from PIL import Image
from pdf2image import convert_from_path
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration - Using environment variables
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

# Configuration - Using environment variables (SECURE)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY environment variable is not set!")

UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-2.5-flash')

# ==================== HELPER FUNCTIONS ====================

def extract_cheque_number_from_micr(micr_code):
    """Extract 6-digit cheque number from MICR code (first segment)"""
    if not micr_code:
        return ""
    
    parts = re.findall(r'[⑈⑆]\s*(\d+)\s*[⑈⑆]', micr_code)
    
    if len(parts) >= 1:
        cheque_num = parts[0]
        print(f"✓ Extracted cheque number from MICR: {cheque_num}")
        return cheque_num
    
    fallback = re.findall(r'\b\d{6}\b', micr_code)
    if fallback:
        return fallback[0]
    
    return ""

def format_indian_currency(amount_str):
    """Format number in Indian numbering system"""
    if not amount_str:
        return ""
    
    digits = re.sub(r'[^\d]', '', str(amount_str))
    if not digits:
        return ""
    
    amount = int(digits)
    s = str(amount)
    if len(s) > 3:
        last_three = s[-3:]
        remaining = s[:-3]
        formatted = ""
        for i in range(len(remaining) - 1, -1, -1):
            formatted = remaining[i] + formatted
            if i > 0 and (len(remaining) - i) % 2 == 0:
                formatted = ',' + formatted
        s = formatted + ',' + last_three
    return f"₹ {s}/-"

# ==================== CHEQUE PROCESSING ====================

def extract_cheque_with_gemini(image_path):
    """Extract cheque data using Gemini AI"""
    print(f"💳 Processing cheque with Gemini: {image_path}")
    
    img = Image.open(image_path)
    
    prompt = """You are an expert at reading bank cheques. Analyze this cheque image and extract:

**MANDATORY FIELDS:**
1. **Bank Name**: Name of the bank (e.g., "State Bank of India", "HDFC Bank")
2. **Account Holder Name**: Name printed on the cheque (usually top-right or bottom area - THIS IS THE ACCOUNT OWNER'S NAME, NOT PAYEE)
3. **Payee Name**: Name after "PAY" (the person/entity receiving payment)
4. **Amount in Words**: Written amount after "RUPEES" (e.g., "Fifty Lakh Only")
5. **Amount in Numbers**: Numeric amount in the box (e.g., "5000000" or "50,00,000")
6. **Date**: Date from top-right boxes (DD/MM/YYYY format)
7. **Account Number**: 11-16 digit account number (usually below "A/c No.")
8. **IFSC Code**: 11-character code (format: SBIN0001234)
9. **MICR Code**: Bottom code with symbols - EXTRACT EXACTLY AS PRINTED WITH ALL SYMBOLS
   Example: "⑈343242⑈ 520002206⑆ 000860⑈ 24" or "230270• 143002341: 004052 31"
10. **Bank Address**: Full bank branch address if visible   
   

**OPTIONAL FIELDS:**
10. **PREFIX Number**: PREFIX account identifier if visible
11. **Branch Name**: Branch name if mentioned
12. **Branch Code**: Branch code if mentioned

**CRITICAL INSTRUCTIONS:**
- Account Holder Name is the name printed on the cheque (NOT the payee name)
- Extract MICR code EXACTLY as printed with all symbols (⑈, ⑆, •, :) and spacing
- For amount in numbers, extract the raw number without currency symbols
- Date must be in DD/MM/YYYY format

Return ONLY valid JSON (no markdown, no explanations):
{
  "bank_name": "",
  "account_holder_name": "",
  "payee_name": "",
  "amount_words": "",
  "amount_numbers": "",
  "date": "",
  "account_number": "",
  "ifsc_code": "",
  "micr_code": "",
  "prefix_number": "",
  "branch_name": "",
  "bank_address": "",
  "branch_code": ""
}"""
    
    try:
        response = gemini_model.generate_content([prompt, img])
        json_text = response.text.strip()
        
        if json_text.startswith('```json'):
            json_text = json_text.split('```json')[1].split('```')[0].strip()
        elif json_text.startswith('```'):
            json_text = json_text.split('```')[1].split('```')[0].strip()
        
        extracted = json.loads(json_text)
        print(f"✓ Gemini extracted JSON: {extracted}")
        
        micr_code = extracted.get('micr_code', '')
        cheque_number = extract_cheque_number_from_micr(micr_code)
        
        amount_num = extracted.get('amount_numbers', '')
        formatted_amount = format_indian_currency(amount_num) if amount_num else ''
        
        result = {
            'document_type': 'cheque',
            'bank_name': extracted.get('bank_name', ''),
            'account_holder_name': extracted.get('account_holder_name', ''),
            'payee_name': extracted.get('payee_name', ''),
            'amount_words': extracted.get('amount_words', ''),
            'amount_numbers': amount_num,
            'amount_formatted': formatted_amount,
            'date': extracted.get('date', ''),
            'account_number': extracted.get('account_number', ''),
            'ifsc_code': extracted.get('ifsc_code', ''),
            'micr_code': micr_code,
            'cheque_number': cheque_number,
            'prefix_number': extracted.get('prefix_number', ''),
            'branch_name': extracted.get('branch_name', ''),
            'bank_address': extracted.get('bank_address', ''),
            'branch_code': extracted.get('branch_code', ''),
            'extracted_at': datetime.now().isoformat()
        }
        
        print(f"✓ Extracted Account Holder: {result['account_holder_name']}")
        
       
        
        return result
        
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        import traceback
        traceback.print_exc()
        return None

# ==================== PASSBOOK PROCESSING ====================

def extract_passbook_with_gemini(image_path):
    """Extract bank passbook COVER PAGE details only"""
    print(f"📖 Processing bank passbook cover page: {image_path}")
    
    img = Image.open(image_path)
    
    prompt = """You are an expert at reading bank passbook cover pages. Analyze this passbook FIRST PAGE/COVER PAGE image and extract ONLY the account holder information.

**IMPORTANT:** Extract ONLY account holder details. DO NOT extract transaction data.

**FIELDS TO EXTRACT FROM COVER PAGE:**

1. **CIF Number**: Customer Information File number
2. **Account Number**: Full bank account number
3. **Customer Name**: Account holder's full name
4. **Father's/Husband's Name**: S/O, W/O, D/O details
5. **Address**: Complete address
6. **Phone**: Contact number
7. **Email**: Email address if visible
8. **Date of Birth (D.O.B.)**: Birth date in DD/MM/YYYY format
9. **Minor Status (MOP)**: SINGLE/MINOR status
10. **Nominee Registration Number**: If visible
11. **Bank Details:**
    - Bank Name
    - Branch Name
    - Branch Code
    - IFSC Code
    - MICR Code
    - SWIFT Code (if visible)
    - IBAN (if visible)
12. **Account Type**: Savings/Current
13. **Date of Issue**: When passbook was issued (DD/MM/YYYY)
14. **Date of Activation**: Account opening date if visible

**INSTRUCTIONS:**
- Extract EXACTLY as printed on the passbook
- For dates, use DD/MM/YYYY format
- If any field is not visible or not applicable, use empty string ""
- DO NOT extract any transaction data
- DO NOT extract photo or signature information

Return ONLY valid JSON (no markdown, no explanations):
{
  "cif_number": "",
  "account_number": "",
  "customer_name": "",
  "father_husband_name": "",
  "address": "",
  "phone": "",
  "email": "",
  "date_of_birth": "",
  "minor_status": "",
  "nominee_reg_number": "",
  "bank_name": "",
  "branch_name": "",
  "branch_code": "",
  "ifsc_code": "",
  "micr_code": "",
  "swift_code": "",
  "iban": "",
  "account_type": "",
  "date_of_issue": "",
  "date_of_activation": ""
}"""
    
    try:
        response = gemini_model.generate_content([prompt, img])
        json_text = response.text.strip()
        
        if json_text.startswith('```json'):
            json_text = json_text.split('```json')[1].split('```')[0].strip()
        elif json_text.startswith('```'):
            json_text = json_text.split('```')[1].split('```')[0].strip()
        
        extracted = json.loads(json_text)
        
        result = {
            'document_type': 'passbook',
            'cif_number': extracted.get('cif_number', ''),
            'account_number': extracted.get('account_number', ''),
            'customer_name': extracted.get('customer_name', ''),
            'father_husband_name': extracted.get('father_husband_name', ''),
            'address': extracted.get('address', ''),
            'phone': extracted.get('phone', ''),
            'email': extracted.get('email', ''),
            'date_of_birth': extracted.get('date_of_birth', ''),
            'minor_status': extracted.get('minor_status', ''),
            'nominee_reg_number': extracted.get('nominee_reg_number', ''),
            'bank_name': extracted.get('bank_name', ''),
            'branch_name': extracted.get('branch_name', ''),
            'branch_code': extracted.get('branch_code', ''),
            'ifsc_code': extracted.get('ifsc_code', ''),
            'micr_code': extracted.get('micr_code', ''),
            'swift_code': extracted.get('swift_code', ''),
            'iban': extracted.get('iban', ''),
            'account_type': extracted.get('account_type', ''),
            'date_of_issue': extracted.get('date_of_issue', ''),
            'date_of_activation': extracted.get('date_of_activation', ''),
            'extracted_at': datetime.now().isoformat()
        }
        
        print(f"✓ Extracted SWIFT: {result['swift_code']}")
        print(f"✓ Extracted Customer: {result['customer_name']}")
        print(f"✓ Extracted Bank Name: {result['bank_name']}")
        
        return result
        
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        import traceback
        traceback.print_exc()
        return None


        
  
# ==================== ROUTES ====================

@app.route('/')
def index():
    return jsonify({
        'status': 'running',
        'service': 'Document Extractor API',
        'version': '2.0',
        'message': 'API is running successfully',
        'endpoints': {
            'status': '/api/status',
            'cheque': '/api/extract/cheque',
            'gst': '/api/extract/gst',
            'passbook': '/api/extract/passbook'
        }
    })

@app.route('/api/status')
def api_status():
    return jsonify({
        'status': 'running',
        'service': 'Document Extractor API',
        'version': '2.0',
        'endpoints': {
            'cheque': '/api/extract/cheque',
            'gst': '/api/extract/gst',
            'passbook': '/api/extract/passbook'
        }
    })

@app.route('/api/extract/cheque', methods=['POST'])
def process_cheque():
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file provided',
                'message': 'Please upload a cheque image or PDF'
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'Empty filename',
                'message': 'No file selected'
            }), 400
        
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        if filepath.lower().endswith('.pdf'):
            images = convert_from_path(filepath, dpi=300)
            temp_img = f"{filepath}_page1.jpg"
            images[0].save(temp_img, 'JPEG')
            data = extract_cheque_with_gemini(temp_img)
            os.remove(temp_img)
        else:
            data = extract_cheque_with_gemini(filepath)
        
        os.remove(filepath)
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Extraction failed',
                'message': 'Failed to extract cheque data. Please ensure the image is clear and readable.'
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Cheque data extracted successfully',
            'data': data
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Server error',
            'message': str(e)
        }), 500



@app.route('/api/extract/passbook', methods=['POST'])
def process_passbook():
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file provided',
                'message': 'Please upload a passbook image or PDF'
            }), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'Empty filename',
                'message': 'No file selected'
            }), 400
        
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        if filepath.lower().endswith('.pdf'):
            images = convert_from_path(filepath, dpi=300)
            temp_img = f"{filepath}_page1.jpg"
            images[0].save(temp_img, 'JPEG')
            data = extract_passbook_with_gemini(temp_img)
            os.remove(temp_img)
        else:
            data = extract_passbook_with_gemini(filepath)
        
        os.remove(filepath)
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Extraction failed',
                'message': 'Failed to extract passbook data. Please ensure the cover page is clear and readable.'
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Passbook data extracted successfully',
            'data': data
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'Server error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)