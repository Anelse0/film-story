"""0.6.0 检查脚本回归：正文边界、台词块、语言、画内 / 画外、制作参数、表面线索的命名、约束检查只查正文。
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


class Patterns(Base):
    def _tags(self, name):
        scenes, meta = cd.parse(self.fx / name)
        r = cd.analyse(scenes[0], meta['lang'])
        return {m['text']: m['tags'] for m in r['marked_lines']}

    def test_en_parallel_and_pickup(self):
        tags = self._tags('patterns.md')
        self.assertIn(cd.TAG['pickup'], tags["Who's 'we'?"])
        self.assertIn(cd.TAG['parallel'], tags['He wants the credit, she wants the control.'])
        self.assertIn(cd.TAG['parallel'], tags['Not the money. Not the fame. Not the work.'])
        self.assertNotIn("Okay. I'll bring the van.", tags)
        self.assertNotIn('We leave at nine.', tags)
        self.assertNotIn("And then I did the closet, and then it's five, and I've got a call at seven.", tags)
        self.assertIn(cd.TAG['parallel'], tags["You don't call. You don't text. You don't show."])

    def test_zh_parallel_and_pickup(self):
        tags = self._tags('patterns-zh.md')
        self.assertIn(cd.TAG['pickup'], tags['大家是谁？'])
        self.assertIn(cd.TAG['parallel'], tags['他要的是面子，我要的是日子。'])
        self.assertNotIn('我回来了，你吃饭了？', tags)
        self.assertNotIn('饭在锅里。', tags)
        self.assertNotIn('我去了，我等了，我走了。', tags)
        self.assertIn(cd.TAG['parallel'], tags['不是钱，不是名，不是脸。'])

    def test_cue_wording_is_surface(self):
        out = self.run_script('check_dialogue.py', self.fx / 'patterns.md')
        self.assertIn('等长对仗 / 排比', out)
        self.assertIn('接住上一句的词反问', out)
        self.assertIn('需人工判断', out)


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


if __name__ == '__main__':
    unittest.main()
