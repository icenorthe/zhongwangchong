@echo off
set "MOBILE_PORT=8000"
set "BRIDGE_PORT=9000"
set "TUNNEL_ENABLED=0"
set "TUNNEL_COMMAND=cloudflared tunnel --url http://127.0.0.1:%MOBILE_PORT%"
set "TUNNEL_PROCESS_NAME=cloudflared.exe"
