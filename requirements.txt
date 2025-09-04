import os
import json
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai
from datetime import datetime
import logging

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cấu hình từ environment variables
ZALO_BOT_TOKEN = os.environ.get('ZALO_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')  # URL webhook trên Render

class ZaloBot:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://openapi.zalo.me/v3.0"
        
    def send_message(self, user_id, message):
        """Gửi tin nhắn text"""
        url = f"{self.base_url}/oa/message/cs"
        headers = {
            'Content-Type': 'application/json',
            'access_token': self.token
        }
        data = {
            'recipient': {
                'user_id': user_id
            },
            'message': {
                'text': message
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            logger.info(f"Sent message response: {response.status_code}")
            return response.json()
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    def send_typing_action(self, user_id):
        """Gửi action đang gõ"""
        url = f"{self.base_url}/oa/message/cs"
        headers = {
            'Content-Type': 'application/json',
            'access_token': self.token
        }
        data = {
            'recipient': {
                'user_id': user_id
            },
            'sender_action': 'typing_on'
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            return response.json()
        except Exception as e:
            logger.error(f"Error sending typing action: {e}")
            return None

    def set_webhook(self, webhook_url):
        """Thiết lập webhook"""
        url = f"{self.base_url}/oa/webhook"
        headers = {
            'Content-Type': 'application/json',
            'access_token': self.token
        }
        data = {
            'url': webhook_url,
            'events': ['user_send_text', 'user_send_image', 'user_send_link']
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            logger.info(f"Webhook setup response: {response.status_code}")
            return response.json()
        except Exception as e:
            logger.error(f"Error setting webhook: {e}")
            return None

class GeminiAI:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        
    def generate_response(self, message, context=None):
        """Tạo phản hồi từ Gemini"""
        try:
            # Thêm context nếu có
            prompt = message
            if context:
                prompt = f"Ngữ cảnh: {context}\nTin nhắn: {message}"
            
            # Thêm hướng dẫn cho bot
            system_prompt = """
            Bạn là một trợ lý AI thông minh và hữu ích trên Zalo. 
            Hãy trả lời một cách tự nhiên, thân thiện và hữu ích.
            Trả lời bằng tiếng Việt trừ khi được yêu cầu ngôn ngữ khác.
            Giữ câu trả lời ngắn gọn và dễ hiểu (tối đa 500 từ).
            """
            
            full_prompt = f"{system_prompt}\n\nCâu hỏi: {prompt}"
            
            response = self.model.generate_content(full_prompt)
            return response.text
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "Xin lỗi, tôi đang gặp chút vấn đề. Bạn có thể thử lại sau không?"

# Khởi tạo bot và AI
zalo_bot = ZaloBot(ZALO_BOT_TOKEN)
gemini_ai = GeminiAI(GEMINI_API_KEY) if GEMINI_API_KEY else None

# Lưu trữ context người dùng đơn giản (trong thực tế nên dùng database)
user_context = {}

@app.route('/')
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "running",
        "bot_configured": bool(ZALO_BOT_TOKEN),
        "gemini_configured": bool(GEMINI_API_KEY),
        "timestamp": datetime.now().isoformat()
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Xử lý webhook từ Zalo"""
    try:
        data = request.get_json()
        logger.info(f"Received webhook data: {json.dumps(data, indent=2)}")
        
        if not data:
            return jsonify({"status": "no data"}), 400
        
        # Xử lý event
        if 'events' in data:
            for event in data['events']:
                handle_event(event)
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_event(event):
    """Xử lý từng event"""
    try:
        event_name = event.get('event_name')
        user_id = event.get('sender', {}).get('id')
        
        if not user_id:
            logger.warning("No user_id found in event")
            return
        
        logger.info(f"Handling event: {event_name} from user: {user_id}")
        
        if event_name == 'user_send_text':
            handle_text_message(event, user_id)
        elif event_name == 'user_send_image':
            handle_image_message(event, user_id)
        elif event_name == 'user_send_link':
            handle_link_message(event, user_id)
        else:
            logger.info(f"Unhandled event: {event_name}")
            
    except Exception as e:
        logger.error(f"Error handling event: {e}")

def handle_text_message(event, user_id):
    """Xử lý tin nhắn text"""
    try:
        message = event.get('message', {}).get('text', '')
        
        if not message:
            return
        
        logger.info(f"Received message from {user_id}: {message}")
        
        # Gửi typing action
        zalo_bot.send_typing_action(user_id)
        
        # Xử lý các lệnh đặc biệt
        if message.lower().startswith('/start'):
            response = "🤖 Xin chào! Tôi là Bot AI được trang bị Gemini. Tôi có thể trả lời câu hỏi, hỗ trợ và trò chuyện với bạn. Hãy gửi bất kỳ câu hỏi nào bạn muốn!"
            zalo_bot.send_message(user_id, response)
            return
            
        elif message.lower().startswith('/help'):
            response = """
📋 Danh sách lệnh:
/start - Khởi động bot
/help - Hiển thị trợ giúp
/clear - Xóa lịch sử trò chuyện

🤖 Tính năng:
• Trả lời câu hỏi bằng AI Gemini
• Trò chuyện tự nhiên
• Hỗ trợ tiếng Việt
• Nhớ ngữ cảnh cuộc trò chuyện

Chỉ cần gửi tin nhắn bình thường để bắt đầu!
            """
            zalo_bot.send_message(user_id, response.strip())
            return
            
        elif message.lower().startswith('/clear'):
            if user_id in user_context:
                del user_context[user_id]
            response = "🗑️ Đã xóa lịch sử trò chuyện!"
            zalo_bot.send_message(user_id, response)
            return
        
        # Sử dụng Gemini AI để tạo phản hồi
        if gemini_ai:
            # Lấy context của user
            context = user_context.get(user_id, [])
            context_text = None
            if context:
                # Lấy 3 tin nhắn gần nhất làm context
                recent_context = context[-6:]  # 3 cặp hỏi-đáp
                context_text = "\n".join([f"User: {ctx['user']}\nBot: {ctx['bot']}" for ctx in recent_context])
            
            # Tạo phản hồi
            ai_response = gemini_ai.generate_response(message, context_text)
            
            # Lưu context
            if user_id not in user_context:
                user_context[user_id] = []
            
            user_context[user_id].append({
                'user': message,
                'bot': ai_response,
                'timestamp': datetime.now().isoformat()
            })
            
            # Giữ chỉ 10 cặp hỏi-đáp gần nhất
            if len(user_context[user_id]) > 10:
                user_context[user_id] = user_context[user_id][-10:]
            
            # Gửi phản hồi
            zalo_bot.send_message(user_id, ai_response)
            
        else:
            # Fallback nếu không có Gemini
            response = f"📝 Tôi đã nhận được tin nhắn: {message}\n\n⚠️ Tính năng AI chưa được cấu hình. Vui lòng liên hệ admin để kích hoạt."
            zalo_bot.send_message(user_id, response)
            
    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        zalo_bot.send_message(user_id, "Xin lỗi, đã xảy ra lỗi khi xử lý tin nhắn của bạn. Vui lòng thử lại!")

def handle_image_message(event, user_id):
    """Xử lý tin nhắn hình ảnh"""
    try:
        response = "🖼️ Cảm ơn bạn đã gửi hình ảnh! Hiện tại tôi chưa thể phân tích hình ảnh, nhưng tôi có thể trả lời các câu hỏi khác của bạn."
        zalo_bot.send_message(user_id, response)
    except Exception as e:
        logger.error(f"Error handling image message: {e}")

def handle_link_message(event, user_id):
    """Xử lý tin nhắn link"""
    try:
        response = "🔗 Cảm ơn bạn đã chia sẻ link! Tôi có thể trả lời các câu hỏi về nội dung hoặc hỗ trợ bạn với vấn đề khác."
        zalo_bot.send_message(user_id, response)
    except Exception as e:
        logger.error(f"Error handling link message: {e}")

@app.route('/setup-webhook', methods=['POST'])
def setup_webhook():
    """Endpoint để thiết lập webhook (chỉ cần gọi 1 lần)"""
    try:
        if not WEBHOOK_URL:
            return jsonify({"error": "WEBHOOK_URL not configured"}), 400
            
        result = zalo_bot.set_webhook(WEBHOOK_URL)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    
    # Log thông tin cấu hình
    logger.info("🚀 Starting Zalo Bot with Gemini 2.5 Flash + Google Search")
    logger.info(f"Port: {port}")
    logger.info(f"Zalo Token configured: {bool(ZALO_BOT_TOKEN)}")
    logger.info(f"Gemini API configured: {bool(GEMINI_API_KEY)}")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")
    logger.info("✨ Features: Thinking, Google Search, Streaming responses")
    
    app.run(host='0.0.0.0', port=port, debug=False)
