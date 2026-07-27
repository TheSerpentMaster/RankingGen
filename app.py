import os
import secrets
import sqlite3
import subprocess
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path
from shutil import which
from typing import Dict, List

from flask import Flask, jsonify, redirect, render_template_string, request, send_file, session, url_for
from PIL import Image, ImageDraw, ImageFont
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.config["UPLOAD_FOLDER"] = os.path.join(os.getcwd(), "uploads")
app.config["PYTHON"] = os.environ.get("PYTHON_BIN", os.sys.executable)
Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

DB_PATH = os.path.join(os.getcwd(), "rankingen.sqlite3")


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            topic TEXT NOT NULL,
            status TEXT NOT NULL,
            output_path TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


def build_ranking_beats(topic: str) -> List[Dict[str, str]]:
    clean_topic = (topic or "viral ranking").strip() or "viral ranking"
    base = clean_topic.lower()
    items = []
    for rank in range(1, 6):
        title = f"{rank}. {clean_topic.title()} #{rank}"
        if rank == 1:
            title = f"1. The Best {clean_topic.title()}"
        elif rank == 5:
            title = f"5. The Wildcard {clean_topic.title()}"
        items.append(
            {
                "rank": str(rank),
                "title": title,
                "description": f"A fast-paced highlight for {clean_topic} tuned for short-form engagement.",
                "hook": f"Why this {base} made the cut.",
            }
        )
    return items


