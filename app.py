"""
Flask Backend for Document Extractor (Cheque & Passbook)
Production-ready with environment variables - Backend Only
Enhanced with document type validation
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

def validate_document_type(image_path, expected_type):
    """
    Validate if the uploaded document matches the expected type
    expected_type: 'cheque', 'passbook', or 'gst'
    Returns: (is_valid, detected_type)
    """
    print(f"🔍 Validating document type. Expected: {expected_type}")
    
    img = Image.open(image_path)
    
    prompt = """You are a document classifier. Analyze this image and determine what type of document it is.

Classify the document into ONE of these categories:
- "cheque" - if it's a bank cheque
- "passbook" - if it's a bank passbook (cover page or inside pages)
- "gst" - if it's a GST Registration Certificate (Form GST REG-06)
- "other" - if it's any other type of document

Look for these indicators:
**Cheque indicators:**
- "Pay" or "PAY" text
- MICR code at bottom (with special symbols)
- Amount box
- Date boxes
- Signature line
- Cheque number
- "A/c No." or "Account Number"

**Passbook indicators:**
- "PASSBOOK" text
- Account holder details (CIF, Customer Name)
- Bank logo with branch details
- Transaction entries (Date, Particulars, Withdrawals, Deposits, Balance columns)
- "Date of Issue" or "Date of Activation"

**GST Certificate indicators:**
- "Goods and Services Tax" header
- "Registration Certificate" title
- "Form GST REG-06"
- "Registration Number" with GSTIN (15 digits)
- "Government of India"
- "Legal Name" and "Trade Name"
- "Constitution of Business"
- "Address of Principal Place of Business"
- Jurisdictional office details
- Digital signature reference

Return ONLY a single-word classification in this exact format:
DOCUMENT_TYPE: cheque
OR
DOCUMENT_TYPE: passbook
OR
DOCUMENT_TYPE: gst
OR
DOCUMENT_TYPE: other

No explanations, no additional text."""
    
    try:
        response = gemini_model.generate_content([prompt, img])
        result_text = response.text.strip()
        
        # Extract document type from response
        if "DOCUMENT_TYPE:" in result_text:
            detected_type = result_text.split("DOCUMENT_TYPE:")[1].strip().lower()
        else:
            # Fallback: look for keywords in response
            result_lower = result_text.lower()
            if "gst" in result_lower:
                detected_type = "gst"
            elif "cheque" in result_lower:
                detected_type = "cheque"
            elif "passbook" in result_lower:
                detected_type = "passbook"
            else:
                detected_type = "other"
        
        print(f"✓ Detected document type: {detected_type}")
        
        is_valid = detected_type == expected_type.lower()
        return is_valid, detected_type
        
    except Exception as e:
        print(f"❌ Document validation error: {e}")
        import traceback
        traceback.print_exc()
        # On error, assume invalid
        return False, "unknown"

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


# ==================== GST PROCESSING (GEMINI AI) ====================

def extract_gst_with_gemini(image_path):
    """Extract GST Certificate data using Gemini AI with improved error handling"""
    print(f"📄 Processing GST Certificate with Gemini: {image_path}")
    
    img = Image.open(image_path)
    
    prompt = """You are an expert at reading GST Registration Certificates from India. Analyze this GST certificate image and extract ALL fields accurately.

MANDATORY FIELDS TO EXTRACT:

1. Registration Number (GSTIN): 15-character alphanumeric code (format: 24AAEFW5097R1ZA)
2. Legal Name: The legal registered business name
3. Trade Name: Trade name if mentioned (may be same as legal name or "Not Applicable")
4. Constitution of Business: Type like "Limited Liability Partnership", "Private Limited Company", "Proprietorship", etc.
5. Address Components:
   - Floor Number
   - Building/Flat Number
   - Name of Premises/Building
   - Road/Street
   - Locality/Sub Locality
   - City/Town/Village
   - District
   - State
   - PIN Code (6 digits)
6. Validity Period:
   - Valid From (DD/MM/YYYY format)
   - Valid To (may be "Not Applicable")
