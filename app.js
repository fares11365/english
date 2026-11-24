// ---------- Storage ----------
const STORE_KEY = "vocab-builder-v1";

function load() {
  try {
    const data = JSON.parse(localStorage.getItem(STORE_KEY));
    if (data && Array.isArray(data.words)) return data;
  } catch (e) { /* storage unavailable or corrupt */ }
  return {
    words: STARTER_WORDS.map((w, i) => ({ ...w, id: Date.now() + i, level: 0, due: 0 })),
  };
}
function save() {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* ignore */ }
}

let state = load();

// Simple spaced repetition: level 0..5, each level waits longer before the card returns.
const INTERVALS_MIN = [0, 1, 10, 60 * 24, 60 * 24 * 3, 60 * 24 * 7];
const MASTERED = INTERVALS_MIN.length - 1;

const $ = (id) => document.getElementById(id);
const shuffle = (arr) => {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
};

// ---------- Tabs ----------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => showView(tab.dataset.view));
});
function showView(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === name));
  if (name === "cards") nextCard();
  if (name === "quiz") nextQuestion();
  if (name === "words") renderList();
}

// ---------- Flashcards ----------
let current = null;

function pickCard() {
  const now = Date.now();
  const due = state.words.filter((w) => w.due <= now);
  const pool = due.length ? due : state.words;
  // Prefer the lowest level among the pool, with some randomness.
  const minLevel = Math.min(...pool.map((w) => w.level));
  const candidates = pool.filter((w) => w.level <= minLevel + 1 && w !== current);
  const list = candidates.length ? candidates : pool;
  return list[Math.floor(Math.random() * list.length)];
}

function nextCard() {
  const empty = state.words.length === 0;
  $("cards-empty").hidden = !empty;
  $("card").hidden = empty;
  document.querySelector("#cards .actions").hidden = empty;
  updateCardStats();
  if (empty) return;

  current = pickCard();
  $("card").classList.remove("flipped");
  $("card-word").textContent = current.word;
  $("card-pos").textContent = current.pos;
  $("card-def").textContent = current.def;
  $("card-example").textContent = current.example ? `“${current.example}”` : "";
}

function updateCardStats() {
  const total = state.words.length;
  const mastered = state.words.filter((w) => w.level >= MASTERED).length;
  const due = state.words.filter((w) => w.due <= Date.now()).length;
  $("card-stats").textContent = `${due} due · ${mastered} / ${total} mastered`;
}

function grade(knew) {
  if (!current) return;
  current.level = knew ? Math.min(current.level + 1, MASTERED) : 0;
  current.due = Date.now() + INTERVALS_MIN[current.level] * 60 * 1000;
  save();
  nextCard();
}

$("card").addEventListener("click", () => $("card").classList.toggle("flipped"));
$("btn-know").addEventListener("click", () => grade(true));
$("btn-again").addEventListener("click", () => grade(false));
document.addEventListener("keydown", (e) => {
  if (!$("cards").classList.contains("active") || e.target.matches("input, select")) return;
  if (e.code === "Space") { e.preventDefault(); $("card").classList.toggle("flipped"); }
  if (e.key === "ArrowRight") grade(true);
  if (e.key === "ArrowLeft") grade(false);
});

// ---------- Quiz ----------
let score = { right: 0, total: 0 };
let lastQuizId = null;

