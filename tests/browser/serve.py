import runtime
import os
import uvicorn
from app import main
from fastapi.responses import Response


@main.app.middleware('http')
async def worker_release(request, call_next):
    # Test-only release switch; the production application has no such hook.
    marker=runtime.root/'worker-version'
    if request.url.path=='/sw.js' and marker.exists():
        response=main.service_worker()
        return Response(response.body.decode().replace(main.APP_VERSION,marker.read_text().strip(),1),
                        media_type='application/javascript',headers={'Cache-Control':'no-cache','Service-Worker-Allowed':'/'})
    return await call_next(request)

async def browser_test_app(scope, receive, send):
    # Browser routing cannot reliably intercept requests controlled by a WebKit
    # service worker. Inject real HTTP/transport faults at this test-only boundary.
    marker = runtime.root / 'network-fault'
    mode = marker.read_text().strip() if marker.exists() else ''
    if scope['type'] != 'http' or scope['path'] != '/api/mobile/actions' or not mode:
        return await main.app(scope, receive, send)
    if mode == 'html':
        return await Response('<h1>Login</h1>', media_type='text/html')(scope, receive, send)
    if mode == 'unavailable':
        return await Response('Test server unavailable', status_code=503)(scope, receive, send)
    if mode != 'disconnect-after-commit':
        raise RuntimeError(f'Unknown browser test fault: {mode}')

    messages = []
    async def collect(message):
        messages.append(message)
    await main.app(scope, receive, collect)  # Includes the committed booking.
    start = next(message for message in messages if message['type'] == 'http.response.start')
    assert start['status'] == 200, 'The transport test requires a successful server commit'
    headers = [(key, value) for key, value in start['headers'] if key.lower() != b'content-length']
    await send({**start, 'headers': [*headers, (b'content-length', b'100')]})
    await send({'type': 'http.response.body', 'body': b'{', 'more_body': True})
    # Uvicorn closes the connection with an incomplete HTTP body, after commit.
    raise ConnectionResetError('Intentional browser test disconnect after server commit')


uvicorn.run(browser_test_app,host='127.0.0.1',port=int(os.environ.get('ERFASSUNG_E2E_PORT', '8765')))
