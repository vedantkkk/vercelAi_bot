from flask import Flask, render_template, request, jsonify, send_file
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import os
import PyPDF2
from datetime import datetime
import secrets
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
import io
import time
import re
import traceback
import html
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
# Set writable directory for serverless (Vercel has read-only filesystem except for /tmp)
if os.environ.get('VERCEL') or os.name != 'nt':
    app.config['UPLOAD_FOLDER'] = '/tmp'
else:
    app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Constants
TOTAL_QUESTIONS = 8
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
}

class InterviewSession:
    def __init__(self, api_key, resume_text, session_id, analyze=True):
        print(f"Initializing interview session: {session_id}")
        self.api_key = api_key
        # Create a session-isolated API client to prevent concurrent session key pollution
        from google.ai import generativelanguage as glm
        client = glm.GenerativeServiceClient(client_options={'api_key': api_key})
        
        # Dynamic model probing fallback mechanism
        self.model = None
        models_to_try = [
            'gemini-1.5-flash-latest',
            'gemini-1.5-flash',
            'gemini-2.5-flash-lite',
            'gemini-2.5-flash',
            'gemini-2.0-flash',
            'gemini-pro'
        ]
        
        last_error = None
        for model_name in models_to_try:
            try:
                print(f"Testing model configuration: {model_name}...")
                test_model = genai.GenerativeModel(model_name)
                # Assign the isolated client
                test_model._client = client
                # Fire a tiny test request to verify both model exists (not 404) and has quota (not 429)
                test_model.generate_content("test", generation_config=genai.types.GenerationConfig(max_output_tokens=5))
                self.model = test_model
                print(f"--> Success! Binding model: {model_name}")
                break
            except Exception as e:
                print(f"--> Failed for {model_name}: {e}")
                last_error = e
                
        if not self.model:
            print(f"CRITICAL: All models failed initialization. Last error details: {last_error}")
            raise last_error
            
        self.resume_text = resume_text
        self.session_id = session_id
        self.conversation_history = []
        self.current_question = 0
        self.is_speaking = False
        self.resume_analysis = None
        self.asked_categories = set()
        self.asked_specific_items = set()
        
        # Coding challenge state
        self.coding_asked = False
        self.knows_coding = None  # True/False/None
        self.coding_language = None
        self.coding_challenge_given = False
        self.coding_question = None
        self.coding_submission = None
        self.coding_template = ""  # Initialize empty template
        
        self.scores = {
            'technical': 0,
            'communication': 0,
            'problem_solving': 0,
            'confidence': 0,
            'coding': 0
        }
        self.proctoring_violations = []
        self.is_disqualified = False
        
        if analyze:
            print("Starting resume analysis...")
            self._analyze_resume()
            print(f"Resume analysis complete. Categories found: {list(self.resume_analysis.keys()) if self.resume_analysis else 'None'}")
        
    @classmethod
    def from_dict(cls, data):
        """Restore InterviewSession from a dictionary (state)"""
        session = cls(data['api_key'], data['resume_text'], data['session_id'], analyze=False)
        session.conversation_history = data.get('conversation_history', [])
        session.current_question = data.get('current_question', 0)
        session.is_speaking = data.get('is_speaking', False)
        session.resume_analysis = data.get('resume_analysis')
        session.asked_categories = set(data.get('asked_categories', []))
        session.asked_specific_items = set(data.get('asked_specific_items', []))
        session.coding_asked = data.get('coding_asked', False)
        session.knows_coding = data.get('knows_coding')
        session.coding_language = data.get('coding_language')
        session.coding_challenge_given = data.get('coding_challenge_given', False)
        session.coding_question = data.get('coding_question')
        session.coding_submission = data.get('coding_submission')
        session.coding_template = data.get('coding_template', '')
        session.scores = data.get('scores', {
            'technical': 0,
            'communication': 0,
            'problem_solving': 0,
            'confidence': 0,
            'coding': 0
        })
        session.proctoring_violations = data.get('proctoring_violations', [])
        session.is_disqualified = data.get('is_disqualified', False)
        return session

    def to_dict(self):
        """Serialize InterviewSession to a dictionary (state)"""
        return {
            'api_key': self.api_key,
            'resume_text': self.resume_text,
            'session_id': self.session_id,
            'conversation_history': self.conversation_history,
            'current_question': self.current_question,
            'is_speaking': self.is_speaking,
            'resume_analysis': self.resume_analysis,
            'asked_categories': list(self.asked_categories),
            'asked_specific_items': list(self.asked_specific_items),
            'coding_asked': self.coding_asked,
            'knows_coding': self.knows_coding,
            'coding_language': self.coding_language,
            'coding_challenge_given': self.coding_challenge_given,
            'coding_question': self.coding_question,
            'coding_submission': self.coding_submission,
            'coding_template': self.coding_template,
            'scores': self.scores,
            'proctoring_violations': self.proctoring_violations,
            'is_disqualified': self.is_disqualified
        }

    def _analyze_resume(self):
        """Deep analysis of resume to extract all key areas"""
        prompt = f"""Analyze this resume and extract ALL key areas for interview questions:

{self.resume_text}

Provide a structured analysis:
1. TECHNICAL_SKILLS: List all technologies, programming languages, frameworks, tools
2. PROJECTS: List each project with its tech stack and key challenges
3. INTERNSHIPS: List each internship with role, company, and responsibilities
4. EDUCATION: Degree, major, relevant coursework
5. CERTIFICATIONS: Any certifications mentioned
6. CLUBS_ACTIVITIES: Clubs, leadership roles, extracurriculars
7. VOLUNTEERING: Any volunteer work or community service
8. ACHIEVEMENTS: Awards, competitions, recognitions
9. SOFT_SKILLS: Any soft skills mentioned or implied

Format as:
CATEGORY: item1 | item2 | item3"""

        analysis = self.generate_content(prompt)
        if analysis:
            self.resume_analysis = self._parse_resume_analysis(analysis)
            print(f"Parsed categories: {self.resume_analysis}")
        else:
            print("WARNING: Resume analysis failed!")
    
    def _parse_resume_analysis(self, analysis_text):
        """Parse the structured resume analysis"""
        categories = {}
        lines = analysis_text.split('\n')
        
        for line in lines:
            if ':' in line:
                parts = line.split(':', 1)
                category = parts[0].strip().upper()
                items = [item.strip() for item in parts[1].split('|') if item.strip()]
                if items:
                    categories[category] = items
        
        return categories
    
    def should_ask_coding_question(self):
        """Check if it's time to ask about coding (around question 3-4)"""
        return not self.coding_asked and self.current_question in [2, 3]
    
    def generate_coding_challenge(self):
        """Generate a coding challenge based on user's language"""
        if not self.coding_language:
            self.coding_language = "Python"
        
        topics = ['arrays', 'strings', 'linked lists', 'hash maps', 'two pointers']
        
        prompt = f"""Generate a simple coding problem suitable for an interview in {self.coding_language}.

Topic: {topics[self.current_question % len(topics)]}
Difficulty: Easy

Requirements:
1. Problem should be practical and commonly asked (like LeetCode easy problems)
2. Include clear input/output examples
3. Should be solvable in 5-10 minutes
4. Provide a function template that user needs to complete

Format your response EXACTLY as:
PROBLEM: [Clear problem statement in 2-3 sentences]

EXAMPLE 1:
Input: [example input]
Output: [expected output]
Explanation: [brief explanation]

EXAMPLE 2:
Input: [example input]
Output: [expected output]

CONSTRAINTS:
- [constraint 1]
- [constraint 2]

FUNCTION_TEMPLATE:
[Provide ONLY the function signature with parameter names that user needs to complete]

For Python: def functionName(param1, param2):
For Java: public return_type functionName(type param1, type param2) {{
For JavaScript: function functionName(param1, param2) {{
For C++: return_type functionName(type param1, type param2) {{

Keep it concise and LeetCode-style."""
        
        challenge = self.generate_content(prompt)
        print(f"=== FULL CHALLENGE TEXT ===\n{challenge}\n=== END ===")
        if challenge:
            self.coding_question = challenge
            
            # Extract function template
            template_match = re.search(r'FUNCTION_TEMPLATE:\s*\n(.+?)(?:\n\n|\Z)', challenge, re.DOTALL)
            if template_match:
                self.coding_template = template_match.group(1).strip()
            else:
                # Fallback templates
                templates = {
                    'Python': 'def solution(nums):\n    # Write your code here\n    pass',
                    'Java': 'public class Solution {\n    public int[] solution(int[] nums) {\n        // Write your code here\n        \n    }\n}',
                    'JavaScript': 'function solution(nums) {\n    // Write your code here\n    \n}',
                    'C++': 'class Solution {\npublic:\n    vector<int> solution(vector<int>& nums) {\n        // Write your code here\n        \n    }\n};'
                }
                self.coding_template = templates.get(self.coding_language, templates['Python'])
            
            return challenge
        return None
    
    def evaluate_code_submission(self, code):
        """Evaluate submitted code"""
        if not code or len(code.strip()) < 10:
            return {
                'score': 0,
                'feedback': 'Code submission too short or empty.'
            }
        
        prompt = f"""Evaluate this coding solution:

PROBLEM:
{self.coding_question}

SUBMITTED CODE:
{code}

Provide evaluation in this format:
CORRECTNESS: [0-10 score]
EXPLANATION: [Brief explanation]
CODE_QUALITY: [0-10 score]
EFFICIENCY: [0-10 score]
ISSUES: [Any bugs or improvements]
POSITIVES: [What they did well]

Be constructive and specific."""
        
        evaluation = self.generate_content(prompt)
        
        if evaluation:
            try:
                correctness_match = re.search(r'CORRECTNESS:\s*(\d+)', evaluation)
                code_quality_match = re.search(r'CODE_QUALITY:\s*(\d+)', evaluation)
                efficiency_match = re.search(r'EFFICIENCY:\s*(\d+)', evaluation)
                
                correctness = int(correctness_match.group(1)) if correctness_match else 5
                quality = int(code_quality_match.group(1)) if code_quality_match else 5
                efficiency = int(efficiency_match.group(1)) if efficiency_match else 5
                
                avg_score = round((correctness + quality + efficiency) / 3, 1)
                self.scores['coding'] = avg_score
                
                return {
                    'score': avg_score,
                    'feedback': evaluation,
                    'correctness': correctness,
                    'quality': quality,
                    'efficiency': efficiency
                }
            except Exception as e:
                print(f"Error parsing evaluation: {e}")
                return {
                    'score': 5,
                    'feedback': evaluation or "Unable to evaluate properly."
                }
        
        return {
            'score': 0,
            'feedback': 'Failed to evaluate code submission.'
        }
        
    def generate_content(self, prompt, stream=False):
        """Generate AI content with streaming support"""
        try:
            print(f"Calling Gemini API... Prompt length: {len(prompt)}")
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.7,
                    max_output_tokens=800,
                ),
                safety_settings=SAFETY_SETTINGS,
                stream=stream
            )
            
            if stream:
                return response
            
            if hasattr(response, 'text'):
                print(f"API Response received: {response.text[:100]}...")
                return response.text
            
            print("ERROR: Response has no text attribute")
            return None
            
        except Exception as e:
            print(f"!!! ERROR generating content: {e}")
            traceback.print_exc()
            raise e
    
    def get_introduction(self):
        """Generate personalized introduction"""
        resume_preview = self.resume_text[:500]
        
        prompt = f"""You are a friendly AI interviewer. The candidate's resume shows:

{resume_preview}

Give a warm, professional greeting (2-3 sentences). Mention specific impressive items from their resume and ask them to briefly introduce themselves. Keep it conversational and encouraging."""
        
        print("Generating introduction...")
        return self.generate_content(prompt)
    
    def get_question(self, user_response=None):
        """Generate next interview question"""
        self.current_question += 1
        print(f"Generating question {self.current_question}/{TOTAL_QUESTIONS}")
        
        # Check if we should ask about coding
        if self.should_ask_coding_question():
            print("TIME TO ASK ABOUT CODING!")
            self.coding_asked = True
            return "Do you know any programming languages? If yes, which one are you most comfortable with?"
        
        # If they said yes to coding and we haven't given challenge yet
        if self.knows_coding and not self.coding_challenge_given and self.coding_language:
            print("TIME FOR CODING CHALLENGE!")
            self.coding_challenge_given = True
            return None  # Signal to emit coding challenge
        
        print(f"Asked categories: {self.asked_categories}")
        print(f"Asked items: {self.asked_specific_items}")
        
        question_strategies = [
            ("TECHNICAL_SKILLS", "Ask about ONE specific technology they listed."),
            ("PROJECTS", "Ask about ONE specific project - their biggest challenge and contribution."),
            ("INTERNSHIPS", "Ask about ONE internship - their key responsibility and impact."),
            ("CLUBS_ACTIVITIES", "Ask about ONE club/activity - their role and impact."),
            ("VOLUNTEERING", "Ask about ONE volunteer experience."),
            ("PROBLEM_SOLVING", "Present a practical scenario related to their background."),
            ("BEHAVIORAL", "Ask about teamwork, handling failure, or conflict resolution."),
            ("CAREER_GOALS", "Ask about their career aspirations.")
        ]
        
        if self.current_question <= len(question_strategies):
            strategy_category, strategy_prompt = question_strategies[self.current_question - 1]
        else:
            strategy_category = "FOLLOW_UP"
            strategy_prompt = "Ask a thoughtful follow-up."
        
        available_items = []
        if self.resume_analysis and strategy_category in self.resume_analysis:
            all_items = self.resume_analysis[strategy_category]
            available_items = [item for item in all_items if item not in self.asked_specific_items]
            
            if available_items:
                self.asked_categories.add(strategy_category)
        
        items_context = ""
        if available_items:
            selected_item = available_items[0]
            self.asked_specific_items.add(selected_item)
            items_context = f"\nSpecific item: {selected_item}"
        
        history_context = ""
        if user_response:
            history_context = f"\nPrevious response: {user_response[:200]}"
        
        asked_summary = ""
        if self.asked_categories:
            asked_summary = f"\nALREADY ASKED: {', '.join(self.asked_categories)}"
        
        prompt = f"""You are conducting an interview. DO NOT repeat topics.

Resume:
{self.resume_text[:700]}
{items_context}
{history_context}
{asked_summary}

Strategy: {strategy_prompt}

Generate ONE NEW question (1-2 sentences, conversational):"""
        
        return self.generate_content(prompt)
    
    def analyze_response(self, response_text):
        """Analyze candidate's response for scoring"""
        prompt = f"""Analyze this response:

"{response_text[:300]}"

Rate 1-10:
Technical_Knowledge: [score]
Communication_Clarity: [score]
Problem_Solving: [score]
Confidence: [score]"""
        
        try:
            analysis = self.generate_content(prompt)
            if analysis:
                scores = re.findall(r'(\d+)', analysis)
                if len(scores) >= 4:
                    self.scores['technical'] += int(scores[0])
                    self.scores['communication'] += int(scores[1])
                    self.scores['problem_solving'] += int(scores[2])
                    self.scores['confidence'] += int(scores[3])
        except Exception as e:
            print(f"Error in analyze_response scoring: {e}")

    def log_violation(self, violation_type, details):
        """Log proctoring violation"""
        print(f"VIOLATION: {violation_type} - {details}")
        self.proctoring_violations.append({
            'type': violation_type,
            'details': details,
            'timestamp': datetime.now().isoformat()
        })
    
    def generate_feedback(self):
        """Generate comprehensive feedback"""
        print("Generating feedback...")
        
        responses = [h['content'] for h in self.conversation_history if h['role'] == 'Candidate']
        responses_text = "\n\n".join([f"Q{i+1}: {r[:200]}" for i, r in enumerate(responses)])
        
        num_responses = max(len(responses), 1)
        avg_scores = {
            'technical': round(self.scores['technical'] / num_responses, 1),
            'communication': round(self.scores['communication'] / num_responses, 1),
            'problem_solving': round(self.scores['problem_solving'] / num_responses, 1),
            'confidence': round(self.scores['confidence'] / num_responses, 1),
            'coding': self.scores['coding']
        }
        
        if self.coding_challenge_given:
            overall_score = round(sum(avg_scores.values()) / len(avg_scores), 1)
        else:
            overall_score = round(sum(v for k, v in avg_scores.items() if k != 'coding') / 4, 1)
        
        violations_text = ""
        if self.proctoring_violations:
            violations_text = f"\n\nPROCTORING VIOLATIONS: {len(self.proctoring_violations)} detected"
        
        coding_section = ""
        if self.coding_challenge_given and self.coding_submission:
            coding_section = f"\n\nCODING RESULT:\nScore: {avg_scores['coding']}/10\n{self.coding_submission.get('feedback', 'N/A')}"
        
        coding_assessment = ""
        if self.coding_challenge_given:
            coding_assessment = f"CODING ASSESSMENT ({avg_scores['coding']}/10):\n[2-3 sentences about coding ability]\n\n"
        
        prompt = f"""Interview summary for {TOTAL_QUESTIONS} questions.

Resume: {self.resume_text[:500]}
Responses: {responses_text}
{coding_section}
{violations_text}

Format:

OVERALL SCORE: {overall_score}/10

STRENGTHS:
- [Specific strength]
- [Another strength]
- [Third strength]

AREAS FOR IMPROVEMENT:
- [Specific area]
- [Another area]
- [Third area]

TECHNICAL ASSESSMENT ({avg_scores['technical']}/10):
[2-3 sentences]

COMMUNICATION SKILLS ({avg_scores['communication']}/10):
[2-3 sentences]

PROBLEM-SOLVING ({avg_scores['problem_solving']}/10):
[2-3 sentences]

CONFIDENCE ({avg_scores['confidence']}/10):
[2-3 sentences]

{coding_assessment}RECOMMENDATION:
[Strongly Recommend/Recommend/Consider/Not Ready - with reasoning]

KEY TAKEAWAYS:
- [Tip 1]
- [Tip 2]
- [Tip 3]"""
        
        return self.generate_content(prompt)

