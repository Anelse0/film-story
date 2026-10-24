#!/usr/bin/env python3
"""对白检查（film-story）。只数能数的东西，给人看线索；不打分，不判通过。

用法:
  python3 check_dialogue.py scene.md [scene2.md ...] [--lang auto|en|zh]
                            [--constraints <项目>/story/constraints.md] [--wps N] [--cps N] [--json]

正文：只读 <!-- script-body:start --> 与 <!-- script-body:end --> 之间（可以有多段）；头部、本版改动、批注、备选台词
在标记之外，不计入。没有标记的旧文件按全文读并提示；标记不成对时报格式问题，按能推断的范围读。

识别四种写法（混用也行）：
  1) **NAME** 单独一行，下面到空行为止是台词块（Offset 写法）；块里另一种语言的行算对照翻译
  2) NAME：“台词”　（中文翻译：…）   （FAMILIARS 写法；只取引号内）
  3) NAME: line  /  NAME（提示）: line
  4) 全大写 NAME 单独一行，下面到空行为止是台词（传统剧本）
括号行 （…）/(…) 视为括注。角色名或括注里有 电话里 / 手机里 / 画外 / 旁白 / V.O. / O.S. 等的，算画外说话人。

语言（--lang）：auto（默认：按全文多数台词的语言定，另一种算对照翻译）/ en / zh。中文统计句数、字数、问句、接话链
（只按问号）和解释 / 复述 / 泛称开头 / "不是……而是……"四类词面线索；"与上一句实词重合"要分词，中文不支持，输出里写明。

时长：语速和单条生成上限读项目约束文件的"## 制作参数"（--constraints 指定，或从场景文件往上找 story/constraints.md），
--wps / --cps 临时指定；都没有就只报词数 / 字数，不估秒，不提拆条。估的是口播时长，不是成片时长。

输出每场：句数、说话人分布（画外单独标出）、词数或字数、连续接话、短句占比、问句过半的说话人、词面线索、括号里的
情绪标签。所有阈值都是 [推论]，在 THRESH 里改。退出码恒为 0。"""
import argparse, json, math, re, sys, statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_config import find_constraints, load_constraints  # noqa: E402

THRESH = {
    'pingpong_run': 4,        # 连续 ≥4 句都换人且接着上一句 → 提示"连续接话"
    'short_words': 3,         # 英文 ≤3 词算短句
    'short_chars': 5,         # 中文 ≤5 字算短句
    'short_share_warn': 0.5,  # 短句占比 ≥50% 提示
    'echo_overlap': 0.5,      # 与上一句实词重合 ≥50%（只算英文）
    'question_share': 0.5,    # 某人问句占其台词 ≥50%……
    'question_min': 3,        # ……且至少 3 句 → 提示"一直在问"
}

START = re.compile(r'<!--\s*script-body:start\s*-->')
END = re.compile(r'<!--\s*script-body:end\s*-->')
CUE_BOLD = re.compile(r'^\*\*([^*]+?)\*\*\s*(（.*?）|\(.*?\))?\s*$')
CUE_UPPER = re.compile(r'^([A-Z][A-Z0-9 .\'-]{1,30})\s*(（.*?）|\(.*?\))?\s*$')
CUE_INLINE = re.compile(r'^([A-Za-z][A-Za-z .\'-]{0,30}|[一-鿿·]{1,8})\s*(（[^）]*）|\([^)]*\))?\s*[:：]\s*(.+)$')
NAME_LEAD = re.compile(r'^([A-Za-z][A-Za-z.\'-]{1,30})()\s*[一-鿿][^：:]*[:：]\s*([“"].+)$')  # "June 在“墙”后面喊：“…”"
NAME_PAREN = re.compile(r'^(.*?)\s*(（[^）]*）|\([^)]*\))\s*$')
PAREN_ONLY = re.compile(r'^[（(].*[)）]\s*$')
QUOTED = re.compile(r'[“"]([^”"]+)[”"]')
CJK = re.compile(r'[一-鿿]')
FULLWIDTH = re.compile(r'[，。！？、；：（）《》]')
SCENE_HEAD = re.compile(r'^(?:#+\s*)?(?:场\s*\d|SCENE\b|INT\.|EXT\.|冷开)|^#+\s*\d{1,3}\s*[｜|]', re.I)
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
OFFSCREEN = re.compile(r"电话里|电话那头|电话那边|手机里|屏幕里|视频里|画外|旁白|广播里|对讲机里|"
                       r"\bV\.?\s?O\.?(?![A-Za-z])|\bO\.?\s?[SC]\.?(?![A-Za-z])|filtered|over the phone|"
                       r"off-?screen|voice-?over", re.I)
