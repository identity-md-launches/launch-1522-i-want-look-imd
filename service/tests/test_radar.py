"""Deterministic Radar contract, cache, source-precedence and outage tests (no network)."""
import base64
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chadboard import db
from chadboard.api import Api
from chadboard.config import Config, IMD_TOKEN
from chadboard.radar import AGENTS, SEAT, SWARM, Radar, normalize, SchemaError
from chadboard.snapshot import build_snapshot
from chadboard.backfill import coverage
from chadboard.rpc import HistoricalRpc, Rpc, RpcError

A = '0x' + '11' * 20
B = '0x' + '22' * 20
NFT = '0x' + '33' * 20
NOW = 1791907000
AT = '2026-10-13T16:00:00Z'
HASH = '0x' + 'ab' * 32


def swarm(owner=A):
    return {'at': AT, 'seats': [[1, 50700, 10, 5, 2, 1, 2, 1791900000000, 0, 1, owner]], 'events': [{'jobId': 'fixture-job', 'state': 'accepted'}], 'running': []}


def seat(owner=A):
    return {'seat': 1, 'agentId': 50700, 'owner': owner, 'online': True, 'status': 'active',
            'attempts': 10, 'accepted': 5, 'rejected': 2, 'failed': 1, 'pending': 2,
            'work': [{'at': AT, 'status': 'accepted', 'jobId': 'fixture-job'}]}


def agents():
    return {'updatedAt': AT, 'minLiquidityUsd': 2000,
            'launches': [{'n': 5, 'symbol': 'GOOD', 'liquidityUsd': 2500, 'priceUsd': 2, 'counted': True},
                         {'n': 6, 'symbol': 'LOW', 'liquidityUsd': 3, 'priceUsd': 1000, 'counted': True},
                         {'n': 7, 'symbol': 'EXCLUDED', 'liquidityUsd': 5000, 'priceUsd': 5, 'counted': False}],
            'agents': [{'wallet': A, 'seats': [1], 'acceptedTasks': 5, 'launches': 3, 'valueUsd': 100250,
                        'unclaimedUsd': 100200, 'tokens': [[5, 100, 0], [6, 100, 0], [7, 10, 1]]}]}