7. Registration Type: Like "Regular", "Composition", etc.
8. Approving Authority Details:
   - Name of Approving Officer
   - Designation
   - Jurisdictional Office
9. Date of Issue: Certificate issue date (DD/MM/YYYY)

INSTRUCTIONS:
- Extract EXACTLY as printed on the certificate
- For dates, use DD/MM/YYYY format
- If any field is not found, leave it as empty string ""
- Compile full address from all address components
- YOU MUST respond with ONLY valid JSON, no explanations before or after

Return ONLY this JSON structure with no additional text:
{
  "registration_number": "",
  "legalname": "",
  "trade_name": "",
  "constitution": "",
  "floor_number": "",
  "building_number": "",
  "premises_name": "",
  "road_street": "",
  "locality": "",
  "city": "",
  "district": "",
  "state": "",
  "pin_code": "",
  "validity_from": "",
  "validity_to": "",
  "registration_type": "",
  "approving_officer": "",
  "designation": "",
  "office": "",
  "issue_date": ""
}"""
    
    try:
        response = gemini_model.generate_content([prompt, img])
        json_text = response.text.strip()
        
        print(f"🔍 Raw Gemini response (first 200 chars): {json_text[:200]}")
        
        # Check if response is empty
        if not json_text:
            print("❌ Empty response from Gemini")
            return None
        
        # Remove markdown code blocks if present
        if '```json' in json_text:
            json_text = json_text.split('```json')[1].split('```')[0].strip()
        elif '```' in json_text:
            # Handle case where it's just ``` without json
            parts = json_text.split('```')
            if len(parts) >= 2:
                json_text = parts[1].strip()
        
        # Remove any leading/trailing whitespace and newlines
        json_text = json_text.strip()
        
        # Try to find JSON object if there's text before/after
        if not json_text.startswith('{'):
            # Try to extract JSON from the response
            start_idx = json_text.find('{')
            end_idx = json_text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                json_text = json_text[start_idx:end_idx+1]
            else:
                print(f"❌ No JSON object found in response: {json_text}")
                return None
        
        print(f"🔍 Cleaned JSON (first 200 chars): {json_text[:200]}")
        
        # Parse JSON
        extracted = json.loads(json_text)
        
        # Compile full address
        address_parts = []
        if extracted.get('floor_number'):
            address_parts.append(f"Floor: {extracted['floor_number']}")
        if extracted.get('building_number'):
            address_parts.append(f"Building: {extracted['building_number']}")
        if extracted.get('premises_name'):
            address_parts.append(extracted['premises_name'])
        if extracted.get('road_street'):
            address_parts.append(extracted['road_street'])
        if extracted.get('locality'):
            address_parts.append(extracted['locality'])
        
        full_address = ', '.join(filter(None, address_parts))
        
        # Format the data for sheets
        result = {
            'document_type': 'gst',
            'registration_number': extracted.get('registration_number', ''),
            'legalname': extracted.get('legalname', ''),
            'trade_name': extracted.get('trade_name', ''),
            'constitution': extracted.get('constitution', ''),
            'full_address': full_address,
            'city': extracted.get('city', ''),
            'district': extracted.get('district', ''),
            'state': extracted.get('state', ''),
            'pin_code': extracted.get('pin_code', ''),
            'validity_from': extracted.get('validity_from', ''),
            'validity_to': extracted.get('validity_to', ''),
            'registration_type': extracted.get('registration_type', ''),
            'approving_officer': extracted.get('approving_officer', ''),
            'designation': extracted.get('designation', ''),
            'office': extracted.get('office', ''),
            'issue_date': extracted.get('issue_date', ''),
            'extracted_at': datetime.now().isoformat()
        }
        
        print(f"✓ Extracted GSTIN: {result['registration_number']}")
        print(f"✓ Extracted Legal Name: {result['legalname']}")
        print(f"✓ Extracted City: {result['city']}, State: {result['state']}")
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing error: {e}")
        print(f"❌ Failed to parse text: {json_text if 'json_text' in locals() else 'No text available'}")
        return None
    except Exception as e:
        print(f"❌ Gemini error: {e}")
        import traceback
        traceback.print_exc()
        return None


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
5. **BANK Address**: Complete address
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
  "bank_address": "",
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
            'bank_address': extracted.get('bank_address', ''),
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


# ==================== FLASK ROUTES ====================

@app.route('/api/extract/gst', methods=['POST'])
def process_gst():
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file provided',
                'message': 'Please upload a GST certificate image or PDF'
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
        
        # Convert PDF to image if needed
        if filepath.lower().endswith('.pdf'):
            images = convert_from_path(filepath, dpi=300)
            temp_img = f"{filepath}_page1.jpg"
            images[0].save(temp_img, 'JPEG')
            validation_path = temp_img
        else:
            validation_path = filepath
        
        # VALIDATE DOCUMENT TYPE
        is_valid, detected_type = validate_document_type(validation_path, 'gst')
        
        if not is_valid:
            # Clean up files
            if filepath.lower().endswith('.pdf') and os.path.exists(validation_path):
                os.remove(validation_path)
            os.remove(filepath)
            
            return jsonify({
                'success': False,
                'error': 'Invalid document type',
                'message': f'This endpoint only accepts GST certificate documents. Detected document type: {detected_type}',
                'expected_type': 'gst',
                'detected_type': detected_type
            }), 400
        
        # Extract GST data
        data = extract_gst_with_gemini(validation_path)
        
        # Clean up temporary files
        if filepath.lower().endswith('.pdf') and os.path.exists(validation_path):
            os.remove(validation_path)
        os.remove(filepath)
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'Extraction failed',
                'message': 'Failed to extract GST data. Please ensure the certificate is clear and readable.'
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'GST certificate data extracted successfully',
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
        
        # Convert PDF to image if needed
        if filepath.lower().endswith('.pdf'):
            images = convert_from_path(filepath, dpi=300)
            temp_img = f"{filepath}_page1.jpg"
            images[0].save(temp_img, 'JPEG')
            validation_path = temp_img
        else:
            validation_path = filepath
        
        # VALIDATE DOCUMENT TYPE
        is_valid, detected_type = validate_document_type(validation_path, 'cheque')
        
        if not is_valid:
            # Clean up files
            if filepath.lower().endswith('.pdf') and os.path.exists(validation_path):
                os.remove(validation_path)
            os.remove(filepath)
            
            return jsonify({
                'success': False,
                'error': 'Invalid document type',
                'message': f'This endpoint only accepts cheque documents. Detected document type: {detected_type}',
                'expected_type': 'cheque',
                'detected_type': detected_type
            }), 400
        
        # Extract cheque data
        data = extract_cheque_with_gemini(validation_path)
        
        # Clean up temporary files
        if filepath.lower().endswith('.pdf') and os.path.exists(validation_path):
            os.remove(validation_path)
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
        
        # Convert PDF to image if needed
        if filepath.lower().endswith('.pdf'):
            images = convert_from_path(filepath, dpi=300)
            temp_img = f"{filepath}_page1.jpg"
            images[0].save(temp_img, 'JPEG')
            validation_path = temp_img
        else:
            validation_path = filepath
        
        # VALIDATE DOCUMENT TYPE
        is_valid, detected_type = validate_document_type(validation_path, 'passbook')
        
        if not is_valid:
            # Clean up files
            if filepath.lower().endswith('.pdf') and os.path.exists(validation_path):
                os.remove(validation_path)
            os.remove(filepath)
            
            return jsonify({
                'success': False,
                'error': 'Invalid document type',
                'message': f'This endpoint only accepts passbook documents. Detected document type: {detected_type}',
                'expected_type': 'passbook',
                'detected_type': detected_type
            }), 400
        
        # Extract passbook data
        data = extract_passbook_with_gemini(validation_path)
        
        # Clean up temporary files
        if filepath.lower().endswith('.pdf') and os.path.exists(validation_path):
            os.remove(validation_path)
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