NARRATOR = {'旁白', '画外音', 'narrator', 'voice'}
NON_SPEAKER = {'汇合到', '记录', '片名', '邮件', '短信', '插入', '屏幕', '屏幕上', '字幕', '画面', '标题', '名字卡', '咒语卡'}

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
EXPLAIN_ZH = re.compile(r"因为|所以说|我的意思是|我想说的是|说白了|说实话|老实说|你要明白|你得明白|你要知道")
RECAP_ZH = re.compile(r"你刚才说|你刚刚说|你说过|我说过|你不是说|上次你|那天你|你还记得")
APHORISM_ZH = re.compile(r"^(人啊|人这一辈子|有些人|有的人|这世上|生活就是|爱就是|所谓|说到底)")
ANTITHESIS_ZH = [re.compile(p) for p in (r"不是[^，。！？]{1,20}[，,]?\s*而是", r"与其[^，。！？]{1,20}不如")]
EMO_PAREN = re.compile(r"(?<!压)低声|[，,]\s*平[）)]|平静|冷冷|冷淡|讽刺|深情|愤怒|悲伤|激动|温柔|坚定|quietly|coldly|softly|sarcastic|"
                       r"angrily|bitterly|tenderly|firmly|calmly", re.I)
HEADER_WORDS = {'承接', '后续', '版本', '状态', '依据', '位置', '标题', '场序', '人物', '服装说明', '声音', '气场', '设计取向', '主线', '说明', '来源', '注', '新事实', '新事实（提案）', '本场改变了什么', '改动清单', '连带影响', '本版改动', '本轮目标', '改', '删', '加', '备选', '批注', '上一版'}
TAG = {'explain': '含解释性词语', 'recap': '含复述性词语', 'aphorism': '泛称 / 格言式开头',
       'antithesis': '反转句式', 'echo': '与上一句实词重合'}
LANG_NAME = {'en': '英文', 'zh': '中文'}
UNIT = {'en': '词', 'zh': '字'}


def body_lines(src):
    """正文范围：返回 ([(行号, 原文), ...], 说明)。说明为 'markers' / 'no-markers' / 'unpaired (start n / end m)'。"""
    marks = [(i, 's' if START.search(l) else 'e') for i, l in enumerate(src) if START.search(l) or END.search(l)]
    if not marks:
        return [(i + 1, l) for i, l in enumerate(src)], 'no-markers'
    keep, inside, begin, last, ok = set(), False, 0, -1, True
    for i, kind in marks:
        if kind == 's':
            if inside:
                ok = False
            else:
                inside, begin = True, i + 1
        elif inside:
            keep.update(range(begin, i))
            inside = False
        else:
            ok = False
            keep.update(range(last + 1, i))
        last = i
    if inside:
        ok = False
        keep.update(range(begin, len(src)))
    note = 'markers' if ok else 'unpaired (start {} / end {})'.format(
        sum(k == 's' for _, k in marks), sum(k == 'e' for _, k in marks))
    return [(i + 1, src[i]) for i in sorted(keep) if not (START.search(src[i]) or END.search(src[i]))], note


def line_lang(t):
    c, w = len(CJK.findall(t)), len(WORD.findall(t))
    if c and c >= w:
        return 'zh'
    if w:
        # "Rhett。" 这类只有名字的对照行：拉丁字母很少、带全角标点 → 算中文一侧
        return 'zh' if not c and w <= 3 and FULLWIDTH.search(t) else 'en'
    return ''


def size_of(text, lang):
    return len(WORD.findall(text)) if lang == 'en' else len(CJK.findall(text))


def is_question(t):
    return t.strip().rstrip('”"’\'）)').endswith(('?', '？'))


def cue_of(s):
    m = CUE_BOLD.match(s) or CUE_UPPER.match(s)
    if not m or len(m.group(1).split()) > 4 or re.search(r'[:：]', m.group(1)):
        return None  # "**Theo：You're slow.**" 是屏幕上的消息，不是角色名
    name, paren = m.group(1).strip('* ').strip(), m.group(2) or ''
    m2 = NAME_PAREN.match(name)
    if m2 and m2.group(1).strip():
        name, paren = m2.group(1).strip(), (m2.group(2) + ' ' + paren).strip()
    return name, paren


