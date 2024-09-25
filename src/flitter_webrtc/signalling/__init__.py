
class Signalling:
    async def release(self):
        raise NotImplementedError()

    async def update(self, node):
        raise NotImplementedError()
