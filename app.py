from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
import requests
import datetime
import re
import json
import os
import threading
import time

app = Flask(__name__)

def get_token():
    try:
        with open("token.txt", "r") as f:
            return f.read().strip()
    except:
        return os.environ.get("FB_SHORT_TOKEN")

ACCESS_TOKEN = get_token()
PHONE_NUMBER_ID = "653311211196519"
VERIFY_TOKEN = "your_custom_verify_token"

def refresh_token_every_45_days():
    while True:
        try:
            url = f"https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id={os.environ['FB_APP_ID']}&client_secret={os.environ['FB_APP_SECRET']}&fb_exchange_token={os.environ['FB_SHORT_TOKEN']}"
            response = requests.get(url)
            data = response.json()
            if 'access_token' in data:
                with open("token.txt", "w") as f:
                    f.write(data["access_token"])
                print("🔁 Refreshed access token.")
            else:
                print("❌ Failed to refresh token:", data)
        except Exception as e:
            print("❌ Exception during token refresh:", str(e))
        time.sleep(45 * 24 * 60 * 60)

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
        print("💬 Incoming Webhook JSON:", json.dumps(data, indent=2))
        try:
            entry = data.get("entry", [])[0]
            changes = entry.get("changes", [])[0]
            value = changes.get("value", {})
            messages = value.get("messages")

            if messages:
                msg = messages[0]
                sender_raw = msg.get("from")
                sender = normalize_number(sender_raw)
                text = msg.get("text", {}).get("body", "")
                timestamp = datetime.datetime.now().isoformat()

                if sender and text:
                    c.execute("INSERT INTO messages (sender, message, direction, timestamp) VALUES (?, ?, ?, ?)",
                              (sender, text, "incoming", timestamp))
                    conn.commit()
                    print(f"✅ DB insert done: {sender} → {text}")
                else:
                    print("⚠️ Message missing sender or text. Not inserted.")
            else:
                print("⚠️ No messages key in webhook payload.")
        except Exception as e:
            print("❌ Error in processing webhook message:", str(e))

        return "OK", 200

def normalize_number(number):
    return re.sub(r'\D', '', number)

@app.route("/chat")
def chat():
    c.execute("SELECT DISTINCT sender FROM messages ORDER BY id DESC")
    contacts = [row[0] for row in c.fetchall()]
    selected = normalize_number(request.args.get("contact")) if request.args.get("contact") else (contacts[0] if contacts else "")

    if selected:
        c.execute("SELECT sender, message, direction, timestamp FROM messages WHERE sender=? ORDER BY id ASC", (selected,))
        messages = c.fetchall()
    else:
        messages = []

    chat_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WhatsApp Chat UI</title>
        <style>
            body { font-family: Arial; display: flex; height: 100vh; margin: 0; }
            .sidebar { width: 30%; background: #f1f1f1; padding: 20px; overflow-y: auto; border-right: 1px solid #ccc; }
            .content { width: 70%; padding: 20px; overflow-y: auto; }
            .contact { padding: 10px; border-bottom: 1px solid #ddd; }
            .message { margin: 10px 0; }
            .incoming { color: #000; }
            .outgoing { color: green; text-align: right; }
            form { display: flex; flex-direction: column; gap: 10px; margin-top: 20px; }
            input, select { padding: 10px; font-size: 16px; }
            button { padding: 10px 20px; }
            .newchat-form { margin-top: 20px; }
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
            <div class="newchat-form">
                <form method="POST" action="/new">
                    <input name="new_number" placeholder="91XXXXXXXXXX" required />
                    <button type="submit">New Chat</button>
                </form>
            </div>
        </div>
        <div class="content">
            {% if selected %}
                <h3>Chat with {{ selected }}</h3>
                <div id="chatbox">
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
                    <select name="mode">
                        <option value="text">Text Message</option>
                        <option value="template">Send Template</option>
                    </select>
                    <button type="submit">Send</button>
                </form>
                <script>
                    async function pollMessages() {
                        try {
                            const res = await fetch(`/messages?contact={{ selected }}`);
                            const data = await res.json();
                            const box = document.getElementById("chatbox");
                            box.innerHTML = "";
                            data.forEach(msg => {
                                const div = document.createElement("div");
                                div.className = `message ${msg.direction}`;
                                div.innerHTML = `<strong>${msg.direction === 'outgoing' ? 'You' : msg.from}:</strong> ${msg.text}<br><small>${msg.timestamp}</small>`;
                                box.appendChild(div);
                            });
                            box.scrollTop = box.scrollHeight;
                        } catch (err) {
                            console.error("Polling error:", err);
                        }
                    }
                    setInterval(pollMessages, 3000);
                </script>
            {% else %}
                <p>No conversation selected</p>
            {% endif %}
        </div>
    </body>
    </html>
    """
    return render_template_string(chat_template, contacts=contacts, selected=selected, messages=messages)

@app.route("/messages")
def get_messages():
    contact = normalize_number(request.args.get("contact", ""))
    if not contact:
        return jsonify([])
    c.execute("SELECT sender, message, direction, timestamp FROM messages WHERE sender=? ORDER BY id ASC", (contact,))
    rows = c.fetchall()
    messages = [
        {"from": r[0], "text": r[1], "direction": r[2], "timestamp": r[3]} for r in rows
    ]
    return jsonify(messages)

@app.route("/messages")
def get_messages():
    contact = normalize_number(request.args.get("contact", ""))
    if not contact:
        return jsonify([])
    c.execute("SELECT sender, message, direction, timestamp FROM messages WHERE sender=? ORDER BY id ASC", (contact,))
    rows = c.fetchall()
    messages = [
        {"from": r[0], "text": r[1], "direction": r[2], "timestamp": r[3]} for r in rows
    ]
    return jsonify(messages)


if __name__ == '__main__':
    app.run(debug=True)
