const api = (path, opts) => fetch(path, opts).then(r => {
  if (!r.ok) return r.json().then(e => { throw new Error(e.detail || r.statusText); });
  return r.json();
});

// ---- Tabs ----
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'history') loadTrendParticipants();
    if (btn.dataset.tab !== 'sessions' && speechPollTimer) {
      clearInterval(speechPollTimer);
      speechPollTimer = null;
    } else if (btn.dataset.tab === 'sessions' && currentSessionId && !speechPollTimer) {
      speechPollTimer = setInterval(() => loadSpeeches(currentSessionId), 4000);
    }
  });
});

// ---- Participants ----
async function loadParticipants() {
  const list = await api('/api/participants/');
  const tbody = document.querySelector('#participants-table tbody');
  tbody.innerHTML = '';
  for (const p of list) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${p.name}</td><td>${p.aliases || ''}</td><td>${p.club_role}</td><td>${p.email || ''}</td>
      <td><button data-id="${p.id}" class="remove-participant">Remove</button></td>`;
    tbody.appendChild(tr);
  }
  document.querySelectorAll('.remove-participant').forEach(b => b.addEventListener('click', async () => {
    await api(`/api/participants/${b.dataset.id}`, { method: 'DELETE' });
    loadParticipants();
  }));

  // also refresh the upload-form + "now speaking" dropdowns
  for (const selId of ['ingest-participant-select', 'current-speaker-select']) {
    const sel = document.getElementById(selId);
    const placeholder = sel.querySelector('option').outerHTML;
    sel.innerHTML = placeholder;
    for (const p of list) {
      const opt = document.createElement('option');
      opt.value = p.id; opt.textContent = p.name;
      sel.appendChild(opt);
    }
  }
}

document.getElementById('participant-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await api('/api/participants/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.fromEntries(fd)),
  });
  e.target.reset();
  loadParticipants();
});

// ---- Sessions ----
let currentSessionId = null;
let speechPollTimer = null;

async function loadSessions() {
  const list = await api('/api/sessions');
  const tbody = document.querySelector('#sessions-table tbody');
  tbody.innerHTML = '';
  for (const s of list) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${new Date(s.date).toLocaleString()}</td><td>${s.title}</td><td>${s.status}</td>
      <td><button data-id="${s.id}" class="open-session">Open</button></td>`;
    tbody.appendChild(tr);
  }
  document.querySelectorAll('.open-session').forEach(b => b.addEventListener('click', () => openSession(b.dataset.id)));
}

document.getElementById('session-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const s = await api('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.fromEntries(fd)),
  });
  e.target.reset();
  await loadSessions();
  openSession(s.id);
});

async function openSession(id) {
  if (listenState.active && currentSessionId !== id) stopListening();
  currentSessionId = id;
  document.getElementById('session-detail').style.display = 'block';
  document.querySelector('#ingest-audio-form [name=session_id]').value = id;
  await loadSpeeches(id);
  await refreshCurrentSpeakerStatus(id);
  await refreshSessionStatus(id);

  if (speechPollTimer) clearInterval(speechPollTimer);
  speechPollTimer = setInterval(() => loadSpeeches(currentSessionId), 4000);
}

async function refreshSessionStatus(id) {
  const list = await api('/api/sessions');
  const s = list.find(x => x.id == id);
  const label = document.getElementById('session-status-label');
  const btn = document.getElementById('complete-session-btn');
  if (!s) return;
  label.textContent = s.status;
  const isCompleted = s.status === 'completed';
  btn.style.display = isCompleted ? 'none' : '';
  document.getElementById('start-listening-btn').disabled = isCompleted;
}

document.getElementById('complete-session-btn').addEventListener('click', async () => {
  if (!currentSessionId) return;
  if (listenState.active) stopListening();
  await api(`/api/sessions/${currentSessionId}/complete`, { method: 'POST' });
  await refreshSessionStatus(currentSessionId);
  await loadSessions();
});

async function refreshCurrentSpeakerStatus(sessionId) {
  const cur = await api(`/api/sessions/${sessionId}/current-speaker`);
  const statusEl = document.getElementById('current-speaker-status');
  statusEl.textContent = cur.name ? `Currently: ${cur.name}` : '(auto-detect from audio)';
  document.getElementById('current-speaker-select').value = cur.participant_id || '';
}

