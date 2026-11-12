// 端到端渲染冒烟测试：用最小 DOM 桩加载真实页面脚本，喂入后端真实 /api/solve 载荷，
// 检查渲染 HTML 中的序号精度、唯一解 ✔ 高亮覆盖度、冲突提示与候选链序号。
// 运行：node tests/render_smoke.mjs <page.html> <payload.json>
import fs from 'node:fs';

const [, , pagePath, payloadPath] = process.argv;
const html = fs.readFileSync(pagePath, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const payload = JSON.parse(fs.readFileSync(payloadPath, 'utf8'));

function makeEl(id) {
  return {
    id, innerHTML: '', textContent: '', value: '', disabled: false,
    style: {}, dataset: {},
    addEventListener() {}, click() {},
  };
}
const elements = {};
const ids = ['fileInput', 'sampleBtn', 'bigSeqSampleBtn', 'solveBtn', 'fileName',
  'exportAllBtn', 'global-error', 'summary', 'results'];
for (const id of ids) elements[id] = makeEl(id);

globalThis.document = {
  getElementById: (id) => elements[id] || (elements[id] = makeEl(id)),
  querySelectorAll: () => [],
  createElement: () => ({click() {}, set href(v) {}, set download(v) {}}),
};
globalThis.fetch = async () => { throw new Error('smoke test does not use network'); };
globalThis.URL = { createObjectURL: () => 'blob:stub', revokeObjectURL() {} };
globalThis.alert = () => {};
globalThis.FormData = class { append() {} };

const fn = new Function(script + '\n return {render, renderTail};');
const page = fn();
page.render(payload);
const out = elements.results.innerHTML;

let failures = 0;
const check = (name, cond) => {
  console.log((cond ? 'PASS' : 'FAIL') + ' - ' + name);
  if (!cond) failures++;
};
check('render 输出非空', typeof out === 'string' && out.length > 100);
check('汇总 chips 已渲染', elements.summary.innerHTML.includes('summary-chips'));

for (const t of payload.tails) {
  const h = page.renderTail(t);
  // 所有航段序号必须以精确十进制字符串出现
  for (const seg of t.segments || []) {
    check(`${t.tail} 明细表精确渲染 seq=${seg.seq_text}`, h.includes(seg.seq_text));
  }
  if (t.status === 'unique') {
    // 每个航段起飞+落地各一个 ✔，不得漏标
    const marks = (h.match(/class="chosen"/g) || []).length;
    check(`${t.tail} 唯一解 ✔ 数量 = 段数×2（${t.segments.length * 2}）`,
      marks === t.segments.length * 2);
    for (const s of t.solution) {
      check(`${t.tail} 高亮含 seq ${s.seq_text} 的 dep/arr UTC`,
        h.includes('✔ ' + s.dep_utc) && h.includes('✔ ' + s.arr_utc));
    }
  }
  if (t.status === 'no_solution') {
    check(`${t.tail} 冲突提示精确显示 seq=${t.conflict.segment_seq_text}`,
      h.includes('seq=' + t.conflict.segment_seq_text));
  }
  if (t.status === 'multiple') {
    t.solutions.forEach((sol, i) => {
      check(`${t.tail} 候选链 #${i + 1} 渲染且序号精确`,
        h.includes('候选链 #' + (i + 1)) && sol.every(s => h.includes(s.seq_text)));
    });
  }
  if (t.status === 'error') {
    check(`${t.tail} 错误框渲染`, h.includes('error-box'));
  }
}

// 若载荷含 >2^53 的序号，渲染结果绝不能出现“并非任何真实序号”的 JS 舍入串
const allRealSeqs = new Set(payload.tails.flatMap(t => [
  ...(t.segments || []).map(s => s.seq_text),
  ...(t.status === 'no_solution' ? [t.conflict.segment_seq_text] : []),
]).filter(Boolean));
const bigTexts = [...allRealSeqs].filter(x => BigInt(x) > BigInt('9007199254740991'));
for (const txt of bigTexts) {
  const rounded = String(Number(txt));
  const roundedIsPhantom = !allRealSeqs.has(rounded);
  check(`大序号 ${txt} 精确渲染` + (roundedIsPhantom ? `，且无舍入串 ${rounded}` : ''),
    out.includes(txt) && (!roundedIsPhantom || !out.includes(rounded)));
}

if (failures) { console.error('\n' + failures + ' 项失败'); process.exit(1); }
console.log('\n页面渲染冒烟测试全部通过 ✅');
