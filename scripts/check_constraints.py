#!/usr/bin/env python3
"""约束检查（film-story）。把剧本文件和项目约束文件对一遍，报：
  - 头部必填项有没有（只查正文标记之前）
  - 禁用词（只查正文；本版改动、批注里引用的旧句不算）
  - 每场说话人，画内 / 画外分开；画内说话人超过同框上限时提示（同框人数看动作描写，脚本不推算）
  - 动作描写里提到的已登记人物（核对谁在场）
  - 稿里出现、约束里没登记的说话人（可能是擅自新增人物）
  - 正文中的其他大写词（核对是否有未经确认的人名 / 地名 / 品牌）
  - 正文里剩下的占位符（[AGENCY]、[CANON: …] 这类方括号标记；锁稿前清零）
  - 每场台词时长估算（约束文件有"制作参数"时）

用法: python3 check_constraints.py <剧本.md> [--constraints <项目>/story/constraints.md] [--lang auto|en|zh]
不给 --constraints 时从剧本文件往上找 story/constraints.md；找不到时只列占位符。约束文件格式见 templates/constraints.md。
输入也可以是 .pdf / .fountain（先转成 Markdown 再查；这时不查头部必填项，行号是转换后的）。
退出码恒为 0，不替人判。"""
import argparse, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_dialogue import CONVERTED_NOTE, START, END, body_lines, parse, size_of, source_of, speaker_table  # noqa: E402
from project_config import find_constraints, load_constraints  # noqa: E402

FORMAT_CUES = {'voice', 'narrator', '旁白', '画外', '画外音', 'v.o.', 'o.s.'}  # 格式词，不是人名
CAP = re.compile(r'\b([A-Z][a-z]{2,})\b')
CAP_STOP = {'The', 'And', 'But', 'Okay', 'Yeah', 'Hey'}
PLACEHOLDER = re.compile(r"\[(?:CANON[^\]]*|[A-Z][A-Z0-9 _/'’-]{1,30})\](?!\()")  # [AGENCY]、[SOMEONE'S SONG]、[CANON: …]；不算 Markdown 链接


def caps_candidates(lines, known, places):
    """正文里句中出现的大写词（句首、引号或破折号之后的不算）。"""
    out = set()
    for _, t in lines:
        for m in CAP.finditer(t):
            before = t[:m.start()].rstrip()
            if not before or before[-1] in '.!?—…“"\'(（-–:：':
                continue
            w = m.group(1)
            if w in CAP_STOP or w.casefold() in known or w.casefold() in places:
                continue
            out.add(w)
    return sorted(out)


def name_pattern(n):
    if re.search(r'[A-Za-z]', n):
        return re.compile(r'(?<![A-Za-z])' + re.escape(n) + r'(?![A-Za-z])', re.I)
    return re.compile(re.escape(n))


def placeholders(body):
    holes = [f"行{no} {m.group(0)}" for no, t in body for m in PLACEHOLDER.finditer(t)]
    return '无' if not holes else '；'.join(holes[:20]) + (f' 等 {len(holes)} 处' if len(holes) > 20 else '')


def main():
    ap = argparse.ArgumentParser(description='约束检查（film-story）：只报线索，不替人判。')
    ap.add_argument('file')
    ap.add_argument('--constraints', help='项目约束文件；不给时从剧本文件往上找 story/constraints.md')
    ap.add_argument('--lang', choices=('auto', 'en', 'zh'), default='auto')
    a = ap.parse_args()
    cfg = Path(a.constraints) if a.constraints else find_constraints(a.file)
    try:
        src = Path(source_of(a.file)).read_text(encoding='utf-8').splitlines()  # PDF、Fountain 先转成 Markdown
    except RuntimeError as err:
        print(f"== {a.file} ==\n  ⚠ {err}")
        return
    body, note = body_lines(src)
    converted = source_of(a.file) != a.file
    if not cfg or not cfg.is_file():  # 占位符不靠约束文件，照样列出来（别处来的稿常常不在项目里）
        print(f"== {a.file} ==\n  ⚠ 没有约束文件（{a.constraints or '往上没找到 story/constraints.md'}）；先按 templates/constraints.md 建一份")
        if converted:
            print('  ' + CONVERTED_NOTE)
        print('  占位符（锁稿前清零）：' + placeholders(body))
        return
    cons = load_constraints(cfg)
    first = next((i for i, l in enumerate(src) if START.search(l) or END.search(l)), len(src))
    header = '\n'.join(src[:first])
    print(f"== {a.file} ==")
    if converted:
        print('  ' + CONVERTED_NOTE)
    if note == 'no-markers':
        print('  正文：未找到正文标记，按全文查（旧文件兼容）')
    elif note != 'markers':
        print(f'  ⚠ 正文标记不成对：{note}，按能推断的范围查；请修正标记')
    missing = [h for h in cons['必填头部'] if h not in header]
    print('  头部必填项：' + ('来源不是 Markdown，没有头部可查' if converted else '齐' if not missing else '缺 ' + '、'.join(missing)))
    hits = []
    for w in cons['禁用']:
        pat = re.compile(re.escape(w), re.I)
        hits += [f"行{no} “{w}”" for no, t in body if pat.search(t)]
    print('  禁用词（只查正文）：' + ('无' if not hits else '；'.join(hits)))
    print('  占位符（锁稿前清零）：' + placeholders(body))

    names = {n.casefold(): n for n in cons['人物']}
    places = {p.casefold() for p in cons['地点']}
    rate = cons['制作参数']
    cap = cons['同框上限']
    scenes, meta = parse(a.file, a.lang)
    lang = meta['lang']
    unit = '词' if lang == 'en' else '字'
    per_sec = rate.get('wps' if lang == 'en' else 'cps')
    for sc in scenes:
        table = speaker_table(sc['lines'], names, lang)
        on = [d['name'] for d in table if not d['offscreen']]
        off = [d['name'] for d in table if d['offscreen']]
        size = sum(size_of(x['text'], lang) for x in sc['lines'])
        dur = f"台词约 {round(size / per_sec, 1)} s" if per_sec else f"台词 {size} {unit}（约束文件没有制作参数，不估秒）"
        who = f"说话人 {len(table)}（画内 {len(on)}：{'、'.join(on) or '无'}" + (f"；画外 {len(off)}：{'、'.join(off)}" if off else '') + '）'
        print(f"  场「{sc['mark'] + ' · ' if sc.get('mark') and sc['mark'] != sc['title'] else ''}{sc['title']}」：{who} · {dur}")
        seen = [n for n in cons['人物'] if any(name_pattern(n).search(t) for _, t in sc['action'])]
        if seen:
            print(f"    动作描写提到的已登记人物：{'、'.join(seen)}（谁在场、谁同框以正文为准）")
        if len(on) > cap:
            print(f"    ⚠ 画内说话人 {len(on)} 人，超过同框上限 {cap} 人；同框人数要看动作描写（在场无台词的人也算），分镜层再拆正反打或纵深错落")
        unknown = [d['name'] for d in table if d['name'].casefold() not in names and d['name'].casefold() not in FORMAT_CUES]
        if unknown:
            print(f"    ⚠ 约束文件未登记的说话人：{unknown}（新增人物需先录入台账，并确认有参考图）")
    cand = caps_candidates(body, set(names), places)
    if cand:
        print('  正文中的其他大写词（核对是否有未经确认的人名 / 地名 / 品牌）：' + ', '.join(cand[:40]))
    print('说明：脚本只报线索；人物是否出场、台词是否保留，以台账和编剧判断为准。')


if __name__ == '__main__':
    main()
