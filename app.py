from flask import Flask, request, render_template_string, redirect, url_for, jsonify
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
    # Try file first
    try:
        val = open("token.txt", "r").read().strip()
        print("⚙️ get_token(): using token.txt →", val[:10] + "…")
        return val
    except FileNotFoundError:
        val = os.environ.get("FB_SHORT_TOKEN", "")
        print("⚙️ get_token(): using FB_SHORT_TOKEN →", val[:10] + "…")
        return val

ACCESS_TOKEN = get_token()
PHONE_NUMBER_ID = "653311211196519"
VERIFY_TOKEN = "your_custom_verify_token"

# Refresh token every 45 days

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
            .message { margin: 10px 0; }
            .incoming { color: #000; }
            .outgoing { color: green; text-align: right; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h3>📱 Conversations</h3>
            {% for contact in contacts %}
                <div><a href="/chat?contact={{ contact }}">{{ contact }}</a></div>
            {% endfor %}
            <form method="POST" action="/new">
                <input name="new_number" placeholder="91XXXXXXXXXX" required />
                <button type="submit">New Chat</button>
            </form>
        </div>
        <div class="content">
            {% if selected %}
                <h3>Chat with {{ selected }}</h3>
                <div id="chatbox">
                    {% for sender, msg, direction, time in messages %}
                        <div class="message {{ direction }}">
                            <strong>{{ 'You' if direction=='outgoing' else sender }}:</strong> {{ msg }}<br>
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
            {% else %}
                <p>No conversation selected</p>
            {% endif %}
        </div>
    
        <script>
        window.addEventListener('DOMContentLoaded', () => {
            setInterval(async () => {
                alert('Polling...');
                const res = await fetch(`/messages?contact={{ selected }}`);
                const data = await res.json();
                const box = document.getElementById('chatbox');
                box.innerHTML = '';
                data.forEach(m => {
                    const div = document.createElement('div');
                    div.className = `message ${m.direction}`;
                    div.innerHTML = `<strong>${m.direction==='outgoing'?'You':m.from}:</strong> ${m.text}<br><small>${m.timestamp}</small>`;
                    box.appendChild(div);
                });
                box.scrollTop = box.scrollHeight;
            }, 3000);
        });
        </script>
    </body>
    </html>
    """

    return render_template_string(chat_template, contacts=contacts, selected=selected, messages=messages)

@app.route("/new", methods=["POST"])
def new_chat():
    number = normalize_number(request.form.get("new_number"))
    timestamp = datetime.datetime.now().isoformat()
    c.execute("INSERT INTO messages (sender, message, direction, timestamp) VALUES (?, ?, ?, ?)",
              (number, "", "outgoing", timestamp))
    conn.commit()
    return redirect(url_for("chat", contact=number))

@app.route("/send", methods=["POST"])
def send_message():
    to = normalize_number(request.form.get("to"))
    message = request.form.get("message")
    mode = request.form.get("mode")
    timestamp = datetime.datetime.now().isoformat()

    # Always fetch the latest token
    token = get_token()
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Build payload
    if mode == "template":
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": "hello_world",
                "language": {"code": "en_US"}
            }
        }
    else:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message}
        }

    # First attempt
    response = requests.post(url, headers=headers, json=payload)

    # If token expired (OAuthException 190), refresh and retry once
    if response.status_code == 400 and '"code":190' in response.text:
        exch = requests.get(
            f"https://graph.facebook.com/v19.0/oauth/access_token"
            f"?grant_type=fb_exchange_token"
            f"&client_id={os.environ['FB_APP_ID']}"
            f"&client_secret={os.environ['FB_APP_SECRET']}"
            f"&fb_exchange_token={token}"
        ).json()
        if "access_token" in exch:
            with open("token.txt", "w") as f:
                f.write(exch["access_token"])
            token = exch["access_token"]
            headers["Authorization"] = f"Bearer {token}"
            response = requests.post(url, headers=headers, json=payload)

    print("Meta API response:", response.text)

    # Store outgoing in DB
    c.execute(
        "INSERT INTO messages (sender, message, direction, timestamp) VALUES (?, ?, ?, ?)",
        (to, message, "outgoing", timestamp)
    )
    conn.commit()

    return redirect(url_for("chat", contact=to))

# preserve the rest of the file

if __name__ == "__main__":
    threading.Thread(target=refresh_token_every_45_days, daemon=True).start()
    app.run(debug=True, port=5000)
