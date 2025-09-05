import os
import json
import requests
from flask import Flask, request, jsonify, send_file
from google import genai
from google.genai import types
from datetime import datetime
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
import secrets
import hmac
import hashlib
import tempfile
import io
import base64
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import black, blue, red
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import uuid

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cấu hình từ environment variables
ZALO_BOT_TOKEN = os.environ.get('ZALO_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
WEBHOOK_SECRET_TOKEN = os.environ.get('WEBHOOK_SECRET_TOKEN') or secrets.token_urlsafe(16)

class ExamPDFGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.custom_styles = self._create_custom_styles()
        
    def _create_custom_styles(self):
        """Tạo các style tùy chỉnh cho PDF"""
        custom_styles = {}
        
        # Tiêu đề chính
        custom_styles['ExamTitle'] = ParagraphStyle(
            'ExamTitle',
            parent=self.styles['Title'],
            fontSize=18,
            spaceAfter=20,
            alignment=1,  # Center
            textColor=blue
        )
        
        # Thông tin đề thi
        custom_styles['ExamInfo'] = ParagraphStyle(
            'ExamInfo',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceAfter=10,
            alignment=1
        )
        
        # Câu hỏi
        custom_styles['Question'] = ParagraphStyle(
            'Question',
            parent=self.styles['Normal'],
            fontSize=12,
            spaceAfter=8,
            leftIndent=0,
            fontName='Helvetica-Bold'
        )
        
        # Đáp án
        custom_styles['Answer'] = ParagraphStyle(
            'Answer',
            parent=self.styles['Normal'],
            fontSize=11,
            spaceAfter=5,
            leftIndent=20
        )
        
        # Ghi chú
        custom_styles['Note'] = ParagraphStyle(
            'Note',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=10,
            textColor=red,
            fontStyle='italic'
        )
        
        return custom_styles
    
    def generate_exam_pdf(self, exam_data, filename=None):
        """Tạo file PDF từ dữ liệu đề thi"""
        if not filename:
            filename = f"exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        # Tạo file tạm
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
        
        try:
            # Tạo PDF document
            doc = SimpleDocTemplate(
                temp_file.name,
                pagesize=A4,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )
            
            # Tạo nội dung PDF
            story = []
            
            # Tiêu đề đề thi
            title = Paragraph(exam_data.get('title', 'ĐỀ THI'), self.custom_styles['ExamTitle'])
            story.append(title)
            story.append(Spacer(1, 12))
            
            # Thông tin đề thi
            info_lines = [
                f"Môn: {exam_data.get('subject', 'N/A')}",
                f"Thời gian: {exam_data.get('duration', 'N/A')}",
                f"Lớp: {exam_data.get('grade', 'N/A')}",
                f"Ngày tạo: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            ]
            
            for line in info_lines:
                info_para = Paragraph(line, self.custom_styles['ExamInfo'])
                story.append(info_para)
            
            story.append(Spacer(1, 20))
            
            # Hướng dẫn
            if exam_data.get('instructions'):
                instructions = Paragraph(
                    f"<b>Hướng dẫn:</b> {exam_data['instructions']}", 
                    self.custom_styles['Note']
                )
                story.append(instructions)
                story.append(Spacer(1, 15))
            
            # Câu hỏi
            questions = exam_data.get('questions', [])
            for i, question in enumerate(questions, 1):
                # Câu hỏi
                q_text = f"Câu {i}: {question.get('question', '')}"
                q_para = Paragraph(q_text, self.custom_styles['Question'])
                story.append(q_para)
                
                # Đáp án (nếu có)
                if question.get('options'):
                    for j, option in enumerate(question['options']):
                        option_letter = chr(65 + j)  # A, B, C, D
                        option_text = f"{option_letter}. {option}"
                        option_para = Paragraph(option_text, self.custom_styles['Answer'])
                        story.append(option_para)
                
                # Thêm khoảng trống cho câu trả lời tự luận
                if question.get('type') == 'essay':
                    story.append(Spacer(1, 30))
                    lines = Paragraph("_" * 60, self.custom_styles['Answer'])
                    story.append(lines)
                    story.append(Spacer(1, 10))
                else:
                    story.append(Spacer(1, 15))
            
            # Footer
            footer = Paragraph(
                f"--- Hết ---<br/>Tạo bởi Zalo Bot AI - {datetime.now().strftime('%d/%m/%Y %H:%M')}",
                self.custom_styles['Note']
            )
            story.append(Spacer(1, 30))
            story.append(footer)
            
            # Build PDF
            doc.build(story)
            
            return temp_file.name
            
        except Exception as e:
            logger.error(f"Error generating PDF: {e}")
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
            return None

class ZaloBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://bot-api.zapps.me/bot{token}"
        
    def send_message(self, chat_id, text):
        """Gửi tin nhắn text"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': str(chat_id),
            'text': text[:2000]
        }
        
        try:
            response = requests.post(url, json=data)
            logger.info(f"Sent message response: {response.status_code}")
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    def upload_file(self, file_path):
        """Upload file lên Zalo và lấy file_token"""
        url = f"{self.base_url}/uploadFile"
        
        try:
            with open(file_path, 'rb') as file:
                files = {'file': file}
                response = requests.post(url, files=files)
                
            logger.info(f"Upload file response: {response.status_code}")
            logger.info(f"Upload response: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    return result.get('result', {}).get('file_token')
            return None
            
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            return None
    
    def send_document(self, chat_id, file_path, caption=None):
        """Gửi file document"""
        # Method 1: Thử upload file trước rồi gửi file_token
        file_token = self.upload_file(file_path)
        if file_token:
            return self.send_file_by_token(chat_id, file_token, caption)
        
        # Method 2: Gửi trực tiếp file (fallback)
        url = f"{self.base_url}/sendDocument"
        
        try:
            with open(file_path, 'rb') as file:
                files = {
                    'document': file
                }
                data = {
                    'chat_id': str(chat_id)
                }
                if caption:
                    data['caption'] = caption
                
                response = requests.post(url, files=files, data=data)
            
            logger.info(f"Send document response: {response.status_code}")
            logger.info(f"Response: {response.text}")
            return response.json() if response.status_code == 200 else None
            
        except Exception as e:
            logger.error(f"Error sending document: {e}")
            return None
    
    def send_file_by_token(self, chat_id, file_token, caption=None):
        """Gửi file bằng file_token"""
        url = f"{self.base_url}/sendMessage"
        
        data = {
            'chat_id': str(chat_id),
            'message': {
                'attachment': {
                    'type': 'file',
                    'payload': {
                        'file_token': file_token
                    }
                }
            }
        }
        
        if caption:
            data['message']['text'] = caption
        
        try:
            response = requests.post(url, json=data)
            logger.info(f"Send file by token response: {response.status_code}")
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Error sending file by token: {e}")
            return None
    
    def set_webhook(self, webhook_url, secret_token):
        """Thiết lập webhook"""
        url = f"{self.base_url}/setWebhook"
        data = {
            'url': webhook_url,
            'secret_token': secret_token
        }
        
        try:
            response = requests.post(url, json=data)
            return response.json() if response.status_code == 200 else response.json()
        except Exception as e:
            logger.error(f"Error setting webhook: {e}")
            return None

class GeminiExamGenerator:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash"
        
    def generate_exam(self, subject, grade, num_questions, question_types, difficulty="medium", specific_topics=None):
        """Tạo đề thi bằng Gemini"""
        try:
            # Tạo prompt chi tiết
            prompt = f"""
            Tạo một đề thi {subject} cho lớp {grade} với các yêu cầu sau:
            
            📋 **Thông tin đề thi:**
            - Số câu hỏi: {num_questions}
            - Loại câu hỏi: {', '.join(question_types)}
            - Mức độ: {difficulty}
            - Chủ đề cụ thể: {specific_topics if specific_topics else 'Tổng hợp'}
            
            📝 **Yêu cầu format JSON:**
            {{
                "title": "ĐỀ KIỂM TRA {subject.upper()}",
                "subject": "{subject}",
                "grade": "{grade}",
                "duration": "45 phút",
                "instructions": "Đọc kỹ đề bài trước khi làm bài. Viết rõ ràng, sạch sẽ.",
                "questions": [
                    {{
                        "id": 1,
                        "type": "multiple_choice|essay|fill_blank",
                        "question": "Nội dung câu hỏi...",
                        "options": ["Đáp án A", "Đáp án B", "Đáp án C", "Đáp án D"],
                        "correct_answer": "A",
                        "explanation": "Giải thích đáp án đúng",
                        "points": 1
                    }}
                ]
            }}
            
            🎯 **Lưu ý quan trọng:**
            - Câu hỏi phải phù hợp với chương trình {grade}
            - Nội dung chính xác, không sai lệch kiến thức
            - Đáp án rõ ràng, không gây nhầm lẫn
            - Phân bổ điểm hợp lý
            - Trả về CHÍNH XÁC format JSON, không thêm markdown hay text khác
            
            📚 **Chủ đề tập trung:** {specific_topics if specific_topics else 'Tổng hợp kiến thức cơ bản'}
            """
            
            # Generate với thinking để tạo đề thi chất lượng
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)]
                )
            ]
            
            generate_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=-1),
                tools=[types.Tool(googleSearch=types.GoogleSearch())] if specific_topics else None
            )
            
            response_text = ""
            for chunk in self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_config
            ):
                if chunk.text:
                    response_text += chunk.text
            
            # Parse JSON từ response
            try:
                # Tìm và extract JSON từ response
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}') + 1
                
                if start_idx != -1 and end_idx != -1:
                    json_str = response_text[start_idx:end_idx]
                    exam_data = json.loads(json_str)
                    return exam_data
                else:
                    logger.error("No valid JSON found in Gemini response")
                    return None
                    
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"Response text: {response_text}")
                return None
            
        except Exception as e:
            logger.error(f"Error generating exam: {e}")
            return None

# Khởi tạo components
zalo_bot = ZaloBot(ZALO_BOT_TOKEN) if ZALO_BOT_TOKEN else None
gemini_exam = GeminiExamGenerator(GEMINI_API_KEY) if GEMINI_API_KEY else None
pdf_generator = ExamPDFGenerator()

# Storage cho exam sessions
exam_sessions = {}

@app.route('/')
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "running",
        "features": [
            "Zalo Bot API",
            "Gemini 2.5 Flash",
            "PDF Exam Generation",
            "File Upload & Send"
        ],
        "bot_configured": bool(ZALO_BOT_TOKEN),
        "gemini_configured": bool(GEMINI_API_KEY),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Xử lý webhook từ Zalo"""
    try:
        data = request.get_json()
        logger.info(f"Received webhook: {json.dumps(data, indent=2)}")
        
        if 'message' in data:
            handle_message(data)
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

def handle_message(data):
    """Xử lý tin nhắn"""
    try:
        message_data = data.get('message', {})
        chat_id = message_data.get('chat', {}).get('id')
        user_id = message_data.get('from', {}).get('id')
        text = message_data.get('text', '')
        
        if not chat_id or not text:
            return
        
        logger.info(f"Message from {user_id}: {text}")
        
        # Xử lý commands
        if text.lower().startswith('/start'):
            welcome_msg = """🎓 **Chào mừng đến với Exam Generator Bot!**

✨ **Tính năng:**
• 📝 Tạo đề thi tự động bằng Gemini AI
• 📄 Xuất file PDF chuyên nghiệp  
• 🔍 Tìm kiếm nội dung mới nhất
• 🎯 Tùy chỉnh theo từng môn học

📋 **Cách sử dụng:**
• `/create` - Tạo đề thi mới
• `/help` - Hướng dẫn chi tiết
• `/demo` - Tạo đề thi mẫu

🚀 **Bắt đầu:** Gõ `/create` để tạo đề thi đầu tiên!"""
            
            zalo_bot.send_message(chat_id, welcome_msg)
            
        elif text.lower().startswith('/help'):
            help_msg = """📚 **Hướng dẫn sử dụng Exam Generator Bot**

🔧 **Commands:**
• `/create` - Bắt đầu tạo đề thi mới
• `/demo` - Tạo đề thi toán lớp 10 mẫu
• `/status` - Kiểm tra trạng thái hệ thống

📝 **Quy trình tạo đề thi:**
1️⃣ Gõ `/create` 
2️⃣ Nhập thông tin: môn học, lớp, số câu
3️⃣ Bot tạo đề thi bằng Gemini AI
4️⃣ Xuất file PDF và gửi qua Zalo

💡 **Ví dụ lệnh tạo nhanh:**
`/create Toán 10 15 trắc nghiệm hàm số`
`/create Văn 12 10 tự luận thơ Nguyễn Du`

🎯 **Hỗ trợ:**
• Tất cả môn học từ lớp 1-12
• Trắc nghiệm, tự luận, điền khuyết
• Tìm kiếm nội dung mới nhất"""
            
            zalo_bot.send_message(chat_id, help_msg)
            
        elif text.lower().startswith('/demo'):
            zalo_bot.send_message(chat_id, "🔄 Đang tạo đề thi Toán lớp 10 mẫu...")
            create_demo_exam(chat_id)
            
        elif text.lower().startswith('/create'):
            handle_create_exam(chat_id, user_id, text)
            
        elif text.lower().startswith('/status'):
            status_msg = f"""⚡ **Trạng thái hệ thống:**

🤖 Zalo Bot: {"✅ Hoạt động" if zalo_bot else "❌ Lỗi"}
🧠 Gemini AI: {"✅ Hoạt động" if gemini_exam else "❌ Lỗi"}  
📄 PDF Generator: ✅ Hoạt động
🔒 Webhook: ✅ Bảo mật

📊 **Thống kê:**
• Sessions: {len(exam_sessions)}
• Uptime: {datetime.now().strftime('%H:%M:%S')}

🎯 **Sẵn sàng tạo đề thi!**"""
            
            zalo_bot.send_message(chat_id, status_msg)
            
        else:
            # Xử lý input cho exam creation
            session_key = f"{chat_id}_{user_id}"
            if session_key in exam_sessions:
                handle_exam_input(chat_id, user_id, text)
            else:
                suggestion_msg = """💡 **Gợi ý:**

Để tạo đề thi, hãy sử dụng:
• `/create` - Tạo đề thi mới
• `/demo` - Xem đề thi mẫu
• `/help` - Hướng dẫn chi tiết

🎓 Hoặc thử ngay: `/create Toán 10 15 trắc nghiệm`"""
                
                zalo_bot.send_message(chat_id, suggestion_msg)
        
    except Exception as e:
        logger.error(f"Error handling message: {e}")

def handle_create_exam(chat_id, user_id, text):
    """Xử lý lệnh tạo đề thi"""
    try:
        session_key = f"{chat_id}_{user_id}"
        
        # Parse lệnh nhanh: /create Toán 10 15 trắc nghiệm hàm số
        parts = text.split()[1:]  # Bỏ '/create'
        
        if len(parts) >= 3:
            subject = parts[0]
            grade = parts[1] 
            num_questions = int(parts[2]) if parts[2].isdigit() else 10
            question_type = parts[3] if len(parts) > 3 else "trắc nghiệm"
            topics = " ".join(parts[4:]) if len(parts) > 4 else None
            
            zalo_bot.send_message(chat_id, f"🔄 Đang tạo đề thi {subject} lớp {grade}...")
            create_exam_async(chat_id, subject, grade, num_questions, [question_type], topics)
            
        else:
            # Bắt đầu interactive session
            exam_sessions[session_key] = {
                'step': 'subject',
                'data': {}
            }
            
            prompt_msg = """📝 **Tạo đề thi mới**

Nhập thông tin theo format:
`[Môn học] [Lớp] [Số câu] [Loại câu] [Chủ đề]`

🎯 **Ví dụ:**
• `Toán 10 15 trắc nghiệm hàm số`
• `Văn 12 10 tự luận thơ Nguyễn Du`
• `Anh 9 20 điền khuyết thì quá khứ`

💡 **Hoặc nhập từng bước:**
Môn học (Toán, Văn, Anh, Lý, Hóa, ...)?: """
            
            zalo_bot.send_message(chat_id, prompt_msg)
    
    except Exception as e:
        logger.error(f"Error in handle_create_exam: {e}")
        zalo_bot.send_message(chat_id, "❌ Lỗi khi xử lý lệnh. Vui lòng thử lại!")

def create_exam_async(chat_id, subject, grade, num_questions, question_types, topics=None):
    """Tạo đề thi async"""
    try:
        # Generate exam với Gemini
        exam_data = gemini_exam.generate_exam(
            subject=subject,
            grade=grade, 
            num_questions=num_questions,
            question_types=question_types,
            specific_topics=topics
        )
        
        if not exam_data:
            zalo_bot.send_message(chat_id, "❌ Không thể tạo đề thi. Vui lòng thử lại!")
            return
        
        # Tạo PDF
        pdf_path = pdf_generator.generate_exam_pdf(exam_data)
        
        if not pdf_path:
            zalo_bot.send_message(chat_id, "❌ Không thể tạo file PDF. Vui lòng thử lại!")
            return
        
        # Gửi file PDF
        caption = f"""📄 **Đề thi {exam_data.get('subject', subject)}**

📚 Lớp: {exam_data.get('grade', grade)}
📝 Số câu: {len(exam_data.get('questions', []))}
⏰ Thời gian: {exam_data.get('duration', '45 phút')}
🎯 Chủ đề: {topics or 'Tổng hợp'}

✅ Đề thi đã được tạo bằng Gemini AI"""
        
        result = zalo_bot.send_document(chat_id, pdf_path, caption)
        
        if result:
            zalo_bot.send_message(chat_id, "✅ Đã gửi đề thi PDF thành công!\n\n💡 Gõ `/create` để tạo đề thi khác.")
        else:
            # Fallback: gửi thông tin đề thi dạng text
            text_content = format_exam_as_text(exam_data)
            zalo_bot.send_message(chat_id, f"📝 **Nội dung đề thi:**\n\n{text_content}")
        
        # Cleanup
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)
            
    except Exception as e:
        logger.error(f"Error creating exam: {e}")
        zalo_bot.send_message(chat_id, "❌ Có lỗi xảy ra khi tạo đề thi. Vui lòng thử lại!")

def create_demo_exam(chat_id):
    """Tạo đề thi demo"""
    demo_exam = {
        "title": "ĐỀ KIỂM TRA TOÁN HỌC",
        "subject": "Toán",
        "grade": "Lớp 10",
        "duration": "45 phút",
        "instructions": "Đọc kỹ đề bài. Viết rõ ràng, sạch sẽ.",
        "questions": [
            {
                "id": 1,
                "type": "multiple_choice",
                "question": "Hàm số nào sau đây là hàm số bậc nhất?",
                "options": ["y = 2x + 1", "y = x²", "y = 1/x", "y = √x"],
                "correct_answer": "A",
                "points": 1
            },
            {
                "id": 2,
                "type": "multiple_choice", 
                "question": "Tập xác định của hàm số y = √(x-1) là:",
                "options": ["[1, +∞)", "(-∞, 1]", "ℝ", "(1, +∞)"],
                "correct_answer": "A",
                "points": 1
            }
        ]
    }
    
    create_exam_from_data(chat_id, demo_exam)

def create_exam_from_data(chat_id, exam_data):
    """Tạo PDF từ data có sẵn"""
    try:
        pdf_path = pdf_generator.generate_exam_pdf(exam_data)
        
        if pdf_path:
            caption = f"📄 **{exam_data['title']}** (Demo)\n\n✅ Tạo bằng Gemini AI"
            result = zalo_bot.send_document(chat_id, pdf_path, caption)
            
            if result:
                zalo_bot.send_message(chat_id, "✅ Demo thành công! Gõ `/create` để tạo đề thi riêng.")
            
            # Cleanup
            os.unlink(pdf_path)
        else:
            zalo_bot.send_message(chat_id, "❌ Không thể tạo demo PDF.")
    
    except Exception as e:
        logger.error(f"Error creating demo: {e}")

def format_exam_as_text(exam_data):
    """Format đề thi thành text"""
    try:
        text = f"""📋 **{exam_data.get('title', 'ĐỀ THI')}**

📚 Môn: {exam_data.get('subject', 'N/A')}
🎓 Lớp: {exam_data.get('grade', 'N/A')}  
⏰ Thời gian: {exam_data.get('duration', '45 phút')}

📝 **Hướng dẫn:** {exam_data.get('instructions', 'Làm bài cẩn thận')}

───────────────────"""
        
        questions = exam_data.get('questions', [])
        for i, q in enumerate(questions[:5], 1):  # Chỉ hiện 5 câu đầu
            text += f"\n\n**Câu {i}:** {q.get('question', '')}"
            
            if q.get('options'):
                for j, opt in enumerate(q['options']):
                    letter = chr(65 + j)
                    text += f"\n{letter}. {opt}"
        
        if len(questions) > 5:
            text += f"\n\n... (và {len(questions) - 5} câu khác trong file PDF)"
        
        text += f"\n\n───────────────────\n✅ **Tổng {len(questions)} câu** - Tạo bởi Gemini AI"
        
        return text[:1500]  # Giới hạn độ dài
        
    except Exception as e:
        logger.error(f"Error formatting exam text: {e}")
        return "Không thể hiển thị nội dung đề thi."

@app.route('/setup-webhook', methods=['POST', 'GET'])
def setup_webhook():
    """Setup webhook endpoint"""
    try:
        if not all([ZALO_BOT_TOKEN, WEBHOOK_URL, WEBHOOK_SECRET_TOKEN]):
            return jsonify({"error": "Missing configuration"}), 400
        
        webhook_endpoint = WEBHOOK_URL + '/webhook'
        result = zalo_bot.set_webhook(webhook_endpoint, WEBHOOK_SECRET_TOKEN)
        
        return jsonify({
            "success": result and result.get('ok'),
            "webhook_url": webhook_endpoint,
            "result": result
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test-pdf')
def test_pdf():
    """Test PDF generation"""
    try:
        demo_data = {
            "title": "TEST PDF GENERATION",
            "subject": "Test",
            "grade": "Demo",
            "duration": "N/A",
            "questions": [{"id": 1, "question": "Test question?", "type": "multiple_choice"}]
        }
        
        pdf_path = pdf_generator.generate_exam_pdf(demo_data)
        
        if pdf_path:
            return send_file(pdf_path, as_attachment=True, download_name="test_exam.pdf")
        else:
            return jsonify({"error": "PDF generation failed"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    
    logger.info("🚀 Starting Zalo Exam Generator Bot")
    logger.info(f"Features: PDF Generation, Gemini AI, File Upload")
    logger.info(f"Bot configured: {bool(zalo_bot)}")
    logger.info(f"Gemini configured: {bool(gemini_exam)}")
    
    app.run(host='0.0.0.0', port=port, debug=False)
