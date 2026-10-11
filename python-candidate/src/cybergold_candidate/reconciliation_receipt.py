"""Retained completed-reconciliation receipt and RPC-count contract, unchanged v2."""
import copy
import math
import re

from .alias_dates import date_milliseconds
from .rpc_http import parse_json
from .worker_contract import iso_seconds

KIND='cybergold-onchain-indexer-reconciliation-receipt'
METHODS=('eth_call','eth_chainId','eth_getBlockByHash','eth_getBlockByNumber','eth_getCode','eth_getLogs')
SOURCES=('core-event','governance-event','safe-event','core-address','governance-address','safe-address')
IDENTITIES=('databaseSchemaVersion','rawJournalVersion','dashboardProjectionVersion','stateSnapshotVersion','safeCursorVersion')


def safe_count(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0 and value<=2**53-1 and value==int(value)


def matches(pattern,value):return isinstance(value,str) and re.fullmatch(pattern,value) is not None
def decimal(value):return matches(r'0|[1-9][0-9]*',value)
def text(value):
    if not isinstance(value,str):raise ValueError('Receipt text is invalid')
    return value
def record(value,keys):
    if not isinstance(value,dict) or set(value)!=set(keys):raise ValueError('Receipt object is invalid')
    return value
def iso_milliseconds(value):
    if abs(value)>8640000000000000:raise ValueError('Invalid time value')
    return iso_seconds(int(value)//1000)[:-5]+f'.{int(value)%1000:03d}Z'


class GatewayMethodRejectedError(ValueError):
    def __init__(self):
        super().__init__('Indexer gateway RPC method is outside the frozen App allowlist')


class RpcCounter:
    def __init__(self):
        self.counts={'totalAttempts':0,'failedAttempts':0,'adaptiveRetryAttempts':0,
            'byMethod':dict.fromkeys(METHODS,0),'ethGetLogs':{'attempts':0,'plannedAttempts':0,'adaptiveAttempts':0,
            'failedAttempts':0,'addressScopedViemTransportRetries':0,'legacyViemTransportRetriesObserved':None,
            'bySource':dict.fromkeys(SOURCES,0),'plannedBySource':dict.fromkeys(SOURCES,0)}}
    def plan(self,source):
        self.counts['ethGetLogs']['plannedAttempts']+=1;self.counts['ethGetLogs']['plannedBySource'][source]+=1
    def log_attempt(self,source,adaptive=False):
        logs=self.counts['ethGetLogs'];logs['attempts']+=1;logs['bySource'][source]+=1
        if adaptive:logs['adaptiveAttempts']+=1;self.counts['adaptiveRetryAttempts']+=1
    def log_failure(self):self.counts['ethGetLogs']['failedAttempts']+=1
    def gateway_attempt(self,method):
        if method not in METHODS:raise GatewayMethodRejectedError()
        self.counts['totalAttempts']+=1;self.counts['byMethod'][method]+=1
    def gateway_failure(self):self.counts['failedAttempts']+=1
    def snapshot(self):return copy.deepcopy(self.counts)


def validate_rpc(counts):
    logs=counts['ethGetLogs']
    scalars=[counts[key] for key in ('totalAttempts','failedAttempts','adaptiveRetryAttempts')]
    scalars+=list(counts['byMethod'].values())+[logs[key] for key in ('attempts','plannedAttempts','adaptiveAttempts','failedAttempts','addressScopedViemTransportRetries')]
    scalars+=list(logs['bySource'].values())+list(logs['plannedBySource'].values())
    if (set(counts['byMethod'])!=set(METHODS) or set(logs['bySource'])!=set(SOURCES) or set(logs['plannedBySource'])!=set(SOURCES)
        or not all(safe_count(value) for value in scalars) or logs['legacyViemTransportRetriesObserved'] is not None
        or sum(counts['byMethod'].values())!=counts['totalAttempts']
        or counts['failedAttempts']>counts['totalAttempts'] or counts['adaptiveRetryAttempts']>counts['totalAttempts']
        or counts['byMethod']['eth_getLogs']!=logs['attempts'] or counts['adaptiveRetryAttempts']!=logs['adaptiveAttempts']
        or sum(logs['bySource'].values())!=logs['attempts'] or sum(logs['plannedBySource'].values())!=logs['plannedAttempts']
        or any(logs[key]>logs['attempts'] for key in ('plannedAttempts','adaptiveAttempts','failedAttempts'))
        or logs['failedAttempts']>counts['failedAttempts']):raise ValueError('Reconciliation RPC request counts are invalid')


def cursors(values,anchor,label):
    result=[];addresses=set()
    for value in values:
        address=value['address'].lower()
        if (not matches(r'0x[0-9a-fA-F]{40}',address) or address in addresses
            or value['blockNumber']!=anchor['blockNumber'] or value['blockHash'].lower()!=anchor['blockHash'].lower()):
            raise ValueError(label+' is not completely bound to the anchor')
        addresses.add(address);result.append({'address':address,'blockNumber':str(value['blockNumber']),'blockHash':value['blockHash'].lower()})
    return sorted(result,key=lambda row:row['address'])


def create_receipt(value):
    if (not matches(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',value['reconciliationId'])
        or not matches(r'[0-9a-f]{64}',value['gatewayConfigRevision'])
        or value['runtimeConfigId'] is not None and not matches(r'sha256:[0-9a-f]{64}',value['runtimeConfigId'])
        or not safe_count(value['completedAtMs']) or not safe_count(value['durationMs'])):
        raise ValueError('Reconciliation receipt identity or completion time is invalid')
    for label,version in value['identities'].items():
        if not matches(r'[A-Za-z0-9._:-]{1,128}',version):raise ValueError(label+' is invalid')
    for field,key,label in [('rawJournal','logCount','Raw journal log count'),('dashboardProjection','eventLogCount','Dashboard projection event count'),
        ('stateSnapshot','modelCount','State snapshot model count'),('safeCursors','eventLogCount','Safe event count')]:
        if not decimal(value[field][key]):raise ValueError(label+' is invalid')
    validate_rpc(value['rpcRequests']);anchor=value['finalizedAnchor']
    raw=cursors(value['rawJournal']['cursors'],anchor,'Raw journal cursor')
    safe=cursors(value['safeCursors']['cursors'],anchor,'Safe cursor')
    tracked=value['rawJournal']['trackedAddressCount'];configured=value['safeCursors']['configuredSafeCount']
    dashboard=value['dashboardProjection'];snapshot=value['stateSnapshot']
    if (not safe_count(tracked) or tracked<1 or len(raw)!=tracked or not safe_count(configured) or len(safe)!=configured
        or any(row['blockNumber']!=anchor['blockNumber'] or row['blockHash'].lower()!=anchor['blockHash'].lower() for row in (dashboard,snapshot))
        or dashboard['profile']!=snapshot['profile'] or not dashboard['profile']):
        raise ValueError('Reconciliation receipt is partial or anchor-inconsistent')
    return {'kind':KIND,'formatVersion':2,'partial':False,'reconciliationId':value['reconciliationId'],
        'gatewayConfigRevision':value['gatewayConfigRevision'],'runtimeConfigId':value['runtimeConfigId'],
        'finalizedAnchor':{'number':str(anchor['blockNumber']),'hash':anchor['blockHash'].lower()},'identities':copy.deepcopy(value['identities']),
        'rawJournal':{'trackedAddressCount':tracked,'cursorCount':len(raw),'logCount':value['rawJournal']['logCount'],'cursors':raw},
        'dashboardProjection':{'cursorCount':1,'eventLogCount':dashboard['eventLogCount'],'blockNumber':str(dashboard['blockNumber']),
            'blockHash':dashboard['blockHash'].lower(),'profile':dashboard['profile']},
        'stateSnapshot':{'cursorCount':1,'modelCount':snapshot['modelCount'],'blockNumber':str(snapshot['blockNumber']),
            'blockHash':snapshot['blockHash'].lower(),'profile':snapshot['profile']},
        'safeCursors':{'configuredSafeCount':configured,'cursorCount':len(safe),'eventLogCount':value['safeCursors']['eventLogCount'],'cursors':safe},
        'rpcRequests':copy.deepcopy(value['rpcRequests']),'completedAt':iso_milliseconds(value['completedAtMs']),'durationMs':value['durationMs']}


def stored_cursors(value):
    if not isinstance(value,list):raise ValueError('Receipt cursors are invalid')
    result=[]
    for row in value:
        record(row,('address','blockHash','blockNumber'))
        if not matches(r'0x[a-fA-F0-9]{40}',row['address']) or not matches(r'0x[a-fA-F0-9]{64}',row['blockHash']) or not decimal(row['blockNumber']):raise ValueError('Receipt cursor identity is invalid')
        result.append({**row,'blockNumber':int(row['blockNumber'])})
    return result


def parse_receipt(raw):
    try:
        value=record(parse_json(raw),('completedAt','dashboardProjection','durationMs','finalizedAnchor','formatVersion',
            'gatewayConfigRevision','identities','kind','partial','rawJournal','reconciliationId','rpcRequests','runtimeConfigId','safeCursors','stateSnapshot'))
        if value['kind']!=KIND or type(value['formatVersion']) not in (int,float) or value['formatVersion']!=2 or value['partial'] is not False:raise ValueError('Receipt header is invalid')
        anchor=record(value['finalizedAnchor'],('hash','number'))
        if not matches(r'0x[a-fA-F0-9]{64}',anchor['hash']) or not decimal(anchor['number']):raise ValueError('Receipt anchor is invalid')
        identities=record(value['identities'],IDENTITIES)
        raw_journal=record(value['rawJournal'],('cursorCount','cursors','logCount','trackedAddressCount'))
        safe=record(value['safeCursors'],('configuredSafeCount','cursorCount','cursors','eventLogCount'))
        raw_cursors=stored_cursors(raw_journal['cursors']);safe_cursors=stored_cursors(safe['cursors'])
        dashboard=record(value['dashboardProjection'],('blockHash','blockNumber','cursorCount','eventLogCount','profile'))
        snapshot=record(value['stateSnapshot'],('blockHash','blockNumber','cursorCount','modelCount','profile'))
        for number,count in [(raw_journal['cursorCount'],len(raw_cursors)),(raw_journal['trackedAddressCount'],len(raw_cursors)),
            (safe['cursorCount'],len(safe_cursors)),(safe['configuredSafeCount'],len(safe_cursors)),(dashboard['cursorCount'],1),(snapshot['cursorCount'],1)]:
            if not safe_count(number) or number!=count:raise ValueError('Receipt cursor counts are invalid')
        rpc=record(value['rpcRequests'],('adaptiveRetryAttempts','byMethod','ethGetLogs','failedAttempts','totalAttempts'))
        record(rpc['byMethod'],METHODS);logs=record(rpc['ethGetLogs'],('adaptiveAttempts','addressScopedViemTransportRetries','attempts',
            'bySource','failedAttempts','legacyViemTransportRetriesObserved','plannedAttempts','plannedBySource'))
        record(logs['bySource'],SOURCES);record(logs['plannedBySource'],SOURCES)
        if type(logs['addressScopedViemTransportRetries']) not in (int,float) or logs['addressScopedViemTransportRetries']!=0:raise ValueError('Receipt RPC retry identity is invalid')
        completed=date_milliseconds(text(value['completedAt']))
        if not safe_count(completed) or iso_milliseconds(completed)!=value['completedAt']:raise ValueError('Receipt completion timestamp is invalid')
        for row,key in [(dashboard,'eventLogCount'),(snapshot,'modelCount')]:
            if not decimal(row['blockNumber']) or not decimal(row[key]):raise ValueError('Receipt decimal is invalid')
            text(row['blockHash']);text(row['profile'])
        return create_receipt({'reconciliationId':text(value['reconciliationId']),'gatewayConfigRevision':text(value['gatewayConfigRevision']),
            'runtimeConfigId':None if value['runtimeConfigId'] is None else text(value['runtimeConfigId']),
            'finalizedAnchor':{'blockNumber':int(anchor['number']),'blockHash':anchor['hash']},
            'identities':{key:text(item) for key,item in identities.items()},
            'rawJournal':{'trackedAddressCount':len(raw_cursors),'logCount':raw_journal['logCount'],'cursors':raw_cursors},
            'safeCursors':{'configuredSafeCount':len(safe_cursors),'eventLogCount':safe['eventLogCount'],'cursors':safe_cursors},
            'dashboardProjection':{**dashboard,'blockNumber':int(dashboard['blockNumber'])},
            'stateSnapshot':{**snapshot,'blockNumber':int(snapshot['blockNumber'])},'rpcRequests':rpc,
            'completedAtMs':int(completed),'durationMs':value['durationMs']})
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        raise ValueError('Stored reconciliation receipt is invalid') from None
