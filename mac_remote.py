#!/usr/bin/env python3
"""
Mac Remote Control Server v5
A full-featured personal remote for your own Mac, controlled from your phone.
Dependencies: flask, psutil, Pillow  (installed automatically by install.sh)
Optional CLI tools: cliclick (mouse), brightness (screen), imagesnap (webcam)
"""

from flask import Flask, request, jsonify, send_from_directory, send_file, Response
import subprocess, os, socket, platform, random, json, base64, time, threading, io

app = Flask(__name__)

# ── Persistent config (token survives restarts so mobile bookmark keeps working) ──
CONFIG_DIR = os.path.expanduser("~/.macremote")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
ADJ = ["Gepard","Ulv","Ørn","Tiger","Bjørn","Rev","Gaupe","Elg","Sel","Hval","Ravn","Hare","Bison","Løve","Irbis","Falk","Oter"]
NOUN = ["Fjord","Skog","Topp","Dal","Mark","Kyst","Bre","Eng","Foss","Vann","Heim","Berg","Vik","Nes"]

def gen_token():
    return random.choice(ADJ) + random.choice(NOUN) + str(random.randint(10,99))

def load_config():
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                return json.load(f)
    except: pass
    return {}

def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
    except: pass

_cfg = load_config()
if "token" not in _cfg:
    _cfg["token"] = gen_token()
    save_config(_cfg)
TOKEN = _cfg["token"]

# ── Helpers ──
def check_auth(req):
    t = req.headers.get("X-Auth-Token") or req.args.get("token")
    return t == TOKEN

def run(cmd, shell=True, timeout=15):
    try:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=timeout)
        return {"ok": True, "out": r.stdout.strip(), "err": r.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "err": "Tidsavbrudd"}
    except Exception as e:
        return {"ok": False, "err": str(e)}

def osa(script):
    return run(["osascript", "-e", script], shell=False)

def which(tool):
    return subprocess.run(f"which {tool}", shell=True, capture_output=True).returncode == 0

HAS_CLICLICK = which("cliclick")
HAS_BRIGHTNESS = which("brightness")
HAS_IMAGESNAP = which("imagesnap")

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Caffeinate handle for keep-awake toggle
_caffeinate = {"proc": None}

# ══════════════════════════════════════════════════════════════════════════
#  Static
# ══════════════════════════════════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "mac_remote.html")

@app.route("/manifest.json")
def manifest():
    data = {"name":"Mac Remote","short_name":"MacRemote","start_url":"/",
            "display":"standalone","background_color":"#0e1210","theme_color":"#0e1210",
            "icons":[{"src":"/icon.png","sizes":"512x512","type":"image/png","purpose":"any"}]}
    return Response(json.dumps(data), mimetype="application/json")

@app.route("/icon.png")
def icon():
    p = os.path.join(BASE_DIR, "icon.png")
    if os.path.exists(p):
        return send_file(p, mimetype="image/png")
    px = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    return Response(px, mimetype="image/png")

def guard():
    return None if check_auth(request) else (jsonify({"error":"Ugyldig token"}), 401)

# ══════════════════════════════════════════════════════════════════════════
#  Status / info
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/info")
def info():
    g = guard()
    if g: return g
    vol = run("osascript -e 'output volume of (get volume settings)'")
    muted = run("osascript -e 'output muted of (get volume settings)'")
    batt_raw = run("pmset -g batt")
    batt_pct = "?"
    charging = False
    time_left = ""
    out = batt_raw.get("out","")
    import re
    m = re.search(r"(\d+)%", out)
    if m: batt_pct = m.group(1)
    charging = "AC Power" in out or "charging" in out.lower()
    tm = re.search(r"(\d+:\d+) remaining", out)
    if tm: time_left = tm.group(1)
    wifi = run("networksetup -getairportnetwork en0 | awk -F': ' '{print $2}'")
    bright = ""
    if HAS_BRIGHTNESS:
        br = run("brightness -l 2>/dev/null | grep 'display 0' | grep -o 'brightness [0-9.]*' | awk '{print $2}'")
        bright = br.get("out","")
    uptime = ""
    if HAS_PSUTIL:
        secs = int(time.time() - psutil.boot_time())
        d = secs//86400; h = (secs%86400)//3600; mn=(secs%3600)//60
        uptime = (f"{d}d " if d else "") + f"{h}t {mn}m"
    return jsonify({
        "hostname": socket.gethostname(),
        "os": platform.mac_ver()[0],
        "volume": vol.get("out","?"),
        "muted": muted.get("out","false"),
        "battery": batt_pct,
        "charging": charging,
        "time_left": time_left,
        "wifi": wifi.get("out","?"),
        "brightness": bright,
        "uptime": uptime,
        "caffeinated": _caffeinate["proc"] is not None,
    })

