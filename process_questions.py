import os
import requests
import json
import base64
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ================== CONFIG ==================

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent"

# Load API keys from environment variable (for GitHub Secrets)
API_KEYS_STR = os.environ.get('GEMINI_API_KEYS', '')
if not API_KEYS_STR:
    raise ValueError("❌ GEMINI_API_KEYS environment variable not set!")

API_KEYS = [key.strip() for key in API_KEYS_STR.split(',') if key.strip()]
if not API_KEYS:
    raise ValueError("❌ No valid API keys found!")

print(f"✅ Loaded {len(API_KEYS)} API keys from environment")

BASE_IMAGES_FOLDER = "Images"
OUTPUT_BASE_FOLDER = "output_data"
MAX_WORKERS = 7 
MAX_INNER_WORKERS = 4

# Load folder contexts from JSON file
CONTEXTS_FILE = "folder_contexts.json"

# Global topic tracker for sequential processing
GLOBAL_TOPIC_TRACKER = {
    "current_topic_bn": None,
    "current_topic_en": None
}

# Translation Cache to avoid redundant API calls
TOPIC_TRANSLATION_CACHE = {}

# ================== LOGIC ==================

key_index = 0

def get_next_key():
    """Rotate instantly to next API key."""
    global key_index
    key = API_KEYS[key_index % len(API_KEYS)]
    key_index += 1
    return key

def encode_image(image_path):
    """Encodes the image file to a base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def call_gemini_api(prompt, image_data=None, timeout=120):
    """Generic Gemini API caller with instant key rotation on failure/timeout."""
    total_keys = len(API_KEYS)
    
    for attempt in range(total_keys):
        api_key = get_next_key()
        headers = {"Content-Type": "application/json"}
        
        parts = [{"text": prompt}]
        if image_data:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_data}})
        
        payload = {"contents": [{"parts": parts}]}

        try:
            resp = requests.post(
                f"{GEMINI_ENDPOINT}?key={api_key}",
                headers=headers,
                json=payload,
                timeout=timeout
            )

            if resp.status_code == 200:
                result = resp.json()
                if result.get("candidates") and result["candidates"][0].get("content"):
                    text = result["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if text and len(text) > 0:
                        return text
                print(f"⚠️ Empty response → switching key (attempt {attempt + 1}/{total_keys})")
            elif resp.status_code == 429:
                print(f"⚠️ Rate limit hit → switching key (attempt {attempt + 1}/{total_keys})")
                time.sleep(0.5)
                continue
            else:
                print(f"⚠️ API error [{resp.status_code}] → switching key (attempt {attempt + 1}/{total_keys})")
                continue

        except requests.exceptions.Timeout:
            print(f"⚠️ Timeout after {timeout}s → switching key (attempt {attempt + 1}/{total_keys})")
            continue
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Network error → switching key (attempt {attempt + 1}/{total_keys}): {str(e)[:50]}")
            continue
        except Exception as e:
            print(f"⚠️ Unexpected error → switching key (attempt {attempt + 1}/{total_keys}): {str(e)[:50]}")
            continue

    print(f"❌ All {total_keys} API keys exhausted")
    return None

def translate_topic_to_english(bengali_topic):
    """Translate Bengali topic to English using AI WITH CACHING."""
    if not bengali_topic or bengali_topic == "সাধারণ":
        return "General"
    if bengali_topic == "Self Test":
        return "Self Test"
    
    if bengali_topic in TOPIC_TRANSLATION_CACHE:
        print(f"     └─ 💰 Using cached translation for: {bengali_topic}")
        return TOPIC_TRANSLATION_CACHE[bengali_topic]
    
    print(f"     └─ 🔄 Translating new topic: {bengali_topic}")
    translation_prompt = f"""
Translate the following Bengali mathematics topic to English. Return ONLY the English translation, nothing else.

Bengali Topic: {bengali_topic}

