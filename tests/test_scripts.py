"""检查脚本回归：正文边界、台词块、语言、画内 / 画外、制作参数、表面线索的命名、约束检查只查正文（0.6.0）；
标准剧本格式的 Markdown、动作描写线索、Fountain / Markdown / 标准版面互转（0.7.1）。
场标记与按场取出（0.7.2）；比稿：结构有没有变、改了哪些句子，带精修简报核对锁定的台词（0.7.3）；
表演线索、占位符、指定改法，场标记分场与场号归一（0.7.4）；
分页、扉页、PDF 读写（读回时按上一行排没排满判断折行）、拆句识别、改动清单文件（0.7.5）。要 Chrome 和 swift 的用例在没有它们的机器上跳过。
夹具在 tests/fixtures/；每个用例先把夹具复制到临时目录，免得往上找到真实项目的 story/constraints.md。"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import check_dialogue as cd  # noqa: E402
from project_config import load_constraints  # noqa: E402


def scenes_of(path, lang='auto'):
    return cd.parse(path, lang)[0]


def write_script(path, *body, head=('# SAMPLE · Episode 2', '', '版本：Draft v0.3 · 2026-11-10 · 依据：节拍单 v0.5', '')):
    """写一份带头部和正文标记的剧本文件（body 一行一个参数）。"""
    Path(path).write_text('\n'.join(list(head) + ['<!-- script-body:start -->'] + list(body) + ['<!-- script-body:end -->', '']), encoding='utf-8')
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(ROOT / 'tests' / 'fixtures', self.tmp / 'fx')
        self.fx = self.tmp / 'fx'
        self.cons = self.fx / 'project' / 'story' / 'constraints.md'

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_script(self, name, *args):
        r = subprocess.run([sys.executable, str(SCRIPTS / name)] + [str(x) for x in args],
                           capture_output=True, text=True, cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def texts(self, path, lang='auto'):
        return [x['text'] for sc in scenes_of(path, lang) for x in sc['lines']]


class BodyBounds(Base):
    def test_annotations_after_body_not_counted(self):
        scenes, meta = cd.parse(self.fx / 'body-annotations.md')
        self.assertEqual(meta['body'], 'markers')
        self.assertEqual(len(scenes), 1)
        self.assertEqual(self.texts(self.fx / 'body-annotations.md'), ['You came.', 'Told you.'])

    def test_no_markers_reads_whole_file(self):
        scenes, meta = cd.parse(self.fx / 'no-markers.md')
        self.assertEqual(meta['body'], 'no-markers')
        self.assertEqual(self.texts(self.fx / 'no-markers.md'), ["You're late.", 'Traffic.'])
        self.assertIn('旧文件兼容', self.run_script('check_dialogue.py', self.fx / 'no-markers.md'))

    def test_unpaired_markers_reported(self):
        scenes, meta = cd.parse(self.fx / 'unpaired.md')
        self.assertTrue(meta['body'].startswith('unpaired'))
        self.assertEqual(self.texts(self.fx / 'unpaired.md'), ["You're late.", 'Traffic.'])
        self.assertIn('正文标记不成对', self.run_script('check_dialogue.py', self.fx / 'unpaired.md'))


class Blocks(Base):
    def test_multiline_speech_and_name_translation(self):
        self.assertEqual(self.texts(self.fx / 'multiline.md'), [
            'Rhett.', "Yeah. That should've been an easy question. But I guess I couldn't always tell what was real."])

    def test_blank_lines_between_cue_paren_and_line(self):
        lines = scenes_of(self.fx / 'loose.md')[0]['lines']
        self.assertEqual([(x['speaker'], x['text']) for x in lines], [
            ('EZRA', 'That was really good.'), ('EVELYN', 'Hey. You came.'), ('June', 'Clothes— the chair.')])
        self.assertEqual(lines[0]['paren'], '（真心实意地，语气放松）')

    def test_inline_labels_and_scene_heading(self):
        scenes = scenes_of(self.fx / 'inline.md')
        self.assertEqual(scenes[0]['title'], '07｜内景 June 家／Vera 工作室—7:02 PM')
        self.assertEqual([x['speaker'] for x in scenes[0]['lines']], ['June', 'Vera', 'June'])


class Language(Base):
    def test_zh_auto(self):
        scenes, meta = cd.parse(self.fx / 'zh-scene.md')
        self.assertEqual(meta['lang'], 'zh')
        r = cd.analyse(scenes[0], meta['lang'])
        self.assertEqual(r['n_lines'], 4)
        self.assertEqual(r['unit'], '字')
        self.assertTrue(r['unsupported'])
        tags = {m['text']: m['tags'] for m in r['marked_lines']}
        self.assertIn(cd.TAG['antithesis'], tags['加班。不是我想晚，而是事情没做完。'])
        self.assertIn(cd.TAG['recap'], tags['你说过这周不加班的。'])
        self.assertEqual(r['speakers']['妈妈']['questions'], 1)

    def test_forced_lang_reports_what_was_left_out(self):
        out = self.run_script('check_dialogue.py', self.fx / 'zh-scene.md', '--lang', 'en')
        self.assertIn('未计入', out)
        self.assertIn('--lang zh', out)

    def test_zh_output_names_unsupported_cue(self):
        self.assertIn('中文不支持的线索', self.run_script('check_dialogue.py', self.fx / 'zh-scene.md'))


class Offscreen(Base):
    def test_phone_voices_are_offscreen(self):
        lines = scenes_of(self.fx / 'phone.md')[0]['lines']
        self.assertEqual([(x['speaker'], x['offscreen']) for x in lines],
                         [('JO', True), ('THEO', False), ('HOLLIS', True), ('THEO', False)])

    def test_constraints_split_on_and_offscreen(self):
        out = self.run_script('check_constraints.py', self.fx / 'phone.md', '--constraints', self.cons)
        self.assertIn('画内 1：Theo；画外 2：Jo、Hollis', out)
        self.assertNotIn('超过同框上限', out)
        self.assertIn('动作描写提到的已登记人物：Theo、Rhett', out)


class Config(Base):
    def test_rates_parse_blank_and_comment_lines(self):
        self.assertEqual(load_constraints(self.cons)['制作参数'], {'wps': 4.0, 'clip_max': 10.0})

    def test_discovery_and_clip_warning(self):
        meta, rs = cd.report(self.fx / 'project' / 'ep01' / '03_script' / 's01-long.md')
        self.assertTrue(meta['config'].endswith('constraints.md'))
        self.assertEqual(rs[0]['est_seconds'], round(rs[0]['total_size'] / 4, 1))
        self.assertTrue(any('超过单条生成上限 10 s' in f for f in rs[0]['flags']))

    def test_no_config_means_no_seconds(self):
        meta, rs = cd.report(self.fx / 'no-markers.md')
        self.assertIsNone(meta['config'])
        self.assertIsNone(rs[0]['est_seconds'])
        self.assertIn('不估算时长', cd.describe(meta))

    def test_cli_rate_override(self):
        meta, rs = cd.report(self.fx / 'no-markers.md', wps=2)
        self.assertEqual(rs[0]['est_seconds'], round(rs[0]['total_size'] / 2, 1))


class Labels(Base):
    def test_surface_cue_wording(self):
        out = self.run_script('check_dialogue.py', self.fx / 'questions.md')
        self.assertIn('连续接话', out)
        self.assertIn('表面线索', out)
        self.assertNotIn('精准', out)

    def test_question_share_flag(self):
        r = cd.analyse(scenes_of(self.fx / 'questions.md')[0])
        self.assertTrue(any(f.startswith('THEO 的 4 句里 4 句是问句') for f in r['flags']), r['flags'])

    def test_display_names(self):
        sc = scenes_of(self.fx / 'questions.md')[0]
        self.assertIn('DJ', cd.analyse(sc)['speakers'])
        self.assertIn('Theo', cd.analyse(sc, names={'theo': 'Theo'})['speakers'])


class Constraints(Base):
    def hole(self, text):
        p = self.fx / 'hole.md'
        p.write_text((self.fx / 'episode.md').read_text(encoding='utf-8').replace('One more.', text), encoding='utf-8')
        return p

    def test_forbidden_word_outside_body_ignored(self):
        out = self.run_script('check_constraints.py', self.fx / 'body-annotations.md', '--constraints', self.cons)
        self.assertIn('禁用词（只查正文）：无', out)
        self.assertIn('头部必填项：齐', out)
        for w in ('Mike', 'Torres', 'Remember'):
            self.assertNotIn(w, out)

    def test_forbidden_word_in_body_flagged(self):
        p = self.fx / 'kiss.md'
        p.write_text('<!-- script-body:start -->\n场 01 · 内 · 车里 · 夜\n\nTheo leans in for a kiss.\n<!-- script-body:end -->\n',
                     encoding='utf-8')
        self.assertIn('行4 “kiss”', self.run_script('check_constraints.py', p, '--constraints', self.cons))

    def test_missing_header_reported(self):
        out = self.run_script('check_constraints.py', self.fx / 'unpaired.md', '--constraints', self.cons)
        self.assertIn('缺 本场改变了什么：、新事实（提案）：', out)

    def test_placeholders_listed(self):
        p = self.hole('[AGENCY] wants one more. See [the note](x) and [CANON: name].')
        c = self.fx / 'ep-cons2.md'
        c.write_text('## 人物\n- Dev, Mara\n', encoding='utf-8')
        out = self.run_script('check_constraints.py', p, '--constraints', c)
        self.assertIn('[AGENCY]', out)
        self.assertIn('[CANON: name]', out)
        self.assertNotIn('[the note]', out)
        self.assertIn('占位符（锁稿前清零）：无', self.run_script('check_constraints.py', self.fx / 'episode.md', '--constraints', c))

    def test_no_built_in_name_exemptions(self):
        c = self.fx / 'only-jo.md'
        c.write_text('## 人物\n- Jo\n', encoding='utf-8')
        out = self.run_script('check_constraints.py', self.fx / 'no-markers.md', '--constraints', c)
        self.assertIn("未登记的说话人：['THEO', 'RHETT']", out)


class StandardFormat(Base):
    """标准剧本格式的 Markdown：二级标题是场景标题，加粗全大写单独一行是角色名，下面紧跟台词。"""

    def test_elements_are_told_apart(self):
        scenes, meta = cd.parse(self.fx / 'standard.md')
        self.assertEqual(meta['body'], 'markers')
        self.assertEqual([sc['title'] for sc in scenes], ['INT. KITCHEN - NIGHT'])
        lines = scenes[0]['lines']
        self.assertEqual([(x['speaker'], x['text'], x['offscreen']) for x in lines], [
            ('DEV', "You kept the old sign.", False), ('MARA', 'Still works.', False), ('MARA', 'Told you.', True)])
        self.assertEqual(lines[2]['paren'], '(V.O.) (laughing)')
        action = [t for _, t in scenes[0]['action']]
        for kept in ('Pull back: two stools, one of them empty.', 'The note on the fridge reads: "BACK AT TEN."',
                     'SILENCE.', '**THE NEXT MORNING**', '### AT THE WINDOW'):
            self.assertIn(kept, action)  # 带冒号的动作、全大写的动作、片名卡、小标题都不是角色名
        self.assertNotIn('CUT TO:', action)  # 转场不算动作

    def test_action_cues(self):
        p = self.fx / 'long.md'
        long_para = ' '.join(['He crosses the room and sets the glass down on the far end of the bar.'] * 4)
        p.write_text(f'<!-- script-body:start -->\n## INT. BAR - NIGHT\n\n{long_para}\n\nMara 觉得他在躲她。\n\n' +
                     ''.join(f'**{n}**\nLine {k}.\n\n' for k, n in enumerate(['DEV', 'MARA'] * 4)) +
                     '<!-- script-body:end -->\n', encoding='utf-8')
        meta, rs = cd.report(p)
        act = rs[0]['action']
        self.assertEqual((act['paras'], act['max_lines'], act['long_paras'], act['dialogue_run']), (2, 5, [(4, 5)], 8))
        self.assertEqual([(m['line'], m['words']) for m in act['marks']], [(6, ['觉得'])])
        self.assertTrue(any(f.startswith('动作段偏长：行 4（约 5 行）') for f in rs[0]['flags']), rs[0]['flags'])
        self.assertTrue(any(f.startswith('连续 8 句对白中间没有动作段') for f in rs[0]['flags']), rs[0]['flags'])
        out = self.run_script('check_dialogue.py', p)
        self.assertIn('动作描写 2 段', out)
        self.assertIn('← 觉得', out)

    def test_inner_word_in_standard_fixture(self):
        meta, rs = cd.report(self.fx / 'standard.md')
        self.assertEqual([m['words'] for m in rs[0]['action']['marks']], [['realizes']])
        self.assertEqual(rs[0]['action']['dialogue_run'], 2)  # 小标题不算动作段：MARA → MARA (V.O.) 连着

    def test_no_action_cues_without_markers(self):
        meta, rs = cd.report(self.fx / 'no-markers.md')
        self.assertNotIn('action', rs[0])


class EpisodeFile(Base):
    """一集一个文件：每场开头一行场标记，一场可以有几个场景标题。"""

    def test_units_follow_scene_markers(self):
        scenes, meta = cd.parse(self.fx / 'episode.md')
        self.assertEqual([(sc['mark'], sc['title']) for sc in scenes], [
            ('S01 · THE BAR', 'INT. BAR - NIGHT'), ('S01 · THE BAR', 'EXT. STREET - CONTINUOUS'),
            ('S02 · THE MORNING AFTER', 'INT. KITCHEN - MORNING'), ('S10 · LATER', 'INT. BAR - NIGHT')])

    def test_totals_per_scene(self):
        meta, rs = cd.report(self.fx / 'episode.md', wps=4)
        self.assertEqual(cd.unit_totals(rs), [('S01 · THE BAR', 3, 8, 2.0), ('S02 · THE MORNING AFTER', 1, 1, 0.2),
                                              ('S10 · LATER', 1, 2, 0.5)])
        out = self.run_script('check_dialogue.py', self.fx / 'episode.md', '--wps', '4')
        self.assertIn('-- [S01 · THE BAR] EXT. STREET - CONTINUOUS', out)
        self.assertIn('S01 · THE BAR：台词 3 句 · 8 词 · 约 2 s', out)

    def test_marker_starts_a_scene_and_any_h2_is_a_heading(self):
        p = self.fx / 'zh-episode.md'
        p.write_text('# 测试 · 第一集\n\n<!-- script-body:start -->\n<!-- 场 01 · 厨房 -->\n## 内 · 厨房 · 夜\n\n妈妈停下手里的活，看着她。\n\n'
                     '**妈妈**\n嗯，你又回来这么晚……\n\n（沉默）\n\n<!-- 场 02 · 门口 -->\n\n**女儿**\n我走了。\n\n## 外 · 楼道 · 夜\n\n灯坏了。\n'
                     '<!-- script-body:end -->\n', encoding='utf-8')
        scenes, meta = cd.parse(p)
        self.assertEqual([(sc['mark'], sc['title']) for sc in scenes], [
            ('场 01 · 厨房', '内 · 厨房 · 夜'), ('场 02 · 门口', '场 02 · 门口'), ('场 02 · 门口', '外 · 楼道 · 夜')])
        self.assertEqual([x['speaker'] for sc in scenes for x in sc['lines']], ['妈妈', '女儿'])  # 场标记后面没跟标题，台词也归这一场
        cues = cd.performance_cues(scenes[0])
        self.assertEqual({k: cues[k] for k, _ in cd.PERF_KEYS}, {'stops': 1, 'beats': 1, 'looks': 1, 'fillers': 1, 'unfinished': 1})
        self.assertEqual(cd.mark_label('场 01 · 厨房'), cd.mark_label('s1'))
        out = self.run_script('render_screenplay.py', p, '--scene', 'S2')
        self.assertIn('我走了。', out)
        self.assertNotIn('回来这么晚', out)
        self.assertNotIn('格式提示', out)  # "内 / 外 · 地点 · 时间"是中文稿的标准写法
        brief = self.fx / 'zh-brief.md'
        brief.write_text('### 锁定的台词\n- 场 02 > 我走了。\n- S01 > 我走了。\n', encoding='utf-8')
        out = self.run_script('compare_drafts.py', p, '--brief', brief)
        self.assertIn('⚠ 锁定的台词少了 1 句（共 2 句）：', out)
        self.assertIn('- S01 > 我走了。', out)

    def test_word_lists_skip_known_lookalikes(self):
        p = self.fx / 'look.md'
        p.write_text('<!-- script-body:start -->\n## INT. BAR - NIGHT\n\nPause.\n\nHe checks his watch.\n\n**DEV**\nDo you know where it is?\n\n'
                     '**MARA**\nI mean, no.\n<!-- script-body:end -->\n', encoding='utf-8')
        cues = cd.performance_cues(cd.parse(p)[0][0])
        self.assertEqual({k: cues[k] for k, _ in cd.PERF_KEYS}, {'stops': 0, 'beats': 1, 'looks': 0, 'fillers': 1, 'unfinished': 0})

    def test_no_markers_no_totals(self):
        self.assertNotIn('按场合计', self.run_script('check_dialogue.py', self.fx / 'standard.md'))

    def test_episode_header_checked_once(self):
        c = self.fx / 'ep-cons.md'
        c.write_text('## 人物\n- Dev, Mara\n\n## 必填头部\n- 版本：\n- 承接：\n- 新事实（提案）：\n- 状态：\n', encoding='utf-8')
        out = self.run_script('check_constraints.py', self.fx / 'episode.md', '--constraints', c)
        self.assertIn('头部必填项：齐', out)
        self.assertIn('场「S02 · THE MORNING AFTER · INT. KITCHEN - MORNING」', out)
        self.assertNotIn('未登记的说话人', out)


class Render(Base):
    """render_screenplay.py：Fountain / Markdown 互转，标准版面的纯文本和标准页。"""

    def test_fountain_to_markdown(self):
        out = self.tmp / 'out.md'
        msg = self.run_script('render_screenplay.py', self.fx / 'sample.fountain', '--md', out)
        self.assertIn('场景标题 2 个 · 台词 3 段', msg)
        md = out.read_text(encoding='utf-8')
        for piece in ('# SAMPLE · Episode 1\n', 'Draft v0.1 · 2026-11-09\n', '<!-- script-body:start -->\n## INT. KITCHEN - NIGHT\n',
                      "**DEV**\nYou kept the old sign.\n", '### AT THE WINDOW\n', '**MARA (V.O.)**\n(laughing)\nTold you.\n',
                      '**THE NEXT MORNING**\n', '## KITCHEN, LATER\n', '**McAVOY**\nMorning.\n', 'FADE OUT.\n<!-- script-body:end -->'):
            self.assertIn(piece, md)
        scenes = scenes_of(out)  # 转出来的 Markdown，检查脚本读得出同样的台词，分场也和转换脚本一致
        self.assertEqual([sc['title'] for sc in scenes], ['INT. KITCHEN - NIGHT', 'KITCHEN, LATER'])
        self.assertEqual([(x['speaker'], x['offscreen']) for sc in scenes for x in sc['lines']],
                         [('DEV', False), ('MARA', True), ('McAVOY', False)])

    def test_round_trip_keeps_every_line(self):
        md, back = self.tmp / 'out.md', self.tmp / 'back.fountain'
        self.run_script('render_screenplay.py', self.fx / 'sample.fountain', '--md', md)
        self.run_script('render_screenplay.py', md, '--fountain', back)
        body = lambda p: p.read_text(encoding='utf-8').split('\n\n', 1)[1].strip()  # 扉页的几行之后
        self.assertEqual(body(back), (self.fx / 'sample.fountain').read_text(encoding='utf-8').split('\n\n', 1)[1].strip())
        self.assertTrue(back.read_text(encoding='utf-8').startswith('Title:\n    SAMPLE\n    Episode 1\nCredit: Draft v0.1\n'))

    def test_text_layout_columns(self):
        out = self.run_script('render_screenplay.py', self.fx / 'standard.md').splitlines()
        self.assertIn('INT. KITCHEN - NIGHT', out)
        self.assertIn(' ' * 20 + 'DEV', out)
        self.assertIn(' ' * 20 + 'MARA (V.O.)', out)
        self.assertIn(' ' * 15 + '(laughing)', out)
        self.assertIn(' ' * 10 + "You kept the old sign.", out)
        self.assertIn(' ' * 10 + '你还留着旧招牌。', out)
        self.assertIn('AT THE WINDOW', out)
        self.assertIn(' ' * 53 + 'CUT TO:', out)  # 转场靠右，收在第 60 格
        self.assertIn(' ' * 22 + 'THE NEXT MORNING', out)  # 片名卡居中
        self.assertTrue(all(cd.display_width(l) <= 60 for l in out[:-1]), [l for l in out if cd.display_width(l) > 60])
        self.assertIn('对照翻译 2 行在内', out[-1])

    def test_wrap_measures_cjk_at_its_real_width(self):
        import screenplay_pages as sp
        # 中文一个字 12 pt，35 格（252 pt）放 21 个字；不是按"一字两格"放 17 个
        self.assertEqual(sp.wrap('他把手机举高一点，咳了一声。' * 3, 35),
                         ['他把手机举高一点，咳了一声。他把手机举高一', '点，咳了一声。他把手机举高一点，咳了一声。'])
        self.assertEqual(sp.wrap('You changed the sign three weeks ago, I think.', 35), ['You changed the sign three weeks', 'ago, I think.'])
        long = sp.wrap('See https://example.com/' + 'a/very/long/path/' * 6 + 'index.html now.', 35)
        self.assertTrue(all(sp.units(x) <= 35 * 3 for x in long), long)  # 比一行还宽的词硬切，不排出页边
        self.assertEqual(''.join(long).replace(' ', ''), ('See https://example.com/' + 'a/very/long/path/' * 6 + 'index.html now.').replace(' ', ''))
        self.assertEqual(sp.unmarked('She *really* means **it**, 2*3*4.'), 'She really means it, 2*3*4.')  # 版面上不印星号

    def test_no_translation(self):
        out = self.run_script('render_screenplay.py', self.fx / 'standard.md', '--no-translation')
        self.assertNotIn('你还留着旧招牌。', out)
        self.assertIn('对照翻译 2 行已去掉', out)

    def test_html_page_spec(self):
        page = self.tmp / 'out.html'
        self.run_script('render_screenplay.py', self.fx / 'standard.md', '--html', page, '--title', 'SAMPLE')
        h = page.read_text(encoding='utf-8')
        for piece in ('<title>SAMPLE</title>', '12pt/12pt "Courier Prime", "Courier New", Courier', '@page { size: 8.5in 11in; margin: 0; }',
                      'padding: 1in 1in 0 1.5in', '<span class="c">SAMPLE</span>', '<pre>INT. KITCHEN - NIGHT\n', '\n' + ' ' * 20 + 'MARA (V.O.)\n',
                      '\n' + ' ' * 15 + '(laughing)\n', '\n' + ' ' * 10 + '还能用。\n', '<span class="r">CUT TO:</span>',
                      '<span class="c">THE NEXT MORNING</span>'):  # 和 PDF 是同一份排好的页：扉页一页，正文按格数缩进
            self.assertIn(piece, h)

    def test_scene_markers_survive_both_ways(self):
        md, ftn, back = self.tmp / 'out.md', self.tmp / 'out.fountain', self.tmp / 'back.md'
        self.run_script('render_screenplay.py', self.fx / 'episode.md', '--md', md, '--fountain', ftn)
        self.assertIn('<!-- S01 · THE BAR -->\n## INT. BAR - NIGHT\n', md.read_text(encoding='utf-8'))
        self.assertIn('# S02 · THE MORNING AFTER\n\nINT. KITCHEN - MORNING\n', ftn.read_text(encoding='utf-8'))
        self.run_script('render_screenplay.py', ftn, '--md', back)
        self.assertIn('<!-- S02 · THE MORNING AFTER -->\n## INT. KITCHEN - MORNING\n', back.read_text(encoding='utf-8'))
        self.assertNotIn('S01', '\n'.join(self.run_script('render_screenplay.py', self.fx / 'episode.md').splitlines()[:-1]))

    def test_take_one_scene(self):
        out = self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 'S7')
        self.assertIn('没有找到 S7。文件里的场：S01 · THE BAR、S02 · THE MORNING AFTER、S10 · LATER', out)
        out = self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 's1')  # s1、S01、场 1 是同一场，不是 S10
        self.assertIn('EXT. STREET - CONTINUOUS', out)  # 一场可以有几个场景标题
        self.assertNotIn('Morning.', out)
        self.assertNotIn('One more.', out)
        self.assertIn('场 1 个 · 场景标题 2 个 · 台词 3 段', out)
        self.assertIn('对照翻译 1 行在内', out)
        md = self.tmp / 's02.md'
        self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 'S02,S10', '--md', md)
        self.assertEqual([x['text'] for sc in scenes_of(md) for x in sc['lines']], ['Morning.', 'One more.'])

    def test_title_of_old_file_without_markers(self):
        p = self.fx / 'old.md'
        p.write_text("# OLD · 场 01\n\n场 01 · 内 · 酒吧 · 夜\n\n**DEV**\nHi.\n", encoding='utf-8')
        out = self.run_script('render_screenplay.py', p).splitlines()
        self.assertIn('OLD · 场 01', out[0])  # 标题取到了
        self.assertEqual(sum('OLD · 场 01' in l for l in out), 1)  # 没有再当成小标题排一遍

    def test_format_notes(self):
        out = self.run_script('render_screenplay.py', self.fx / 'body-annotations.md')
        self.assertIn('格式提示：场景标题不是「INT. / EXT. 地点 - 时间」「内 / 外 · 地点 · 时间」或「内景 地点 - 时间」的有 1 处', out)


class CompareDrafts(Base):
    """compare_drafts.py：两版剧本的结构有没有变（场、场景标题、每场的说话人），改了哪些句子。"""

    def variant(self, name, *swaps):
        text = (self.fx / 'episode.md').read_text(encoding='utf-8')
        for a, b in swaps:
            self.assertIn(a, text)
            text = text.replace(a, b)
        p = self.fx / name
        p.write_text(text, encoding='utf-8')
        return p

    def polished(self):
        return self.variant('polish.md', ("You kept the old sign.", "You kept the sign."), ('**DEV**\nNight.\n\n', ''),
                            ('Dev pours two coffees.', 'Dev pours two coffees and slides one across.'))

    def test_polish_leaves_structure_alone(self):
        import compare_drafts as cmp
        r = cmp.compare(self.fx / 'episode.md', self.polished(), wps=4)
        self.assertTrue(r['by_mark'])
        self.assertEqual(r['structure'], [])
        self.assertEqual([(x['scene'], x['kind'], x['what']) for x in r['items']],
                         [('S01', '改', 'line'), ('S01', '删', 'line'), ('S02', '改', 'para')])
        self.assertEqual((r['old_total'][0], r['new_total'][0]), (5, 4))
        self.assertEqual(r['scenes'][0]['seconds'], [2.0, 1.5])

    def test_report_gives_pasteable_change_list(self):
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', self.polished(), '--wps', '4')
        for piece in ('按场标记对齐（3 → 3 场）', '结构：场、场景标题、每场的说话人都没变。', '台词：5 → 4 句 · 改 1 · 删 1 · 加 0',
                      "- S01 改：> You kept the old sign. → > You kept the sign.", '- S01 删：> Night.（DEV）',
                      '- S02 改：> Dev pours two coffees. → > Dev pours two coffees and slides one across.'):
            self.assertIn(piece, out)

    def test_structure_changes_are_named(self):
        new = self.variant('rewrite.md', ('<!-- S02 · THE MORNING AFTER -->\n## INT. KITCHEN - MORNING\n\n**MARA**\nMorning.\n\nDev pours two coffees.\n\n', ''),
                           ('**DEV**\nOne more.', '**NIA**\nOne more.\n\n## EXT. ALLEY - NIGHT\n\nRain.'))
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new)
        for piece in ('结构变了', '少了场：S02 · THE MORNING AFTER', 'S10：场景标题 1 → 2（多了 EXT. ALLEY - NIGHT）',
                      'S10：说话人少了 DEV；多了 NIA'):
            self.assertIn(piece, out)

    def test_same_file_and_no_markers(self):
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', self.fx / 'episode.md')
        self.assertIn('两版的台词和动作一字未改。', out)
        out = self.run_script('compare_drafts.py', self.fx / 'standard.md', self.fx / 'standard.md')
        self.assertIn('没有场标记，按场景标题对齐（1 → 1 个）', out)

    def test_brief_locked_lines_and_declared_rewrite(self):
        new = self.variant('v3.md', ('Still works.', 'Still works fine.'),
                           ('**DEV**\nOne more.', '**NIA**\nOne more.\n\n## EXT. ALLEY - NIGHT\n\nRain.'))
        import compare_drafts as cmp
        r = cmp.compare(self.fx / 'episode.md', new, brief=self.fx / 'polish-brief.md')
        self.assertEqual(r['structure'], [])  # S10 登记了局部重写，结构变化不算越界
        self.assertEqual(len(r['declared']), 2)
        self.assertEqual(r['locked']['total'], 3)
        self.assertEqual([(x['scene'], x['text'], x['closest']) for x in r['locked']['missing']],
                         [('S01', 'Still works.', 'Still works fine.'), ('S10', 'One more round.', 'One more.')])
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new, '--brief', self.fx / 'polish-brief.md')
        for piece in ('结构：没登记的场，场、场景标题、每场的说话人都没变。', '登记了局部重写的场有结构变化（简报里写了，不算越界）：',
                      '⚠ 锁定的台词少了 2 句（共 3 句）：', '- S01 > Still works.（现在最接近的一句：Still works fine.）'):
            self.assertIn(piece, out)

    def test_brief_named_edits(self):
        import compare_drafts as cmp
        self.assertEqual(cmp.read_brief(self.fx / 'polish-brief.md')[1],
                         [('S01', 'Night.', 'Good night.'), ('S02', 'Morning.', 'Morning, you.')])
        new = self.variant('named.md', ('**DEV**\nNight.', '**DEV**\nGood night.'))
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new, '--brief', self.fx / 'polish-brief.md')
        self.assertIn('⚠ 指定改法有 1 处没改（共 2 处）：', out)
        self.assertIn('- S02 > Morning, you.（旧句还在：Morning.）', out)
        self.assertNotIn('S01 > Good night.（', out)

    def test_performance_cues_before_and_after(self):
        new = self.variant('perf.md', ('Dev pours two coffees.', 'Dev stops pouring. Beat.\n\nMara looks at him.'),
                           ('**MARA**\nMorning.', '**MARA**\n(beat)\nUm, morning—'))
        scenes, meta = cd.parse(new)
        cues = cd.performance_cues(scenes[2])
        self.assertEqual({k: cues[k] for k, _ in cd.PERF_KEYS}, {'stops': 1, 'beats': 2, 'looks': 1, 'fillers': 1, 'unfinished': 1})
        out = self.run_script('check_dialogue.py', new)
        self.assertIn('表演线索（只数不判）：停手 1 · 停顿 2 · 对视 1 · 填充词 1 · 没说完 1', out)
        self.assertIn('停手 行', out)
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new)
        self.assertIn('表演线索（只数不判）：停手 0 → 1 · 停顿 0 → 2 · 对视 0 → 1 · 填充词 0 → 1 · 没说完 0 → 1', out)

    def test_brief_alone_checks_locked_lines(self):
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', self.fx / 'polish-brief.md')
        self.assertIn('== 核对锁定的台词和指定改法：episode.md ==', out)
        self.assertIn('⚠ 锁定的台词少了 1 句（共 3 句）：', out)  # 带引号写的 "Morning." 也认
        self.assertIn('- S10 > One more round.', out)
        self.assertIn('找不到精修简报', self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', self.fx / 'nope.md'))

    def test_dialogue_only_for_language_versions(self):
        zh = self.variant('zh.md', ('The overhead light hums.', '头顶的灯嗡嗡响。'), ('Dev pours two coffees.', 'Dev 倒了两杯咖啡。'),
                          ('## EXT. STREET - CONTINUOUS', '## 外 · 街上 · 接上'))
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', zh, '--dialogue-only')
        for piece in ('只比对白', '结构：场、每场的说话人都没变。', '台词：5 → 5 句 · 改 0 · 删 0 · 加 0', '两版的台词一字未改。'):
            self.assertIn(piece, out)
        self.assertNotIn('动作：', out)

    def test_speaker_case_is_not_a_change(self):
        new = self.variant('case.md', ('**MARA**\nStill works.', '**Mara**\nStill works.'))
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new)
        self.assertIn('台词：5 → 5 句 · 改 0 · 删 0 · 加 0', out)
        self.assertNotIn('本版改动', out)

    def test_added_scene_and_reorder(self):
        text = (self.fx / 'episode.md').read_text(encoding='utf-8')
        s2 = text[text.index('<!-- S02'):text.index('<!-- S10')]
        s10 = text[text.index('<!-- S10'):text.index('<!-- script-body:end -->')]
        new = self.fx / 'moved.md'
        new.write_text(text.replace(s2 + s10, s10 + '\n' + s2 + '<!-- S11 · CODA -->\n## INT. BAR - DAWN\n\nEmpty.\n'), encoding='utf-8')
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new)
        self.assertIn('多了场：S11 · CODA', out)
        self.assertIn('场的顺序变了：S01 → S10 → S02', out)

    def test_brief_scene_numbers_and_strict_rewrite_rows(self):
        import compare_drafts as cmp
        brief = self.fx / 'b.md'
        brief.write_text('### 锁定的台词\n- s1 > Still works.\n- 场 02 > Morning.\n- S07 > Hello.\n\n### 指定改法\n'
                         '- S10 > One more. → Last one. (too flat)\n- S7 > A. → B.\n\n| 场 | 这一轮 | 保留 | 改 | 结果 |\n|---|---|---|---|---|\n'
                         '| S01 · THE BAR | 小改 | | 不做局部重写 | |\n| S02 · X | 基本不动 | | | 建议下一轮局部重写 |\n'
                         '| **S10** · LATER | 局部重写 | | | |\n', encoding='utf-8')
        locked, edits, rewrite = cmp.read_brief(brief)
        self.assertEqual(rewrite, {'10'})  # 只认第二栏正好写着"局部重写"的行
        self.assertEqual(edits, [('S10', 'One more.', 'Last one.'), ('S7', 'A.', 'B.')])  # 半角括号里的原因也去掉
        r = cmp.locked_only(self.fx / 'episode.md', brief)
        self.assertEqual([(x['scene'], x['no_scene']) for x in r['locked']['missing']], [('S07', True)])
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', brief)
        self.assertIn('- S07 > Hello.（剧本里没有这一场的场标记）', out)
        self.assertIn('- S10 > Last one.（旧句还在：One more.）', out)
        done = self.variant('done.md', ('One more.', 'Last one.'))
        self.assertNotIn('S10 > Last one.', self.run_script('compare_drafts.py', done, '--brief', brief))
        gone = self.variant('gone.md', ('One more.', 'Again.'))
        self.assertIn('- S10 > Last one.（旧句也不在了，核对一下改成了什么）', self.run_script('compare_drafts.py', gone, '--brief', brief))

    def test_brief_all_clear_and_empty(self):
        brief = self.fx / 'ok.md'
        brief.write_text('### 锁定的台词\n- S01 > Still works.\n\n### 指定改法\n- S02 > Hi. → Morning.\n', encoding='utf-8')
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', brief)
        self.assertIn('锁定的台词：1 句逐字都在。', out)
        self.assertIn('指定改法：1 处都改了。', out)
        empty = self.fx / 'empty.md'
        empty.write_text('# 精修简报\n', encoding='utf-8')
        self.assertIn('锁定的台词：简报里没有列', self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', empty))

    def test_without_scene_markers_says_so(self):
        text = (self.fx / 'episode.md').read_text(encoding='utf-8')
        bare = self.fx / 'bare.md'
        bare.write_text('\n'.join(l for l in text.splitlines() if not l.startswith('<!-- S')) + '\n', encoding='utf-8')
        out = self.run_script('compare_drafts.py', bare, bare, '--brief', self.fx / 'polish-brief.md')
        self.assertIn('没有场标记，按场景标题对齐（4 → 4 个）', out)
        self.assertIn('认不出简报里登记了局部重写的场', out)
        self.assertIn('锁定的台词和指定改法在全文里找，不分场', out)
        part = self.variant('part.md', ('<!-- S01 · THE BAR -->\n', ''))
        self.assertIn('不是每个场景标题前都有场标记，按场景标题对齐', self.run_script('compare_drafts.py', part, part))
        out = self.run_script('compare_drafts.py', self.fx / 'no-markers.md', self.fx / 'no-markers.md')
        self.assertIn('有一版没有正文标记，按全文读', out)

    def test_json_output(self):
        import json
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', self.polished(), '--json', '--brief', self.fx / 'polish-brief.md')
        r = json.loads(out)
        self.assertEqual(r['marks'], 'all')
        self.assertEqual(r['structure'], [])
        self.assertEqual(r['performance']['new']['stops'], 0)
        self.assertEqual(r['locked']['total'], 3)

    def test_against_git_revision(self):
        if not shutil.which('git'):
            self.skipTest('没有 git')
        repo = self.tmp / 'repo'
        repo.mkdir()
        script = repo / 'ep.md'
        shutil.copy(self.fx / 'episode.md', script)
        git = ['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.com']
        for args in (['init', '-q'], ['add', 'ep.md'], ['commit', '-q', '-m', 'v0.1']):
            subprocess.run(git + args, check=True, capture_output=True)
        script.write_text(script.read_text(encoding='utf-8').replace('Still works.', 'Still works fine.'), encoding='utf-8')
        out = self.run_script('compare_drafts.py', script, '--rev', 'HEAD')
        self.assertIn('== 比稿：HEAD:ep.md → ep.md ==', out)
        self.assertIn('- S01 改：> Still works. → > Still works fine.', out)
        out = self.run_script('compare_drafts.py', script, '--rev', 'HEAD', '--brief', self.fx / 'polish-brief.md')  # 交付时的用法
        self.assertIn('⚠ 锁定的台词少了 2 句（共 3 句）：', out)
        self.assertIn('- S01 > Still works.（现在最接近的一句：Still works fine.）', out)
        self.assertIn('git 里没有 HEAD~5:ep.md', self.run_script('compare_drafts.py', script, '--rev', 'HEAD~5'))
        self.assertIn('不在 git 仓库里', self.run_script('compare_drafts.py', self.fx / 'episode.md', '--rev', 'HEAD'))


def rows_from_pages(front, pages):
    """把排好的页变成"每行文字 + 位置"，和 pdf_lines.swift 从真 PDF 里读出来的一样：左边距 108 pt，一行 12 pt，
    西文一格 7.2 pt，中文一个字 12 pt（浏览器里实际的字宽）。"""
    import screenplay_pages as sp
    rows, sizes = [], {}
    for pno, page in enumerate(([front] if front else []) + pages, 1):
        sizes[pno] = (612, 792)
        number = pno - (1 if front else 0)
        if number > 1:
            rows.append((pno, 526, 540, 757, f'{number}.'))
        for k, line in enumerate(page):
            text = line.strip(' \x01\x02')
            if text:
                width = sp.units(text) * sp.UNIT
                if line[:1] == '\x01':    # 居中
                    x0 = 108 + (432 - width) / 2
                elif line[:1] == '\x02':  # 靠右
                    x0 = 540 - width
                else:
                    x0 = 108 + (len(line) - len(line.lstrip(' '))) * 7.2
                rows.append((pno, round(x0), round(x0 + width), 720 - 12 * k, text))
    return rows, sizes


class Pages(Base):
    """分页、扉页，和按位置读回（不需要 Chrome 和 swift：用排好的页模拟 PDF 里读出来的行）。"""

    def long_script(self):
        p = self.fx / 'long-ep.md'
        speech = ' '.join(f'This is sentence number {k} of a very long speech' for k in range(1, 30)) + '.'
        action = ' '.join(f'She crosses the room and sets glass {k} down on the bar, then goes back for another' for k in range(1, 9)) + '.'
        body = ['<!-- script-body:start -->', '## INT. BAR - NIGHT', '', 'The overhead light hums.', '']
        for k in range(14):
            body += [f'**{"DEV" if k % 2 else "MARA"}**', f'Line {k}, short and plain.', f'第 {k} 句的对照。', '', f'Mara wipes glass number {k}.', '']
        body += ['**DEV (V.O.)**', '(to the room)', speech, '', action, '', '### AT THE DOOR', '', '**END OF NIGHT**', '', 'CUT TO:', '',
                 '## EXT. STREET - LATER', '', 'Rain.', '<!-- script-body:end -->', '']
        p.write_text('# SAMPLE · Episode 2\n\n版本：Draft v0.3 (Lock Candidate) · 2026-11-10 · 依据：节拍单 v0.5\n说明：A test draft. One page reads as about one minute.\n'
                     '承接：无\n新事实（提案）：无\n页数：\n\n状态：初稿 · 写完\n\n' + '\n'.join(body), encoding='utf-8')
        return p

    def laid_out(self, path):
        import render_screenplay as rs
        title, els = rs.read_any(path)
        els, _ = rs.mark_translation(els)
        paras = rs.paragraphs(els)
        return rs, title, paras, rs.pages.paginate(rs.pages.blocks_of(paras))

    def test_header_becomes_title_page(self):
        rs, title, paras, laid = self.laid_out(self.long_script())
        self.assertEqual(title, {'Title': ['SAMPLE', 'Episode 2'], 'Credit': ['Draft v0.3 (Lock Candidate)'], 'Draft date': ['2026-11-10'],
                                 'Notes': ['A test draft. One page reads as about one minute.']})
        front = rs.pages.title_page(title)
        self.assertEqual(len(front), rs.PAGE_LINES)
        self.assertEqual([l.strip(' \x01') for l in front if l.strip()], ['SAMPLE', 'Episode 2', 'Draft v0.3 (Lock Candidate)',
                                                                   'A test draft. One page reads as about one minute.', '2026-11-10'])
        self.assertEqual(front[14], '\x01SAMPLE')  # 居中的记号；交给浏览器去对齐
        self.assertIn('<span class="c">SAMPLE</span>', rs.pages.pages_html(front, laid))
        self.assertIsNone(rs.pages.title_page({}))
        foreign = rs.pages.title_page({'Title': ['SAMPLE'], 'Credit': ['Written by'], 'Author': ['A. Writer'], 'Contact': ['writer@example.com']})
        self.assertEqual([l.strip(' \x01') for l in foreign if l.strip()], ['SAMPLE', 'Written by', 'A. Writer', 'writer@example.com'])  # 别处来的 Fountain：署名不丢

    def test_pagination_rules(self):
        rs, title, paras, laid = self.laid_out(self.long_script())
        self.assertGreater(len(laid), 2)
        for page in laid:
            self.assertLessEqual(len(page), rs.PAGE_LINES)
            self.assertTrue(page[0].strip())  # 页首不留空行
        text = [l for page in laid for l in page]
        self.assertIn(' ' * 20 + '(MORE)', text)
        self.assertIn(' ' * 20 + "DEV (V.O.) (CONT'D)", text)
        more = next(k for k, page in enumerate(laid) if page[-1].strip() == '(MORE)')
        self.assertEqual(laid[more + 1][0].strip(), "DEV (V.O.) (CONT'D)")

    def test_read_back_from_page_positions(self):
        path = self.long_script()
        rs, title, paras, laid = self.laid_out(path)
        rows, sizes = rows_from_pages(rs.pages.title_page(title), laid)
        title2, els = rs.pages.rows_to_elements(rows, sizes)
        self.assertEqual(title2, title)
        els, _ = rs.mark_translation(els)
        body = lambda text: text[text.index('<!-- script-body:start -->'):]  # noqa: E731
        self.assertEqual(body(rs.to_markdown(title2, rs.paragraphs(els))), body(rs.to_markdown(title, paras)))

    def chinese_version(self):
        p = self.fx / 'long-ep-zh.md'
        action = ('吧台后面，Mara 把杯子一只一只擦干，摆成一排。Dev 推门进来，没有坐下：他看了一眼墙上的钟，又看了一眼 Mara。'
                  'Mara 没抬头。她说过“不等”，可是第 3 只杯子擦了两遍。最上面那张单子写着：LAST CALL。Dev 把伞靠在门边，伞尖上的水滴在地上。')
        body = ['<!-- script-body:start -->', '## 内景 酒吧 - 夜', '', action, '', '**MARA**', '(不抬头)', 'You are late.', '', '**DEV**',
                'Eleven minutes.', '', 'Mara 把抹布搭在肩上。', '', '### 门口', '', '**打烊**', '', '切至：', '', '## 外景 街上 - 稍后', '',
                '雨。', '<!-- script-body:end -->', '']
        p.write_text('# 样片 · 第 2 集〈吧台〉\n\n版本：草稿 v0.3（定稿候选）· 中文版 · 2026 年 1 月 2 日 · 依据：节拍单 v0.5\n'
                     '说明：中文版：场景标题和动作为中文，台词保留英文原文。[HOUSE SONG] 是同一首歌。\n承接：无\n新事实（提案）：无\n\n'
                     '状态：精修 · 有条件锁稿\n\n' + '\n'.join(body), encoding='utf-8')
        return p

    def test_chinese_version_reads_back(self):
        rs, title, paras, laid = self.laid_out(self.chinese_version())
        self.assertEqual(title['Title'], ['样片', '第 2 集〈吧台〉'])
        self.assertEqual(title['Credit'], ['草稿 v0.3（定稿候选）· 中文版'])
        rows, sizes = rows_from_pages(rs.pages.title_page(title), laid)
        title2, els = rs.pages.rows_to_elements(rows, sizes)
        self.assertEqual(title2, title)  # 扉页上居中的中文行不能被当成角色名
        els, _ = rs.mark_translation(els)
        # 中文小标题在页面上和一行短动作没有区别（没有大写可认），读回来是动作行：已知的限制，其余一字不差
        self.assertEqual(rs.to_markdown(title2, rs.paragraphs(els)), rs.to_markdown(title, paras).replace('### 门口', '门口'))

    def test_wrap_breaks_only_where_joining_gives_the_text_back(self):
        import functools
        import screenplay_pages as sp
        self.assertEqual(sp.join_lines('盯着屏幕。', 'Mara 在看手机。'), '盯着屏幕。Mara 在看手机。')  # 全角标点旁边不留空格
        self.assertEqual(sp.join_lines('写着：', 'LAST CALL'), '写着：LAST CALL')
        self.assertEqual(sp.join_lines('侧过脸看着', 'Dev。'), '侧过脸看着 Dev。')
        self.assertEqual(sp.join_lines('吧台', '后面'), '吧台后面')
        self.assertEqual(sp.join_lines('她说过', '“不等”'), '她说过“不等”')
        self.assertEqual(sp.join_lines('by the', 'door.”'), 'by the door.”')
        texts = ['吧台后面，Mara 把杯子一只一只擦干。Dev 推门进来：他看了一眼墙上的钟，又看了一眼 Mara。她说过“不等”，可是第3只杯子擦了两遍。',
                 '单子上写着： LAST CALL。 Dev 把伞靠在门边，伞尖上的水滴在地上，一滴，两滴——然后停了…… Mara 没抬头。',
                 'She crosses the room and sets the glass down on the bar, then goes back for another one, and another.']
        for text in texts:
            for width in range(8, 40):
                lines = sp.wrap(text, width)
                self.assertEqual(functools.reduce(sp.join_lines, lines), text, (width, lines))
                self.assertFalse([x for x in lines[1:] if x[0] in sp.NO_LINE_START], (width, lines))  # 收尾标点不在行首

    def test_heading_left_at_page_bottom_is_not_joined(self):
        import screenplay_pages as sp
        first = ['INT. BAR - NIGHT', '', 'Mara wipes the last glass and holds it up to the', 'light', '', 'INT. KITCHEN - LATER']
        second = ['The stove is still on. Dev turns it off.', '', 'AT THE WINDOW']
        third = ['Rain on the glass.']
        rows, sizes = rows_from_pages(None, [first, second, third])
        _, els = sp.rows_to_elements(rows, sizes)
        self.assertEqual([(k, t) for k, t in els if k != 'blank'], [
            ('scene', 'INT. BAR - NIGHT'), ('action', 'Mara wipes the last glass and holds it up to the light'),
            ('scene', 'INT. KITCHEN - LATER'), ('action', 'The stove is still on. Dev turns it off.'),  # 别的工具会把场景标题留在页底
            ('sub', 'AT THE WINDOW'), ('action', 'Rain on the glass.')])

    def elements(self, *pages):
        """手排的几页 → 读回来的元素（不要空行）。"""
        import screenplay_pages as sp
        rows, sizes = rows_from_pages(None, [list(p) for p in pages])
        return [(k, t) for k, t in sp.rows_to_elements(rows, sizes)[1] if k != 'blank']

    def through_pages(self, path):
        """剧本 → 排好的页 → 按位置读回。返回 (原稿的正文, 读回来的正文)，场标记不算。"""
        rs, title, paras, laid = self.laid_out(path)
        rows, sizes = rows_from_pages(rs.pages.title_page(title), laid)
        title2, els = rs.pages.rows_to_elements(rows, sizes)
        els, _ = rs.mark_translation(els)
        body = lambda text: text[text.index('<!-- script-body:start -->'):]  # noqa: E731
        return body(rs.to_markdown(title, [p for p in paras if p[0] != 'mark'])), body(rs.to_markdown(title2, rs.paragraphs(els)))

    def test_translation_after_page_break_stays_its_own_line(self):
        cue, d = ' ' * 20, ' ' * 10
        for more, again in (('(MORE)', "MARA (CONT'D)"), ('(more)', 'MARA (CONT’D)')):  # 别的工具有写弯撇号、小写的
            got = self.elements(['INT. BAR - NIGHT', '', 'Rain.', '', cue + 'MARA', d + 'I told you nine. I said it twice', d + 'tonight.', cue + more],
                                [cue + again, d + '我说过九点。', '', 'She waits.'])
            self.assertEqual(got, [('scene', 'INT. BAR - NIGHT'), ('action', 'Rain.'), ('character', 'MARA'),
                                   ('dialogue', 'I told you nine. I said it twice tonight.'), ('dialogue', '我说过九点。'), ('action', 'She waits.')])

    def test_line_breaks_are_judged_by_whether_the_row_was_full(self):
        path = write_script(self.fx / 'rows.md', '## INT. BAR - NIGHT', '', 'Rain.', '',
                            '**MARA**', '你昨天说要去的那个地方是不是叫 Harbour Light Conservatory Garden 还是别的什么名字我记不清了。', '',  # 折出来的一行全是西文
                            '**DEV**', 'His is fine.', 'The rest can wait until the morning, when everyone has slept on it.', '',  # 手动分的两行
                            '**MARA**', 'You were late. I waited for an hour at the corner in the rain tonight.', '你迟到了。我今晚在街角的雨里等了一个小时。', '',
                            'The door opens—', '', 'Dev stands there with his coat on', '', '她把杯子放下（没有看他）', '', 'Mara 把抹布搭在肩上。')
        want, got = self.through_pages(path)
        self.assertEqual(got, want)

    def test_action_across_pages_joins_only_when_the_row_was_full(self):
        full = 'Mara carries the crate of empties out past the bins and sets it'  # 排满的一行，话没说完
        self.assertEqual(self.elements(['INT. BAR - NIGHT', '', 'Rain.', '', full], ['down by the back door.', '', 'Rain again.'])[2],
                         ('action', full + ' down by the back door.'))
        for last in ('The door opens—', 'Mara mouths one word: no', '她把杯子放下（没有看他）'):  # 没排满：是另一段，不接
            got = self.elements(['INT. BAR - NIGHT', '', 'Rain.', '', last], ['Dev stands in the doorway with his coat on.', '', 'Rain again.'])
            self.assertEqual(got[2:4], [('action', last), ('action', 'Dev stands in the doorway with his coat on.')])

    def test_long_paragraphs_survive_any_page_position(self):
        import screenplay_pages as sp
        action = ' '.join(f'She crosses the room and sets glass {k} down on the bar, then goes back for another one' for k in range(1, 7)) + '.'
        three = 'Rain comes down on the empty street and runs along the kerb, past the shuttered shop and the bus stop, and pools under the one lamp left.'
        moved = cut = 0
        for filler in range(16, 30):  # 挪动后面几段在页面上的位置：总有几次正好压在页底
            body = ['## INT. BAR - NIGHT', ''] + [x for k in range(filler) for x in (f'Filler action line number {k}.', '')]
            body += [action, '', '## EXT. STREET - LATER', '', three, '', '### AT THE DOOR', '', '**MARA**', 'One.', 'Two more words here.', '', 'Rain.']
            path = write_script(self.fx / f'pos{filler}.md', *body)
            rs, title, paras, laid = self.laid_out(path)
            for k, page in enumerate(laid[:-1]):
                self.assertFalse(sp.is_heading(page[-1].strip()), (filler, page[-1]))  # 场景标题、小标题不留在页底
                if page[-1].startswith('She ') or ' glass ' in page[-1]:
                    cut += 1
                    self.assertFalse(sp.SENTENCE_END.search(page[-1]), page[-1])  # 动作段跨页断在句子中间
            moved += any(page[0].strip() in ('EXT. STREET - LATER', 'AT THE DOOR') for page in laid[1:])
            want, got = self.through_pages(path)
            self.assertEqual(got, want, filler)
        self.assertGreater(moved, 0)  # 确实碰到过"标题跟着下一块去了下一页"
        self.assertGreater(cut, 0)    # 也碰到过动作段跨页

    def test_cards_read_back_as_cards(self):
        path = write_script(self.fx / 'cards.md', '## INT. BAR - NIGHT', '', 'Rain.', '', '**THREE WEEKS LATER, SOMEWHERE NEAR THE COAST**', '',  # 40 格：左端落在对白栏
                            'Mara wipes the bar.', '', '**(INTERMISSION)**', '', 'Dev counts the till.', '',
                            '**A VERY LONG TITLE CARD THAT RUNS NEARLY THE FULL WIDTH OF THE PAGE OK**', '', 'Rain again.', '', '**END**')
        want, got = self.through_pages(path)
        self.assertEqual(got, want)

    def test_title_page_variants_read_back(self):
        import render_screenplay as rs
        for version, note in (('v2', 'Lock candidate.'), ('3.0 · 2026-11-10', ''), ('v2 · Lock Candidate · 2026-11-10', 'Two placeholders left.'),
                              ('Draft v1 (Lock Candidate) · November 10, 2026', 'A note.')):
            title = rs.header_info(['# SAMPLE · Episode 3', '', f'版本：{version} · 依据：节拍单 v1'] + (['说明：' + note] if note else []))
            title.pop('_line')
            self.assertEqual(title.get('Draft date', [''])[0], version.split(' · ')[-1] if ' · ' in version else '')
            rows, sizes = rows_from_pages(rs.pages.title_page(title), [['INT. BAR - NIGHT', '', 'Rain.', '', 'More rain.']])
            self.assertEqual(rs.pages.rows_to_elements(rows, sizes)[0], title, version)

    def test_overfull_title_page_is_cut_and_reported(self):
        import screenplay_pages as sp
        lost = []
        page = sp.title_page({'Title': [f'PART {k}' for k in range(25)], 'Notes': ['A very long note. ' * 200]}, dropped=lost)
        self.assertEqual(len(page), sp.PAGE_LINES)
        self.assertTrue(lost and lost[0] > 0)
        path = write_script(self.fx / 'many.md', '## INT. BAR - NIGHT', '', 'Rain.', head=('# ' + ' · '.join(f'PART {k}' for k in range(25)), '', '版本：v1', ''))
        self.assertIn('扉页排不下', self.run_script('render_screenplay.py', path, '--html', self.tmp / 'many.html'))

    def test_fountain_title_page_keeps_author_and_contact(self):
        src, md = self.tmp / 'in.fountain', self.tmp / 'in.md'
        src.write_text('Title: SAMPLE\nCredit: Written by\nAuthor: A. Writer\nSource: Based on nothing\nDraft date: 2026-01-02\n'
                       'Contact:\n    writer@example.com\n\nINT. BAR - NIGHT\n\nRain.\n', encoding='utf-8')
        self.run_script('render_screenplay.py', src, '--md', md)
        self.assertIn('# SAMPLE\n\n版本：Written by A. Writer Based on nothing · 2026-01-02\n说明：writer@example.com\n', md.read_text(encoding='utf-8'))

    def test_empty_body_keeps_both_markers(self):
        import render_screenplay as rs
        self.assertTrue(rs.to_markdown({'Title': ['SAMPLE']}, []).endswith('<!-- script-body:start -->\n<!-- script-body:end -->\n'))

    def test_no_browser_writes_html_instead(self):
        import screenplay_pages as sp
        keep, sp.find_browser = sp.find_browser, lambda: None
        try:
            ok, why = sp.write_pdf('<html>x</html>', self.tmp / 'out.pdf')
        finally:
            sp.find_browser = keep
        self.assertFalse(ok)
        self.assertIn('没有找到', why)
        self.assertEqual((self.tmp / 'out.html').read_text(encoding='utf-8'), '<html>x</html>')
        self.assertIn('要写到的目录不存在', self.run_script('render_screenplay.py', self.fx / 'standard.md', '--pdf', self.tmp / 'nope' / 'x.pdf'))

    def test_read_back_keeps_the_small_fixture(self):
        rs, title, paras, laid = self.laid_out(self.fx / 'standard.md')
        rows, sizes = rows_from_pages(rs.pages.title_page(title), laid)
        _, els = rs.pages.rows_to_elements(rows, sizes)
        els, _ = rs.mark_translation(els)
        kinds = [k for k, _ in rs.paragraphs(els)]
        self.assertEqual(kinds, [k for k, _ in paras])  # 场景标题、动作、台词、小标题、片名卡、转场各归各位
        self.assertEqual(rs.to_markdown({}, rs.paragraphs(els)), rs.to_markdown({}, paras))

    def test_markdown_header_round_trip(self):
        rs, title, paras, laid = self.laid_out(self.long_script())
        md = rs.to_markdown(title, paras)
        self.assertIn('# SAMPLE · Episode 2\n\n版本：Draft v0.3 (Lock Candidate) · 2026-11-10\n说明：A test draft.', md)
        self.assertNotIn('待补', md)
        self.assertIn('承接：待补\n新事实（提案）：待补\n\n状态：待补', rs.to_markdown(title, paras, True))
        ftn = rs.to_fountain(title, paras)
        self.assertTrue(ftn.startswith('Title:\n    SAMPLE\n    Episode 2\nCredit: Draft v0.3 (Lock Candidate)\nDraft date: 2026-11-10\nNotes: A test draft.'))

    def test_page_count_goes_back_into_header(self):
        import render_screenplay as rs
        path = self.long_script()
        self.assertTrue(rs.fill_page_count(path, 3, {'Credit': ['Draft v0.3']}))
        self.assertIn('\n页数：3（Draft v0.3，不含扉页）\n', path.read_text(encoding='utf-8'))
        self.assertFalse(rs.fill_page_count(self.fx / 'episode.md', 3, {}))  # 头部没有"页数："一行就不动文件

    @unittest.skipUnless(shutil.which('swift') and __import__('screenplay_pages').find_browser(), '要 swift 和 Chrome')
    def test_real_pdf_out_and_back(self):
        path = self.long_script()
        pdf, back = self.tmp / 'SAMPLE_script_v0.3.pdf', self.tmp / 'back.md'
        out = self.run_script('render_screenplay.py', path, '--pdf', pdf)
        self.assertIn('排成', out)
        self.assertIn('已回填', out)
        self.assertTrue(pdf.read_bytes().startswith(b'%PDF'))
        self.assertRegex(path.read_text(encoding='utf-8'), r'\n页数：\d+（Draft v0\.3 \(Lock Candidate\)，不含扉页，含对照翻译）\n')
        self.run_script('render_screenplay.py', pdf, '--md', back)
        text = back.read_text(encoding='utf-8')
        self.assertIn('# SAMPLE · Episode 2\n\n版本：Draft v0.3 (Lock Candidate) · 2026-11-10\n说明：A test draft. One page reads as about one minute.\n承接：待补', text)
        out = self.run_script('compare_drafts.py', path, pdf)  # 剧本和它导出的 PDF 直接比
        self.assertIn('台词：15 → 15 句 · 改 0 · 删 0 · 加 0', out)
        self.assertIn('两版的台词和动作一字未改。', out)
        out = self.run_script('check_constraints.py', pdf, '--constraints', self.cons)
        self.assertIn('场「INT. BAR - NIGHT」', out)
        self.assertIn('来源不是 Markdown', out)  # 行号是转换后的，头部不查
        self.assertIn('头部必填项：来源不是 Markdown，没有头部可查', out)
        self.run_script('render_screenplay.py', path, '--no-translation', '--pdf', self.tmp / 'clean.pdf')
        self.assertRegex(path.read_text(encoding='utf-8'), r'\n页数：\d+（Draft v0\.3 \(Lock Candidate\)，不含扉页，对照翻译已去掉）\n')

    @unittest.skipUnless(shutil.which('swift') and __import__('screenplay_pages').find_browser(), '要 swift 和 Chrome')
    def test_real_pdf_of_a_chinese_version(self):
        import render_screenplay as rs
        path, pdf = self.chinese_version(), self.tmp / 'zh.pdf'
        self.run_script('render_screenplay.py', path, '--pdf', pdf)
        title, els = rs.read_any(pdf)
        self.assertEqual(title['Title'], ['样片', '第 2 集〈吧台〉'])
        self.assertEqual(title['Credit'], ['草稿 v0.3（定稿候选）· 中文版'])
        els, _ = rs.mark_translation(els)
        want = rs.to_markdown({}, rs.paragraphs(rs.mark_translation(rs.read_any(path)[1])[0])).replace('### 门口', '门口')
        self.assertEqual(rs.to_markdown({}, rs.paragraphs(els)), want)  # 中文小标题读成动作行，其余一字不差

    def test_unreadable_pdf_is_named_and_the_rest_still_run(self):
        bad = self.fx / 'not-a.pdf'
        bad.write_text('not a pdf', encoding='utf-8')
        if shutil.which('swift'):
            out = self.run_script('check_dialogue.py', self.fx / 'episode.md', bad, self.fx / 'standard.md')
            self.assertIn(f'== {bad} ==\n  ⚠ 打不开这份 PDF', out)
            self.assertEqual(out.count('台词 '), self.run_script('check_dialogue.py', self.fx / 'episode.md', self.fx / 'standard.md').count('台词 '))
            self.assertIn('⚠ 打不开这份 PDF', self.run_script('compare_drafts.py', bad, '--brief', self.fx / 'polish-brief.md'))
        for script in ('check_dialogue.py', 'check_constraints.py', 'render_screenplay.py'):
            self.assertIn('找不到文件', self.run_script(script, self.tmp / 'gone.pdf'))


class Splits(Base):
    """一句话被动作拆成两段、词没变：算"拆"，不算改动。"""

    def test_split_and_merge_are_not_changes(self):
        text = (self.fx / 'episode.md').read_text(encoding='utf-8')
        old = self.fx / 'whole.md'
        old.write_text(text.replace('**DEV**\nYou kept the old sign.\n你还留着旧招牌。', '**DEV**\nYou kept the old sign. It still lights up.\n你还留着旧招牌。'), encoding='utf-8')
        new = self.fx / 'split.md'
        new.write_text(text.replace('**DEV**\nYou kept the old sign.\n你还留着旧招牌。', '**DEV**\nYou kept the old sign.\n\nMara looks up.\n\n**DEV**\nIt still lights up.'), encoding='utf-8')
        out = self.run_script('compare_drafts.py', old, new)
        self.assertIn('台词：5 → 6 句 · 改 0 · 删 0 · 加 0 · 拆 1', out)
        self.assertIn('- S01 拆：> You kept the old sign. It still lights up. → > You kept the old sign. ｜ > It still lights up.（词没变）', out)
        out = self.run_script('compare_drafts.py', new, old)
        self.assertIn('台词：6 → 5 句 · 改 0 · 删 0 · 加 0 · 并 1', out)
        self.assertIn('- S01 并：> You kept the old sign. ｜ > It still lights up. → > You kept the old sign. It still lights up.（词没变）', out)

    def test_split_needs_adjacent_lines_and_the_same_words(self):
        old = write_script(self.fx / 'o.md', '<!-- S01 · THE BAR -->', '## INT. BAR - NIGHT', '', '**DEV**', 'Yeah. Okay.', '', '**MARA**', 'Fine.', '',
                           '**DEV**', 'One.', '', '**MARA**', 'No. I told you already that I am not going out to the pier with you.')
        new = write_script(self.fx / 'n.md', '<!-- S01 · THE BAR -->', '## INT. BAR - NIGHT', '', '**DEV**', 'Yeah.', '', '**MARA**', 'Fine.', '',
                           '**DEV**', 'One.', '', '**MARA**', 'No.', '', 'She sets the glass down.', '', '**MARA**',
                           'I told you already that I am not going out to the pier with you.', '', '**DEV**', 'Okay.')
        out = self.run_script('compare_drafts.py', old, new)
        self.assertIn('台词：4 → 6 句 · 改 1 · 删 0 · 加 1 · 拆 1', out)
        self.assertIn('- S01 拆：> No. I told you already that I am not going out to the pier with you. → > No. ｜ >', out)  # 前半句很短也认得出
        self.assertIn('- S01 改：> Yeah. Okay. → > Yeah.', out)  # 隔了几段话才出现的 Okay. 是新加的，不是拆出来的
        self.assertIn('- S01 加：> Okay.', out)
        brief = self.fx / 'b.md'
        brief.write_text('### 锁定的台词\n\n- S01 > No. I told you already that I am not going out to the pier with you.\n', encoding='utf-8')
        out = self.run_script('compare_drafts.py', old, new, '--brief', brief)
        self.assertIn('锁定的台词有 1 句被拆开了', out)
        self.assertNotIn('锁定的台词少了', out)

    def test_split_in_chinese(self):
        old = write_script(self.fx / 'zo.md', '<!-- S01 · 酒吧 -->', '## 内 · 酒吧 · 夜', '', '**小林**', '你还留着那块旧招牌。它还亮着呢。')
        new = write_script(self.fx / 'zn.md', '<!-- S01 · 酒吧 -->', '## 内 · 酒吧 · 夜', '', '**小林**', '你还留着那块旧招牌。', '', '她抬头。', '', '**小林**', '它还亮着呢。')
        self.assertIn('台词：1 → 2 句 · 改 0 · 删 0 · 加 0 · 拆 1', self.run_script('compare_drafts.py', old, new))


class Inputs(Base):
    """改动清单文件、占位符、别的格式直接进检查和比稿。"""

    def test_change_list_file(self):
        new = self.fx / 'v2.md'
        new.write_text((self.fx / 'episode.md').read_text(encoding='utf-8').replace('Still works.', 'Still works fine.'), encoding='utf-8')
        out_file = self.tmp / 'SAMPLE_script_v0.3_changes.md'
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new, '--out', out_file)
        self.assertIn('改动清单已写到', out)
        text = out_file.read_text(encoding='utf-8')
        self.assertTrue(text.startswith('# 改动清单 · episode.md → v2.md\n'))
        self.assertIn('- 结构：场、场景标题、每场的说话人都没变。', text)
        self.assertIn('- S01 改：> Still works. → > Still works fine.', text)
        also = self.tmp / 'with-json.md'
        self.assertTrue(self.run_script('compare_drafts.py', self.fx / 'episode.md', new, '--out', also, '--json').lstrip().startswith('{'))
        self.assertTrue(also.is_file())  # --json 时照样写
        self.run_script('compare_drafts.py', new, '--brief', self.fx / 'polish-brief.md', '--out', self.tmp / 'none.md')
        self.assertFalse((self.tmp / 'none.md').exists())  # 只给一份稿：没有两版可比，不写

    def test_two_language_versions_align_by_order(self):
        en = write_script(self.fx / 'en.md', '## INT. BAR - NIGHT', '', 'Rain.', '', '**MARA**', 'You are late.', '', '## EXT. STREET - LATER', '', '**DEV**', 'Night.')
        zh = write_script(self.fx / 'zh.md', '## 内景 酒吧 - 夜', '', '雨。', '', '**MARA**', 'You are late.', '', '## 外景 街上 - 稍后', '', '**DEV**', 'Night.')
        out = self.run_script('compare_drafts.py', en, zh, '--dialogue-only')
        self.assertIn('按场景的先后对齐（2 → 2 个）', out)
        self.assertIn('两版的台词一字未改。', out)
        one = write_script(self.fx / 'one.md', '## 内景 酒吧 - 夜', '', '**MARA**', 'You are late.', '', '**DEV**', 'Night.')
        out = self.run_script('compare_drafts.py', en, one, '--dialogue-only')
        self.assertIn('场景标题的个数不同：2 → 1，没法一场对一场，整份按先后比', out)  # 照实说，不写"结构没变"
        self.assertNotIn('都没变', out)

    def test_txt_is_read_as_before(self):
        txt = self.fx / 'episode.txt'
        txt.write_text((self.fx / 'episode.md').read_text(encoding='utf-8'), encoding='utf-8')
        self.assertEqual(self.texts(txt), self.texts(self.fx / 'episode.md'))  # 存成 .txt 的 Markdown 稿照 Markdown 读

    def test_chinese_action_with_a_colon_is_not_dialogue(self):
        path = write_script(self.fx / 'note.md', '## 内景 酒吧 - 夜', '', '纸条上写着：“BACK AT TEN.”', '', '**MARA**', 'You are late.', '', '墙上的字：“今日休息”。')
        self.assertEqual([(x['speaker'], x['text']) for sc in scenes_of(path) for x in sc['lines']], [('MARA', 'You are late.')])

    def test_placeholders_listed_without_constraints_file(self):
        lone = Path(tempfile.mkdtemp()) / 'lone.md'  # 不在任何项目里：往上找不到约束文件
        lone.write_text("<!-- script-body:start -->\n## INT. BAR - NIGHT\n\nThe speaker plays [HOUSE SONG].\n<!-- script-body:end -->\n", encoding='utf-8')
        out = self.run_script('check_constraints.py', lone)
        shutil.rmtree(lone.parent)
        self.assertIn('没有约束文件', out)
        self.assertIn('占位符（锁稿前清零）：行4 [HOUSE SONG]', out)

    def test_placeholder_with_apostrophe(self):
        p = self.fx / 'song.md'
        p.write_text((self.fx / 'episode.md').read_text(encoding='utf-8').replace('One more.', "He hums [MARA'S SONG]."), encoding='utf-8')
        c = self.fx / 'c.md'
        c.write_text('## 人物\n- Dev, Mara\n', encoding='utf-8')
        self.assertIn("[MARA'S SONG]", self.run_script('check_constraints.py', p, '--constraints', c))

    def test_fountain_goes_straight_into_the_checks(self):
        out = self.run_script('check_dialogue.py', self.fx / 'sample.fountain')
        self.assertIn('-- INT. KITCHEN - NIGHT', out)
        self.assertIn('MARA（画外）', out)


if __name__ == '__main__':
    unittest.main()