@app.route("/api/system/stats")
def stats():
    g = guard()
    if g: return g
    if not HAS_PSUTIL:
        return jsonify({"error":"psutil mangler"}), 500
    cpu = psutil.cpu_percent(interval=0.4)
    per_core = psutil.cpu_percent(percpu=True)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net = psutil.net_io_counters()
    temps = {}
    try:
        t = psutil.sensors_temperatures()
        for name, entries in (t or {}).items():
            if entries: temps[name] = round(entries[0].current, 1)
    except: pass
    return jsonify({
        "cpu": round(cpu,1),
        "cores": [round(c,1) for c in per_core],
        "ram_used": round(mem.used/1024**3,1),
        "ram_total": round(mem.total/1024**3,1),
        "ram_pct": mem.percent,
        "disk_used": round(disk.used/1024**3,1),
        "disk_total": round(disk.total/1024**3,1),
        "disk_pct": round(disk.used/disk.total*100,1),
        "net_sent": round(net.bytes_sent/1024**2,1),
        "net_recv": round(net.bytes_recv/1024**2,1),
        "temps": temps,
    })

@app.route("/api/system/processes")
def processes():
    g = guard()
    if g: return g
    if not HAS_PSUTIL: return jsonify({"processes":[]})
    procs = []
    for p in psutil.process_iter(['pid','name','cpu_percent','memory_percent']):
        try:
            procs.append({"pid":p.info['pid'],"name":p.info['name'] or "?",
                          "cpu":round(p.info['cpu_percent'] or 0,1),
                          "mem":round(p.info['memory_percent'] or 0,1)})
        except: continue
    procs.sort(key=lambda x:x['cpu'], reverse=True)
    return jsonify({"processes": procs[:22]})

@app.route("/api/system/kill", methods=["POST"])
def kill_proc():
    g = guard()
    if g: return g
    pid = (request.json or {}).get("pid")
    if not pid or int(pid) < 2:
        return jsonify({"ok":False,"err":"Ugyldig PID"})
    try:
        os.kill(int(pid), 15)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"err":str(e)})

@app.route("/api/nowplaying")
def nowplaying():
    g = guard()
    if g: return g
    script = '''
set outp to ""
try
  if application "Spotify" is running then
    tell application "Spotify"
      if player state is playing or player state is paused then
        set outp to (name of current track) & " ||| " & (artist of current track) & " ||| " & (player state as text) & " ||| Spotify"
      end if
    end tell
  end if
end try
if outp is "" then
  try
    if application "Music" is running then
      tell application "Music"
        if player state is playing or player state is paused then
          set outp to (name of current track) & " ||| " & (artist of current track) & " ||| " & (player state as text) & " ||| Music"
        end if
      end tell
    end if
  end try
end if
return outp'''
    r = osa(script)
    out = r.get("out","").strip()
    if not out or "|||" not in out:
        return jsonify({"playing": False})
    parts = [p.strip() for p in out.split("|||")]
    return jsonify({"playing": True, "track": parts[0], "artist": parts[1],
                    "state": parts[2] if len(parts)>2 else "", "app": parts[3] if len(parts)>3 else ""})

