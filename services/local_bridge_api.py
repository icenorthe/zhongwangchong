from __future__ import annotations 
 
import json 
import os 
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field

try:
    from services.project_paths import LOG_DIR
except ImportError:
    from project_paths import LOG_DIR
 
LOG_PATH = LOG_DIR / 'local_bridge.log' 
 
LOCAL_AUTOMATION_COMMAND = os.getenv('LOCAL_AUTOMATION_COMMAND', 'python services\\local_charge_runner.py') 
LOCAL_AUTOMATION_TIMEOUT = int(os.getenv('LOCAL_AUTOMATION_TIMEOUT', '120')) 
 
app = FastAPI(title='Local Charge Bridge', version='1.0.0') 
 
class StartPayload(BaseModel): 
    station_name: str = Field(default='', max_length=120) 
    device_code: str = Field(min_length=1, max_length=64) 
    socket_no: int = Field(ge=1, le=20) 
    amount_yuan: float = Field(gt=0, le=100) 
    remark: str = Field(default='', max_length=200) 
    client_order_id: int 
    pile_no: str = Field(default='') 
 
def write_log(message): 
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S') 
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open('a', encoding='utf-8') as f: 
        f.write(f'[{ts}] {message}\\n') 
 
def run_local_command(order): 
    input_text = json.dumps(order, ensure_ascii=False) 
    try: 
        result = subprocess.run(LOCAL_AUTOMATION_COMMAND, input=input_text, capture_output=True, text=True, timeout=LOCAL_AUTOMATION_TIMEOUT, shell=True) 
    except subprocess.TimeoutExpired: 
        return False, f'local automation timeout ({LOCAL_AUTOMATION_TIMEOUT}s)', '' 
    except Exception as err: 
        return False, f'local automation error: {err}', '' 
 
    stdout = (result.stdout or '').strip() 
    stderr = (result.stderr or '').strip() 
    if result.returncode != 0: 
        return False, f'exit={result.returncode}: {stderr or stdout}', '' 
    if not stdout: 
        return False, 'local automation returned empty output', ''
 
    try: 
        data = json.loads(stdout) 
    except Exception: 
        client_id = str(order.get('client_order_id', 'na')) 
        return True, stdout, f'local-{client_id}' 
 
    success = bool(data.get('success', False)) 
    message = str(data.get('message', '')) 
    client_id = str(order.get('client_order_id', 'na')) 
    fallback_order_id = f'local-{client_id}' 
    order_id = str(data.get('order_id', fallback_order_id)) 
    if not success: 
        return False, message or 'local automation reported failure', order_id 
    return True, message or 'local automation success', order_id 
 
@app.get('/health') 
def health(): 
    return {'ok': True, 'command': LOCAL_AUTOMATION_COMMAND, 'timeout': LOCAL_AUTOMATION_TIMEOUT} 
 
@app.post('/api/start-charge') 
def start_charge(payload: StartPayload): 
    data = payload.model_dump() 
    write_log(f'incoming order: {json.dumps(data, ensure_ascii=False)}') 
    ok, message, vendor_order_id = run_local_command(data) 
    response = {'success': ok, 'message': message, 'order_id': vendor_order_id} 
    write_log(f'result: {json.dumps(response, ensure_ascii=False)}') 
    return response 
 
if __name__ == '__main__': 
    import uvicorn 
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('LOCAL_BRIDGE_PORT', '9000')), reload=False)

