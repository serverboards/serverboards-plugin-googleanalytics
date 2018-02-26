import curio
import threading
from curio.thread import AsyncThread
from curio.workers import run_in_thread
import time

# A thread - standard python
def producer():
    print("Producer")
    time.sleep(1)
    print('Producer done')
    return "Done"

async def run_in_thread_in():
    at = AsyncThread(target=producer)
    await at.start()
    return (await at.join())


async def main():
    q = curio.UniversalQueue()
    res = await run_in_thread_in()
    print("?", res)


if __name__ == '__main__':
    curio.run(main)
