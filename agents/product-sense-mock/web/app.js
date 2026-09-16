// Product Sense Mock: the browser side.
//
// The page never talks to Claude and never sees the API key. It sends answers
// to web.py and renders the events that come back. Everything user- or
// model-supplied goes in through textContent, never innerHTML.

const $ = (selector) => document.querySelector(selector);

const app = {
  config: null,
  id: null,
  session: null,
  busy: false,
  thinkingTimer: null,
};

// --- requests ---------------------------------------------------------------

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    const error = new Error('Could not reach the server. Is web.py still running?');
    error.retryable = true;
    throw error;
  }
  let data;
  try {
    data = await response.json();
  } catch {
    data = { error: `The server returned ${response.status}.` };
  }
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status}).`);
    error.status = response.status;
    error.retryable = Boolean(data.retryable) || response.status === 502;
    throw error;
  }
  return data;
}

// --- helpers ----------------------------------------------------------------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function show(screen) {
  for (const id of ['setup-screen', 'interview-screen', 'debrief-screen']) {
    $(`#${id}`).hidden = id !== screen;
  }
  $('#restart').hidden = screen === 'setup-screen';
  window.scrollTo({ top: 0 });
}

// Stage names come from the server, so the page never goes out of step with
// interview.py. A dimension is shown by the name of the stage that scores it.
function stageLabel(key) {
  const stage = app.config.stages.find((s) => s.key === key);
  return stage ? stage.label : key;
}

function dimensionLabel(dimension) {
  const stage = app.config.stages.find((s) => s.dimension === dimension);
  return stage ? stage.label : dimension.replace(/_/g, ' ');
}

function radio(name, value, checked, title, detail) {
  const choice = el('label', 'choice');
  const input = el('input');
  input.type = 'radio';
  input.name = name;
  input.value = value;
  input.checked = checked;
  const text = el('span');
  if (detail) text.append(el('small', 'prompt-key', detail));
  text.append(el('strong', null, title));
  choice.append(input, text);
  return choice;
}

const LEVEL_DETAIL = {
  pm: 'Mission and a north star are enough for Strategy.',
  senior: 'Strategy also needs why this company, the competitive gap, and the longer arc.',
};

// --- setup ------------------------------------------------------------------

async function init() {
  try {
    app.config = await api('/api/config');
  } catch (error) {
    showSetupError(error.message);
    $('#start').disabled = true;
    return;
  }

  const choices = $('#prompt-choices');
  for (const prompt of app.config.prompts) {
    choices.append(radio(
      'prompt', prompt.key, prompt.key === app.config.default_prompt,
      prompt.question, prompt.key.replace(/-/g, ' '),
    ));
  }

  const levels = $('#level-choices');
  for (const level of app.config.levels) {
    const choice = radio('level', level.key, level.key === app.config.default_level, level.label);
    const detail = LEVEL_DETAIL[level.key];
    if (detail) choice.querySelector('span').append(el('small', null, detail));
    levels.append(choice);
  }

  const files = app.config.context_files;
  $('#context-note').textContent = files.length
    ? `Claude will also judge against your reference files: ${files.join(', ')}.`
    : 'No reference files found, so Claude judges from the built-in rubric only.';

  const updateWarning = () => {
    const live = document.querySelector('input[name=mode]:checked').value === 'live';
    $('#live-warning').hidden = !live || app.config.live_available;
    $('#context-note').hidden = !live;
  };
  for (const input of document.querySelectorAll('input[name=mode]')) {
    input.addEventListener('change', updateWarning);
  }
  if (!app.config.live_available) {
    document.querySelector('input[name=mode][value=offline]').checked = true;
  }
  updateWarning();
}

function showSetupError(message) {
  const node = $('#setup-error');
  node.textContent = message;
  node.hidden = !message;
}

async function startInterview(event) {
  event.preventDefault();
  if (app.busy) return;
  const prompt = document.querySelector('input[name=prompt]:checked');
  const mode = document.querySelector('input[name=mode]:checked').value;
  const level = document.querySelector('input[name=level]:checked');
  if (!prompt || !level) {
    showSetupError('Pick a question and a level first.');
    return;
  }
  showSetupError('');

  const question = app.config.prompts.find((p) => p.key === prompt.value).question;
  const levelLabel = app.config.levels.find((l) => l.key === level.value).label;
  resetInterview(question, mode, levelLabel);
  show('interview-screen');
  setBusy(true, mode);

  try {
    const data = await api('/api/sessions', { prompt: prompt.value, mode, level: level.value });
    app.id = data.id;
    apply(data);
  } catch (error) {
    setBusy(false);
    show('setup-screen');
    showSetupError(error.message);
  }
}

