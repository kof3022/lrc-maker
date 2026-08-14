// 前端脚本行为测试：用 DOM 桩执行 index.html 里的脚本并模拟关键交互。
// 运行: node scripts/test_web.js
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'index.html'), 'utf8');
const m = /<script>([\s\S]*?)<\/script>/.exec(html);
if (!m) {
  console.error('未找到 <script>');
  process.exit(1);
}

// ---------- DOM 桩 ----------
const els = {};
function makeEl(id) {
  const el = {
    id, value: '', disabled: false, textContent: '', hidden: true, src: '', currentTime: 0,
    paused: true, files: [], listeners: {}, _children: [],
    className: '', innerHTML: '',
    style: {}, dataset: {},
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      toggle(c, force) {
        if (force === undefined) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); }
        else { force ? this._s.add(c) : this._s.delete(c); }
      },
      contains(c) { return this._s.has(c); },
    },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    appendChild(child) { this._children.push(child); return child; },
    remove() {}, play() { this.paused = false; if (this.listeners.play) this.listeners.play(); return Promise.resolve(); }, pause() { this.paused = true; if (this.listeners.pause) this.listeners.pause(); },
    scrollIntoView() {},
    querySelector() { return makeEl(); },
    click() {},
  };
  Object.defineProperty(el, 'children', { get() { return el._children; } });
  return el;
}
global.document = {
  getElementById(id) { if (!els[id]) els[id] = makeEl(id); return els[id]; },
  createElement() { return makeEl(); },
  addEventListener() {}, body: makeEl('body'),
};
global.URL = { createObjectURL() { return 'blob:x'; }, revokeObjectURL() {} };
global.navigator = { clipboard: { writeText() { return Promise.resolve(); } } };
global.fetch = function () {
  return Promise.resolve({
    ok: true,
    json() {
      return Promise.resolve({
        duration: 10,
        lines: [
          { text: '第一句', start: 1.0, end: 3.0, confidence: 90, matched: true, source: 'match' },
          { text: '第二句', start: 4.0, end: 6.0, confidence: 90, matched: true, source: 'match' },
          { text: '第三句', start: null, end: null, confidence: 0, matched: false, source: 'none' },
        ],
      });
    },
  });
};

// 预置 HTML 里已有的元素及初始状态
els['btn-align'] = makeEl('btn-align');
els['btn-align'].disabled = true;
els['btn-hint'] = makeEl('btn-hint');
els['btn-hint'].textContent = '请先选择音频文件，再粘贴歌词';
els['status-text'] = makeEl('status-text');
els['drop'] = makeEl('drop');
els['drop-title'] = makeEl('drop-title');
els['drop-hint'] = makeEl('drop-hint');
els['file'] = makeEl('file');
els['player-wrap'] = makeEl('player-wrap');
els['player'] = makeEl('player');
els['player2'] = makeEl('player2');
els['meta-title'] = makeEl('meta-title');
els['meta-artist'] = makeEl('meta-artist');
els['lyrics'] = makeEl('lyrics');
els['btn-settings'] = makeEl('btn-settings');

// 执行页面脚本（IIFE 初始化）
eval(m[1]);

// ---------- 断言工具 ----------
let failed = 0;
const assert = (cond, msg) => {
  if (!cond) { console.error('FAIL: ' + msg); failed = 1; }
  else { console.log('PASS: ' + msg); }
};

async function main() {
  const btn = els['btn-align'];
  const hint = els['btn-hint'];
  const lyrics = els['lyrics'];
  const fileInput = els['file'];
  const metaTitle = els['meta-title'];

  // --- 按钮状态 ---
  assert(btn.disabled === true, '初始按钮置灰');
  assert(hint.textContent.includes('音频'), '初始提示提及音频');

  lyrics.value = '第一句歌词\n第二句歌词\n第三句歌词';
  lyrics.listeners.input();
  assert(btn.disabled === true, '只有歌词时仍置灰');
  assert(hint.textContent.includes('音频'), '提示还缺音频');

  fileInput.files = [{ name: 'song.mp3', size: 3000000 }];
  fileInput.listeners.change();
  assert(btn.disabled === false, '有文件+歌词后按钮可点');
  assert(hint.textContent.includes('可以生成'), '提示变为可生成');

  lyrics.value = '   ';
  lyrics.listeners.input();
  assert(btn.disabled === true, '清空歌词后置灰');

  metaTitle.listeners.input();
  console.log('meta 输入不抛错');

  // --- 生成 + 播放高亮 ---
  lyrics.value = '第一句歌词\n第二句歌词\n第三句歌词';
  lyrics.listeners.input();
  btn.listeners.click();
  await new Promise((r) => setTimeout(r, 30)); // 等待 fetch 流程完成

  const linesBox = els['lines'];
  assert(linesBox._children.length === 3, '生成后渲染 3 行歌词');
  assert(els['step-result'].hidden === false, '结果区显示');

  const player2 = els['player2'];
  assert(player2.src !== '', '播放器已挂载音频');

  player2.currentTime = 0.5;
  player2.listeners.timeupdate();
  assert(linesBox._children.every((r) => !r.classList.contains('playing')), '前奏期间无高亮');

  player2.currentTime = 4.5;
  player2.listeners.timeupdate();
  assert(linesBox._children[1].classList.contains('playing'), '播放到 4.5s 高亮第 2 句');
  assert(!linesBox._children[0].classList.contains('playing'), '第 1 句取消高亮');
  assert(!linesBox._children[2].classList.contains('playing'), '未匹配行不高亮');

  player2.currentTime = 8.0;
  player2.listeners.timeupdate();
  assert(linesBox._children[1].classList.contains('playing'), '超出末句时间后保持最后一句高亮');

  player2.listeners.ended();
  assert(linesBox._children.every((r) => !r.classList.contains('playing')), '播放结束清除高亮');

  // --- 播放控制按钮 ---
  player2.currentTime = 6;
  els['btn-back5'].listeners.click();
  assert(player2.currentTime === 1, '后退5秒生效');

  els['btn-fwd5'].listeners.click();
  assert(player2.currentTime === 6, '前进5秒生效');

  player2.duration = 4;
  els['btn-fwd5'].listeners.click();
  assert(player2.currentTime === 4, '前进不超过音频时长');

  player2.duration = undefined;
  player2.paused = true;
  assert(els['btn-toggle'].textContent.includes('播放'), '初始按钮显示播放');
  els['btn-toggle'].listeners.click();
  assert(player2.paused === false, '点击后开始播放');
  assert(els['btn-toggle'].textContent.includes('暂停'), '播放中按钮显示暂停');
  els['btn-toggle'].listeners.click();
  assert(player2.paused === true, '再次点击暂停');
  assert(els['btn-toggle'].textContent.includes('播放'), '暂停后按钮显示播放');

  if (failed) process.exit(1);
  console.log('test_web: OK');
}

main().catch((e) => {
  console.error('test_web 异常: ' + e.message);
  process.exit(1);
});