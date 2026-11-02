import runtime
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

uvicorn.run(main.app,host='127.0.0.1',port=8765)
