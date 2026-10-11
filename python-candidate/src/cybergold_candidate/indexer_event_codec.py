"""Retained strict raw and permissive legacy event views over the Web3 codec."""
from eth_utils.abi import collapse_if_tuple, event_abi_to_log_topic
from web3 import Web3

from .core_activity import wire_value
from .dashboard_builder import DEFINITIONS

CODEC = Web3().codec


def selector(definition):
    return Web3.to_hex(event_abi_to_log_topic(definition['abi']))


def arguments(abi, data, topics, *, strict):
    if not topics or topics[0] != Web3.to_hex(event_abi_to_log_topic(abi)):
        raise ValueError('Event signature does not match')
    values, missing = {}, []
    indexed = [parameter for parameter in abi['inputs'] if parameter.get('indexed', False)]
    for index, parameter in enumerate(indexed):
        topic = topics[index+1] if len(topics) > index+1 else None
        if not topic:
            if strict:
                raise ValueError('Missing indexed event argument')
            missing.append(parameter)
            continue
        if parameter['type'] in ('string', 'bytes', 'tuple') or parameter['type'].endswith(']'):
            values[parameter['name']] = topic
        else:
            decoded = CODEC.decode([collapse_if_tuple(parameter)], bytes.fromhex(topic[2:]))[0]
            values[parameter['name']] = wire_value(decoded, parameter)
    non_indexed = [parameter for parameter in abi['inputs'] if not parameter.get('indexed', False)]
    parameters = non_indexed if strict else [*missing, *non_indexed]
    if parameters:
        try:
            decoded = CODEC.decode([collapse_if_tuple(parameter) for parameter in parameters], bytes.fromhex(data[2:]))
            for parameter, value in zip(parameters, decoded, strict=True):
                values[parameter['name']] = wire_value(value, parameter)
        except Exception:
            if strict:
                raise
    return values or None


def decode_known(log, domain):
    topic = log['topics'][0].lower() if log['topics'] else None
    definition = next((definition for definition in DEFINITIONS[domain] if selector(definition).lower() == topic), None)
    if definition is None:
        return None
    try:
        return {'eventName': definition['name'], 'args': arguments(definition['abi'], log['data'], log['topics'], strict=True)}
    except Exception as error:
        raise ValueError('Failed to decode known ' + definition['name'] + ' raw log') from error


def decode_legacy(log, definition):
    if not log['topics'] or log['topics'][0] != selector(definition):
        return None
    try:
        args = arguments(definition['abi'], log['data'], log['topics'], strict=True)
    except Exception:
        try:
            args = arguments(definition['abi'], log['data'], log['topics'], strict=False)
        except Exception:
            args = {}
    return {'eventName': definition['name'], 'args': args}
