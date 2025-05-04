from flask import Flask, request, render_template_string, redirect, url_for
import sqlite3
import requests
import datetime

app = Flask(__name__)

# Replace with your actual token and number
ACCESS_TOKEN = "<YOUR_LONG_LIVED_ACCESS_TOKEN>"
PHONE_NUMBER_ID = "<YOUR_PHONE_NUMBER_ID>"
VERIFY_TOKEN = "your_custom_verify_token"

# Initialize DB
conn = sqlite3.connect("messages.db", check_same_thread=False)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT,
    message TEXT,
    direction TEXT,
    timestamp TEXT
)''')
conn.commit()

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
                timestamp = datetime.datetime.now().isoformat()

                c.execute("INSERT INTO messages (sender, message, direction, timestamp) VALUES (?, ?, ?, ?)",
                          (sender, text, "incoming", timestamp))
                conn.commit()

                print(f"📩 Message from {sender}: {text}")
        except Exception as e:
            print("Error in processing message:", e)

        return "OK", 200

@app.route("/chat")
def chat():
    c.execute("SELECT DISTINCT sender FROM messages ORDER BY id DESC")
    contacts = [row[0] for row in c.fetchall()]
    selected = request.args.get("contact") or (contacts[0] if contacts else "")

    c.execute("SELECT sender, message, direction, timestamp FROM messages WHERE sender=? ORDER BY id ASC", (selected,))
    messages = c.fetchall()

    chat_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WhatsApp Chat UI</title>
        <style>
            body { font-family: Arial; display: flex; height: 100vh; margin: 0; }
            .sidebar { width: 30%; background: #f1f1f1; padding: 20px; overflow-y: auto; border-right: 1px solid #ccc; }
            .content { width: 70%; padding: 20px; }
            .contact { padding: 10px; border-bottom: 1px solid #ddd; }
            .message { margin: 10px 0; }
            .incoming { color: #000; }
            .outgoing { color: green; text-align: right; }
            form { display: flex; margin-top: 20px; }
            input[name=message] { flex: 1; padding: 10px; font-size: 16px; }
            button { padding: 10px 20px; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h3>📱 Conversations</h3>
            {% for contact in contacts %}
                <div class="contact">
                    <a href="/chat?contact={{ contact }}">{{ contact }}</a>
                </div>
            {% endfor %}
        </div>
        <div class="content">
            <h3>Chat with {{ selected }}</h3>
            <div>
                {% for sender, msg, direction, time in messages %}
                    <div class="message {{ direction }}">
                        <strong>{{ 'You' if direction == 'outgoing' else sender }}:</strong> {{ msg }}<br>
                        <small>{{ time }}</small>
                    </div>
                {% endfor %}
            </div>
            <form method="POST" action="/send">
                <input type="hidden" name="to" value="{{ selected }}" />
                <input name="message" placeholder="Your message" required />
                <button type="submit">Send</button>
            </form>
        </div>
    </body>
    </html>
    """
    return render_template_string(chat_template, contacts=contacts, selected=selected, messages=messages)

@app.route("/send", methods=["POST"])
def send_message():
    to = request.form.get("to")
    message = request.form.get("message")
    timestamp = datetime.datetime.now().isoformat()

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
    print("✅ Sent message to", to, ":", message)

    c.execute("INSERT INTO messages (sender, message, direction, timestamp) VALUES (?, ?, ?, ?)",
              (to, message, "outgoing", timestamp))
    conn.commit()

    return redirect(url_for("chat", contact=to))

if __name__ == "__main__":
    app.run(debug=True, port=5000)
