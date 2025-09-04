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
    
    def generate_response_async(self, message, context=None, use_search=False):
        """Async wrapper cho generate_response"""
        return self.executor.submit(self.generate_response, message, context, use_search)

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
            response = """🤖 Xin chào! Tôi là Bot AI được trang bị Gemini 2.5 Flash với khả năng:

✨ Trả lời câu hỏi thông minh
🔍 Tìm kiếm thông tin mới nhất trên Google  
💭 Suy nghĩ logic và phân tích sâu
🗣️ Trò chuyện tự nhiên bằng tiếng Việt

Hãy gửi bất kỳ câu hỏi nào bạn muốn!"""
            zalo_bot.send_message(user_id, response)
            return
            
        elif message.lower().startswith('/help'):
            response = """
📋 Danh sách lệnh:
/start - Khởi động bot
/help - Hiển thị trợ giúp
/clear - Xóa lịch sử trò chuyện
/search [câu hỏi] - Tìm kiếm thông tin mới nhất

🤖 Tính năng AI mới:
• Gemini 2.5 Flash - Model mới nhất
• Tìm kiếm Google tự động
• Khả năng suy nghĩ logic (thinking)
• Trả lời dựa trên thông tin real-time
• Nhớ ngữ cảnh cuộc trò chuyện

🔍 Tự động tìm kiếm khi:
• Hỏi tin tức, thời tiết
• Hỏi giá cả, tỷ giá
• Cần thông tin mới nhất
• Hỏi về sự kiện hiện tại

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
            
        elif message.lower().startswith('/search '):
            search_query = message[8:]  # Bỏ "/search "
            if search_query.strip():
                logger.info(f"Force search for: {search_query}")
                zalo_bot.send_message(user_id, "🔍 Đang tìm kiếm thông tin mới nhất...")
                if gemini_ai:
                    ai_response = gemini_ai.generate_response(search_query, None, use_search=True)
                    zalo_bot.send_message(user_id, f"🔍 **Kết quả tìm kiếm:**\n\n{ai_response}")
                return
            else:
                zalo_bot.send_message(user_id, "❌ Vui lòng nhập nội dung cần tìm kiếm. Ví dụ: /search giá Bitcoin hôm nay")
                return
        
        # Sử dụng Gemini AI để tạo phản hồi
        if gemini_ai:
            try:
                # Lấy context của user
                context = user_context.get(user_id, [])
                context_text = None
                if context:
                    # Lấy 3 tin nhắn gần nhất làm context
                    recent_context = context[-6:]  # 3 cặp hỏi-đáp
                    context_text = "\n".join([f"User: {ctx['user']}\nBot: {ctx['bot']}" for ctx in recent_context])
                
                # Kiểm tra xem có nên thông báo đang tìm kiếm không
                will_search = gemini_ai._should_use_search(message)
                if will_search:
                    zalo_bot.send_message(user_id, "🔍 Đang tìm kiếm thông tin mới nhất...")
                
                # Tạo phản hồi với SDK mới
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
                
                # Gửi phản hồi với prefix nếu đã tìm kiếm
                if will_search:
                    final_response = f"🔍 **Thông tin mới nhất:**\n\n{ai_response}"
                else:
                    final_response = ai_response
                    
                zalo_bot.send_message(user_id, final_response)
                
            except Exception as e:
                logger.error(f"Error in AI processing: {e}")
                zalo_bot.send_message(user_id, "⚠️ Đã xảy ra lỗi khi xử lý. Tôi sẽ thử trả lời đơn giản...")
                
                # Fallback response
                fallback_response = f"📝 Tôi đã nhận được: \"{message}\"\n\n💡 Bạn có thể thử:\n• Diễn đạt lại câu hỏi\n• Sử dụng /help để xem hướng dẫn\n• Dùng /search [nội dung] để tìm kiếm"
                zalo_bot.send_message(user_id, fallback_response)
            
        else:
            # Fallback nếu không có Gemini
            response = f"📝 Tôi đã nhận được tin nhắn: {message}\n\n⚠️ Tính năng AI chưa được cấu hình. Vui lòng liên hệ admin để kích hoạt."
            zalo_bot.send_message(user_id, response)
            
    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        zalo_bot.send_message(user_id, "❌ Xin lỗi, đã xảy ra lỗi khi xử lý tin nhắn. Vui lòng thử lại!")

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
        logger.info("Setting up webhook...")
        
        if not ZALO_BOT_TOKEN:
            return jsonify({"error": "ZALO_BOT_TOKEN not configured", "success": False}), 400
            
        if not WEBHOOK_URL:
            return jsonify({"error": "WEBHOOK_URL not configured", "success": False}), 400
        
        logger.info(f"Using webhook URL: {WEBHOOK_URL}")
        result = zalo_bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook setup result: {result}")
        
        if result:
            return jsonify({
                "success": True,
                "webhook_url": WEBHOOK_URL,
                "zalo_response": result
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to setup webhook",
                "webhook_url": WEBHOOK_URL
            }), 500
            
    except Exception as e:
        logger.error(f"Error setting up webhook: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "webhook_url": WEBHOOK_URL if WEBHOOK_URL else "Not configured"
        }), 500

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