// --- interview --------------------------------------------------------------

function resetInterview(question, mode, levelLabel) {
  app.id = null;
  app.session = null;
  $('#question').textContent = question;
  $('#transcript').replaceChildren();
  $('#answer').value = '';
  $('#mode-label').textContent = mode === 'live'
    ? `Interviewer: Claude (${app.config.model}). Level: ${levelLabel}.`
    : `Interviewer: offline script with keyword scoring. Level: ${levelLabel}.`;
  hideError();
  renderStages(app.config.stages, 0);
}

function renderStages(stages, index) {
  const list = $('#stages');
  list.replaceChildren();
  stages.forEach((stage, i) => {
    const item = el('li');
    if (i < index) item.classList.add('done');
    if (i === index) item.classList.add('active');
    const marker = el('b', null, i < index ? '✓' : String(i + 1));
    item.append(marker, el('span', 'stage-label', stage.label));
    if (i === index) item.setAttribute('aria-current', 'step');
    list.append(item);
  });
}

function addBubble(who, text, target = $('#transcript')) {
  const bubble = el('div', `bubble ${who}`);
  bubble.append(el('span', 'who', who === 'interviewer' ? 'INTERVIEWER' : 'YOU'), document.createTextNode(text));
  target.append(bubble);
  return bubble;
}

function summarizeTool(event) {
  if (event.is_error) return `Rejected: ${event.result.error}`;
  const input = event.input || {};
  switch (event.name) {
    case 'record_signal':
      return `Scored ${dimensionLabel(input.dimension)}: ${input.score} (${event.result.recorded.label})`;
    case 'advance_stage':
      return event.result.stage === 'debrief'
        ? 'All stages done'
        : `Moved on to ${stageLabel(event.result.stage)}`;
    case 'end_interview':
      return 'Filed the debrief';
    default:
      return event.name;
  }
}

function addEvent(event, target = $('#transcript')) {
  if (event.kind === 'interviewer') {
    addBubble('interviewer', event.text, target);
  } else if (event.kind === 'notice') {
    target.append(el('p', 'notice', event.text));
  } else if (event.kind === 'tool') {
    const note = el('details', event.is_error ? 'tool-note error' : 'tool-note');
    const summary = el('summary');
    summary.append(el('span', 'tool-name', event.name), el('span', null, summarizeTool(event)));
    const raw = el('pre', null, `input  ${JSON.stringify(event.input, null, 2)}\nresult ${JSON.stringify(event.result, null, 2)}`);
    note.append(summary, raw);
    target.append(note);
  }
}

function apply(data) {
  for (const event of data.events) addEvent(event);
  app.session = data.session;
  setBusy(false);

  const { stages, stage_index: index, done } = app.session;
  renderStages(stages, Math.min(index, stages.length));

  if (done) {
    renderDebrief();
    return;
  }
  if (!app.session.awaiting_answer) {
    showError('The interview stopped without asking a question.', true);
    return;
  }
  $('#answer').focus();
  scrollToLatest();
}

function setBusy(busy, mode) {
  app.busy = busy;
  const waiting = busy || !app.session || !app.session.awaiting_answer || app.session.done;
  $('#answer').disabled = waiting;
  $('#send').disabled = waiting;
  $('#quit').disabled = busy || !app.id;
  $('#thinking').hidden = !busy;

  clearTimeout(app.thinkingTimer);
  if (busy) {
    const live = (mode || (app.session && app.session.mode)) === 'live';
    $('#thinking-text').textContent = 'The interviewer is thinking';
    if (live) {
      app.thinkingTimer = setTimeout(() => {
        $('#thinking-text').textContent = 'Still thinking. Live turns can take up to a minute when the interviewer scores and moves stages.';
      }, 9000);
    }
    scrollToLatest();
  }
}

function scrollToLatest() {
  requestAnimationFrame(() => {
    $('#composer').scrollIntoView({ block: 'end', behavior: 'smooth' });
  });
}

function showError(message, retryable) {
  $('#error-text').textContent = message;
  $('#retry').hidden = !retryable;
  $('#error-bar').hidden = false;
}

function hideError() {
  $('#error-bar').hidden = true;
}

async function send(action, body) {
  if (app.busy || !app.id) return null;
  hideError();
  setBusy(true);
  try {
    const data = await api(`/api/sessions/${app.id}/${action}`, body || {});
    apply(data);
    return data;
  } catch (error) {
    // Anything but a 409 failed after the server accepted the request, so the
    // interviewer is no longer waiting for a fresh answer. Lock the composer
    // until "Try again" gets the next question.
    if (error.status !== 409 && app.session) app.session.awaiting_answer = false;
    setBusy(false);
    showError(error.message, error.retryable || error.status !== 409);
    throw error;
  }
}

