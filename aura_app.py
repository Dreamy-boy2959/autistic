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

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Get API key from environment
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
CLAUDE_MODEL = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')  # Free alternative!
USE_AI_EVALUATION = os.getenv('USE_AI_EVALUATION', 'true').lower() == 'true'
AI_PROVIDER = os.getenv('AI_PROVIDER', 'groq')  # 'claude' or 'groq'
USE_AI_SKILL_ANALYSIS = os.getenv('USE_AI_SKILL_ANALYSIS', 'true').lower() == 'true'
# Debug info
print("="*60)
print("🔧 AURA CONFIGURATION:")
print(f"AI_PROVIDER: {AI_PROVIDER}")
print(f"USE_AI_EVALUATION: {USE_AI_EVALUATION}")
print(f"GROQ_API_KEY exists: {bool(GROQ_API_KEY)}")
if GROQ_API_KEY:
    print(f"GROQ_API_KEY (first 20): {GROQ_API_KEY[:20]}...")
else:
    print("⚠️  GROQ_API_KEY is EMPTY - will use fallback!")
print("="*60)
print()

def get_job_detail(job_url, headers):
    """
    Fetch detailed job description from job detail page
    Only return first 2 sections (Mô tả công việc & Yêu cầu ứng viên)
    """
    try:
        time.sleep(2)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            "Referer": "https://www.google.com/"
        }

        response = requests.get(job_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        description_items = soup.find_all('div', class_='job-description__item')
        
        job_descriptions = []
        for item in description_items[:2]:
            heading = item.find(['h3', 'h4', 'strong'])
            heading_text = heading.get_text(strip=True) if heading else ""
            content = item.get_text(separator='\n', strip=True)
            
            if content:
                job_descriptions.append({
                    'heading': heading_text,
                    'content': content
                })
        
        return job_descriptions
        
    except Exception as e:
        print(f"Error fetching job detail: {str(e)}")
        return []

def scrape_topcv_jobs(job_title, max_results=15):
    """
    Scrape job descriptions from TopCV based on job title
    """
    results = []
    
    try:
        search_query = job_title.strip().replace(' ', '-').lower()
        base_url = f"https://www.topcv.vn/tim-viec-lam-{search_query}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        
        response = requests.get(base_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        job_cards = soup.find_all('div', class_='job-item-default')
        
        if not job_cards:
            job_cards = soup.find_all('div', class_=re.compile(r'job.*item'))
        
        for idx, job_card in enumerate(job_cards[:max_results]):
            try:
                job_data = {}
                
                title_elem = job_card.find('h3', class_='title') or job_card.find('a', class_='title')
                if title_elem:
                    job_data['title'] = title_elem.get_text(strip=True)
                    job_link = title_elem.find('a') if title_elem.name != 'a' else title_elem
                    if job_link and job_link.get('href'):
                        job_data['url'] = job_link['href'] if job_link['href'].startswith('http') else f"https://www.topcv.vn{job_link['href']}"
                
                if job_data.get('url'):
                    print(f"Fetching JD & JR for job {idx+1}/{min(len(job_cards), max_results)}...")
                    job_data['description_details'] = get_job_detail(job_data['url'], headers)
                
                if job_data.get('title') and job_data.get('description_details'):
                    results.append(job_data)
                    
            except Exception as e:
                print(f"Error parsing job card {idx}: {str(e)}")
                continue
        
        if not results:
            return {
                'success': False,
                'message': f'Không tìm thấy việc làm cho "{job_title}"',
                'jobs': []
            }
        
        return {
            'success': True,
            'message': f'Tìm thấy {len(results)} công việc',
            'jobs': results
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Lỗi: {str(e)}',
            'jobs': []
        }

def analyze_jd_jr_with_groq(jobs):
    """
    Use Groq AI to analyze JD/JR and extract skills
    More accurate than keyword matching
    """
    
    if not GROQ_API_KEY:
        print("⚠️  GROQ_API_KEY not found, falling back to keyword matching")
        return analyze_skills_from_jobs_keyword(jobs)
    
    print("\n" + "="*60)
    print("🤖 ANALYZING JD/JR WITH GROQ AI")
    print("="*60)
    
    # Prepare JD/JR text for AI
    jd_jr_texts = []
    for idx, job in enumerate(jobs[:15], 1):  # Max 15 jobs
        if job.get('description_details'):
            job_text = '\n'.join([section['content'] for section in job['description_details']])
            jd_jr_texts.append(f"Job {idx}:\n{job_text}\n")
    
    combined_text = '\n---\n'.join(jd_jr_texts)
    
    # Truncate if too long (max ~10K tokens = ~40K chars)
    if len(combined_text) > 40000:
        combined_text = combined_text[:40000] + "\n\n[Truncated...]"
    
    print(f"📊 Analyzing {len(jd_jr_texts)} job descriptions...")
    print(f"📝 Total text length: {len(combined_text)} characters")
    
    # Groq API prompt
    prompt = f"""Bạn là chuyên gia phân tích tuyển dụng IT. Hãy phân tích các Job Description (JD) và Job Requirements (JR) sau đây.

{combined_text}

Nhiệm vụ:
1. Trích xuất TẤT CẢ các kỹ năng kỹ thuật (technical skills) được yêu cầu
2. Đếm số lượng job yêu cầu mỗi skill
3. Phân loại skills vào categories phù hợp

QUAN TRỌNG: Trả lời CHÍNH XÁC theo format JSON này (không thêm markdown, không thêm backticks):
{{
  "skills": [
    {{
      "skill": "Tên skill",
      "job_count": số_lượng_jobs,
      "percentage": phần_trăm,
      "category": "Programming Language/Frontend/Backend/Database/DevOps/Tools/Data-AI/Soft Skills"
    }}
  ]
}}

Lưu ý:
- Chỉ list top 15 skills quan trọng nhất
- Sắp xếp theo job_count giảm dần
- Percentage = (job_count / {len(jobs)}) * 100
- Category phải chính xác (Programming Language, Frontend, Backend, Database, DevOps, Tools, Data/AI, Soft Skills)
- Skill names phải chuẩn: Python, Java, JavaScript, React, Docker, SQL, Git...
"""

    try:
        print("📤 Sending request to Groq API...")
        
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {GROQ_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'llama-3.3-70b-versatile',
                'messages': [
                    {
                        'role': 'system', 
                        'content': 'You are a technical recruiter expert. Always respond with valid JSON only, no markdown.'
                    },
                    {
                        'role': 'user', 
                        'content': prompt
                    }
                ],
                'temperature': 0.3,  # Lower for more consistent output
                'max_tokens': 2048
            },
            timeout=60
        )
        
        print(f"📥 Groq response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content'].strip()
            
            print(f"✅ Groq API SUCCESS!")
            print(f"Response preview: {content[:200]}...")
            
            # Remove markdown code blocks if present
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
            
            # Parse JSON
            analysis = json.loads(content)
            skills = analysis.get('skills', [])
            
            print(f"\n✅ Extracted {len(skills)} skills:")
            for skill in skills[:10]:
                print(f"   • {skill['skill']}: {skill['percentage']}% ({skill['job_count']} jobs) - {skill['category']}")
            
            return skills
            
        else:
            print(f"❌ Groq API error: {response.status_code}")
            print(f"Error details: {response.text[:200]}")
            print("⚠️  Falling back to keyword matching...")
            return analyze_skills_from_jobs_keyword(jobs)
            
    except Exception as e:
        print(f"❌ Groq API error: {str(e)}")
        import traceback
        traceback.print_exc()
        print("⚠️  Falling back to keyword matching...")
        return analyze_skills_from_jobs_keyword(jobs)

def analyze_skills_from_jobs_keyword(jobs):
    """
    Keyword-based skill extraction (fallback method)
    Original implementation - fast and free
    """
    # Comprehensive skill database
    skill_database = {
        # Programming Languages
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
        
        # Frontend
        'React': ['react', 'reactjs', 'react.js'],
        'Vue.js': ['vue', 'vuejs', 'vue.js'],
        'Angular': ['angular', 'angularjs'],
        'HTML/CSS': ['html', 'css', 'html5', 'css3'],
        'Next.js': ['next.js', 'nextjs'],
        'Tailwind CSS': ['tailwind', 'tailwindcss'],
        
        # Backend Frameworks
        'Django': ['django'],
        'Flask': ['flask'],
        'FastAPI': ['fastapi'],
        'Spring Boot': ['spring boot', 'springboot'],
        'Laravel': ['laravel'],
        'Express.js': ['express', 'expressjs', 'express.js'],
        'Node.js': ['node.js', 'nodejs', 'node js'],
        
        # Databases
        'SQL': ['sql', 'mysql', 'postgresql', 'postgres', 'mssql'],
        'MongoDB': ['mongodb', 'mongo'],
        'Redis': ['redis'],
        'Elasticsearch': ['elasticsearch', 'elastic search'],
        'Firebase': ['firebase'],
        
        # Cloud & DevOps
        'AWS': ['aws', 'amazon web services'],
        'Azure': ['azure', 'microsoft azure'],
        'Google Cloud': ['gcp', 'google cloud', 'google cloud platform'],
        'Docker': ['docker', 'containerization'],
        'Kubernetes': ['kubernetes', 'k8s'],
        'CI/CD': ['ci/cd', 'jenkins', 'gitlab ci', 'github actions'],
        'Terraform': ['terraform'],
        
        # Tools & Others
        'Git': ['git', 'github', 'gitlab', 'version control'],
        'REST API': ['rest', 'restful', 'rest api'],
        'GraphQL': ['graphql'],
        'Microservices': ['microservices', 'microservice'],
        'Linux': ['linux', 'ubuntu', 'unix'],
        'Agile/Scrum': ['agile', 'scrum', 'kanban'],
        'Testing': ['unit test', 'testing', 'jest', 'pytest', 'selenium'],
        'OOP': ['oop', 'object-oriented', 'lập trình hướng đối tượng'],
        
        # Data & AI
        'Machine Learning': ['machine learning', 'ml', 'sklearn'],
        'Deep Learning': ['deep learning', 'neural network', 'tensorflow', 'pytorch'],
        'Data Analysis': ['data analysis', 'pandas', 'numpy'],
        'SQL Analytics': ['data analytics', 'bi', 'tableau', 'power bi'],
        
        # Soft Skills
        'English': ['tiếng anh', 'english', 'toeic', 'ielts'],
        'Communication': ['giao tiếp', 'communication', 'presentation'],
        'Teamwork': ['làm việc nhóm', 'teamwork', 'collaboration'],
        'Problem Solving': ['giải quyết vấn đề', 'problem solving', 'analytical'],
    }
    
    # Count skills: each skill counted ONCE per job
    skill_job_counts = {skill: 0 for skill in skill_database.keys()}
    
    for job in jobs:
        if not job.get('description_details'):
            continue
            
        # Combine all text from this job
        job_text = '\n'.join([section['content'] for section in job['description_details']]).lower()
        
        # For each skill, check if it appears in THIS job (count once)
        for skill_name, keywords in skill_database.items():
            skill_found = False
            for keyword in keywords:
                if keyword.lower() in job_text:
                    skill_found = True
                    break
            
            if skill_found:
                skill_job_counts[skill_name] += 1
    
    # Filter out skills with 0 count
    skill_counts = {k: v for k, v in skill_job_counts.items() if v > 0}
    
    # Sort by frequency
    sorted_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)
    
    total_jobs = len(jobs)
    skill_analysis = []
    
    for skill, count in sorted_skills[:15]:  # Top 15 skills
        percentage = (count / total_jobs) * 100
        skill_analysis.append({
            'skill': skill,
            'job_count': count,  # Number of jobs requiring this skill
            'percentage': round(percentage, 1),
            'category': get_skill_category(skill, skill_database)
        })
    
    return skill_analysis

def analyze_skills_from_jobs(jobs):
    """
    Main skill analysis function
    Tries AI analysis first, falls back to keyword matching if needed
    """
    # Check if we should use AI
    use_ai = os.getenv('USE_AI_SKILL_ANALYSIS', 'false').lower() == 'true'
    
    if use_ai and GROQ_API_KEY:
        print("🤖 Using AI-powered skill analysis...")
        return analyze_jd_jr_with_groq(jobs)
    else:
        print("🔤 Using keyword-based skill analysis...")
        return analyze_skills_from_jobs_keyword(jobs)

def get_skill_category(skill_name, skill_database=None):
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
    
    print(f"\n📊 Top tech skills from market:")
    for i, skill in enumerate(tech_skills[:10], 1):
        print(f"  {i}. {skill['skill']}: {skill['percentage']}% ({skill['job_count']} jobs)")
    
    # Match market skills with question bank
    matched_skills = []
    for skill_data in tech_skills:
        skill_name = skill_data['skill']
        if skill_name in question_bank:
            matched_skills.append(skill_data)
            print(f"✅ Matched: {skill_name}")
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
        'scenario': generate_scenario(job_title, matched_skills),
        'questions': selected_questions
    }
    
    return challenge