# ══════════════════════════════════════════════════════════════════════════
#  Audio / brightness / media
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/volume/set/<int:level>")
def volume_set(level):
    g = guard()
    if g: return g
    return jsonify(osa(f"set volume output volume {max(0,min(100,level))}"))

@app.route("/api/volume/togglemute")
def toggle_mute():
    g = guard()
    if g: return g
    r = run("osascript -e 'output muted of (get volume settings)'")
    muted = r.get("out","false").strip().lower() == "true"
    osa("set volume without output muted" if muted else "set volume with output muted")
    return jsonify({"ok":True,"muted": not muted})

@app.route("/api/brightness/set/<int:level>")
def brightness_set(level):
    g = guard()
    if g: return g
    if not HAS_BRIGHTNESS:
        return jsonify({"ok":False,"err":"brightness-verktøy ikke installert"})
    val = max(0,min(100,level))/100.0
    return jsonify(run(f"brightness {val}"))

@app.route("/api/media/<action>")
def media(action):
    g = guard()
    if g: return g
    keys = {"play":"key code 49","next":"key code 124 using {command down}","prev":"key code 123 using {command down}"}
    if action not in keys: return jsonify({"ok":False,"err":"Ukjent"})
    return jsonify(osa(f'tell application "System Events" to {keys[action]}'))

# ══════════════════════════════════════════════════════════════════════════
#  Display / screen
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/display/sleep")
def display_sleep():
    g = guard()
    if g: return g
    return jsonify(run("pmset displaysleepnow"))

@app.route("/api/display/wake")
def display_wake():
    g = guard()
    if g: return g
    return jsonify(run("caffeinate -u -t 1"))

def capture_jpeg(max_w=None, quality=70):
    path = "/tmp/mr_shot.png"
    subprocess.run(f"screencapture -x -t png -o {path}", shell=True, timeout=10)
    if not os.path.exists(path): return None
    if HAS_PIL:
        try:
            im = Image.open(path).convert("RGB")
            if max_w and im.width > max_w:
                ratio = max_w / im.width
                im = im.resize((max_w, int(im.height*ratio)))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality)
            os.remove(path)
            return buf.getvalue()
        except: pass
    with open(path,"rb") as f: data = f.read()
    os.remove(path)
    return data

@app.route("/api/display/screenshot")
def screenshot():
    g = guard()
    if g: return g
    data = capture_jpeg(max_w=1600, quality=82)
    if not data: return jsonify({"ok":False,"err":"Klarte ikke ta skjermbilde"})
    return jsonify({"ok":True,"image": base64.b64encode(data).decode()})

@app.route("/api/display/stream")
def stream():
    if not check_auth(request): return Response("Unauthorized", status=401)
    def gen():
        while True:
            data = capture_jpeg(max_w=1000, quality=55)
            if data:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n")
            time.sleep(0.25)
    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/webcam/snapshot")
def webcam():
    g = guard()
    if g: return g
    if not HAS_IMAGESNAP:
        return jsonify({"ok":False,"err":"imagesnap ikke installert"})
    path = "/tmp/mr_cam.jpg"
    run(f"imagesnap -w 1 {path}", timeout=8)
    if not os.path.exists(path):
        return jsonify({"ok":False,"err":"Klarte ikke ta bilde"})
    with open(path,"rb") as f: data = f.read()
    os.remove(path)
    return jsonify({"ok":True,"image": base64.b64encode(data).decode()})

# ══════════════════════════════════════════════════════════════════════════
#  System actions
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/system/sleep")
def sys_sleep():
    g = guard()
    if g: return g
    return jsonify(osa('tell application "System Events" to sleep'))

@app.route("/api/system/lock")
def sys_lock():
    g = guard()
    if g: return g
    return jsonify(run("pmset sleepnow"))

@app.route("/api/system/screensaver")
def sys_saver():
    g = guard()
    if g: return g
    return jsonify(run("open -a ScreenSaverEngine"))

@app.route("/api/system/darkmode")
def darkmode():
    g = guard()
    if g: return g
    return jsonify(osa('tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'))