async function submitAnswer(event) {
  event.preventDefault();
  const text = $('#answer').value.trim();
  if (!text || app.busy) return;

  const bubble = addBubble('candidate', text);
  $('#answer').value = '';
  try {
    await send('answer', { text });
  } catch (error) {
    // A 409 means the server refused the answer outright, so it was never
    // recorded: put it back. Any other failure happened after the server
    // stored it, and "Try again" continues from there.
    if (error.status === 409) {
      bubble.remove();
      $('#answer').value = text;
      setBusy(false);
    }
  }
}

async function quitInterview() {
  if (!app.id || app.busy) return;
  if (!window.confirm('End the interview now? You will get a debrief for what you covered so far.')) return;
  try {
    await send('quit');
  } catch {
    // error already shown
  }
}

async function retry() {
  try {
    await send('retry');
  } catch {
    // error already shown
  }
}

// --- debrief ----------------------------------------------------------------

function renderDebrief() {
  const { scorecard, debrief, prompt, mode, level, ended_reason: endedReason } = app.session;

  const interviewer = mode === 'live' ? 'Interviewed by Claude' : 'Offline script (keyword scoring)';
  $('#debrief-mode').textContent = `${interviewer} · Level: ${level.label}`;
  $('#debrief-headline').textContent = (debrief && debrief.headline) || endedReasonText(endedReason);
  $('#debrief-question').textContent = prompt.question;

  if (scorecard.assessed) {
    $('#debrief-score').textContent = `${scorecard.total} / ${scorecard.possible}`;
    $('#debrief-score-note').textContent = `across ${scorecard.assessed} assessed dimension${scorecard.assessed === 1 ? '' : 's'}`;
  } else {
    $('#debrief-score').textContent = '—';
    $('#debrief-score-note').textContent = 'nothing was assessed';
  }

  const body = $('#scorecard');
  body.replaceChildren();
  for (const row of scorecard.rows) {
    const tr = el('tr');
    const scoreCell = el('td');
    const chip = el(
      'span',
      `score-chip ${row.score === null ? 'score-none' : `score-${row.score}`}`,
      row.score === null ? 'not assessed' : `${row.score} ${row.label}`,
    );
    scoreCell.append(chip);
    tr.append(
      el('td', null, row.label_text),
      scoreCell,
      el('td', null, row.evidence || '—'),
      el('td', 'gap', row.gap || '—'),
    );
    body.append(tr);
  }

  fillList('#strengths', debrief && debrief.strengths);
  $('#strengths-panel').hidden = !(debrief && debrief.strengths && debrief.strengths.length);
  fillList('#improvements', debrief && debrief.improvements);
  $('#next-prompt').textContent = (debrief && debrief.next_prompt) || '';
  $('#next-panel').hidden = !(debrief && debrief.next_prompt);

  $('#download').href = `/api/sessions/${app.id}/debrief.md`;
  $('#download').hidden = !debrief;

  const final = $('#final-transcript');
  final.replaceChildren(...Array.from($('#transcript').children).map((node) => node.cloneNode(true)));

  show('debrief-screen');
}

function fillList(selector, items) {
  const list = $(selector);
  list.replaceChildren(...(items || []).map((item) => el('li', null, item)));
}

function endedReasonText(reason) {
  return {
    refusal: 'The interviewer declined to continue, so no debrief was filed.',
    max_tokens: 'A response ran too long, so the interview stopped before a debrief.',
    turn_limit: 'The interview hit its turn limit before a debrief was filed.',
  }[reason] || 'The interview ended.';
}

// --- wiring -----------------------------------------------------------------

function startOver() {
  if (app.busy) return;
  if (app.session && !app.session.done && !window.confirm('Leave this interview? It will not be saved.')) return;
  app.id = null;
  app.session = null;
  show('setup-screen');
}

document.addEventListener('DOMContentLoaded', () => {
  $('#setup-form').addEventListener('submit', startInterview);
  $('#composer').addEventListener('submit', submitAnswer);
  $('#quit').addEventListener('click', quitInterview);
  $('#retry').addEventListener('click', retry);
  $('#restart').addEventListener('click', startOver);
  $('#again').addEventListener('click', startOver);

  $('#answer').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      $('#composer').requestSubmit();
    }
  });

  const notes = $('#show-notes');
  const applyNotes = () => {
    $('#transcript').classList.toggle('hide-notes', !notes.checked);
    $('#final-transcript').classList.toggle('hide-notes', !notes.checked);
  };
  notes.addEventListener('change', applyNotes);
  applyNotes();

  init();
});
