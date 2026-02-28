from flask import Flask, render_template, request, jsonify, session
import requests
from bs4 import BeautifulSoup
import time
import re
import json
from datetime import datetime
import secrets
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

GROQ_API_KEY          = os.getenv('GROQ_API_KEY', '')
GEMINI_API_KEY        = os.getenv('GEMINI_API_KEY', '')  # kept for backward compat
USE_AI_EVALUATION     = os.getenv('USE_AI_EVALUATION', 'true').lower() == 'true'
USE_AI_SKILL_ANALYSIS = os.getenv('USE_AI_SKILL_ANALYSIS', 'true').lower() == 'true'
GROQ_MODEL            = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')

# Use Groq if available, else fall back to Gemini
ACTIVE_API = 'groq' if GROQ_API_KEY else ('gemini' if GEMINI_API_KEY else None)

print("=" * 60)
print("🔧 AURA CONFIGURATION:")
print(f"  USE_AI_EVALUATION    : {USE_AI_EVALUATION}")
print(f"  USE_AI_SKILL_ANALYSIS: {USE_AI_SKILL_ANALYSIS}")
print(f"  GROQ_API_KEY         : {'✅ set' if GROQ_API_KEY else '❌ MISSING'}")
print(f"  GEMINI_API_KEY       : {'✅ set' if GEMINI_API_KEY else '❌ MISSING'}")
print(f"  ACTIVE_API           : {ACTIVE_API or '❌ NONE - will use fallback!'}")
if GROQ_API_KEY:
    print(f"  GROQ_MODEL           : {GROQ_MODEL}")
print("=" * 60)
print()

def call_ai_api(prompt, max_tokens=2048, temperature=0.3):
    """
    Unified AI API caller: tries Groq first, falls back to Gemini.
    Returns parsed JSON response or None on error.
    """
    if GROQ_API_KEY:
        result = call_groq_api(prompt, max_tokens, temperature)
        if result is not None:
            return result
        print("⚠️  Groq failed → trying Gemini fallback")
    if GEMINI_API_KEY:
        return call_gemini_api(prompt, max_tokens, temperature)
    return None