@app.route("/api/system/caffeinate")
def caffeinate_toggle():
    g = guard()
    if g: return g
    if _caffeinate["proc"] is not None:
        try: _caffeinate["proc"].terminate()
        except: pass
        _caffeinate["proc"] = None
        return jsonify({"ok":True,"caffeinated":False})
    else:
        _caffeinate["proc"] = subprocess.Popen(["caffeinate","-d"])
        return jsonify({"ok":True,"caffeinated":True})

@app.route("/api/system/notification", methods=["POST"])
def notif():
    g = guard()
    if g: return g
    d = request.json or {}
    title = d.get("title","Mac Remote").replace('"','')
    msg = d.get("message","").replace('"','')
    return jsonify(osa(f'display notification "{msg}" with title "{title}"'))

@app.route("/api/system/say", methods=["POST"])
def say():
    g = guard()
    if g: return g
    text = (request.json or {}).get("text","").replace('"','').replace("'","")[:250]
    return jsonify(run(f'say "{text}"'))

@app.route("/api/system/findmymac")
def findmymac():
    g = guard()
    if g: return g
    run("osascript -e 'set volume output volume 90'")
    threading.Thread(target=lambda: run('say "Her er jeg. Her er jeg. Her er jeg."')).start()
    return jsonify({"ok":True})

@app.route("/api/system/power", methods=["POST"])
def power():
    g = guard()
    if g: return g
    action = (request.json or {}).get("action","")
    cmds = {
        "restart":'tell application "System Events" to restart',
        "shutdown":'tell application "System Events" to shut down',
        "logout":'tell application "System Events" to log out',
    }
    if action not in cmds: return jsonify({"ok":False,"err":"Ukjent handling"})
    threading.Thread(target=lambda: osa(cmds[action])).start()
    return jsonify({"ok":True})

# ══════════════════════════════════════════════════════════════════════════
#  Apps
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/apps/installed")
def apps_installed():
    g = guard()
    if g: return g
    r = run("ls /Applications/ | grep '.app' | sed 's/.app//'")
    apps = sorted([a.strip() for a in r.get("out","").split("\n") if a.strip()])
    return jsonify({"apps": apps})

@app.route("/api/apps/running")
def apps_running():
    g = guard()
    if g: return g
    r = run("osascript -e 'tell application \"System Events\" to get name of every application process whose background only is false'")
    apps = [a.strip() for a in r.get("out","").split(",") if a.strip()]
    return jsonify({"apps": apps})

@app.route("/api/app/open/<appname>")
def app_open(appname):
    g = guard()
    if g: return g
    safe = appname.replace('"','').replace(';','').replace('&','').replace('|','')
    return jsonify(run(["open","-a",safe], shell=False))

@app.route("/api/app/quit/<appname>")
def app_quit(appname):
    g = guard()
    if g: return g
    safe = appname.replace('"','').replace(';','').replace('&','').replace('|','')
    return jsonify(osa(f'tell application "{safe}" to quit'))

# ══════════════════════════════════════════════════════════════════════════
#  Input: keyboard / mouse / clipboard
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/type", methods=["POST"])
def type_text():
    g = guard()
    if g: return g
    text = (request.json or {}).get("text","").replace('"','\\"')
    return jsonify(osa(f'tell application "System Events" to keystroke "{text}"'))

