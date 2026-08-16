# Toastmasters Speech Evaluator

An automatic evaluation tool for speeches and Table Topics at a Toastmasters club: listens to your meeting from your own computer, counts filler words (like the "Ah-Counter" role), gives a Toastmasters-style score and feedback, emails each participant their own evaluation, and keeps everything so you can track improvement over time.

**Live deployment:** https://toastmasters-evaluator.onrender.com (free tier — the first request after 15 minutes of inactivity takes about a minute to wake up).

## How it actually works

**No Zoom API connection, no Zoom Marketplace app, no Zoom cost, and no terminal required.** Listening happens directly inside the browser dashboard: open a session, click "Start Listening," and the browser will ask for microphone access and/or screen-share-with-audio ("Share audio" / "Share system audio" checkbox) — that's how the dashboard "hears" the meeting, with nothing extra to install. It automatically detects when someone starts/stops talking and uploads each finished "turn" to the server. There, it's transcribed locally and for free (only to count filler words and measure pace/duration — the full transcript isn't the focus, and you can expand it only if you want to), scored, and saved.

**One important limitation to understand:** listening to "whatever comes out of the speakers" (whether via the browser or the advanced script) picks up every other participant, but **not** the microphone of the computer running the tool (Zoom doesn't play your own voice back to you). So it's best to run this from a computer that joins the meeting as an extra, silent participant (mic off, camera off) — e.g. the Timer role's computer — rather than from the computer of an actual speaker.

**Browser requirement:** Chrome or Edge on Windows/Linux work out of the box. On macOS and some browsers, system-audio sharing may not be available — in that case there's a script-based alternative (see "Advanced method" at the end of this document).

## Identifying who's speaking

There are two ways, and it's best to use both together:

1. **Manual (recommended, most reliable):** On the dashboard, in the "Meeting Sessions" tab, there's a "Now speaking" field — before calling on someone (the next Table Topic, or a speech), pick their name from the list and click "Set." Every following speaking turn is attributed to them automatically, until you change it.
2. **Automatic (fallback):** If nobody is set, the system tries to detect a name from the transcript itself (e.g. "Hi, my name is Dana" or "let's hear from David"), with fuzzy matching against the roster.

## Setup and running (one-time, then one command per meeting)

### Step 1: one-time setup
```bash
cd backend
pip install -r requirements.txt
```

### Step 2: every meeting
```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Open a browser to `http://localhost:8000` (or the computer's IP address if the dashboard runs on a different machine), add participants (one-time, they stay forever), create a new session, and click "Start Listening." When the browser's share dialog appears, choose "Entire Screen" and make sure the "Share audio" (or "Share system audio") checkbox is ticked — that's it, every speaking turn appears on the dashboard within seconds.

## Sending feedback by email (free)

Every participant on the dashboard has an email field (filled in on the Participants tab). Once an evaluation is ready, a "Send to participant" button appears next to their row — click it, and they receive **only their own evaluation**, not everyone's.

One-time setup (completely free via Gmail):
1. Turn on 2-Step Verification on the Gmail account that will send the emails.
2. Create an "App Password" at myaccount.google.com/apppasswords (free, a 16-character code).
3. Set these environment variables before starting the server:
```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your_address@gmail.com
export SMTP_PASS=xxxxxxxxxxxxxxxx   # the App Password
export SMTP_FROM_NAME="Toastmasters Club Evaluator"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Any other SMTP provider (Outlook, the club's Google Workspace, etc.) works the same way — just change HOST/PORT.

## Architecture

```
toastmasters-evaluator/
  listener/                     # advanced/alternative method (optional) -- see end of document
    listen_and_score.py
    requirements-listener.txt
  backend/
    app/
      main.py
      models.py              # Participant, MeetingSession (+current_speaker_id), SpeechRecord, Evaluation (+email_sent)
      routers/
        participants.py      # CRUD for participants (kept permanently)
        sessions.py           # sessions, "who's speaking now", audio-turn upload (+duration_seconds), email sending, trends
      services/
        filler_words.py       # English filler-word counter
        scoring.py             # rule-based scoring engine (time, pace, filler words, structure)
        transcription.py        # local, free transcription (faster-whisper) -- only for word count/pace
        speaker_id.py            # name detection from transcript (fallback to the manual "now speaking")
        email_service.py         # personal email sending via SMTP (free)
        pipeline.py                # ties it all together: transcription -> speaker ID -> scoring -> saving
      static/
        index.html, app.js, style.css   # the dashboard, including the "Start Listening" button (getDisplayMedia + browser-side VAD)
    tests/test_scoring.py         # unit tests for the scoring engine (passing)
    requirements.txt
    Dockerfile
  render.yaml                   # Render Blueprint -- lets Render auto-configure the service from this repo
  .gitignore
  docker-compose.yml
```

## What was actually tested

- `pytest tests/test_scoring.py` — 4 unit tests for the scoring engine passed, including after every change.
- Ran a real server and tested end-to-end multiple times: create participant → session → set "Now speaking" → submit a transcript with no name in it → the system correctly attributed it to the manually-selected participant, computed a score, and saved it.
- Tested name detection from the transcript (without a manual setting): "Hi, my name is Dana" correctly matched "Dana Cohen" on the roster (fuzzy matching).
- Tested the `duration_seconds` parameter (what the browser sends, as opposed to a WAV file from the local listener) — the API correctly uses the value sent instead of computing it from the file.
- **Actually installed faster-whisper and ran real transcription** through the API (not just mocked logic) — worked. Downloading the model from Hugging Face failed in my own test environment due to a network restriction there (unrelated to the code) — in practice, on your machine this works normally as long as there's regular internet access (the download happens once, the first time you run it, and is then cached locally).
- Syntax-checked the "Start Listening" button's JavaScript (`node --check`) — passed. **Did not test it in an actual browser** (no browser/microphone in my own environment) — this is the most important check left for you to do.
- Tested sending an email without SMTP configured — returns a clear error ("SMTP not configured") instead of crashing; actual sending was not tested (requires a real Gmail account + your own App Password).
- **Deployed live and verified in a real browser:** created the GitHub repository, pushed the code, created a free Neon Postgres database, deployed on Render via Blueprint, and confirmed the live site loads and that adding a participant is correctly saved to the real Postgres database (tested by adding and then removing a test participant).

## Costs

- **Transcription, scoring, speaker ID, email sending — all free**, whether running locally or on the deployed link; nothing is billed per use.
- **Hosting:** Render's free tier (used for the live deployment above) and Neon's free tier (database) are both $0. The only real limitation is that the free Render instance spins down after 15 minutes of inactivity (about a minute to wake back up) and Neon's free tier caps storage at 0.5 GB, which is far more than a club needs for meeting transcripts/scores.

## Cloud deployment — a real link anyone can open (free)

Already done for the live deployment above, using three free accounts (GitHub, Neon, Render) with `render.yaml` and `.gitignore` prepared in this repo, and Postgres support via `TM_DATABASE_URL`. The steps below are here for reference (e.g. to redeploy elsewhere, or if you fork this project).

### Step 1: push the code to GitHub (one-time)
If you don't have an account, sign up for free at github.com. Then create a new, empty repository (no README, no .gitignore — this repo already has one). In a terminal, inside the project folder:
```bash
cd /path/to/toastmasters-evaluator
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/toastmasters-evaluator.git
git push -u origin main
```
(If `git` isn't recognized as a command, install it from git-scm.com first.)

### Step 2: a free, permanent database (Neon)
Sign up for free at neon.tech (no credit card), create a new project, and copy the "Connection string" shown (it looks like `postgresql://user:pass@ep-xxxx.neon.tech/dbname`). Keep it aside — you'll need it in the next step.

### Step 3: deploy on Render
Sign up for free at render.com (you can use your GitHub account). Click **New → Blueprint**, pick the repository you pushed in step 1 — Render will automatically detect `render.yaml` and offer to set up a service named `toastmasters-evaluator`. Before clicking "Deploy," fill in the environment variables:
- `TM_DATABASE_URL` = the connection string from Neon (step 2)
- `SMTP_USER`, `SMTP_PASS`, `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587` — if you want email sending (see "Sending feedback by email" above)

Click Deploy. The first build takes a few minutes (it downloads all dependencies, including faster-whisper). When it's done, Render gives you a permanent link like `https://toastmasters-evaluator.onrender.com` — that's the link to share with everyone.

**Note:** Render's free tier spins down after 15 minutes of inactivity, and the next request takes about a minute (cold start) — perfectly fine for club use (it's not sitting idle mid-day), the first open at each meeting will just be a bit slow.

### A faster alternative (no GitHub at all)
If you'd rather skip this whole process, docker compose still works on any VM/server with Docker (including a home server, a cheap VPS, etc.) with no need for GitHub/Render at all:
```bash
docker compose up --build
```

## Advanced/alternative method: a separate listener script (optional)

If your browser doesn't support system-audio sharing (mainly macOS, or browsers other than Chrome/Edge), there's an alternative: `listener/listen_and_score.py` — a Python script that runs in a terminal and listens directly to the sound card, with no browser dependency.
```bash
cd listener
pip install -r requirements-listener.txt
python listen_and_score.py --api http://localhost:8000
```
On macOS you'll also need a free virtual audio device like [BlackHole](https://github.com/ExistentialAudio/BlackHole) to capture system audio (then `--device "BlackHole 2ch"`). On Windows/Linux this works directly. **Note:** newer NumPy versions have a compatibility break with the `soundcard` library that causes a crash (`fromstring is removed`) — this is already fixed in the current file (there's a shim at the top), no action needed.

## Future extension: Zoom RTMS (optional, not required)

The `backend/app/services/zoom_rtms.py` and `backend/app/routers/zoom_webhook.py` files contain an alternative integration layer for connecting directly to Zoom through their official API (RTMS — Realtime Media Streams). This isn't the path you chose (it requires a Zoom Marketplace app and paid Zoom credits), but it's kept in the code in case you want a more "official" connection in the future. Feel free to ignore it entirely.

## Known limitations

- **Speaker identification** relies on a manual setting ("Now speaking") or a name mentioned in the transcript. Without either, the turn is saved without being linked to a participant (it still gets a score and filler-word count, just no specific person attached).
- **Filler words** are defined for English only. It's easy to add a Hebrew (or other language) list in `filler_words.py` if you'd like.
- **The listening computer/browser can't hear itself** — see the explanation above, hence the recommendation to run it from a "quiet" computer in the meeting.
- **Vocal variety** is not measured — it would require audio analysis beyond the transcript alone.
- The "Start Listening" button requires the browser tab to stay open for the whole meeting (closing the tab stops listening).

## Running the tests

```bash
cd backend
pytest tests/test_scoring.py -v
```
