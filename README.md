# Nayan Quiz
Flask + Supabase. Share a quiz link, collect answers, read them at `/admin`.
Quizzes, questions, responses, answers and Nayan messages are stored in your Supabase project.

## 1. Supabase
1. Create a project at supabase.com.
2. SQL Editor > New query > paste `supabase_schema.sql` > Run. This creates the tables and turns on
   Row Level Security with no policies, so the public anon key cannot read anything.
3. Project Settings > API: copy the **Project URL** and the **service_role** key.
   The service_role key is a secret: use it only as a server env var, never in frontend code or git.

## 2. Environment variables
    SECRET_KEY=...                  # long random string, signs the admin session
    ADMIN_PASSWORD=...              # your admin login
    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_SERVICE_ROLE_KEY=...
    COOKIE_SECURE=1                 # use 0 only on http://localhost

## 3. Run locally
    pip install -r requirements.txt
    (export the variables above, COOKIE_SECURE=0)
    python app.py                   # http://localhost:5000/admin

## 4. Deploy (Render / Railway / Fly)
Build: `pip install -r requirements.txt`. Start: `gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT`.
Add the env vars above. No disk is needed because data lives in Supabase.

## Notes
- `test_flow.py` runs the full flow against the Supabase project in your env vars and leaves a test quiz called "Friends" behind. Use a separate test project, not production.
- Supabase's API returns at most 1000 rows per request; responses lists are capped at 1000 per quiz.