document.getElementById('set-current-speaker-btn').addEventListener('click', async () => {
  const sel = document.getElementById('current-speaker-select');
  const participant_id = sel.value ? parseInt(sel.value) : null;
  await api(`/api/sessions/${currentSessionId}/current-speaker`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participant_id }),
  });
  refreshCurrentSpeakerStatus(currentSessionId);
});

function scoreColor(score) {
  if (score >= 8) return '#2e7d32';
  if (score >= 6) return '#f9a825';
  return '#c62828';
}

async function loadSpeeches(sessionId) {
  const list = await api(`/api/sessions/${sessionId}/speeches`);
  const tbody = document.querySelector('#speeches-table tbody');
  tbody.innerHTML = '';
  for (const sp of list) {
    const tr = document.createElement('tr');
    const hasEval = !!sp.evaluation;
    const score = hasEval ? sp.evaluation.score_total : '-';
    const color = hasEval ? scoreColor(sp.evaluation.score_total) : '#999';
    const canEmail = hasEval && sp.participant_id;
    const alreadySent = hasEval && sp.evaluation.email_sent;

    let emailCell = '<span class="hint">no matched participant</span>';
    if (canEmail) {
      emailCell = alreadySent
        ? `<span class="hint">Sent ✓</span>`
        : `<button data-id="${sp.id}" class="send-email-btn">Send to participant</button>`;
    }

    tr.innerHTML = `
      <td>${sp.speaker_name_raw || '(unmatched)'}</td>
      <td>${sp.speech_type}</td>
      <td>${Math.round(sp.duration_seconds)}s</td>
      <td>${sp.words_per_minute}</td>
      <td><strong>${sp.filler_total}</strong> <span class="hint">(${sp.filler_rate_per_100_words}/100w)</span></td>
      <td><span class="score-pill" style="background:${color}">${score}</span></td>
      <td>
        <pre class="feedback">${hasEval ? sp.evaluation.feedback_text : ''}</pre>
        <details><summary class="hint">Show transcript</summary><p class="hint">${sp.transcript || ''}</p></details>
      </td>
      <td>${emailCell}</td>
    `;
    tbody.appendChild(tr);
  }
  document.querySelectorAll('.send-email-btn').forEach(b => b.addEventListener('click', async () => {
    b.disabled = true; b.textContent = 'Sending...';
    try {
      await api(`/api/speeches/${b.dataset.id}/send-email`, { method: 'POST' });
      loadSpeeches(currentSessionId);
    } catch (err) {
      alert('Could not send email: ' + err.message);
      b.disabled = false; b.textContent = 'Send to participant';
    }
  }));
}

document.getElementById('ingest-audio-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await fetch('/api/speeches/ingest-audio', { method: 'POST', body: fd }).then(r => {
    if (!r.ok) return r.json().then(err => { throw new Error(err.detail); });
    return r.json();
  });
  e.target.reset();
  document.querySelector('#ingest-audio-form [name=session_id]').value = currentSessionId;
  loadSpeeches(currentSessionId);
});

// ---- In-browser live listening (no install, no terminal) ----
// Captures TWO audio sources and mixes them into one stream:
//   1. The room microphone -- for people physically in the room.
//   2. System/Zoom audio via the screen-share picker ("Share audio" /
//      "Share system audio" checkbox) -- for remote participants.
// Either source is optional (e.g. cancel the screen-share picker for an
// in-person-only meeting, or it still works with no mic if that's denied).
// Watches the mixed levels to detect when someone starts/stops talking
// (same logic as listener/listen_and_score.py, just in JS), and uploads
// each finished turn straight to /api/speeches/ingest-audio.
const VAD = {
  FRAME_MS: 100,
  CALIBRATION_MS: 2000,
  // How long a silence has to last before we decide the turn is over. 1200ms
  // was too trigger-happy -- a normal thinking pause in a Table Topics
  // answer easily runs past 1.2s, so one continuous answer was getting
  // chopped into 2-3 separate "speeches" (confirmed live: two answers
  // produced four rows). 2500ms tolerates a real pause while still closing
  // the turn promptly once someone actually stops talking.
  SILENCE_HANGOVER_MS: 2500,
  MIN_TURN_MS: 3000,
  MAX_TURN_MS: 480000,
};

let listenState = {
  active: false,
  stream: null,      // merged stream (mic + system audio), used for VAD + recording
  rawStreams: [],     // original source streams, kept only to stop their tracks on cleanup
  audioCtx: null,
  analyser: null,
  vadTimer: null,
  noiseFloor: 0,
  threshold: 0,
  calibrating: true,
  speaking: false,
  silenceMs: 0,
  turnStartedAt: null,
  recorder: null,
};