def call_groq_api(prompt, max_tokens=2048, temperature=0.3):
    """Call Groq API (OpenAI-compatible). Returns parsed JSON or None."""
    try:
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {GROQ_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': GROQ_MODEL,
                'messages': [{'role': 'user', 'content': prompt}],
                'max_tokens': max_tokens,
                'temperature': temperature,
            },
            timeout=60
        )

        if response.status_code == 200:
            data = response.json()
            content = data['choices'][0]['message']['content'].strip()
            print(f"📥 Groq raw response preview: {content[:150]}...")
            return _parse_json_from_content(content)
        else:
            print(f"❌ Groq API error {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"❌ Groq API exception: {str(e)}")
        return None

def call_gemini_api(prompt, max_tokens=2048, temperature=0.3):
    """Call Gemini API. Returns parsed JSON or None."""
    if not GEMINI_API_KEY:
        return None
    
    try:
        # Gemini uses REST API with API key in URL
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={GEMINI_API_KEY}'
        
        response = requests.post(
            url,
            headers={'Content-Type': 'application/json'},
            json={
                'contents': [{
                    'parts': [{'text': prompt}]
                }],
                'generationConfig': {
                    'temperature': temperature,
                    'maxOutputTokens': max_tokens
                }
            },
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            if 'candidates' not in data or not data['candidates']:
                print(f"❌ Gemini: No candidates in response")
                return None
            content = data['candidates'][0]['content']['parts'][0]['text'].strip()
            print(f"📥 Gemini raw response preview: {content[:150]}...")
            return _parse_json_from_content(content)
        else:
            print(f"❌ Gemini API error {response.status_code}: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"❌ Gemini API exception: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def _parse_json_from_content(content):
    """Parse JSON from API response, handling markdown code blocks."""
    if '```json' in content:
        start = content.find('```json') + 7
        end = content.find('```', start)
        if end > start:
            content = content[start:end].strip()
    elif '```' in content:
        parts = content.split('```')
        if len(parts) >= 3:
            content = parts[1].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode error: {e}")
        if '{' in content and '}' in content:
            s = content.find('{')
            e2 = content.rfind('}') + 1
            try:
                return json.loads(content[s:e2])
            except:
                pass
        return None

def fetch_vietnamworks_detail(job_url):
    """
    Scrape JD & JR from VietnamWorks job detail page
    VietnamWorks job pages are not blocked!
    """
    try:
        time.sleep(0.5)
        response = requests.get(
            job_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8',
            },
            timeout=10
        )
        
        if response.status_code != 200:
            print(f"    Detail page status: {response.status_code}")
            return ''
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        parts = []
        
        selectors = [
            'div.job-description',
            'div[class*="job-description"]',
            'div[class*="description"]',
            'section[class*="description"]',
            'div.job-details',
            'div[class*="job-detail"]',
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            for el in elements:
                text = el.get_text(separator='\n', strip=True)
                if len(text) > 100:
                    parts.append(text)
            if parts:
                break
        
        if not parts:
            headings = soup.find_all(['h2', 'h3'], string=re.compile(
                r'mô tả|yêu cầu|description|requirement|job detail|kỹ năng|skill',
                re.IGNORECASE
            ))
            for heading in headings:
                sibling = heading.find_next_sibling()
                if sibling:
                    text = sibling.get_text(separator='\n', strip=True)
                    if len(text) > 50:
                        parts.append(text)
        
        result = '\n'.join(filter(None, parts))
        if result:
            print(f"    ✅ Got {len(result)} chars of JD/JR")
        else:
            print(f"    ⚠️  No JD/JR found on page")
        
        return result
        
    except Exception as e:
        print(f"    Error fetching detail: {str(e)}")
        return ''

def scrape_itviec_jobs(job_title, max_results=30):
    """
    Fetch jobs from VietnamWorks public API
    No scraping needed - uses official JSON API
    Works everywhere including deployed servers!
    """
    results = []
    
    try:
        print(f"\n🌐 Fetching from VietnamWorks API: {job_title}")
        
        response = requests.post(
            'https://ms.vietnamworks.com/job-search/v1.0/search',
            headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.vietnamworks.com/',
            'Origin': 'https://www.vietnamworks.com',
        },
            json={
            "query": job_title,
            "filter": [],
            "ranges": [],
            "order": [{"field": "relevant", "order": "desc"}],
            "hitsPerPage": max_results,
            "page": 0,
            "languageCode": "vi"
        },
            timeout=30
        )
        
        print(f"  Status: {response.status_code}")
        
        if response.status_code != 200:
            return {
                'success': False,
                'message': f'VietnamWorks API error: {response.status_code}',
                'jobs': []
            }
        
        data = response.json()
        
        jobs_data = data.get('data', [])
        
        print(f"  Found {len(jobs_data)} jobs")
        
        for job in jobs_data:
            try:
                if not isinstance(job, dict):
                    continue
                
                title = job.get('jobTitle', '')
                job_url = job.get('jobUrl', '')
                job_id = job.get('jobId', '')
                
                
                description_parts = []
                
                for field in ['jobDescription', 'jobRequirement', 'benefit']:
                    val = job.get(field, '')
                    if val and isinstance(val, str) and len(val) > 50:
                        description_parts.append(val)
                
                skills = job.get('skills') or []
                if skills and isinstance(skills, list):
                    skill_names = []
                    for s in skills:
                        if isinstance(s, dict):
                            skill_names.append(s.get('skillName', '') or s.get('name', '') or s.get('skill', ''))
                        elif isinstance(s, str):
                            skill_names.append(s)
                    if skill_names:
                        description_parts.append(' '.join(filter(None, skill_names)))
                
                if not description_parts and job_url:
                    detail = fetch_vietnamworks_detail(job_url)
                    if detail:
                        description_parts.append(detail)
                
                combined_text = '\n'.join(filter(None, description_parts))
                
                if title and combined_text:
                    results.append({
                        'title': title,
                        'url': job_url,
                        'description_details': [{
                            'heading': 'Job Description & Requirements',
                            'content': combined_text
                        }]
                    })
                    print(f"  ✅ {title[:50]}")
                else:
                    print(f"  ⚠️  Skipped (no description): {title[:50]}")
                    
            except Exception as e:
                print(f"  Error parsing job: {str(e)}")
                continue
        
        if not results:
            return {
                'success': False,
                'message': f'Không tìm thấy việc làm cho "{job_title}". Thử keyword khác.',
                'jobs': []
            }
        
        print(f"\n✅ Got {len(results)} jobs from VietnamWorks")
        
        return {
            'success': True,
            'message': f'Tìm thấy {len(results)} công việc trên VietnamWorks',
            'jobs': results
        }
        
    except requests.exceptions.RequestException as e:
        return {'success': False, 'message': f'Lỗi kết nối: {str(e)}', 'jobs': []}
    except Exception as e:
        return {'success': False, 'message': f'Lỗi: {str(e)}', 'jobs': []}
        
def analyze_jd_jr_with_gemini(jobs):
    """Call AI API to analyze JD/JR and extract skills"""
    if not ACTIVE_API:
        print("⚠️  No AI API configured → skip AI analysis")
        return None

    print(f"\n{'='*60}")
    print(f"🤖 AI ({ACTIVE_API.upper()}): ANALYZING JD/JR")
    print(f"{'='*60}")

    jd_texts = []
    for i, job in enumerate(jobs[:30], 1):
        if job.get('description_details'):
            text = '\n'.join(s['content'] for s in job['description_details'])
            jd_texts.append(f"[Job {i}]\n{text}")

    if not jd_texts:
        print("❌ No job descriptions to analyze")
        return None

    combined = '\n\n---\n\n'.join(jd_texts)
    if len(combined) > 40000:
        combined = combined[:40000] + '\n\n[Truncated...]'

    print(f"📊 {len(jd_texts)} jobs  |  {len(combined):,} chars")

    prompt = f"""Bạn là chuyên gia phân tích tuyển dụng IT. Phân tích các Job Description / Job Requirements sau.

{combined}

NHIỆM VỤ:
1. Trích xuất TẤT CẢ kỹ năng kỹ thuật (technical skills) được yêu cầu
2. Đếm số job yêu cầu mỗi skill (mỗi job chỉ đếm 1 lần)
3. Phân loại đúng category

CRITICAL: Respond ONLY with valid JSON. NO markdown, NO explanation, NO text before or after JSON.
Start response with {{ and end with }}

JSON format:
{{
  "skills": [
    {{
      "skill": "Tên chuẩn (vd: Python, React, Docker)",
      "job_count": <số nguyên>,
      "percentage": <số thực 1 chữ số>,
      "category": "Programming Language|Frontend|Backend|Database|DevOps|Tools|Data/AI|Soft Skills"
    }}
  ]
}}

Lưu ý:
- Tổng jobs = {len(jobs)}, percentage = job_count / {len(jobs)} * 100
- Tối đa 30 skills, sắp xếp job_count giảm dần
- Bao gồm soft skills nếu xuất hiện nhiều
- ONLY return the JSON object, nothing else"""

    print("📤 Calling Gemini API...")
    
    result = call_ai_api(
        prompt=prompt,
        max_tokens=2048,
        temperature=0.2
    )
    
    if result and 'skills' in result:
        skills = result['skills']
        total_jobs = len(jobs)
        # Recalculate percentage from job_count to avoid AI hallucinating wrong numbers
        for s in skills:
            job_count = s.get('job_count', 0)
            s['percentage'] = round(job_count / total_jobs * 100, 1) if total_jobs > 0 else 0
        print(f"✅ Gemini extracted {len(skills)} skills:")
        for s in skills[:10]:
            print(f"   • {s['skill']}: {s['percentage']}% ({s['job_count']} jobs) [{s['category']}]")
        return skills
    
    print("❌ Gemini analysis failed")
    return None

def analyze_skills_from_jobs(jobs):
    """
    Entry point: dùng Groq nếu USE_AI_SKILL_ANALYSIS=true,
    fallback về keyword matching nếu Groq fail hoặc tắt.
    """
    if USE_AI_SKILL_ANALYSIS:
        print("🤖 Using Groq skill analysis...")
        result = analyze_jd_jr_with_gemini(jobs)
        if result:
            return result
        print("⚠️  Groq failed → fallback to keyword matching")
    else:
        print("🔤 Using keyword skill analysis...")

    return analyze_skills_from_jobs_keyword(jobs)

def analyze_skills_from_jobs_keyword(jobs):
    """Keyword-based fallback — nhanh, không cần API."""
    skill_database = {
        'Python': ['python', 'py'],
        'Java': ['java', 'spring boot', 'spring framework'],
        'JavaScript': ['javascript', 'js', 'ecmascript'],
        'TypeScript': ['typescript', 'ts'],
        'C#': ['c#', 'csharp', '.net', 'dotnet'],
        'PHP': ['php'],
        'Go': ['golang', 'go programming'],
        'Ruby': ['ruby', 'ruby on rails'],
        'C++': ['c++', 'cpp'],
        'Rust': ['rust'],
        'Kotlin': ['kotlin'],
        'Swift': ['swift'],
        
        'React': ['react', 'reactjs', 'react.js'],
        'Vue.js': ['vue', 'vuejs', 'vue.js'],
        'Angular': ['angular', 'angularjs'],
        'HTML/CSS': ['html', 'css', 'html5', 'css3'],
        'Next.js': ['next.js', 'nextjs'],
        'Tailwind CSS': ['tailwind', 'tailwindcss'],
        
        'Django': ['django'],
        'Flask': ['flask'],
        'FastAPI': ['fastapi'],
        'Spring Boot': ['spring boot', 'springboot'],
        'Laravel': ['laravel'],
        'Express.js': ['express', 'expressjs', 'express.js'],
        'Node.js': ['node.js', 'nodejs', 'node js'],
        
        'SQL': ['sql', 'mysql', 'postgresql', 'postgres', 'mssql'],
        'MongoDB': ['mongodb', 'mongo'],
        'Redis': ['redis'],
        'Elasticsearch': ['elasticsearch', 'elastic search'],
        'Firebase': ['firebase'],
        
        'AWS': ['aws', 'amazon web services'],
        'Azure': ['azure', 'microsoft azure'],
        'Google Cloud': ['gcp', 'google cloud', 'google cloud platform'],
        'Docker': ['docker', 'containerization'],
        'Kubernetes': ['kubernetes', 'k8s'],
        'CI/CD': ['ci/cd', 'jenkins', 'gitlab ci', 'github actions'],
        'Terraform': ['terraform'],
        
        'Git': ['git', 'github', 'gitlab', 'version control'],
        'REST API': ['rest', 'restful', 'rest api'],
        'GraphQL': ['graphql'],
        'Microservices': ['microservices', 'microservice'],
        'Linux': ['linux', 'ubuntu', 'unix'],
        'Agile/Scrum': ['agile', 'scrum', 'kanban'],
        'Testing': ['unit test', 'testing', 'jest', 'pytest', 'selenium'],
        'OOP': ['oop', 'object-oriented', 'lập trình hướng đối tượng'],
        
        'Machine Learning': ['machine learning', 'ml', 'sklearn'],
        'Deep Learning': ['deep learning', 'neural network', 'tensorflow', 'pytorch'],
        'Data Analysis': ['data analysis', 'pandas', 'numpy'],
        'SQL Analytics': ['data analytics', 'bi', 'tableau', 'power bi'],
        
        'English': ['tiếng anh', 'english', 'toeic', 'ielts'],
        'Communication': ['giao tiếp', 'communication', 'presentation'],
        'Teamwork': ['làm việc nhóm', 'teamwork', 'collaboration'],
        'Problem Solving': ['giải quyết vấn đề', 'problem solving', 'analytical'],
    }
    
    skill_job_counts = {skill: 0 for skill in skill_database.keys()}
    
    for job in jobs:
        if not job.get('description_details'):
            continue
        job_text = '\n'.join([s['content'] for s in job['description_details']]).lower()
        for skill_name, keywords in skill_database.items():
            if any(kw.lower() in job_text for kw in keywords):
                skill_job_counts[skill_name] += 1
    
    skill_counts = {k: v for k, v in skill_job_counts.items() if v > 0}
    sorted_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)
    
    total_jobs = len(jobs)
    return [
        {
            'skill': skill,
            'job_count': count,
            'percentage': round(count / total_jobs * 100, 1),
            'category': get_skill_category(skill, skill_database)
        }
        for skill, count in sorted_skills[:30]
    ]

def get_skill_category(skill_name, skill_database):
    """Determine skill category"""
    categories = {
        'Programming Languages': ['Python', 'Java', 'JavaScript', 'TypeScript', 'C#', 'PHP', 'Go', 'Ruby', 'C++', 'Rust', 'Kotlin', 'Swift'],
        'Frontend': ['React', 'Vue.js', 'Angular', 'HTML/CSS', 'Next.js', 'Tailwind CSS'],
        'Backend': ['Django', 'Flask', 'FastAPI', 'Spring Boot', 'Laravel', 'Express.js', 'Node.js'],
        'Database': ['SQL', 'MongoDB', 'Redis', 'Elasticsearch', 'Firebase'],
        'DevOps': ['AWS', 'Azure', 'Google Cloud', 'Docker', 'Kubernetes', 'CI/CD', 'Terraform'],
        'Tools': ['Git', 'REST API', 'GraphQL', 'Microservices', 'Linux', 'Agile/Scrum', 'Testing', 'OOP'],
        'Data/AI': ['Machine Learning', 'Deep Learning', 'Data Analysis', 'SQL Analytics'],
        'Soft Skills': ['English', 'Communication', 'Teamwork', 'Problem Solving']
    }
    
    for category, skills in categories.items():
        if skill_name in skills:
            return category
    return 'Other'

def generate_technical_challenge(job_title, top_skills):
    """
    Generate technical challenge by picking 5 questions from question bank
    Based on top TECHNICAL skills from market analysis
    """
    
    print("\n" + "="*60)
    print("🎯 GENERATING TECHNICAL CHALLENGE")
    print("="*60)
    
    # Load question bank
    try:
        with open('skill_questions.json', 'r', encoding='utf-8') as f:
            question_bank = json.load(f)
        print(f"✅ Loaded question bank with {len(question_bank)} skills")
    except FileNotFoundError:
        print("⚠️  skill_questions.json not found - using fallback")
        return generate_fallback_challenge(job_title, top_skills)
    
    # Filter TECH SKILLS only (exclude soft skills)
    soft_skills = ['English', 'Communication', 'Teamwork', 'Problem Solving']
    tech_skills = [s for s in top_skills if s['skill'] not in soft_skills]
    
    # Skill name mapping: market skill → question bank skill
    skill_name_mapping = {
        'HTML/CSS': ['HTML/HTML5', 'CSS/CSS3'],  # Map to BOTH
        'HTML5': 'HTML/HTML5',
        'HTML': 'HTML/HTML5',
        'CSS3': 'CSS/CSS3',
        'CSS': 'CSS/CSS3',
        'PostgreSQL': 'SQL',
        'MySQL': 'SQL',
        'NoSQL': 'MongoDB',
        'Google Cloud': 'AWS',
        'Azure': 'AWS',
        'GCP': 'AWS',
    }
    
    print(f"\n📊 Top tech skills from market:")
    for i, skill in enumerate(tech_skills[:10], 1):
        print(f"  {i}. {skill['skill']}: {skill['percentage']}% ({skill['job_count']} jobs)")
    
    # Match market skills with question bank
    matched_skills = []
    for skill_data in tech_skills:
        skill_name = skill_data['skill']
        
        # Try direct match first
        if skill_name in question_bank:
            matched_skills.append(skill_data)
            print(f"✅ Matched: {skill_name}")
        # Try mapped name
        elif skill_name in skill_name_mapping:
            mapped = skill_name_mapping[skill_name]
            
            # Handle 1-to-many mapping (e.g., HTML/CSS → both HTML and CSS)
            if isinstance(mapped, list):
                for mapped_name in mapped:
                    if mapped_name in question_bank:
                        mapped_skill = skill_data.copy()
                        mapped_skill['skill'] = mapped_name
                        matched_skills.append(mapped_skill)
                        print(f"✅ Mapped: {skill_name} → {mapped_name}")
            # Handle 1-to-1 mapping
            else:
                if mapped in question_bank:
                    mapped_skill = skill_data.copy()
                    mapped_skill['skill'] = mapped
                    matched_skills.append(mapped_skill)
                    print(f"✅ Mapped: {skill_name} → {mapped}")
                else:
                    print(f"⚠️  Mapping failed: {skill_name} → {mapped}")
        else:
            print(f"⚠️  No questions for: {skill_name}")
    
    if not matched_skills:
        print("❌ No matched skills found - using fallback")
        return generate_fallback_challenge(job_title, top_skills)
    
    print(f"\n🎯 {len(matched_skills)} skills matched with question bank")
    
    # Pick 5 questions from matched skills
    selected_questions = []
    question_id = 1
    
    # Round-robin: pick 1 question from each top skill until we have 5
    for i, skill_data in enumerate(matched_skills):
        if len(selected_questions) >= 5:
            break
            
        skill_name = skill_data['skill']
        skill_info = question_bank[skill_name]
        
        # Get the single question for this skill
        selected_questions.append({
            'id': question_id,
            'skill': skill_name,
            'question': skill_info['question'],
            'skills': [skill_name],
            'evaluation_criteria': skill_info['evaluation_criteria']
        })
        question_id += 1
        print(f"  ✅ Q{question_id-1}: {skill_name}")
    
    print(f"\n✅ Selected {len(selected_questions)} questions")
    
    # Build challenge
    challenge = {
        'job_title': job_title,
        'skills_tested': [q['skill'] for q in selected_questions],
        'questions': selected_questions
    }
    
    return challenge

def generate_fallback_challenge(job_title, top_skills):
    """Fallback when question bank not available - use generic questions"""
    skill_list = [s['skill'] for s in top_skills[:5]]
    
    challenge = {
        'job_title': job_title,
        'skills_tested': skill_list,
        'questions': [
            {
                'id': 1,
                'question': 'Mô tả kinh nghiệm của bạn với các công nghệ trong job description. Những challenges gặp phải và cách giải quyết?',
                'skills': skill_list[:2],
                'evaluation_criteria': [
                    'Hiểu rõ technical concepts',
                    'Problem-solving approach',
                    'Real-world experience',
                    'Learning ability'
                ]
            },
            {
                'id': 2,
                'question': 'Thiết kế architecture cho scalable system. Giải thích các technical decisions và trade-offs.',
                'skills': ['Architecture', 'System Design'],
                'evaluation_criteria': [
                    'System design knowledge',
                    'Scalability considerations',
                    'Trade-off analysis',
                    'Best practices'
                ]
            },
            {
                'id': 3,
                'question': 'Debug performance issue trong production. Mô tả process từ detection đến resolution.',
                'skills': ['Debugging', 'Performance'],
                'evaluation_criteria': [
                    'Debugging methodology',
                    'Profiling tools',
                    'Root cause analysis',
                    'Prevention strategies'
                ]
            }
        ]
    }
    
    return challenge

def evaluate_answer_with_ai(question, answer, evaluation_criteria):
    """Use AI to evaluate answer. Fallback if no API key."""
    if not USE_AI_EVALUATION:
        return fallback_evaluation(answer, evaluation_criteria)

    if ACTIVE_API:
        return evaluate_with_gemini(question, answer, evaluation_criteria)

    print("⚠️  No AI API configured → fallback evaluation")
    return fallback_evaluation(answer, evaluation_criteria)

def evaluate_with_gemini(question, answer, evaluation_criteria):
    """Use AI API (Groq/Gemini) to evaluate answer and determine skill level"""
    
    print("="*50)
    print(f"🚀 CALLING AI API ({ACTIVE_API})...")
    print(f"Question: {question[:50]}...")
    print(f"Answer length: {len(answer)} chars")
    print("="*50)
    
    prompt = f"""You are a senior technical interviewer evaluating a candidate's skill level.

Câu hỏi: {question}

Tiêu chí đánh giá:
{chr(10).join(f"- {c}" for c in evaluation_criteria)}

Câu trả lời của ứng viên:
{answer}

NHIỆM VỤ: Đánh giá trình độ của ứng viên trên kỹ năng này theo thang 0-5:

**LEVEL 0 (No Knowledge):**
- Không hiểu câu hỏi hoặc trả lời hoàn toàn sai
- Không biết khái niệm cơ bản
- Không có kinh nghiệm thực tế

**LEVEL 1 (Beginner - Biết surface level):**
- Biết tên các khái niệm nhưng không hiểu cách hoạt động
- Chỉ liệt kê features/syntax mà không giải thích WHY
- Không đề cập trade-offs
- VD: "React dùng Virtual DOM. Redux quản lý state."

**LEVEL 2 (Elementary - Hiểu cơ bản):**
- Hiểu cách hoạt động ở mức surface
- Giải thích được WHAT nhưng chưa rõ WHY
- Đề cập 1-2 use cases đơn giản
- Chưa phân tích trade-offs
- VD: "Virtual DOM giúp update UI nhanh hơn. Redux dùng khi app phức tạp."

**LEVEL 3 (Competent - Có thể làm việc):**
- Hiểu rõ cách hoạt động và WHY
- Đề cập được 2-3 use cases thực tế
- Nhắc đến 1-2 trade-offs cơ bản
- Có kinh nghiệm làm việc thực tế
- VD: "Virtual DOM diff changes trước khi update real DOM để giảm reflows. Redux tốt cho shared state nhưng overkill cho local state."

**LEVEL 4 (Proficient - Làm việc độc lập tốt):**
- Hiểu sâu mechanisms và WHY
- Phân tích 3+ trade-offs chi tiết với ví dụ cụ thể
- So sánh với alternatives (Redux vs Context vs Zustand)
- Biết khi nào KHÔNG nên dùng
- Đề cập performance implications, debugging strategies
- VD: "Virtual DOM có overhead cho simple updates. Redux: predictable state + time-travel debugging nhưng boilerplate nhiều. Context re-renders nhiều. Zustand: less boilerplate, performance tốt hơn."

**LEVEL 5 (Expert - Architect level):**
- Comprehensive understanding of internals
- Phân tích deep technical details (reconciliation algorithm, fiber architecture)
- 5+ trade-offs với quantifiable impact (bundle size, render time)
- Architecture decisions cho large-scale systems
- Biết edge cases và limitations
- References best practices từ official docs/RFCs
- VD: "React 18 concurrent rendering với startTransition cho non-urgent updates. Redux: normalized state với selectors (reselect) để prevent re-renders. Alternative: Jotai atoms cho atomic state. Trade-off: learning curve vs team size. For 100k+ users: consider state machine (XState) cho complex flows."

CHÚ Ý:
- Đánh giá dựa vào NỘI DUNG trả lời, KHÔNG phải độ dài
- Score thấp nếu chỉ liệt kê mà không giải thích
- Score cao nếu có trade-offs + real-world decisions
- Câu trả lời ngắn nhưng đúng trọng tâm > dài nhưng lan man

CRITICAL: Respond ONLY with valid JSON. NO markdown, NO explanation, NO text before or after.
Start with {{ and end with }}

JSON format:
{{
    "score": <0-5>,
    "level_name": "<No Knowledge|Beginner|Elementary|Competent|Proficient|Expert>",
    "feedback": "<Đánh giá chi tiết bằng tiếng Việt>",
    "strengths": ["điểm mạnh 1", "điểm mạnh 2"],
    "improvements": ["cải thiện 1", "cải thiện 2"]
}}"""

    print(f"📤 Calling AI API ({ACTIVE_API})...")
    
    result = call_ai_api(
        prompt=prompt,
        max_tokens=1500,
        temperature=0.2
    )
    
    if result:
        print(f"✅ AI API SUCCESS! Score: {result.get('score', 0)}/5")
        return result
    
    print("❌ AI API failed → fallback")
    return fallback_evaluation(answer, evaluation_criteria)

def fallback_evaluation(answer, evaluation_criteria):
    """Fallback evaluation when API is not available"""
    score = 0
    answer_lower = answer.lower()
    
    for criterion in evaluation_criteria:
        criterion_lower = criterion.lower()
        if any(word in answer_lower for word in criterion_lower.split() if len(word) > 4):
            score += 1
    
    score = min(5, max(0, score))
    
    level_names = ['No Knowledge', 'Beginner', 'Elementary', 'Competent', 'Proficient', 'Expert']
    
    return {
        'score': score,
        'level_name': level_names[score],
        'feedback': f'Đánh giá tự động (API chưa cấu hình). Câu trả lời đề cập {score}/{len(evaluation_criteria)} tiêu chí.',
        'strengths': ['Có đề cập khái niệm liên quan'] if score > 0 else [],
        'improvements': ['Phân tích trade-offs', 'Thêm ví dụ thực tế', 'Cấu hình GROQ_API_KEY để đánh giá chính xác']
    }

def calculate_skill_gap(assessment_results, market_skills):
    """
    Calculate skill gap between user's current level and market requirements
    """
    skill_gaps = []
    
    for result in assessment_results:
        skill_name = result['skill']
        user_level = result['level']
        
        market_skill = next((s for s in market_skills if s['skill'] == skill_name), None)
        
        if market_skill:
            market_importance = min(5, int(market_skill['percentage'] / 50))  # Scale to 0-5
            gap = market_importance - user_level
            
            if gap > 0:  # Only skills that need improvement
                skill_gaps.append({
                    'skill': skill_name,
                    'current_level': user_level,
                    'required_level': market_importance,
                    'gap': gap,
                    'priority': 'High' if gap >= 3 else 'Medium' if gap >= 2 else 'Low',
                    'category': result.get('category', 'Other')
                })
    
    skill_gaps.sort(key=lambda x: x['gap'], reverse=True)
    
    return skill_gaps

def generate_learning_suggestions(evaluations, top_skills):
    """
    Generate learning suggestions for top 5 skills
    Hybrid approach:
    - Score < 3: Use static knowledge map (fast, structured)
    - Score >= 3: Call AI for personalized advanced topics
    """
    
    # Load knowledge map
    try:
        with open('knowledge_map.json', 'r', encoding='utf-8') as f:
            knowledge_map = json.load(f)
    except FileNotFoundError:
        knowledge_map = {}
    
    suggestions = []
    
    # Map evaluations to skills
    eval_by_skill = {}
    for ev in evaluations:
        skill = ev.get('skill', 'Unknown')
        eval_by_skill[skill] = ev
    
    # Generate suggestions for top 5 skills only
    for skill_data in top_skills[:5]:
        skill_name = skill_data['skill']
        
        # Get evaluation for this skill (if exists)
        evaluation = eval_by_skill.get(skill_name)
        
        if not evaluation:
            continue
        
        score = evaluation.get('score', 0)
        level_name = evaluation.get('level_name', 'Unknown')
        
        # Hybrid logic
        if score < 3:
            # Use static knowledge map
            suggestion = get_static_learning_path(skill_name, score, knowledge_map)
            suggestion['method'] = 'structured'
        else:
            # Call AI for personalized suggestions
            suggestion = get_ai_advanced_suggestions(
                skill_name, 
                score, 
                level_name,
                evaluation.get('feedback', ''),
                evaluation.get('improvements', [])
            )
            suggestion['method'] = 'ai_personalized'
        
        suggestion['skill'] = skill_name
        suggestion['current_score'] = score
        suggestion['current_level'] = level_name
        suggestions.append(suggestion)
    
    return suggestions

def get_static_learning_path(skill_name, score, knowledge_map):
    """Get structured learning path from knowledge map for beginners"""
    
    # Map score to level key
    if score <= 1:
        level_key = 'level_0_1'
    else:
        level_key = 'level_2'
    
    # Get from knowledge map
    if skill_name in knowledge_map and level_key in knowledge_map[skill_name]:
        return knowledge_map[skill_name][level_key]
    
    # Fallback if skill not in map
    return {
        'current_level': f'Level {score}/5',
        'topics_to_learn': [
            'Study fundamentals from official documentation',
            'Complete beginner tutorials',
            'Practice with hands-on projects'
        ],
        'resources': [
            f'{skill_name} official documentation',
            'Online courses (Udemy, Coursera)',
            'YouTube tutorials'
        ],
        'practice': [
            'Build 3 small projects',
            'Solve coding challenges'
        ],
        'estimated_time': '7-10 days'
    }

def get_ai_advanced_suggestions(skill_name, score, level_name, feedback, improvements):
    """
    Call Gemini to generate personalized advanced learning suggestions
    Only for users with score >= 3 (already competent)
    """
    
    if not ACTIVE_API or not USE_AI_EVALUATION:
        return {
            'current_level': level_name,
            'topics_to_learn': [
                f'Advanced {skill_name} patterns',
                'Performance optimization',
                'Best practices at scale',
                'Architecture decisions'
            ],
            'resources': [
                f'Advanced {skill_name} documentation',
                'Technical blogs and case studies',
                'Open source projects'
            ],
            'practice': [
                'Contribute to production codebase',
                'Build complex real-world project',
                'Code review others\' work'
            ],
            'estimated_time': 'Ongoing learning'
        }
    
    prompt = f"""User đã đạt {level_name} ({score}/5) trong {skill_name}.

Feedback từ đánh giá:
{feedback}

Điểm cần cải thiện:
{chr(10).join(f"- {imp}" for imp in improvements)}

NHIỆM VỤ: Đề xuất learning path để user lên level cao hơn (Proficient hoặc Expert).

Tập trung vào:
1. Advanced topics phù hợp với level hiện tại
2. Gaps cụ thể từ feedback
3. Real-world applications
4. Deep dive topics (internals, performance, architecture)

Trả về JSON (NO markdown):
{{
    "topics_to_learn": [
        "Topic 1 với explanation ngắn",
        "Topic 2...",
        "..."
    ],
    "resources": [
        "Resource 1 cụ thể (tên book/course/blog)",
        "Resource 2...",
        "..."
    ],
    "practice": [
        "Project idea 1 để practice",
        "Challenge 1...",
        "..."
    ],
    "estimated_time": "X days/weeks"
}}"""
    
    result = call_ai_api(
        prompt=prompt,
        max_tokens=1000,
        temperature=0.7
    )
    
    if result:
        result['current_level'] = level_name
        return result
    
    # Fallback
    return {
        'current_level': level_name,
        'topics_to_learn': [f'Advanced {skill_name} topics'],
        'resources': ['Official docs', 'Tech blogs'],
        'practice': ['Real-world projects'],
        'estimated_time': 'Ongoing'
    }

def generate_learning_roadmap(skill_gaps, job_title, days=7):
    """
    Generate learning roadmap based on skill gaps
    days: 3 for short roadmap, 7 for full roadmap
    """
    priority_skills = skill_gaps[:5]
    
    roadmap = {
        'job_title': job_title,
        'total_days': days,
        'daily_plan': []
    }
    
    if days == 3:
        roadmap['daily_plan'].append({
            'day': 1,
            'title': 'Foundation',
            'focus': f'Củng cố {priority_skills[0]["skill"]}' if priority_skills else 'Review basics',
            'skills': [priority_skills[0]['skill']] if len(priority_skills) > 0 else [],
            'tasks': [
                'Ôn lại concepts cơ bản',
                'Practice exercises',
                'Đọc best practices'
            ]
        })
        
        roadmap['daily_plan'].append({
            'day': 2,
            'title': 'Advanced & Integration',
            'focus': f'Kết hợp skills',
            'skills': [priority_skills[1]['skill']] if len(priority_skills) > 1 else [],
            'tasks': [
                'Học advanced topics',
                'Build mini-project',
                'Code review'
            ]
        })
        
        roadmap['daily_plan'].append({
            'day': 3,
            'title': 'Build Artifact',
            'focus': 'Showcase project',
            'skills': ['All learned skills'],
            'tasks': [
                'Design project architecture',
                'Implement core features',
                'Deploy và document'
            ]
        })
        
        return roadmap
    
    
    roadmap['daily_plan'].append({
        'day': 1,
        'title': 'Foundation & Setup',
        'focus': 'Cài đặt môi trường & học cơ bản',
        'skills': [priority_skills[0]['skill']] if len(priority_skills) > 0 else [],
        'tasks': [
            'Cài đặt công cụ và môi trường phát triển',
            'Học syntax và concepts cơ bản',
            'Làm bài tập nhỏ để làm quen',
            'Đọc documentation chính thức'
        ]
    })
    
    roadmap['daily_plan'].append({
        'day': 2,
        'title': 'Core Concepts',
        'focus': 'Nắm vững khái niệm cốt lõi',
        'skills': [priority_skills[0]['skill']] if len(priority_skills) > 0 else [],
        'tasks': [
            'Học các design patterns phổ biến',
            'Practice hands-on exercises',
            'Build small projects',
            'Review best practices'
        ]
    })
    
    roadmap['daily_plan'].append({
        'day': 3,
        'title': 'Expand Skills',
        'focus': 'Mở rộng kỹ năng bổ trợ',
        'skills': [priority_skills[1]['skill']] if len(priority_skills) > 1 else [],
        'tasks': [
            'Học framework/library phổ biến',
            'Tích hợp với skill ngày 1-2',
            'Build mini-project kết hợp',
            'Code review & refactoring'
        ]
    })
    
    roadmap['daily_plan'].append({
        'day': 4,
        'title': 'Advanced Topics',
        'focus': 'Chủ đề nâng cao',
        'skills': [priority_skills[2]['skill']] if len(priority_skills) > 2 else [],
        'tasks': [
            'Học advanced concepts',
            'Performance optimization',
            'Security best practices',
            'Testing & debugging'
        ]
    })
    
    roadmap['daily_plan'].append({
        'day': 5,
        'title': 'Project Planning',
        'focus': 'Lên kế hoạch dự án chính',
        'skills': ['All learned skills'],
        'tasks': [
            'Brainstorm project ideas',
            'Design architecture',
            'Setup project structure',
            'Create task breakdown'
        ]
    })
    
    roadmap['daily_plan'].append({
        'day': 6,
        'title': 'Build Artifact',
        'focus': 'Xây dựng Proof of Work',
        'skills': ['All learned skills'],
        'tasks': [
            'Implement core features',
            'Apply all learned skills',
            'Write clean, documented code',
            'Add tests'
        ]
    })
    
    roadmap['daily_plan'].append({
        'day': 7,
        'title': 'Polish & Deploy',
        'focus': 'Hoàn thiện và deploy',
        'skills': ['DevOps', 'Documentation'],
        'tasks': [
            'UI/UX improvements',
            'Deploy to production',
            'Write comprehensive README',
            'Prepare for CV showcase'
        ]
    })
    
    return roadmap

def load_artifacts_db():
    """Load artifacts.json once."""
    try:
        with open('artifacts.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("⚠️  artifacts.json not found")
        return {}

def match_artifact_category(job_title: str, top_skills: list) -> str:
    """
    Match job_title + skills to best artifact category.
    Returns category key (e.g. 'frontend', 'backend', ...).
    """
    db = load_artifacts_db()
    job_lower = job_title.lower()
    skill_names = [s['skill'].lower() for s in top_skills]

    best_cat = None
    best_score = 0

    for cat, cat_data in db.items():
        if cat.startswith('_'):
            continue
        keywords = cat_data.get('_match_keywords', [])
        score = 0
        for kw in keywords:
            if kw in job_lower:
                score += 3  # Job title match weighs more
            if any(kw in sk for sk in skill_names):
                score += 1
        if score > best_score:
            best_score = score
            best_cat = cat

    # Default fallback
    if not best_cat:
        best_cat = 'fullstack'

    print(f"🎯 Artifact category matched: {best_cat} (score={best_score}) for '{job_title}'")
    return best_cat


def generate_artifact_ideas(job_title, top_skills):
    """
    Load 3 artifact ideas from artifacts.json matching job_title + skills.
    Falls back to hardcoded list if file not found.
    """
    db = load_artifacts_db()
    if not db:
        return _fallback_artifact_ideas(job_title, top_skills)

    category = match_artifact_category(job_title, top_skills)
    cat_data = db.get(category, db.get('fullstack', {}))
    raw_artifacts = cat_data.get('artifacts', [])

    # Convert to frontend-friendly format
    result = []
    for a in raw_artifacts[:3]:
        result.append({
            'id': a['id'],
            'title': a['title'],
            'tagline': a.get('tagline', ''),
            'difficulty': a.get('difficulty', 'medium'),
            'estimated_days': a.get('estimated_days', 5),
            'description': a.get('description', ''),
            'why_cv_worthy': a.get('why_cv_worthy', ''),
            'tech_stack': a.get('tech_stack', {}),
            'core_features': a.get('core_features', []),
            'bonus_features': a.get('bonus_features', []),
            'ui_ux_requirements': a.get('ui_ux_requirements', {}),
            'cv_ready_criteria': a.get('cv_ready_criteria', {}),
        })
    return result


def _fallback_artifact_ideas(job_title, top_skills):
    """Fallback when artifacts.json is missing."""
    skill_names = [s['skill'] for s in top_skills[:4]]
    return [
        {
            'id': 'fallback_001',
            'title': f'Full-Stack Application for {job_title}',
            'tagline': 'Demonstrate your core skills end-to-end',
            'difficulty': 'medium',
            'estimated_days': 7,
            'description': f'Build a complete application showcasing: {", ".join(skill_names)}',
            'why_cv_worthy': 'Covers full stack depth relevant to your target role.',
            'tech_stack': {'required': skill_names[:3], 'bonus': []},
            'core_features': ['User authentication', 'CRUD operations', 'Responsive UI', 'Deployed live'],
            'bonus_features': ['Tests', 'CI/CD'],
            'ui_ux_requirements': {'must_have': ['Clean layout', 'Mobile responsive', 'Loading states']},
            'cv_ready_criteria': {'readme_must_have': ['Setup guide', 'Screenshots', 'Live demo'], 'minimum_score_to_pass': 65},
        }
    ]

@app.route('/')
def index():
    return render_template('aura_index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze_market():
    """Step 1: Analyze market and generate technical challenge"""
    data = request.get_json()
    job_title = data.get('job_title', '').strip()
    max_results = int(data.get('max_results', 30))
    
    if not job_title:
        return jsonify({'success': False, 'message': 'Vui lòng nhập tên nghề'})
    
    # Scrape jobs
    scrape_results = scrape_itviec_jobs(job_title, max_results)
    
    if not scrape_results['success']:
        return jsonify(scrape_results)
    
    # Analyze skills
    skill_analysis = analyze_skills_from_jobs(scrape_results['jobs'])
    
    # Generate technical challenge based on top skills
    challenge = generate_technical_challenge(job_title, skill_analysis)
    
    # Store in session
    session['job_title'] = job_title
    session['market_skills'] = skill_analysis
    session['challenge'] = challenge
    
    return jsonify({
        'success': True,
        'job_title': job_title,
        'total_jobs': len(scrape_results['jobs']),
        'market_skills': skill_analysis,
        'challenge': challenge
    })

@app.route('/api/submit-challenge', methods=['POST'])
def submit_challenge():
    """Step 2: Evaluate challenge answers and calculate skill gap"""
    data = request.get_json()
    answers = data.get('answers', [])
    
    challenge = session.get('challenge', {})
    market_skills = session.get('market_skills', [])
    job_title = session.get('job_title', '')
    
    if not challenge:
        return jsonify({'success': False, 'message': 'Session expired'})
    
    evaluations = []
    skill_scores = {}  # Map skill to average score
    
    for answer_data in answers:
        question_id = answer_data['question_id']
        answer_text = answer_data['answer']
        
        question = next((q for q in challenge['questions'] if q['id'] == question_id), None)
        if not question:
            continue
        
        evaluation = evaluate_answer_with_ai(
            question['question'],
            answer_text,
            question['evaluation_criteria']
        )
        
        evaluation['question_id'] = question_id
        evaluation['question'] = question['question']
        evaluations.append(evaluation)
        
        for skill in question['skills']:
            if skill not in skill_scores:
                skill_scores[skill] = []
            skill_scores[skill].append(evaluation['score'])
    
    avg_skill_scores = {
        skill: sum(scores) / len(scores)
        for skill, scores in skill_scores.items()
    }
    
    skill_mapping = {
        'Database Design': ['SQL', 'MongoDB', 'PostgreSQL', 'MySQL'],
        'SQL': ['SQL', 'PostgreSQL', 'MySQL'],
        'MongoDB': ['MongoDB', 'NoSQL'],
        'NoSQL': ['MongoDB', 'Redis', 'Elasticsearch'],
        
        'Scaling': ['Docker', 'Kubernetes', 'AWS', 'Azure', 'Google Cloud'],
        'Caching': ['Redis', 'Memcached'],
        'Load Balancing': ['Kubernetes', 'AWS', 'Nginx'],
        'Performance': ['React', 'Vue.js', 'JavaScript', 'Optimization'],
        'Optimization': ['Performance', 'Caching'],
        
        'Security': ['Authentication', 'OAuth', 'JWT'],
        'Authentication': ['Security', 'JWT', 'OAuth'],
        
        'State Management': ['React', 'Vue.js', 'Redux'],
        'React': ['React', 'JavaScript', 'Frontend'],
        'Vue.js': ['Vue.js', 'JavaScript', 'Frontend'],
        'PWA': ['JavaScript', 'Service Workers'],
        'Offline-first': ['PWA', 'Service Workers'],
        
        'Architecture': ['Microservices', 'System Design'],
        'System Design': ['Architecture', 'Microservices'],
        'Microservices': ['Docker', 'Kubernetes'],
        
        'DevOps': ['Docker', 'Kubernetes', 'CI/CD'],
        'Reliability': ['DevOps', 'Monitoring'],
        
        'Machine Learning': ['Python', 'TensorFlow', 'PyTorch'],
        'Data Engineering': ['Python', 'SQL', 'Apache Spark'],
        'ETL': ['Data Engineering', 'Python', 'SQL'],
        'Algorithms': ['Python', 'Java', 'C++'],
        'Statistics': ['Python', 'R', 'Data Analysis'],
        'Experimentation': ['Statistics', 'A/B Testing'],
    }
    
    assessment_results = []
    market_skill_scores = {}  # Track scores for each market skill
    
    for challenge_skill, score in avg_skill_scores.items():
        if challenge_skill in [s['skill'] for s in market_skills]:
            if challenge_skill not in market_skill_scores:
                market_skill_scores[challenge_skill] = []
            market_skill_scores[challenge_skill].append(score)
        
        if challenge_skill in skill_mapping:
            for related_skill in skill_mapping[challenge_skill]:
                if related_skill in [s['skill'] for s in market_skills]:
                    if related_skill not in market_skill_scores:
                        market_skill_scores[related_skill] = []
                    market_skill_scores[related_skill].append(score * 0.8)
    
    for skill_data in market_skills[:10]:
        skill = skill_data['skill']
        
        if skill in market_skill_scores:
            user_score = sum(market_skill_scores[skill]) / len(market_skill_scores[skill])
        else:
            user_score = 0
        
        assessment_results.append({
            'skill': skill,
            'category': skill_data['category'],
            'level': round(user_score)
        })
    
    skill_gaps = calculate_skill_gap(assessment_results, market_skills)
    
    # Check readiness using ACTUAL evaluation scores (from 5 questions answered)
    actual_scores = [e['score'] for e in evaluations if 'score' in e]
    
    if actual_scores:
        avg_score = sum(actual_scores) / len(actual_scores)
        min_score = min(actual_scores)
        
        print(f"\n📊 Readiness Check:")
        print(f"  Questions answered: {len(actual_scores)}")
        print(f"  Individual scores: {actual_scores}")
        print(f"  Average score: {avg_score:.2f}/5")
        print(f"  Minimum score: {min_score}/5")
        
        if avg_score >= 3.5 and min_score >= 2.5:
            readiness = 'ready_for_artifact'
            roadmap = {
                'status': 'ready',
                'message': '🎉 Excellent! Bạn đã ready để làm artifact showcase!',
                'recommendation': 'Không cần học thêm - hãy build project ngay để chứng minh skills!',
                'job_title': job_title,
                'total_days': 0,
                'daily_plan': []
            }
            print(f"  ✅ READY FOR ARTIFACT!")
        elif avg_score >= 3.0:
            readiness = 'short_roadmap'
            roadmap = generate_learning_roadmap(skill_gaps, job_title, days=3)
            roadmap['status'] = 'short_roadmap'
            roadmap['message'] = '👍 Good! Học thêm 3 ngày để strengthen skills'
            print(f"  📚 SHORT ROADMAP (3 days)")
        else:
            readiness = 'full_roadmap'
            roadmap = generate_learning_roadmap(skill_gaps, job_title, days=7)
            roadmap['status'] = 'full_roadmap'
            roadmap['message'] = '📖 Cần học thêm để làm artifact chất lượng'
            print(f"  📖 FULL ROADMAP (7 days)")
    else:
        readiness = 'full_roadmap'
        roadmap = generate_learning_roadmap(skill_gaps, job_title, days=7)
        roadmap['status'] = 'full_roadmap'
        print(f"  ⚠️  No scores - FULL ROADMAP")
    
    artifacts = generate_artifact_ideas(job_title, market_skills)
    
    # Generate learning suggestions for top 5 skills
    learning_suggestions = generate_learning_suggestions(evaluations, market_skills)
    
    session['evaluations'] = evaluations
    session['skill_gaps'] = skill_gaps
    session['roadmap'] = roadmap
    session['artifacts'] = artifacts
    session['learning_suggestions'] = learning_suggestions
    
    return jsonify({
        'success': True,
        'evaluations': evaluations,
        'skill_gaps': skill_gaps,
        'roadmap': roadmap,
        'artifacts': artifacts,
        'learning_suggestions': learning_suggestions
    })

@app.route('/api/get-roadmap', methods=['GET'])
def get_roadmap():
    """Get current roadmap from session"""
    roadmap = session.get('roadmap', {})
    artifacts = session.get('artifacts', [])
    
    return jsonify({
        'success': True,
        'roadmap': roadmap,
        'artifacts': artifacts
    })

# ─────────────────────────────────────────────────────────────
# PHASE 4: ARTIFACT SUBMISSION & CV-READINESS EVALUATION
# ─────────────────────────────────────────────────────────────

def _github_headers():
    """Build GitHub API headers, attach token if available."""
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'Aura-App/1.0',
    }
    token = os.getenv('GITHUB_TOKEN', '').strip()
    if token:
        headers['Authorization'] = f'token {token}'
        print(f"  🔑 GitHub token: attached ({token[:6]}...)")
    else:
        print("  ⚠️  GitHub token: MISSING — unauthenticated (60 req/hr limit)")
    return headers


def _github_error_message(status_code, response_body=''):
    """Return human-friendly error message for GitHub API status codes."""
    if status_code == 401:
        return ('GitHub token không hợp lệ hoặc đã hết hạn. '
                'Vào GitHub → Settings → Developer settings → Personal access tokens → tạo token mới, '
                'rồi set GITHUB_TOKEN=<token> trong file .env')
    if status_code == 403:
        # Check if it's rate limit
        if 'rate limit' in response_body.lower() or 'api rate limit' in response_body.lower():
            return ('GitHub API rate limit exceeded (60 req/giờ với unauthenticated). '
                    'Fix: Tạo GitHub Personal Access Token (free) và set GITHUB_TOKEN=<token> trong .env. '
                    'Với token, limit tăng lên 5000 req/giờ.')
        return ('GitHub API trả về 403 Forbidden. Nguyên nhân có thể: '
                '(1) Rate limit — set GITHUB_TOKEN trong .env để fix, '
                '(2) Repo bị hạn chế truy cập. '
                'Tạo token tại: github.com/settings/tokens')
    if status_code == 404:
        return 'Repo không tìm thấy. Kiểm tra URL hoặc repo có thể là private (cần GITHUB_TOKEN).'
    if status_code == 422:
        return 'GitHub API: Unprocessable Entity — repo có thể rỗng hoặc không có commits.'
    return f'GitHub API lỗi {status_code}. Thử lại sau hoặc kiểm tra GITHUB_TOKEN trong .env.'


def fetch_github_repo(github_url):
    import re as _re
    match = _re.search(r'github\.com/([^/\s?#]+/[^/\s?#]+)', github_url)
    if not match:
        return {'success': False, 'message': 'URL GitHub không hợp lệ. Ví dụ: https://github.com/user/repo'}

    repo_path = match.group(1).rstrip('/')
    repo_path = re.sub(r'\.git$', '', repo_path)  # strip trailing .git if any
    print(f"\n📦 Fetching GitHub repo: {repo_path}")

    headers = _github_headers()

    try:
        # ── 1. Repo metadata ──────────────────────────────────────────
        r = requests.get(f'https://api.github.com/repos/{repo_path}',
                         headers=headers, timeout=15)

        if r.status_code != 200:
            msg = _github_error_message(r.status_code, r.text)
            print(f"  ❌ Repo fetch failed: {r.status_code}")
            # Log rate limit headers if present
            remaining = r.headers.get('X-RateLimit-Remaining', '?')
            reset_ts  = r.headers.get('X-RateLimit-Reset', '')
            if reset_ts:
                import datetime as _dt
                reset_time = _dt.datetime.fromtimestamp(int(reset_ts)).strftime('%H:%M:%S')
                print(f"  Rate limit remaining: {remaining} | Resets at: {reset_time}")
            return {'success': False, 'message': msg}

        repo = r.json()
        print(f"  ✅ Repo found: {repo.get('full_name')} ({'private' if repo.get('private') else 'public'})")

        # ── 2. README ─────────────────────────────────────────────────
        readme_text = ''

        # Try API first (works for both public & private with token)
        r2 = requests.get(
            f'https://api.github.com/repos/{repo_path}/README',
            headers={**headers, 'Accept': 'application/vnd.github.v3.raw'},
            timeout=10
        )
        if r2.status_code == 200:
            readme_text = r2.text[:8000]
            print(f"  ✅ README: {len(readme_text)} chars (via API)")
        else:
            # Fallback: try raw.githubusercontent.com for public repos
            for branch in ('main', 'master'):
                for fname in ('README.md', 'readme.md', 'README.MD'):
                    raw_url = f'https://raw.githubusercontent.com/{repo_path}/{branch}/{fname}'
                    try:
                        r_raw = requests.get(raw_url, timeout=8)
                        if r_raw.status_code == 200:
                            readme_text = r_raw.text[:8000]
                            print(f"  ✅ README: {len(readme_text)} chars (via raw, {branch}/{fname})")
                            break
                    except Exception:
                        pass
                if readme_text:
                    break
            if not readme_text:
                print("  ⚠️  README: not found")

        # ── 3. Languages ──────────────────────────────────────────────
        r3 = requests.get(f'https://api.github.com/repos/{repo_path}/languages',
                          headers=headers, timeout=10)
        languages = list(r3.json().keys()) if r3.status_code == 200 else []
        print(f"  ✅ Languages: {languages}")

        # ── 4. File tree ──────────────────────────────────────────────
        file_tree = []
        default_branch = repo.get('default_branch', 'main')
        r4 = requests.get(
            f'https://api.github.com/repos/{repo_path}/git/trees/{default_branch}',
            headers=headers, timeout=10
        )
        if r4.status_code == 200:
            file_tree = [f['path'] for f in r4.json().get('tree', [])[:40]]
        elif r4.status_code == 409:
            print("  ⚠️  File tree: repo is empty (no commits)")
        else:
            print(f"  ⚠️  File tree: {r4.status_code}")

        return {
            'success': True,
            'repo_path': repo_path,
            'name': repo.get('name', ''),
            'description': repo.get('description', '') or '',
            'stars': repo.get('stargazers_count', 0),
            'forks': repo.get('forks_count', 0),
            'updated_at': repo.get('updated_at', ''),
            'topics': repo.get('topics', []),
            'homepage': repo.get('homepage', '') or '',
            'languages': languages,
            'readme': readme_text,
            'file_tree': file_tree,
            'open_issues': repo.get('open_issues_count', 0),
        }

    except requests.exceptions.Timeout:
        return {'success': False, 'message': 'GitHub API timeout. Kiểm tra kết nối mạng và thử lại.'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'message': 'Không thể kết nối GitHub API. Kiểm tra internet.'}
    except Exception as e:
        return {'success': False, 'message': f'Lỗi fetch GitHub: {str(e)}'}


def ai_generate_followup_questions(repo_info, job_title, description):
    prompt = f"""Bạn là senior engineer đang interview một fresh graduate về project của họ.

Project info:
- Repo: {repo_info.get('repo_path','')}
- Description: {repo_info.get('description','')}
- Languages: {', '.join(repo_info.get('languages', []))}
- Topics: {', '.join(repo_info.get('topics', []))}
- Demo: {repo_info.get('homepage','')}
- Candidate mô tả: {description}
- README excerpt: {repo_info.get('readme','')[:2000]}
- Files: {', '.join(repo_info.get('file_tree', [])[:20])}

Target job: {job_title}

Tạo ĐÚNG 3 câu hỏi follow-up SPECIFIC với project này (không generic) để đánh giá:
1. Technical depth - họ có thực sự hiểu code/architecture không
2. Decision making - tại sao chọn approach/tech này
3. Impact & value - project giải quyết vấn đề gì thực tế

JSON only (no markdown):
{{"questions": [{{"id": 1, "question": "...", "focus": "technical_depth"}}, {{"id": 2, "question": "...", "focus": "decision_making"}}, {{"id": 3, "question": "...", "focus": "impact_and_value"}}]}}"""

    result = call_ai_api(prompt, max_tokens=800, temperature=0.4)
    if result and 'questions' in result:
        return result['questions']
    langs = ', '.join(repo_info.get('languages', ['technology']))
    return [
        {"id": 1, "question": f"Tại sao bạn chọn {langs} cho project này thay vì các alternatives?", "focus": "technical_depth"},
        {"id": 2, "question": "Phần khó nhất khi build project là gì và bạn giải quyết như thế nào?", "focus": "decision_making"},
        {"id": 3, "question": "Project này giải quyết vấn đề gì? Nếu có người dùng thực, họ benefit gì?", "focus": "impact_and_value"},
    ]


def ai_evaluate_artifact(repo_info, description, followup_answers, job_title, market_skills):
    top_skills = ', '.join([s['skill'] for s in market_skills[:8]])
    qa_text = '\n'.join([f"Q{a['id']}: {a['question']}\nA: {a['answer']}" for a in followup_answers])
    file_tree = repo_info.get('file_tree', [])
    has_tests = any('test' in f.lower() for f in file_tree)
    has_ci = any(f in ['.github', '.travis.yml', 'Dockerfile', 'docker-compose.yml'] for f in file_tree)

    prompt = f"""Bạn là senior engineer + HR tech đánh giá project của fresh graduate cho vị trí {job_title}.

=== PROJECT ===
Repo: {repo_info.get('repo_path','')}
Description: {repo_info.get('description','')}
Languages: {', '.join(repo_info.get('languages', []))}
Topics: {', '.join(repo_info.get('topics', []))}
Demo: {repo_info.get('homepage','') or 'Không có'}
README: {'Có (' + str(len(repo_info.get('readme',''))) + ' chars)' if repo_info.get('readme') else 'KHÔNG CÓ'}
Tests: {'✅' if has_tests else '❌'}
CI/Docker: {'✅' if has_ci else '❌'}
Files: {', '.join(file_tree[:25])}

README:
{repo_info.get('readme','')[:2500]}

Candidate mô tả: {description}

Follow-up Q&A:
{qa_text}

=== MARKET CONTEXT ===
Top skills needed: {top_skills}

=== RUBRIC (fresh grad standard, không phải senior) ===
1. README Quality (0-20): Setup guide? Features? Tech stack? Screenshots?
2. Code Structure (0-20): Sensible folder structure? Not spaghetti?
3. Technical Relevance (0-20): Tech stack matches market? Demonstrates in-demand skills?
4. Problem & Impact (0-20): Solves real problem? Can articulate value?
5. Completeness (0-20): Works end-to-end? Deployed/demo? Not just boilerplate?

CV-Ready threshold: >= 65/100

JSON only (no markdown):
{{
  "total_score": <int 0-100>,
  "cv_ready": <true/false>,
  "verdict": "<1-2 câu kết luận>",
  "scores": {{
    "readme_quality": {{"score": <0-20>, "comment": "..."}},
    "code_structure": {{"score": <0-20>, "comment": "..."}},
    "technical_relevance": {{"score": <0-20>, "comment": "..."}},
    "problem_impact": {{"score": <0-20>, "comment": "..."}},
    "completeness": {{"score": <0-20>, "comment": "..."}}
  }},
  "strengths": ["...", "...", "..."],
  "improvements": [
    {{"priority": "high", "action": "việc làm cụ thể", "reason": "tại sao quan trọng"}}
  ],
  "cv_bullet": "<gợi ý viết project này lên CV, format: Built X using Y that Z>"
}}"""

    result = call_ai_api(prompt, max_tokens=2000, temperature=0.3)
    if result:
        print(f"✅ Artifact eval: {result.get('total_score',0)}/100 CV-Ready={result.get('cv_ready')}")
        return result
    return {
        "total_score": 50, "cv_ready": False,
        "verdict": "Không thể đánh giá - vui lòng cấu hình GROQ_API_KEY",
        "scores": {k: {"score": 10, "comment": "Cần AI API"} for k in
                   ["readme_quality","code_structure","technical_relevance","problem_impact","completeness"]},
        "strengths": ["Đã có project để showcase"],
        "improvements": [{"priority": "high", "action": "Cấu hình GROQ_API_KEY", "reason": "Cần AI để evaluate"}],
        "cv_bullet": "Built [project] using [tech] to solve [problem]"
    }


@app.route('/api/fetch-github', methods=['POST'])
def api_fetch_github():
    data = request.get_json()
    github_url = data.get('github_url', '').strip()
    if not github_url:
        return jsonify({'success': False, 'message': 'Vui lòng nhập GitHub URL'})
    result = fetch_github_repo(github_url)
    if not result['success']:
        return jsonify(result)
    session['artifact_repo'] = result
    return jsonify({'success': True, 'repo': {
        'name': result['name'], 'description': result['description'],
        'languages': result['languages'], 'topics': result['topics'],
        'homepage': result['homepage'], 'has_readme': len(result.get('readme','')) > 100,
        'stars': result['stars'],
    }})


@app.route('/api/get-followup-questions', methods=['POST'])
def api_get_followup_questions():
    data = request.get_json()
    description = data.get('description', '').strip()
    repo_info = session.get('artifact_repo', {})
    job_title = session.get('job_title', 'Software Developer')
    if not repo_info:
        return jsonify({'success': False, 'message': 'Chưa fetch GitHub repo'})
    questions = ai_generate_followup_questions(repo_info, job_title, description)
    session['artifact_description'] = description
    session['artifact_questions'] = questions
    return jsonify({'success': True, 'questions': questions})


@app.route('/api/evaluate-artifact', methods=['POST'])
def api_evaluate_artifact():
    data = request.get_json()
    answers = data.get('answers', [])
    repo_info = session.get('artifact_repo', {})
    description = session.get('artifact_description', '')
    job_title = session.get('job_title', 'Software Developer')
    market_skills = session.get('market_skills', [])
    if not repo_info:
        return jsonify({'success': False, 'message': 'Thiếu thông tin repo'})
    result = ai_evaluate_artifact(repo_info, description, answers, job_title, market_skills)
    session['artifact_result'] = result
    return jsonify({'success': True, 'result': result,
                    'repo_name': repo_info.get('name',''),
                    'repo_path': repo_info.get('repo_path','')})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
