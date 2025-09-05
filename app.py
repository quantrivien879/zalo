import os
import json
import requests
from flask import Flask, request, jsonify
from google import genai
from google.genai import types
from datetime import datetime
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
import secrets
import hmac
import hashlib

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Cấu hình từ environment variables
ZALO_BOT_TOKEN = os.environ.get('ZALO_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')  # URL webhook trên Render
WEBHOOK_SECRET_TOKEN = os.environ.get('WEBHOOK_SECRET_TOKEN') or secrets.token_urlsafe(16)  # Tạo secret token ngẫu nhiên nếu không có

class ZaloBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://bot-api.zapps.me/bot{token}"  # Sử dụng Bot API
        
    def send_message(self, chat_id, text):
        """Gửi tin nhắn text theo Bot API"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': str(chat_id),
            'text': text[:2000]  # Giới hạn 2000 ký tự
        }
        
        try:
            response = requests.post(url, json=data)
            logger.info(f"Sent message response: {response.status_code}")
            logger.info(f"Response content: {response.text}")
            return response.json() if response.status_code == 200 else response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return None
    
    def set_webhook(self, webhook_url, secret_token):
        """Thiết lập webhook cho Bot API với secret_token"""
        url = f"{self.base_url}/setWebhook"
        data = {
            'url': webhook_url,
            'secret_token': secret_token  # Thêm secret_token (tối thiểu 8 ký tự)
        }
        
        try:
            response = requests.post(url, json=data)
            logger.info(f"Webhook setup response: {response.status_code}")
            logger.info(f"Response content: {response.text}")
            return response.json() if response.status_code == 200 else response.json()
        except Exception as e:
            logger.error(f"Error setting webhook: {e}")
            return None

    def get_bot_info(self):
        """Lấy thông tin bot để test token"""
        url = f"{self.base_url}/getMe"
        
        try:
            response = requests.get(url)
            logger.info(f"Get bot info response: {response.status_code}")
            logger.info(f"Response content: {response.text}")
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.error(f"Error getting bot info: {e}")
            return None

class GeminiAI:
    def __init__(self, api_key):
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash"
        self.executor = ThreadPoolExecutor(max_workers=2)
        
    def generate_response(self, message, context=None, use_search=False):
        """Tạo phản hồi từ Gemini với khả năng tìm kiếm"""
        try:
            # Thêm context nếu có
            prompt = message
            if context:
                prompt = f"Ngữ cảnh cuộc trò chuyện trước đó:\n{context}\n\nTin nhắn hiện tại: {message}"
            
            # Thêm hướng dẫn cho bot
            system_prompt = """
            Bạn là một trợ lý AI thông minh và hữu ích trên Zalo. 
            Hãy trả lời một cách tự nhiên, thân thiện và hữu ích.
            Trả lời bằng tiếng Việt trừ khi được yêu cầu ngôn ngữ khác.
            Giữ câu trả lời ngắn gọn và dễ hiểu (tối đa 500 từ).
            
            Nếu câu hỏi cần thông tin mới nhất hoặc tìm kiếm trên internet, 
            hãy sử dụng công cụ tìm kiếm để có thông tin chính xác.
            """
            
            full_prompt = f"{system_prompt}\n\n{prompt}"
            
            # Tạo content cho API mới
            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=full_prompt),
                    ],
                ),
            ]
            
            # Cấu hình tools nếu cần tìm kiếm
            tools = []
            if use_search or self._should_use_search(message):
                tools.append(types.Tool(googleSearch=types.GoogleSearch()))
            
            # Cấu hình generation
            generate_content_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_budget=-1,  # Unlimited thinking
                ),
                tools=tools if tools else None,
            )
            
            # Generate response
            response_text = ""
            for chunk in self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            ):
                if chunk.text:
                    response_text += chunk.text
            
            return response_text if response_text else "Xin lỗi, tôi không thể tạo được phản hồi lúc này."
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "Xin lỗi, tôi đang gặp chút vấn đề. Bạn có thể thử lại sau không?"
    
    def _should_use_search(self, message):
        """Kiểm tra xem có nên sử dụng tìm kiếm không"""
        search_keywords = [
            'tin tức', 'news', 'mới nhất', 'hiện tại', 'hôm nay',
            'giá', 'price', 'tỷ giá', 'thời tiết', 'weather',
            'tìm kiếm', 'search', 'thông tin về', 'what is',
            'covid', 'virus', 'dịch bệnh', 'bầu cử', 'election'
        ]
        
        message_lower = message.lower()
        return any(keyword in message_lower for keyword in search_keywords)

def verify_webhook_signature(secret_token, request_data):
    """Xác minh webhook signature (optional security measure)"""
    # Đây là hàm optional để xác minh signature nếu Zalo hỗ trợ
    # Hiện tại chỉ kiểm tra header secret token cơ bản
    return True

# Khởi tạo bot và AI
zalo_bot = ZaloBot(ZALO_BOT_TOKEN) if ZALO_BOT_TOKEN else None
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
        "webhook_secret_configured": bool(WEBHOOK_SECRET_TOKEN),
        "timestamp": datetime.now().isoformat(),
        "api_type": "Zalo Bot API with Secret Token"
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """Xử lý webhook từ Zalo Bot API"""
    try:
        # Lấy secret token từ header (nếu Zalo gửi)
        received_secret = request.headers.get('X-Zalo-Bot-Secret-Token')
        
        # Kiểm tra secret token nếu có
        if WEBHOOK_SECRET_TOKEN and received_secret:
            if received_secret != WEBHOOK_SECRET_TOKEN:
                logger.warning("Invalid webhook secret token")
                return jsonify({"status": "forbidden"}), 403
        
        data = request.get_json()
        logger.info(f"Received webhook data: {json.dumps(data, indent=2)}")
        
        if not data:
            return jsonify({"status": "no data"}), 400
        
        # Xử lý tin nhắn từ Bot API
        if 'message' in data:
            handle_message(data)
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_message(data):
    """Xử lý tin nhắn từ Bot API"""
    try:
        message_data = data.get('message', {})
        chat_id = message_data.get('chat', {}).get('id')
        user_id = message_data.get('from', {}).get('id')
        text = message_data.get('text', '')
        
        if not chat_id or not text:
            logger.warning("Missing chat_id or text in message")
            return
        
        logger.info(f"Received message from {user_id} in chat {chat_id}: {text}")
        
        # Xử lý các lệnh đặc biệt
        if text.lower().startswith('/start'):
            response = """🤖 Xin chào! Tôi là Bot AI được trang bị Gemini 2.5 Flash với khả năng:

✨ Trả lời câu hỏi thông minh
🔍 Tìm kiếm thông tin mới nhất trên Google  
💭 Suy nghĩ logic và phân tích sâu
🗣️ Trò chuyện tự nhiên bằng tiếng Việt
🔒 Bảo mật với Secret Token

Hãy gửi bất kỳ câu hỏi nào bạn muốn!"""
            zalo_bot.send_message(chat_id, response)
            return
            
        elif text.lower().startswith('/help'):
            response = """📋 Danh sách lệnh:
/start - Khởi động bot
/help - Hiển thị trợ giúp
/clear - Xóa lịch sử trò chuyện
/search [câu hỏi] - Tìm kiếm thông tin mới nhất
/token - Hiển thị thông tin secret token

🤖 Tính năng AI mới:
• Gemini 2.5 Flash - Model mới nhất
• Tìm kiếm Google tự động
• Khả năng suy nghĩ logic (thinking)
• Trả lời dựa trên thông tin real-time
• Nhớ ngữ cảnh cuộc trò chuyện
• Bảo mật webhook với secret token

🔍 Tự động tìm kiếm khi:
• Hỏi tin tức, thời tiết
• Hỏi giá cả, tỷ giá
• Cần thông tin mới nhất
• Hỏi về sự kiện hiện tại

Chỉ cần gửi tin nhắn bình thường để bắt đầu!"""
            zalo_bot.send_message(chat_id, response)
            return
            
        elif text.lower().startswith('/clear'):
            context_key = f"{chat_id}_{user_id}"
            if context_key in user_context:
                del user_context[context_key]
            response = "🗑️ Đã xóa lịch sử trò chuyện!"
            zalo_bot.send_message(chat_id, response)
            return
            
        elif text.lower().startswith('/token'):
            response = f"""🔐 **Thông tin Secret Token:**

✅ Secret Token được cấu hình: {"Có" if WEBHOOK_SECRET_TOKEN else "Không"}
📝 Token length: {len(WEBHOOK_SECRET_TOKEN) if WEBHOOK_SECRET_TOKEN else 0} ký tự
🔒 Token (ẩn): {"*" * min(len(WEBHOOK_SECRET_TOKEN), 8) if WEBHOOK_SECRET_TOKEN else "Chưa có"}