Rules:
- Return ONLY the English translation
- Keep it concise and accurate
- Use proper mathematical terminology
- Example: "ম্যাট্রিক্সের মাত্রা বিশ্লেষণ" → "Matrix Dimension Analysis"
- Example: "কৃষি বিশ্ববিদ্যালয় সমূহের বিগত বছরের প্রশ্ন ও সমাধান" → "Agricultural University Past Questions & Solutions"
"""
    
    result = call_gemini_api(translation_prompt, timeout=60)
    if result:
        result = result.strip().strip('"').strip("'")
        TOPIC_TRANSLATION_CACHE[bengali_topic] = result
        return result
    return "General"

def extract_questions_from_image(image_path, previous_topic_bn=None, previous_topic_en=None):
    """Extract raw question text from image with topic continuation support."""
    
    topic_context = ""
    if previous_topic_bn and previous_topic_en:
        topic_context = f"""
🔴 IMPORTANT TOPIC CONTEXT 🔴
The previous page ended with this topic:
- Bengali: {previous_topic_bn}
- English: {previous_topic_en}

If this page does NOT start with a new "Topic N:" header at the very top, you MUST continue using this topic for ALL questions until you find a new topic header.
"""
    
    extraction_prompt = f"""
আপনি একজন উচ্চতর গণিত MCQ বিশেষজ্ঞ। এই ইমেজ থেকে সমস্ত প্রশ্ন নিখুঁত নির্ভুলতার সাথে সংগ্রহ করুন।

{topic_context}

🔴 CRITICAL SPATIAL ORDERING REQUIREMENT (MANDATORY) 🔴
YOU MUST EXTRACT QUESTIONS IN THIS EXACT ORDER:
1. Start from TOP-LEFT of the page
2. Move DOWN through ALL items on the LEFT side (topics, questions, text)
3. Then move to TOP-RIGHT of the page
4. Move DOWN through ALL items on the RIGHT side

This strict order (LEFT column top-to-bottom, then RIGHT column top-to-bottom) is ESSENTIAL for correct topic assignment.

🔴 CRITICAL TOPIC DETECTION & CONTINUATION RULES 🔴

1. **Topic Header Format Detection:**
    - Look for headers like "Topic [number]: [Bengali Text]" or "Topic [number] [Bengali Text]"
    - Examples: "Topic 1: শর্টকাট টেকনিক", "Topic 2 ভেক্টর"
    - Extract ONLY the Bengali text (e.g., "শর্টকাট টেকনিক", "ভেক্টর") as the topic.

2. **Spatial Processing with Topic Tracking (MANDATORY):**
    - Scan LEFT column top→bottom first, then RIGHT column top→bottom.
    - When you encounter a "Topic N:" header → This becomes the NEW CURRENT TOPIC.
    - ALL questions found AFTER this header (in either column) belong to this NEW CURRENT TOPIC.
    - The topic remains active until you find the *next* header.

