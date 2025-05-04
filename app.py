from flask import Flask, request, jsonify, render_template_string
import requests

app = Flask(__name__)

# Store messages in memory for now (simple demo)
chat_history = []

# Replace with your real values
ACCESS_TOKEN = "<YOUR_LONG_LIVED_ACCESS_TOKEN>"
PHONE_NUMBER_ID = "<YOUR_PHONE_NUMBER_ID>"

VERIFY_TOKEN = "your_custom_verify_token"

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403

    if request.method == "POST":
        data = request.get_json()
        try:
            entry = data["entry"][0]
            changes = entry["changes"][0]
            value = changes["value"]
            messages = value.get("messages")

            if messages:
                msg = messages[0]
                sender = msg.get("from")
                text = msg.get("text", {}).get("body", "")

                chat_history.append({"from": sender, "text": text})

                print(f"📩 Message from {sender}: {text}")
        except Exception as e:
            print("Error in processing message:", e)

        return "OK", 200

@app.route("/chat", methods=["GET"])
def chat_ui():
    chat_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WhatsApp Chat</title>
        <style>
            body { font-family: Arial; padding: 20px; background: #f4f4f4; }
            .chat-box { max-width: 600px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; }
            .message { padding: 8px; border-bottom: 1px solid #eee; }
            .form-row { display: flex; margin-top: 20px; }
            input { flex: 1; padding: 10px; font-size: 16px; }
            button { padding: 10px 20px; }
        </style>
    </head>
    <body>
        <div class="chat-box">
            <h2>📱 WhatsApp Chat</h2>
            <div id="chat">
                {% for msg in chat_history %}
                    <div class="message"><strong>{{ msg.from }}:</strong> {{ msg.text }}</div>
                {% endfor %}
            </div>
            <form class="form-row" method="POST" action="/send">
                <input name="to" placeholder="Phone Number (e.g. 91XXXXXXXXXX)" required />
                <input name="message" placeholder="Your message" required />
                <button type="submit">Send</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(chat_html, chat_history=chat_history)

@app.route("/send", methods=["POST"])
def send_message():
    to = request.form.get("to")
    message = request.form.get("message")

    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }

    r = requests.post(url, headers=headers, json=payload)
    print("Sent message to", to, ":", message)
    return "<script>window.location.href='/chat';</script>"

if __name__ == "__main__":
    app.run(debug=True, port=5000)