function nextQuestion() {
  const enough = state.words.length >= 4;
  $("quiz-empty").hidden = enough;
  ["quiz-q", "choices", "feedback", "quiz-score"].forEach((id) => ($(id).hidden = !enough));
  $("btn-next").hidden = true;
  $("feedback").textContent = "";
  if (!enough) return;

  const pool = state.words.filter((w) => w.id !== lastQuizId);
  const answer = pool[Math.floor(Math.random() * pool.length)];
  lastQuizId = answer.id;
  const distractors = shuffle(state.words.filter((w) => w.id !== answer.id)).slice(0, 3);
  const options = shuffle([answer, ...distractors]);

  // Alternate between "word → meaning" and "meaning → word".
  const askMeaning = Math.random() < 0.5;
  const q = $("quiz-q");
  q.textContent = "";
  if (askMeaning) {
    q.append("What does ");
    const s = document.createElement("strong");
    s.textContent = answer.word;
    q.append(s, " mean?");
  } else {
    q.textContent = `Which word means: “${answer.def}”?`;
  }

  const box = $("choices");
  box.innerHTML = "";
  options.forEach((opt) => {
    const b = document.createElement("button");
    b.textContent = askMeaning ? opt.def : opt.word;
    b.addEventListener("click", () => {
      const correct = opt.id === answer.id;
      score.total++;
      if (correct) score.right++;
      box.querySelectorAll("button").forEach((btn, i) => {
        btn.disabled = true;
        if (options[i].id === answer.id) btn.classList.add("correct");
      });
      if (!correct) b.classList.add("wrong");
      $("feedback").textContent = correct ? "Correct!" : `Not quite — the answer is “${askMeaning ? answer.def : answer.word}”.`;
      $("feedback").style.color = correct ? "var(--good)" : "var(--bad)";
      $("quiz-score").textContent = `Score: ${score.right} / ${score.total}`;
      $("btn-next").hidden = false;
      $("btn-next").focus();
    });
    box.appendChild(b);
  });
}
$("btn-next").addEventListener("click", nextQuestion);

// ---------- Word list ----------
function renderList() {
  const term = $("search").value.trim().toLowerCase();
  const items = state.words
    .filter((w) => !term || w.word.toLowerCase().includes(term) || w.def.toLowerCase().includes(term))
    .sort((a, b) => a.word.localeCompare(b.word));

  $("count").textContent = `(${state.words.length})`;
  const ul = $("word-list");
  ul.innerHTML = "";
  items.forEach((w) => {
    const li = document.createElement("li");
    const info = document.createElement("div");
    info.className = "info";
    const word = document.createElement("span"); word.className = "w"; word.textContent = w.word;
    const pos = document.createElement("span"); pos.className = "p"; pos.textContent = w.pos;
    const def = document.createElement("div"); def.className = "d"; def.textContent = w.def;
    info.append(word, pos, def);

    const badge = document.createElement("span");
    const mastered = w.level >= MASTERED;
    badge.className = "badge" + (mastered ? " known" : "");
    badge.textContent = mastered ? "mastered" : w.level === 0 ? "new" : `level ${w.level}`;

    const del = document.createElement("button");
    del.className = "del";
    del.title = `Delete “${w.word}”`;
    del.setAttribute("aria-label", del.title);
    del.textContent = "×";
    del.addEventListener("click", () => {
      state.words = state.words.filter((x) => x.id !== w.id);
      save();
      renderList();
    });

    li.append(info, badge, del);
    ul.appendChild(li);
  });
}

$("search").addEventListener("input", renderList);

$("add-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const word = $("f-word").value.trim();
  const def = $("f-def").value.trim();
  if (!word || !def) return;
  if (state.words.some((w) => w.word.toLowerCase() === word.toLowerCase())) {
    $("form-msg").textContent = `“${word}” is already in your list.`;
    $("form-msg").hidden = false;
    return;
  }
  $("form-msg").hidden = true;
  state.words.push({
    id: Date.now(),
    word,
    pos: $("f-pos").value,
    def,
    example: $("f-example").value.trim(),
    level: 0,
    due: 0,
  });
  save();
  e.target.reset();
  $("f-word").focus();
  renderList();
});

// Two-step reset: first click asks, second click within 4 seconds resets.
let resetArmed = null;
$("btn-reset").addEventListener("click", () => {
  const btn = $("btn-reset");
  if (!resetArmed) {
    btn.textContent = "Click again to reset all progress";
    resetArmed = setTimeout(() => { resetArmed = null; btn.textContent = "Reset progress"; }, 4000);
    return;
  }
  clearTimeout(resetArmed);
  resetArmed = null;
  btn.textContent = "Reset progress";
  state.words.forEach((w) => { w.level = 0; w.due = 0; });
  save();
  renderList();
});

// ---------- Start ----------
nextCard();
