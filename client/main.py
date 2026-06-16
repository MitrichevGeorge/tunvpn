import os
import asyncio
import websockets
from websockets.asyncio.client import ClientConnection
from collections.abc import Buffer
from core import create_tun, run_command
from urllib.parse import urlparse

TUN_IP = "10.0.0.2/24"
TUN = "tun0"
DEV = "eth0"
URI = "wss://.....taildfcdfd.ts.net/...."

async def tun_to_ws(websocket: ClientConnection, tun_fd: int):
    loop = asyncio.get_running_loop()
    while True:
        try:
            packet = await loop.run_in_executor(None, os.read, tun_fd, 2048)
            if packet:
                print(f"[TUN -> WS] Клиент отправляет пакет: {len(packet)} байт")
                await websocket.send(packet)
        except BlockingIOError:
            await asyncio.sleep(0.001)
        except websockets.exceptions.ConnectionClosed:
            print("Соединение с сервером закрыто (tun_to_ws)")
            break
        except Exception as e:
            print(f"Ошибка чтения из TUN клиента: {e}")
            break

async def ws_to_tun(websocket: ClientConnection, tun_fd: int):
    loop = asyncio.get_running_loop()
    try:
        async for packet in websocket:
            print(f"[WS -> TUN] Клиент получил пакет: {len(packet)} байт")
            if not isinstance(packet, Buffer):
                raise ValueError
            try:
                await loop.run_in_executor(None, os.write, tun_fd, packet)
            except Exception as e:
                print(f"Ошибка записи в TUN клиента: {e}")
    except websockets.exceptions.ConnectionClosed:
        print("Соединение с сервером закрыто (ws_to_tun)")

async def main():
    global ip, ts
    try:
        ip = await run_command("ip route show default | awk '{print $3}'")
        ts = await run_command(f"getent hosts {urlparse(URI).netloc} | awk '{{print $1}}'")
        tun_fd = create_tun(TUN.encode())
        await run_command(f"ip addr add {TUN_IP} dev {TUN}")
        await run_command(f"ip link set up dev {TUN}")
        await run_command(f"ip link set dev {TUN} mtu 1400")
        await run_command(f"sudo ip route add {ts} via {ip}")
        await run_command(f"sudo ip route del default")
        await run_command(f"sudo ip route add default dev {TUN}")
        print(f"TUN интерфейс '{TUN}' успешно создан на клиенте.")
    except PermissionError:
        print("Запустите с sudo")
        return
    except Exception as e:
        print(f"Не удалось создать TUN: {e}")
        return

    print(f"Подключение к {URI}...")

    try:
        async with websockets.connect(URI) as websocket:
            print("Соединение установлено! Туннель активен.")
            await asyncio.gather(
                tun_to_ws(websocket=websocket, tun_fd=tun_fd),
                ws_to_tun(websocket=websocket, tun_fd=tun_fd)
            )
    except Exception as e:
        print(f"Ошибка подключения или работы сокета: {e}")

async def finish():
    await run_command("sudo ip route del default")
    await run_command(f"sudo ip route add default via {ip} dev {DEV}")
    await run_command(f"sudo ip route del {ts}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nКлиент остановлен пользователем.")
    finally:
        asyncio.run(finish())