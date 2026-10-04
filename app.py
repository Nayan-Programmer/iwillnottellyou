import os, io, csv, json, uuid, time, hmac, secrets, re
from dotenv import load_dotenv

load_dotenv()

from datetime import datetime, timezone
from functools import wraps
from postgrest import SyncPostgrestClient
from werkzeug.exceptions import HTTPException
from flask import Flask, request, jsonify, session, Response, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")
app.secret_key = os.environ["SECRET_KEY"]                      # all secrets come from env vars
ADMIN_PASSWORD = os.environ["ADMIN_PASSWORD"]
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")                # https://xxxx.supabase.co
SB_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]               # server only, never sent to the browser
app.config.update(
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12, MAX_CONTENT_LENGTH=64 * 1024)

sb = SyncPostgrestClient(os.environ.get("SUPABASE_REST_URL", SB_URL + "/rest/v1"),
                         headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY}, timeout=15)
T = sb.from_
rows = lambda q: q.execute().data
def one(q):
    d = rows(q.limit(1)); return d[0] if d else None

now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
def err(msg, code=400): return jsonify(error=msg), code

def admin_only(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"): return err("Not signed in", 401)
        if request.method not in ("GET", "HEAD") and request.headers.get("X-Requested-With") != "fetch":
            return err("Bad request", 403)  # CSRF guard: cross-site forms cannot set this header
        return f(*a, **k)
    return w

@app.errorhandler(404)
def nf(_):
    return err("Not found", 404) if request.path.startswith("/api") else (send_from_directory("static", "404.html"), 404)
@app.errorhandler(413)
def big(_): return err("Request too large", 413)
@app.errorhandler(500)
def boom(_): return err("Server error, please try again", 500)
@app.errorhandler(Exception)
def anyerr(e):
    if isinstance(e, HTTPException): return e
    app.logger.exception(e); return err("Could not reach the database, please try again", 503)

# ---------- pages ----------
@app.route("/")
def home(): return send_from_directory("static", "home.html")
@app.route("/q/<slug>")
def quiz_page(slug): return send_from_directory("static", "quiz.html")
@app.route("/admin")
def admin_page(): return send_from_directory("static", "admin.html")

# ---------- public API ----------
def quiz_by_slug(slug): return one(T("quizzes").select("*").eq("slug", slug))
def qlist(qid):
    return [dict(r, options=json.loads(r["options"] or "[]")) for r in rows(T("questions").select("*").eq("quiz_id", qid).order("position"))]

@app.get("/api/quiz/<slug>")
def get_quiz(slug):
    q = quiz_by_slug(slug)
    if not q: return err("This quiz doesn't exist", 404)
    if not q["active"]: return err("This quiz is not accepting responses right now", 403)
    qs = [{"id": x["id"], "text": x["text"], "type": x["type"], "options": x["options"]} for x in qlist(q["id"])]
    return jsonify(title=q["title"], description=q["description"], ask_name=bool(q["ask_name"]), questions=qs)

@app.post("/api/quiz/<slug>/submit")
def submit(slug):
    q = quiz_by_slug(slug)
    if not q or not q["active"]: return err("This quiz is not accepting responses", 403)
    data = request.get_json(silent=True) or {}
    qs, given = qlist(q["id"]), data.get("answers") or {}
    name = str(data.get("name") or "").strip()[:80]
    if q["ask_name"] and not name: return err("Please enter your name")
    vals = []
    for x in qs:
        v = str(given.get(str(x["id"]), "")).strip()
        if not v: return err("Please answer every question")
        if x["type"] == "mc" and v not in x["options"]: return err("Invalid choice")
        vals.append((x, v[:1000]))
    rid = uuid.uuid4().hex
    T("responses").insert({"id": rid, "quiz_id": q["id"], "name": name, "created_at": now()}).execute()
    try:
        T("answers").insert([{"response_id": rid, "question_id": x["id"], "value": v} for x, v in vals]).execute()
    except Exception:
        T("responses").delete().eq("id", rid).execute(); raise
    out = {"response_id": rid}
    if q["show_answers"]:
        out["results"] = [{"question": x["text"], "yours": v, "correct": x["correct"],
                           "is_correct": (v.lower() == x["correct"].lower()) if x["correct"] else None} for x, v in vals]
    return jsonify(out)

@app.post("/api/message")
def send_message():
    data = request.get_json(silent=True) or {}
    body = str(data.get("body") or "").strip()
    if not body: return err("Write a message first")
    if len(body) > 1000: return err("Message is too long (max 1000 characters)")
    r = one(T("responses").select("*").eq("id", str(data.get("response_id"))))
    if not r: return err("Unknown submission", 404)
    if one(T("messages").select("id").eq("response_id", r["id"])): return err("You already sent a message", 409)
    T("messages").insert({"quiz_id": r["quiz_id"], "response_id": r["id"], "name": r["name"], "body": body, "created_at": now()}).execute()
    return jsonify(ok=True)

# ---------- admin auth ----------
FAILS = {}
@app.post("/api/admin/login")
def login():
    ip, t = request.remote_addr, time.time()
    n, first = FAILS.get(ip, (0, t))
    if t - first > 300: n, first = 0, t
    if n >= 5: return err("Too many attempts. Try again in a few minutes.", 429)
    pw = str((request.get_json(silent=True) or {}).get("password", ""))
    if hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
        FAILS.pop(ip, None); session.clear(); session["admin"] = True; session.permanent = True
        return jsonify(ok=True)
    FAILS[ip] = (n + 1, first)
    return err("Wrong password", 401)

@app.post("/api/admin/logout")
def logout(): session.clear(); return jsonify(ok=True)
@app.get("/api/admin/me")
def me(): return jsonify(admin=bool(session.get("admin")))

# ---------- admin: quizzes ----------
def quiz_json(r):
    c = T("responses").select("id", count="exact").eq("quiz_id", r["id"]).limit(1).execute().count or 0
    return {**{k: r[k] for k in ("id", "slug", "title", "description", "created_at")},
            "active": bool(r["active"]), "show_answers": bool(r["show_answers"]), "ask_name": bool(r["ask_name"]),
            "responses": c, "questions": qlist(r["id"])}

@app.get("/api/admin/quizzes")
@admin_only
def quizzes():
    return jsonify([quiz_json(r) for r in rows(T("quizzes").select("*").order("id", desc=True))])

def clean_quiz(p):
    title = str(p.get("title") or "").strip()[:120]
    if not title: raise ValueError("Give your quiz a title")
    qs = p.get("questions") or []
    if not 2 <= len(qs) <= 3: raise ValueError("A quiz needs 2 or 3 questions")
    out = []
    for i, x in enumerate(qs, 1):
        text, typ = str(x.get("text") or "").strip()[:300], x.get("type")
        if not text: raise ValueError(f"Question {i} is empty")
        if typ not in ("mc", "text"): raise ValueError(f"Question {i} has an invalid type")
        opts, correct = [], str(x.get("correct") or "").strip()[:200] or None
        if typ == "mc":
            opts = [str(o).strip()[:200] for o in x.get("options") or [] if str(o).strip()]
            if not 2 <= len(opts) <= 6 or len(set(opts)) != len(opts):
                raise ValueError(f"Question {i} needs 2-6 different options")
            if correct and correct not in opts: correct = None
        out.append((x.get("id"), text, typ, json.dumps(opts), correct))
    return title, str(p.get("description") or "").strip()[:500], out

@app.route("/api/admin/quizzes", methods=["POST"])
@app.route("/api/admin/quizzes/<int:qid>", methods=["PUT"])
@admin_only
def save_quiz(qid=None):
    p = request.get_json(silent=True) or {}
    try: title, desc, qs = clean_quiz(p)
    except ValueError as e: return err(str(e))
    f = {"title": title, "description": desc, "active": int(bool(p.get("active"))),
         "show_answers": int(bool(p.get("show_answers"))), "ask_name": int(bool(p.get("ask_name", True)))}
    if qid is None:
        f.update(slug=secrets.token_urlsafe(6).replace("_", "x").replace("-", "y"), created_at=now())
        qid = T("quizzes").insert(f).execute().data[0]["id"]
    else:
        if not T("quizzes").update(f).eq("id", qid).execute().data: return err("Quiz not found", 404)
    own = {r["id"] for r in rows(T("questions").select("id").eq("quiz_id", qid))}
    keep = [x[0] for x in qs if x[0] in own]
    gone = [i for i in own if i not in keep]
    if gone: T("questions").delete().eq("quiz_id", qid).in_("id", gone).execute()
    new = []
    for pos, (xid, text, typ, opts, correct) in enumerate(qs):
        rec = {"position": pos, "text": text, "type": typ, "options": opts, "correct": correct}
        if xid in own: T("questions").update(rec).eq("id", xid).execute()
        else: new.append({**rec, "quiz_id": qid})
    if new: T("questions").insert(new).execute()
    return jsonify(quiz_json(one(T("quizzes").select("*").eq("id", qid))))

@app.patch("/api/admin/quizzes/<int:qid>")
@admin_only
def patch_quiz(qid):
    p = request.get_json(silent=True) or {}
    f = {k: int(bool(p[k])) for k in ("active", "show_answers") if k in p}
    if f: T("quizzes").update(f).eq("id", qid).execute()
    return jsonify(ok=True)

@app.delete("/api/admin/quizzes/<int:qid>")
@admin_only
def del_quiz(qid):
    T("quizzes").delete().eq("id", qid).execute(); return jsonify(ok=True)

# ---------- admin: responses ----------
def responses_for(qid, term=""):
    qs = qlist(qid); out = []
    for r in rows(T("responses").select("id,name,created_at,answers(question_id,value)").eq("quiz_id", qid).order("created_at", desc=True).limit(1000)):
        a = {x["question_id"]: x["value"] for x in r["answers"]}
        row = {"id": r["id"], "name": r["name"], "created_at": r["created_at"], "answers": [a.get(x["id"], "") for x in qs]}
        if term and term.lower() not in " ".join([r["name"], *row["answers"]]).lower(): continue
        out.append(row)
    return qs, out

@app.get("/api/admin/quizzes/<int:qid>/responses")
@admin_only
def responses(qid):
    qs, rows = responses_for(qid, request.args.get("q", "").strip())
    allrows = rows if not request.args.get("q") else responses_for(qid)[1]
    stats = []
    for i, x in enumerate(qs):
        vals = [r["answers"][i] for r in allrows]
        dist = {o: vals.count(o) for o in x["options"]} if x["type"] == "mc" else None
        stats.append({"id": x["id"], "text": x["text"], "type": x["type"], "answered": len(vals), "distribution": dist})
    return jsonify(questions=[{"id": x["id"], "text": x["text"], "type": x["type"]} for x in qs],
                   responses=rows, total=len(allrows), stats=stats)

@app.delete("/api/admin/responses/<rid>")
@admin_only
def del_response(rid):
    T("responses").delete().eq("id", rid).execute(); return jsonify(ok=True)

def safe(v):
    v = str(v)
    return "'" + v if v[:1] in "=+-@\t\r" and v else v

@app.get("/api/admin/quizzes/<int:qid>/export.csv")
@admin_only
def export(qid):
    q = one(T("quizzes").select("title").eq("id", qid))
    if not q: return err("Quiz not found", 404)
    qs, rows = responses_for(qid)
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["response_id", "submitted_at_utc", "name", *[x["text"] for x in qs]])
    for r in rows: w.writerow([r["id"], r["created_at"], safe(r["name"]), *map(safe, r["answers"])])
    fn = re.sub(r"[^a-z0-9]+", "-", q["title"].lower()).strip("-") or "quiz"
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{fn}-responses.csv"'})

# ---------- admin: messages ----------
@app.get("/api/admin/messages")
@admin_only
def messages():
    data = rows(T("messages").select("*,quizzes(title)").order("created_at", desc=True).order("id", desc=True))
    return jsonify([{**{k: m[k] for k in ("id", "quiz_id", "response_id", "name", "body", "created_at")},
                     "quiz": (m["quizzes"] or {}).get("title", ""), "is_read": bool(m["is_read"])} for m in data])

@app.patch("/api/admin/messages/<int:mid>")
@admin_only
def mark(mid):
    T("messages").update({"is_read": int(bool((request.get_json(silent=True) or {}).get("is_read")))}).eq("id", mid).execute()
    return jsonify(ok=True)

@app.delete("/api/admin/messages/<int:mid>")
@admin_only
def del_msg(mid):
    T("messages").delete().eq("id", mid).execute(); return jsonify(ok=True)

@app.after_request
def headers(r):
    r.headers["X-Content-Type-Options"] = "nosniff"; r.headers["X-Frame-Options"] = "DENY"
    r.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith("/api/admin") or request.path == "/admin": r.headers["Cache-Control"] = "no-store"
    return r

if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5000)), debug=False)