def _speech(speaker, paren, no):
    return {'speaker': speaker, 'cue_paren': paren, 'parens': [], 'cand': {'en': [], 'zh': []}, 'first': '', 'no': no}


def _inline(m, no):
    spk, par, text = m.group(1).strip(), m.group(2) or '', m.group(3).strip()
    if spk in NON_SPEAKER:  # "汇合到：Vera：“…”" → Vera；"邮件：“…”" 是画面文字，不是台词
        m2 = CUE_INLINE.match(text) or NAME_LEAD.match(text)
        if not m2 or m2.group(1).strip() in NON_SPEAKER:
            return None
        spk, par, text = m2.group(1).strip(), m2.group(2) or '', m2.group(3).strip()
    if CJK.search(spk) and (spk in HEADER_WORDS or not QUOTED.search(text)):
        return None
    q = QUOTED.findall(text)
    text = ' '.join(q) if q else text
    text = re.sub(r'（中文翻译[:：][^）]*）', '', text).strip()
    lang = line_lang(text)
    if not lang:
        return None
    sp = _speech(spk, par, no)
    sp['cand'][lang].append(text)
    sp['first'] = lang
    return sp


def _take(sp, cur, no, t):
    """台词块里的一行：括注记下；台词按语言放进候选（另一种语言就是对照翻译）。"""
    if PAREN_ONLY.match(t):
        sp['parens'].append(t)
        cur['parens'].append(t)
        return
    text = ' '.join(QUOTED.findall(t)) or t
    lg = line_lang(text)
    if lg:
        if not sp['first']:
            sp['first'], sp['no'] = lg, no
        sp['cand'][lg].append(text)


def _block_end(t):
    return SCENE_HEAD.match(t) or cue_of(t) or t.startswith('<!--')


def _tight_block(body, i, sp, cur):
    """台词块：角色名下面紧接着写，到空行、下一个角色名或场标题为止。"""
    while i < len(body):
        no, t = body[i][0], body[i][1].strip()
        if not t or _block_end(t):
            break
        _take(sp, cur, no, t)
        i += 1
    return i


def _loose_block(body, i, sp, cur):
    """角色名和台词之间隔着空行（从文档导出的稿）：跳过空行和前置括注，每种语言最多取一行。"""
    while i < len(body):
        no, t = body[i][0], body[i][1].strip()
        if not t:
            i += 1
            continue
        if _block_end(t):
            break
        if not (PAREN_ONLY.match(t) and not sp['first']):
            lg = line_lang(' '.join(QUOTED.findall(t)) or t)
            if not lg or sp['cand'][lg]:
                break  # 这种语言已经有一行：后面是动作或别的段落
        _take(sp, cur, no, t)
        i += 1
        if sp['cand']['en'] and sp['cand']['zh']:
            break
    return i


def _scene(title):
    return {'title': title, 'lines': [], 'parens': [], 'action': [], 'speeches': [], 'headed': title != '(开头)'}


