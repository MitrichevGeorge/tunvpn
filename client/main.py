import os
import fcntl
import struct
import asyncio
import websockets
import subprocess

TUNSETIFF = 0x400454ca
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000

def create_tun(name=b"tun0"):
    tun = os.open("/dev/net/tun", os.O_RDWR | os.O_NONBLOCK)
    ifr = struct.pack("16sH", name, IFF_TUN | IFF_NO_PI)
    fcntl.ioctl(tun, TUNSETIFF, ifr)
    return tun

async def tun_to_ws(websocket, tun_fd):
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

async def ws_to_tun(websocket, tun_fd):
    loop = asyncio.get_running_loop()
    try:
        async for packet in websocket:
            print(f"[WS -> TUN] Клиент получил пакет: {len(packet)} байт")
            try:
                await loop.run_in_executor(None, os.write, tun_fd, packet)
            except Exception as e:
                print(f"Ошибка записи в TUN клиента: {e}")
    except websockets.exceptions.ConnectionClosed:
        print("Соединение с сервером закрыто (ws_to_tun)")

async def runcmd(cmd):
    print(f"[bash] {cmd}")
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        print(f"[Ошибка] Команда '{cmd}' завершилась с кодом {process.returncode}")
        print(f"[След ошибки]: {stderr.decode().strip()}")

    return stdout.decode().strip()

async def main():
    global ip, ts
    try:
        tun_fd = create_tun(b"tun0")
        print("TUN интерфейс 'tun0' успешно создан на клиенте.")
        await runcmd("ip addr add 10.0.0.2/24 dev tun0")
        await runcmd("ip link set up dev tun0")
        await runcmd("ip link set dev tun0 mtu 1400")
        print("Getting router")
        ip = await runcmd("ip route show default | awk '{print $3}'")
        print("Getting tailscale")
        ts = await runcmd("getent hosts raspberrypi.taildfcdfd.ts.net | awk '{print $1}'")
        await runcmd(f"sudo ip route add {ts} via {ip}")
        await runcmd("sudo ip route del default")
        await runcmd("sudo ip route add default dev tun0")
    except Exception as e:
        print(f"Не удалось создать TUN (запустите через sudo): {e}")
        return

    uri = "wss://raspberrypi.taildfcdfd.ts.net/cc"
    print(f"Подключение к {uri}...")

    try:
        async with websockets.connect(uri) as websocket:
            print("Соединение установлено! Туннель активен.")
            await asyncio.gather(
                tun_to_ws(websocket=websocket, tun_fd=tun_fd),
                ws_to_tun(websocket=websocket, tun_fd=tun_fd)
            )
    except Exception as e:
        print(f"Ошибка подключения или работы сокета: {e}")

async def finish():
    #ip = await runcmd("ip route show default | awk '{print $3}'")
    #ts = await runcmd("getent hosts raspberrypi.taildfcdfd.ts.net | awk '{print $1}'")
    await runcmd("sudo ip route del default")
    await runcmd(f"sudo ip route add default via {ip} dev eth0")
    await runcmd(f"sudo ip route del {ts}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nКлиент остановлен пользователем.")
        asyncio.run(finish())