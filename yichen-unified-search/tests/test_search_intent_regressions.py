"""Offline behavior regressions: no backend, login state or credentials accessed."""
import contextlib
import io
import json
import sys
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from test_route_search import ROUTER, request
import aihot_search as AIHOT
from public_urls import is_public_http_url


class IntentRegressionTests(unittest.TestCase):
    def test_full_numeric_and_chinese_time_windows(self):
        for wording, days in [('过去17天',17),('过去30天',30),('最近三十天',30),
                              ('最近一个月',30),('past 30 days',30),('最近7天',7)]:
            with self.subTest(wording=wording):
                query = wording + ' AI latest news'
                self.assertEqual(ROUTER.infer_aihot_days(query,None),days)
                result=ROUTER.plan(request(queries=(query,)))
                self.assertEqual(result['route']['backend'],'anysearch' if days>7 else 'aihot')
                if days>7:
                    explicit=ROUTER.plan(request(queries=(query,),platform='aihot'))
                    self.assertEqual(explicit['status'],'invalid_request')
                    self.assertEqual(explicit['steps'],[])

    def test_explicit_days_override_inferred_days(self):
        result=ROUTER.plan(request(queries=('过去30天 AI 新闻',),days=3))
        argv=result['steps'][0]['argv']
        self.assertEqual(argv[argv.index('--days')+1],'3')

    def test_no_native_platform_silently_discards_queries(self):
        for platform in ['youtube','github','wechat','bilibili','xiaohongshu','douyin','toutiao','xiaoyuzhou']:
            with self.subTest(platform=platform):
                result=ROUTER.plan(request(platform=platform,queries=('first','second')))
                self.assertEqual(result['status'],'invalid_request')
                self.assertEqual(result['steps'],[])
                batch=ROUTER.plan(request(platform=platform,queries=('first','second'),mode='batch'))
                payload=json.loads(batch['steps'][0]['argv'][-1])
                self.assertEqual(len(payload),2)
                self.assertTrue(all(item['query'].startswith('site:') for item in payload))

    def test_mixed_platforms_have_no_ready_calls_and_include_split_evidence(self):
        for queries in [('知乎上的 AI 讨论','微博上的 AI 讨论'),('在知乎和微博搜索 AI',)]:
            result=ROUTER.plan(request(queries=queries,mode='batch'))
            self.assertEqual(result['status'],'invalid_request')
            self.assertEqual(result['steps'],[])
            self.assertEqual(len(result['query_routes']),len(queries))

    def test_company_subject_is_not_channel_and_issue_is_not_github(self):
        for query in ['微博公司的最新财报','微博财报','Weibo stock earnings','how to resolve a housing issue']:
            self.assertEqual(ROUTER.plan(request(queries=(query,)))['route']['backend'],'anysearch')
        for query in ['微博上的最新讨论','latest Weibo posts about iPhone','在微博搜索财报']:
            self.assertEqual(ROUTER.plan(request(queries=(query,)))['route']['backend'],'weibo-readonly-auto')

    def test_explicit_platform_remains_authoritative(self):
        result=ROUTER.plan(request(platform='weibo',queries=('知乎与微博对比',)))
        self.assertEqual(result['route']['platform'],'weibo')

    def test_all_topics_preserved_in_adapter_arguments(self):
        result=ROUTER.plan(request(queries=('今天 Claude 和 Gemini 有什么更新',)))
        argv=result['steps'][0]['argv']
        topics=[argv[i+1] for i,v in enumerate(argv) if v=='--keyword']
        self.assertEqual(topics,['Claude','Gemini'])
        self.assertEqual(ROUTER.infer_aihot_keywords('Claude claude Gemini'),['Claude','Gemini'])
        self.assertEqual(ROUTER.infer_aihot_keywords('ChatGPT 和 GPT-6发布 metadata agentic'),['ChatGPT','GPT-6'])

    def test_more_than_five_topics_rejected_without_truncation(self):
        query='今天 OpenAI Anthropic Claude Gemini Mistral Grok 更新'
        result=ROUTER.plan(request(queries=(query,)))
        self.assertEqual(result['status'],'invalid_request')
        self.assertEqual(result['steps'],[])

    def test_empty_input_and_multiple_channels_fail(self):
        for args in [dict(queries=(' ',)),dict(platform='youtube',mode='channel',queries=('@one','@two'))]:
            self.assertEqual(ROUTER.plan(request(**args))['status'],'invalid_request')

    def test_cli_returns_nonzero_for_invalid_plan(self):
        with mock.patch.object(sys,'argv',['route_search.py','--query','a','--query','b','--platform','youtube']), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ROUTER.main(),2)