@app.route('/')
def index():
    has_default_key = bool(os.environ.get('GEMINI_API_KEY'))
    return render_template('index.html', has_default_key=has_default_key)

@app.route('/upload_resume', methods=['POST'])
def upload_resume():
    """Handle resume upload, construct initial session state"""
    try:
        print("\n=== UPLOAD RESUME ===")
        
        if 'resume' not in request.files:
            return jsonify({'error': 'No resume file'}), 400
        
        file = request.files['resume']
        api_key = request.form.get('api_key') or os.environ.get('GEMINI_API_KEY')
        
        if api_key:
            api_key = api_key.strip()
            
        if not api_key or len(api_key) < 20:
            return jsonify({'error': 'Valid API key required. Make sure it is set in the environment or input field.'}), 400
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.lower().endswith(('.pdf', '.txt')):
            return jsonify({'error': 'Only PDF/TXT supported'}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{secrets.token_hex(8)}_{filename}")
        file.save(filepath)
        
        resume_text = ""
        try:
            if filename.lower().endswith('.pdf'):
                with open(filepath, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    for page in pdf_reader.pages:
                        resume_text += page.extract_text() + "\n"
            else:
                with open(filepath, 'r', encoding='utf-8') as f:
                    resume_text = f.read()
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
        
        if len(resume_text.strip()) < 50:
            return jsonify({'error': 'Resume too short'}), 400
        
        session_id = secrets.token_hex(16)
        interview = InterviewSession(api_key, resume_text, session_id, analyze=True)
        
        return jsonify({
            'success': True,
            'session_state': interview.to_dict(),
            'message': 'Resume uploaded! Starting interview...'
        })
        
    except Exception as e:
        print(f"!!! ERROR: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/join_interview', methods=['POST'])
def join_interview():
    """Start interview, returns the introduction"""
    try:
        data = request.json or {}
        state = data.get('session_state')
        if not state:
            return jsonify({'error': 'Missing session_state'}), 400
            
        interview = InterviewSession.from_dict(state)
        intro = interview.get_introduction()
        
        if intro:
            interview.conversation_history.append({
                'role': 'Interviewer',
                'content': intro,
                'timestamp': datetime.now().isoformat()
            })
            return jsonify({
                'success': True,
                'session_state': interview.to_dict(),
                'intro': intro,
                'total_questions': TOTAL_QUESTIONS
            })
        else:
            return jsonify({'error': 'Failed to generate introduction'}), 500
            
    except Exception as e:
        err_msg = str(e)
        print(f"!!! Error in join_interview: {err_msg}")
        traceback.print_exc()
        if "quota" in err_msg.lower() or "429" in err_msg.lower() or "limit" in err_msg.lower():
            return jsonify({'error': 'Google Gemini API Quota Limit Exceeded (429). Please verify your API key limits.'}), 429
        return jsonify({'error': f'API Error during startup: {err_msg}'}), 500

@app.route('/api/submit_response', methods=['POST'])
def submit_response():
    """Process user response and return next question or feedback"""
    try:
        data = request.json or {}
        state = data.get('session_state')
        response_text = data.get('response', '').strip()
        
        if not state or not response_text:
            return jsonify({'error': 'Missing session_state or response'}), 400
            
        interview = InterviewSession.from_dict(state)
        
        if interview.is_disqualified:
            return jsonify({'error': 'Interview terminated due to proctoring disqualification.'}), 400
            
        # Check if this is response to "do you know coding?"
        if interview.coding_asked and interview.knows_coding is None:
            response_lower = response_text.lower()
            if any(w in response_lower for w in ['yes', 'python', 'java', 'javascript', 'c++', 'c#', 'ruby', 'go']):
                interview.knows_coding = True
                # Extract language
                for lang in ['python', 'java', 'javascript', 'c++', 'c#', 'ruby', 'go']:
                    if lang in response_lower:
                        interview.coding_language = lang.title()
                        break
                if not interview.coding_language:
                    interview.coding_language = "Python"
                print(f"User knows coding: {interview.coding_language}")
            else:
                interview.knows_coding = False
                print("User doesn't know coding")
                
        interview.conversation_history.append({
            'role': 'Candidate',
            'content': response_text,
            'timestamp': datetime.now().isoformat()
        })
        
        # Analyze response synchronously
        interview.analyze_response(response_text)
        
        # If client reports disqualification flags or we detect it
        if state.get('is_disqualified'):
            interview.is_disqualified = True
            
        if interview.current_question >= TOTAL_QUESTIONS:
            print("Interview complete!")
            feedback = interview.generate_feedback()
            if feedback:
                interview.conversation_history.append({
                    'role': 'Feedback',
                    'content': feedback,
                    'timestamp': datetime.now().isoformat()
                })
                return jsonify({
                    'status': 'complete',
                    'session_state': interview.to_dict(),
                    'feedback': feedback
                })
            else:
                return jsonify({'error': 'Failed to generate feedback report'}), 500
                
        next_question = interview.get_question(response_text)
        
        # Check if coding challenge should be given
        if next_question is None and interview.coding_challenge_given and not interview.coding_submission:
            print("Generating coding challenge...")
            challenge = interview.generate_coding_challenge()
            if challenge:
                return jsonify({
                    'status': 'coding_challenge',
                    'session_state': interview.to_dict(),
                    'challenge': challenge,
                    'language': interview.coding_language,
                    'template': interview.coding_template,
                    'question_number': interview.current_question,
                    'total_questions': TOTAL_QUESTIONS
                })
            else:
                return jsonify({'error': 'Failed to generate coding challenge'}), 500
                
        if next_question:
            interview.conversation_history.append({
                'role': 'Interviewer',
                'content': next_question,
                'timestamp': datetime.now().isoformat()
            })
            return jsonify({
                'status': 'question',
                'session_state': interview.to_dict(),
                'message': next_question,
                'question_number': interview.current_question,
                'total_questions': TOTAL_QUESTIONS
            })
        else:
            return jsonify({'error': 'Failed to generate next question'}), 500
            
    except Exception as e:
        err_msg = str(e)
        print(f"!!! Error in submit_response: {err_msg}")
        traceback.print_exc()
        if "quota" in err_msg.lower() or "429" in err_msg.lower() or "limit" in err_msg.lower():
            return jsonify({'error': 'Google Gemini API Quota Limit Exceeded (429). Please verify your API key limits.'}), 429
        return jsonify({'error': f'API Error during response processing: {err_msg}'}), 500

@app.route('/api/submit_code', methods=['POST'])
def submit_code():
    """Handle coding challenge submission"""
    try:
        data = request.json or {}
        state = data.get('session_state')
        code = data.get('code', '').strip()
        
        if not state or not code:
            return jsonify({'error': 'Missing session_state or code'}), 400
            
        interview = InterviewSession.from_dict(state)
        evaluation = interview.evaluate_code_submission(code)
        interview.coding_submission = evaluation
        
        interview.conversation_history.append({
            'role': 'Candidate',
            'content': f"[CODE]\n{code}",
            'timestamp': datetime.now().isoformat()
        })
        
        interview.conversation_history.append({
            'role': 'Evaluation',
            'content': evaluation['feedback'],
            'timestamp': datetime.now().isoformat()
        })
        
        # Get next question
        next_question = interview.get_question()
        if next_question:
            interview.conversation_history.append({
                'role': 'Interviewer',
                'content': next_question,
                'timestamp': datetime.now().isoformat()
            })
            
            return jsonify({
                'success': True,
                'session_state': interview.to_dict(),
                'evaluation': {
                    'score': evaluation['score'],
                    'feedback': evaluation['feedback'],
                    'correctness': evaluation.get('correctness', 0),
                    'quality': evaluation.get('quality', 0),
                    'efficiency': evaluation.get('efficiency', 0)
                },
                'next_question': next_question,
                'question_number': interview.current_question,
                'total_questions': TOTAL_QUESTIONS
            })
        else:
            return jsonify({'error': 'Failed to generate next question after code submission'}), 500
            
    except Exception as e:
        err_msg = str(e)
        print(f"!!! Error in submit_code: {err_msg}")
        traceback.print_exc()
        if "quota" in err_msg.lower() or "429" in err_msg.lower() or "limit" in err_msg.lower():
            return jsonify({'error': 'Google Gemini API Quota Limit Exceeded (429). Please verify your API key limits.'}), 429
        return jsonify({'error': f'API Error during code evaluation: {err_msg}'}), 500

@app.route('/api/download_report', methods=['POST'])
def download_report():
    """Stateless download of PDF report"""
    try:
        data = request.json or {}
        state = data.get('session_state')
        if not state:
            return "Missing session_state", 400
            
        interview = InterviewSession.from_dict(state)
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
        story = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle('Title', parent=styles['Title'], fontSize=28, textColor='#1e40af', spaceAfter=20, alignment=1)
        heading_style = ParagraphStyle('Heading', parent=styles['Heading2'], fontSize=14, textColor='#3b82f6', spaceAfter=10, spaceBefore=15)
        
        story.append(Paragraph("AI Interview Performance Report", title_style))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", styles['Normal']))
        story.append(Spacer(1, 0.3*inch))
        
        feedback_entry = next((h for h in interview.conversation_history if h['role'] == 'Feedback'), None)
        
        if feedback_entry:
            feedback_text = feedback_entry['content']
            sections = feedback_text.split('\n\n')
            for section in sections:
                if section.strip():
                    lines = section.split('\n')
                    if lines[0].isupper() or ':' in lines[0]:
                        story.append(Paragraph(html.escape(lines[0]), heading_style))
                        for line in lines[1:]:
                            if line.strip():
                                story.append(Paragraph(html.escape(line), styles['Normal']))
                                story.append(Spacer(1, 0.05*inch))
                    else:
                        story.append(Paragraph(html.escape(section), styles['Normal']))
                    story.append(Spacer(1, 0.15*inch))
        
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'interview_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"!!! Report error: {e}")
        return f"Error: {str(e)}", 500

if __name__ == '__main__':
    print("\n" + "="*50)
    print("STARTING STATALESS AI INTERVIEW BOT SERVER")
    print("="*50 + "\n")
    app.run(debug=True, host='127.0.0.1', port=5000)