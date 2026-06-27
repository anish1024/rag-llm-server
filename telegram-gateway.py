import os
import requests
from pydantic import BaseModel
from flask import Flask, request, jsonify

app = Flask(__name__)



##### Water Dispenser Section 

TELEGRAM_TOKEN = "8488173380:AAFh31bZqPyJHo0Z7ut_-8is16byLrw8vx0" #  os.getenv("TELEGRAM_BOT_TOKEN")  # Set in .env
TELEGRAM_CHAT_ID = "8359564001" # os.getenv("TELEGRAM_CHAT_ID")  # Your chat/group ID

class TelegramMsg(BaseModel):
    message: str

@app.post("/telegram/send")
async def send_telegram(msg: TelegramMsg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return {"error": "Telegram env vars missing"}
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"🚰 Dispenser: {msg.message}"
    }
    resp = requests.post(url, json=data)
    return {"status": resp.json()}

@app.route('/send', methods=['POST'])
def send_telegram_msg():  # SYNC, no args/return complex
    try:
        data = request.get_json()
        message = data.get('message', 'No message')
        
        url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
        resp = requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': f'🚰 Dispenser: {message}'
        })
        return jsonify({'status': 'sent', 'response': resp.json()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    return {'status': 'OK', 'telegram_ready': bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)}

######################################

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "anibot")

#RAG_CHAT_URL = os.getenv("RAG_CHAT_URL", "http://rag-agents:8000/rag")
RAG_CHAT_URL = "http://rag-agents:8000/chat"
RAG_IMPORT_URL = os.getenv("RAG_IMPORT_URL", "http://rag-tool-server:9000/import")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

def send_message(chat_id, text):
    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000]},
        timeout=30,
    )

def download_telegram_file(file_id, dest_path):
    # 1) getFile
    r = requests.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id}, timeout=30)
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    # 2) download file
    url = f"{FILE_API}/{file_path}"
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
    return dest_path

@app.post(f"/telegram/{WEBHOOK_SECRET}")
def telegram_webhook():
    update = request.get_json()
    print(f"[telegram_gateway] >>> incoming mesg : {update}", flush=True)
    if "message" not in update:
        return "ignored", 200

    msg = update["message"]
    chat_id = msg["chat"]["id"]

    # 1) Document upload
    if "document" in msg:
        doc = msg["document"]
        file_id = doc["file_id"]
        filename = doc.get("file_name", file_id)
        local_path = f"/data/uploads/{chat_id}/{filename}"

        try:
            download_telegram_file(file_id, local_path)
            resp = requests.post(
                RAG_IMPORT_URL,
                json={"user_id": str(chat_id), "path": local_path, "type": "document"},
                timeout=120,
            )
            ok = resp.json().get("ok", True)
            if ok:
                send_message(chat_id, f"📄 Imported '{filename}' into your RAG wiki.")
            else:
                send_message(chat_id, f"Import failed: {resp.text}")
        except Exception as e:
            send_message(chat_id, f"Error handling document: {e}")
        return "ok", 200

    # 2) Image upload
    if "photo" in msg:
        photo = msg["photo"][-1]  # highest resolution
        file_id = photo["file_id"]
        filename = f"{file_id}.jpg"
        local_path = f"/data/uploads/{chat_id}/{filename}"

        try:
            download_telegram_file(file_id, local_path)
            resp = requests.post(
                RAG_IMPORT_URL,
                json={"user_id": str(chat_id), "path": local_path, "type": "image"},
                timeout=120,
            )
            ok = resp.json().get("ok", True)
            if ok:
                send_message(chat_id, "🖼 Imported image into your RAG wiki.")
            else:
                send_message(chat_id, f"Image import failed: {resp.text}")
        except Exception as e:
            send_message(chat_id, f"Error handling image: {e}")
        return "ok", 200

    # 3) Text → RAG agent
    if "text" in msg:
        text = msg["text"]
        try:
            #payload = {"question": text, "doc_type": null}
            payload = {"messages":[{"role":"user", "content":text}]}
            print(f"[telegram_gateway] !! payload !! => '{payload}'", flush=True)

            rag_resp = requests.post(
                RAG_CHAT_URL,
                json=payload,
                timeout=1200,
            )
            # answer = rag_resp.json().get("answer", "Sorry, I couldn't generate a reply.")
            answer = rag_resp.json()
            print(f"[telegram_gateway] !! LLM response !! <= '{answer}'", flush=True)
            # 1. First, check if the structure has a "choices" list (New Remote Qwen API format)
            choices = answer.get("choices")
            if choices and isinstance(choices, list) and len(choices) > 0:
                # Safely dive into choices[0] -> "message" -> "content"
                content = choices[0].get("message", {}).get("content")
                print(f"[telegram_gateway] !! LLM choice !! <= '{content}'", flush=True)
            else:
                # 2. Fallback to the previous direct structure (Ollama API format)
                content = answer.get("message", {}).get("content")
                print(f"[telegram_gateway] !! LLM fallback !! <= '{content}'", flush=True)
            if content is not None:
                content = content.strip()
            # 3. Assign final value, defaulting to an error string if neither matched
            answer = content if content is not None else "Sorry, I had an error."
        except Exception as e:
            answer = f"Backend error talking to the RAG agent.: {e}"
        send_message(chat_id, answer)
        return "ok", 200

    return "ignored", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