class AihotQualityTests(unittest.TestCase):
    def normalize(self,rows,limit=10):
        return AIHOT.normalize_items({'items':rows},query='AI news',limit=limit,days=1,feed='selected',retrieved_at='2026-09-05T00:00:00Z')

    def test_true_zero_and_malformed_zero_are_distinct(self):
        empty=self.normalize([])
        broken=self.normalize([{'title':'missing URL'},None,{'url':'https://example.com','title':42}])
        self.assertEqual(empty['routes'][0]['status'],'completed')
        self.assertEqual(empty['errors'],[])
        self.assertEqual(broken['routes'][0]['status'],'failed')
        self.assertEqual(broken['coverage'][0]['rejected_count'],3)
        self.assertTrue(broken['errors'])

    def test_rejected_rows_do_not_use_valid_result_limit(self):
        result=self.normalize([None,{'title':'one','url':'https://example.com/a'},{'title':'one again','url':'https://example.com/a'},{'title':'two','url':'https://example.com/b'}],2)
        self.assertEqual(len(result['candidates']),2)
        self.assertEqual(result['routes'][0]['status'],'partial')
        self.assertEqual(result['coverage'][0]['duplicate_count'],1)
        self.assertFalse(result['coverage'][0]['truncated'])

    def test_nonpublic_and_invalid_urls_rejected(self):
        for url in ['http://127.0.0.1/private','http://2130706433/','http://0x7f000001/',
                    'http://localhost/','http://printer/','https://a.internal/',
                    'http://[::1]/','https://user:password@example.com/',
                    'javascript:alert(1)','file:///tmp/file','http://example.com\\@localhost/',[],42]:
            with self.subTest(url=url):
                self.assertFalse(is_public_http_url(url))
                result=self.normalize([{'title':'bad','url':url}])
                self.assertEqual(result['routes'][0]['status'],'failed')
                self.assertEqual(result['candidates'],[])
        self.assertTrue(is_public_http_url('https://example.com/item'))

    def test_unknown_language_stays_null(self):
        result=self.normalize([{'title':'English title','url':'https://example.com/item'}])
        self.assertIsNone(result['candidates'][0]['language'])

    def test_daily_uses_same_validation_and_no_false_truncation(self):
        result=AIHOT.normalize_daily({'sections':[], 'flashes':[{'title':'one','url':'https://example.com/a'},{'title':'again','url':'https://example.com/a'},None]},query='daily',limit=10,retrieved_at='now')
        self.assertEqual(result['routes'][0]['status'],'partial')
        self.assertFalse(result['coverage'][0]['truncated'])
        with self.assertRaises(ValueError):
            AIHOT.normalize_daily({'unexpected':[]},query='daily',limit=10,retrieved_at='now')

    def test_multi_topic_fetch_merge_and_coverage(self):
        calls=[]
        def fetch(url,timeout):
            topic=parse_qs(urlsplit(url).query)['q'][0]
            calls.append(topic)
            return {'items':[{'title':topic,'url':f'https://example.com/{topic}'},{'title':'shared','url':'https://example.com/shared'}]}
        args=Namespace(keyword=['Claude','Gemini'],feed='selected',days=1,limit=3,category=None,timeout=20,query='today Claude Gemini')
        result=AIHOT.run_items(args,datetime(2026,9,5,tzinfo=timezone.utc),fetch)
        self.assertEqual(calls,['Claude','Gemini'])
        self.assertEqual(len(result['candidates']),3)
        shared=next(c for c in result['candidates'] if c['url'].endswith('/shared'))
        self.assertEqual(shared['provenance']['matched_topics'],['Claude','Gemini'])
        self.assertEqual([c['topic'] for c in result['coverage'][:-1]],['Claude','Gemini'])
        self.assertEqual([c['selected_count'] for c in result['coverage'][:-1]],[2,2])

    def test_one_topic_failure_does_not_erase_other_topic(self):
        def fetch(url,timeout):
            if 'Claude' in url: raise URLError('synthetic')
            return {'items':[{'title':'Gemini','url':'https://example.com/gemini'}]}
        args=Namespace(keyword=['Claude','Gemini'],feed='selected',days=1,limit=10,category=None,timeout=20,query='news')
        result=AIHOT.run_items(args,datetime.now(timezone.utc),fetch)
        self.assertEqual(len(result['candidates']),1)
        self.assertTrue(result['errors'])
        self.assertEqual([r['status'] for r in result['routes']],['failed','completed'])

    def test_main_invalid_candidate_returns_nonzero(self):
        with mock.patch.object(sys,'argv',['aihot_search.py','--query','news']), mock.patch.object(AIHOT,'fetch_json',return_value={'items':[{}]}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(AIHOT.main(),2)


if __name__=='__main__':
    unittest.main()
