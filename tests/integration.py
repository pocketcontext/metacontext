#!/usr/bin/env python3
"""Exercise schema ingestion using isolated DealContext and MetaContext servers."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ingestion'))
from sync import Client, sync


def records(collection, record_id=None):
    path = f'/api/collections/{collection}/records'
    return path if record_id is None else f'{path}/{record_id}'


class Server:
    def __init__(self, binary, root):
        self.root = root
        self.common = [str(binary), '--dir', str(root / 'pb_data'),
                       '--migrationsDir', str(root / 'pb_migrations'),
                       '--hooksDir', str(root / 'pb_hooks')]
        self.password = secrets.token_urlsafe(24)
        subprocess.run(self.common + ['superuser', 'upsert', 'admin@example.test', self.password],
                       cwd=root, check=True, capture_output=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.url = f'http://127.0.0.1:{self.port}'
        self.process = None
        self.log = open(root / 'server.log', 'w+')
        self.start()
        self.admin = Client(self.url, Client(self.url).request(
            'POST', '/api/collections/_superusers/auth-with-password',
            {'identity': 'admin@example.test', 'password': self.password})['token'])
        self.admin.request('POST', records('agents'), {
            'name': 'Integration agent', 'email': 'agent@example.test',
            'password': self.password, 'passwordConfirm': self.password})
        self.agent = Client(self.url, Client(self.url).request(
            'POST', '/api/collections/agents/auth-with-password',
            {'identity': 'agent@example.test', 'password': self.password})['token'])

    def start(self):
        self.process = subprocess.Popen(self.common + ['serve', '--http', f'127.0.0.1:{self.port}',
                                      '--contextConfig', str(self.root / 'pocketcontext.json')],
                                      cwd=self.root, stdout=self.log, stderr=self.log)
        for _ in range(150):
            try:
                Client(self.url).request('GET', '/api/health')
                return
            except Exception:
                if self.process.poll() is not None:
                    raise RuntimeError('Server exited during startup; inspect temporary server.log')
                time.sleep(.1)
        raise RuntimeError('Server did not start')

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def close(self):
        self.stop()
        self.log.close()

    def configure(self, config):
        self.stop()
        (self.root / 'pocketcontext.json').write_text(json.dumps(config))
        self.start()


@contextlib.contextmanager
def fails(label):
    try:
        yield
    except Exception:
        return
    raise AssertionError(f'{label}: expected failure')


def snapshot(client):
    tables = client.query('SELECT id, database, name, description, state FROM tables')
    columns = client.query('SELECT id, "table", name, data_type, description, state FROM columns')
    return tables, columns


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--dealcontext', default=str(ROOT.parent / 'dealcontext'))
    args = parser.parse_args()
    binary = Path(args.binary).resolve()
    with tempfile.TemporaryDirectory(prefix='metacontext-test-') as temporary:
        workspace = Path(temporary)
        source_root, catalog_root = workspace / 'source', workspace / 'catalog'
        source_root.mkdir()
        catalog_root.mkdir()
        # Use committed fixtures, preserving and excluding unrelated working-tree edits.
        fixture_version = (ROOT / 'DEALCONTEXT_TEST_VERSION').read_text().strip()
        archive = subprocess.run(['git', '-C', str(Path(args.dealcontext).resolve()), 'archive',
                                  fixture_version, 'pb_migrations', 'pb_hooks', 'pocketcontext.json'],
                                 check=True, capture_output=True).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as fixture:
            fixture.extractall(source_root, filter='data')
        for directory in ('pb_migrations', 'pb_hooks'):
            if (ROOT / directory).exists():
                shutil.copytree(ROOT / directory, catalog_root / directory)
        shutil.copy(ROOT / 'pocketcontext.json', catalog_root / 'pocketcontext.json')
        with contextlib.ExitStack() as stack:
            source = Server(binary, source_root)
            stack.callback(source.close)
            catalog = Server(binary, catalog_root)
            stack.callback(catalog.close)
            client = catalog.agent
            db = client.request('POST', records('databases'), {
                'name': 'DealContext', 'endpoint': source.url, 'description': 'Curated database'})
            db2 = client.request('POST', records('databases'), {
                'name': 'Independent registration', 'endpoint': source.url})
            source_schema = source.agent.request('GET', '/api/context/schema')['tables']
            sync(client, db['id'], source.agent.token)
            tables, columns = snapshot(client)
            assert {t['name'] for t in tables} == {t['name'] for t in source_schema}
            assert 'agents' not in {t['name'] for t in tables}
            assert all(not t['name'].startswith('_') for t in tables)
            for expected in source_schema:
                table = next(t for t in tables if t['name'] == expected['name'])
                actual = {(c['name'], c['data_type']) for c in columns if c['table'] == table['id']}
                assert actual == {(c['name'], c['type']) for c in expected['columns']}
            assert all(r['state'] == 'present' for r in tables + columns)
            first_ids = ({t['id'] for t in tables}, {c['id'] for c in columns})
            chosen_table = next(t for t in tables if t['name'] == 'organizations')
            chosen_column = next(c for c in columns if c['table'] == chosen_table['id'] and c['name'] == 'name')
            client.request('PATCH', records('tables', chosen_table['id']), {'description': 'Curated table'})
            client.request('PATCH', records('columns', chosen_column['id']), {'description': 'Curated column'})
            sync(client, db['id'], source.agent.token)
            tables, columns = snapshot(client)
            assert first_ids == ({t['id'] for t in tables}, {c['id'] for c in columns})
            assert next(t for t in tables if t['id'] == chosen_table['id'])['description'] == 'Curated table'
            assert next(c for c in columns if c['id'] == chosen_column['id'])['description'] == 'Curated column'
            sync(client, db2['id'], source.agent.token)
            tables, columns = snapshot(client)
            other_table_ids = {t['id'] for t in tables if t['database'] == db2['id']}
            assert len(other_table_ids) == len(first_ids[0]) and other_table_ids.isdisjoint(first_ids[0])
            before_failure = snapshot(client)
            with fails('source authentication'):
                sync(client, db['id'], 'invalid-token')
            assert snapshot(client) == before_failure
            runs = client.query('SELECT status, error FROM ingestion_runs')
            assert any(r['status'] == 'failed' and r['error'] for r in runs)
            lock = client.request('POST', records('ingestion_runs'), {'database': db['id'], 'status': 'running'})
            with fails('concurrent run'):
                sync(client, db['id'], source.agent.token)
            assert snapshot(client) == before_failure
            client.request('PATCH', records('ingestion_runs', lock['id']), {'status': 'failed', 'error': 'Test lock released'})
            original_config = json.loads((source_root / 'pocketcontext.json').read_text())
            restricted = json.loads(json.dumps(original_config))
            del restricted['tables']['notes']
            restricted['tables']['organizations'] = ['id']
            source.configure(restricted)
            # Simulate a lost response after a real write committed. Retrying
            # must reconcile partial writes without duplicating their identities.
            class LostResponse(Client):
                def request(self, method, path, body=None):
                    result = super().request(method, path, body)
                    if method == 'PATCH' and path.startswith(records('columns') + '/'):
                        raise RuntimeError('Injected lost response after committed column update')
                    return result

            with fails('interrupted import'):
                sync(LostResponse(catalog.url, client.token), db['id'], source.agent.token)
            assert snapshot(client) == before_failure
            sync(client, db['id'], source.agent.token)
            tables, columns = snapshot(client)
            missing_table = next(t for t in tables if t['database'] == db['id'] and t['name'] == 'notes')
            assert missing_table['state'] == 'missing'
            assert all(c['state'] == 'missing' for c in columns if c['table'] == missing_table['id'])
            assert next(c for c in columns if c['id'] == chosen_column['id'])['state'] == 'missing'
            assert all(t['state'] == 'present' for t in tables if t['database'] == db2['id'])
            assert all(c['state'] == 'present' for c in columns if c['table'] in other_table_ids)
            source.configure(original_config)
            sync(client, db['id'], source.agent.token)
            tables, columns = snapshot(client)
            assert all(r['state'] == 'present' for r in tables + columns)
            assert first_ids[0] == {t['id'] for t in tables if t['database'] == db['id']}
            assert first_ids[1] == {c['id'] for c in columns if c['table'] in first_ids[0]}
            assert next(c for c in columns if c['id'] == chosen_column['id'])['description'] == 'Curated column'
            with fails('agent deletion'):
                client.request('DELETE', records('databases', db['id']))
            with fails('unauthenticated SQL'):
                Client(catalog.url).query('SELECT id FROM databases')
            with fails('auth metadata SQL'):
                client.query('SELECT id FROM agents')
            with fails('duplicate table identity'):
                client.request('POST', records('tables'), {'database': db['id'], 'name': chosen_table['name'], 'state': 'present'})
            for collection, record_id, changes in (
                ('tables', chosen_table['id'], {'name': 'renamed'}),
                ('tables', chosen_table['id'], {'database': db2['id']}),
                ('columns', chosen_column['id'], {'name': 'renamed'}),
                ('columns', chosen_column['id'], {'table': next(iter(other_table_ids))}),
                ('ingestion_runs', lock['id'], {'database': db2['id']}),
            ):
                with fails(f'immutable {collection} identity'):
                    client.request('PATCH', records(collection, record_id), changes)
            other_run = client.query(f"SELECT id FROM ingestion_runs WHERE database = '{db2['id']}'")[0]['id']
            for collection, record_id in (('tables', chosen_table['id']), ('columns', chosen_column['id'])):
                with fails('cross-database observation marker'):
                    client.request('PATCH', records(collection, record_id), {'last_seen_run': other_run})
            print('PASS: DealContext schema import, repeatability, curation, failure, locking, scoped missing/reappearance, permissions')


if __name__ == '__main__':
    main()
