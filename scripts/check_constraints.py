#!/usr/bin/env python3
"""约束检查（film-story）。把场景稿和项目约束文件对一遍，报：
  - 稿里出现、约束里没登记的人名（可能是擅自新增人物）
  - 禁用词（例：亲密动作、点破关系的词）
  - 场景头部必填项有没有
  - 每场说话人数 ≥3 的提示（竖幅同框限制）
  - 每场台词时长估算

用法: python3 check_constraints.py scene.md --constraints constraints.md
约束文件格式见 templates/constraints.md。退出码恒为 0，不替人判。"""
import argparse, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_dialogue import extract, WORD, THRESH  # noqa

SECTION = re.compile(r'^##\s*(.+?)\s*$')


def load_constraints(path):
    cons = {'人物': set(), '地点': set(), '禁用': [], '必填头部': [], '同框上限': 2}
    cur = None
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        m = SECTION.match(line.strip())
        if m:
            cur = m.group(1); continue
        s = line.strip().lstrip('-').strip()
        if not s or not cur:
            continue
        if cur.startswith('人物'):
            for name in re.split(r'[,，/｜|]', s):
                name = name.strip()
                if name: cons['人物'].add(name)
        elif cur.startswith('地点'):
            cons['地点'].add(s)
        elif cur.startswith('禁用'):
            cons['禁用'].append(s)
        elif cur.startswith('必填'):
            cons['必填头部'].append(s)
        elif cur.startswith('同框'):
            try: cons['同框上限'] = int(re.findall(r'\d+', s)[0])
            except Exception: pass
    return cons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file'); ap.add_argument('--constraints', required=True)
    a = ap.parse_args()
    cons = load_constraints(a.constraints)
    text = Path(a.file).read_text(encoding='utf-8')
    print(f"== {a.file} ==")
    missing = [h for h in cons['必填头部'] if h not in text]
    print('  头部必填项：' + ('齐' if not missing else '缺 ' + '、'.join(missing)))
    hits = []
    for w in cons['禁用']:
        for m in re.finditer(re.escape(w), text, re.I):
            ln = text.count('\n', 0, m.start()) + 1
            hits.append(f"行{ln} “{w}”")
    print('  禁用词：' + ('无' if not hits else '；'.join(hits)))
    known = {n.lower() for n in cons['人物']}
    seen = {}
    for sc in extract(a.file):
        spk = {x['speaker'] for x in sc['lines']}
        unknown = [s for s in spk if s.lower() not in known and s.lower() not in ('reporter', 'staffer', 'presenter', 'photographer', 'voice', '画外')]
        est = round(sum(len(WORD.findall(x['text'])) for x in sc['lines']) / THRESH['words_per_sec'], 1)
        print(f"  场「{sc['title']}」：说话人 {len(spk)} 人 {sorted(spk)} · 台词约 {est} s" + (f" · ⚠ 超过同框上限 {cons['同框上限']} 人，分镜要拆正反打或纵深错落" if len(spk) > cons['同框上限'] else ''))
        if unknown:
            print(f"    ⚠ 约束文件未登记的说话人：{unknown}（新增人物需先录入台账，并确认有参考图）")
    # 正文里出现的大写人名（非句首）
    caps = set(re.findall(r'(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})\b', text, re.M))
    cand = sorted(c for c in caps if c.lower() not in known and c not in {'The', 'And', 'But', 'Okay', 'Yeah', 'Hey', 'Rhett', 'Theo'} and c.lower() not in {w.lower() for w in cons['地点']})
    if cand:
        print('  正文中的其他大写词（核对是否有未经确认的人名 / 地名 / 品牌）：' + ', '.join(cand[:40]))
    print('说明：脚本只报线索；人物是否出场、台词是否保留，以台账和编剧判断为准。')


if __name__ == '__main__':
    main()
