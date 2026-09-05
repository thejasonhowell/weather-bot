"""Isolate main.py functions: no credentials, network, signals or live bot startup."""
import ast
from pathlib import Path
import unittest
import tempfile
import types
import math
import time
import json
import os
import hashlib
import logging
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

SOURCE = Path(__file__).resolve().parents[1] / 'main.py'
TREE = ast.parse(SOURCE.read_text())

def namespace():
    ns = dict(datetime=datetime, time=time, math=math, logging=logging,
              os=os, json=json, hashlib=hashlib, PEORIA_TIMEZONE=ZoneInfo('America/Chicago'),
              MAX_OBSERVATION_AGE_SECONDS=900, HTTP_TIMEOUT=(5,20))
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef):
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), ns)
    return ns

class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace()
        self.now = time.time()
        self.obs = dict(timestamp=self.now, air_temperature=20, wind_avg=1,
                        wind_gust=2, wind_direction=180, precip_accum_last_1hr=0, precip_accum_local_day=0)

    def test_invalid_and_stale_observations(self):
        validate = self.ns['_validate_observation']
        self.assertIsNotNone(validate(self.obs))
        for field in ('timestamp', 'air_temperature', 'wind_avg', 'wind_gust', 'wind_direction'):
            for value in (None, 'invalid', float('nan'), float('inf')):
                self.assertIsNone(validate({**self.obs, field:value}))
        self.assertIsNone(validate({**self.obs,'timestamp':self.now-901}))
        self.assertIsNone(validate({**self.obs,'timestamp':self.now+120}))
        self.assertEqual(validate({**self.obs,'air_temperature':'20','feels_like':None})['feels_like'],20)

    def test_empty_observation_and_timeout(self):
        calls=[]
        def get(*args, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(raise_for_status=lambda:None, json=lambda:{'obs':[]})
        self.ns['requests']=types.SimpleNamespace(get=get, RequestException=OSError)
        self.assertIsNone(self.ns['fetch_station_observation']())
        self.assertEqual(calls[0]['timeout'],(5,20))

    def test_all_requests_have_timeouts(self):
        for node in ast.walk(TREE):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='get' and isinstance(node.func.value,ast.Name) and node.func.value.id=='requests':
                self.assertIn('timeout',[k.arg for k in node.keywords],node.lineno)

    def test_partial_delivery_retries_only_missing_destination_and_survives_reload(self):
        ns=self.ns
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            ns.update(DELIVERY_STATE_FILE=tmp+'/delivery.json', _delivery_state=None,
                      session=object(), TELEGRAM_TOKEN='test',TELEGRAM_CHAT_ID='test',
                      post_to_bluesky=lambda m:calls.append('bsky') or True,
                      send_telegram_message=lambda m:calls.append('telegram') or False)
            self.assertFalse(ns['_deliver_post']('hello'))
            ns['_delivery_state']=None
            ns['send_telegram_message']=lambda m:calls.append('telegram') or True
            self.assertTrue(ns['_deliver_post']('hello'))
            self.assertEqual(calls,['bsky','telegram','telegram'])
            self.assertTrue(ns['_deliver_post']('hello'))
            self.assertEqual(len(calls),3)

    def test_failed_weather_not_recorded(self):
        ns=self.ns
        with tempfile.TemporaryDirectory() as tmp:
            recorded=[]
            ns.update(DELIVERY_STATE_FILE=tmp+'/delivery.json',_delivery_state=None,
                      session=object(),TELEGRAM_TOKEN=None,TELEGRAM_CHAT_ID=None,
                      post_to_bluesky=lambda m:False,_snapshot_log_summary=lambda s:'test',
                      _record_weather_post=lambda *a:recorded.append(a))
            self.assertFalse(ns['post_weather_update']('test',{'observed_at':datetime.now()},'routine'))
            self.assertEqual(recorded,[])

    def test_rain_dry_gap_and_observation_timestamp(self):
        ns=self.ns
        self.now = datetime.now(ns["PEORIA_TIMEZONE"]).replace(hour=12, minute=0, second=0, microsecond=0).timestamp()
        ns.update(daily_date=datetime.fromtimestamp(self.now,ns['PEORIA_TIMEZONE']).strftime('%Y-%m-%d'),daily_max_wind_avg=0,daily_max_wind_gust=0,
                  current_event_strike_total=0,last_strike_epoch_global=None,
                  current_rain_event_total=0,rain_event_baseline=None,last_rain_epoch_global=None,
                  _previous_rain_total=None,_previous_rain_date=None,_daily_high_temp_f=None,
                  _daily_low_temp_f=None,_daily_rain_total_in=0,_pressure_history=[])
        def poll(offset, rain):
            epoch=self.now+offset
            ns['time']=types.SimpleNamespace(time=lambda:epoch)
            return ns['_build_weather_snapshot']({**self.obs,'timestamp':epoch,'precip_accum_local_day':rain})
        first=poll(0,0)
        self.assertEqual(first['observed_at'].timestamp(),self.now)
        self.assertAlmostEqual(poll(300,2.54)['current_rain_event_total'],.1,places=5)
        for t in range(600,15000,300):
            dry=poll(t,2.54)
        self.assertEqual(dry['current_rain_event_total'],0)
        self.assertAlmostEqual(poll(15000,5.08)['current_rain_event_total'],.1,places=5)

    def test_pending_weather_retry_records_only_after_recovery(self):
        ns=self.ns
        with tempfile.TemporaryDirectory() as tmp:
            recorded=[]
            ns.update(DELIVERY_STATE_FILE=tmp+'/delivery.json',_delivery_state=None,
                      session=object(),TELEGRAM_TOKEN=None,TELEGRAM_CHAT_ID=None,
                      post_to_bluesky=lambda m:False,_snapshot_log_summary=lambda s:'test',
                      _last_posted_weather_snapshot=None,
                      _record_weather_post=lambda *a:recorded.append(a))
            snapshot={'observed_at':datetime.now(ns['PEORIA_TIMEZONE'])}
            self.assertFalse(ns['post_weather_update']('pending',snapshot,'routine'))
            ns['post_to_bluesky']=lambda m:True
            ns['_retry_pending_deliveries']()
            self.assertEqual(len(recorded),1)
            self.assertEqual(recorded[0][0]['observed_at'],snapshot['observed_at'])
            ns['_retry_pending_deliveries']()
            self.assertEqual(len(recorded),1)

    def test_failed_alert_is_not_added_to_history(self):
        ns=self.ns; saved={}
        ns.update(_last_nws_alert_check_epoch=0,_cleanup_alert_history=lambda h:h,
                  _load_alert_history=lambda:{},fetch_nws_alerts=lambda:[{'id':'test','properties':{'sent':'now'}}],
                  format_nws_alert_post=lambda a:'test',_deliver_post=lambda *a,**k:False,
                  _save_alert_history=lambda h:saved.update(h))
        ns['check_nws_alerts'](True)
        self.assertEqual(saved,{})
        ns['_deliver_post']=lambda *a,**k:True
        ns['check_nws_alerts'](True)
        self.assertIn('test|now',saved)

    def test_signals_only_enqueue(self):
        ns=self.ns; calls=[]
        ns.update(_pending_commands=deque(),_load_control_command=lambda:'alerts',
                  _run_control_command=lambda c:calls.append(c))
        ns['force_update'](None,None); ns['run_control_command'](None,None)
        self.assertEqual(calls,[])
        ns['_drain_control_commands']()
        self.assertEqual(calls,['weather','alerts'])

if __name__=='__main__': unittest.main()