@app.route("/api/key", methods=["POST"])
def key_press():
    g = guard()
    if g: return g
    key = (request.json or {}).get("key","")
    keys = {
        "return":"key code 36","delete":"key code 51","escape":"key code 53",
        "tab":"key code 48","space":"key code 49","up":"key code 126",
        "down":"key code 125","left":"key code 123","right":"key code 124",
        "home":"key code 115","end":"key code 119","pageup":"key code 116","pagedown":"key code 121",
        "f5":"key code 96","f11":"key code 103",
        "cmd_c":'keystroke "c" using command down',
        "cmd_v":'keystroke "v" using command down',
        "cmd_x":'keystroke "x" using command down',
        "cmd_z":'keystroke "z" using command down',
        "cmd_a":'keystroke "a" using command down',
        "cmd_s":'keystroke "s" using command down',
        "cmd_w":'keystroke "w" using command down',
        "cmd_t":'keystroke "t" using command down',
        "cmd_q":'keystroke "q" using command down',
        "cmd_tab":'keystroke tab using command down',
        "cmd_space":'keystroke space using command down',
        "mission":"key code 126 using {control down}",
    }
    if key not in keys: return jsonify({"ok":False,"err":"Ukjent tast"})
    return jsonify(osa(f'tell application "System Events" to {keys[key]}'))

@app.route("/api/mouse/move", methods=["POST"])
def mouse_move():
    if not check_auth(request): return jsonify({"error":"401"}), 401
    d = request.json or {}
    dx = int(float(d.get("dx",0))); dy = int(float(d.get("dy",0)))
    if HAS_CLICLICK:
        return jsonify(run(f"cliclick m:+{dx},+{dy}"))
    return jsonify(osa(f'''tell application "System Events"
set cp to position of mouse
set position of mouse to {{(item 1 of cp)+{dx}, (item 2 of cp)+{dy}}}
end tell'''))

@app.route("/api/mouse/click", methods=["POST"])
def mouse_click():
    if not check_auth(request): return jsonify({"error":"401"}), 401
    btn = (request.json or {}).get("button","left")
    if HAS_CLICLICK:
        flag = {"right":"rc","double":"dc","left":"c"}.get(btn,"c")
        return jsonify(run(f"cliclick {flag}:."))
    if btn == "right":
        return jsonify(osa('tell application "System Events" to perform action "AXShowMenu" of (position of mouse)'))
    return jsonify(osa('tell application "System Events" to click at (position of mouse)'))

@app.route("/api/mouse/scroll", methods=["POST"])
def mouse_scroll():
    if not check_auth(request): return jsonify({"error":"401"}), 401
    dy = int((request.json or {}).get("dy",0))
    if HAS_CLICLICK:
        return jsonify(run(f"cliclick {'d' if dy>0 else 'u'}:."))
    return jsonify(osa(f'tell application "System Events" to scroll {abs(dy)} {"down" if dy>0 else "up"}'))

@app.route("/api/clipboard/set", methods=["POST"])
def clip_set():
    g = guard()
    if g: return g
    p = subprocess.run("pbcopy", input=(request.json or {}).get("text","").encode(), capture_output=True)
    return jsonify({"ok": p.returncode==0})

@app.route("/api/clipboard/get")
def clip_get():
    g = guard()
    if g: return g
    return jsonify({"text": run("pbpaste").get("out","")})

# ══════════════════════════════════════════════════════════════════════════
#  Terminal
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/terminal", methods=["POST"])
def terminal():
    g = guard()
    if g: return g
    cmd = (request.json or {}).get("cmd","").strip()
    if not cmd: return jsonify({"ok":False,"err":"Tom kommando"})
    blocked = ["rm -rf /"," rm -rf /","mkfs","dd if=",":(){","> /dev/sda","chmod -R 000"]
    for b in blocked:
        if b in cmd:
            return jsonify({"ok":False,"err":"Blokkert av sikkerhetshensyn"})
    r = run(cmd, timeout=20)
    return jsonify({"ok":True,"out":r.get("out",""),"err":r.get("err","")})

# ══════════════════════════════════════════════════════════════════════════
#  Files
# ══════════════════════════════════════════════════════════════════════════
HOME = os.path.expanduser("~")

def safe_path(path):
    p = os.path.normpath(path)
    return p if p.startswith(HOME) else HOME