def generate_scenario(job_title, matched_skills):
    """Generate scenario text based on job title"""
    skill_names = [s['skill'] for s in matched_skills[:5]]
    
    scenario = f"""
🎯 Technical Challenge for: {job_title}

Top skills required in market: {', '.join(skill_names)}

Dưới đây là {len(matched_skills)} câu hỏi technical để đánh giá hiểu biết của bạn về các skills quan trọng nhất.
Mỗi câu hỏi yêu cầu bạn phải:
- Giải thích technical concepts
- Phân tích trade-offs
- Đưa ra quyết định có lý do

Hãy trả lời chi tiết và chứng minh bạn hiểu rõ WHY, không chỉ WHAT.
"""
    return scenario.strip()

def generate_fallback_challenge(job_title, top_skills):
    """Fallback when question bank not available - use generic questions"""
    skill_list = [s['skill'] for s in top_skills[:5]]
    
    challenge = {
        'job_title': job_title,
        'skills_tested': skill_list,
        'scenario': f"""
🎯 Technical Challenge for: {job_title}

Top skills: {', '.join(skill_list)}

Trả lời các câu hỏi sau để chứng minh hiểu biết technical và khả năng phân tích trade-offs.
""",
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
    

def evaluate_answer_with_ai(question, answer, evaluation_criteria, use_ai=True):
    
    if not use_ai:
        return fallback_evaluation(answer, evaluation_criteria)
    
    if AI_PROVIDER == 'groq' and GROQ_API_KEY:
        return evaluate_with_groq(question, answer, evaluation_criteria)
    elif AI_PROVIDER == 'claude' and ANTHROPIC_API_KEY:
        return evaluate_with_claude(question, answer, evaluation_criteria)
    else:
        return fallback_evaluation(answer, evaluation_criteria)
    
    if not use_ai:
        return fallback_evaluation(answer, evaluation_criteria)
    
    if AI_PROVIDER == 'groq' and GROQ_API_KEY:
        return evaluate_with_groq(question, answer, evaluation_criteria)
    elif AI_PROVIDER == 'claude' and ANTHROPIC_API_KEY:
        return evaluate_with_claude(question, answer, evaluation_criteria)
    else:
        # No API key configured, use fallback
        return fallback_evaluation(answer, evaluation_criteria)

def evaluate_with_groq(question, answer, evaluation_criteria):
    """Use Groq API (FREE!) for evaluation"""
    
    print("="*50)
    print("🚀 CALLING GROQ API...")
    print(f"Question: {question[:50]}...")
    print(f"Answer length: {len(answer)} chars")
    print("="*50)
    
    prompt = f"""Bạn là một technical interviewer chuyên nghiệp. Đánh giá câu trả lời của ứng viên.

Câu hỏi: {question}

Tiêu chí đánh giá:
{chr(10).join(f"- {c}" for c in evaluation_criteria)}

Câu trả lời của ứng viên:
{answer}

Hãy đánh giá theo thang điểm 0-5:
- 0: Không hiểu hoặc sai hoàn toàn
- 1: Hiểu cơ bản nhưng thiếu sâu sắc
- 2: Hiểu khá nhưng thiếu trade-offs
- 3: Hiểu tốt, nhắc đến một số trade-offs
- 4: Hiểu rất tốt, phân tích trade-offs chi tiết
- 5: Expert level, comprehensive understanding

QUAN TRỌNG: Trả lời CHÍNH XÁC theo format JSON này (không thêm markdown, không thêm backticks):
{{
    "score": <số từ 0-5>,
    "feedback": "<feedback chi tiết bằng tiếng Việt>",
    "strengths": ["điểm mạnh 1", "điểm mạnh 2"],
    "improvements": ["cần cải thiện 1", "cần cải thiện 2"]
}}"""

    try:
        print("📤 Sending request to Groq...")
        
        response = requests.post(
            'https://api.groq.com/openai/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {GROQ_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'model': 'llama-3.3-70b-versatile',  # Free model
                'messages': [
                    {'role': 'system', 'content': 'You are a helpful technical interviewer. Always respond with valid JSON only.'},
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.7,
                'max_tokens': 1024
            },
            timeout=30
        )
        
        print(f"📥 Groq response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content'].strip()
            
            print(f"✅ Groq API SUCCESS!")
            print(f"Response preview: {content[:100]}...")
            
            # Remove markdown code blocks if present
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]
                content = content.strip()
            
            # Parse JSON
            evaluation = json.loads(content)
            print(f"✅ Score: {evaluation['score']}/5")
            return evaluation
        else:
            print(f"❌ Groq API error: {response.status_code}")
            print(f"Error details: {response.text[:200]}")
            return fallback_evaluation(answer, evaluation_criteria)
            
    except Exception as e:
        print(f"❌ Groq evaluation error: {str(e)}")
        import traceback
        traceback.print_exc()
        return fallback_evaluation(answer, evaluation_criteria)

def evaluate_with_claude(question, answer, evaluation_criteria):
    """Use Claude API (PAID) for evaluation"""
    
    prompt = f"""Bạn là một technical interviewer chuyên nghiệp. Đánh giá câu trả lời của ứng viên.

Câu hỏi: {question}

Tiêu chí đánh giá:
{chr(10).join(f"- {c}" for c in evaluation_criteria)}

Câu trả lời của ứng viên:
{answer}

Hãy đánh giá theo thang điểm 0-5:
- 0: Không hiểu hoặc sai hoàn toàn
- 1: Hiểu cơ bản nhưng thiếu sâu sắc
- 2: Hiểu khá nhưng thiếu trade-offs
- 3: Hiểu tốt, nhắc đến một số trade-offs
- 4: Hiểu rất tốt, phân tích trade-offs chi tiết
- 5: Expert level, comprehensive understanding

Trả lời theo format JSON:
{{
    "score": <0-5>,
    "feedback": "<feedback chi tiết bằng tiếng Việt>",
    "strengths": ["điểm mạnh 1", "điểm mạnh 2"],
    "improvements": ["cần cải thiện 1", "cần cải thiện 2"]
}}"""

    try:
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': CLAUDE_MODEL,
                'max_tokens': 1024,
                'messages': [
                    {'role': 'user', 'content': prompt}
                ]
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result['content'][0]['text']
            
            # Parse JSON response
            evaluation = json.loads(content)
            return evaluation
        else:
            return fallback_evaluation(answer, evaluation_criteria)
            
    except Exception as e:
        print(f"Claude evaluation error: {str(e)}")
        return fallback_evaluation(answer, evaluation_criteria)

def fallback_evaluation(answer, evaluation_criteria):
    """Fallback evaluation when API is not available"""
    score = 0
    answer_lower = answer.lower()
    
    # Check for key concepts
    for criterion in evaluation_criteria:
        criterion_lower = criterion.lower()
        # Check if key concepts are mentioned
        if any(word in answer_lower for word in criterion_lower.split() if len(word) > 4):
            score += 1
    
    score = min(5, max(0, score))
    
    return {
        'score': score,
        'feedback': f'Đánh giá tự động dựa trên keywords (API key chưa được cấu hình). Câu trả lời đề cập đến {score}/{len(evaluation_criteria)} tiêu chí.',
        'strengths': ['Câu trả lời có đề cập đến một số khái niệm liên quan'] if score > 0 else [],
        'improvements': ['Nên phân tích sâu hơn về trade-offs', 'Thêm ví dụ cụ thể', 'Cấu hình API key trong .env để có đánh giá chi tiết hơn']
    }

def calculate_skill_gap(assessment_results, market_skills):
    """
    Calculate skill gap between user's current level and market requirements
    """
    skill_gaps = []
    
    for result in assessment_results:
        skill_name = result['skill']
        user_level = result['level']
        
        # Find market requirement
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
    
    # Sort by gap (largest first)
    skill_gaps.sort(key=lambda x: x['gap'], reverse=True)
    
    return skill_gaps

def generate_learning_roadmap(skill_gaps, job_title):
    """
    Generate a 7-day learning roadmap based on skill gaps
    """
    # Take top 5 priority skills
    priority_skills = skill_gaps[:5]
    
    roadmap = {
        'job_title': job_title,
        'total_days': 7,
        'daily_plan': []
    }
    
    # Day 1-2: Foundation
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
    
    # Day 3-4: Secondary Skills
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
    
    # Day 5-6: Integration & Project
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
    
    # Day 7: Polish & Deploy
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

def generate_artifact_ideas(job_title, top_skills):
    """
    Generate project ideas for proof of work
    """
    artifacts = []
    
    # Extract skill names
    skill_names = [s['skill'] for s in top_skills[:5]]
    
    # Generic project templates based on job title
    if 'python' in job_title.lower() or 'Python' in skill_names:
        artifacts.append({
            'title': 'REST API với FastAPI/Flask',
            'description': 'Xây dựng RESTful API hoàn chỉnh với authentication, CRUD operations, và database integration',
            'tech_stack': ['Python', 'FastAPI/Flask', 'SQL', 'Docker'],
            'features': [
                'User authentication (JWT)',
                'CRUD endpoints',
                'Database integration',
                'API documentation (Swagger)',
                'Unit tests',
                'Docker containerization'
            ],
            'showcase': 'Deploy lên Heroku/Railway và thêm link vào CV'
        })
    
    if any(skill in skill_names for skill in ['React', 'Vue.js', 'JavaScript']):
        artifacts.append({
            'title': 'Interactive Dashboard',
            'description': 'Dashboard tương tác với charts, real-time data, và responsive design',
            'tech_stack': ['React/Vue', 'Chart.js', 'REST API', 'Tailwind CSS'],
            'features': [
                'Data visualization với charts',
                'Real-time updates',
                'Responsive design',
                'State management',
                'API integration',
                'Dark mode'
            ],
            'showcase': 'Deploy lên Vercel/Netlify và thêm demo link'
        })
    
    if 'Java' in skill_names or 'Spring' in skill_names:
        artifacts.append({
            'title': 'Spring Boot Microservice',
            'description': 'Microservice với Spring Boot, có API Gateway và Service Discovery',
            'tech_stack': ['Java', 'Spring Boot', 'MySQL', 'Docker'],
            'features': [
                'Microservices architecture',
                'API Gateway',
                'Service discovery',
                'Database per service',
                'Inter-service communication',
                'Monitoring & logging'
            ],
            'showcase': 'GitHub repo với detailed README'
        })
    
    # Always include a full-stack project
    artifacts.append({
        'title': 'Full-Stack Application',
        'description': f'Ứng dụng full-stack phù hợp với vị trí {job_title}',
        'tech_stack': skill_names[:4],
        'features': [
            'Frontend UI/UX',
            'Backend API',
            'Database design',
            'Authentication & Authorization',
            'Deployment pipeline',
            'Testing coverage'
        ],
        'showcase': 'Live demo + GitHub repo + Blog post về technical decisions'
    })
    
    return artifacts[:3]  # Return top 3 ideas

@app.route('/')
def index():
    return render_template('aura_index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze_market():
    """Step 1: Analyze market and generate technical challenge"""
    data = request.get_json()
    job_title = data.get('job_title', '').strip()
    max_results = int(data.get('max_results', 15))
    
    if not job_title:
        return jsonify({'success': False, 'message': 'Vui lòng nhập tên nghề'})
    
    # Scrape jobs
    scrape_results = scrape_topcv_jobs(job_title, max_results)
    
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
    
    # Evaluate each answer
    evaluations = []
    skill_scores = {}  # Map skill to average score
    
    for answer_data in answers:
        question_id = answer_data['question_id']
        answer_text = answer_data['answer']
        
        # Find corresponding question
        question = next((q for q in challenge['questions'] if q['id'] == question_id), None)
        if not question:
            continue
        
        # Evaluate with AI
        evaluation = evaluate_answer_with_ai(
            question['question'],
            answer_text,
            question['evaluation_criteria']
        )
        
        evaluation['question_id'] = question_id
        evaluation['question'] = question['question']
        evaluations.append(evaluation)
        
        # Map scores to skills
        for skill in question['skills']:
            if skill not in skill_scores:
                skill_scores[skill] = []
            skill_scores[skill].append(evaluation['score'])
    
    # Calculate average score per skill
    avg_skill_scores = {
        skill: sum(scores) / len(scores)
        for skill, scores in skill_scores.items()
    }
    
    # Smart mapping: Map challenge skills to market skills
    # Challenge might test 'Database Design' but market tracks 'SQL', 'MongoDB'
    skill_mapping = {
        # Database related
        'Database Design': ['SQL', 'MongoDB', 'PostgreSQL', 'MySQL'],
        'SQL': ['SQL', 'PostgreSQL', 'MySQL'],
        'MongoDB': ['MongoDB', 'NoSQL'],
        'NoSQL': ['MongoDB', 'Redis', 'Elasticsearch'],
        
        # Scaling/Performance
        'Scaling': ['Docker', 'Kubernetes', 'AWS', 'Azure', 'Google Cloud'],
        'Caching': ['Redis', 'Memcached'],
        'Load Balancing': ['Kubernetes', 'AWS', 'Nginx'],
        'Performance': ['React', 'Vue.js', 'JavaScript', 'Optimization'],
        'Optimization': ['Performance', 'Caching'],
        
        # Security/Auth
        'Security': ['Authentication', 'OAuth', 'JWT'],
        'Authentication': ['Security', 'JWT', 'OAuth'],
        
        # Frontend
        'State Management': ['React', 'Vue.js', 'Redux'],
        'React': ['React', 'JavaScript', 'Frontend'],
        'Vue.js': ['Vue.js', 'JavaScript', 'Frontend'],
        'PWA': ['JavaScript', 'Service Workers'],
        'Offline-first': ['PWA', 'Service Workers'],
        
        # Backend
        'Architecture': ['Microservices', 'System Design'],
        'System Design': ['Architecture', 'Microservices'],
        'Microservices': ['Docker', 'Kubernetes'],
        
        # DevOps
        'DevOps': ['Docker', 'Kubernetes', 'CI/CD'],
        'Reliability': ['DevOps', 'Monitoring'],
        
        # Data
        'Machine Learning': ['Python', 'TensorFlow', 'PyTorch'],
        'Data Engineering': ['Python', 'SQL', 'Apache Spark'],
        'ETL': ['Data Engineering', 'Python', 'SQL'],
        'Algorithms': ['Python', 'Java', 'C++'],
        'Statistics': ['Python', 'R', 'Data Analysis'],
        'Experimentation': ['Statistics', 'A/B Testing'],
    }
    
    # Create assessment results with smart mapping
    assessment_results = []
    market_skill_scores = {}  # Track scores for each market skill
    
    # First, map challenge scores to market skills
    for challenge_skill, score in avg_skill_scores.items():
        # Direct match
        if challenge_skill in [s['skill'] for s in market_skills]:
            if challenge_skill not in market_skill_scores:
                market_skill_scores[challenge_skill] = []
            market_skill_scores[challenge_skill].append(score)
        
        # Indirect match via mapping
        if challenge_skill in skill_mapping:
            for related_skill in skill_mapping[challenge_skill]:
                if related_skill in [s['skill'] for s in market_skills]:
                    if related_skill not in market_skill_scores:
                        market_skill_scores[related_skill] = []
                    # Use 80% of score for indirect match
                    market_skill_scores[related_skill].append(score * 0.8)
    
    # Now create assessment results for top 10 market skills
    for skill_data in market_skills[:10]:
        skill = skill_data['skill']
        
        # Get average score for this skill (or 0 if not tested)
        if skill in market_skill_scores:
            user_score = sum(market_skill_scores[skill]) / len(market_skill_scores[skill])
        else:
            user_score = 0
        
        assessment_results.append({
            'skill': skill,
            'category': skill_data['category'],
            'level': round(user_score)
        })
    
    # Calculate skill gap
    skill_gaps = calculate_skill_gap(assessment_results, market_skills)
    
    # Generate roadmap
    roadmap = generate_learning_roadmap(skill_gaps, job_title)
    
    # Generate artifact ideas
    artifacts = generate_artifact_ideas(job_title, market_skills)
    
    # Store in session
    session['evaluations'] = evaluations
    session['skill_gaps'] = skill_gaps
    session['roadmap'] = roadmap
    session['artifacts'] = artifacts
    
    return jsonify({
        'success': True,
        'evaluations': evaluations,
        'skill_gaps': skill_gaps,
        'roadmap': roadmap,
        'artifacts': artifacts
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
