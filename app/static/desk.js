const sample = document.querySelector('#sample');
sample.addEventListener('change', () => document.querySelector('input[name=run]')?.remove());
document.querySelector('#print-book').addEventListener('click', () => window.print());
const rerun = document.querySelector('#rerun');
rerun?.addEventListener('click', async () => {
  const feedback = document.querySelector('#feedback');
  rerun.disabled = true;
  feedback.textContent = '复算中…';
  try {
    const res = await fetch(`/api/journal/${rerun.dataset.run}/rerun`, {method:'POST'});
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || '复算失败');
    feedback.textContent = data.reused ? '复算一致，沿用原簿' : '新簿已归档';
  } catch (error) {
    feedback.textContent = `${error.message}，请重试。`;
  } finally { rerun.disabled = false; }
});

const feedback = document.querySelector('#sailing-feedback');
const note = (text) => { if (feedback) feedback.textContent = text; };
const reopen = (advice) => {
  const url = new URL(location.href);
  url.searchParams.delete('run');
  if (advice) url.searchParams.set('advice', advice);
  location.href = url;
};
const post = async (url, body) => {
  const res = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const data = await res.json();
  if (!res.ok) throw new Error(data.message || '提交失败');
  return data;
};

const adviceForm = document.querySelector('#file-advice');
adviceForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  note('核算中…');
  const tiers = [...adviceForm.querySelectorAll('tbody tr')].map((row) => {
    const [tier, draft_m, air_m, bridge_m] = [...row.querySelectorAll('input')].map((input) => input.value.trim());
    return {tier, draft_m, air_m, bridge_m};
  }).filter((tier) => tier.tier);
  try {
    const data = await post('/api/sailing/advice', {sample:adviceForm.dataset.sample, vessel:adviceForm.dataset.vessel, tiers});
    reopen(data.advice.id);
  } catch (error) { note(`${error.message}，请重试。`); }
});

const confirmButton = document.querySelector('#confirm-advice');
confirmButton?.addEventListener('click', async () => {
  confirmButton.disabled = true;
  note('确认中…');
  try {
    await post(`/api/sailing/advice/${confirmButton.dataset.advice}/confirm`, {});
    reopen(confirmButton.dataset.advice);
  } catch (error) {
    note(`${error.message}`);
    setTimeout(() => reopen(confirmButton.dataset.advice), 1500);
  } finally { confirmButton.disabled = false; }
});

const supplementForm = document.querySelector('#file-supplement');
supplementForm?.addEventListener('submit', async (event) => {
  event.preventDefault();
  note('补录中…');
  const rows = supplementForm.querySelector('textarea').value.split('\n')
    .map((line) => line.trim()).filter(Boolean)
    .map((line) => {
      const [station, observed_at, level, unit, quality] = line.split(',').map((field) => field.trim());
      return {station, observed_at, level, unit, quality};
    });
  try {
    const data = await post('/api/sailing/supplement', {sample:supplementForm.dataset.sample, rows});
    note(data.invalidated.length ? `补录已入账，${data.invalidated.length} 份建议失效并重算。` : '补录已入账，结论未受影响。');
    setTimeout(() => reopen(), 900);
  } catch (error) { note(`${error.message}，请重试。`); }
});
