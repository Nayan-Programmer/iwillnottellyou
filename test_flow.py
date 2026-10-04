import os, tempfile
os.environ.update(SECRET_KEY="t", ADMIN_PASSWORD="pw", COOKIE_SECURE="0")  # needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY set; writes real rows
from app import app
c = app.test_client(); H = {"X-Requested-With": "fetch"}
def ok(r, code=200):
    assert r.status_code == code, (r.status_code, r.get_data(as_text=True)); return r.get_json() if r.is_json else r
assert c.get("/api/admin/quizzes").status_code == 401
ok(c.post("/api/admin/login", json={"password": "bad"}), 401)
ok(c.post("/api/admin/login", json={"password": "pw"}))
ok(c.post("/api/admin/quizzes", json={"title": "x", "questions": [{"text": "a", "type": "text"}]}, headers=H), 400)
ok(c.post("/api/admin/quizzes", json={"title": "x"}))  if False else None
assert c.post("/api/admin/quizzes", json={"title":"x"}).status_code == 403  # CSRF guard
q = ok(c.post("/api/admin/quizzes", headers=H, json={"title": "Friends", "active": True, "show_answers": False, "ask_name": True, "questions": [
    {"text": "Fav color?", "type": "mc", "options": ["Red", "Blue"], "correct": "Blue"}, {"text": "Why?", "type": "text"}]}))
slug = q["slug"]
pub = ok(c.get(f"/api/quiz/{slug}")); assert "correct" not in str(pub) and len(pub["questions"]) == 2
p = app.test_client()  # anonymous participant
assert p.get("/api/admin/quizzes").status_code == 401
ids = [x["id"] for x in pub["questions"]]
ok(p.post(f"/api/quiz/{slug}/submit", json={"name": "Ann", "answers": {str(ids[0]): "Blue"}}), 400)  # missing answer
r = ok(p.post(f"/api/quiz/{slug}/submit", json={"name": "Ann", "answers": {str(ids[0]): "Blue", str(ids[1]): "=cmd|x"}}))
assert "results" not in r
ok(p.post("/api/message", json={"response_id": r["response_id"], "body": "Hi Nayan!"}))
ok(p.post("/api/message", json={"response_id": r["response_id"], "body": "again"}), 409)
d = ok(c.get(f"/api/admin/quizzes/{q['id']}/responses")); assert d["total"] == 1 and d["stats"][0]["distribution"]["Blue"] == 1
assert ok(c.get(f"/api/admin/quizzes/{q['id']}/responses?q=zzz"))["responses"] == []
m = ok(c.get("/api/admin/messages")); assert m[0]["body"] == "Hi Nayan!" and m[0]["name"] == "Ann" and m[0]["quiz"] == "Friends" and not m[0]["is_read"]
ok(c.patch(f"/api/admin/messages/{m[0]['id']}", json={"is_read": True}, headers=H)); assert ok(c.get("/api/admin/messages"))[0]["is_read"]
csvr = ok(c.get(f"/api/admin/quizzes/{q['id']}/export.csv")); t = csvr.get_data(as_text=True); assert "Ann" in t and "'=cmd" in t
ok(c.patch(f"/api/admin/quizzes/{q['id']}", json={"show_answers": True}, headers=H))
r2 = ok(p.post(f"/api/quiz/{slug}/submit", json={"name": "Bob", "answers": {str(ids[0]): "Red", str(ids[1]): "x"}})); assert r2["results"][0]["is_correct"] is False
ok(c.patch(f"/api/admin/quizzes/{q['id']}", json={"active": False}, headers=H)); ok(p.get(f"/api/quiz/{slug}"), 403)
ok(c.delete(f"/api/admin/responses/{r2['response_id']}", headers=H)); assert ok(c.get(f"/api/admin/quizzes/{q['id']}/responses"))["total"] == 1
ok(c.delete(f"/api/admin/messages/{m[0]['id']}", headers=H)); assert ok(c.get("/api/admin/messages")) == []
for path in ("/", f"/q/{slug}", "/admin", "/static/style.css"): ok(p.get(path))
print("ALL FLOW CHECKS PASSED")