def parse(path, lang='auto'):
    """返回 (场景列表, 元信息)。场景：{'title', 'lines', 'parens', 'action'}；lines 每句 {'speaker', 'text', 'paren',
    'raw_no', 'lang', 'offscreen'}。元信息：{'body', 'lang', 'other_lang_speeches', 'body_lines'}。"""
    src = Path(path).read_text(encoding='utf-8').splitlines()
    body, note = body_lines(src)
    scenes, cur = [], _scene('(开头)')
    i, n = 0, len(body)
    while i < n:
        no, raw = body[i]
        s = raw.strip()
        i += 1
        if not s or s.startswith('<!--'):
            continue
        if SCENE_HEAD.match(s) and not CUE_INLINE.match(s):
            if cur['headed'] or cur['speeches'] or cur['parens'] or cur['action']:
                scenes.append(cur)
            cur = _scene(s.lstrip('#').strip())
            continue
        cue = cue_of(s)
        if cue:
            sp = _speech(cue[0], cue[1], no)
            if cue[1]:
                cur['parens'].append(cue[1])
            loose = i < n and not body[i][1].strip()
            i = (_loose_block if loose else _tight_block)(body, i, sp, cur)
            if sp['first']:
                cur['speeches'].append(sp)
            continue
        if s.startswith(('|', '- ', '>')):
            cur['action'].append((no, s))
            continue
        m = CUE_INLINE.match(s)
        if m:
            sp = _inline(m, no)
            if sp:
                if sp['cue_paren']:
                    cur['parens'].append(sp['cue_paren'])
                cur['speeches'].append(sp)
                continue
        if PAREN_ONLY.match(s):
            cur['parens'].append(s)
            continue
        cur['action'].append((no, s))
    if cur['headed'] or cur['speeches'] or cur['parens'] or cur['action']:
        scenes.append(cur)

    firsts = [sp['first'] for sc in scenes for sp in sc['speeches']]
    primary = lang if lang in ('en', 'zh') else ('zh' if firsts.count('zh') > firsts.count('en') else 'en')
    other = 0
    for sc in scenes:
        for sp in sc.pop('speeches'):
            texts = sp['cand'][primary]
            if not texts:
                other += 1
                continue
            paren = ' '.join([sp['cue_paren']] + sp['parens']).strip()
            sc['lines'].append({'speaker': sp['speaker'], 'text': ' '.join(texts), 'paren': paren, 'raw_no': sp['no'],
                                'lang': primary,
                                'offscreen': bool(OFFSCREEN.search(paren)) or sp['speaker'].casefold() in NARRATOR})
        sc.pop('headed')
    return scenes, {'body': note, 'lang': primary, 'other_lang_speeches': other, 'body_lines': len(body)}


def extract(path, lang='auto'):
    """兼容旧接口：只返回场景列表。"""
    return parse(path, lang)[0]


def content_words(t):
    return [w.lower() for w in WORD.findall(t) if w.lower() not in STOP]


def speaker_table(lines, names=None, lang='en'):
    """按说话人汇总（不分大小写）；names 是约束文件登记的人名，用来显示规范写法。"""
    names = names or {}
    spk = {}
    for x in lines:
        key = x['speaker'].casefold()
        d = spk.setdefault(key, {'name': names.get(key, x['speaker']), 'lines': 0, 'size': 0, 'questions': 0,
                                 'offscreen_lines': 0})
        d['lines'] += 1
        d['size'] += size_of(x['text'], lang)
        d['questions'] += is_question(x['text'])
        d['offscreen_lines'] += x['offscreen']
    for d in spk.values():
        d['mean'] = round(d['size'] / d['lines'], 1)
        d['offscreen'] = d['offscreen_lines'] == d['lines']
    return list(spk.values())