💡 Secret Token được sử dụng để xác minh tính xác thực của webhook requests từ Zalo."""
            zalo_bot.send_message(chat_id, response)
            return
            
        elif text.lower().startswith('/search '):
            search_query = text[8:]  # Bỏ "/search "
            if search_query.strip():
                logger.info(f"Force search for: {search_query}")
                zalo_bot.send_message(chat_id, "🔍 Đang tìm kiếm thông tin mới nhất...")
                if gemini_ai:
                    ai_response = gemini_ai.generate_response(search_query, None, use_search=True)
                    zalo_bot.send_message(chat_id, f"🔍 **Kết quả tìm kiếm:**\n\n{ai_response}")
                return
            else:
                zalo_bot.send_message(chat_id, "❌ Vui lòng nhập nội dung cần tìm kiếm. Ví dụ: /search giá Bitcoin hôm nay")
                return
        
        # Sử dụng Gemini AI để tạo phản hồi
        if gemini_ai:
            try:
                # Lấy context của user (kết hợp chat_id và user_id)
                context_key = f"{chat_id}_{user_id}"
                context = user_context.get(context_key, [])
                context_text = None
                if context:
                    # Lấy 3 tin nhắn gần nhất làm context
                    recent_context = context[-6:]  # 3 cặp hỏi-đáp
                    context_text = "\n".join([f"User: {ctx['user']}\nBot: {ctx['bot']}" for ctx in recent_context])
                
                # Kiểm tra xem có nên thông báo đang tìm kiếm không
                will_search = gemini_ai._should_use_search(text)
                if will_search:
                    zalo_bot.send_message(chat_id, "🔍 Đang tìm kiếm thông tin mới nhất...")
                
                # Tạo phản hồi với SDK mới
                ai_response = gemini_ai.generate_response(text, context_text)
                
                # Lưu context
                if context_key not in user_context:
                    user_context[context_key] = []
                
                user_context[context_key].append({
                    'user': text,
                    'bot': ai_response,
                    'timestamp': datetime.now().isoformat()
                })
                
                # Giữ chỉ 10 cặp hỏi-đáp gần nhất
                if len(user_context[context_key]) > 10:
                    user_context[context_key] = user_context[context_key][-10:]
                
                # Gửi phản hồi với prefix nếu đã tìm kiếm
                if will_search:
                    final_response = f"🔍 **Thông tin mới nhất:**\n\n{ai_response}"
                else:
                    final_response = ai_response
                    
                zalo_bot.send_message(chat_id, final_response)
                
            except Exception as e:
                logger.error(f"Error in AI processing: {e}")
                zalo_bot.send_message(chat_id, "⚠️ Đã xảy ra lỗi khi xử lý. Tôi sẽ thử trả lời đơn giản...")
                
                # Fallback response
                fallback_response = f"📝 Tôi đã nhận được: \"{text}\"\n\n💡 Bạn có thể thử:\n• Diễn đạt lại câu hỏi\n• Sử dụng /help để xem hướng dẫn\n• Dùng /search [nội dung] để tìm kiếm"
                zalo_bot.send_message(chat_id, fallback_response)
            
        else:
            # Fallback nếu không có Gemini
            response = f"📝 Tôi đã nhận được tin nhắn: {text}\n\n⚠️ Tính năng AI chưa được cấu hình. Vui lòng liên hệ admin để kích hoạt."
            zalo_bot.send_message(chat_id, response)
            
    except Exception as e:
        logger.error(f"Error handling message: {e}")

@app.route('/test-token', methods=['GET'])
def test_token():
    """Test Zalo Bot Token"""
    try:
        if not ZALO_BOT_TOKEN:
            return jsonify({"error": "ZALO_BOT_TOKEN not configured"}), 400
        
        if not zalo_bot:
            return jsonify({"error": "ZaloBot not initialized"}), 400
        
        # Test với getMe API
        result = zalo_bot.get_bot_info()
        
        return jsonify({
            "token_configured": True,
            "bot_info": result,
            "token_valid": result is not None and result.get('ok') == True,
            "secret_token_configured": bool(WEBHOOK_SECRET_TOKEN),
            "secret_token_length": len(WEBHOOK_SECRET_TOKEN) if WEBHOOK_SECRET_TOKEN else 0
        })
        
    except Exception as e:
        logger.error(f"Error testing token: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/setup-webhook', methods=['POST', 'GET'])
def setup_webhook():
    """Endpoint để thiết lập webhook với secret token"""
    try:
        logger.info("Setting up webhook with secret token...")
        
        if not ZALO_BOT_TOKEN:
            return jsonify({"error": "ZALO_BOT_TOKEN not configured", "success": False}), 400
            
        if not WEBHOOK_URL:
            return jsonify({"error": "WEBHOOK_URL not configured", "success": False}), 400
            
        if not WEBHOOK_SECRET_TOKEN:
            return jsonify({"error": "WEBHOOK_SECRET_TOKEN not configured", "success": False}), 400
        
        if not zalo_bot:
            return jsonify({"error": "ZaloBot not initialized", "success": False}), 400
        
        # Kiểm tra độ dài secret token
        if len(WEBHOOK_SECRET_TOKEN) < 8:
            return jsonify({
                "error": "WEBHOOK_SECRET_TOKEN must be at least 8 characters long", 
                "success": False,
                "current_length": len(WEBHOOK_SECRET_TOKEN)
            }), 400
        
        webhook_endpoint = WEBHOOK_URL + '/webhook'
        logger.info(f"Using webhook URL: {webhook_endpoint}")
        logger.info(f"Using secret token length: {len(WEBHOOK_SECRET_TOKEN)} characters")
        
        # Thiết lập webhook với secret token
        result = zalo_bot.set_webhook(webhook_endpoint, WEBHOOK_SECRET_TOKEN)
        logger.info(f"Webhook setup result: {result}")
        
        if result and result.get('ok') == True:
            return jsonify({
                "success": True,
                "webhook_url": webhook_endpoint,
                "secret_token_configured": True,
                "secret_token_length": len(WEBHOOK_SECRET_TOKEN),
                "zalo_response": result
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to setup webhook",
                "webhook_url": webhook_endpoint,
                "secret_token_length": len(WEBHOOK_SECRET_TOKEN),
                "zalo_response": result
            }), 500
            
    except Exception as e:
        logger.error(f"Error setting up webhook: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "webhook_url": WEBHOOK_URL + '/webhook' if WEBHOOK_URL else "Not configured",
            "secret_token_configured": bool(WEBHOOK_SECRET_TOKEN),
            "secret_token_length": len(WEBHOOK_SECRET_TOKEN) if WEBHOOK_SECRET_TOKEN else 0
        }), 500

@app.route('/generate-secret', methods=['POST'])
def generate_secret():
    """Endpoint để tạo secret token mới"""
    try:
        new_secret = secrets.token_urlsafe(16)  # Tạo secret 16 ký tự
        
        return jsonify({
            "success": True,
            "new_secret_token": new_secret,
            "length": len(new_secret),
            "message": "Vui lòng copy secret token này và set làm environment variable WEBHOOK_SECRET_TOKEN",
            "instructions": [
                "1. Copy secret token này",
                "2. Set environment variable: WEBHOOK_SECRET_TOKEN=" + new_secret,
                "3. Restart ứng dụng",
                "4. Gọi lại /setup-webhook để cập nhật"
            ]
        })
        
    except Exception as e:
        logger.error(f"Error generating secret: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    
    # Log thông tin cấu hình
    logger.info("🚀 Starting Zalo Bot with Gemini 2.5 Flash + Google Search + Secret Token")
    logger.info(f"Port: {port}")
    logger.info(f"Zalo Bot Token configured: {bool(ZALO_BOT_TOKEN)}")
    logger.info(f"Gemini API configured: {bool(GEMINI_API_KEY)}")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")
    logger.info(f"Secret Token configured: {bool(WEBHOOK_SECRET_TOKEN)}")
    logger.info(f"Secret Token length: {len(WEBHOOK_SECRET_TOKEN) if WEBHOOK_SECRET_TOKEN else 0} characters")
    logger.info(f"Bot API URL: {zalo_bot.base_url if zalo_bot else 'Not configured'}")
    logger.info("✨ Features: Zalo Bot API, Thinking, Google Search, Streaming responses, Webhook Security")
    
    app.run(host='0.0.0.0', port=port, debug=False)
