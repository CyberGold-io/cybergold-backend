# SPDX-License-Identifier: AGPL-3.0-only
"""Public version-specific source information; no runtime credentials or RPC."""
import json
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import JSONResponse

REPOSITORY = 'https://github.com/CyberGold-io/cybergold-backend'
OFFERS = json.loads(Path(__file__).with_name('source-offers.json').read_text())


def source_information(version):
    offer = next((item for item in OFFERS if item['version'] == version), None)
    return {
        'repository': REPOSITORY,
        'license': 'AGPL-3.0-only',
        'version': version,
        'downloadUrl': offer['downloadUrl'] if offer else
            REPOSITORY + '/archive/' + quote(version, safe='') + '.tar.gz' if version else None,
        'sha256': offer['sha256'] if offer else None,
    }


class SourceLinkMiddleware:
    """Append source discovery without consuming or buffering streaming bodies."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def forward(message):
            if message['type'] == 'http.response.start':
                message = {**message, 'headers': [*message.get('headers', []),
                    (b'link', b'</source>; rel="describedby"; title="Source code (AGPL-3.0)"')]}
            await send(message)
        await self.app(scope, receive, forward if scope['type'] == 'http' else send)


def install_source_offer(app, version):
    app.add_middleware(SourceLinkMiddleware)

    @app.api_route('/source', methods=['GET', 'HEAD'])
    async def source():
        information = source_information(version)
        headers = {'Cache-Control': 'no-store'}
        if information['downloadUrl']:
            headers['Link'] = '<' + information['downloadUrl'] + '>; rel="alternate"; title="Corresponding Source"'
        return JSONResponse(information, headers=headers)
