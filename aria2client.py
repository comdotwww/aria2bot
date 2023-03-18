import os
from pprint import pprint

import ujson
from aioaria2 import Aria2WebsocketClient

from util import getFileName, order_moov, imgCoverFromFile

from cachetools import TTLCache

SEND_ID = int(os.getenv('SEND_ID'))
# 是否上传到Telegram
UP_TELEGRAM = os.getenv('UP_TELEGRAM', 'False') == 'True'
# 上传Telegram完成后，是否删除该文件
IS_DELETED_AFTER_UPLOAD = os.getenv(
    'IS_DELETED_AFTER_UPLOAD', 'False') == 'True'
# 创建一个最大容量为 100 且过期时间为 600 秒的缓存对象
ttl_cache = TTLCache(maxsize=100, ttl=600)


class Aria2Client:
    rpc_url = ''
    rpc_token = ''
    bot = None
    client = None
    bot = None

    def __init__(self, rpc_url, rpc_token, bot):
        self.rpc_url = rpc_url
        self.rpc_token = rpc_token
        self.bot = bot

    async def init(self):
        self.client: Aria2WebsocketClient = await Aria2WebsocketClient.new(self.rpc_url, token=self.rpc_token,
                                                                           loads=ujson.loads,
                                                                           dumps=ujson.dumps, )

        # 先取消回调
        # self.client.unregister(self.on_download_start, "aria2.onDownloadStart")
        # self.client.unregister(self.on_download_pause, "aria2.onDownloadPause")
        # self.client.unregister(self.on_download_complete, "aria2.onDownloadComplete")
        # self.client.unregister(self.on_download_error, "aria2.onDownloadError")

    async def on_download_start(self, trigger, data):
        print(f"===========下载 开始 {data}")
        gid = data['params'][0]['gid']
        # 查询是否是绑定特征值的文件
        tellStatus = await self.client.tellStatus(gid)
        await self.bot.send_message(SEND_ID,
                                    f'{getFileName(tellStatus)} 任务已经开始下载... \n 对应路径: {tellStatus["dir"]}',
                                    parse_mode='html')

    async def on_download_pause(self, trigger, data):
        gid = data['params'][0]['gid']

        tellStatus = await self.client.tellStatus(gid)
        filename = getFileName(tellStatus)
        print('回调===>任务: ', filename, '暂停')
        # await bot.send_message(SEND_ID, filename + ' 任务已经成功暂停')

    async def on_download_complete(self, trigger, data):
        print(f"===========下载 完成 {data}")
        gid = data['params'][0]['gid']

        tellStatus = await self.client.tellStatus(gid)
        files = tellStatus['files']
        # 上传文件
        for file in files:
            path = file['path']
            await self.bot.send_message(SEND_ID,
                                        '下载完成===> ' + path,
                                        )
            # 发送文件下载成功的信息

            if UP_TELEGRAM:
                if '[METADATA]' in path:
                    os.unlink(path)
                    return
                print('开始上传,路径文件:' + path)
                msg = await self.bot.send_message(SEND_ID,
                                                  '上传中===> ' + path,
                                                  )

                # 最近一次上传进度
                # last_upload_rate = 0.0
                # 创建一个缓存项
                if ttl_cache.get(path) is None:
                    ttl_cache[path] = 0.0

                async def callback(current, total):
                    # 当前上传进度
                    upload_rate = round(current / total, 3)
                    last_upload_rate = ttl_cache.get(path)
                    # 不小于 0.5 变动刷新进度
                    if last_upload_rate is None or last_upload_rate == 0.0:
                        last_upload_rate = upload_rate
                        await self.bot.edit_message(msg, path + ' \n上传中 : {:.3%}'.format(upload_rate))
                    elif last_upload_rate >= 0.50 and upload_rate - last_upload_rate >= 0.50:
                        await self.bot.edit_message(msg, path + ' \n上传中 : {:.3%}'.format(upload_rate))
                        last_upload_rate = upload_rate
                    ttl_cache[path] = last_upload_rate
                    # print("\r", '正在发送', current, 'out of', total,
                    #       'bytes: {:.2%}'.format(current / total), end="", flush=True)
                    # if round(upload_rate % 0.50, 2) == 0:
                    #     await self.bot.edit_message(msg, path + ' \n上传中 : {:.2%}'.format(upload_rate))
                    # print(current / total)

                try:
                    # 单独处理mp4视频上传
                    if path.lower().endswith('.mp4'):

                        pat, filename = os.path.split(path)
                        await order_moov(path, pat + '/' + 'mo-' + filename)
                        # 截图
                        await imgCoverFromFile(path, pat + '/' + filename + '.jpg')
                        # 删除文件
                        if IS_DELETED_AFTER_UPLOAD:
                            os.unlink(path)
                            await self.bot.send_message(SEND_ID,
                                                        '文件已删除===> ' + path,
                                                        )
                        # 判断文件大小 2G=2*1024*1024*1024=2147483648 bytes
                        if os.path.getsize(pat + '/' + 'mo-' + filename) <= 2147483648:
                            await self.bot.send_file(SEND_ID,
                                                     pat + '/' + 'mo-' + filename,
                                                     thumb=pat + '/' + filename + '.jpg',
                                                     supports_streaming=True,
                                                     progress_callback=callback,
                                                     caption=filename,
                                                     # force_document=False
                                                     )
                        else:
                            await self.bot.send_message(SEND_ID,
                                                        '文件上传失败, 大小超过2GB===> ' + pat + '/' + 'mo-' + filename,
                                                        )
                        await msg.delete()

                        # 删除缓存中的数据
                        del ttl_cache[path]
                        # 删除文件
                        if IS_DELETED_AFTER_UPLOAD:
                            os.unlink(pat + '/' + filename + '.jpg')
                            os.unlink(pat + '/' + 'mo-' + filename)
                            await self.bot.send_message(SEND_ID,
                                                        '文件已删除===> ' + pat + '/' + filename + '.jpg',
                                                        )
                            await self.bot.send_message(SEND_ID,
                                                        '文件已删除===> ' + pat + '/' + 'mo-' + filename,
                                                        )
                    else:
                        pat, filename = os.path.split(path)
                        # 判断文件大小 2G=2*1024*1024*1024=2147483648 bytes
                        if os.path.getsize(path) <= 2147483648:
                            await self.bot.send_file(SEND_ID,
                                                     path,
                                                     progress_callback=callback,
                                                     caption=filename,
                                                     # force_document=True
                                                     )
                        else:
                            await self.bot.send_message(SEND_ID,
                                                        '文件上传失败, 大小超过2GB===> ' + path,
                                                        )
                        await msg.delete()
                        # 删除文件
                        if IS_DELETED_AFTER_UPLOAD:
                            os.unlink(path)
                            await self.bot.send_message(SEND_ID,
                                                        '文件已删除===> ' + path,
                                                        )

                except FileNotFoundError as e:
                    print('文件未找到')
                    await self.bot.send_message(SEND_ID,
                                                '文件未找到===> ' + path,
                                                )

    async def on_download_error(self, trigger, data):
        print(f"===========下载 错误 {data}")
        gid = data['params'][0]['gid']

        tellStatus = await self.client.tellStatus(gid)
        errorCode = tellStatus['errorCode']
        errorMessage = tellStatus['errorMessage']
        print('任务', gid, '错误码', errorCode, '错误信息：', errorMessage)
        if errorCode == '12':
            await self.bot.send_message(SEND_ID, ' 任务正在下载,请删除后再尝试')
        else:
            await self.bot.send_message(SEND_ID, errorMessage)

        pprint(tellStatus)
