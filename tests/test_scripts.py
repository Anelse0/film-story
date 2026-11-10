"""检查脚本回归：正文边界、台词块、语言、画内 / 画外、制作参数、表面线索的命名、约束检查只查正文（0.6.0）；
标准剧本格式的 Markdown、动作描写线索、Fountain / Markdown / 标准版面互转（0.7.1）。
场标记与按场取出（0.7.2）；比稿：结构有没有变、改了哪些句子（0.7.3）。
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
        return [x['text'] for sc in cd.extract(path, lang) for x in sc['lines']]


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
        lines = cd.extract(self.fx / 'loose.md')[0]['lines']
        self.assertEqual([(x['speaker'], x['text']) for x in lines], [
            ('EZRA', 'That was really good.'), ('EVELYN', 'Hey. You came.'), ('June', 'Clothes— the chair.')])
        self.assertEqual(lines[0]['paren'], '（真心实意地，语气放松）')

    def test_inline_labels_and_scene_heading(self):
        scenes = cd.extract(self.fx / 'inline.md')
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
        lines = cd.extract(self.fx / 'phone.md')[0]['lines']
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
        r = cd.analyse(cd.extract(self.fx / 'questions.md')[0])
        self.assertTrue(any(f.startswith('THEO 的 4 句里 4 句是问句') for f in r['flags']), r['flags'])

    def test_display_names(self):
        sc = cd.extract(self.fx / 'questions.md')[0]
        self.assertIn('DJ', cd.analyse(sc)['speakers'])
        self.assertIn('Theo', cd.analyse(sc, names={'theo': 'Theo'})['speakers'])


class Constraints(Base):
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
            ('DEV', "You're really good at this.", False), ('MARA', 'I know.', False), ('MARA', 'Told you.', True)])
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

    def test_old_export_with_blank_after_cue_still_read(self):
        # 全文的角色名后面都空一行的旧导出稿：照旧算角色名
        self.assertEqual([x['speaker'] for x in cd.extract(self.fx / 'loose.md')[0]['lines']], ['EZRA', 'EVELYN', 'June'])


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
                      "**DEV**\nYou're really good at this.\n", '### AT THE WINDOW\n', '**MARA (V.O.)**\n(laughing)\nTold you.\n',
                      '**THE NEXT MORNING**\n', '## KITCHEN, LATER\n', '**McAVOY**\nMorning.\n', 'FADE OUT.\n<!-- script-body:end -->'):
            self.assertIn(piece, md)
        lines = cd.extract(out)[0]['lines']  # 转出来的 Markdown，检查脚本读得出同样的台词
        self.assertEqual([(x['speaker'], x['offscreen']) for x in lines], [('DEV', False), ('MARA', True), ('McAVOY', False)])

    def test_round_trip_keeps_every_line(self):
        md, back = self.tmp / 'out.md', self.tmp / 'back.fountain'
        self.run_script('render_screenplay.py', self.fx / 'sample.fountain', '--md', md)
        self.run_script('render_screenplay.py', md, '--fountain', back)
        body = lambda p: p.read_text(encoding='utf-8').split('\n\n', 1)[1].strip()  # 标题页之后
        self.assertEqual(body(back), (self.fx / 'sample.fountain').read_text(encoding='utf-8').split('\n\n', 1)[1].strip())
        self.assertTrue(back.read_text(encoding='utf-8').startswith('Title: SAMPLE · Episode 1\n'))

    def test_text_layout_columns(self):
        out = self.run_script('render_screenplay.py', self.fx / 'standard.md').splitlines()
        self.assertIn('INT. KITCHEN - NIGHT', out)
        self.assertIn(' ' * 20 + 'DEV', out)
        self.assertIn(' ' * 20 + 'MARA (V.O.)', out)
        self.assertIn(' ' * 15 + '(laughing)', out)
        self.assertIn(' ' * 10 + "You're really good at this.", out)
        self.assertIn(' ' * 10 + '你真的很会这个。', out)
        self.assertIn('AT THE WINDOW', out)
        self.assertIn(' ' * 53 + 'CUT TO:', out)  # 转场靠右，收在第 60 格
        self.assertIn(' ' * 22 + 'THE NEXT MORNING', out)  # 片名卡居中
        self.assertTrue(all(cd.display_width(l) <= 60 for l in out[:-1]), [l for l in out if cd.display_width(l) > 60])
        self.assertIn('对照翻译 2 行在内', out[-1])

    def test_wrap_counts_cjk_as_two_columns(self):
        import render_screenplay as rs
        self.assertEqual(rs.wrap('他把手机举高一点，咳了一声。' * 3, 35),
                         ['他把手机举高一点，咳了一声。他把手', '机举高一点，咳了一声。他把手机举高', '一点，咳了一声。'])
        self.assertEqual(rs.wrap('You changed the sign three weeks ago, I think.', 35), ['You changed the sign three weeks', 'ago, I think.'])

    def test_no_translation(self):
        out = self.run_script('render_screenplay.py', self.fx / 'standard.md', '--no-translation')
        self.assertNotIn('你真的很会这个。', out)
        self.assertIn('对照翻译 2 行已去掉', out)

    def test_html_page_spec(self):
        page = self.tmp / 'out.html'
        self.run_script('render_screenplay.py', self.fx / 'standard.md', '--html', page, '--title', 'SAMPLE')
        h = page.read_text(encoding='utf-8')
        for piece in ('<title>SAMPLE</title>', '12pt/12pt "Courier Prime", "Courier New", Courier',
                      '@page { size: 8.5in 11in; margin: 1in 1in 1in 1.5in; }', '<p class="character">MARA (V.O.)</p>',
                      '<p class="paren">(laughing)</p>', '<p class="alt">我知道。</p>', '<p class="scene">INT. KITCHEN - NIGHT</p>',
                      '<p class="transition">CUT TO:</p>', '<p class="center">THE NEXT MORNING</p>'):
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
        out = self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 's1')
        self.assertIn('没有找到 s1。文件里的场：S01 · THE BAR、S02 · THE MORNING AFTER、S10 · LATER', out)
        out = self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 'S01')
        self.assertIn('EXT. STREET - CONTINUOUS', out)  # 一场可以有几个场景标题
        self.assertNotIn('Morning.', out)
        self.assertNotIn('One more.', out)
        self.assertIn('场 1 个 · 场景标题 2 个 · 台词 3 段', out)
        self.assertIn('对照翻译 1 行在内', out)
        md = self.tmp / 's02.md'
        self.run_script('render_screenplay.py', self.fx / 'episode.md', '--scene', 'S02,S10', '--md', md)
        self.assertEqual([x['text'] for sc in cd.extract(md) for x in sc['lines']], ['Morning.', 'One more.'])

    def test_format_notes(self):
        out = self.run_script('render_screenplay.py', self.fx / 'body-annotations.md')
        self.assertIn('格式提示：场景标题不是「INT. / EXT. 地点 - 时间」的有 1 处', out)


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
        return self.variant('polish.md', ("You're really good at this.", "You're good at this."), ('**DEV**\nNight.\n\n', ''),
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
                      "- S01 改：> You're really good at this. → > You're good at this.", '- S01 删：> Night.（DEV）',
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
        new = self.variant('v3.md', ('I know.', 'I know that.'),
                           ('**DEV**\nOne more.', '**NIA**\nOne more.\n\n## EXT. ALLEY - NIGHT\n\nRain.'))
        import compare_drafts as cmp
        r = cmp.compare(self.fx / 'episode.md', new, brief=self.fx / 'polish-brief.md')
        self.assertEqual(r['structure'], [])  # S10 登记了局部重写，结构变化不算越界
        self.assertEqual(len(r['declared']), 2)
        self.assertEqual(r['locked']['total'], 3)
        self.assertEqual([(x['scene'], x['text'], x['closest']) for x in r['locked']['missing']],
                         [('S01', 'I know.', 'I know that.'), ('S10', 'One more round.', 'One more.')])
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', new, '--brief', self.fx / 'polish-brief.md')
        for piece in ('结构：没登记的场，场、场景标题、每场的说话人都没变。', '登记了局部重写的场有结构变化（简报里写了，不算越界）：',
                      '⚠ 锁定的台词少了 2 句（共 3 句）：', '- S01 > I know.（现在最接近的一句：I know that.）'):
            self.assertIn(piece, out)

    def test_brief_alone_checks_locked_lines(self):
        out = self.run_script('compare_drafts.py', self.fx / 'episode.md', '--brief', self.fx / 'polish-brief.md')
        self.assertIn('== 核对锁定的台词：episode.md ==', out)
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
        script.write_text(script.read_text(encoding='utf-8').replace('I know.', 'I know that.'), encoding='utf-8')
        out = self.run_script('compare_drafts.py', script, '--rev', 'HEAD')
        self.assertIn('== 比稿：HEAD:ep.md → ep.md ==', out)
        self.assertIn('- S01 改：> I know. → > I know that.', out)
        self.assertIn('git 里没有 HEAD~5:ep.md', self.run_script('compare_drafts.py', script, '--rev', 'HEAD~5'))
        self.assertIn('不在 git 仓库里', self.run_script('compare_drafts.py', self.fx / 'episode.md', '--rev', 'HEAD'))


if __name__ == '__main__':
    unittest.main()
