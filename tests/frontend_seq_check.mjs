// 用后端真实 /api/solve 载荷模拟前端：验证 int64 序号在 JS 下的展示与高亮映射。
// 运行：node tests/frontend_seq_check.mjs <payload.json>
import fs from 'node:fs';

const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
let failures = 0;
const check = (name, cond) => {
  console.log((cond ? 'PASS' : 'FAIL') + ' - ' + name);
  if (!cond) failures++;
};

const byTail = Object.fromEntries(payload.tails.map(t => [t.tail, t]));

// 1) 旧逻辑复现：数字 seq 在 JS 中碰撞，相邻大序号显示成同一个数
const l1 = byTail['L-1001'];
const numericSeqs = l1.segments.map(s => Number(s.seq));
check('旧逻辑复现：9007199254740992/3 在 JS Number 下碰撞',
  numericSeqs[0] === numericSeqs[1] && String(numericSeqs[0]) === '9007199254740992');
check('旧逻辑复现：int64 最大值被舍入',
  String(Number('9223372036854775807')) === '9223372036854776000');

// 2) 新逻辑：seq_text 字符串精确展示
check('seq_text 精确展示碰撞对（前两段不同）',
  l1.segments[0].seq_text === '9007199254740992' &&
  l1.segments[1].seq_text === '9007199254740993');
check('seq_text 精确展示 int64 最大值',
  l1.segments[2].seq_text === '9223372036854775807');
check('唯一解 solution 每行带 seq_text',
  l1.solution.every(s => typeof s.seq_text === 'string' && /^\d+$/.test(s.seq_text)));

// 3) 新高亮映射：字符串键，每个航段都能命中（旧逻辑碰撞键会互相覆盖）
const chosenNew = {};
l1.solution.forEach(s => { chosenNew[s.seq_text] = {dep: s.dep_utc, arr: s.arr_utc}; });
check('新逻辑：三段全部能命中高亮映射',
  l1.segments.every(seg => chosenNew[seg.seq_text] !== undefined));

const chosenOld = {};
l1.solution.forEach(s => { chosenOld[s.seq] = {dep: s.dep_utc, arr: s.arr_utc}; });
const missed = l1.segments.filter(seg => chosenOld[seg.seq] === undefined
  || chosenOld[seg.seq].dep !== l1.solution.find(x => x.seq_text === seg.seq_text).dep_utc);
check('旧逻辑复现：碰撞序号的高亮被覆盖/漏标', missed.length > 0);

// 4) 高亮的 UTC 与“导出内容”逐段相符（同一份 solution 字符串）
check('高亮 UTC 与解逐段相符',
  l1.solution.every(s => chosenNew[s.seq_text].dep === s.dep_utc
    && chosenNew[s.seq_text].arr === s.arr_utc));

// 5) 无解冲突提示使用精确字符串序号
const l2 = byTail['L-1002'];
check('无解状态带 segment_seq_text 且精确',
  l2.status === 'no_solution'
  && l2.conflict.segment_seq_text === '9223372036854775806');
check('冲突航段在明细表中能按字符串键找到对应行',
  l2.segments.some(s => s.seq_text === l2.conflict.segment_seq_text));

// 6) 多解候选链展示精确字符串序号
const l3 = byTail['L-1003'];
check('多解候选链 seq_text 精确',
  l3.status === 'multiple'
  && l3.solutions.every(sol => sol.every(s =>
    ['9007199254740994', '9007199254740995'].includes(s.seq_text))));

// 7) 默认数字字段与类型保持不变（批处理兼容）
check('默认 seq 字段仍为 JSON number',
  l1.segments.every(s => typeof s.seq === 'number')
  && l1.solution.every(s => typeof s.seq === 'number')
  && typeof l2.conflict.segment_seq === 'number');

if (failures) { console.error('\n' + failures + ' 项失败'); process.exit(1); }
console.log('\n前端序号/高亮核对全部通过 ✅');
