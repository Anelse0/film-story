#!/usr/bin/env python3
"""对白检查（film-story）。只算能数的东西，给人看线索；不打分，不判通过。

用法:
  python3 check_dialogue.py scene.md [scene2.md ...] [--json] [--lang en]

识别四种写法（混用也行）：
  1) **NAME** 单独一行，下面是台词行（Offset 写法；中文对照行自动跳过）
  2) NAME：“English line”　（中文翻译：…）   （FAMILIARS 写法；只取引号内）
  3) NAME: line  /  NAME（提示）: line
  4) 全大写 NAME 单独一行，下一行台词（传统剧本）
括号行 （…）/(…) 视为表演提示。

输出每场：行数、说话人分布、词数分布、问答对接链、疑似金句、解释/复述标记、回声句、
括号里的情绪标签、台词时长估算（默认 4 词/秒）。所有阈值都是 [推论]，在 THRESH 里改。
退出码恒为 0。"""
import argparse, json, re, sys, statistics
from pathlib import Path

THRESH = {
    'words_per_sec': 4.0,       # 用户项目约定
    'pingpong_run': 4,          # 连续 ≥4 句每句都精准接上一句 → 提示"问答式对接"
    'short_words': 3,           # ≤3 词算短句
    'short_share_warn': 0.5,    # 短句占比 ≥50% 提示
    'echo_overlap': 0.5,        # 与上一句实词重合 ≥50% → 回声/抠字眼
}

CUE_BOLD = re.compile(r'^\*\*([^*]+?)\*\*\s*(（.*?）|\(.*?\))?\s*$')
CUE_UPPER = re.compile(r'^([A-Z][A-Z0-9 .\'-]{1,30})\s*(（.*?）|\(.*?\))?\s*$')
CUE_INLINE = re.compile(r'^([A-Za-z][A-Za-z .\'-]{0,30}|[一-鿿·]{1,8})\s*(（[^）]*）|\([^)]*\))?\s*[:：]\s*(.+)$')
PAREN_ONLY = re.compile(r'^[（(].*[)）]\s*$')
QUOTED = re.compile(r'[“"]([^”"]+)[”"]')
CJK = re.compile(r'[一-鿿]')
SCENE_HEAD = re.compile(r'^(#+\s*)?(场|SCENE|INT\.|EXT\.|冷开|##\s*场)', re.I)
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")

STOP = set("""a an the and or but so to of in on at for with by from as is are was were be been am do does did
have has had will would can could should may might must i you he she it we they me him her us them my your his
its our their this that these those there here what who whom which when where why how not no yes oh okay ok yeah
just like well right now then if about up out over into than too very really get got go going come came know think
want say said tell told ask asked mean one thing things way don't doesn't didn't isn't aren't wasn't can't won't
i'm you're he's she's it's we're they're i've you've i'll you'll that's there's what's let's gonna wanna""".split())

EXPLAIN = re.compile(r"\b(because|the reason|i mean|what i'm saying|what i meant|let me explain|the truth is|"
                     r"the point is|you have to understand|i just (want|need|think)|honestly|to be honest)\b", re.I)
RECAP = re.compile(r"\b(you said|i said|you told|i told|last night you|remember when|like you said|"
                   r"you (just|already) (said|did|told)|in front of (all of )?them|up there i)\b", re.I)
APHORISM = re.compile(r"^(people|everyone|everybody|nobody|sometimes|that's (what|how|why)|it's not about|"
                      r"there are two kinds|the thing about|you can't|you don't get to|that's the)\b", re.I)
ANTITHESIS = [re.compile(p, re.I) for p in (
    r"\bnot\b[^.?!]{1,40}\bbut\b", r",\s*not\b", r"\bit's not\b[^.?!]{1,40}\.\s*it's\b",
    r"\bthat's not\b[^.?!]{1,40}\.\s*that's\b", r"\bnever\b[^.?!]{1,30}\balways\b", r"\balways\b[^.?!]{1,30}\bnever\b")]