function logLine(msg) {
  const box = document.getElementById('listen-log');
  box.style.display = 'block';
  const time = new Date().toLocaleTimeString();
  box.textContent = `[${time}] ${msg}\n` + box.textContent;
}

function setListenStatus(text) {
  document.getElementById('listen-status').textContent = text;
}

async function startListening() {
  // Require a speaker to be selected first -- otherwise every turn is
  // saved as "(unmatched)" with no participant attached, which is much
  // harder to fix after the fact than just picking a name up front.
  const speakerSel = document.getElementById('current-speaker-select');
  if (!speakerSel.value) {
    alert('Please select who\'s speaking first: use the "Now speaking" dropdown above and click "Set", then start listening.');
    return;
  }

  const sources = [];

  // Source 1: room microphone (in-person speakers). Browsers apply echo
  // cancellation by default, which helps avoid the mic picking up Zoom
  // audio played back through the room's speakers.
  if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
    try {
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      sources.push(micStream);
      logLine('Microphone connected (captures anyone speaking in the room).');
    } catch (err) {
      logLine('Microphone not available/denied: ' + err.message);
    }
  }

  // Source 2: Zoom / system audio, via the screen-share picker. Optional --
  // cancel the picker to skip this for an in-person-only meeting.
  if (navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia) {
    try {
      const displayStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      displayStream.getVideoTracks().forEach(t => t.stop()); // we only need audio
      const audioTracks = displayStream.getAudioTracks();
      if (audioTracks.length > 0) {
        sources.push(new MediaStream(audioTracks));
        logLine('System/Zoom audio connected (captures remote participants).');
      } else {
        displayStream.getTracks().forEach(t => t.stop());
        logLine('Screen share had no audio ("Share audio" wasn\'t checked) -- continuing without Zoom audio.');
      }
    } catch (err) {
      logLine('Skipped Zoom/system audio (screen share cancelled or unsupported) -- continuing with microphone only.');
    }
  }

  if (sources.length === 0) {
    alert('No audio source available. Allow microphone access, or share your screen with audio, and try again.');
    return;
  }

  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const destination = audioCtx.createMediaStreamDestination();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 2048;

  // Mix every connected source into one merged stream: each source feeds
  // both the recording destination and the level-meter used for VAD.
  sources.forEach((s) => {
    const node = audioCtx.createMediaStreamSource(s);
    node.connect(destination);
    node.connect(analyser);
  });

  listenState = {
    active: true,
    stream: destination.stream,
    rawStreams: sources,
    audioCtx,
    analyser,
    vadTimer: null,
    noiseFloor: 0,
    threshold: 0.003,
    calibrating: true,
    speaking: false,
    silenceMs: 0,
    turnStartedAt: null,
    recorder: null,
  };

  document.getElementById('start-listening-btn').style.display = 'none';
  document.getElementById('stop-listening-btn').style.display = 'inline-block';
  setListenStatus('Calibrating ambient noise -- keep it quiet for a moment...');
  logLine('Listening started.');

  const calibSamples = [];
  const calibEndAt = Date.now() + VAD.CALIBRATION_MS;

  listenState.vadTimer = setInterval(() => {
    if (!listenState.active) return;
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += Math.abs(data[i]);
    const level = sum / data.length;

    if (listenState.calibrating) {
      calibSamples.push(level);
      if (Date.now() >= calibEndAt) {
        const floor = calibSamples.reduce((a, b) => a + b, 0) / calibSamples.length;
        listenState.noiseFloor = floor;
        listenState.threshold = Math.max(floor * 4, 0.003);
        listenState.calibrating = false;
        setListenStatus('Listening...');
        logLine(`Calibrated. Noise floor ${floor.toFixed(5)}, threshold ${listenState.threshold.toFixed(5)}`);
      }
      return;
    }

    const isLoud = level > listenState.threshold;
    if (!listenState.speaking) {
      if (isLoud) startTurn();
    } else {
      listenState.silenceMs = isLoud ? 0 : listenState.silenceMs + VAD.FRAME_MS;
      const elapsed = Date.now() - listenState.turnStartedAt;
      if (listenState.silenceMs >= VAD.SILENCE_HANGOVER_MS || elapsed >= VAD.MAX_TURN_MS) {
        endTurn();
      }
    }
  }, VAD.FRAME_MS);
}

