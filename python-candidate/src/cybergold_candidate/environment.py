"""Existing setting names/kinds, using standard Pydantic and Web3 validation."""
import json
import os
from pathlib import Path
import re
from typing import Annotated

from pydantic import AnyUrl, BaseModel, ConfigDict, TypeAdapter, UrlConstraints, ValidationError, create_model, field_validator
from web3 import Web3

from .aliases import JS_WHITESPACE

CATALOG = json.loads(Path(__file__).with_name('environment-catalog.json').read_text())
SETTINGS = {item['name']:item for item in CATALOG}
HTTP_URL = TypeAdapter(Annotated[AnyUrl,UrlConstraints(allowed_schemes=['http','https'])])
DATABASE_URL = TypeAdapter(Annotated[AnyUrl,UrlConstraints(allowed_schemes=['postgres','postgresql'])])


class EnvironmentBase(BaseModel):
    model_config = ConfigDict(frozen=True,extra='ignore',validate_default=True,hide_input_in_errors=True)

    @field_validator('*',mode='before',check_fields=False)
    @classmethod
    def setting(cls,value,info):
        name = info.field_name
        definition = SETTINGS[name]
        kind = definition['kind']
        value = value.strip(JS_WHITESPACE) if isinstance(value,str) else value
        if value is None or value == '':
            if definition['required']:
                raise ValueError(name+' is required.')
            return None
        try:
            if not isinstance(value,str):
                raise ValueError()
            if kind in ('address','addresses'):
                addresses = value.split(',') if kind == 'addresses' else [value]
                normalized = []
                for address in addresses:
                    address = address.strip(JS_WHITESPACE)
                    if not re.fullmatch(r'0x[a-fA-F0-9]{40}',address):
                        raise ValueError()
                    normalized.append(Web3.to_checksum_address(address))
                return ','.join(normalized)
            if kind in ('url','database'):
                (HTTP_URL if kind=='url' else DATABASE_URL).validate_python(value)
            if kind in ('integer','positiveInteger'):
                if not re.fullmatch(r'[0-9]+',value) or int(value)>2**53-1 or (kind=='positiveInteger' and int(value)==0):
                    raise ValueError()
            if kind == 'flag' and value not in ('0','1'):
                raise ValueError()
            return value
        except (ValueError,TypeError):
            raise ValueError(name+' is not a valid '+kind+' setting.') from None


RuntimeSettings = create_model('RuntimeSettings',__base__=EnvironmentBase,
    **{item['name']:(str|None,None) for item in CATALOG})


def load_environment(values=None):
    try:
        return RuntimeSettings.model_validate(os.environ if values is None else values)
    except ValidationError as error:
        # Only the setting's established error, never credential values.
        raise ValueError(error.errors(include_input=False)[0]['msg'].removeprefix('Value error, ')) from None