EMO_PAREN = re.compile(r"(?<!压)低声|[，,]\s*平[）)]|平静|冷冷|冷淡|讽刺|深情|愤怒|悲伤|激动|温柔|坚定|quietly|coldly|softly|sarcastic|"
                       r"angrily|bitterly|tenderly|firmly|calmly", re.I)
HEADER_WORDS = {'承接', '后续', '版本', '状态', '依据', '位置', '标题', '场序', '人物', '服装说明', '声音', '气场', '设计取向', '主线', '说明', '来源', '注', '新事实', '新事实（提案）', '本场改变了什么', '改动清单', '连带影响'}


def extract(path):
    """返回场景列表：[{'title':..., 'lines':[{'speaker','text','paren','raw_no'}], 'parens':[...]}]"""
    scenes, cur = [], {'title': '(开头)', 'lines': [], 'parens': []}
    src = Path(path).read_text(encoding='utf-8').splitlines()
    i, n = 0, len(src)
    pending = None  # (speaker, paren) 等台词行
    while i < n:
        raw = src[i].rstrip()
        s = raw.strip()
        i += 1
        if not s:
            continue
        if SCENE_HEAD.match(s) and not CUE_INLINE.match(s):
            if cur['lines'] or cur['parens']:
                scenes.append(cur)
            cur = {'title': s.lstrip('#').strip(), 'lines': [], 'parens': []}
            pending = None
            continue
        if s.startswith('<!--') or s.startswith('|') or s.startswith('- ') or s.startswith('>'):
            continue
        m = CUE_BOLD.match(s) or CUE_UPPER.match(s)
        if m and len(m.group(1).split()) <= 4:
            pending = (m.group(1).strip('* ').title() if m.group(1).isupper() else m.group(1).strip('* '), m.group(2) or '')
            continue
        if PAREN_ONLY.match(s):
            cur['parens'].append(s)
            if pending:
                pending = (pending[0], (pending[1] + ' ' + s).strip())
            continue
        m = CUE_INLINE.match(s)
        if m and not pending:
            spk, par, text = m.group(1).strip(), m.group(2) or '', m.group(3).strip()
            if CJK.search(spk) and (spk in HEADER_WORDS or not QUOTED.search(text)):
                continue
            q = QUOTED.findall(text)
            text = ' '.join(q) if q else text
            text = re.sub(r'（中文翻译[:：][^）]*）', '', text).strip()
            if par:
                cur['parens'].append(par)
            if WORD.search(text) and len(CJK.findall(text)) < len(WORD.findall(text)):
                cur['lines'].append({'speaker': spk, 'text': text, 'paren': par, 'raw_no': i})
            continue
        if pending:
            if CJK.search(s) and len(CJK.findall(s)) >= len(WORD.findall(s)):
                # 中文对照行或中文台词：跳过（英文剧本只量英文）
                continue
            text = ' '.join(QUOTED.findall(s)) or s
            cur['lines'].append({'speaker': pending[0], 'text': text, 'paren': pending[1], 'raw_no': i})
            pending = None
            continue
    if cur['lines'] or cur['parens']:
        scenes.append(cur)
    return scenes


def content_words(t):
    return [w.lower() for w in WORD.findall(t) if w.lower() not in STOP]