3. **Topic Continuation Logic (MANDATORY):**
    - If the page starts with questions (no new topic at the top) → Use the topic from the previous page (I've provided this in TOPIC CONTEXT). Output `TOPIC: CONTINUE`.
    - When you find a new header ("Topic N:", etc.) → Switch to that new topic immediately.

4. **Default Handling:**
    - Use "TOPIC: সাধারণ" ONLY if no topic is provided and no topic is found on the page.

🔴 CRITICAL LATEX REQUIREMENT 🔴
ALL MATHEMATICAL EXPRESSIONS MUST BE IN LATEX FORMAT!
(Examples: ² → $^2$, √x → $\\sqrt{{x}}$, 1/2 → $\\frac{{1}}{{2}}$, ∫ → $\\int$, A⁻¹ → $A^{{-1}}$, A⃗ → $\\vec{{A}}$)

📋 QUESTION FORMAT DETECTION (Supports Multiple Formats):
- Question Number: "01.", "02.", etc.
- Question Text: Bengali/mixed text (may have multiple lines)
- Options: Can be inline "(A) text (B) text" or separate lines
- Support: (A)/(a)/(ক), (B)/(b)/(খ), (C)/(c)/(গ), (D)/(d)/(ঘ)
- Answer: Look for "ANS:(B)", "[Ans: b]", or "Solve ... ⊗ B"
- Reference: Look for "[Ref: source]" or "[RU'19-20]"

📤 UNIVERSAL OUTPUT FORMAT:

TOPIC: [The Bengali topic text OR "CONTINUE" OR "সাধারণ"]
Q_NUM: [number]
Q_TEXT: [full question text WITH LATEX]
OPT_A: [option a text WITH LATEX]
OPT_B: [option b text WITH LATEX]
OPT_C: [option c text WITH LATEX]
OPT_D: [option d text WITH LATEX]
ANS: [correct option letter: a/b/c/d]
REF: [reference/source if exists, else 'NREF']
===END===

Extract ALL questions from this image with STRICT SPATIAL ORDERING and SMART TOPIC TRACKING:
"""
    
    image_data = encode_image(image_path)
    return call_gemini_api(extraction_prompt, image_data, timeout=180)

def safe_json_parse(text):
    """Properly handle LaTeX backslashes and malformed JSON responses."""
    if not text or not text.strip():
        print(f"      DEBUG: Empty response received")
        return None
        
    cleaned = text.strip()
    
    if cleaned.startswith('```'):
        lines = cleaned.split('\n')
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith('```'):
                in_block = not in_block
                continue
            if in_block or (not line.strip().startswith('```')):
                json_lines.append(line)
        cleaned = '\n'.join(json_lines).strip()
    
    json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if not json_match:
        print(f"      DEBUG: No JSON object found in response")
        return None
    
    json_str = json_match.group(0)
    
    try:
        try:
            parsed = json.loads(json_str)
            return parsed
        except json.JSONDecodeError:
            pass
        
        json_str = json_str.replace('\\\\', '\x00DOUBLE_BACKSLASH\x00')
        json_str = json_str.replace('\\', '\\\\')
        json_str = json_str.replace('\x00DOUBLE_BACKSLASH\x00', '\\\\')
        
        try:
            parsed = json.loads(json_str)
            return parsed
        except json.JSONDecodeError:
            pass
        
        json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
        parsed = json.loads(json_str)
        return parsed
        
    except json.JSONDecodeError as e:
        print(f"      DEBUG: JSON parse failed: {e}")
        return None
    except Exception as e:
        print(f"      DEBUG: Unexpected error in safe_json_parse: {e}")
        return None

def generate_explanation(question_text, options, correct_answer):
    """Generate comprehensive explanation using AI with proper JSON handling."""
    
    options_str = "\n".join([f"{opt['key']}) {opt['text']}" for opt in options])

    explanation_prompt = f"""
আপনি একজন উচ্চতর গণিত শিক্ষক। নিচের প্রশ্নের জন্য বিস্তারিত ব্যাখ্যা তৈরি করুন।

প্রশ্ন: {question_text}
অপশন:
{options_str}

সঠিক উত্তর: {correct_answer.upper()}

🔴 CRITICAL INSTRUCTIONS 🔴
1. ALL MATHEMATICAL EXPRESSIONS MUST BE IN LATEX FORMAT!
2. Use $...$ for inline math
3. Return ONLY valid JSON, nothing else
4. Do NOT include markdown code blocks or any text before/after JSON
5. Ensure all backslashes in LaTeX are properly formatted (e.g., \\frac, \\sqrt)
6. START the short explanation with: "সঠিক উত্তর: {correct_answer.upper()}"

Return ONLY this JSON structure (no other text):

{{
  "short": "সঠিক উত্তর: {correct_answer.upper()} - সংক্ষিপ্ত ব্যাখ্যা (২–৩ বাক্য) with LaTeX for all math",
  "detailed": "বিস্তারিত ব্যাখ্যা সূত্র এবং ধারণা সহ (minimum 4-5 sentences) with LaTeX",
  "mathematical_derivation": "গাণিতিক সূত্র, ডেরিভেশন বা প্রমাণ with LaTeX (or 'প্রযোজ্য নয়' if not applicable)",
  "key_concept": "এই প্রশ্নের মূল গাণিতিক ধারণা এবং নীতি (minimum 3-4 sentences)",
  "common_mistakes": "শিক্ষার্থীরা যে ভুল করে থাকে এবং কেন (minimum 3-4 sentences)",
  "real_world_application": "বাস্তব জীবনে বা উচ্চতর গণিতে এর প্রয়োগ (minimum 2-3 sentences)",
  "memory_tip": "সহজে মনে রাখার কৌশল বা সূত্র (minimum 2 sentences)"
}}

CRITICAL: Return ONLY the JSON object. No markdown, no code blocks, no extra text!
"""
    
    max_retries = 3
    for attempt in range(max_retries):
        result = call_gemini_api(explanation_prompt, timeout=180)
        
        if result:
            parsed_json = safe_json_parse(result)
            
            if parsed_json:
                required_fields = ["short", "detailed", "mathematical_derivation", 
                                   "key_concept", "common_mistakes", "real_world_application", "memory_tip"]
                
                if all(field in parsed_json and parsed_json[field] and len(str(parsed_json[field]).strip()) > 5 
                       for field in required_fields):
                    if parsed_json["short"].strip().startswith(f"সঠিক উত্তর: {correct_answer.upper()}"):
                        if attempt > 0:
                            print(f"      ✓ Explanation complete (attempt {attempt + 1})")
                        return parsed_json
                    else:
                        print(f"      ⚠️ Short explanation format wrong (attempt {attempt + 1}/{max_retries}), retrying...")
                else:
                    print(f"      ⚠️ Incomplete fields (attempt {attempt + 1}/{max_retries}), retrying...")
            else:
                print(f"      ⚠️ JSON parsing failed (attempt {attempt + 1}/{max_retries}), retrying...")
        else:
            print(f"      ⚠️ No API response (attempt {attempt + 1}/{max_retries}), retrying...")
        
        if attempt < max_retries - 1:
            time.sleep(0.5)
    
    print(f"      ⚠️ Using fallback explanation after {max_retries} attempts")
    return {
        "short": f"সঠিক উত্তর: {correct_answer.upper()}",
        "detailed": "এই প্রশ্নটি উচ্চতর গণিতের একটি গুরুত্বপূর্ণ ধারণা পরীক্ষা করে। উত্তরটি সাবধানে পড়ুন এবং প্রতিটি বিকল্প বিশ্লেষণ করুন।",
        "mathematical_derivation": "প্রাসঙ্গিক সূত্র এবং নীতি প্রয়োগ করা হয়েছে।",
        "key_concept": "এই ধারণাটি উচ্চতর গণিতের মূল বিষয়গুলির একটি। নিয়মিত অনুশীলনের মাধ্যমে আপনি এটি আরও ভালভাবে বুঝতে পারবেন।",
        "common_mistakes": "অনেক শিক্ষার্থী বিভিন্ন বিকল্পের সূক্ষ্ম পার্থক্য বুঝতে ভুল করে। প্রতিটি বিকল্প সাবধানে বিশ্লেষণ করুন এবং মূল ধারণাটি চিহ্নিত করুন।",
        "real_world_application": "এই গাণিতিক নীতিগুলি প্রকৌশল, পদার্থবিজ্ঞান এবং কম্পিউটার বিজ্ঞানে ব্যাপকভাবে ব্যবহৃত হয়। উচ্চতর পড়াশোনায় এই ধারণাগুলি অত্যন্ত গুরুত্বপূর্ণ।",
        "memory_tip": "নিয়মিত অনুশীলন এবং পুনরাবৃত্তি এটি স্মরণ করতে সাহায্য করবে। সূত্র এবং ধাপগুলি মনে রাখার জন্য সংক্ষিপ্ত নোট তৈরি করুন।"
    }

def extract_structured_questions(raw_text, base_id="math_hs", folder_context=None):
    """Parse extracted text into structured question format with smart topic tracking."""
    global GLOBAL_TOPIC_TRACKER
    
    questions = []
    question_blocks = raw_text.split('===END===')
    
    for idx, block in enumerate(question_blocks, 1):
        if not block.strip():
            continue
        
        try:
            q_data = {}
            lines = block.strip().split('\n')
            
            topic_for_this_question_str = None
            
            for line in lines:
                line = line.strip()
                if line.startswith('TOPIC:'):
                    topic_for_this_question_str = line.replace('TOPIC:', '').strip()
                elif line.startswith('Q_NUM:'):
                    q_data['number'] = line.replace('Q_NUM:', '').strip()
                elif line.startswith('Q_TEXT:'):
                    q_data['text'] = line.replace('Q_TEXT:', '').strip()
                elif line.startswith('OPT_A:'):
                    q_data['opt_a'] = line.replace('OPT_A:', '').strip()
                elif line.startswith('OPT_B:'):
                    q_data['opt_b'] = line.replace('OPT_B:', '').strip()
                elif line.startswith('OPT_C:'):
                    q_data['opt_c'] = line.replace('OPT_C:', '').strip()
                elif line.startswith('OPT_D:'):
                    q_data['opt_d'] = line.replace('OPT_D:', '').strip()
                elif line.startswith('ANS:'):
                    answer_raw = line.replace('ANS:', '').strip().lower()
                    q_data['answer'] = answer_raw[0] if answer_raw else 'a'
                elif line.startswith('REF:'):
                    q_data['reference'] = line.replace('REF:', '').strip()
            
            required = ['number', 'text', 'opt_a', 'opt_b', 'opt_c', 'opt_d', 'answer']
            if not all(key in q_data for key in required):
                print(f"⚠️ Skipping incomplete question block {idx} (missing data)")
                continue
            
            # Topic Logic (INTACT)
            if topic_for_this_question_str:
                if topic_for_this_question_str == "CONTINUE":
                    pass 
                elif topic_for_this_question_str == "Self Test":
                    if GLOBAL_TOPIC_TRACKER["current_topic_bn"] != "Self Test":
                        print(f"   🔖 New Topic Detected: Self Test")
                        GLOBAL_TOPIC_TRACKER["current_topic_bn"] = "Self Test"
                        GLOBAL_TOPIC_TRACKER["current_topic_en"] = "Self Test"
                elif topic_for_this_question_str and topic_for_this_question_str not in ["সাধারণ", "General"]:
                    if GLOBAL_TOPIC_TRACKER["current_topic_bn"] != topic_for_this_question_str:
                        print(f"   🔖 New Topic Detected: {topic_for_this_question_str}")
                        GLOBAL_TOPIC_TRACKER["current_topic_bn"] = topic_for_this_question_str
                        GLOBAL_TOPIC_TRACKER["current_topic_en"] = translate_topic_to_english(topic_for_this_question_str)
                        print(f"     └─ English: {GLOBAL_TOPIC_TRACKER['current_topic_en']}")
                elif topic_for_this_question_str in ["সাধারণ", "General"] and not GLOBAL_TOPIC_TRACKER["current_topic_bn"]:
                    print("   🔖 Setting default topic: সাধারণ")
                    GLOBAL_TOPIC_TRACKER["current_topic_bn"] = "সাধারণ"
                    GLOBAL_TOPIC_TRACKER["current_topic_en"] = "General"
            
            if not GLOBAL_TOPIC_TRACKER["current_topic_bn"]:
                print("   🔖 No topic found, setting default: সাধারণ")
                GLOBAL_TOPIC_TRACKER["current_topic_bn"] = "সাধারণ"
                GLOBAL_TOPIC_TRACKER["current_topic_en"] = "General"
            
            current_topic_bn = GLOBAL_TOPIC_TRACKER["current_topic_bn"]
            current_topic_en = GLOBAL_TOPIC_TRACKER["current_topic_en"]

            options = [
                {"key": "a", "text": q_data['opt_a']},
                {"key": "b", "text": q_data['opt_b']},
                {"key": "c", "text": q_data['opt_c']},
                {"key": "d", "text": q_data['opt_d']}
            ]
            
            correct_answer = q_data['answer']
            reference = q_data.get('reference', 'NREF')
            
            difficulty = "easy-medium"
            math_symbols = [
                '$', '^', 'frac', 'theta', 'Delta', 'int', 'lim', 'sum', 'sqrt',
                '\\frac', '\\theta', '\\Delta', '\\int', '\\lim', '\\sum', '\\sqrt'
            ]
            if any(symbol in q_data['text'] for symbol in math_symbols):
                difficulty = "medium-hard"
            
            topic_tags = ["MCQ", "Mathematics", "Higher_Math", "HSC"]
            if current_topic_en:
                topic_tags.append(current_topic_en.replace(' ', '_').replace('-', '_'))
            
            # Use folder context instead of hardcoded
            question_context = folder_context.copy() if folder_context else {}
            question_context["topic_bn"] = current_topic_bn
            question_context["topic_en"] = current_topic_en

            question_obj = {
                "id": f"{base_id}_{q_data['number'].replace('.', '')}",
                "context": question_context,
                "question_text": q_data['text'],
                "options": options,
                "correct_answer_key": correct_answer,
                "reference": reference,
                "tags": topic_tags,
                "difficulty": difficulty,
                "is_generated": False,
                "original_question_id": None
            }
            
            questions.append(question_obj)
            print(f"   ✓ Structured Q{q_data['number']} (Topic: {current_topic_bn})")
            
        except Exception as e:
            print(f"⚠️ Error structuring question block {idx}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    return questions

def generate_explanations_only(questions):
    """Generates explanations for all original questions (NO similar questions)."""
    num_questions = len(questions)
    if num_questions == 0:
        return []

    print(f"   └─ Generating {num_questions} explanations...")
    
    all_questions_final = []
    explanation_results = [None] * num_questions
    futures_to_q_index_exp = {}

    # Generate explanations for ORIGINALS only
    print(f"     ├─ Generating {num_questions} explanations for originals...")
    with ThreadPoolExecutor(max_workers=MAX_INNER_WORKERS) as executor:
        for i, q in enumerate(questions):
            future = executor.submit(
                generate_explanation, 
                q['question_text'], 
                q['options'], 
                q['correct_answer_key']
            )
            futures_to_q_index_exp[future] = i

        for future in as_completed(futures_to_q_index_exp):
            q_index = futures_to_q_index_exp[future]
            try:
                explanation = future.result()
                explanation_results[q_index] = explanation
            except Exception as e:
                print(f"     ❌ Error generating explanation for {questions[q_index]['id']}: {e}")

    # Assemble final list (originals with explanations only)
    for i, original_q in enumerate(questions):
        original_q['explanation'] = explanation_results[i]
        all_questions_final.append(original_q)

    return all_questions_final

def process_image(image_path, folder_context):
    """Main processing function for each image with topic continuation."""
    global GLOBAL_TOPIC_TRACKER
    
    filename = Path(image_path).stem
    print(f"[🧠] Processing {filename}.jpg ...")
    
    prev_topic_bn = GLOBAL_TOPIC_TRACKER["current_topic_bn"]
    prev_topic_en = GLOBAL_TOPIC_TRACKER["current_topic_en"]
    
    print(f"   └─ Extracting raw text...")
    if prev_topic_bn:
        print(f"     └─ Continuing from previous topic: {prev_topic_bn}")
        
    raw_text = extract_questions_from_image(image_path, prev_topic_bn, prev_topic_en)
    
    if not raw_text:
        print(f"❌ Failed to extract text from {filename}")
        return None
    
    print(f"   └─ Structuring questions (and updating topics)...")
    structured_questions = extract_structured_questions(raw_text, f"math_hs_{filename}", folder_context)
    
    if not structured_questions:
        print(f"⚠️ No structured questions found in {filename}")
        return None

    final_questions_list = generate_explanations_only(structured_questions)
    
    print(f"✅ Processed: {filename}.jpg ({len(final_questions_list)} questions)")
    print(f"   └─ Current Global Topic is now: {GLOBAL_TOPIC_TRACKER['current_topic_bn']}")
    
    return final_questions_list

def merge_json_files(json_data_list, folder_name, output_folder):
    """Merge all JSON data into a single full.json file for the folder."""
    if not json_data_list:
        print(f"⚠️ No data to merge for folder: {folder_name}")
        return None
    
    all_questions = []
    for data in json_data_list:
        if data and isinstance(data, list):
            all_questions.extend(data)
    
    if all_questions:
        full_json_path = Path(output_folder) / "full.json"
        with open(full_json_path, 'w', encoding='utf-8') as f:
            json.dump(all_questions, f, ensure_ascii=False, indent=2)
        
        print(f"\n📦 Consolidated full.json created for {folder_name}!")
        print(f"   └─ Location: {full_json_path}")
        print(f"   └─ Total Questions: {len(all_questions)}")
        print(f"   └─ File Size: {full_json_path.stat().st_size / (1024*1024):.2f} MB")
        
        return str(full_json_path)
    return None

def get_sorted_images(folder_path):
    """Get images sorted by filename (natural sorting for numbers)."""
    def natural_sort_key(path):
        filename = path.stem
        numbers = re.findall(r'(\d+)', filename)
        if numbers:
            return int(numbers[-1])
        return filename
    
    images = sorted(Path(folder_path).glob("*.jpg"), key=natural_sort_key)
    return [str(img) for img in images]

def load_folder_contexts():
    """Load folder contexts from JSON file."""
    if not os.path.exists(CONTEXTS_FILE):
        print(f"❌ {CONTEXTS_FILE} not found!")
        return None
    
    with open(CONTEXTS_FILE, 'r', encoding='utf-8') as f:
        contexts = json.load(f)
    
    return contexts

def save_progress_state(folder_name, processed_count, total_count):
    """Save processing progress to file."""
    state_file = Path(OUTPUT_BASE_FOLDER) / folder_name / "progress.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    
    state = {
        "folder": folder_name,
        "processed": processed_count,
        "total": total_count,
        "timestamp": time.time(),
        "topic_tracker": GLOBAL_TOPIC_TRACKER.copy()
    }
    
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_progress_state(folder_name):
    """Load processing progress from file."""
    state_file = Path(OUTPUT_BASE_FOLDER) / folder_name / "progress.json"
    
    if not state_file.exists():
        return None
    
    with open(state_file, 'r', encoding='utf-8') as f:
        state = json.load(f)
    
    return state

def process_folder_with_breaks(folder_name, folder_context, batch_size=20, break_minutes=20):
    """Process a folder with breaks every batch_size images."""
    global GLOBAL_TOPIC_TRACKER
    
    folder_path = Path(BASE_IMAGES_FOLDER) / folder_name
    output_folder = Path(OUTPUT_BASE_FOLDER) / folder_name
    output_folder.mkdir(parents=True, exist_ok=True)
    
    if not folder_path.exists():
        print(f"❌ Folder not found: {folder_path}")
        return None
    
    images = get_sorted_images(folder_path)
    
    if not images:
        print(f"❌ No images found in folder: {folder_name}")
        return None
    
    # Load previous progress if exists
    progress = load_progress_state(folder_name)
    start_index = 0
    
    if progress:
        start_index = progress.get('processed', 0)
        if start_index >= len(images):
            print(f"✅ Folder {folder_name} already fully processed!")
            return str(output_folder / "full.json")
        
        # Restore topic tracker
        saved_tracker = progress.get('topic_tracker')
        if saved_tracker:
            GLOBAL_TOPIC_TRACKER.update(saved_tracker)
            print(f"🔄 Resuming from image {start_index + 1}/{len(images)}")
            print(f"   └─ Restored topic: {GLOBAL_TOPIC_TRACKER['current_topic_bn']}")
    else:
        # Reset topic tracker for new folder
        GLOBAL_TOPIC_TRACKER = {
            "current_topic_bn": None,
            "current_topic_en": None
        }
    
    print(f"\n{'='*60}")
    print(f"📁 Processing Folder: {folder_name}")
    print(f"{'='*60}")
    print(f"   └─ Total Images: {len(images)}")
    print(f"   └─ Starting from: {start_index + 1}")
    print(f"   └─ Batch Size: {batch_size}")
    print(f"   └─ Break Duration: {break_minutes} minutes")
    print(f"   └─ Topic tracking: ENABLED")
    print()
    
    all_json_data = []
    
    for idx in range(start_index, len(images)):
        img = images[idx]
        
        print(f"\n{'='*60}")
        print(f"📄 Image {idx + 1}/{len(images)}: {Path(img).name}")
        print(f"{'='*60}")
        
        try:
            json_data = process_image(img, folder_context)
            if json_data:
                all_json_data.append(json_data)
                
                # Save individual file
                filename = Path(img).stem
                output_path = output_folder / f"{filename}.json"
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(json_data, f, ensure_ascii=False, indent=2)
                print(f"   └─ Saved: {output_path.name}")
            
            # Save progress
            save_progress_state(folder_name, idx + 1, len(images))
            
            # Check if we need a break
            if (idx + 1) % batch_size == 0 and (idx + 1) < len(images):
                print(f"\n{'='*60}")
                print(f"⏸️  BREAK TIME - Processed {idx + 1}/{len(images)} images")
                print(f"{'='*60}")
                print(f"   └─ Sleeping for {break_minutes} minutes...")
                print(f"   └─ Current topic: {GLOBAL_TOPIC_TRACKER['current_topic_bn']}")
                print(f"   └─ Will resume at image {idx + 2}")
                
                for remaining in range(break_minutes * 60, 0, -30):
                    mins, secs = divmod(remaining, 60)
                    print(f"   └─ Time remaining: {mins:02d}:{secs:02d}", end='\r')
                    time.sleep(30)
                
                print(f"\n   └─ Resuming processing...")
                print(f"{'='*60}\n")
                
        except Exception as e:
            print(f"❌ Critical error processing {img}: {e}")
            import traceback
            traceback.print_exc()
    
    # Merge all JSON files
    print(f"\n{'='*60}")
    print(f"🔗 Merging JSON files for folder: {folder_name}")
    print(f"{'='*60}")
    
    full_json_path = merge_json_files(all_json_data, folder_name, output_folder)
    
    print(f"\n✅ Folder processing complete: {folder_name}")
    print(f"   └─ Output folder: {output_folder}")
    print(f"   └─ Final topic: {GLOBAL_TOPIC_TRACKER['current_topic_bn']}")
    
    return full_json_path

def process_all_folders():
    """Process all folders defined in folder_contexts.json."""
    contexts = load_folder_contexts()
    
    if not contexts:
        print("❌ Could not load folder contexts!")
        return
    
    if not isinstance(contexts, dict) or 'folders' not in contexts:
        print("❌ Invalid folder_contexts.json format!")
        print("Expected: {'folders': [{'name': '...', 'context': {...}}, ...]}")
        return
    
    folders = contexts['folders']
    
    print(f"\n{'='*80}")
    print(f"🚀 STARTING MULTI-FOLDER PROCESSING")
    print(f"{'='*80}")
    print(f"   └─ Total Folders: {len(folders)}")
    print(f"   └─ Loaded {len(API_KEYS)} API keys")
    print(f"   └─ Topic tracking: ENABLED (carries across pages within each folder)")
    print(f"   └─ Similar questions: DISABLED")
    print(f"   └─ Break interval: Every 20 images, rest 20 minutes")
    print(f"{'='*80}\n")
    
    start_time = time.time()
    completed_folders = []
    
    for idx, folder_info in enumerate(folders, 1):
        folder_name = folder_info.get('name')
        folder_context = folder_info.get('context')
        
        if not folder_name or not folder_context:
            print(f"⚠️ Skipping invalid folder entry at index {idx}")
            continue
        
        print(f"\n{'#'*80}")
        print(f"📂 FOLDER {idx}/{len(folders)}: {folder_name}")
        print(f"{'#'*80}\n")
        
        full_json_path = process_folder_with_breaks(folder_name, folder_context)
        
        if full_json_path:
            completed_folders.append({
                'name': folder_name,
                'output_path': full_json_path
            })
    
    elapsed = time.time() - start_time
    hours, remainder = divmod(int(elapsed), 3600)
    minutes, seconds = divmod(remainder, 60)
    
    print(f"\n{'='*80}")
    print(f"🏁 ALL FOLDERS PROCESSING COMPLETE")
    print(f"{'='*80}")
    print(f"   └─ Total Time: {hours:02d}:{minutes:02d}:{seconds:02d}")
    print(f"   └─ Folders Processed: {len(completed_folders)}/{len(folders)}")
    print(f"   └─ Translation Cache Size: {len(TOPIC_TRANSLATION_CACHE)} topics")
    print(f"\n📋 Completed Folders:")
    
    for folder_info in completed_folders:
        print(f"   ✅ {folder_info['name']}")
        print(f"      └─ Output: {folder_info['output_path']}")
    
    print(f"{'='*80}\n")

# ================== MAIN ==================

if __name__ == "__main__":
    process_all_folders()