def analyse(scene, lang='en', rates=None, names=None):
    rates = rates or {}
    L = scene['lines']
    out = {'title': scene['title'], 'n_lines': len(L), 'lang': lang, 'flags': [], 'marked_lines': [],
           'unsupported': ['与上一句实词重合（要分词）'] if lang == 'zh' else []}
    if not L:
        return out
    unit = UNIT[lang]
    sizes = [size_of(x['text'], lang) for x in L]
    rate = rates.get('wps' if lang == 'en' else 'cps')
    out['total_size'] = sum(sizes)
    out['unit'] = unit
    out['est_seconds'] = round(sum(sizes) / rate, 1) if rate else None
    out['mean_size'] = round(statistics.mean(sizes), 1)
    short = THRESH['short_words'] if lang == 'en' else THRESH['short_chars']
    out['short_share'] = round(sum(1 for w in sizes if w <= short) / len(L), 2)
    table = speaker_table(L, names, lang)
    out['speakers'] = {d['name']: d for d in table}

    # 连续接话：换人，且上一句是问句（英文另算：与上一句有相同实词）。只是表面线索
    run, best, best_span = 0, 0, None
    for k in range(1, len(L)):
        prev, cur = L[k - 1], L[k]
        linked = cur['speaker'].casefold() != prev['speaker'].casefold() and (
            is_question(prev['text']) or (lang == 'en' and bool(set(content_words(cur['text'])) & set(content_words(prev['text'])))))
        run = run + 1 if linked else 0
        if run > best:
            best, best_span = run, (L[k - run]['raw_no'], cur['raw_no'])
    out['longest_linked_run'] = best
    if best + 1 >= THRESH['pingpong_run']:
        basis = '问号或相同实词' if lang == 'en' else '问号；中文不比较实词'
        out['flags'].append(f"连续接话：{best + 1} 句每句都换人、接着上一句（行 {best_span[0]}–{best_span[1]}；表面线索：{basis}）。"
                            f"复核这几句是不是都只在回答上一句、两人是不是都在回答作者；处境需要的保留 [推论]")
    if out['short_share'] >= THRESH['short_share_warn'] and len(L) >= 6:
        out['flags'].append(f"短句占比 {out['short_share']:.0%}：核对是一人一句的口号式短语，还是有真实往来（表面线索，需人工判断）[推论]")
    for d in table:
        if d['questions'] >= THRESH['question_min'] and d['questions'] / d['lines'] >= THRESH['question_share']:
            out['flags'].append(f"{d['name']} 的 {d['lines']} 句里 {d['questions']} 句是问句：核对他是不是一直在问、"
                                f"主动权是不是都在对方（表面线索）[推论]")

    for k, x in enumerate(L):
        t, tags = x['text'], []
        if lang == 'en':
            if EXPLAIN.search(t): tags.append(TAG['explain'])
            if RECAP.search(t): tags.append(TAG['recap'])
            if APHORISM.search(t.strip()): tags.append(TAG['aphorism'])
            if any(p.search(t) for p in ANTITHESIS): tags.append(TAG['antithesis'])
            if k and x['speaker'].casefold() != L[k - 1]['speaker'].casefold():
                a, b = set(content_words(t)), set(content_words(L[k - 1]['text']))
                if a and b and len(a & b) / len(a) >= THRESH['echo_overlap'] and len(a) >= 2:
                    tags.append(TAG['echo'])
        else:
            if EXPLAIN_ZH.search(t): tags.append(TAG['explain'])
            if RECAP_ZH.search(t): tags.append(TAG['recap'])
            if APHORISM_ZH.search(t.strip()): tags.append(TAG['aphorism'])
            if any(p.search(t) for p in ANTITHESIS_ZH): tags.append(TAG['antithesis'])
        if tags:
            name = (names or {}).get(x['speaker'].casefold(), x['speaker'])
            out['marked_lines'].append({'line': x['raw_no'], 'speaker': name, 'text': t, 'tags': tags})
    emo = [p for p in scene['parens'] if EMO_PAREN.search(p)]
    if emo:
        out['emotion_parens'] = emo
        out['flags'].append(f"{len(emo)} 处括号写的是情绪标签而不是可见动作（例：{emo[0]}）。强度依本场处境确定，不套用人物小传 [用户纠正 10-16]")
    clip = rates.get('clip_max')
    if out['est_seconds'] and clip and out['est_seconds'] > clip:
        out['flags'].append(f"台词约 {out['est_seconds']} s（口播），超过单条生成上限 {clip:g} s，制作至少要拆成 "
                            f"{math.ceil(out['est_seconds'] / clip)} 条；逐句确认是否必要（成片另加动作与停顿）")
    return out


def project_settings(path, constraints=None, wps=None, cps=None):
    """返回 (rates, names, 配置文件路径或 None, 警告)。"""
    cfg, warn = None, ''
    if constraints:
        cfg = Path(constraints)
        if not cfg.is_file():
            cfg, warn = None, f'约束文件不存在：{constraints}'
    else:
        cfg = find_constraints(path)
    rates, names = {}, {}
    if cfg:
        cons = load_constraints(cfg)
        rates = dict(cons['制作参数'])
        names = {n.casefold(): n for n in cons['人物']}
    if wps:
        rates['wps'] = wps
    if cps:
        rates['cps'] = cps
    return rates, names, cfg, warn


def report(path, lang='auto', constraints=None, wps=None, cps=None):
    """一个文件的检查结果：(元信息, 各场结果)。"""
    scenes, meta = parse(path, lang)
    rates, names, cfg, warn = project_settings(path, constraints, wps, cps)
    meta.update({'file': str(path), 'config': str(cfg) if cfg else None, 'rates': rates, 'warn': warn})
    results = [analyse(sc, meta['lang'], rates, names) for sc in scenes] or [analyse(_empty(), meta['lang'], rates, names)]
    return meta, results


def _empty():
    return {'title': '(无内容)', 'lines': [], 'parens': [], 'action': []}