def analyse(scene):
    L = scene['lines']
    out = {'title': scene['title'], 'n_lines': len(L), 'flags': []}
    if not L:
        return out
    words = [len(WORD.findall(x['text'])) for x in L]
    out['total_words'] = sum(words)
    out['est_seconds'] = round(sum(words) / THRESH['words_per_sec'], 1)
    out['mean_words'] = round(statistics.mean(words), 1)
    out['short_share'] = round(sum(1 for w in words if w <= THRESH['short_words']) / len(L), 2)
    spk = {}
    for x, w in zip(L, words):
        d = spk.setdefault(x['speaker'], {'lines': 0, 'words': 0, 'questions': 0})
        d['lines'] += 1; d['words'] += w; d['questions'] += x['text'].strip().endswith('?')
    for k, d in spk.items():
        d['mean_words'] = round(d['words'] / d['lines'], 1)
    out['speakers'] = spk

    # 问答/精准对接链：上一句是问句且本句换人作答，或本句实词重合上一句 ≥1 且换人
    run, best, best_span = 0, 0, None
    for k in range(1, len(L)):
        prev, cur = L[k - 1], L[k]
        linked = cur['speaker'] != prev['speaker'] and (
            prev['text'].strip().endswith('?') or set(content_words(cur['text'])) & set(content_words(prev['text'])))
        run = run + 1 if linked else 0
        if run > best:
            best, best_span = run, (L[k - run]['raw_no'], cur['raw_no'])
    out['longest_linked_run'] = best
    if best + 1 >= THRESH['pingpong_run']:
        out['flags'].append(f"问答式对接：连续 {best + 1} 句每句都精准接上一句（行 {best_span[0]}–{best_span[1]}）。看是否需要延迟、偏移、落在动作或第三人身上 [推论]")
    if out['short_share'] >= THRESH['short_share_warn'] and len(L) >= 6:
        out['flags'].append(f"短句占比 {out['short_share']:.0%}：像一人一句的标语，还是有来回？人判 [推论]")

    marks = []
    for k, x in enumerate(L):
        t = x['text']
        tags = []
        if EXPLAIN.search(t): tags.append('解释')
        if RECAP.search(t): tags.append('复述前情')
        if APHORISM.search(t.strip()): tags.append('格言式开头')
        if any(p.search(t) for p in ANTITHESIS): tags.append('对仗/反转结构')
        if k and x['speaker'] != L[k - 1]['speaker']:
            a, b = set(content_words(t)), set(content_words(L[k - 1]['text']))
            if a and b and len(a & b) / len(a) >= THRESH['echo_overlap'] and len(a) >= 2:
                tags.append('回声上一句')
        if tags:
            marks.append({'line': x['raw_no'], 'speaker': x['speaker'], 'text': t, 'tags': tags})
    out['marked_lines'] = marks
    emo = [p for p in scene['parens'] if EMO_PAREN.search(p)]
    if emo:
        out['emotion_parens'] = emo
        out['flags'].append(f"{len(emo)} 处括号写的是情绪标签而不是可见动作（例：{emo[0]}）。按本场处境定强度，不从小传套 [用户纠正 10-16]")
    if out['est_seconds'] > 30:
        out['flags'].append(f"台词约 {out['est_seconds']} s（4 词/秒），一条 clip 放不下，生产要切 ≥{int(out['est_seconds'] // 30) + 1} 条；是否每句都值得占时间？")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    report = []
    for f in a.files:
        for sc in extract(f):
            r = analyse(sc); r['file'] = f; report.append(r)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2)); return
    for r in report:
        print(f"\n== {r['file']} · {r['title']} ==")
        if not r['n_lines']:
            print('  没有识别到英文台词行（安静戏，或写法未被识别）'); continue
        print(f"  台词 {r['n_lines']} 句 · 共 {r['total_words']} 词 · 约 {r['est_seconds']} s · 平均 {r['mean_words']} 词/句 · 短句 {r['short_share']:.0%}")
        for k, d in r['speakers'].items():
            print(f"    {k}: {d['lines']} 句, 平均 {d['mean_words']} 词, 问句 {d['questions']}")
        for fl in r['flags']:
            print('  ! ' + fl)
        if r['marked_lines']:
            print('  需人判的句子：')
            for m in r['marked_lines']:
                print(f"    行{m['line']} {m['speaker']}: “{m['text']}”  ← {', '.join(m['tags'])}")
    print('\n说明：以上只是线索。标记多不等于台词差，没标记不等于台词好；真正的判断看这句是不是这个人此刻会对这个人说的话。')


if __name__ == '__main__':
    main()