function startTurn() {
  listenState.speaking = true;
  listenState.silenceMs = 0;
  listenState.turnStartedAt = Date.now();
  setListenStatus('Speech detected, recording turn...');
  logLine('Speech detected, recording turn...');

  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
  const recorder = new MediaRecorder(listenState.stream, { mimeType });
  const chunks = [];
  recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  recorder.onstop = () => {
    const durationMs = Date.now() - listenState.turnStartedAt;
    const blob = new Blob(chunks, { type: mimeType });
    if (durationMs >= VAD.MIN_TURN_MS) {
      uploadTurn(blob, durationMs / 1000);
    } else {
      logLine(`(discarded short blip, ${(durationMs / 1000).toFixed(1)}s)`);
    }
  };
  recorder.start();
  listenState.recorder = recorder;
}

function endTurn() {
  listenState.speaking = false;
  setListenStatus('Listening...');
  if (listenState.recorder && listenState.recorder.state !== 'inactive') {
    listenState.recorder.stop();
  }
  listenState.recorder = null;
}

async function uploadTurn(blob, durationSeconds) {
  const fd = new FormData();
  fd.append('session_id', currentSessionId);
  fd.append('speech_type', 'table_topic');
  fd.append('project_title', '');
  fd.append('target_min_seconds', 60);
  fd.append('target_max_seconds', 120);
  fd.append('speaker_name_raw', '');
  fd.append('duration_seconds', durationSeconds.toFixed(1));
  fd.append('file', blob, 'turn.webm');
  setListenStatus('Processing last turn (transcribing)...');
  logLine('Uploading & transcribing turn -- this takes a few seconds, listening continues in the background...');
  try {
    const resp = await fetch('/api/speeches/ingest-audio', { method: 'POST', body: fd });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const result = await resp.json();
    const score = result.evaluation ? result.evaluation.score_total : '?';
    const speaker = result.speaker_name_raw || '(unmatched)';
    logLine(`Turn uploaded (${durationSeconds.toFixed(0)}s): speaker=${speaker} score=${score} fillers=${result.filler_total}`);
    loadSpeeches(currentSessionId);
  } catch (err) {
    logLine('Upload failed: ' + err.message);
  } finally {
    if (listenState.active) setListenStatus('Listening...');
  }
}

function stopListening() {
  if (listenState.vadTimer) clearInterval(listenState.vadTimer);
  if (listenState.recorder && listenState.recorder.state !== 'inactive') listenState.recorder.stop();
  // Stop the ORIGINAL mic/display tracks (not just the merged destination
  // stream) so the browser actually releases the mic and ends the screen
  // share -- the merged stream's own tracks don't control that.
  (listenState.rawStreams || []).forEach(s => s.getTracks().forEach(t => t.stop()));
  if (listenState.audioCtx) listenState.audioCtx.close();
  listenState.active = false;
  document.getElementById('start-listening-btn').style.display = 'inline-block';
  document.getElementById('stop-listening-btn').style.display = 'none';
  setListenStatus('Not listening.');
  logLine('Listening stopped.');
}

document.getElementById('start-listening-btn').addEventListener('click', startListening);
document.getElementById('stop-listening-btn').addEventListener('click', stopListening);

// ---- History / Trends ----
let trendChart = null;

async function loadTrendParticipants() {
  const list = await api('/api/participants/');
  const sel = document.getElementById('trend-participant-select');
  sel.innerHTML = '';
  for (const p of list) {
    const opt = document.createElement('option');
    opt.value = p.id; opt.textContent = p.name;
    sel.appendChild(opt);
  }
  sel.onchange = () => loadTrend(sel.value);
  if (list.length) loadTrend(list[0].id);
}

async function loadTrend(participantId) {
  const points = await api(`/api/participants/${participantId}/trend`);
  const labels = points.map(p => new Date(p.date).toLocaleDateString());
  const scores = points.map(p => p.score_total);
  const fillerRates = points.map(p => p.filler_rate_per_100_words);

  const ctx = document.getElementById('trend-chart').getContext('2d');
  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Overall score (0-10)', data: scores, borderColor: '#772432', yAxisID: 'y' },
        { label: 'Filler words / 100 words', data: fillerRates, borderColor: '#f9a825', yAxisID: 'y1' },
      ],
    },
    options: {
      scales: {
        y: { position: 'left', min: 0, max: 10, title: { display: true, text: 'Score' } },
        y1: { position: 'right', min: 0, title: { display: true, text: 'Fillers/100w' }, grid: { drawOnChartArea: false } },
      },
    },
  });
}

loadParticipants();
loadSessions();