def _rel(p):
    try:
        return str(Path(p).resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(p)


def describe(meta):
    body = {'markers': f"标记之间（{meta['body_lines']} 行）", 'no-markers': '未找到正文标记，按全文读（旧文件兼容）'}.get(
        meta['body'], f"⚠ 正文标记不成对：{meta['body']}，按能推断的范围读；请修正标记")
    lang = LANG_NAME[meta['lang']] + ('（另一种语言的行算对照翻译）' if meta['lang'] == 'en' else '')
    r = meta['rates']
    if r.get('wps') or r.get('cps'):
        parts = []
        if r.get('wps'): parts.append(f"英文 {r['wps']:g} 词/秒")
        if r.get('cps'): parts.append(f"中文 {r['cps']:g} 字/秒")
        if r.get('clip_max'): parts.append(f"单条上限 {r['clip_max']:g} s")
        cfg = f"{_rel(meta['config'])}（{'，'.join(parts)}）" if meta['config'] else '，'.join(parts) + '（命令行指定）'
    elif meta['config']:
        cfg = f"{_rel(meta['config'])}（没有制作参数，不估算时长）"
    else:
        cfg = '未找到 story/constraints.md，不估算时长（可用 --wps / --cps 临时指定）'
    out = f"  正文：{body} · 语言：{lang} · 配置：{cfg}"
    if meta['warn']:
        out += f"\n  ⚠ {meta['warn']}"
    return out


def main():
    ap = argparse.ArgumentParser(description='对白检查（film-story）：只给词面与结构线索，不打分。')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--lang', choices=('auto', 'en', 'zh'), default='auto', help='台词语言；默认按全文多数台词判断')
    ap.add_argument('--constraints', help='项目约束文件；不给时从场景文件往上找 story/constraints.md')
    ap.add_argument('--wps', type=float, help='英文语速（词/秒），临时覆盖配置')
    ap.add_argument('--cps', type=float, help='中文语速（字/秒），临时覆盖配置')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    files = [report(f, a.lang, a.constraints, a.wps, a.cps) for f in a.files]
    if a.json:
        print(json.dumps([dict(r, file=m['file'], body=m['body'], config=m['config'], rates=m['rates'],
                               other_lang_speeches=m['other_lang_speeches']) for m, rs in files for r in rs],
                         ensure_ascii=False, indent=2))
        return
    for meta, results in files:
        print(f"\n== {meta['file']} ==")
        print(describe(meta))
        for r in results:
            print(f"-- {r['title']}")
            if not r['n_lines']:
                other = meta['other_lang_speeches']
                if other:
                    o = 'zh' if meta['lang'] == 'en' else 'en'
                    print(f"  没有识别到{LANG_NAME[meta['lang']]}台词；全文另有 {other} 段{LANG_NAME[o]}台词未计入（用 --lang {o} 统计）")
                else:
                    print('  没有识别到台词行（安静戏，或写法未被识别）')
                continue
            sec = f" · 约 {r['est_seconds']} s" if r['est_seconds'] is not None else ''
            print(f"  台词 {r['n_lines']} 句 · 共 {r['total_size']} {r['unit']}{sec} · 平均 {r['mean_size']} {r['unit']}/句 · 短句 {r['short_share']:.0%}")
            for d in r['speakers'].values():
                off = '（画外）' if d['offscreen'] else ''
                print(f"    {d['name']}{off}: {d['lines']} 句, 平均 {d['mean']} {r['unit']}, 问句 {d['questions']}")
            for fl in r['flags']:
                print('  ! ' + fl)
            if r['marked_lines']:
                print('  词面线索（需人工判断）：')
                for m in r['marked_lines']:
                    print(f"    行{m['line']} {m['speaker']}: “{m['text']}”  ← {', '.join(m['tags'])}")
            if r['unsupported']:
                print('  中文不支持的线索：' + '；'.join(r['unsupported']))
        if meta['other_lang_speeches'] and any(r['n_lines'] for r in results):
            o = 'zh' if meta['lang'] == 'en' else 'en'
            print(f"  另有 {meta['other_lang_speeches']} 段只有{LANG_NAME[o]}的台词未计入")
    print('\n说明：以上是词面和结构线索，不是判断；阈值是通用默认。是否算问题，先对照本剧规则表（story/rules.md）和本场处境；'
          '判断标准是这句是否为该人物在当下处境中会对对方说的话。')


if __name__ == '__main__':
    main()