class FakeChain:
    def block(self, n):
        return {'number': hex(n), 'hash': HASH, 'timestamp': hex(NOW - (100-n)*12)}
    def eth_call(self, *args):
        return hex(100 * 10**18)


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(db_path=Path(self.tmp.name)/'db.sqlite', radar_enabled=True,
                          chain_id=1, token=IMD_TOKEN,
                          archive_rpc_url='', radar_seat_limit=2, verify_balances=0,
                          seat_nft=NFT, activation_event='0x'+'cd'*32+':seat:1')
        self.conn = db.connect(self.cfg.db_path)
        self.payloads = {SWARM: swarm(), SEAT+'1': seat(), AGENTS: agents()}
        self.calls = []
        def transport(url, timeout):
            self.calls.append(url)
            return json.dumps(self.payloads[url]).encode()
        self.radar = Radar(self.conn, self.cfg, transport, lambda: NOW)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def snapshot(self):
        self.conn.execute('INSERT OR IGNORE INTO transfer_events VALUES(?,?,?,?,?,?,?,?)', (HASH,0,90,HASH,self.cfg.token,'0x'+'0'*40,A,str(100*10**18)))
        self.conn.execute('INSERT OR IGNORE INTO seat_events VALUES(?,?,?,?,?,?,?,?,?,?)', (HASH,1,91,HASH,NFT,'transfer','1','0x'+'0'*40,A,None))
        self.conn.execute('INSERT OR IGNORE INTO seat_events VALUES(?,?,?,?,?,?,?,?,?,?)', (HASH,2,92,HASH,NFT,'activation','1',None,None,None))
        db.set_checkpoint(self.conn, 'transfers:'+self.cfg.token,100,HASH)
        return build_snapshot(self.conn, FakeChain(), self.cfg, FakeChain().block(100), NFT, {'configuration':1})

    def test_import_raw_hash_metadata_and_cache_ttl(self):
        status = self.radar.refresh()
        self.assertEqual(status['cachedResponses'],3)
        self.radar.refresh()
        self.assertEqual(len(self.calls),3)
        response=self.conn.execute('SELECT * FROM radar_responses WHERE source_url=?',(SWARM,)).fetchone()
        self.assertEqual(response['response_hash'],hashlib.sha256(response['raw_body']).hexdigest())
        self.assertEqual(response['retrieved_at'],NOW)
        self.assertTrue(response['schema_version'])
        raw=Api(self.conn,self.cfg).handle('/v1/radar/raw/'+str(response['id']),{})
        self.assertEqual(base64.b64decode(raw['rawBodyBase64']),response['raw_body'])
        observed=self.radar.observations(address=A)
        self.assertEqual(observed['seats'][0]['accepted'],5)
        self.assertTrue(any(s['online'] for s in observed['seats']))
        self.assertEqual(self.radar.activity()['events'][0]['jobId'],'fixture-job')

    def test_api_unavailable_keeps_cache_and_ethereum_snapshot(self):
        self.radar.refresh()
        sid=self.snapshot()
        self.radar.bind(sid)
        before=Api(self.conn,self.cfg).leaderboard(10,sid)
        def unavailable(*args): raise OSError('offline')
        self.radar.transport=unavailable
        status=self.radar.refresh(force=True)
        self.assertEqual(status['dataQuality']['status'],'degraded')
        self.assertEqual(status['cachedResponses'],3)
        after=Api(self.conn,self.cfg).leaderboard(10,sid)
        self.assertEqual(before,after)
        self.assertEqual(after['rows'][0]['score'],before['rows'][0]['score'])

    def test_unavailable_without_cache_and_disabled_are_optional(self):
        def unavailable(*args): raise TimeoutError()
        self.radar.transport=unavailable
        self.assertEqual(self.radar.refresh()['dataQuality']['status'],'unavailable')
        sid=self.snapshot()
        rows=Api(self.conn,self.cfg).leaderboard(10,sid)['rows']
        self.assertEqual(rows[0]['source'],'ethereum')
        self.cfg.radar_enabled=False
        self.assertEqual(self.radar.refresh()['dataQuality']['status'],'disabled')

    def test_outage_does_not_fan_out_to_cached_seat_endpoints(self):
        self.radar.refresh()
        self.calls.clear()
        def unavailable(url, timeout):
            self.calls.append(url)
            raise TimeoutError()
        self.radar.transport=unavailable
        self.radar.refresh(force=True)
        self.assertEqual(set(self.calls),{SWARM,AGENTS})

    def test_unexpected_radar_failure_cannot_rollback_ranking(self):
        from chadboard.pipeline import refresh_once
        self.snapshot()
        chain=FakeChain()
        chain.chain_id=lambda: self.cfg.chain_id
        chain.finalized_block=lambda _: chain.block(100)
        with patch('chadboard.pipeline.read_board_state',return_value={'seatNFT':NFT}), \
             patch('chadboard.pipeline.sync_transfers',return_value=0), \
             patch('chadboard.pipeline.sync_seats',return_value=0), \
             patch('chadboard.pipeline.write_publication',return_value={}), \
             patch('chadboard.pipeline.Radar.refresh',side_effect=RuntimeError('unavailable')):
            result=refresh_once(self.conn,chain,self.cfg,1)
        row=Api(self.conn,self.cfg).leaderboard(10,result['snapshot_id'])['rows'][0]
        self.assertEqual(row['wallet'],A)
        self.assertEqual(row['source'],'ethereum')

    def test_malformed_response_quarantined_without_cache_replacement(self):
        self.radar.refresh()
        old=self.radar.observations()
        for raw in (b'<html>not JSON</html>',b'{"seats": [true]}',b'[]',b'null'):
            self.assertIsNone(self.radar.ingest(SWARM,raw,NOW+1))
        self.assertEqual(self.radar.observations(),old)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM radar_responses WHERE valid=0').fetchone()[0],4)
        self.assertEqual(self.radar.status()['failures'][0]['error'],'malformed-response')
        with self.assertRaises(SchemaError): normalize(SEAT+'2',seat(),self.cfg)

    def test_stale_upstream_data_and_old_cache_are_visible(self):
        old=swarm();old['at']='2020-01-01T00:00:00Z'
        self.radar.ingest(SWARM,json.dumps(old).encode(),NOW)
        self.assertTrue(self.radar.observations()['dataQuality']['stale'])
        self.radar.ingest(SWARM,json.dumps(swarm()).encode(),NOW-2*86400)
        self.assertTrue(self.radar.observations()['dataQuality']['stale'])
        self.assertEqual(self.radar.status()['dataQuality']['staleResponses'],1)

    def test_mapping_disagreement_preserves_values_and_ethereum_ranking(self):
        sid=self.snapshot()
        before=Api(self.conn,self.cfg).leaderboard(10,sid)
        self.payloads[SWARM]=swarm(B);self.payloads[SEAT+'1']=seat(B)
        self.radar.refresh();self.radar.bind(sid)
        result=Api(self.conn,self.cfg).leaderboard(10,sid)
        a=result['rows'][0]
        self.assertEqual(a['score'],before['rows'][0]['score'])
        self.assertEqual(a['rank'],before['rows'][0]['rank'])
        self.assertEqual(a['seat']['count'],1)
        self.assertEqual(a['balances']['current']['raw'],str(100*10**18))
        self.assertEqual(a['source'],'merged')
        self.assertTrue(result['conflict'])
        conflict=next(c for c in a['conflicts'] if c['kind']=='ethereum-radar-disagreement')
        self.assertEqual(conflict['ethereum'],A);self.assertIn(B,conflict['radar'])
        self.assertEqual(a['fieldSources']['score'],'ethereum')
        self.assertEqual(a['asOfBlock'],100)
        absent=Api(self.conn,self.cfg).wallets([B],sid)['wallets'][0]
        self.assertFalse(absent['found']) # Radar cannot add a ranked wallet.
        self.assertTrue(absent['radar']['dataQuality']['available'])

    def test_duplicate_relationships_deduplicate_and_multi_seat_wallet_is_valid(self):
        data=swarm();data['seats'].append(copy.deepcopy(data['seats'][0]))
        second=copy.deepcopy(data['seats'][0]);second[0]=2;data['seats'].append(second)
        self.radar.ingest(SWARM,json.dumps(data).encode(),NOW)
        result=self.radar.observations()
        self.assertEqual(len(result['relationships']),2)
        self.assertEqual([c['kind'] for c in result['conflicts']],['duplicate-relationship'])
        data['seats'][1][-1]=B
        self.radar.ingest(SWARM,json.dumps(data).encode(),NOW)
        self.assertIn('radar-disagreement',[c['kind'] for c in self.radar.observations()['conflicts']])

    def test_low_liquidity_rewards_excluded_but_participation_and_raw_preserved(self):
        self.radar.refresh()
        agent=self.radar.observations(address=A)['launches'][0]
        self.assertEqual([r['launch'] for r in agent['rewards']],[5])
        self.assertEqual(agent['eligibleValueUsd'],'200')
        self.assertEqual(agent['eligibleUnclaimedUsd'],'200')
        self.assertEqual(agent['participation'],[5,6,7])
        self.assertEqual(len(agent['excluded']),2)
        self.assertEqual(agent['reportedValueUsd'],'100250')
        self.cfg.radar_min_liquidity_usd=3000
        self.assertEqual(normalize(AGENTS,agents(),self.cfg)['agents'][0]['rewards'],[])

    def test_snapshot_observations_are_immutable_after_refresh(self):
        self.radar.refresh();sid=self.snapshot();self.radar.bind(sid)
        frozen=self.radar.observations(sid)
        before=db.snapshot_row(db.latest_snapshot(self.conn))['contentHash']
        self.payloads[SEAT+'1']['accepted']=99
        self.radar.refresh(force=True);self.radar.bind(sid)
        self.assertEqual(self.radar.observations(sid),frozen)
        self.assertEqual(db.snapshot_row(db.latest_snapshot(self.conn))['contentHash'],before)
        self.assertTrue(any(s['accepted']==99 for s in self.radar.observations()['seats']))

    def test_status_conflict_and_sources_have_no_false_block_claim(self):
        self.payloads[SEAT+'1']['status']='inactive'
        self.radar.refresh();sid=self.snapshot();self.radar.bind(sid)
        row=Api(self.conn,self.cfg).wallets([A],sid)['wallets'][0]
        self.assertIn('status-disagreement',[c['kind'] for c in row['conflicts']])
        self.assertTrue(all(s['asOfBlock'] is None for s in row['radar']['sources']))
        self.assertTrue(row['seat']['activated'])

    def test_coverage_reports_gaps_and_unique_wallets(self):
        self.snapshot();stream='transfers:'+self.cfg.token
        db.set_setting(self.conn,stream+':start','80')
        self.conn.execute('INSERT INTO indexed_ranges VALUES(?,?,?,?)',(stream,80,90,1))
        c=coverage(self.conn,self.cfg,100)
        self.assertEqual(c['gaps'],[{'fromBlock':91,'toBlock':100}])
        self.assertFalse(c['coverageVerified']);self.assertEqual(c['walletCount'],1)

    def test_http_reader_never_sees_uncommitted_snapshot(self):
        import threading
        import urllib.request
        from chadboard.api import make_server
        sid=self.snapshot()
        self.cfg.port=0
        server=make_server(self.conn,self.cfg)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.conn.execute('BEGIN')
        try:
            self.conn.execute("INSERT INTO snapshots SELECT 'partial',sequence+1,as_of_block,as_of_block_hash,as_of_timestamp,created_at,content_hash,score_version,total_seats,activated_seats,ranked_wallets,metadata FROM snapshots WHERE id=?",(sid,))
            with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_address[1])+'/v1/snapshot/latest',timeout=3) as response:
                self.assertEqual(json.load(response)['snapshotId'],sid)
        finally:
            self.conn.execute('ROLLBACK')
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_rpc_secrets_not_logged_or_returned(self):
        from chadboard.rpc import provider_error, safe_error
        secret='https://private.invalid/private-credential'
        self.assertNotIn('private-credential',provider_error('rate limit '+secret))
        self.assertNotIn('private-credential',safe_error(OSError(secret)))
        self.cfg.archive_rpc_url=secret
        self.assertNotIn('private-credential',repr(self.cfg))

    def test_archive_routes_only_historical_state_and_deep_logs(self):
        self.cfg.archive_rpc_url='https://archive.invalid'
        rpc=HistoricalRpc(self.cfg,historical_before=100)
        with patch.object(Rpc,'_post',return_value='0x1') as post:
            rpc.eth_call(A,'0x',99)
            self.assertEqual(post.call_args.args[0],self.cfg.archive_rpc_url)
            rpc.eth_call(A,'0x','latest')
            self.assertEqual(post.call_args.args[0],self.cfg.rpc_urls[0])
            rpc.block_number()
            self.assertEqual(post.call_args.args[0],self.cfg.rpc_urls[0])

    def test_adaptive_log_scan_learns_provider_cap_without_repeat_failures(self):
        rpc=Rpc(['https://fixture.invalid'])
        sizes=[]
        def logs(params):
            size=int(params[0]['toBlock'],16)-int(params[0]['fromBlock'],16)+1
            sizes.append(size)
            if size>10: raise RpcError('range cap',status=400,max_range=10)
            return []
        with patch.object(rpc,'_get_logs_once',side_effect=logs):
            chunks=list(rpc.get_logs_adaptive(A,[],0,29,2000))
        self.assertEqual(sizes,[30,10,10,10])
        self.assertEqual([(a,b) for a,b,_ in chunks],[(0,9),(10,19),(20,29)])

    def test_first_mainnet_scan_requires_archive_preflight(self):
        from chadboard.pipeline import refresh_with_retries
        with patch('chadboard.backfill.preflight',side_effect=RuntimeError('archive unavailable')) as check, \
             patch('chadboard.pipeline.sync_transfers') as sync:
            with self.assertRaisesRegex(RuntimeError,'archive unavailable'):
                refresh_with_retries(self.conn,self.cfg)
            check.assert_called_once()
            sync.assert_not_called()


if __name__ == '__main__': unittest.main()