def _draw_slide(draw: ImageDraw.ImageDraw, beat: Dict[str, str], topic: str, total: int) -> None:
  width, height = 1080, 1920
  # base background
  draw.rectangle((0, 0, width, height), fill=(12, 14, 28))
  # subtle horizontal bands for depth
  for y in range(0, height, 28):
    band = 6 if (y // 28) % 2 == 0 else 4
    draw.rectangle((0, y, width, y + band), fill=(18 + (y % 30), 28 + (y % 40), 56))

  # locate a bold system font if available
  def find_font(names, size):
    for n in names:
      try:
        return ImageFont.truetype(n, size)
      except Exception:
        continue
    return ImageFont.load_default()

  title_font = find_font(["/Library/Fonts/Impact.ttf", "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"], 58)
  rank_font = find_font(["/Library/Fonts/Impact.ttf", "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"], 84)
  body_font = find_font(["/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"], 42)
  hook_font = find_font(["/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"], 36)

  # Top centered title bar (semi-opaque)
  title = f"Top {total} {topic}"
  bar_h = 140
  draw.rectangle((0, 0, width, bar_h), fill=(0, 0, 0, 200))
  def text_size(text, font):
    try:
      bbox = draw.textbbox((0, 0), text, font=font)
      return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
      try:
        return font.getsize(text)
      except Exception:
        return (0, 0)

  w, h = text_size(title, title_font)
  draw.text(((width - w) / 2, (bar_h - h) / 2 + 6), title, font=title_font, fill=(255, 235, 59))

  # Left-side numbered badge
  badge_x = 60
  badge_y = 420
  badge_r = 60
  colors = [(239, 68, 68), (59, 130, 246), (250, 204, 21), (107, 114, 128), (99, 102, 241)]
  badge_color = colors[(int(beat.get("rank", "1")) - 1) % len(colors)]
  draw.ellipse((badge_x, badge_y, badge_x + badge_r * 2, badge_y + badge_r * 2), fill=(0, 0, 0, 200), outline=badge_color)
  rn_w, rn_h = text_size(beat["rank"], rank_font)
  draw.text((badge_x + badge_r - rn_w / 2, badge_y + badge_r - rn_h / 2 - 6), beat["rank"], font=rank_font, fill=(255, 255, 255))

  # Main headline (big, wrapped, fit-to-width)
  headline = f"{beat['title']}"
  max_w = width - (badge_x + badge_r * 2) - 140
  # reduce font size until it fits into max_w
  hf_size = 78
  hf = find_font(["/Library/Fonts/Impact.ttf", "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"], hf_size)
  while hf_size > 28:
    w, _ = text_size(headline, hf)
    if w <= max_w:
      break
    hf_size -= 4
    hf = find_font(["/Library/Fonts/Impact.ttf", "/Library/Fonts/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"], hf_size)

  # allow multi-line breakpoints
  import textwrap as _tw
  lines = _tw.wrap(headline, width=20)
  text_x = badge_x + badge_r * 2 + 40
  text_y = badge_y + 8
  for i, line in enumerate(lines[:3]):
    draw.text((text_x, text_y + i * (hf_size + 6)), line, font=hf, fill=(255, 255, 255))

  # description
  desc_lines = textwrap.wrap(beat.get("description", ""), width=36)
  for i, line in enumerate(desc_lines[:4]):
    draw.text((text_x, text_y + 220 + i * 46), line, font=body_font, fill=(230, 230, 230))

  # hook / callout
  draw.text((text_x, text_y + 420), beat.get("hook", ""), font=hook_font, fill=(167, 139, 250))

  # footer small note
  footer = "Shorts • 9:16 • auto-generated"
  fw, fh = text_size(footer, body_font)
  draw.text(((width - fw) / 2, height - 140), footer, font=body_font, fill=(180, 220, 230))


def build_simple_video(topic: str, output_path: str) -> str:
  beats = build_ranking_beats(topic)
  temp_dir = tempfile.mkdtemp(prefix="rank-", dir=app.config["UPLOAD_FOLDER"])
  slide_paths = []

  ffmpeg = which("ffmpeg")
  if not ffmpeg:
    raise RuntimeError("ffmpeg is required for MP4 rendering")

  # create image slides and per-slide mp4 with simple fades
  for index, beat in enumerate(beats):
    width, height = 1080, 1920
    image = Image.new("RGB", (width, height), (10, 10, 24))
    draw = ImageDraw.Draw(image)
    _draw_slide(draw, beat, topic, len(beats))
    image_path = os.path.join(temp_dir, f"frame_{index}.png")
    image.save(image_path)

    slide_mp4 = os.path.join(temp_dir, f"slide_{index}.mp4")
    # 6s per slide with 0.5s fade in/out
    vf = "scale=1080:1920,format=yuv420p,fade=t=in:st=0:d=0.5,fade=t=out:st=5.5:d=0.5"
    cmd = [
      ffmpeg,
      "-y",
      "-loop",
      "1",
      "-i",
      image_path,
      "-t",
      "6",
      "-vf",
      vf,
      "-c:v",
      "libx264",
      "-pix_fmt",
      "yuv420p",
      "-preset",
      "veryfast",
      slide_mp4,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    slide_paths.append(slide_mp4)

  # write concat list for ffmpeg
  concat_list = os.path.join(temp_dir, "slides.txt")
  with open(concat_list, "w", encoding="utf-8") as fh:
    for p in slide_paths:
      fh.write(f"file '{p}'\n")

  final_cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", output_path]
  subprocess.run(final_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
  return output_path


@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template_string(HTML_APP)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        conn.close()
        if row and check_password_hash(row[0], password):
            session["user"] = username
            return redirect(url_for("index"))
        return render_template_string(LOGIN_HTML, error="Invalid credentials")
    return render_template_string(LOGIN_HTML)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            return render_template_string(SIGNUP_HTML, error="Please provide both fields")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), datetime.utcnow().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template_string(SIGNUP_HTML, error="Username already exists")
        conn.close()
        session["user"] = username
        return redirect(url_for("index"))
    return render_template_string(SIGNUP_HTML)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
  if request.method == "POST":
    payload = request.get_json(silent=True) or {}
    app.config["OPENAI_API_KEY"] = payload.get("openai_api_key", "")
    app.config["NVIDIA_NIM_KEY"] = payload.get("nvidia_nim_key", "")
    app.config["NVIDIA_NIM_ENDPOINT"] = payload.get("nvidia_nim_endpoint", "")
    app.config["YOUTUBE_CHANNEL_ID"] = payload.get("youtube_channel_id", "")
    return jsonify({"ok": True})

  return jsonify({
    "openai_api_key": app.config.get("OPENAI_API_KEY", ""),
    "nvidia_nim_key": app.config.get("NVIDIA_NIM_KEY", ""),
    "nvidia_nim_endpoint": app.config.get("NVIDIA_NIM_ENDPOINT", ""),
    "youtube_channel_id": app.config.get("YOUTUBE_CHANNEL_ID", ""),
  })


@app.route("/api/history")
def api_history():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT topic, status, output_path, created_at FROM jobs WHERE username = ? ORDER BY id DESC LIMIT 8", (session["user"],))
    rows = cur.fetchall()
    conn.close()
    items = []
    for topic, status, output_path, created_at in rows:
        filename = os.path.basename(output_path) if output_path else ""
        items.append({"topic": topic, "status": status, "filename": filename, "created_at": created_at})
    return jsonify(items)


@app.route("/api/generate", methods=["POST"])
def api_generate():
    if "user" not in session:
        return jsonify({"error": "login required"}), 401
    topic = (request.json or {}).get("topic", "")
    if not topic.strip():
        return jsonify({"error": "Topic is required"}), 400

    safe_name = "-".join(topic.lower().split())
    output_name = f"{safe_name}-{secrets.token_hex(3)}.mp4"
    output_path = os.path.join(app.config["UPLOAD_FOLDER"], output_name)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO jobs (username, topic, status, output_path, created_at) VALUES (?, ?, ?, ?, ?)",
        (session["user"], topic, "rendering", output_path, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    try:
        build_simple_video(topic, output_path)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET status = ? WHERE output_path = ?", ("ready", output_path))
    conn.commit()
    conn.close()
    return jsonify({"download_url": f"/download/{output_name}"})


@app.route("/download/<path:filename>")
def download(filename: str):
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "not found"}), 404
    return send_file(file_path, as_attachment=True, mimetype="video/mp4")


HTML_APP = """
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>RankingGen</title>
  <style>
    :root { color-scheme: dark; }
    body { margin:0; font-family: Inter, system-ui, sans-serif; background: radial-gradient(circle at top, #111827, #05060a 70%); color:#f8fafc; min-height:100vh; }
    .app { max-width: 1280px; margin: 0 auto; padding: 24px; }
    .card { background: rgba(15, 23, 42, .78); border:1px solid rgba(148,163,184,.2); border-radius:24px; box-shadow:0 20px 40px rgba(0,0,0,.25); backdrop-filter: blur(16px); }
    .topbar { display:flex; justify-content:space-between; align-items:center; padding:24px 28px; }
    .tabs { display:flex; gap:10px; flex-wrap:wrap; padding:0 28px 20px; }
    .tab { background:#111827; color:#cbd5e1; padding:10px 14px; border-radius:999px; cursor:pointer; border:1px solid transparent; }
    .tab.active { background: linear-gradient(90deg,#7c3aed,#2563eb); color:white; }
    .panel { display:none; padding: 0 28px 28px; }
    .panel.active { display:block; }
    .hero { padding:28px; margin:24px 0; display:grid; grid-template-columns: 1.2fr .8fr; gap:16px; }
    input, textarea, button { font: inherit; }
    input, textarea { width:100%; padding:14px 16px; border-radius:14px; border:1px solid #334155; background:#0f172a; color:white; margin-top:8px; }
    button { cursor:pointer; padding:12px 18px; border:none; border-radius:999px; color:white; background: linear-gradient(90deg,#4f46e5,#06b6d4); box-shadow:0 8px 20px rgba(6,182,212,.24); }
    .grid { display:grid; gap:16px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
    .pill { padding:6px 10px; border-radius:999px; background:#1f2937; color:#67e8f9; display:inline-block; margin-top:8px; }
    .toast { position:fixed; right:18px; bottom:18px; background:#111827; color:white; padding:13px 16px; border-radius:12px; opacity:0; transform:translateY(10px); transition: all .25s ease; pointer-events:none; }
    .toast.show { opacity:1; transform:translateY(0); }
    .small { color:#94a3b8; font-size:.95rem; }
    .status { margin-top: 12px; color:#86efac; }
    .preview { aspect-ratio: 9 / 16; background: linear-gradient(135deg,#1d4ed8,#7c3aed); border-radius:24px; display:flex; align-items:center; justify-content:center; padding:24px; color:white; text-align:center; animation: float 6s ease-in-out infinite; }
    @keyframes float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-8px)} }
    @media (max-width: 780px){ .hero{grid-template-columns:1fr;} }
  </style>
</head>
<body>
<div class=\"app\">
  <div class=\"card\">
    <div class=\"topbar\">
      <div>
        <h1 style=\"margin:0\">RankingGen</h1>
        <div class=\"small\">Create viral short-form ranking videos locally in one click.</div>
      </div>
      <a href=\"/logout\" style=\"color:#f8fafc;text-decoration:none\">Logout</a>
    </div>
    <div class=\"tabs\">
      <div class=\"tab active\" data-tab=\"generator\">Generator</div>
      <div class=\"tab\" data-tab=\"settings\">API Settings</div>
      <div class=\"tab\" data-tab=\"history\">History</div>
    </div>
    <div class=\"panel active\" id=\"generator\">
      <div class=\"hero\">
        <div>
          <h2 style=\"margin-top:0\">Turn any prompt into a polished Shorts-ready ranking clip</h2>
          <p class=\"small\">Enter a topic, leave the rest to the generator, and download a 30-60s MP4 in 9:16.</p>
          <textarea id=\"topic\" rows=\"4\" placeholder=\"e.g. best sci-fi movies of all time\"></textarea>
          <button id=\"generateBtn\" style=\"margin-top:12px\">Generate Short</button>
          <div id=\"status\" class=\"status\">Ready to create your next ranking short.</div>
        </div>
        <div class=\"preview\">
          <div>
            <div class=\"pill\">9:16 Shorts Format</div>
            <h3>Auto-generated top-5 ranking narrative</h3>
            <div class=\"small\">Local MP4 export • animated captions • viral-style pacing</div>
          </div>
        </div>
      </div>
    </div>
    <div class=\"panel\" id=\"settings\">
      <div class=\"grid\">
        <div class=\"card\" style=\"padding:18px\">
          <h3 style=\"margin-top:0\">API configuration</h3>
          <label>OpenAI API key</label>
          <input id=\"openaiApiKey\" placeholder=\"sk-...\" />
          <label style=\"margin-top:12px;display:block\">NVIDIA NIM Key</label>
          <input id=\"nvidiaNimKey\" placeholder=\"nim-...\" />
          <label style=\"margin-top:12px;display:block\">NVIDIA NIM Endpoint</label>
          <input id=\"nvidiaNimEndpoint\" placeholder=\"https://api.nvidia.com/....\" />
          <label style=\"margin-top:12px;display:block\">YouTube channel ID</label>
          <input id=\"youtubeChannelId\" placeholder=\"UC...\" />
          <button id=\"saveConfigBtn\" style=\"margin-top:14px\">Save configuration</button>
        </div>
      </div>
    </div>
    <div class=\"panel\" id=\"history\">
      <div class=\"card\" style=\"padding:18px\">
        <h3 style=\"margin-top:0\">Recent generations</h3>
        <div id=\"historyList\" class=\"small\">No jobs yet.</div>
      </div>
    </div>
  </div>
</div>
<div id=\"toast\" class=\"toast\"></div>
<script>
  const tabs = [...document.querySelectorAll('.tab')];
  const panels = [...document.querySelectorAll('.panel')];
  tabs.forEach(tab => tab.addEventListener('click', () => {
    tabs.forEach(t => t.classList.remove('active'));
    panels.forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(tab.dataset.tab).classList.add('active');
  }));
  function toast(message){ const el=document.getElementById('toast'); el.textContent=message; el.classList.add('show'); clearTimeout(window.toastTimer); window.toastTimer=setTimeout(()=>el.classList.remove('show'), 2200); }
  document.getElementById('generateBtn').addEventListener('click', async ()=>{
    const topic = document.getElementById('topic').value.trim();
    if(!topic){ toast('Please enter a topic.'); return; }
    const btn=document.getElementById('generateBtn'); btn.disabled=true; btn.textContent='Generating...';
    document.getElementById('status').textContent='Rendering your short...';
    const response=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({topic})});
    btn.disabled=false; btn.textContent='Generate Short';
    const data=await response.json();
    if(!response.ok){ toast(data.error || 'Generation failed'); document.getElementById('status').textContent='Generation failed.'; return; }
    document.getElementById('status').innerHTML=`<a href=\"${data.download_url}\" target=\"_blank\" style=\"color:#67e8f9\">Download MP4</a>`;
    toast('Short generated and ready to download.');
    loadHistory();
  });
  document.getElementById('saveConfigBtn').addEventListener('click', async ()=>{
    const payload={
      openai_api_key: document.getElementById('openaiApiKey').value,
      nvidia_nim_key: document.getElementById('nvidiaNimKey').value,
      nvidia_nim_endpoint: document.getElementById('nvidiaNimEndpoint').value,
      youtube_channel_id: document.getElementById('youtubeChannelId').value
    };
    const response=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await response.json();
    if(response.ok){ toast('Configuration saved.'); } else { toast(data.error || 'Save failed'); }
  });
  async function loadConfig(){
    const response=await fetch('/api/config');
    const data=await response.json();
    document.getElementById('openaiApiKey').value=data.openai_api_key || '';
    document.getElementById('nvidiaNimKey').value=data.nvidia_nim_key || '';
    document.getElementById('nvidiaNimEndpoint').value=data.nvidia_nim_endpoint || '';
    document.getElementById('youtubeChannelId').value=data.youtube_channel_id || '';
  }
  async function loadHistory(){
    const response=await fetch('/api/history');
    const data=await response.json();
    const list=document.getElementById('historyList');
    if(!data.length){ list.innerHTML='No jobs yet.'; return; }
    list.innerHTML=data.map(item => `<div style=\"margin-top:8px\"><strong>${item.topic}</strong><br/>${item.status} • ${item.filename || 'video'} • ${item.created_at}</div>`).join('');
  }
  loadConfig();
  loadHistory();
</script>
</body>
</html>
"""

LOGIN_HTML = """
<!doctype html>
<html lang=\"en\">
<head><meta charset=\"utf-8\" /><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /><title>Login • RankingGen</title>
<style>body{margin:0;font-family:Inter,sans-serif;background:radial-gradient(circle at top,#111827,#05060a);color:white;min-height:100vh;display:flex;align-items:center;justify-content:center;} .card{width:min(420px,92vw);padding:24px;border-radius:24px;background:rgba(15,23,42,.82);border:1px solid rgba(255,255,255,.1);box-shadow:0 20px 40px rgba(0,0,0,.25);} input,button{width:100%;padding:12px 14px;border-radius:12px;border:1px solid #334155;background:#0f172a;color:white;margin-top:10px;} button{background:linear-gradient(90deg,#4f46e5,#06b6d4);border:none;cursor:pointer;} a{color:#67e8f9;} .error{color:#fda4af;margin-top:10px;}</style></head>
<body><div class=\"card\"><h2 style=\"margin-top:0\">RankingGen</h2><p>Sign in to generate Shorts locally.</p><form method=\"post\"><input name=\"username\" placeholder=\"Username\" /><input name=\"password\" type=\"password\" placeholder=\"Password\" /><button>Login</button></form><p><a href=\"/signup\">Create an account</a></p>{% if error %}<div class=\"error\">{{error}}</div>{% endif %}</div></body></html>
"""

SIGNUP_HTML = """
<!doctype html>
<html lang=\"en\">
<head><meta charset=\"utf-8\" /><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" /><title>Sign up • RankingGen</title>
<style>body{margin:0;font-family:Inter,sans-serif;background:radial-gradient(circle at top,#111827,#05060a);color:white;min-height:100vh;display:flex;align-items:center;justify-content:center;} .card{width:min(420px,92vw);padding:24px;border-radius:24px;background:rgba(15,23,42,.82);border:1px solid rgba(255,255,255,.1);box-shadow:0 20px 40px rgba(0,0,0,.25);} input,button{width:100%;padding:12px 14px;border-radius:12px;border:1px solid #334155;background:#0f172a;color:white;margin-top:10px;} button{background:linear-gradient(90deg,#4f46e5,#06b6d4);border:none;cursor:pointer;} a{color:#67e8f9;} .error{color:#fda4af;margin-top:10px;}</style></head>
<body><div class=\"card\"><h2 style=\"margin-top:0\">RankingGen</h2><p>Create your account and start generating.</p><form method=\"post\"><input name=\"username\" placeholder=\"Username\" /><input name=\"password\" type=\"password\" placeholder=\"Password\" /><button>Create account</button></form><p><a href=\"/login\">Back to login</a></p>{% if error %}<div class=\"error\">{{error}}</div>{% endif %}</div></body></html>
"""


if __name__ == "__main__":
    app.config["PYTHON"] = os.environ.get("PYTHON_BIN", os.sys.executable)
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=True)
