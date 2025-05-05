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
    try:
        val = open("token.txt", "r").read().strip()
        print("⚙️ get_token(): using token.txt →", val[:10] + "…")
        return val
    except Exception:
        val = os.environ.get("FB_SHORT_TOKEN", "")
        print("⚙️ get_token(): fallback to FB_SHORT_TOKEN →", val[:10] + "…")
        return val

PHONE_NUMBER_ID = "653311211196519"
VERIFY_TOKEN = "your_custom_verify_token"

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

    data = request.get_json()
    print("💬 Incoming Webhook JSON:", json.dumps(data, indent=2))
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages")
        if messages:
            msg = messages[0]
            sender = normalize_number(msg.get("from"))
            text = msg.get("text", {}).get("body", "")
            ts = datetime.datetime.now().isoformat()
            if sender and text:
                c.execute(
                    "INSERT INTO messages (sender, message, direction, timestamp) VALUES (?,?,?,?)",
                    (sender, text, "incoming", ts)
                )
                conn.commit()
                print(f"✅ DB insert done: {sender} → {text}")
            else:
                print("⚠️ Message missing sender or text. Not inserted.")
        else:
            print("⚠️ No messages key in webhook payload.")
    except Exception as e:
        print("❌ Error in processing webhook message:", e)
    return "OK", 200

@app.route("/chat")
def chat():
    c.execute("SELECT DISTINCT sender FROM messages ORDER BY id DESC")
    contacts = [r[0] for r in c.fetchall()]
    selected = normalize_number(request.args.get("contact")) if request.args.get("contact") else (contacts[0] if contacts else "")
    if selected:
        c.execute(
            "SELECT sender, message, direction, timestamp FROM messages WHERE sender=? ORDER BY id ASC",
            (selected,)
        )
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
            {% for ctc in contacts %}
                <div class="contact"><a href="/chat?contact={{ ctc }}">{{ ctc }}</a></div>
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
                    {% for s, m, d, t in messages %}
                        <div class="message {{ d }}">
                            <strong>{{ 'You' if d=='outgoing' else s }}:</strong> {{ m }}<br>
                            <small>{{ t }}</small>
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
        window.addEventListener("DOMContentLoaded", () => {
            setInterval(async () => {
                console.log("Polling for", "{{ selected }}");
                try {
                    const res = await fetch(`/messages?contact={{ selected }}`);
                    console.log("Fetch status:", res.status);
                    const data = await res.json();
                    console.log("Fetched:", data);
                    const box = document.getElementById("chatbox");
                    box.innerHTML = "";
                    data.forEach(m => {
                        const div = document.createElement("div");
                        div.className = `message ${m.direction}`;
                        div.innerHTML = `<strong>${m.direction==='outgoing'?'You':m.from}:</strong> ${m.text}<br><small>${m.timestamp}</small>`;
                        box.appendChild(div);
                    });
                    box.scrollTop = box.scrollHeight;
                } catch (err) {
                    console.error("Polling error:", err);
                }
            }, 3000);
        });
        </script>
    </body>
    </html>
    """
    return render_template_string(chat_template, contacts=contacts, selected=selected, messages=messages)

@app.route("/new", methods=["POST"])
def new_chat():
    num = normalize_number(request.form.get("new_number"))
    ts = datetime.datetime.now().isoformat()
    c.execute("INSERT INTO messages (sender, message, direction, timestamp) VALUES (?,?,?,?)", (num, "", "outgoing", ts))
    conn.commit()
    return redirect(url_for("chat", contact=num))

@app.route("/send", methods=["POST"])
def send_message():
    to = normalize_number(request.form.get("to"))
    message = request.form.get("message")
    mode = request.form.get("mode")
    ts = datetime.datetime.now().isoformat()
    token = get_token()
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization":f"Bearer {token}","Content-Type":"application/json"}
    if mode=="template":
        payload={"messaging_product":"whatsapp","to":to,"type":"template","template":{"name":"hello_world","language":{"code":"en_US"}}}
    else:
        payload={"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":message}}
    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code==400 and '"code":190' in resp.text:
        exch = requests.get(f"https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id={os.environ['FB_APP_ID']}&client_secret={os.environ['FB_APP_SECRET']}&fb_exchange_token={token}").json()
        print("🔄 Token exchange response:", exch)
        if 'access_token' in exch:
            open("token.txt","w").write(exch['access_token'])
            token=exch['access_token']
            headers['Authorization']=f"Bearer {token}"
            resp = requests.post(url, headers=headers, json=payload)
    print("Meta API response:", resp.text)
    c.execute("INSERT INTO messages (sender, message, direction, timestamp) VALUES (?,?,?,?)", (to, message, "outgoing", ts))
    conn.commit()
    return redirect(url_for("chat", contact=to))

def normalize_number(n): return re.sub(r'\D','',n or '')

if __name__ == "__main__":
    app.run(debug=True, port=5000)
