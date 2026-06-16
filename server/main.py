import os
import fcntl
import struct
import asyncio
import websockets
from core import create_tun, run_command

PORT = 8323

async def ws_to_tun(websocket, tun_fd):
    loop = asyncio.get_running_loop()
    try:
        async for packet in websocket:
            print(f"[WS -> TUN] Сервер получил пакет: {len(packet)} байт")
            try:
                await loop.run_in_executor(None, os.write, tun_fd, packet)
            except Exception as e:
                print(f"Ошибка записи в TUN сервера: {e}")
    except websockets.exceptions.ConnectionClosed:
        print("Соединение с клиентом закрыто (ws_to_tun)")

async def tun_to_ws(websocket, tun_fd):
    loop = asyncio.get_running_loop()
    while True:
        try:
            packet = await loop.run_in_executor(None, os.read, tun_fd, 2048)
            if packet:
                print(f"[TUN -> WS] Сервер отправляет пакет: {len(packet)} байт")
                await websocket.send(packet)
        except BlockingIOError:
            await asyncio.sleep(0.001)
        except websockets.exceptions.ConnectionClosed:
            print("Соединение с клиентом закрыто (tun_to_ws)")
            break
        except Exception as e:
            print(f"Ошибка чтения из TUN сервера: {e}")
            break

async def handler(websocket):
    path = websocket.request.path
    print(f"Попытка подключения на путь: {path} от {websocket.remote_address}")
    
    print("Соединение одобрено. Запуск двустороннего обмена.")
    
    await asyncio.gather(
        ws_to_tun(websocket=websocket, tun_fd=tun_fd_global),
        tun_to_ws(websocket=websocket, tun_fd=tun_fd_global)
    )
    print(f"Клиент {websocket.remote_address} отключился.")

async def main():
    global tun_fd_global
    try:
        tun_fd_global = create_tun(b"tun0")
        print("TUN интерфейс 'tun0' успешно создан на сервере.")
        await run_command(f"sudo ip addr add 10.0.0.1/24 dev tun0")
        await run_command(f"sudo ip link set up dev tun0")
        await run_command(f"sudo ip link set dev tun0 mtu 1400")
        await run_command(f"sudo iptables -P FORWARD ACCEPT")
        await run_command(f"sudo iptables -A FORWARD -i tun0 -o wlan0 -j ACCEPT")
        await run_command(f"sudo iptables -A FORWARD -i wlan0 -o tun0 -m state --state RELATED,ESTABLISHED -j ACCEPT")
        await run_command(f"sudo iptables -t nat -A POSTROUTING -o wlan0 -j MASQUERADE")
    except Exception as e:
        print(f"Не удалось создать TUN (запустите через sudo): {e}")
        return

    async with websockets.serve(handler, "localhost", PORT):
        print(f"WebSocket сервер запущен на ws://localhost:{PORT}. Можете открыть порт например через tailscale funnel")
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nСервер остановлен пользователем.")