@app.route("/api/files/quick")
def files_quick():
    g = guard()
    if g: return g
    folders = [
        {"name":"Hjem","path":HOME,"icon":"🏠"},
        {"name":"Skrivebord","path":os.path.join(HOME,"Desktop"),"icon":"🖥️"},
        {"name":"Nedlastinger","path":os.path.join(HOME,"Downloads"),"icon":"⬇️"},
        {"name":"Dokumenter","path":os.path.join(HOME,"Documents"),"icon":"📄"},
    ]
    return jsonify({"folders":[f for f in folders if os.path.isdir(f["path"])]})

@app.route("/api/files/list")
def files_list():
    g = guard()
    if g: return g
    path = safe_path(request.args.get("path", HOME))
    try:
        entries = []
        for name in sorted(os.listdir(path), key=str.lower):
            if name.startswith("."): continue
            full = os.path.join(path, name)
            try:
                is_dir = os.path.isdir(full)
                entries.append({"name":name,"path":full,"is_dir":is_dir,
                                "size": os.path.getsize(full) if not is_dir else 0})
            except: continue
        entries.sort(key=lambda e:(not e["is_dir"], e["name"].lower()))
        return jsonify({"ok":True,"path":path,"parent":os.path.dirname(path),"entries":entries})
    except Exception as e:
        return jsonify({"ok":False,"err":str(e)})

@app.route("/api/files/download")
def files_download():
    if not check_auth(request): return jsonify({"error":"401"}), 401
    path = request.args.get("path","")
    if not os.path.isfile(path) or not os.path.normpath(path).startswith(HOME):
        return jsonify({"error":"Ikke tillatt"}), 403
    return send_file(path, as_attachment=True)

@app.route("/api/files/open")
def files_open():
    g = guard()
    if g: return g
    path = request.args.get("path","")
    if not os.path.normpath(path).startswith(HOME):
        return jsonify({"ok":False,"err":"Ikke tillatt"})
    return jsonify(run(["open", path], shell=False))

@app.route("/api/files/upload", methods=["POST"])
def files_upload():
    g = guard()
    if g: return g
    dest = safe_path(request.form.get("path", os.path.join(HOME,"Downloads")))
    if not os.path.isdir(dest): dest = os.path.join(HOME,"Downloads")
    if "file" not in request.files:
        return jsonify({"ok":False,"err":"Ingen fil"})
    f = request.files["file"]
    name = os.path.basename(f.filename)
    if not name: return jsonify({"ok":False,"err":"Ugyldig filnavn"})
    f.save(os.path.join(dest, name))
    return jsonify({"ok":True,"saved":name,"dest":dest})

# ══════════════════════════════════════════════════════════════════════════
#  Config / token
# ══════════════════════════════════════════════════════════════════════════
@app.route("/api/token/regenerate", methods=["POST"])
def regen_token():
    g = guard()
    if g: return g
    global TOKEN, _cfg
    TOKEN = gen_token()
    _cfg["token"] = TOKEN
    save_config(_cfg)
    return jsonify({"ok":True,"token":TOKEN})

@app.route("/api/capabilities")
def capabilities():
    g = guard()
    if g: return g
    return jsonify({
        "cliclick": HAS_CLICLICK,
        "brightness": HAS_BRIGHTNESS,
        "webcam": HAS_IMAGESNAP,
        "psutil": HAS_PSUTIL,
        "pil": HAS_PIL,
    })

# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        ip = subprocess.run("ipconfig getifaddr en0", shell=True, capture_output=True, text=True).stdout.strip()
        if not ip:
            ip = subprocess.run("ipconfig getifaddr en1", shell=True, capture_output=True, text=True).stdout.strip()
        if not ip:
            ip = socket.gethostbyname(socket.gethostname())
    except: ip = "?"
    port = 5055
    print(f"""
╔════════════════════════════════════════════════╗
║        Mac Remote Control Server  v5           ║
╠════════════════════════════════════════════════╣
║                                                ║
║   Åpne på mobil (samme Wi-Fi):                 ║
║   http://{ip}:{port}
║                                                ║
║   Token:  {TOKEN}
║                                                ║
║   Token lagres og er likt hver oppstart.       ║
║   Lukk vinduet for å stoppe serveren.          ║
╚════════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
